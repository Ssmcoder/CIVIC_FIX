"""Admin auth: JWT + password hashing + jurisdiction resolution."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .database import get_db
from .models import Admin, Jurisdiction

bearer = HTTPBearer(auto_error=False)


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:  # noqa: BLE001
        return False


def create_token(admin: Admin) -> str:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(minutes=s.access_token_expire_minutes)
    payload = {"sub": admin.id, "role": admin.role, "jid": admin.jurisdiction_id, "exp": exp}
    return jwt.encode(payload, s.secret_key, algorithm="HS256")


async def get_current_admin(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> Admin:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing token")
    try:
        payload = jwt.decode(creds.credentials, get_settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    res = await db.execute(select(Admin).where(Admin.id == payload["sub"], Admin.is_active == True))  # noqa: E712
    admin = res.scalar_one_or_none()
    if admin is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin not found or inactive")
    return admin


async def jurisdiction_chain(db: AsyncSession, admin: Admin) -> set[str]:
    """Return set of jurisdiction ids the admin can see (own + descendants)."""
    if admin.role == "super_admin":
        res = await db.execute(select(Jurisdiction.id))
        return {r[0] for r in res.all()}
    if not admin.jurisdiction_id:
        return set()
    # collect descendants
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
    """A record is visible if ANY of its jurisdiction ids is in scope.
    Records with no jurisdiction are visible only to super_admin."""
    present = [j for j in jids if j]
    if not present:
        return False
    return any(j in admin_jids for j in present)


async def assert_can_access_complaint(db: AsyncSession, admin: Admin, complaint) -> None:
    if admin.role == "super_admin":
        return
    jids = await jurisdiction_chain(db, admin)
    if not in_jurisdiction(jids, complaint.ward_id, complaint.municipality_id, complaint.district_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Outside your jurisdiction")


async def assert_can_access_incident(db: AsyncSession, admin: Admin, incident) -> None:
    if admin.role == "super_admin":
        return
    jids = await jurisdiction_chain(db, admin)
    if not in_jurisdiction(jids, incident.ward_id):
        # fall back to member complaints' jurisdictions
        from .models import Complaint, IncidentReport
        res = await db.execute(
            select(Complaint.ward_id, Complaint.municipality_id, Complaint.district_id)
            .join(IncidentReport, IncidentReport.complaint_id == Complaint.id)
            .where(IncidentReport.incident_id == incident.id))
        rows = res.all()
        if not any(in_jurisdiction(jids, *r) for r in rows):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Outside your jurisdiction")
