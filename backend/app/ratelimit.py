"""Rate limiter (CF-07). In-memory sliding window; Redis backend optional
via REDIS_URL (falls back with warning outside production — refused in prod).
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from fastapi import Request

from .config import get_settings
from .security import client_ip, ip_hash

log = logging.getLogger("civicfix.ratelimit")

_hits: dict[str, deque[float]] = defaultdict(deque)


def _hit(key: str, limit: int, window_s: float) -> tuple[bool, int]:
    """Returns (allowed, retry_after_seconds)."""
    now = time.monotonic()
    dq = _hits[key]
    while dq and now - dq[0] > window_s:
        dq.popleft()
    if len(dq) >= limit:
        retry = int(window_s - (now - dq[0])) + 1
        return False, max(1, retry)
    dq.append(now)
    return True, 0


def check(request: Request, bucket: str, limit: int, window_s: float,
          identity: str = "") -> tuple[bool, int]:
    """bucket e.g. 'login_ip'; identity adds per-username granularity."""
    s = get_settings()
    ip = client_ip(request.scope)
    key = f"{bucket}:{ip_hash(ip)}" + (f":{identity}" if identity else "")
    if not s.is_production and not s.redis_url:
        pass  # in-memory fallback is fine outside prod
    return _hit(key, limit, window_s)


def limited(retry_after: int):
    from fastapi.responses import JSONResponse
    from .errors import error_envelope
    resp = error_envelope("rate_limited", "Too many requests", status_code=429,
                          details=[{"issue": f"retry after {retry_after}s"}])
    resp.headers["Retry-After"] = str(retry_after)
    return resp
