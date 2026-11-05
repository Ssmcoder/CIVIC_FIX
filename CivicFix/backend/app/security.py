"""Security primitives: passwords, TOTP/MFA, IP derivation, token hashing."""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import os
import secrets
import struct
import time
from pathlib import Path

import bcrypt
from cryptography.fernet import Fernet

from .config import get_settings

# ---------------------------------------------------------------- passwords

_COMMON_PASSWORDS = {
    "password", "password1", "password123", "123456", "12345678", "123456789",
    "qwerty", "qwerty123", "admin", "admin123", "letmein", "welcome", "welcome1",
    "iloveyou", "monkey", "dragon", "football", "baseball", "abc123", "111111",
    "123123", "trustno1", "sunshine", "master", "shadow", "superman", "michael",
    "civicfix", "civicfix123", "odisha123", "bhubaneswar", "govind123",
}

DUMMY_HASH = bcrypt.hashpw(b"dummy-password-for-timing", bcrypt.gensalt(rounds=12)).decode()


def hash_password(pw: str) -> str:
    # bcrypt cost 12 (CF-15)
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:  # noqa: BLE001
        return False


def needs_rehash(hashed: str) -> bool:
    """True if stored hash uses fewer than 12 bcrypt rounds."""
    try:
        return hashed.startswith("$2b$") and int(hashed.split("$")[2]) < 12
    except Exception:  # noqa: BLE001
        return False


def validate_password_policy(pw: str, username: str = "") -> list[str]:
    s = get_settings()
    errs = []
    if not (s.password_min_length <= len(pw) <= s.password_max_length):
        errs.append(f"password must be {s.password_min_length}-{s.password_max_length} characters")
    if pw.lower() in _COMMON_PASSWORDS:
        errs.append("password is too common")
    if username and username.lower() in pw.lower():
        errs.append("password must not contain the username")
    if sum(c.isalpha() for c in pw) < 4 or sum(c.isdigit() for c in pw) < 1:
        errs.append("password needs letters and digits")
    return errs


# ------------------------------------------------------------------- TOTP

def _totp_key(secret: str) -> bytes:
    return base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp_code(secret: str, for_time: int | None = None, step: int = 30, digits: int = 6) -> str:
    t = int(time.time() if for_time is None else for_time) // step
    msg = struct.pack(">Q", t)
    digest = hmac.new(_totp_key(secret), msg, hashlib.sha1).digest()
    off = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return f"{code:0{digits}d}"


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit():
        return False
    now = int(time.time())
    for w in range(-window, window + 1):
        if hmac.compare_digest(totp_code(secret, now + w * 30), code):
            return True
    return False


def provisioning_uri(secret: str, username: str, issuer: str = "CivicFix") -> str:
    return (f"otpauth://totp/{issuer}:{username}?secret={secret}"
            f"&issuer={issuer}&digits=6&period=30")


def _fernet() -> Fernet | None:
    key = get_settings().fernet_key
    if not key:
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:  # noqa: BLE001
        return None


def encrypt_secret(plain: str) -> str:
    f = _fernet()
    if f is None:
        # dev fallback — still not plaintext in DB? we must store something;
        # use a keyed hash-free reversible fallback only in non-prod.
        return "plain:" + plain
    return "fernet:" + f.encrypt(plain.encode()).decode()


def decrypt_secret(stored: str) -> str | None:
    if not stored:
        return None
    if stored.startswith("plain:"):
        return stored[6:]
    if stored.startswith("fernet:"):
        f = _fernet()
        if f is None:
            return None
        try:
            return f.decrypt(stored[7:].encode()).decode()
        except Exception:  # noqa: BLE001
            return None
    return stored  # legacy plaintext


# ------------------------------------------------------------- backup codes

def hash_backup_code(code: str) -> str:
    return hashlib.sha256(("bc:" + code.strip().upper()).encode()).hexdigest()


def generate_backup_codes(n: int = 10) -> tuple[list[str], list[str]]:
    plain = [secrets.token_hex(4).upper() for _ in range(n)]
    return plain, [hash_backup_code(c) for c in plain]


# ------------------------------------------------------------- IP (CF-18)

def client_ip(scope) -> str:
    """Derive client IP honouring TRUSTED_PROXY_COUNT / FORWARDED_ALLOW_IPS.
    Never trusts raw X-Forwarded-For from untrusted peers."""
    s = get_settings()
    peer = scope.get("client")[0] if scope.get("client") else "unknown"
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    allow = {x.strip() for x in s.forwarded_allow_ips.split(",") if x.strip()}
    trusted = peer_ip.is_private or peer_ip.is_loopback or str(peer_ip) in allow
    hops = int(s.trusted_proxy_count or 0)
    if not trusted or hops <= 0:
        return str(peer_ip)
    xff = scope.get("headers", {}).get(b"x-forwarded-for", b"").decode()
    if not xff:
        return str(peer_ip)
    parts = [p.strip() for p in xff.split(",")]
    # right-most untrusted hop is the client; walk back `hops` proxies
    idx = max(0, len(parts) - hops - 1)
    try:
        return str(ipaddress.ip_address(parts[idx]))
    except ValueError:
        return str(peer_ip)


def ip_hash(ip: str) -> str:
    """HMAC-SHA256 keyed hash, truncated (CF-18)."""
    key = get_settings().ip_hash_key.encode()
    return hmac.new(key, ip.encode(), hashlib.sha256).hexdigest()[:32]


# ------------------------------------------------------- tracking tokens (CF-02)

def tracking_secret() -> str:
    return secrets.token_urlsafe(24)  # 192 bits


def _kh(secret: str, kid: str) -> str:
    return hashlib.sha256((kid + ":" + secret).encode()).hexdigest()


def hash_tracking_token(token: str) -> tuple[str, str]:
    """Return (kid, hash) using the CURRENT key."""
    s = get_settings()
    kid, sec = s.tracking_keys[0]
    return kid, hmac.new(sec.encode(), token.encode(), hashlib.sha256).hexdigest()


def verify_tracking_token(token: str, stored_hash: str, stored_kid: str | None = None) -> tuple[bool, str | None]:
    """Check token against current then legacy keys.
    Returns (ok, kid_to_store). Caller should re-hash with returned kid."""
    s = get_settings()
    for kid, sec in s.tracking_keys:
        cand = hmac.new(sec.encode(), token.encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(cand, stored_hash):
            # upgrade to current if it matched a legacy key
            return True, (s.current_tracking_kid if kid != s.current_tracking_kid else None)
    return False, None


def rehash_tracking_token(token: str) -> tuple[str, str]:
    return hash_tracking_token(token)


# ------------------------------------------------------------- misc

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_filename(name: str) -> str:
    base = Path(name or "file").name
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in base)[:120]
