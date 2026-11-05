"""Admin portal endpoints. Every endpoint enforces auth + jurisdiction server-side."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..auth import (
    assert_can_access_complaint, assert_can_access_incident, create_token,
    get_current_admin, hash_password, in_jurisdiction, jurisdiction_chain,
    verify_password,
)
from ..config import get_settings
from ..database import get_db
from ..models import (
    Admin, Assignment, AuditLog, ChatMessage, Complaint, Department, Evidence,
    Incident, IncidentReport, Jurisdiction, MlFeedback, MlModel, Notification,
    PriorityConfig, SlaRecord, SlaRule, StatusHistory,
)
from ..schemas import (
    AdminCreate, AdminLogin, AssignRequest, CategoryCorrect, ComplaintPatch,
    ResolveRequest,
)
from ..services import pipeline, priority as prio_svc, sla as sla_svc
from ..taxonomy import CATEGORIES, CATEGORIES_ORDERED, PRIORITY_BANDS, ROLES, STATUSES

router = APIRouter(prefix="/admin", tags=["admin"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ------------------------------------------------------------------ auth

@router.post("/login")
async def login(body: AdminLogin, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Admin).where(
        (Admin.username == body.username) | (Admin.email == body.username)))
    admin = res.scalar_one_or_none()
    if admin is None or not admin.is_active or not verify_password(body.password, admin.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    return {"token": create_token(admin), "admin": _admin_out(admin)}


@router.post("/admins", status_code=status.HTTP_201_CREATED)
async def create_admin(body: AdminCreate, admin: Admin = Depends(get_current_admin),
                       db: AsyncSession = Depends(get_db)):
    if admin.role != "super_admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only super admin can create admins")
    if body.role not in ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid role")
    exists = await db.execute(select(Admin).where(
        (Admin.username == body.username) | (Admin.email == body.email)))
    if exists.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Username/email already exists")
    a = Admin(email=body.email, username=body.username,
              password_hash=hash_password(body.password), full_name=body.full_name,
              role=body.role, jurisdiction_id=body.jurisdiction_id)
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


def _admin_out(a: Admin) -> dict:
    return {"id": a.id, "email": a.email, "username": a.username,
            "full_name": a.full_name, "role": a.role,
            "jurisdiction_id": a.jurisdiction_id}


# ------------------------------------------------------------- jurisdiction

async def _scoped_complaints(db: AsyncSession, admin: Admin):
    """Query complaints visible to admin's jurisdiction."""
    if admin.role == "super_admin":
        return select(Complaint)
    jids = await jurisdiction_chain(db, admin)
    if not jids:
        return select(Complaint).where(Complaint.id == "__none__")
    return select(Complaint).where(
        (Complaint.ward_id.in_(jids)) |
        (Complaint.municipality_id.in_(jids)) |
        (Complaint.district_id.in_(jids))
    )


async def _scoped_incidents(db: AsyncSession, admin: Admin):
    if admin.role == "super_admin":
        return select(Incident)
    jids = await jurisdiction_chain(db, admin)
    if not jids:
        return select(Incident).where(Incident.id == "__none__")
    # incidents carry ward_id; also include incidents whose complaints are in scope
    sub = await _scoped_complaints(db, admin)
    subq = sub.with_only_columns(Complaint.incident_id).where(Complaint.incident_id.isnot(None))
    return select(Incident).where(
        (Incident.ward_id.in_(jids)) | (Incident.id.in_(subq)))


# --------------------------------------------------------------- dashboard

