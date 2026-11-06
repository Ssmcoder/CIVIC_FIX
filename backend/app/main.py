"""CivicFix 360 — FastAPI application entrypoint (hardened)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import func, select

from .config import get_settings
from .database import Base, SessionLocal, engine
from .errors import (
    BodySizeMiddleware, RequestIdMiddleware, SecurityHeadersMiddleware,
    install_redaction, register_exception_handlers,
)
from .routers import admin, chat, complaints

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
install_redaction()
log = logging.getLogger("civicfix")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # CF-13: never log credentials — driver+host only
    try:
        u = urlparse(settings.database_url.replace("+aiosqlite", "").replace("sqlite", "sqlite"))
        log.info("DB driver=%s host=%s", u.scheme or "sqlite", u.hostname or "local-file")
    except Exception:  # noqa: BLE001
        log.info("DB configured (URL redacted)")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        await _ensure_reference_data(db)
    yield


async def _ensure_reference_data(db):
    """Seed reference data ONLY (departments, jurisdictions, SLA rules,
    priority config, FAQ). NO admin accounts — CF-01: admins are created
    exclusively via `python -m app.cli create-superadmin`."""
    from .models import (
        Department, FaqDocument, Jurisdiction, PriorityConfig, SlaRule,
    )
    from .taxonomy import DEFAULT_PRIORITY_WEIGHTS, DEFAULT_SLA_RULES
    import json as _json

    if (await db.execute(select(func.count(Department.id)))).scalar():
        return

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
    for wname, (minla, maxla, minlo, maxlo) in WARDS.items():
        db.add(Jurisdiction(level="ward", name=wname, parent_id=muni.id,
                            min_lat=minla, max_lat=maxla, min_lon=minlo, max_lon=maxlo))
    await db.flush()

    for name, cmap in [
        ("Road Maintenance", {"categories": ["roads"]}),
        ("Sanitation & Waste", {"categories": ["waste"]}),
        ("Drainage & Waterlogging", {"categories": ["drainage"]}),
        ("Water Supply", {"categories": ["water"]}),
        ("Electrical Services", {"categories": ["electricity"]}),
        ("Public Safety & Works", {"categories": ["public_safety", "other"]}),
    ]:
        db.add(Department(name=name, category_map=_json.dumps(cmap)))
    for cat, band, h, e in DEFAULT_SLA_RULES:
        db.add(SlaRule(category=cat, priority_band=band, deadline_hours=h, escalation_hours=e))
    for k, v in DEFAULT_PRIORITY_WEIGHTS.items():
        db.add(PriorityConfig(key=k, value=v, description=f"Priority weight {k}"))
    for q, a, d in [
        ("How do I report a problem?", "Open CivicFix, tap 'Report a problem', describe the issue, confirm location, submit. No login needed.", "General"),
        ("How do I track my complaint?", "Use the tracking ID and secret shown at submission, or ask the AI assistant.", "General"),
        ("What do priority bands mean?", "Computed from severity, safety risk, report count, waiting time and infrastructure vulnerability — all factors are shown.", "General"),
        ("Why grouped with other complaints?", "Similar text + nearby location + same category are grouped into one incident.", "General"),
        ("Is my information private?", "Contact details are optional and never public. You can report anonymously.", "Privacy"),
        ("What if it's not fixed?", "After work is marked complete you can confirm or reopen — reopening alerts the department.", "General"),
    ]:
        db.add(FaqDocument(question=q, answer=a, department=d))
    await db.commit()
    log.info("Seeded reference data (no admin accounts — use app.cli)")


def create_app() -> FastAPI:
    settings = get_settings()
    docs = settings.enable_docs and not settings.is_production
    app = FastAPI(title="CivicFix 360", version="0.2.0", lifespan=lifespan,
                  docs_url="/docs" if docs else None,
                  redoc_url="/redoc" if docs else None,
                  openapi_url="/openapi.json" if docs else None)

    app.add_middleware(TrustedHostMiddleware,
                       allowed_hosts=[h.strip() for h in settings.allowed_hosts.split(",")])
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(BodySizeMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Chat-Token"],
    )

    register_exception_handlers(app)
    app.include_router(complaints.router)
    app.include_router(complaints.incidents_router)
    app.include_router(chat.router)
    app.include_router(admin.auth_router)
    app.include_router(admin.router)

    @app.get("/health")
    async def health():
        return {"ok": True, "service": "civicfix-360"}

    @app.get("/config/public")
    async def public_config():
        from .taxonomy import CATEGORIES, CATEGORIES_ORDERED, STATUSES
        return {
            "max_upload_bytes": settings.max_upload_bytes,
            "max_images_per_complaint": settings.max_images_per_complaint,
            "allowed_image_types": ["image/jpeg", "image/png", "image/webp"],
            "max_description_length": 2000,
            "max_transcript_length": 5000,
            "max_nearby_radius_m": settings.nearby_max_radius_m,
            "categories": CATEGORIES_ORDERED,
            "category_labels": CATEGORIES,
            "statuses": STATUSES,
            "feature_flags": {
                "ml_retrain_enabled": settings.enable_ml_retrain,
                "mfa_required_roles": sorted(settings.mfa_roles),
            },
        }

    return app


app = create_app()
