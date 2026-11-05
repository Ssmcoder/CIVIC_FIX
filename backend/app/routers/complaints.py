"""Public (no-login) complaint endpoints."""
from __future__ import annotations

import json
import math
import os
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..database import get_db
from ..models import (
    AuditLog, Complaint, Evidence, Incident, IncidentReport, MlFeedback,
    Notification, StatusHistory,
)
from ..schemas import ComplaintCreate, NearbyIncident, SupportRequest, VerifyRequest
from ..services import pipeline
from ..services.location import haversine_m
from ..taxonomy import CATEGORIES

router = APIRouter(prefix="/complaints", tags=["complaints"])
incidents_router = APIRouter(prefix="/incidents", tags=["incidents"])

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "video/mp4", "audio/webm",
                "audio/ogg", "audio/mpeg", "audio/wav", "application/pdf"}


def _complaint_out(c: Complaint, db_incident: Incident | None = None,
                   history: list[StatusHistory] | None = None,
                   evidence: list[Evidence] | None = None) -> dict:
    factors = {}
    try:
        factors = json.loads(c.priority_factors or "{}")
    except Exception:  # noqa: BLE001
        pass
    ward_name = getattr(c, "_ward_name", None)
    return {
        "id": c.id,
        "public_id": c.public_id,
        "status": c.status,
        "category": c.category,
        "category_label": CATEGORIES.get(c.category, c.category),
        "issue_type": c.issue_type,
        "ai_category": c.ai_category,
        "ai_confidence": c.ai_confidence,
        "ai_explanation": c.ai_explanation,
        "category_confirmed": c.category_confirmed,
        "description": c.description,
        "transcript": c.transcript,
        "language": c.language,
        "source": c.source,
        "severity": c.severity,
        "severity_score": c.severity_score,
        "safety_risk": c.safety_risk,
        "priority_score": c.priority_score,
        "priority_band": c.priority_band,
        "priority_factors": factors,
        "priority_override_reason": c.priority_override_reason,
        "sla_deadline": c.sla_deadline.isoformat() if c.sla_deadline else None,
        "sla_breached": c.sla_breached,
        "department_id": c.department_id,
        "location": {
            "lat": c.lat, "lon": c.lon,
            "landmark": c.landmark_text,
            "confidence": c.location_confidence,
            "verified": c.location_verified,
            "ward": ward_name,
        },
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
        "review_reason": c.review_reason,
        "trust_flags": json.loads(c.trust_flags or "[]"),
        "incident_id": c.incident_id,
        "incident": _incident_brief(db_incident) if db_incident else None,
        "status_history": [
            {"from": h.from_status, "to": h.to_status, "actor": h.actor_type,
             "note": h.note, "at": h.created_at.isoformat() if h.created_at else None}
            for h in (history or [])
        ],
        "evidence": [
            {"id": e.id, "kind": e.kind, "name": e.original_name,
             "mime": e.mime_type, "size": e.size_bytes,
             "caption": e.caption, "is_resolution": e.is_resolution,
             "created_at": e.created_at.isoformat() if e.created_at else None}
            for e in (evidence or [])
        ],
    }


def _incident_brief(i: Incident) -> dict:
    return {
        "id": i.id, "title": i.title, "category": i.category,
        "status": i.status, "priority_band": i.priority_band,
        "priority_score": i.priority_score, "citizens_affected": i.citizens_affected,
        "sla_deadline": i.sla_deadline.isoformat() if i.sla_deadline else None,
    }


async def _get_by_token(db: AsyncSession, token: str) -> Complaint:
    h = pipeline.hash_token(token)
    res = await db.execute(select(Complaint).where(Complaint.tracking_token_hash == h))
    c = res.scalar_one_or_none()
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invalid tracking token")
    return c


