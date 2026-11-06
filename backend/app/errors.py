"""Standard error envelope + request-id + security headers middleware (CF-19/CF-20)."""
from __future__ import annotations

import logging
import re
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

log = logging.getLogger("civicfix")

REDACT_KEYS = re.compile(r"(password|secret|token|authorization|tracking|totp|api[_-]?key)", re.I)


def error_envelope(code: str, message: str, request_id: str = "",
                   details: list | None = None, status_code: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={
        "error": {"code": code, "message": message, "request_id": request_id,
                  "details": details or []}})


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(self), camera=(self), microphone=(self)"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


class BodySizeMiddleware(BaseHTTPMiddleware):
    """Reject oversized JSON bodies early (upload routes exempt)."""
    MAX_JSON = 1_000_000

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH") and "multipart" not in (
                request.headers.get("content-type") or ""):
            cl = request.headers.get("content-length")
            if cl and cl.isdigit() and int(cl) > self.MAX_JSON:
                return error_envelope("payload_too_large", "Request body too large",
                                      getattr(request.state, "request_id", ""),
                                      status_code=413)
        return await call_next(request)


class RedactingFilter(logging.Filter):
    """Redact secrets from log records (CF-13)."""
    PAT = re.compile(
        r"(?i)(authorization['\"]?\s*[:=]\s*['\"]?)[^\s,'\"]+|"
        r"(password|secret|token|tracking|totp|api[_-]?key)(['\"]?\s*[:=]\s*['\"]?)[^\s,'\"}]+")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            record.msg = self.PAT.sub(lambda m: (m.group(1) or m.group(2) or "") +
                                      (m.group(3) or "") + "***", msg)
            record.args = ()
        except Exception:  # noqa: BLE001
            pass
        return True


def install_redaction() -> None:
    f = RedactingFilter()
    for name in ("civicfix", "uvicorn", "uvicorn.access", "uvicorn.error", "app"):
        logging.getLogger(name).addFilter(f)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exc(request: Request, exc: StarletteHTTPException):
        rid = getattr(request.state, "request_id", "")
        code = {
            400: "bad_request", 401: "unauthorized", 403: "forbidden",
            404: "not_found", 405: "method_not_allowed", 409: "conflict",
            413: "payload_too_large", 415: "unsupported_media_type",
            422: "validation_error", 429: "rate_limited",
        }.get(exc.status_code, "http_error")
        details = exc.headers and [{"issue": exc.detail}] or None
        return error_envelope(code, str(exc.detail)[:300], rid,
                              details=details, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exc(request: Request, exc: RequestValidationError):
        rid = getattr(request.state, "request_id", "")
        details = [{"field": ".".join(str(p) for p in e["loc"]), "issue": e["msg"]}
                   for e in exc.errors()[:20]]
        return error_envelope("validation_error", "Request validation failed",
                              rid, details=details, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        rid = getattr(request.state, "request_id", "")
        log.exception("Unhandled error rid=%s path=%s", rid, request.url.path)
        return error_envelope("internal_error", "An unexpected error occurred",
                              rid, status_code=500)
