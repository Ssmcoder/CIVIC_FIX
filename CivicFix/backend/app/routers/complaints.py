"""Public (no-login) complaint endpoints — hardened per CF register."""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..errors import error_envelope
from ..models import (
    AuditLog, Complaint, Evidence, Incident, IncidentReport, IncidentSupport,
    MlFeedback, StatusHistory,
)
from ..ratelimit import check as rl_check, limited
from ..schemas import SupportRequest, VerifyRequest
from ..security import verify_tracking_token, rehash_tracking_token
from ..services import pipeline
from .. import uploads
from ..services.location import haversine_m
from ..taxonomy import CATEGORIES

router = APIRouter(prefix="/complaints", tags=["complaints"])
incidents_router = APIRouter(prefix="/incidents", tags=["incidents"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _complaint_out(c: Complaint, db_incident: Incident | None = None,
                   history: list | None = None, evidence: list | None = None) -> dict:
    factors = {}
    try:
        factors = json.loads(c.priority_factors or "{}")
    except Exception:  # noqa: BLE001
        pass
    return {
        "id": c.id, "public_id": c.public_id, "status": c.status,
        "category": c.category, "category_label": CATEGORIES.get(c.category, c.category),
        "issue_type": c.issue_type, "ai_category": c.ai_category,
        "ai_confidence": c.ai_confidence, "ai_explanation": c.ai_explanation,
        "category_confirmed": c.category_confirmed,
        "description": c.description, "transcript": c.transcript, "language": c.language,
        "source": c.source, "severity": c.severity, "severity_score": c.severity_score,
        "safety_risk": c.safety_risk, "priority_score": c.priority_score,
        "priority_band": c.priority_band, "priority_factors": factors,
        "priority_override_reason": c.priority_override_reason,
        "sla_deadline": c.sla_deadline.isoformat() if c.sla_deadline else None,
        "sla_breached": c.sla_breached, "department_id": c.department_id,
        "location": {"lat": c.lat, "lon": c.lon, "landmark": c.landmark_text,
                     "confidence": c.location_confidence, "verified": c.location_verified},
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
        "review_reason": c.review_reason,
        "incident_id": c.incident_id,
        "incident": {"id": db_incident.id, "title": db_incident.title,
                     "status": db_incident.status, "citizens_affected": db_incident.citizens_affected,
                     "priority_band": db_incident.priority_band} if db_incident else None,
        "status_history": [{"from": h.from_status, "to": h.to_status, "actor": h.actor_type,
                            "note": h.note, "at": h.created_at.isoformat() if h.created_at else None}
                           for h in (history or [])],
        "evidence": [{"id": e.id, "kind": e.kind, "name": e.original_name,
                      "mime": e.mime_type, "size": e.size_bytes, "caption": e.caption,
                      "is_resolution": e.is_resolution,
                      "created_at": e.created_at.isoformat() if e.created_at else None}
                     for e in (evidence or []) if e.uploader_type != "citizen" or not e.is_resolution],
    }


async def _lookup_by_token(db: AsyncSession, token: str) -> Complaint | None:
    """Find complaint by tracking secret; upgrades hash to current key (CF-02)."""
    res = await db.execute(select(Complaint).where(Complaint.tracking_token_hash.isnot(None)))
    # tokens are high-entropy; compare against stored 'kid:hash'
    for c in res.scalars().all():
        stored = c.tracking_token_hash or ""
        if ":" in stored:
            _, h = stored.split(":", 1)
            ok, upgrade_kid = verify_tracking_token(token, h)
        else:
            # legacy unsalted sha256 format — accept then upgrade
            import hashlib
            from ..config import get_settings
            legacy = hashlib.sha256((token + get_settings().tracking_token_secret).encode()).hexdigest()
            ok = secrets.compare_digest(legacy, stored)
            upgrade_kid = "v1" if ok else None
        if ok:
            if upgrade_kid:
                kid, newh = rehash_tracking_token(token)
                c.tracking_token_hash = f"{kid}:{newh}"
                await db.commit()
            return c
    return None


async def _get_by_token_or_404(db: AsyncSession, token: str) -> Complaint:
    c = await _lookup_by_token(db, token)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invalid tracking token")
    return c


# ------------------------------------------------------------------ submit

@router.post("", status_code=status.HTTP_201_CREATED)
async def submit_complaint(request: Request, body: dict,
                           db: AsyncSession = Depends(get_db)):
    """Accepts the validated ComplaintCreate shape (kept as dict here so the
    OpenAPI schema is generated from the TypedDict below via response_model)."""
    from ..schemas import ComplaintCreate
    try:
        data = ComplaintCreate.model_validate(body)
    except Exception as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)[:400])
    ok, retry = rl_check(request, "submit", get_settings().rl_submit_per_hour, 3600)
    if not ok:
        return limited(retry)
    complaint, token = await pipeline.create_complaint(
        db, description=data.description, lat=data.lat, lon=data.lon,
        landmark_text=data.landmark_text,
        manual_location_confirmed=data.manual_location_confirmed,
        language=data.language, source=data.source, transcript=data.transcript,
        contact_phone=data.contact_phone, contact_email=data.contact_email,
        anonymous=data.anonymous, category_override=data.category_override)
    pipe = getattr(complaint, "_pipeline", {})
    dept_name = None
    if complaint.department_id:
        from ..models import Department
        d = await db.get(Department, complaint.department_id)
        dept_name = d.name if d else None
    return {
        "public_id": complaint.public_id,
        "tracking_token": token,  # shown ONCE (CF-08)
        "status": complaint.status, "category": complaint.category,
        "category_label": CATEGORIES.get(complaint.category, complaint.category),
        "issue_type": complaint.issue_type, "ai_confidence": complaint.ai_confidence,
        "ai_explanation": complaint.ai_explanation,
        "priority_band": complaint.priority_band, "priority_score": complaint.priority_score,
        "priority_factors": json.loads(complaint.priority_factors or "{}"),
        "sla_deadline": complaint.sla_deadline.isoformat() if complaint.sla_deadline else None,
        "department": dept_name, "incident_id": complaint.incident_id,
        "location": {"lat": complaint.lat, "lon": complaint.lon,
                     "landmark": complaint.landmark_text,
                     "confidence": complaint.location_confidence,
                     "verified": complaint.location_verified,
                     "candidates": pipe.get("location_candidates", []),
                     "method": pipe.get("location_method")},
        "possible_duplicates": pipe.get("match_candidates", []),
        "review_reasons": pipe.get("review_reasons", []),
        "message": "Complaint received. An authorised administrator will review it.",
    }


