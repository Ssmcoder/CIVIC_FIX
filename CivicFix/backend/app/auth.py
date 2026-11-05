"""Admin auth: JWT (access+refresh), sessions, lockout, jurisdiction."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .database import get_db
from .models import Admin, AdminSession, AuditLog, Jurisdiction
from .security import (
    DUMMY_HASH, client_ip, decrypt_secret, encrypt_secret, hash_password,
    ip_hash, needs_rehash, verify_password,
)

bearer = HTTPBearer(auto_error=False)
REFRESH_COOKIE = "cfx_refresh"


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------- JWT

def _jwt_encode(payload: dict, ttl_minutes: int, jti: str, typ: str) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    claims = {
        "iss": s.jwt_issuer, "aud": s.jwt_audience,
        "iat": now, "exp": now + timedelta(minutes=ttl_minutes),
        "jti": jti, "type": typ, **payload,
    }
    return jwt.encode(claims, s.secret_key, algorithm="HS256")


def create_access_token(admin: Admin, session_jti: str) -> str:
    return _jwt_encode({"sub": admin.id, "role": admin.role,
                        "jid": admin.jurisdiction_id, "sid": session_jti},
                       get_settings().access_token_expire_minutes, session_jti, "access")


def create_refresh_token(admin: Admin, session: AdminSession) -> str:
    return _jwt_encode({"sub": admin.id, "sid": session.id},
                       int(get_settings().refresh_token_absolute_days * 24 * 60),
                       session.id, "refresh")


async def _session_valid(db: AsyncSession, sid: str) -> AdminSession | None:
    res = await db.execute(select(AdminSession).where(AdminSession.id == sid))
    sess = res.scalar_one_or_none()
    if sess is None or sess.revoked:
        return None
    now = utcnow()
    if now > sess.idle_expires_at or now > sess.absolute_expires_at:
        sess.revoked = True
        await db.commit()
        return None
    return sess


async def get_current_admin(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> Admin:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing token",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(creds.credentials, get_settings().secret_key,
                             algorithms=["HS256"], issuer=get_settings().jwt_issuer,
                             audience=get_settings().jwt_audience)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token type")
    sess = await _session_valid(db, payload.get("sid", ""))
    if sess is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or revoked")
    res = await db.execute(select(Admin).where(Admin.id == payload["sub"], Admin.is_active == True))  # noqa: E712
    admin = res.scalar_one_or_none()
    if admin is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin not found or inactive")
    if admin.must_change_password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Password change required")
    sess.last_used_at = utcnow()
    await db.commit()
    return admin


# ------------------------------------------------------------- sessions

async def create_session(db: AsyncSession, admin: Admin, request: Request) -> tuple[AdminSession, str]:
    s = get_settings()
    now = utcnow()
    sess = AdminSession(
        admin_id=admin.id, family_id=uuid.uuid4().hex,
        refresh_hash="", user_agent=(request.headers.get("user-agent") or "")[:300],
        ip_hash=ip_hash(client_ip(request.scope)),
        idle_expires_at=now + timedelta(hours=s.refresh_token_idle_hours),
        absolute_expires_at=now + timedelta(days=s.refresh_token_absolute_days),
    )
    db.add(sess)
    await db.flush()
    refresh = create_refresh_token(admin, sess)
    # store hash of refresh token
    import hashlib
    sess.refresh_hash = hashlib.sha256(refresh.encode()).hexdigest()
    await db.commit()
    return sess, refresh


def set_refresh_cookie(response: Response, refresh: str) -> None:
    s = get_settings()
    secure = s.is_production
    response.set_cookie(
        REFRESH_COOKIE, refresh, max_age=s.refresh_token_absolute_days * 86400,
        httponly=True, secure=secure, samesite="strict", path="/auth")


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path="/auth")


async def revoke_session(db: AsyncSession, session: AdminSession) -> None:
    session.revoked = True
    await db.commit()


async def revoke_all_sessions(db: AsyncSession, admin_id: str) -> None:
    res = await db.execute(select(AdminSession).where(
        AdminSession.admin_id == admin_id, AdminSession.revoked == False))  # noqa: E712
    for s in res.scalars().all():
        s.revoked = True
    await db.commit()


# ------------------------------------------------------------- lockout

LOCK_AFTER = 5
BASE_LOCK_MIN = 15


async def register_login_failure(db: AsyncSession, admin: Admin, request: Request) -> None:
    admin.failed_attempts = (admin.failed_attempts or 0) + 1
    if admin.failed_attempts >= LOCK_AFTER:
        # exponential backoff on repeat lockouts
        backoff = BASE_LOCK_MIN * (2 ** min(admin.lock_count or 0, 4))
        admin.locked_until = utcnow() + timedelta(minutes=backoff)
        admin.lock_count = (admin.lock_count or 0) + 1
        admin.failed_attempts = 0
        db.add(AuditLog(admin_id=admin.id, action="admin.lockout",
                        entity_type="admin", entity_id=admin.id,
                        detail=f"locked {backoff}m after repeated failures",
                        ip_hash=ip_hash(client_ip(request.scope))))
    await db.commit()


async def register_login_success(db: AsyncSession, admin: Admin) -> None:
    admin.failed_attempts = 0
    admin.lock_count = 0
    admin.locked_until = None
    admin.last_login_at = utcnow()
    await db.commit()


def is_locked(admin: Admin) -> bool:
    return admin.locked_until is not None and admin.locked_until > utcnow()


# ------------------------------------------------------------- password/MFA

async def change_password(db: AsyncSession, admin: Admin, new_password: str) -> None:
    from .security import validate_password_policy
    errs = validate_password_policy(new_password, admin.username)
    if errs:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "; ".join(errs))
    admin.password_hash = hash_password(new_password)
    admin.must_change_password = False
    await revoke_all_sessions(db, admin.id)
    await db.commit()


def totp_secret_for(admin: Admin) -> str | None:
    return decrypt_secret(admin.totp_secret) if admin.totp_secret else None


def set_totp_secret(admin: Admin, secret: str) -> None:
    admin.totp_secret = encrypt_secret(secret)


# ------------------------------------------------------------- jurisdiction

async def jurisdiction_chain(db: AsyncSession, admin: Admin) -> set[str]:
    if admin.role == "super_admin":
        res = await db.execute(select(Jurisdiction.id))
        return {r[0] for r in res.all()}
    if not admin.jurisdiction_id:
        return set()
    allowed = {admin.jurisdiction_id}
    frontier = [admin.jurisdiction_id]
    all_j = list((await db.execute(select(Jurisdiction))).scalars().all())
    children = {}
    for j in all_j:
        children.setdefault(j.parent_id, []).append(j.id)
    while frontier:
        cur = frontier.pop()
        for ch in children.get(cur, []):
            if ch not in allowed:
                allowed.add(ch)
                frontier.append(ch)
    return allowed


def in_jurisdiction(admin_jids: set[str], *jids: str | None) -> bool:
    present = [j for j in jids if j]
    if not present:
        return False
    return any(j in admin_jids for j in present)


async def assert_can_access_complaint(db: AsyncSession, admin: Admin, complaint) -> None:
    if admin.role == "super_admin":
        return
    jids = await jurisdiction_chain(db, admin)
    if not in_jurisdiction(jids, complaint.ward_id, complaint.municipality_id, complaint.district_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Complaint not found")  # 404 not 403 (CF-09)


async def assert_can_access_incident(db: AsyncSession, admin: Admin, incident) -> None:
    if admin.role == "super_admin":
        return
    jids = await jurisdiction_chain(db, admin)
    if in_jurisdiction(jids, incident.ward_id):
        return
    from .models import Complaint, IncidentReport
    res = await db.execute(
        select(Complaint.ward_id, Complaint.municipality_id, Complaint.district_id)
        .join(IncidentReport, IncidentReport.complaint_id == Complaint.id)
        .where(IncidentReport.incident_id == incident.id))
    if not any(in_jurisdiction(jids, *r) for r in res.all()):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Incident not found")
