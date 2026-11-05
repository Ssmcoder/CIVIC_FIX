"""CivicFix 360 — FastAPI application entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import Base, SessionLocal, engine
from .routers import admin, chat, complaints

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("civicfix")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    log.info("DB: %s", settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # seed reference data if empty
    async with SessionLocal() as db:
        await _ensure_seed(db)
    yield


async def _ensure_seed(db):
    """Insert reference data (departments, jurisdictions, SLA rules, admins,
    priority config, FAQ) if the DB is empty. Full demo data comes from
    `python -m seed.seed` or the seed script."""
    from sqlalchemy import func, select
    from .models import (
        Admin, Department, FaqDocument, Jurisdiction, PriorityConfig, SlaRule,
    )
    from .taxonomy import CATEGORIES_ORDERED, DEFAULT_PRIORITY_WEIGHTS, DEFAULT_SLA_RULES
    from .auth import hash_password

    if (await db.execute(select(func.count(Admin.id)))).scalar():
        return

    # jurisdictions: Odisha > Khordha > Bhubaneswar > wards
    state = Jurisdiction(level="state", name="Odisha")
    db.add(state)
    await db.flush()
    dist = Jurisdiction(level="district", name="Khordha", parent_id=state.id)
    db.add(dist)
    await db.flush()
    muni = Jurisdiction(level="municipality", name="Bhubaneswar", parent_id=dist.id)
    db.add(muni)
    await db.flush()
    from .services.location import WARDS
    ward_rows = {}
    for wname, (minla, maxla, minlo, maxlo) in WARDS.items():
        w = Jurisdiction(level="ward", name=wname, parent_id=muni.id,
                         min_lat=minla, max_lat=maxla, min_lon=minlo, max_lon=maxlo)
        db.add(w)
        ward_rows[wname] = w
    await db.flush()

    # departments
    dept_defs = [
        ("Road Maintenance", {"roads": True, "categories": ["roads"]}),
        ("Sanitation & Waste", {"waste": True, "categories": ["waste"]}),
        ("Drainage & Waterlogging", {"drainage": True, "categories": ["drainage"]}),
        ("Water Supply", {"water": True, "categories": ["water"]}),
        ("Electrical Services", {"electricity": True, "categories": ["electricity"]}),
        ("Public Safety & Works", {"public_safety": True, "categories": ["public_safety", "other"]}),
    ]
    import json as _json
    for name, cmap in dept_defs:
        db.add(Department(name=name, category_map=_json.dumps(cmap)))

    for cat, band, h, e in DEFAULT_SLA_RULES:
        db.add(SlaRule(category=cat, priority_band=band, deadline_hours=h, escalation_hours=e))

    for k, v in DEFAULT_PRIORITY_WEIGHTS.items():
        db.add(PriorityConfig(key=k, value=v, description=f"Priority weight {k}"))

    # demo admins
    ward12 = ward_rows.get("Ward 12")
    db.add(Admin(email="state@civicfix.demo", username="state_admin",
                 password_hash=hash_password("admin123"), full_name="State Admin",
                 role="state_admin", jurisdiction_id=state.id))
    db.add(Admin(email="district@civicfix.demo", username="district_admin",
                 password_hash=hash_password("admin123"), full_name="District Admin",
                 role="district_admin", jurisdiction_id=dist.id))
    db.add(Admin(email="ward12@civicfix.demo", username="ward12_admin",
                 password_hash=hash_password("admin123"), full_name="Ward 12 Officer",
                 role="ward_admin", jurisdiction_id=ward12.id if ward12 else muni.id))
    db.add(Admin(email="super@civicfix.demo", username="super_admin",
                 password_hash=hash_password("admin123"), full_name="Super Admin",
                 role="super_admin"))

    # FAQ seed
    faqs = [
        ("How do I report a problem?", "Open CivicFix, tap 'Report a problem', describe the issue, confirm the location, and submit. No login needed.", "General"),
        ("How do I track my complaint?", "Use the tracking ID (CFX-YYYY-NNNNN) and the secret shown at submission on the Track page or ask the AI assistant.", "General"),
        ("What do the priority bands mean?", "Critical/High/Medium/Low are computed from severity, safety risk, number of reports, waiting time and infrastructure vulnerability — every factor is shown on the complaint.", "General"),
        ("Why was my complaint grouped with others?", "Reports with similar text, nearby location and same category are grouped into one incident so the department fixes the real problem once.", "General"),
        ("How are departments assigned?", "Each issue category maps to a responsible municipal department; routing is rule-based and workload-aware.", "General"),
        ("Is my information private?", "Contact details are optional and never shown publicly. Location is stored to route the complaint; you can report anonymously.", "Privacy"),
        ("What if the problem isn't fixed?", "After work is marked complete you can confirm the fix or reopen the complaint — reopening alerts the department and extends accountability.", "General"),
        ("What are SLA deadlines?", "Each priority band has a target resolution time. Breaches are escalated automatically and shown publicly on tracking.", "General"),
    ]
    for q, a, d in faqs:
        db.add(FaqDocument(question=q, answer=a, department=d))

    await db.commit()
    log.info("Seeded reference data + demo admins (password: admin123)")


app = FastAPI(title="CivicFix 360", version="0.1.0", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

app.include_router(complaints.router)
app.include_router(complaints.incidents_router)
app.include_router(chat.router)
app.include_router(admin.router)


@app.get("/health")
async def health():
    return {"ok": True, "service": "civicfix-360"}


@app.get("/")
async def root():
    return {"service": "CivicFix 360 API", "docs": "/docs"}
