"""Admin portal endpoints — auth, sessions, MFA, workflow, aggregates."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..auth import (
    REFRESH_COOKIE, assert_can_access_complaint, change_password,
    clear_refresh_cookie, create_access_token, create_session, get_current_admin,
    hash_password, in_jurisdiction, is_locked, jurisdiction_chain,
    register_login_failure, register_login_success, revoke_all_sessions,
    revoke_session, set_refresh_cookie, set_totp_secret, totp_secret_for,
    utcnow, _session_valid,
)
from ..config import get_settings
from ..database import get_db
from ..errors import error_envelope
from ..models import (
    Admin, AdminSession, Assignment, AuditLog, ChatMessage, Complaint, Department,
    Evidence, Incident, IncidentReport, Jurisdiction, MlFeedback, MlModel,
    MlRetrainJob, Notification, PriorityConfig, SlaRecord, SlaRule, StatusHistory,
)
from ..ratelimit import check as rl_check, limited
from ..schemas import (
    AdminCreate, AdminLogin, AssignRequest, CategoryCorrect, ChangePassword,
    ComplaintPatch, MfaConfirm, MfaDisable, ResolveRequest,
)
from ..security import (
    DUMMY_HASH, client_ip, generate_backup_codes, generate_totp_secret,
    hash_backup_code, ip_hash, needs_rehash, provisioning_uri,
    validate_password_policy, verify_password, verify_totp,
)
from ..services import pipeline, priority as prio_svc
from ..taxonomy import CATEGORIES, CATEGORIES_ORDERED, ROLES, STATUSES
from ..workflow import (
    CLOSE_ROLES, DEPT_PLUS, PRIORITY_OVERRIDE_ROLES, allowed_actions_for,
    can_transition,
)

router = APIRouter(prefix="/admin", tags=["admin"])
auth_router = APIRouter(prefix="/auth", tags=["auth"])


def _admin_out(a: Admin) -> dict:
    return {"id": a.id, "email": a.email, "username": a.username,
            "full_name": a.full_name, "role": a.role,
            "jurisdiction_id": a.jurisdiction_id, "mfa_enabled": a.mfa_enabled,
            "must_change_password": a.must_change_password}


# ------------------------------------------------------------------ login

@auth_router.post("/login")
async def login(body: AdminLogin, request: Request, response: Response,
                db: AsyncSession = Depends(get_db)):
    s = get_settings()
    ok, retry = rl_check(request, "login_ip", s.rl_login_ip_per_min, 60)
    if not ok:
        return limited(retry)
    ok2, retry2 = rl_check(request, "login_user", s.rl_login_user_per_min, 60,
                           identity=body.username.lower())
    if not ok2:
        return limited(retry2)

    res = await db.execute(select(Admin).where(
        (Admin.username == body.username) | (Admin.email == body.username)))
    admin = res.scalar_one_or_none()
    pw_ok = verify_password(body.password,
                            admin.password_hash if admin else DUMMY_HASH)
    generic = HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")

    if admin is None or not pw_ok:
        if admin is not None and admin.is_active:
            await register_login_failure(db, admin, request)
        raise generic
    if not admin.is_active or is_locked(admin):
        raise generic  # identical response for locked/disabled (CF-15)
    if needs_rehash(admin.password_hash):
        admin.password_hash = hash_password(body.password)

    # MFA
    if admin.mfa_enabled:
        secret = totp_secret_for(admin)
        totp_ok = verify_totp(secret, body.totp_code or "") if secret else False
        # backup codes
        if not totp_ok:
            codes = json.loads(admin.backup_codes or "[]")
            h = hash_backup_code(body.totp_code or "")
            if h in codes:
                codes.remove(h)
                admin.backup_codes = json.dumps(codes)
                totp_ok = True
        if not totp_ok:
            await register_login_failure(db, admin, request)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "mfa_required")

    await register_login_success(db, admin)
    sess, refresh = await create_session(db, admin, request)
    set_refresh_cookie(response, refresh)
    access = create_access_token(admin, sess.id)
    db.add(AuditLog(admin_id=admin.id, action="admin.login", entity_type="admin",
                    entity_id=admin.id, ip_hash=ip_hash(client_ip(request.scope))))
    await db.commit()
    return {"access_token": access, "token_type": "bearer",
            "expires_in": s.access_token_expire_minutes, "admin": _admin_out(admin)}


@auth_router.post("/refresh")
async def refresh(request: Request, response: Response,
                  db: AsyncSession = Depends(get_db)):
    """Rotate refresh token; reuse detection revokes the family (CF-15)."""
    s = get_settings()
    # Origin check (cookie is SameSite=Strict; belt & braces)
    origin = request.headers.get("origin", "")
    allowed = {o.strip() for o in s.cors_origins.split(",")}
    if origin and origin not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "bad_origin")
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no_refresh_cookie")
    try:
        import jwt as pyjwt
        payload = pyjwt.decode(token, s.secret_key, algorithms=["HS256"],
                               issuer=s.jwt_issuer, audience=s.jwt_audience)
    except Exception:  # noqa: BLE001
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_refresh")
    if payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong_type")
    sess = await _session_valid(db, payload.get("sid", ""))
    if sess is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session_revoked")
    # rotation: presented token must match stored hash
    h = hashlib.sha256(token.encode()).hexdigest()
    now = utcnow()
    if sess.rotated_at is not None or not _ct_eq(sess.refresh_hash, h):
        # reuse of an old rotated token -> revoke whole family
        await db.execute(select(AdminSession).where(AdminSession.family_id == sess.family_id))
        fam = (await db.execute(select(AdminSession).where(
            AdminSession.family_id == sess.family_id))).scalars().all()
        for f in fam:
            f.revoked = True
        await db.commit()
        clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh_reuse_detected")
    admin = await db.get(Admin, sess.admin_id)
    if admin is None or not admin.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "admin_inactive")
    # rotate
    sess.rotated_at = now
    sess.last_used_at = now
    sess.idle_expires_at = now + timedelta(hours=s.refresh_token_idle_hours)
    new_refresh = _new_refresh(admin, sess)
    sess.refresh_hash = hashlib.sha256(new_refresh.encode()).hexdigest()
    await db.commit()
    set_refresh_cookie(response, new_refresh)
    return {"access_token": create_access_token(admin, sess.id),
            "token_type": "bearer", "expires_in": s.access_token_expire_minutes}


def _ct_eq(a: str, b: str) -> bool:
    import secrets as _s
    return _s.compare_digest(a or "", b or "")


def _new_refresh(admin: Admin, sess: AdminSession) -> str:
    from ..auth import create_refresh_token
    return create_refresh_token(admin, sess)


@auth_router.post("/logout")
async def logout(request: Request, response: Response,
                 db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        import jwt as pyjwt
        try:
            payload = pyjwt.decode(token, get_settings().secret_key,
                                   algorithms=["HS256"], issuer=get_settings().jwt_issuer,
                                   audience=get_settings().jwt_audience)
            sess = await db.get(AdminSession, payload.get("sid", ""))
            if sess:
                await revoke_session(db, sess)
        except Exception:  # noqa: BLE001
            pass
    clear_refresh_cookie(response)
    return {"ok": True}


@auth_router.post("/logout-all")
async def logout_all(request: Request, response: Response,
                     admin: Admin = Depends(get_current_admin),
                     db: AsyncSession = Depends(get_db)):
    await revoke_all_sessions(db, admin.id)
    clear_refresh_cookie(response)
    return {"ok": True}


# ------------------------------------------------------------------- MFA

@router.post("/mfa/enroll")
async def mfa_enroll(admin: Admin = Depends(get_current_admin),
                     db: AsyncSession = Depends(get_db)):
    if admin.mfa_enabled:
        raise HTTPException(409, "MFA already enabled")
    secret = generate_totp_secret()
    set_totp_secret(admin, secret)  # stored encrypted, not yet confirmed
    await db.commit()
    uri = provisioning_uri(secret, admin.username)
    return {"secret": secret, "provisioning_uri": uri}


@router.post("/mfa/confirm")
async def mfa_confirm(body: MfaConfirm, admin: Admin = Depends(get_current_admin),
                      db: AsyncSession = Depends(get_db)):
    secret = totp_secret_for(admin)
    if not secret or not verify_totp(secret, body.code):
        raise HTTPException(400, "invalid_code")
    plain, hashed = generate_backup_codes(10)
    admin.backup_codes = json.dumps(hashed)
    admin.mfa_enabled = True
    db.add(AuditLog(admin_id=admin.id, action="mfa.enable", entity_type="admin",
                    entity_id=admin.id))
    await db.commit()
    return {"ok": True, "backup_codes": plain,
            "warning": "Store these backup codes safely — they are shown once."}


@router.post("/mfa/disable")
async def mfa_disable(body: MfaDisable, admin: Admin = Depends(get_current_admin),
                      db: AsyncSession = Depends(get_db)):
    if not verify_password(body.password, admin.password_hash):
        raise HTTPException(403, "bad_password")
    secret = totp_secret_for(admin)
    if not secret or not verify_totp(secret, body.totp_code):
        raise HTTPException(403, "bad_totp")
    if admin.role in get_settings().mfa_roles:
        raise HTTPException(403, "MFA is mandatory for your role")
    admin.mfa_enabled = False
    admin.totp_secret = None
    admin.backup_codes = "[]"
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- sessions

@router.get("/sessions")
async def list_sessions(admin: Admin = Depends(get_current_admin),
                        db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(AdminSession).where(
        AdminSession.admin_id == admin.id, AdminSession.revoked == False))  # noqa: E712
    return [{"id": s.id, "user_agent": s.user_agent, "ip_hash": s.ip_hash[:8] + "…",
             "created_at": s.created_at.isoformat() if s.created_at else None,
             "last_used_at": s.last_used_at.isoformat() if s.last_used_at else None,
             "idle_expires_at": s.idle_expires_at.isoformat() if s.idle_expires_at else None}
            for s in res.scalars().all()]


@router.delete("/sessions/{sid}")
async def delete_session(sid: str, admin: Admin = Depends(get_current_admin),
                         db: AsyncSession = Depends(get_db)):
    sess = await db.get(AdminSession, sid)
    if sess is None or sess.admin_id != admin.id:
        raise HTTPException(404, "Session not found")
    await revoke_session(db, sess)
    return {"ok": True}


@router.post("/change-password")
async def pw_change(body: ChangePassword, admin: Admin = Depends(get_current_admin),
                    db: AsyncSession = Depends(get_db)):
    if not verify_password(body.current_password, admin.password_hash):
        raise HTTPException(403, "bad_password")
    await change_password(db, admin, body.new_password)
    return {"ok": True}


# ------------------------------------------------------------------ misc

@router.post("/admins", status_code=status.HTTP_201_CREATED)
async def create_admin(body: AdminCreate, admin: Admin = Depends(get_current_admin),
                       db: AsyncSession = Depends(get_db)):
    if admin.role != "super_admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only super admin can create admins")
    if body.role not in ROLES:
        raise HTTPException(400, "Invalid role")
    errs = validate_password_policy(body.password, body.username)
    if errs:
        raise HTTPException(422, "; ".join(errs))
    exists = await db.execute(select(Admin).where(
        (Admin.username == body.username) | (Admin.email == body.email)))
    if exists.scalar_one_or_none():
        raise HTTPException(409, "Username/email already exists")
    a = Admin(email=body.email, username=body.username,
              password_hash=hash_password(body.password), full_name=body.full_name,
              role=body.role, jurisdiction_id=body.jurisdiction_id,
              must_change_password=True)
    db.add(a)
    await db.commit()
    await db.refresh(a)
    db.add(AuditLog(admin_id=admin.id, action="admin.create", entity_type="admin",
                    entity_id=a.id, detail=json.dumps({"username": a.username, "role": a.role})))
    await db.commit()
    return _admin_out(a)


@router.get("/me")
async def me(admin: Admin = Depends(get_current_admin)):
    return _admin_out(admin)


# ------------------------------------------------------------- jurisdiction

async def _scoped_complaints(db: AsyncSession, admin: Admin):
    if admin.role == "super_admin":
        return select(Complaint)
    jids = await jurisdiction_chain(db, admin)
    if not jids:
        return select(Complaint).where(Complaint.id == "__none__")
    return select(Complaint).where(
        Complaint.ward_id.in_(jids) | Complaint.municipality_id.in_(jids) |
        Complaint.district_id.in_(jids))


async def _scoped_incidents(db: AsyncSession, admin: Admin):
    if admin.role == "super_admin":
        return select(Incident)
    jids = await jurisdiction_chain(db, admin)
    if not jids:
        return select(Incident).where(Incident.id == "__none__")
    sub = (await _scoped_complaints(db, admin)
           .with_only_columns(Complaint.incident_id)
           .where(Complaint.incident_id.isnot(None)))
    return select(Incident).where(Incident.ward_id.in_(jids) | Incident.id.in_(sub))


# ---------------------------------------------------------- aggregates (CF cross-cutting)

@router.get("/dashboard/summary")
async def dash_summary(admin: Admin = Depends(get_current_admin),
                       db: AsyncSession = Depends(get_db),
                       **_):
    base = await _scoped_complaints(db, admin)
    res = await db.execute(base)
    cs = list(res.scalars().all())
    now = utcnow()
    total = len(cs)
    awaiting = sum(1 for c in cs if c.status == "awaiting_verification")
    resolved = sum(1 for c in cs if c.status in ("resolved", "closed"))
    breached = sum(1 for c in cs if c.sla_breached or
                   (c.sla_deadline and c.sla_deadline < now and
                    c.status not in ("resolved", "closed", "awaiting_verification")))
    by_status = {}
    for c in cs:
        by_status[c.status] = by_status.get(c.status, 0) + 1
    return {"total": total, "awaiting_verification": awaiting, "resolved": resolved,
            "sla_breaches": breached, "by_status": by_status}


@router.get("/dashboard/by-status")
async def dash_by_status(admin: Admin = Depends(get_current_admin),
                         db: AsyncSession = Depends(get_db)):
    return (await dash_summary(admin, db))["by_status"]


@router.get("/dashboard/by-ward")
async def dash_by_ward(admin: Admin = Depends(get_current_admin),
                       db: AsyncSession = Depends(get_db)):
    base = await _scoped_complaints(db, admin)
    res = await db.execute(base)
    counts: dict[str, int] = {}
    for c in res.scalars().all():
        if c.ward_id:
            w = await db.get(Jurisdiction, c.ward_id)
            name = w.name if w else c.ward_id
            counts[name] = counts.get(name, 0) + 1
    return {"wards": [{"ward": k, "count": v} for k, v in
                      sorted(counts.items(), key=lambda x: -x[1])]}


@router.get("/dashboard/timeseries")
async def dash_timeseries(admin: Admin = Depends(get_current_admin),
                          db: AsyncSession = Depends(get_db),
                          days: int = 30):
    base = await _scoped_complaints(db, admin)
    cutoff = utcnow() - timedelta(days=min(days, 365))
    res = await db.execute(base.where(Complaint.created_at >= cutoff))
    buckets: dict[str, dict] = {}
    for c in res.scalars().all():
        day = (c.created_at or utcnow()).strftime("%Y-%m-%d")
        b = buckets.setdefault(day, {"date": day, "received": 0, "resolved": 0})
        b["received"] += 1
        if c.resolved_at and c.resolved_at >= cutoff:
            rd = c.resolved_at.strftime("%Y-%m-%d")
            buckets.setdefault(rd, {"date": rd, "received": 0, "resolved": 0})
            buckets[rd]["resolved"] += 1
    return {"series": [buckets[k] for k in sorted(buckets)]}


@router.get("/dashboard/funnel")
async def dash_funnel(admin: Admin = Depends(get_current_admin),
                      db: AsyncSession = Depends(get_db)):
    base = await _scoped_complaints(db, admin)
    res = await db.execute(base)
    stages = ["received", "under_review", "inspection_scheduled", "in_progress",
              "awaiting_verification", "closed"]
    counts = {s: 0 for s in stages}
    for c in res.scalars().all():
        for s in stages:
            if c.status == s or (s == "closed" and c.status == "resolved"):
                counts[s] += 1
                break
        else:
            counts["received"] += 0
    # cumulative funnel
    order = ["received", "under_review", "inspection_scheduled", "in_progress",
             "awaiting_verification", "closed"]
    rank = {s: i for i, s in enumerate(order)}
    out = []
    cs = list((await db.execute(base)).scalars().all())
    for s in order:
        n = sum(1 for c in cs if rank.get(c.status if c.status in rank else "received", 0) >= rank[s]
                or (s == "closed" and c.status in ("resolved", "closed")))
        out.append({"stage": s, "count": n})
    return {"funnel": out}


@router.get("/dashboard")
async def dashboard(admin: Admin = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    return await dash_summary(admin, db)


# --------------------------------------------------------------- complaints

@router.get("/complaints")
async def list_complaints(
    admin: Admin = Depends(get_current_admin), db: AsyncSession = Depends(get_db),
    status_filter: str | None = None, category: str | None = None,
    priority_band: str | None = None, ward_id: str | None = None,
    department_id: str | None = None, q: str | None = None,
    overdue: bool | None = None, sort: str = "created_at",
    page: int = 1, page_size: int = 25,
):
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)
    base = await _scoped_complaints(db, admin)
    qy = base.options(selectinload(Complaint.evidence))
    if status_filter:
        qy = qy.where(Complaint.status == status_filter)
    if category:
        qy = qy.where(Complaint.category == category)
    if priority_band:
        qy = qy.where(Complaint.priority_band == priority_band)
    if ward_id:
        qy = qy.where(Complaint.ward_id == ward_id)
    if department_id:
        qy = qy.where(Complaint.department_id == department_id)
    if q:
        qy = qy.where((Complaint.public_id.ilike(f"%{q}%")) |
                      (Complaint.description.ilike(f"%{q}%")))
    if overdue:
        qy = qy.where(Complaint.sla_deadline < utcnow(),
                      Complaint.status.notin_(["resolved", "closed", "awaiting_verification"]))
    sort_col = Complaint.priority_score if sort == "priority" else Complaint.created_at
    qy = qy.order_by(sort_col.desc() if sort == "priority" else sort_col.desc())
    total = (await db.execute(select(func.count()).select_from(qy.subquery()))).scalar() or 0
    res = await db.execute(qy.offset((page - 1) * page_size).limit(page_size))
    items = [await _admin_complaint_out(db, c, admin) for c in res.scalars().all()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


async def _admin_complaint_out(db: AsyncSession, c: Complaint, admin: Admin | None = None) -> dict:
    dept_name = None
    if c.department_id:
        d = await db.get(Department, c.department_id)
        dept_name = d.name if d else None
    ward = await db.get(Jurisdiction, c.ward_id) if c.ward_id else None
    dist = await db.get(Jurisdiction, c.district_id) if c.district_id else None
    hist = (await db.execute(select(StatusHistory).where(StatusHistory.complaint_id == c.id)
                           .order_by(StatusHistory.created_at))).scalars().all()
    ev = (await db.execute(select(Evidence).where(Evidence.complaint_id == c.id))).scalars().all()
    inc = await db.get(Incident, c.incident_id) if c.incident_id else None
    members = []
    if inc:
        mres = await db.execute(
            select(Complaint.public_id, Complaint.description, IncidentReport.link_type)
            .join(IncidentReport, IncidentReport.complaint_id == Complaint.id)
            .where(IncidentReport.incident_id == inc.id))
        members = [{"public_id": r[0], "description": (r[1] or "")[:160],
                    "link_type": r[2]} for r in mres.all()]
    has_res_ev = any(e.is_resolution for e in ev)
    out = {
        "id": c.id, "public_id": c.public_id, "status": c.status,
        "category": c.category, "category_label": CATEGORIES.get(c.category, c.category),
        "issue_type": c.issue_type, "ai_category": c.ai_category,
        "ai_confidence": c.ai_confidence, "ai_explanation": c.ai_explanation,
        "category_confirmed": c.category_confirmed,
        "description": c.description, "transcript": c.transcript, "language": c.language,
        "source": c.source, "severity": c.severity, "severity_score": c.severity_score,
        "safety_risk": c.safety_risk, "priority_score": c.priority_score,
        "priority_band": c.priority_band,
        "priority_factors": json.loads(c.priority_factors or "{}"),
        "priority_override_reason": c.priority_override_reason,
        "sla_deadline": c.sla_deadline.isoformat() if c.sla_deadline else None,
        "sla_breached": c.sla_breached, "department_id": c.department_id,
        "department": dept_name,
        "location": {"lat": c.lat, "lon": c.lon, "landmark": c.landmark_text,
                     "confidence": c.location_confidence, "verified": c.location_verified,
                     "ward": ward.name if ward else None,
                     "district": dist.name if dist else None},
        "contact_phone": c.contact_phone, "contact_email": c.contact_email,
        "anonymous": c.anonymous,
        "review_reason": c.review_reason,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
        "incident_id": c.incident_id,
        "incident": {"id": inc.id, "title": inc.title, "status": inc.status,
                     "citizens_affected": inc.citizens_affected,
                     "priority_band": inc.priority_band} if inc else None,
        "incident_members": members,
        "status_history": [{"from": h.from_status, "to": h.to_status, "actor": h.actor_type,
                            "note": h.note, "at": h.created_at.isoformat() if h.created_at else None}
                           for h in hist],
        "evidence": [{"id": e.id, "kind": e.kind, "name": e.original_name,
                      "mime": e.mime_type, "size": e.size_bytes, "caption": e.caption,
                      "is_resolution": e.is_resolution, "uploader_type": e.uploader_type,
                      "marked_by": e.marked_by,
                      "created_at": e.created_at.isoformat() if e.created_at else None}
                     for e in ev],
    }
    if admin is not None:
        out["allowed_actions"] = allowed_actions_for(
            c.status, admin.role, has_resolution_evidence=has_res_ev)
    return out


async def _get_scoped_complaint(db: AsyncSession, admin: Admin, cid: str) -> Complaint:
    res = await db.execute(select(Complaint).where(
        (Complaint.id == cid) | (Complaint.public_id == cid)))
    c = res.scalar_one_or_none()
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Complaint not found")
    await assert_can_access_complaint(db, admin, c)
    return c


@router.get("/complaints/{complaint_id}")
async def get_complaint(complaint_id: str, admin: Admin = Depends(get_current_admin),
                        db: AsyncSession = Depends(get_db)):
    c = await _get_scoped_complaint(db, admin, complaint_id)
    return await _admin_complaint_out(db, c, admin)


@router.patch("/complaints/{complaint_id}")
async def patch_complaint(complaint_id: str, body: ComplaintPatch,
                          admin: Admin = Depends(get_current_admin),
                          db: AsyncSession = Depends(get_db)):
    """Workflow-enforced transition (CF-09): row lock, role gate, evidence gate."""
    res = await db.execute(select(Complaint).where(
        (Complaint.id == complaint_id) | (Complaint.public_id == complaint_id))
        .with_for_update())
    c = res.scalar_one_or_none()
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Complaint not found")
    await assert_can_access_complaint(db, admin, c)
    changes = {}

    if body.status:
        target = body.status
        if not can_transition(c.status, target, admin.role):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f"Transition {c.status} -> {target} not permitted for {admin.role}")
        if target == "awaiting_verification":
            ev = (await db.execute(select(Evidence).where(
                Evidence.complaint_id == c.id, Evidence.is_resolution == True))).scalars().all()  # noqa: E712
            if not ev:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    "Resolution evidence required before awaiting_verification")
        if target == "closed":
            if admin.role not in CLOSE_ROLES:
                raise HTTPException(status.HTTP_403_FORBIDDEN,
                                    "Only department-level admins can close; ward officers cannot")
            if not body.close_reason:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    "close_reason required for admin close")
        old = c.status
        c.status = target
        if target == "closed":
            c.resolved_at = c.resolved_at or utcnow()
        db.add(StatusHistory(complaint_id=c.id, incident_id=c.incident_id,
                             from_status=old, to_status=target, actor_type="admin",
                             actor_id=admin.id,
                             note=body.note or body.close_reason or ""))
        changes["status"] = {"from": old, "to": target}

    if body.category:
        if body.category not in CATEGORIES_ORDERED:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid category")
        old = c.category
        c.category = body.category
        c.category_confirmed = True
        changes["category"] = {"from": old, "to": body.category}
        db.add(MlFeedback(kind="category_correction", complaint_id=c.id,
                          input_text=(c.transcript or c.description)[:1000],
                          predicted_label=old, confirmed_label=body.category,
                          confidence=c.ai_confidence, model_version="admin"))

    if body.priority_override_score is not None:
        if admin.role not in PRIORITY_OVERRIDE_ROLES:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Priority override requires department-level role")
        if not body.override_reason:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "override_reason required")
        c.priority_score = body.priority_override_score
        c.priority_band = prio_svc.band_for(body.priority_override_score)
        c.priority_override_reason = body.override_reason
        changes["priority_override"] = {"score": body.priority_override_score,
                                        "reason": body.override_reason}

    db.add(AuditLog(admin_id=admin.id, action="complaint.update", entity_type="complaint",
                    entity_id=c.id, detail=json.dumps(changes)))
    if c.incident_id:
        await _derive_incident(db, c.incident_id)
    await db.commit()
    return {"ok": True, "changes": changes}


async def _derive_incident(db: AsyncSession, incident_id: str):
    from ..routers.complaints import _derive_incident_status
    await _derive_incident_status(db, incident_id)


@router.post("/complaints/{complaint_id}/assign")
async def assign_complaint(complaint_id: str, body: AssignRequest,
                           admin: Admin = Depends(get_current_admin),
                           db: AsyncSession = Depends(get_db)):
    c = await _get_scoped_complaint(db, admin, complaint_id)
    dept = await db.get(Department, body.department_id)
    if dept is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Department not found")
    c.department_id = dept.id
    db.add(Assignment(complaint_id=c.id, incident_id=c.incident_id,
                      department_id=dept.id, assigned_by=admin.id, note=body.note))
    if c.status == "received":
        c.status = "under_review"
    db.add(StatusHistory(complaint_id=c.id, incident_id=c.incident_id,
                         from_status="", to_status=c.status, actor_type="admin",
                         actor_id=admin.id, note=f"Assigned to {dept.name}: {body.note}"))
    db.add(AuditLog(admin_id=admin.id, action="complaint.assign", entity_type="complaint",
                    entity_id=c.id, detail=json.dumps({"department": dept.name})))
    await db.commit()
    return {"ok": True, "department": dept.name}


@router.post("/complaints/{complaint_id}/resolve")
async def resolve_complaint(complaint_id: str, body: ResolveRequest,
                            admin: Admin = Depends(get_current_admin),
                            db: AsyncSession = Depends(get_db)):
    """CF-04: evidence_ids scoped to THIS complaint; resolution flag admin-only."""
    c = await _get_scoped_complaint(db, admin, complaint_id)
    # transition gate: only dept+ can submit resolution
    if admin.role not in DEPT_PLUS and c.status not in ("in_progress", "inspection_scheduled"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot submit resolution")
    invalid = []
    marked = []
    if body.evidence_ids:
        res = await db.execute(select(Evidence).where(
            Evidence.id.in_(body.evidence_ids), Evidence.complaint_id == c.id))
        found = {e.id: e for e in res.scalars().all()}
        for eid in body.evidence_ids:
            if eid not in found:
                invalid.append(eid)
            else:
                e = found[eid]
                e.is_resolution = True
                e.marked_by = admin.id
                e.marked_at = utcnow()
                marked.append(e)
        if invalid:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"Evidence IDs not belonging to this complaint: {invalid}")
    res_evs = (await db.execute(select(Evidence).where(
        Evidence.complaint_id == c.id, Evidence.is_resolution == True))).scalars().all()  # noqa: E712
    if not res_evs:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Resolution requires at least one admin-flagged resolution evidence item")
    old = c.status
    c.status = "awaiting_verification"
    c.resolved_at = utcnow()
    c.sla_breached = c.sla_breached or bool(c.sla_deadline and c.sla_deadline < c.resolved_at)
    db.add(StatusHistory(complaint_id=c.id, incident_id=c.incident_id,
                         from_status=old, to_status=c.status, actor_type="admin",
                         actor_id=admin.id, note=body.note or "Resolution submitted with evidence"))
    db.add(AuditLog(admin_id=admin.id, action="complaint.resolve", entity_type="complaint",
                    entity_id=c.id,
                    detail=json.dumps({"evidence": [e.id for e in res_evs], "note": body.note})))
    await db.commit()
    return {"ok": True, "status": c.status, "awaiting": "citizen verification"}


# ---------------------------------------------------------------- incidents

@router.get("/incidents")
async def list_incidents(admin: Admin = Depends(get_current_admin),
                         db: AsyncSession = Depends(get_db),
                         status_filter: str | None = None, priority_band: str | None = None,
                         page: int = 1, page_size: int = 25):
    page_size = min(max(page_size, 1), 100)
    base = await _scoped_incidents(db, admin)
    q = base.order_by(Incident.priority_score.desc(), Incident.created_at.desc())
    if status_filter:
        q = q.where(Incident.status == status_filter)
    if priority_band:
        q = q.where(Incident.priority_band == priority_band)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    res = await db.execute(q.offset((max(page, 1) - 1) * page_size).limit(page_size))
    items = [{"id": i.id, "title": i.title, "category": i.category, "status": i.status,
              "priority_band": i.priority_band, "priority_score": i.priority_score,
              "citizens_affected": i.citizens_affected,
              "sla_deadline": i.sla_deadline.isoformat() if i.sla_deadline else None,
              "lat": i.lat, "lon": i.lon,
              "created_at": i.created_at.isoformat() if i.created_at else None}
             for i in res.scalars().all()]
    return {"total": total, "items": items}


@router.get("/map")
async def map_data(admin: Admin = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    res = await db.execute(await _scoped_incidents(db, admin))
    return {"points": [{"id": i.id, "lat": i.lat, "lon": i.lon, "status": i.status,
                        "priority_band": i.priority_band, "category": i.category,
                        "citizens_affected": i.citizens_affected, "title": i.title}
                       for i in res.scalars().all() if i.lat is not None]}


# ------------------------------------------------------------ departments etc

@router.get("/departments")
async def departments(admin: Admin = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Department))
    return [{"id": d.id, "name": d.name, "description": d.description,
             "category_map": json.loads(d.category_map or "{}")} for d in res.scalars().all()]


@router.get("/jurisdictions")
async def jurisdictions(admin: Admin = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    jids = await jurisdiction_chain(db, admin)
    res = await db.execute(select(Jurisdiction).where(Jurisdiction.id.in_(jids)))
    return [{"id": j.id, "level": j.level, "name": j.name, "parent_id": j.parent_id}
            for j in res.scalars().all()]


@router.get("/sla-rules")
async def sla_rules(admin: Admin = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(SlaRule))
    return [{"id": r.id, "category": r.category, "priority_band": r.priority_band,
             "deadline_hours": r.deadline_hours, "escalation_hours": r.escalation_hours}
            for r in res.scalars().all()]


@router.get("/priority-config")
async def priority_config(admin: Admin = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(PriorityConfig))
    return {r.key: {"value": r.value, "description": r.description} for r in res.scalars().all()}


@router.put("/priority-config/{key}")
async def set_priority_config(key: str, value: float,
                              admin: Admin = Depends(get_current_admin),
                              db: AsyncSession = Depends(get_db)):
    if admin.role != "super_admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Super admin only")
    if not (0 <= value <= 1):
        raise HTTPException(422, "weight must be 0..1")
    res = await db.execute(select(PriorityConfig).where(PriorityConfig.key == key))
    pc = res.scalar_one_or_none()
    if pc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown config key")
    old = pc.value
    pc.value = value
    db.add(AuditLog(admin_id=admin.id, action="config.priority", entity_type="priority_config",
                    entity_id=key, detail=json.dumps({"from": old, "to": value})))
    await db.commit()
    return {"ok": True, "key": key, "value": value}


# ------------------------------------------------------------------ ML

@router.get("/ml/metrics")
async def ml_metrics(admin: Admin = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(MlModel).order_by(MlModel.created_at.desc()))
    models = [{"id": m.id, "name": m.name, "version": m.version,
               "metrics": json.loads(m.metrics or "{}"), "is_active": m.is_active,
               "created_at": m.created_at.isoformat() if m.created_at else None}
              for m in res.scalars().all()]
    fb = await db.execute(select(MlFeedback.kind, func.count()).group_by(MlFeedback.kind))
    conf_res = await db.execute(select(Complaint.ai_confidence).where(Complaint.ai_confidence.isnot(None)))
    confs = [c for (c,) in conf_res.all() if c is not None]
    low = sum(1 for c in confs if c < get_settings().classify_review_threshold)
    return {"models": models,
            "active_model": next((m for m in models if m["is_active"]), None),
            "feedback_counts": {k: n for k, n in fb.all()},
            "predictions_logged": len(confs), "low_confidence_count": low,
            "low_confidence_rate": round(low / len(confs), 3) if confs else 0.0}


_RETRAIN_LOCK = False


@router.post("/ml/retrain")
async def ml_retrain(admin: Admin = Depends(get_current_admin),
                     db: AsyncSession = Depends(get_db)):
    """CF-16: gated, super-admin only, background job record."""
    s = get_settings()
    if not s.enable_ml_retrain:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "ML retraining is disabled")
    if admin.role != "super_admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Super admin only")
    global _RETRAIN_LOCK
    if _RETRAIN_LOCK:
        raise HTTPException(status.HTTP_409_CONFLICT, "A retrain job is already running")
    job = MlRetrainJob(admin_id=admin.id, status="queued")
    db.add(job)
    await db.commit()
    await db.refresh(job)
    import asyncio
    _RETRAIN_LOCK = True

    async def runner():
        global _RETRAIN_LOCK
        try:
            job.status = "running"
            await db.commit()
            from pathlib import Path
            import sys, os
            ml_dir = Path(__file__).resolve().parents[3] / "ml"
            script = ml_dir / "train.py"
            if not script.exists():
                job.status = "failed"
                job.log_tail = "ml/train.py not found"
                await db.commit()
                return
            env = dict(os.environ)
            env["DATABASE_URL"] = s.database_url
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(script), "--register",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=str(ml_dir), env=env)
            job.pid = proc.pid
            out, err = await asyncio.wait_for(proc.communicate(), timeout=600)
            job.log_tail = (out or b"").decode(errors="replace")[-2000:]
            job.status = "done" if proc.returncode == 0 else "failed"
            for line in (out or b"").decode(errors="replace").splitlines():
                if line.startswith("METRICS_JSON:"):
                    job.metrics = line.split(":", 1)[1][:4000]
            if proc.returncode != 0:
                log_tail_err = (err or b"").decode(errors="replace")[-1000:]
                job.log_tail += "\nSTDERR:" + log_tail_err  # server-side log only
        except Exception as e:  # noqa: BLE001
            job.status = "failed"
            job.log_tail = f"job error: {type(e).__name__}"
        finally:
            job.finished_at = utcnow()
            _RETRAIN_LOCK = False
            try:
                await db.commit()
            except Exception:  # noqa: BLE001
                pass

    asyncio.create_task(runner())
    return {"job_id": job.id, "status": "queued"}


@router.get("/ml/retrain/{job_id}")
async def ml_retrain_status(job_id: str, admin: Admin = Depends(get_current_admin),
                            db: AsyncSession = Depends(get_db)):
    job = await db.get(MlRetrainJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return {"id": job.id, "status": job.status, "metrics": json.loads(job.metrics or "{}"),
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None}


# ------------------------------------------------------------- notifications (CF-10)

@router.get("/notifications")
async def notifications(admin: Admin = Depends(get_current_admin),
                        db: AsyncSession = Depends(get_db)):
    """Jurisdiction-scoped, minimal fields (CF-10)."""
    jids = await jurisdiction_chain(db, admin)
    res = await db.execute(select(Notification).order_by(Notification.created_at.desc()).limit(50))
    out = []
    for n in res.scalars().all():
        if n.complaint_id:
            c = await db.get(Complaint, n.complaint_id)
            if c is not None:
                await assert_can_access_complaint(db, admin, c)
                # only minimal fields
                out.append({"id": n.id, "kind": n.kind, "read": n.read,
                            "complaint_public_id": c.public_id,
                            "category": c.category,
                            "created_at": n.created_at.isoformat() if n.created_at else None})
                continue
        out.append({"id": n.id, "kind": n.kind, "read": n.read, "title": n.title,
                    "created_at": n.created_at.isoformat() if n.created_at else None})
    return out


# ------------------------------------------------------------------- audit

@router.get("/audit")
async def audit_log(admin: Admin = Depends(get_current_admin),
                    db: AsyncSession = Depends(get_db),
                    page: int = 1, page_size: int = 50):
    if admin.role != "super_admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Super admin only")
    page_size = min(max(page_size, 1), 100)
    q = select(AuditLog).order_by(AuditLog.created_at.desc())
    total = (await db.execute(select(func.count()).select_from(AuditLog))).scalar() or 0
    res = await db.execute(q.offset((max(page, 1) - 1) * page_size).limit(page_size))
    return {"total": total, "items": [{
        "id": a.id, "admin_id": a.admin_id, "action": a.action,
        "entity_type": a.entity_type, "entity_id": a.entity_id,
        "detail": a.detail, "created_at": a.created_at.isoformat() if a.created_at else None}
        for a in res.scalars().all()]}


# keep old name for backwards compat inside module
_admin_out = _admin_out
