"""Submission pipeline: the single entry point for creating complaints.

Guarantees the hard rule: a complaint is ALWAYS saved, even if every AI step
fails. Failures downgrade status to 'awaiting_review' with a reason — never a
silent rejection.
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import (
    Assignment, AuditLog, Complaint, Department, Incident, IncidentReport,
    Jurisdiction, MlFeedback, Notification, SlaRecord, StatusHistory,
)
from ..taxonomy import CATEGORIES_ORDERED
from . import classify as classify_svc
from . import dedup as dedup_svc
from . import location as loc_svc
from . import priority as prio_svc
from . import sla as sla_svc

log = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_token(token: str) -> str:
    return hashlib.sha256((token + get_settings().tracking_token_secret).encode()).hexdigest()


def gen_public_id(seq: int) -> str:
    year = utcnow().year
    return f"CFX-{year}-{seq:05d}"


async def _next_public_id(db: AsyncSession) -> str:
    res = await db.execute(select(Complaint.public_id))
    ids = [r[0] for r in res.all() if r[0]]
    if not ids:
        return gen_public_id(1)
    # find max seq for current year
    year = str(utcnow().year)
    maxseq = 0
    for pid in ids:
        if pid.startswith(f"CFX-{year}-"):
            try:
                maxseq = max(maxseq, int(pid.rsplit("-", 1)[1]))
            except ValueError:
                pass
    return gen_public_id(maxseq + 1)


async def _resolve_jurisdiction(db: AsyncSession, ward_name: str | None,
                                lat: float | None, lon: float | None):
    """Map to ward/district/municipality jurisdiction rows (seeded demo data)."""
    ward = muni = dist = None
    res = await db.execute(select(Jurisdiction).where(Jurisdiction.level == "ward"))
    wards = list(res.scalars().all())
    if ward_name:
        ward = next((w for w in wards if w.name.lower() == ward_name.lower()), None)
    if ward is None and lat is not None and lon is not None:
        ward = next((w for w in wards
                     if w.min_lat is not None and w.min_lat <= lat <= (w.max_lat or 90)
                     and w.min_lon is not None and w.min_lon <= lon <= (w.max_lon or 180)), None)
    if ward is not None:
        muni = await _parent(db, ward.parent_id) if ward.parent_id else None
        dist = await _parent(db, muni.parent_id) if muni and muni.parent_id else None
    return ward, muni, dist


async def _parent(db: AsyncSession, jid: str | None) -> Jurisdiction | None:
    if not jid:
        return None
    res = await db.execute(select(Jurisdiction).where(Jurisdiction.id == jid))
    return res.scalar_one_or_none()


async def _default_department(db: AsyncSession, category: str) -> Department | None:
    res = await db.execute(select(Department))
    for d in res.scalars().all():
        try:
            cmap = json.loads(d.category_map or "{}")
        except Exception:  # noqa: BLE001
            cmap = {}
        if cmap.get(category) or category in (cmap.get("categories") or []):
            return d
    # fallback: first department
    res = await db.execute(select(Department).limit(1))
    return res.scalar_one_or_none()


async def create_complaint(db: AsyncSession, *, description: str,
                           lat: float | None = None, lon: float | None = None,
                           landmark_text: str | None = None,
                           manual_location_confirmed: bool = False,
                           language: str = "en", source: str = "form",
                           transcript: str | None = None,
                           contact_phone: str | None = None,
                           contact_email: str | None = None,
                           anonymous: bool = False,
                           category_override: str | None = None) -> tuple[Complaint, str]:
    """Create + process a complaint. Returns (complaint, raw_tracking_token).
    The raw token is returned ONCE; only its hash is stored."""
    settings = get_settings()
    text = (transcript or description or "").strip()
    if not text:
        text = "(no description provided)"

    public_id = await _next_public_id(db)
    tracking_token = secrets.token_urlsafe(24)

    complaint = Complaint(
        public_id=public_id,
        tracking_token_hash=hash_token(tracking_token),
        description=description or text,
        transcript=transcript,
        language=language or "en",
        source=source,
        landmark_text=landmark_text,
        contact_phone=None if anonymous else contact_phone,
        contact_email=None if anonymous else contact_email,
        anonymous=anonymous,
        status="received",
    )
    db.add(complaint)
    await db.flush()

    review_reasons: list[str] = []
    steps_done: list[str] = []

    # ---- Step 1: classification (never fatal) ----
    try:
        cls = classify_svc.classify_text(text, language)
        complaint.ai_category = cls["category"]
        complaint.ai_confidence = cls["confidence"]
        complaint.ai_explanation = cls["explanation"]
        complaint.issue_type = cls["issue_type"]
        complaint.category = category_override if category_override in CATEGORIES_ORDERED else cls["category"]
        complaint.category_confirmed = bool(category_override)
        if category_override and category_override != cls["category"]:
            db.add(MlFeedback(kind="citizen_override", complaint_id=complaint.id,
                              input_text=classify_svc.strip_pii(text),
                              predicted_label=cls["category"], confirmed_label=category_override,
                              confidence=cls["confidence"], model_version="rules+head"))
        steps_done.append("classified")
        if cls["confidence"] < settings.classify_review_threshold and not category_override:
            review_reasons.append(f"low classification confidence ({cls['confidence']:.2f})")
    except Exception as e:  # noqa: BLE001
        log.exception("classification failed")
        complaint.category = category_override or "other"
        complaint.ai_confidence = 0.0
        complaint.ai_explanation = f"classification error: {e}"
        review_reasons.append("classification step failed")
        db.add(MlFeedback(kind="citizen_override", complaint_id=complaint.id,
                          input_text=classify_svc.strip_pii(text),
                          predicted_label=None, confirmed_label=complaint.category,
                          confidence=0.0, model_version="error"))

    # ---- Step 2: severity + safety ----
    try:
        sev = classify_svc.severity_and_safety(text)
        complaint.severity = sev["severity"]
        complaint.severity_score = sev["severity_score"]
        complaint.safety_risk = sev["safety_risk"]
        steps_done.append("severity")
    except Exception:  # noqa: BLE001
        complaint.severity_score = 45.0
        complaint.safety_risk = 0.0
        review_reasons.append("severity estimation failed")

    # ---- Step 3: location ----
    try:
        loc = loc_svc.resolve(text, lat=lat, lon=lon,
                              manual_confirmed=manual_location_confirmed)
        # if landmark found but no coords yet, adopt candidate coords but NOT verified
        if loc.lat is not None:
            complaint.lat, complaint.lon = loc.lat, loc.lon
        complaint.landmark_text = complaint.landmark_text or loc.landmark_text
        complaint.location_confidence = loc.confidence
        complaint.location_verified = loc.verified
        ward, muni, dist = await _resolve_jurisdiction(db, loc.ward_name or ward_name_for(loc), complaint.lat, complaint.lon)
        complaint.ward_id = ward.id if ward else None
        complaint.municipality_id = muni.id if muni else None
        complaint.district_id = dist.id if dist else None
        steps_done.append("location")
        if loc.method in ("none", "vague", "landmark_ambiguous") or loc.confidence < 0.5:
            review_reasons.append(f"location uncertain ({loc.method}, confidence {loc.confidence:.2f})")
        # stash candidates on complaint for the tracking/chat response via attribute
        complaint._location_candidates = loc.candidates  # type: ignore[attr-defined]
        complaint._location_method = loc.method  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        log.exception("location resolution failed")
        review_reasons.append(f"location resolution failed: {e}")
        complaint.location_confidence = 0.0

    # ---- Step 4: duplicate detection ----
    match_review: list[dict] = []
    try:
        matches = await dedup_svc.find_matches(
            db, text=text, category=complaint.category,
            lat=complaint.lat, lon=complaint.lon)
        if matches:
            best = matches[0]
            if best.verdict == "auto_link":
                await dedup_svc.attach_complaint_to_incident(db, complaint, best.incident, best, "auto")
                steps_done.append("auto_linked_incident")
            else:
                match_review = [{
                    "incident_id": m.incident.id,
                    "score": round(m.score, 3),
                    "verdict": m.verdict,
                    "evidence": m.evidence,
                } for m in matches[:3]]
                review_reasons.append("possible duplicate incident(s) need review")
                steps_done.append("dup_review")
        else:
            steps_done.append("no_duplicates")
    except Exception as e:  # noqa: BLE001
        log.exception("dedup failed")
        review_reasons.append(f"duplicate check failed: {e}")

    # ---- Step 5: priority + SLA + routing (deterministic) ----
    try:
        corroboration = 1
        if complaint.incident_id:
            res = await db.execute(select(IncidentReport).where(IncidentReport.incident_id == complaint.incident_id))
            corroboration = len(res.scalars().all()) + 1
        vuln = prio_svc.vulnerability_for(complaint.category, text)
        prio = prio_svc.compute_priority(
            severity_score=complaint.severity_score,
            safety_risk=complaint.safety_risk,
            corroboration=corroboration,
            waiting_hours=0.0,
            vulnerability=vuln,
        )
        complaint.priority_score = prio["score"]
        complaint.priority_band = prio["band"]
        complaint.priority_factors = json.dumps(prio["factors"])

        from ..models import SlaRule
        rules = list((await db.execute(select(SlaRule))).scalars().all())
        created = utcnow()
        complaint.sla_deadline = sla_svc.deadline_for(created, complaint.category, prio["band"], rules)

        dept = await _default_department(db, complaint.category)
        complaint.department_id = dept.id if dept else None
        if dept:
            db.add(Assignment(complaint_id=complaint.id, incident_id=complaint.incident_id,
                              department_id=dept.id, note="auto-routed by category"))

        db.add(SlaRecord(complaint_id=complaint.id, incident_id=complaint.incident_id,
                         deadline=complaint.sla_deadline))
        steps_done.append("priority_sla_routing")
    except Exception as e:  # noqa: BLE001
        log.exception("priority/SLA failed")
        complaint.priority_band = "medium"
        complaint.priority_score = 40.0
        complaint.priority_factors = json.dumps({"error": str(e)})
        review_reasons.append("priority/SLA step failed")

    # ---- status + history ----
    if review_reasons:
        complaint.status = "under_review"
        complaint.review_reason = "; ".join(review_reasons)
    else:
        complaint.status = "under_review"

    db.add(StatusHistory(complaint_id=complaint.id, from_status="", to_status=complaint.status,
                         actor_type="system", note=f"pipeline steps: {', '.join(steps_done)}"))
    db.add(AuditLog(admin_id=None, action="complaint.submitted", entity_type="complaint",
                    entity_id=complaint.id, detail=json.dumps({"public_id": public_id, "source": source})))
    db.add(Notification(kind="new_complaint", complaint_id=complaint.id,
                        title=f"New complaint {public_id}",
                        body=f"{complaint.category} — priority {complaint.priority_band} ({complaint.priority_score})"))

    # ---- incident creation if auto-linked wasn't possible but incident exists? ----
    # If no auto-link: complaint stands alone; an incident is created lazily by
    # dedup review or by the first complaint itself for grouping. For the demo
    # we create an incident for every complaint so grouping always has a target.
    if complaint.incident_id is None:
        inc = Incident(
            title=_incident_title(complaint),
            category=complaint.category,
            lat=complaint.lat, lon=complaint.lon,
            ward_id=complaint.ward_id, district_id=complaint.district_id,
            department_id=complaint.department_id,
            priority_score=complaint.priority_score,
            priority_band=complaint.priority_band,
            priority_factors=complaint.priority_factors,
            sla_deadline=complaint.sla_deadline,
            citizens_affected=1,
        )
        db.add(inc)
        await db.flush()
        db.add(IncidentReport(incident_id=inc.id, complaint_id=complaint.id,
                              match_text_sim=1.0, match_geo_dist_m=0.0,
                              match_evidence=json.dumps({"note": "first report — incident created"}),
                              link_type="auto"))
        complaint.incident_id = inc.id
        db.add(SlaRecord(complaint_id=complaint.id, incident_id=inc.id,
                         deadline=complaint.sla_deadline))

    # update incident priority after possible merge (recompute with corroboration)
    if complaint.incident_id:
        await _refresh_incident_priority(db, complaint.incident_id)

    # stash transient fields for API response
    complaint._pipeline = {  # type: ignore[attr-defined]
        "steps": steps_done,
        "review_reasons": review_reasons,
        "match_candidates": match_review,
        "location_candidates": getattr(complaint, "_location_candidates", []),
        "location_method": getattr(complaint, "_location_method", "none"),
    }
    await db.commit()
    return complaint, tracking_token


def ward_name_for(loc) -> str | None:
    return loc.ward_name


def _incident_title(c: Complaint) -> str:
    desc = (c.description or "").strip().replace("\n", " ")
    return desc[:80] + ("…" if len(desc) > 80 else "")


async def _refresh_incident_priority(db: AsyncSession, incident_id: str):
    """Recompute incident priority with corroboration = member count + waiting."""
    inc_res = await db.execute(select(Incident).where(Incident.id == incident_id))
    inc = inc_res.scalar_one_or_none()
    if inc is None:
        return
    cnt_res = await db.execute(select(IncidentReport).where(IncidentReport.incident_id == incident_id))
    count = len(cnt_res.scalars().all())
    oldest_res = await db.execute(
        select(Complaint.created_at)
        .join(IncidentReport, IncidentReport.complaint_id == Complaint.id)
        .where(IncidentReport.incident_id == incident_id)
        .order_by(Complaint.created_at.asc()).limit(1))
    oldest = oldest_res.scalar_one_or_none() or utcnow()
    waiting_h = max(0.0, (utcnow() - oldest).total_seconds() / 3600.0)

    # average member severity/safety
    sev_res = await db.execute(
        select(Complaint.severity_score, Complaint.safety_risk, Complaint.category)
        .join(IncidentReport, IncidentReport.complaint_id == Complaint.id)
        .where(IncidentReport.incident_id == incident_id))
    rows = sev_res.all()
    sev = sum(r[0] or 45 for r in rows) / max(1, len(rows))
    safety = max(r[1] or 0 for r in rows)
    vuln = prio_svc.vulnerability_for(rows[0][2] if rows else "other")

    prio = prio_svc.compute_priority(severity_score=sev, safety_risk=safety,
                                     corroboration=count, waiting_hours=waiting_h,
                                     vulnerability=vuln)
    inc.priority_score = prio["score"]
    inc.priority_band = prio["band"]
    inc.priority_factors = json.dumps(prio["factors"])
    inc.citizens_affected = count


STATUSES = {"received", "under_review", "inspection_scheduled", "in_progress",
            "awaiting_verification", "resolved", "reopened", "closed"}