@router.post("", status_code=status.HTTP_201_CREATED)
async def submit_complaint(body: ComplaintCreate, db: AsyncSession = Depends(get_db)):
    complaint, token = await pipeline.create_complaint(
        db,
        description=body.description,
        lat=body.lat, lon=body.lon,
        landmark_text=body.landmark_text,
        manual_location_confirmed=body.manual_location_confirmed,
        language=body.language, source=body.source,
        transcript=body.transcript,
        contact_phone=body.contact_phone, contact_email=body.contact_email,
        anonymous=body.anonymous, category_override=body.category_override,
    )
    pipe = getattr(complaint, "_pipeline", {})
    dept_name = None
    if complaint.department_id:
        from ..models import Department
        d = await db.get(Department, complaint.department_id)
        dept_name = d.name if d else None
    return {
        "public_id": complaint.public_id,
        "tracking_token": token,  # shown ONCE
        "status": complaint.status,
        "category": complaint.category,
        "category_label": CATEGORIES.get(complaint.category, complaint.category),
        "issue_type": complaint.issue_type,
        "ai_confidence": complaint.ai_confidence,
        "ai_explanation": complaint.ai_explanation,
        "priority_band": complaint.priority_band,
        "priority_score": complaint.priority_score,
        "priority_factors": json.loads(complaint.priority_factors or "{}"),
        "sla_deadline": complaint.sla_deadline.isoformat() if complaint.sla_deadline else None,
        "department": dept_name,
        "incident_id": complaint.incident_id,
        "location": {
            "lat": complaint.lat, "lon": complaint.lon,
            "landmark": complaint.landmark_text,
            "confidence": complaint.location_confidence,
            "verified": complaint.location_verified,
            "candidates": pipe.get("location_candidates", []),
            "method": pipe.get("location_method"),
        },
        "possible_duplicates": pipe.get("match_candidates", []),
        "review_reasons": pipe.get("review_reasons", []),
        "message": "Complaint received. An authorised administrator will review it.",
    }


@router.get("/track/{token}")
async def track_complaint(token: str, db: AsyncSession = Depends(get_db)):
    c = await _get_by_token(db, token)
    hist = (await db.execute(
        select(StatusHistory).where(StatusHistory.complaint_id == c.id)
        .order_by(StatusHistory.created_at))).scalars().all()
    ev = (await db.execute(
        select(Evidence).where(Evidence.complaint_id == c.id))).scalars().all()
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
    # resolution evidence = resolution-flagged evidence on incident members
    out["resolution_evidence"] = [
        {"id": e.id, "kind": e.kind, "name": e.original_name, "caption": e.caption,
         "created_at": e.created_at.isoformat() if e.created_at else None}
        for e in ev if e.is_resolution
    ]
    return out


@router.post("/{complaint_id}/evidence")
async def upload_evidence(complaint_id: str, file: UploadFile = File(...),
                          kind: str = Form("photo"), caption: str = Form(""),
                          is_resolution: bool = Form(False),
                          token: str = Form(""),
                          db: AsyncSession = Depends(get_db)):
    # citizens may upload to own complaint via token; admins via separate route
    if token:
        c = await _get_by_token(db, token)
        if c.id != complaint_id and c.public_id != complaint_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Token does not match complaint")
    else:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Tracking token required")
    return await _save_evidence(db, c, file, kind, caption, is_resolution)


async def _save_evidence(db: AsyncSession, c: Complaint, file: UploadFile,
                         kind: str, caption: str, is_resolution: bool) -> dict:
    settings = get_settings()
    mime = file.content_type or "application/octet-stream"
    if mime not in ALLOWED_MIME:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"File type {mime} not allowed")
    data = await file.read()
    max_bytes = settings.media_max_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large")
    safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in (file.filename or "file"))
    path = os.path.join(settings.media_path, c.id)
    os.makedirs(path, exist_ok=True)
    fname = f"{secrets.token_hex(6)}_{safe_name}"
    fpath = os.path.join(path, fname)
    with open(fpath, "wb") as f:
        f.write(data)
    ev = Evidence(complaint_id=c.id, kind=kind if kind in ("photo", "video", "audio", "document") else "photo",
                  file_path=os.path.relpath(fpath, settings.media_path),
                  original_name=file.filename or safe_name, mime_type=mime,
                  size_bytes=len(data), caption=caption, is_resolution=is_resolution)
    db.add(ev)
    await db.commit()
    await db.refresh(ev)
    return {"id": ev.id, "kind": ev.kind, "name": ev.original_name, "size": ev.size_bytes}


