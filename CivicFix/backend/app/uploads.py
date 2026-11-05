"""Secure upload pipeline (CF-11): streaming size cap, magic-byte sniffing,
Pillow validation + re-encode (strips EXIF/GPS), random names, ClamAV hook."""
from __future__ import annotations

import io
import logging
import os
import secrets

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps

from .config import get_settings
from .security import safe_filename

log = logging.getLogger("civicfix.uploads")

MAX_PIXELS = 40_000_000  # decompression-bomb guard
ALLOWED_SIGNED = {
    b"\xff\xd8\xff": ("jpg", "image/jpeg"),
    b"\x89PNG\r\n\x1a\n": ("png", "image/png"),
    b"RIFF": ("webp", "image/webp"),  # checked further below
}


async def scan_upload(path: str) -> None:
    """Pluggable malware scan (CF-11). ClamAV when configured."""
    s = get_settings()
    if not s.clamav_host:
        log.debug("ClamAV not configured; upload scanning disabled")
        return
    try:
        import socket
        with socket.create_connection((s.clamav_host, s.clamav_port), timeout=5) as sock:
            sock.sendall(b"zINSTREAM\0")
            with open(path, "rb") as f:
                while chunk := f.read(8192):
                    sock.sendall(len(chunk).to_bytes(4, "big") + chunk)
            sock.sendall((0).to_bytes(4, "big"))
            verdict = sock.recv(4096).decode(errors="replace")
            if "OK" not in verdict:
                raise HTTPException(422, f"Upload rejected by scanner: {verdict[:80]}")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("ClamAV scan failed (%s); rejecting upload", e)
        raise HTTPException(503, "Upload scanning unavailable")


def sniff_image(head: bytes) -> tuple[str, str] | None:
    """Return (ext, mime) from magic bytes; None if not an allowed image."""
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


async def save_upload(file: UploadFile, dest_dir: str,
                      allowed_kinds: tuple[str, ...] = ("photo", "video", "audio", "document"),
                      kind: str = "photo") -> dict:
    """Stream upload to disk with early abort. For images: sniff + Pillow
    verify + re-encode (EXIF/GPS stripped). Returns evidence metadata."""
    s = get_settings()
    os.makedirs(dest_dir, exist_ok=True)

    # stream to temp file, aborting past the cap
    tmp = os.path.join(dest_dir, f".tmp_{secrets.token_hex(8)}")
    size = 0
    head = b""
    try:
        with open(tmp, "wb") as out:
            while chunk := await file.read(64 * 1024):
                size += len(chunk)
                if size > s.max_upload_bytes:
                    raise HTTPException(413, "File exceeds maximum upload size")
                if len(head) < 16:
                    head += chunk[: 16 - len(head)]
                out.write(chunk)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    sniffed = sniff_image(head)
    is_image = sniffed is not None
    client_mime = (file.content_type or "").lower()

    final_ext = "bin"
    final_mime = "application/octet-stream"
    out_name = None

    if is_image:
        ext, final_mime = sniffed
        try:
            img = Image.open(tmp)
            img.verify()
            img = Image.open(tmp)
            if img.width * img.height > MAX_PIXELS:
                raise HTTPException(422, "Image too large (pixel count)")
            img = ImageOps.exif_transpose(img)
            # re-encode -> strips ALL metadata incl. EXIF GPS (CF-11)
            buf = io.BytesIO()
            fmt = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP"}[ext]
            if fmt == "JPEG":
                img.convert("RGB").save(buf, fmt, quality=88)
            else:
                img.save(buf, fmt)
            out_name = f"{secrets.token_hex(12)}.{ext}"
            final_path = os.path.join(dest_dir, out_name)
            with open(final_path, "wb") as f:
                f.write(buf.getvalue())
            size = len(buf.getvalue())
            os.unlink(tmp)
        except HTTPException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise HTTPException(422, "File is not a valid image")
        final_ext = ext
    else:
        # non-image: allow only explicit safe document/audio/video mimes
        allowed_nonimage = {
            "video/mp4": "mp4", "audio/webm": "webm", "audio/ogg": "ogg",
            "audio/mpeg": "mp3", "audio/wav": "wav", "application/pdf": "pdf",
        }
        if client_mime not in allowed_nonimage:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise HTTPException(415, "Unsupported file type")
        final_ext = allowed_nonimage[client_mime]
        final_mime = client_mime
        out_name = f"{secrets.token_hex(12)}.{final_ext}"
        os.rename(tmp, os.path.join(dest_dir, out_name))

    final_path = os.path.join(dest_dir, out_name)
    await scan_upload(final_path)
    return {
        "file_path": os.path.relpath(final_path, s.media_path),
        "original_name": safe_filename(file.filename or out_name),
        "mime_type": final_mime,
        "size_bytes": size,
        "server_ext": final_ext,
    }