# ------------------------------------------------------------------ track

@router.get("/track/{token}")
async def track_complaint(request: Request, token: str, db: AsyncSession = Depends(get_db)):
    ok, retry = rl_check(request, "track", get_settings().rl_track_per_min, 60)
    if not ok:
        return limited(retry)
    c = await _get_by_token_or_404(db, token)
    hist = (await db.execute(select(StatusHistory).where(StatusHistory.complaint_id == c.id)
                           .order_by(StatusHistory.created_at))).scalars().all()
    ev = (await db.execute(select(Evidence).where(Evidence.complaint_id == c.id))).scalars().all()
    inc = await db.get(Incident, c.incident_id) if c.incident_id else None
    dept_name = None
    if c.department_id:
        from ..models import Department
        d = await db.get(Department, c.department_id)
        dept_name = d.name if d else None
    out = _complaint_out(c, inc, list(hist), list(ev))
    out["department"] = dept_name
    out["citizens_affected"] = inc.citizens_affected if inc else 1
    out["can_verify"] = c.status == "awaiting_verification"
    out["resolution_evidence"] = [
        {"id": e.id, "kind": e.kind, "name": e.original_name, "caption": e.caption,
         "created_at": e.created_at.isoformat() if e.created_at else None}
        for e in ev if e.is_resolution and e.uploader_type != "citizen"]
    return out


# ---------------------------------------------------------------- evidence