@incidents_router.get("/nearby")
async def nearby_incidents(lat: float, lon: float, radius_m: float = 1000.0,
                           category: str | None = None, limit: int = 20,
                           db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Incident).where(
        Incident.status.in_(["open", "in_progress", "awaiting_verification", "reopened"])))
    incs = list(res.scalars().all())
    out = []
    for i in incs:
        if i.lat is None or i.lon is None:
            continue
        d = haversine_m(lat, lon, i.lat, i.lon)
        if d <= radius_m and (not category or i.category == category):
            out.append({"incident_id": i.id, "title": i.title, "category": i.category,
                        "distance_m": round(d, 1), "citizens_affected": i.citizens_affected,
                        "priority_band": i.priority_band, "status": i.status,
                        "lat": i.lat, "lon": i.lon,
                        "priority_score": i.priority_score})
    out.sort(key=lambda x: x["distance_m"])
    return out[:limit]


@incidents_router.post("/{incident_id}/support")
async def support_incident(incident_id: str, body: SupportRequest,
                           db: AsyncSession = Depends(get_db)):
    """'Support this complaint' — citizen confirms same issue via their token.
    Links their complaint to the incident (or creates a support count)."""
    c = await _get_by_token(db, body.token)
    inc_res = await db.execute(select(Incident).where(Incident.id == incident_id))
    inc = inc_res.scalar_one_or_none()
    if inc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Incident not found")
    if c.incident_id == incident_id:
        return {"ok": True, "already_linked": True, "citizens_affected": inc.citizens_affected}
    # link complaint to incident
    db.add(IncidentReport(incident_id=incident_id, complaint_id=c.id,
                          match_text_sim=0.0, match_geo_dist_m=-1,
                          match_evidence=json.dumps({"note": "citizen confirmed same issue"}),
                          link_type="citizen_confirmed"))
    c.incident_id = incident_id
    inc.citizens_affected = (inc.citizens_affected or 1) + 1
    db.add(StatusHistory(complaint_id=c.id, incident_id=incident_id, from_status=c.status,
                         to_status=c.status, actor_type="citizen",
                         note="Citizen confirmed this is the same issue (support)"))
    db.add(MlFeedback(kind="citizen_confirm", complaint_id=c.id,
                      input_text=c.description[:500], predicted_label=None,
                      confirmed_label="same_issue", confidence=None))
    await db.commit()
    await pipeline._refresh_incident_priority(db, incident_id)
    await db.commit()
    return {"ok": True, "already_linked": False, "citizens_affected": inc.citizens_affected}


@router.post("/{complaint_id}/verify")
async def verify_fix(complaint_id: str, body: VerifyRequest,
                     db: AsyncSession = Depends(get_db)):
    """Citizen confirms the fix or reopens. Requires valid tracking token."""
    c = await _get_by_token(db, body.token)
    if c.public_id != complaint_id and c.id != complaint_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Token does not match complaint")
    inc = await db.get(Incident, c.incident_id) if c.incident_id else None
    if body.confirmed:
        c.status = "closed"
        c.resolved_at = c.resolved_at or datetime.now(timezone.utc).replace(tzinfo=None)
        if inc:
            inc.status = "resolved"
            inc.resolved_at = inc.resolved_at or c.resolved_at
        note = body.note or "Citizen confirmed the fix"
    else:
        c.status = "reopened"
        if inc:
            inc.status = "reopened"
        note = body.note or "Citizen reports issue persists — reopened"
    db.add(StatusHistory(complaint_id=c.id, incident_id=c.incident_id,
                         from_status="awaiting_verification", to_status=c.status,
                         actor_type="citizen", note=note))
    db.add(AuditLog(admin_id=None, action="complaint.verify", entity_type="complaint",
                    entity_id=c.id, detail=json.dumps({"confirmed": body.confirmed})))
    await db.commit()
    return {"ok": True, "status": c.status}
