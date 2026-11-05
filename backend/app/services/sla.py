"""SLA rules + breach detection. Deterministic, configurable via sla_rules."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import SlaRule
from ..taxonomy import DEFAULT_SLA_RULES


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def rule_hours(category: str, band: str, rules: list[SlaRule] | None = None) -> tuple[int, int]:
    """Return (deadline_hours, escalation_hours). Category-specific wins over '*'."""
    candidates = rules or []
    chosen = None
    for r in candidates:
        if r.priority_band == band and r.category == category:
            chosen = r
            break
    if chosen is None:
        for r in candidates:
            if r.priority_band == band and r.category == "*":
                chosen = r
                break
    if chosen is None:
        for cat, band_, h, e in DEFAULT_SLA_RULES:
            if band_ == band and cat in (category, "*"):
                return h, e
    return (chosen.deadline_hours, chosen.escalation_hours) if chosen else (168, 48)


async def ensure_default_rules(db: AsyncSession):
    res = await db.execute(select(SlaRule))
    if res.scalars().first() is not None:
        return
    for cat, band, h, e in DEFAULT_SLA_RULES:
        db.add(SlaRule(category=cat, priority_band=band, deadline_hours=h, escalation_hours=e))
    await db.commit()


def deadline_for(created_at: datetime, category: str, band: str,
                 rules: list[SlaRule] | None = None) -> datetime:
    hours, _ = rule_hours(category, band, rules)
    return created_at + timedelta(hours=hours)


async def find_breaches(db: AsyncSession) -> list:
    """Return complaints past SLA deadline not yet resolved/closed."""
    from ..models import Complaint
    now = utcnow()
    res = await db.execute(select(Complaint).where(
        Complaint.sla_deadline.isnot(None),
        Complaint.sla_deadline < now,
        Complaint.sla_breached == False,  # noqa: E712
        Complaint.status.notin_(["resolved", "closed", "awaiting_verification"]),
    ))
    return list(res.scalars().all())