@router.get("/dashboard")
async def dashboard(admin: Admin = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    base = await _scoped_complaints(db, admin)
    res = await db.execute(base)
    complaints = list(res.scalars().all())

    now = utcnow()
    def count(pred):
        return sum(1 for c in complaints if pred(c))

    inc_base = await _scoped_incidents(db, admin)
    inc_res = await db.execute(inc_base)
    incidents = list(inc_res.scalars().all())

    resolved = [c for c in complaints if c.status in ("resolved", "closed")]
    avg_hours = None
    if resolved and any(c.resolved_at for c in resolved):
        hrs = [(c.resolved_at - c.created_at).total_seconds() / 3600
               for c in resolved if c.resolved_at and c.resolved_at > c.created_at]
        avg_hours = round(sum(hrs) / len(hrs), 1) if hrs else None

    # ward-wise counts
    ward_counts: dict[str, int] = {}
    for c in complaints:
        if c.ward_id:
            w = await db.get(Jurisdiction, c.ward_id)
            ward_counts[w.name if w else c.ward_id] = ward_counts.get(w.name if w else c.ward_id, 0) + 1

    # department performance
    dept_stats = {}
    for c in complaints:
        if c.department_id:
            d = await db.get(Department, c.department_id)
            name = d.name if d else c.department_id
            s = dept_stats.setdefault(name, {"total": 0, "resolved": 0, "open": 0})
            s["total"] += 1
            if c.status in ("resolved", "closed"): s["resolved"] += 1
            else: s["open"] += 1

    return {
        "jurisdiction": {"role": admin.role, "jurisdiction_id": admin.jurisdiction_id},
        "total_reports": len(complaints),
        "by_status": {
            "pending": count(lambda c: c.status in ("received", "under_review", "awaiting_review")),
            "inspection_scheduled": count(lambda c: c.status == "inspection_scheduled"),
            "in_progress": count(lambda c: c.status == "in_progress"),
            "awaiting_verification": count(lambda c: c.status == "awaiting_verification"),
            "resolved": count(lambda c: c.status in ("resolved", "closed")),
            "overdue": count(lambda c: c.sla_breached or (c.sla_deadline and c.sla_deadline < now and c.status not in ("resolved", "closed", "awaiting_verification"))),
            "reopened": count(lambda c: c.status == "reopened"),
        },
        "active_incidents": sum(1 for i in incidents if i.status in ("open", "in_progress", "reopened")),
        "critical_high_incidents": sum(1 for i in incidents if i.priority_band in ("critical", "high") and i.status not in ("resolved", "closed")),
        "sla_breached": count(lambda c: c.sla_breached),
        "avg_resolution_hours": avg_hours,
        "citizens_affected_unresolved": sum(i.citizens_affected for i in incidents if i.status not in ("resolved", "closed")),
        "ward_counts": ward_counts,
        "department_stats": dept_stats,
        "by_category": {cat: count(lambda c, cat=cat: c.category == cat) for cat in CATEGORIES_ORDERED},
    }


# ----------------------------------------------------------- complaints

@router.get("/complaints")
async def list_complaints(
    admin: Admin = Depends(get_current_admin), db: AsyncSession = Depends(get_db),
    status_filter: str | None = None, category: str | None = None,
    priority_band: str | None = None, ward_id: str | None = None,
    department_id: str | None = None, overdue: bool | None = None,
    page: int = 1, page_size: int = 25,
):
    base = await _scoped_complaints(db, admin)
    q = base.options(selectinload(Complaint.evidence))
    if status_filter:
        q = q.where(Complaint.status == status_filter)
    if category:
        q = q.where(Complaint.category == category)
    if priority_band:
        q = q.where(Complaint.priority_band == priority_band)
    if ward_id:
        # ward filter must still be within jurisdiction — scoped query handles it
        q = q.where(Complaint.ward_id == ward_id)
    if department_id:
        q = q.where(Complaint.department_id == department_id)
    if overdue:
        q = q.where(Complaint.sla_deadline < utcnow(), Complaint.status.notin_(["resolved", "closed", "awaiting_verification"]))
    q = q.order_by(Complaint.created_at.desc())
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    res = await db.execute(q.offset((page - 1) * page_size).limit(page_size))
    items = []
    for c in res.scalars().all():
        items.append(await _admin_complaint_out(db, c))
    return {"total": total, "page": page, "page_size": page_size, "items": items}


async def _admin_complaint_out(db: AsyncSession, c: Complaint) -> dict:
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
            select(Complaint.public_id, Complaint.description, IncidentReport.match_evidence, IncidentReport.link_type)
            .join(IncidentReport, IncidentReport.complaint_id == Complaint.id)
            .where(IncidentReport.incident_id == inc.id))
        members = [{"public_id": r[0], "description": (r[1] or "")[:160],
                    "match_evidence": r[2], "link_type": r[3]} for r in mres.all()]
    return {
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
        "anonymous": c.anonymous, "trust_flags": json.loads(c.trust_flags or "[]"),
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
                      "is_resolution": e.is_resolution,
                      "created_at": e.created_at.isoformat() if e.created_at else None}
                     for e in ev],
    }


@router.get("/complaints/{complaint_id}")
async def get_complaint(complaint_id: str, admin: Admin = Depends(get_current_admin),
                        db: AsyncSession = Depends(get_db)):
    c = await _get_scoped_complaint(db, admin, complaint_id)
    return await _admin_complaint_out(db, c)


