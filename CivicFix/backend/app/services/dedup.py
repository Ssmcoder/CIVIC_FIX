"""Duplicate detection: embedding similarity + geo distance + category + time.

Auto-link only when all signals agree strongly; medium matches are flagged for
review / citizen confirmation. Similarity alone NEVER merges.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Complaint, Incident, IncidentReport
from ..services.location import haversine_m
from .embeddings import calibrated_cosine, embed_texts


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class MatchResult:
    incident: Incident
    rep_text: str
    text_sim: float
    geo_dist_m: float | None
    category_match: bool
    time_gap_hours: float
    score: float
    verdict: str  # auto_link | review | none
    evidence: dict


def _geo_score(dist_m: float | None, max_m: float) -> float:
    if dist_m is None:
        return 0.4  # unknown location: neutral, slightly penalised
    if dist_m <= 50:
        return 1.0
    if dist_m >= max_m:
        return 0.0
    return 1.0 - (dist_m - 50) / (max_m - 50)


async def _incident_member_texts(db: AsyncSession, incidents: list[Incident]) -> dict[str, list[str]]:
    """All member complaint texts per incident (match against each, take max)."""
    ids = [i.id for i in incidents]
    if not ids:
        return {}
    res = await db.execute(
        select(IncidentReport.incident_id, Complaint.description)
        .join(Complaint, Complaint.id == IncidentReport.complaint_id)
        .where(IncidentReport.incident_id.in_(ids))
    )
    texts: dict[str, list[str]] = {}
    for inc_id, desc in res.all():
        if desc:
            texts.setdefault(inc_id, []).append(desc[:1000])
    return texts


async def find_matches(db: AsyncSession, *, text: str, category: str,
                       lat: float | None, lon: float | None) -> list[MatchResult]:
    settings = get_settings()
    cutoff = utcnow() - timedelta(days=settings.dedup_time_window_days)

    res = await db.execute(select(Incident).where(
        Incident.status.in_(["open", "in_progress", "awaiting_verification", "reopened"]),
        Incident.created_at >= cutoff,
    ))
    incidents = list(res.scalars().all())
    if not incidents:
        return []

    member_texts = await _incident_member_texts(db, incidents)
    flat = [text]
    for inc in incidents:
        flat.extend(member_texts.get(inc.id) or [inc.title or ""])
    embs = embed_texts(flat)
    q_emb = embs[0]

    # map embedding rows to incidents (variable members per incident)
    inc_emb_rows: dict[str, list[int]] = {}
    row = 1
    for inc in incidents:
        members = member_texts.get(inc.id) or [inc.title or ""]
        inc_emb_rows[inc.id] = list(range(row, row + len(members)))
        row += len(members)

    out: list[MatchResult] = []
    for inc in incidents:
        rows = inc_emb_rows[inc.id]
        # best similarity across member complaints
        text_sim = max(float(calibrated_cosine(q_emb, embs[r])) for r in rows)

        dist = None
        if lat is not None and lon is not None and inc.lat is not None and inc.lon is not None:
            dist = haversine_m(lat, lon, inc.lat, inc.lon)

        cat_match = (category == inc.category) or category == "other" or inc.category == "other"
        time_gap = max(0.0, (utcnow() - inc.created_at).total_seconds() / 3600.0)
        geo = _geo_score(dist, settings.dedup_max_distance_m)
        cat_score = 1.0 if cat_match else 0.0
        score = 0.5 * text_sim + 0.3 * geo + 0.2 * cat_score

        if score >= settings.dedup_auto_link_threshold and cat_match and text_sim >= 0.55:
            verdict = "auto_link"
        elif score >= settings.dedup_review_threshold:
            verdict = "review"
        else:
            verdict = "none"

        evidence = {
            "text_similarity": round(text_sim, 3),
            "geo_distance_m": round(dist, 1) if dist is not None else None,
            "geo_score": round(geo, 3),
            "category_match": cat_match,
            "time_gap_hours": round(time_gap, 1),
            "combined_score": round(score, 3),
            "thresholds": {
                "auto_link": settings.dedup_auto_link_threshold,
                "review": settings.dedup_review_threshold,
                "max_distance_m": settings.dedup_max_distance_m,
            },
        }
        if verdict != "none":
            out.append(MatchResult(incident=inc,
                                   rep_text=" | ".join(member_texts.get(inc.id, [])[:2]),
                                   text_sim=text_sim, geo_dist_m=dist,
                                   category_match=cat_match, time_gap_hours=time_gap,
                                   score=score, verdict=verdict, evidence=evidence))

    out.sort(key=lambda m: m.score, reverse=True)
    return out


async def attach_complaint_to_incident(db: AsyncSession, complaint: Complaint,
                                       incident: Incident, match: MatchResult,
                                       link_type: str = "auto") -> IncidentReport:
    rep = IncidentReport(
        incident_id=incident.id, complaint_id=complaint.id,
        match_text_sim=match.text_sim,
        match_geo_dist_m=match.geo_dist_m if match.geo_dist_m is not None else -1,
        match_evidence=json.dumps(match.evidence), link_type=link_type,
    )
    db.add(rep)
    complaint.incident_id = incident.id
    incident.citizens_affected = (incident.citizens_affected or 1) + 1
    return rep