@router.post("/{complaint_id}/evidence")
async def upload_evidence(request: Request, complaint_id: str,
                          file: UploadFile = File(...),
                          kind: str = Form("photo"), caption: str = Form(""),
                          token: str = Form(""),
                          db: AsyncSession = Depends(get_db)):
    ok, retry = rl_check(request, "evidence", get_settings().rl_evidence_per_hour, 3600)
    if not ok:
        return limited(retry)
    c = await _get_by_token_or_404(db, token)
    if c.public_id != complaint_id and c.id != complaint_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Token does not match complaint")
    # image-count cap (CF-11)
    cnt = (await db.execute(select(Evidence).where(Evidence.complaint_id == c.id))).scalars().all()
    if len(cnt) >= get_settings().max_images_per_complaint:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Evidence limit reached")
    dest = os.path.join(get_settings().media_path, c.id)
    meta = await uploads.save_upload(file, dest, kind=kind)
    ev = Evidence(complaint_id=c.id,
                  kind=kind if kind in ("photo", "video", "audio", "document") else "photo",
                  caption=(caption or "")[:500], uploader_type="citizen",
                  is_resolution=False, **{k: meta[k] for k in
                                           ("file_path", "original_name", "mime_type", "size_bytes")})
    db.add(ev)
    await db.commit()
    await db.refresh(ev)
    return {"id": ev.id, "kind": ev.kind, "name": ev.original_name, "size": ev.size_bytes}


# -------------------------------------------------------------- incidents

@incidents_router.get("/nearby")
async def nearby_incidents(request: Request, lat: float, lon: float,
                           radius_m: float | None = None, limit: int = 20,
                           bbox: str | None = None, category: str | None = None,
                           db: AsyncSession = Depends(get_db)):
    """Public-safe incident list (CF-06): coarse coords, generic titles,
    clamped radius/limit, no citizen text, no internal priority."""
    s = get_settings()
    ok, retry = rl_check(request, "nearby", s.rl_nearby_per_min, 60)
    if not ok:
        return limited(retry)
    radius = min(max(radius_m or s.nearby_default_radius_m, 1), s.nearby_max_radius_m)
    limit = min(max(limit, 1), s.nearby_max_limit)
    min_lat = max_lat = min_lon = max_lon = None
    if bbox:
        try:
            min_lat, min_lon, max_lat, max_lon = [float(x) for x in bbox.split(",")]
        except ValueError:
            raise HTTPException(422, "bbox must be min_lat,min_lon,max_lat,max_lon")
    res = await db.execute(select(Incident).where(
        Incident.status.in_(["open", "in_progress", "awaiting_verification", "reopened"])))
    out = []
    for i in res.scalars().all():
        if i.lat is None or i.lon is None:
            continue
        if bbox and not (min_lat <= i.lat <= max_lat and min_lon <= i.lon <= max_lon):
            continue
        d = haversine_m(lat, lon, i.lat, i.lon)
        if d <= radius and (not category or i.category == category):
            ward = None
            if i.ward_id:
                from ..models import Jurisdiction
                w = await db.get(Jurisdiction, i.ward_id)
                ward = w.name if w else None
            issue = CATEGORIES.get(i.category, "Municipal issue")
            out.append({
                "incident_id": i.id,
                "title": f"{issue} reported" + (f" near {ward}" if ward else ""),
                "category": i.category,
                "distance_m": round(d),
                "citizens_affected": i.citizens_affected,
                "status": "open" if i.status in ("open", "reopened") else i.status,
                "lat": round(i.lat, 3), "lon": round(i.lon, 3),  # ~110 m coarsening
            })
    out.sort(key=lambda x: x["distance_m"])
    return out[:limit]