async def _get_scoped_complaint(db: AsyncSession, admin: Admin, cid: str) -> Complaint:
    res = await db.execute(select(Complaint).where(
        (Complaint.id == cid) | (Complaint.public_id == cid)))
    c = res.scalar_one_or_none()
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Complaint not found")
    await assert_can_access_complaint(db, admin, c)
    return c


@router.patch("/complaints/{complaint_id}")
async def patch_complaint(complaint_id: str, body: ComplaintPatch,
                          admin: Admin = Depends(get_current_admin),
                          db: AsyncSession = Depends(get_db)):
    c = await _get_scoped_complaint(db, admin, complaint_id)
    changes = {}
    if body.status:
        if body.status not in STATUSES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid status; allowed: {STATUSES}")
        old = c.status
        c.status = body.status
        db.add(StatusHistory(complaint_id=c.id, incident_id=c.incident_id,
                             from_status=old, to_status=body.status,
                             actor_type="admin", actor_id=admin.id, note=body.note))
        changes["status"] = {"from": old, "to": body.status}
    if body.category:
        if body.category not in CATEGORIES_ORDERED:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid category")
        old = c.category
        c.category = body.category
        c.category_confirmed = True
        changes["category"] = {"from": old, "to": body.category}
        # feeds ML feedback loop
        db.add(MlFeedback(kind="category_correction", complaint_id=c.id,
                          input_text=(c.transcript or c.description)[:1000],
                          predicted_label=old, confirmed_label=body.category,
                          confidence=c.ai_confidence, model_version="admin"))
    if body.priority_override_score is not None:
        if not body.override_reason:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Override reason required")
        c.priority_score = body.priority_override_score
        c.priority_band = prio_svc.band_for(body.priority_override_score)
        c.priority_override_reason = body.override_reason
        changes["priority_override"] = {"score": body.priority_override_score,
                                        "reason": body.override_reason}
    db.add(AuditLog(admin_id=admin.id, action="complaint.update", entity_type="complaint",
                    entity_id=c.id, detail=json.dumps(changes)))
    await db.commit()
    return {"ok": True, "changes": changes}


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
                    entity_id=c.id, detail=json.dumps({"department": dept.name, "note": body.note})))
    await db.commit()
    return {"ok": True, "department": dept.name}


@router.post("/complaints/{complaint_id}/resolve")
async def resolve_complaint(complaint_id: str, body: ResolveRequest,
                            admin: Admin = Depends(get_current_admin),
                            db: AsyncSession = Depends(get_db)):
    """Resolution REQUIRES evidence — never a bare button click."""
    c = await _get_scoped_complaint(db, admin, complaint_id)
    res_evs = (await db.execute(select(Evidence).where(
        Evidence.complaint_id == c.id, Evidence.is_resolution == True))).scalars().all()  # noqa: E712
    if body.evidence_ids:
        marked = (await db.execute(select(Evidence).where(Evidence.id.in_(body.evidence_ids)))).scalars().all()
        for e in marked:
            e.is_resolution = True
        res_evs = list(res_evs) + [e for e in marked if e not in res_evs]
    if not res_evs:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Resolution requires at least one resolution evidence item (photo/document)")
    old = c.status
    c.status = "awaiting_verification"
    c.resolved_at = utcnow()
    c.sla_breached = c.sla_breached or bool(c.sla_deadline and c.sla_deadline < c.resolved_at)
    if c.incident_id:
        inc = await db.get(Incident, c.incident_id)
        if inc:
            inc.status = "awaiting_verification"
            inc.resolved_at = inc.resolved_at or c.resolved_at
            await _refresh_incident_status(db, inc)
    db.add(StatusHistory(complaint_id=c.id, incident_id=c.incident_id,
                         from_status=old, to_status=c.status, actor_type="admin",
                         actor_id=admin.id, note=body.note or "Resolution submitted with evidence"))
    db.add(AuditLog(admin_id=admin.id, action="complaint.resolve", entity_type="complaint",
                    entity_id=c.id, detail=json.dumps({"evidence": [e.id for e in res_evs], "note": body.note})))
    await db.commit()
    return {"ok": True, "status": c.status, "awaiting": "citizen verification"}