@incidents_router.post("/{incident_id}/support")
async def support_incident(incident_id: str, body: SupportRequest,
                           db: AsyncSession = Depends(get_db)):
    """Idempotent 'I am also affected' (CF-23): IncidentSupport unique pair."""
    c = await _get_by_token_or_404(db, body.token)
    inc = await db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Incident not found")
    existing = (await db.execute(select(IncidentSupport).where(
        IncidentSupport.incident_id == incident_id,
        IncidentSupport.complaint_id == c.id))).scalar_one_or_none()
    if existing is not None:
        return {"ok": True, "already_supported": True,
                "citizens_affected": inc.citizens_affected}
    db.add(IncidentSupport(incident_id=incident_id, complaint_id=c.id))
    # move complaint linkage if it isn't already on this incident
    if c.incident_id != incident_id:
        # remove old auto link row if present, then attach
        old = (await db.execute(select(IncidentReport).where(
            IncidentReport.complaint_id == c.id))).scalar_one_or_none()
        if old and old.incident_id != incident_id:
            await db.delete(old)
        rep = (await db.execute(select(IncidentReport).where(
            IncidentReport.complaint_id == c.id))).scalar_one_or_none()
        if rep is None:
            db.add(IncidentReport(incident_id=incident_id, complaint_id=c.id,
                                  match_text_sim=0.0, match_geo_dist_m=-1,
                                  match_evidence=json.dumps({"note": "citizen support"}),
                                  link_type="citizen_confirmed"))
        c.incident_id = incident_id
        inc.citizens_affected = (inc.citizens_affected or 1) + 1
    db.add(StatusHistory(complaint_id=c.id, incident_id=incident_id,
                         from_status=c.status, to_status=c.status,
                         actor_type="citizen", note="Citizen marked 'this affects me too'"))
    db.add(MlFeedback(kind="citizen_confirm", complaint_id=c.id,
                      input_text=(c.description or "")[:500], predicted_label=None,
                      confirmed_label="same_issue", confidence=None))
    await db.commit()
    await pipeline._refresh_incident_priority(db, incident_id)
    await db.commit()
    return {"ok": True, "already_supported": False,
            "citizens_affected": inc.citizens_affected}


# ------------------------------------------------------------------ verify

@router.post("/{complaint_id}/verify")
async def verify_fix(request: Request, complaint_id: str, body: VerifyRequest,
                     db: AsyncSession = Depends(get_db)):
    """CF-03 hardened: status gate, confirm/reject only, constant-time-ish
    indistinguishable 404, no direct incident resolution, row lock, audit."""
    ok, retry = rl_check(request, "track", get_settings().rl_track_per_min, 60)
    if not ok:
        return limited(retry)
    # equalised lookup: try public_id AND id, single query
    res = await db.execute(select(Complaint).where(
        (Complaint.public_id == complaint_id) | (Complaint.id == complaint_id))
        .with_for_update())
    c = res.scalar_one_or_none()
    # dummy verify for timing equalisation on unknown IDs
    if c is None:
        verify_tracking_token(body.token, "0" * 64)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Complaint not found")
    stored = c.tracking_token_hash or ""
    h = stored.split(":", 1)[1] if ":" in stored else stored
    tok_ok, upgrade = verify_tracking_token(body.token, h)
    if not tok_ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Complaint not found")
    if upgrade:
        kid, newh = rehash_tracking_token(body.token)
        c.tracking_token_hash = f"{kid}:{newh}"
    if c.status != "awaiting_verification":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Complaint is '{c.status}', not awaiting verification")
    old = c.status
    if body.action == "confirm":
        c.status = "closed"
        c.resolved_at = c.resolved_at or utcnow()
        note = "Citizen confirmed the fix"
    else:
        c.status = "reopened"
        note = f"Citizen rejected resolution: {(body.reason or '')[:200]}"
    # incident status is DERIVED — never set resolved here (CF-03)
    if c.incident_id:
        await _derive_incident_status(db, c.incident_id)
    db.add(StatusHistory(complaint_id=c.id, incident_id=c.incident_id,
                         from_status=old, to_status=c.status,
                         actor_type="citizen", note=note))
    db.add(AuditLog(admin_id=None, action=f"complaint.verify.{body.action}",
                    entity_type="complaint", entity_id=c.id,
                    detail=json.dumps({"reason": (body.reason or "")[:200]})))
    await db.commit()
    return {"ok": True, "status": c.status}


async def _derive_incident_status(db: AsyncSession, incident_id: str) -> None:
    """Incident resolved ONLY when every linked complaint is closed."""
    inc = await db.get(Incident, incident_id)
    if inc is None:
        return
    res = await db.execute(
        select(Complaint.status)
        .join(IncidentReport, IncidentReport.complaint_id == Complaint.id)
        .where(IncidentReport.incident_id == incident_id))
    statuses = [r[0] for r in res.all()]
    if statuses and all(s == "closed" for s in statuses):
        inc.status = "resolved"
        inc.resolved_at = inc.resolved_at or utcnow()
    elif any(s == "reopened" for s in statuses):
        inc.status = "reopened"
    elif any(s in ("awaiting_verification", "resolved") for s in statuses):
        inc.status = "awaiting_verification"
    else:
        inc.status = "open"