async def _refresh_incident_status(db: AsyncSession, inc: Incident):
    """Incident -> resolved only when ALL member complaints resolved/closed."""
    res = await db.execute(
        select(Complaint.status)
        .join(IncidentReport, IncidentReport.complaint_id == Complaint.id)
        .where(IncidentReport.incident_id == inc.id))
    statuses = [r[0] for r in res.all()]
    if statuses and all(s in ("resolved", "closed", "awaiting_verification") for s in statuses):
        inc.status = "awaiting_verification"
    elif any(s in ("in_progress", "inspection_scheduled") for s in statuses):
        inc.status = "in_progress"
    else:
        inc.status = "open"


@router.get("/incidents")
async def list_incidents(admin: Admin = Depends(get_current_admin),
                         db: AsyncSession = Depends(get_db),
                         status_filter: str | None = None, priority_band: str | None = None,
                         page: int = 1, page_size: int = 25):
    base = await _scoped_incidents(db, admin)
    q = base.order_by(Incident.priority_score.desc(), Incident.created_at.desc())
    if status_filter:
        q = q.where(Incident.status == status_filter)
    if priority_band:
        q = q.where(Incident.priority_band == priority_band)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    res = await db.execute(q.offset((page - 1) * page_size).limit(page_size))
    items = []
    for i in res.scalars().all():
        items.append({
            "id": i.id, "title": i.title, "category": i.category, "status": i.status,
            "priority_band": i.priority_band, "priority_score": i.priority_score,
            "citizens_affected": i.citizens_affected,
            "sla_deadline": i.sla_deadline.isoformat() if i.sla_deadline else None,
            "lat": i.lat, "lon": i.lon, "created_at": i.created_at.isoformat() if i.created_at else None,
        })
    return {"total": total, "items": items}


@router.get("/map")
async def map_data(admin: Admin = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    base = await _scoped_incidents(db, admin)
    res = await db.execute(base)
    pts = [{"id": i.id, "lat": i.lat, "lon": i.lon, "status": i.status,
            "priority_band": i.priority_band, "category": i.category,
            "citizens_affected": i.citizens_affected, "title": i.title}
           for i in res.scalars().all() if i.lat is not None and i.lon is not None]
    return {"points": pts}


# ------------------------------------------------------------ departments

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
    feedback_counts = {k: n for k, n in fb.all()}
    # confidence distribution of predictions
    res2 = await db.execute(select(Complaint.ai_confidence).where(Complaint.ai_confidence.isnot(None)))
    confs = [c for (c,) in res2.all() if c is not None]
    low_conf = sum(1 for c in confs if c < get_settings().classify_review_threshold)
    return {
        "models": models,
        "active_model": next((m for m in models if m["is_active"]), None),
        "feedback_counts": feedback_counts,
        "predictions_logged": len(confs),
        "low_confidence_count": low_conf,
        "low_confidence_rate": round(low_conf / len(confs), 3) if confs else 0.0,
    }


@router.post("/ml/retrain")
async def ml_retrain(admin: Admin = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    if admin.role not in ("super_admin", "district_admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "District admin or above required")
    # run training script in-process (subprocess keeps it isolated)
    ml_dir = Path(__file__).resolve().parents[3] / "ml"
    train_script = ml_dir / "train.py"
    if not train_script.exists():
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "ml/train.py not found")
    try:
        proc = subprocess.run(
            [sys.executable, str(train_script), "--db", _db_path_for_training(), "--register"],
            capture_output=True, text=True, timeout=600, cwd=str(ml_dir))
    except subprocess.TimeoutExpired:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "Training timed out")
    tail = (proc.stdout or "")[-3000:]
    if proc.returncode != 0:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            f"Training failed: {(proc.stderr or tail)[-1000:]}")
    # parse metrics line emitted by train.py
    metrics = {}
    for line in (proc.stdout or "").splitlines():
        if line.startswith("METRICS_JSON:"):
            try:
                metrics = json.loads(line.split(":", 1)[1])
            except Exception:  # noqa: BLE001
                pass
    db.add(AuditLog(admin_id=admin.id, action="ml.retrain", entity_type="ml",
                    entity_id="category_head", detail=json.dumps(metrics)[:4000]))
    await db.commit()
    return {"ok": True, "output": tail, "metrics": metrics}


def _db_path_for_training() -> str:
    url = get_settings().database_url
    if url.startswith("sqlite"):
        return url.split("///", 1)[-1]
    return url


# ------------------------------------------------------------- notifications

@router.get("/notifications")
async def notifications(admin: Admin = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Notification).order_by(Notification.created_at.desc()).limit(50))
    return [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body,
             "read": n.read, "created_at": n.created_at.isoformat() if n.created_at else None,
             "complaint_id": n.complaint_id} for n in res.scalars().all()]
