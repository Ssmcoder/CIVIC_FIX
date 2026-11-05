"""Seed the database with a realistic simulated Odisha/Khordha dataset.

Usage (from repo root or backend/):
    python -m seed.seed            # uses DATABASE_URL from env/.env
    python seed/seed.py            # same

Creates ~160 complaints across 6 categories, English/Hindi/Odia/Hinglish,
with intentional duplicates (same pothole reported 3x, etc.), vague locations,
a few admins, departments, SLA rules, FAQ. Idempotent-ish: skips if complaints
already exist unless --force.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import func, select  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    Complaint, Department, Incident, IncidentReport, Jurisdiction,
    StatusHistory,
)
from app.services import pipeline  # noqa: E402
from app.services.location import GAZETTEER  # noqa: E402

random.seed(42)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ corpus
# (description, lang, category_hint, lat_hint_name or (lat,lon) or None, age_days, status)
POTHole_SCENE = [
    ("There is a huge pothole outside the engineering college gate and two-wheelers are almost falling", "en", "roads", "Engineering College Gate"),
    ("Road damaged near the market entrance, big hole troubling vehicles", "en", "roads", "Main Market"),
    ("Big hole near the market, bikes and cars hitting it daily", "en", "roads", "Main Market"),
    ("College gate ke paas bahut bada gaddha hai, bike waale gir rahe hain", "hinglish", "roads", "Engineering College Gate"),
    ("ଇଞ୍ଜିନିୟରିଂ କଲେଜ ଗେଟ୍ ପାଖରେ ବଡ଼ ଗାଡ଼ା ଅଛି, ବାଇକ୍ ପଡ଼ୁଛି", "odia", "roads", "Engineering College Gate"),
]

SCENES = POTHole_SCENE + [
    # roads
    ("Pothole near railway station crossing, autorickshaws swerving dangerously", "en", "roads", "Railway Station"),
    ("Sadak par gehri driving kharab hai, multiple holes near bus stand", "hinglish", "roads", "Bus Stand"),
    ("Speed breaker broken near Gole Bazar, cars jolting", "en", "roads", "Gole Bazar"),
    ("Footpath near Kalpana Square crumbled, pedestrians at risk", "en", "roads", "Kalpana Square"),
    ("Road crack near airport road widening every week", "en", "roads", "Biju Patnaik Airport"),
    ("Market road fully broken, fruit carts stuck", "en", "roads", "Main Market"),
    ("Gali ke andar sadak kharab, paani jama hone laga", "hinglish", "roads", None),
    # waste
    ("Garbage bin overflowing near temple entrance for a week, smell unbearable", "en", "waste", "Lingaraj Temple"),
    ("Safai nahi ho rahi, kachra ka dher bus stand ke paas", "hinglish", "waste", "Bus Stand"),
    ("Waste not collected in Ward 18 colony, piles of garbage everywhere", "en", "waste", "Ward 18"),
    ("Dustbin full outside college canteen, no pickup since Monday", "en", "waste", "Engineering College Gate"),
    ("Kachra ganjar near market, flies and disease risk", "hinglish", "waste", "Main Market"),
    ("Garbage heap near railway station, stray animals scattering it", "en", "waste", "Railway Station"),
    # drainage
    ("Drain blocked near school gate, rainwater flooding the road", "en", "drainage", "Kendriya Vidyalaya Area"),
    ("Nalika band hai, paani road par jama ho raha hai bus stand ke paas", "hinglish", "drainage", "Bus Stand"),
    ("Choked drain near hospital causing waterlogging every monsoon", "en", "drainage", "Marichi Hospital"),
    ("Drainage line broken near Rajbhavan, sewage smell everywhere", "en", "drainage", "Rajbhavan"),
    ("Gutter overflow near park, stagnant water breeding mosquitoes", "en", "drainage", "Bhatia Park"),
    # water
    ("Water leakage from pipeline near colony gate, road damaged", "en", "water", "Ward 12"),
    ("Pani nahi aa raha 3 din se, tank empty near airport colony", "hinglish", "water", "Biju Patnaik Airport"),
    ("Pipe burst near master canteen, water flooding shopfronts", "en", "water", "Master Canteen"),
    ("No water supply in Ward 7 since morning, tanker needed", "en", "water", "Ward 7"),
    ("Jal nali se leak ho raha hai, sadak par paani bhara hai", "hinglish", "water", None),
    # electricity
    ("Streetlight broken near park entrance, dark and unsafe at night", "en", "electricity", "Bhatia Park"),
    ("Bijli ke pole ke paas wire latka hua hai, bahut khatarnak", "hinglish", "electricity", None),
    ("Multiple streetlights dead along market road", "en", "electricity", "Main Market"),
    ("Transformer making loud noise near college, sparks at night", "en", "electricity", "Engineering College Gate"),
    ("Electric pole tilted near bus stand after rain, wires low", "en", "electricity", "Bus Stand"),
    # public safety
    ("Exposed live wires hanging near school boundary wall, children at risk", "en", "public_safety", "Kendriya Vidyalaya Area"),
    ("Open manhole without cover near market, pedestrians falling risk", "en", "public_safety", "Main Market"),
    ("Collapsed boundary wall near railway station, debris on tracks", "en", "public_safety", "Railway Station"),
    ("Dangerous hanging cable near temple steps, devotees climbing", "en", "public_safety", "Lingaraj Temple"),
    ("Khadar bhanga hua hai college ke paas, gaadi gir sakti hai", "hinglish", "public_safety", "Engineering College Gate"),
    # vague-location extras (no landmark) to exercise geocoding candidates
    ("Huge pothole near the main market entrance area", "en", "roads", None),
    ("Blocked drain somewhere near the railway station side", "en", "drainage", None),
    ("Garbage overflowing near college area", "en", "waste", None),
    ("Streetlight not working near bus stand road", "en", "electricity", None),
    ("Water leaking near hospital road", "en", "water", None),
    # Odia samples
    ("ରାସ୍ତାରେ ବଡ଼ ଗାଡ଼ା ଅଛି ମାର୍କେଟ୍ ପାଖରେ", "odia", "roads", "Main Market"),
    ("ବର୍ଷା ଜଳ ନାଳିରେ ଜମି ଯାଇଛି", "odia", "drainage", None),
    ("ପାଣି ଲିକ୍ ହେଉଛି ମୁଖ୍ୟ ରାସ୍ତାରେ", "odia", "water", None),
    ("ବିଜୁଳି ପୋଲ୍ ଭାଙ୍ଗିଯାଇଛି ରାତିରେ ଅନ୍ଧାର", "odia", "electricity", None),
    ("ଛୋଟ ଗାଡ଼ା ଆପାଣଙ୍କ ପାଖରେ ଖରାପ ଅଛି", "odia", "roads", None),
]

STATUSES = ["received", "under_review", "inspection_scheduled", "in_progress",
            "awaiting_verification", "resolved", "reopened", "closed"]


async def seed(db):
    # departments should exist from lifespan seed; ensure anyway
    dep_count = (await db.execute(select(func.count(Department.id)))).scalar()
    if not dep_count:
        print("Run app once first (lifespan seeds reference data), or seed manually.")
        return

    existing = (await db.execute(select(func.count(Complaint.id)))).scalar()
    if existing and "--force" not in sys.argv:
        print(f"Complaints already exist ({existing}). Use --force to reseed.")
        return

    # resolve landmark name -> coords
    gaz = {g[0].lower(): g for g in GAZETTEER}

    count = 0
    for i, (desc, lang, cat_hint, landmark, age_days, *_rest) in enumerate(SCENES):
        # replicate scenes to reach 150+
        reps = 6 if i < len(POTHole_SCENE) else (4 if i < 20 else 2)
        for r in range(reps):
            lat = lon = None
            ward = None
            method_confirmed = False
            if landmark and landmark.lower() in gaz:
                g = gaz[landmark.lower()]
                lat, lon, ward = g[2], g[3], g[4]
                method_confirmed = r % 2 == 0  # half confirmed
            elif landmark and landmark.startswith("Ward"):
                # ward centre approx
                wmap = {"Ward 18": (20.317, 85.840), "Ward 7": (20.277, 85.815), "Ward 12": (20.302, 85.822)}
                lat, lon = wmap.get(landmark, (20.30, 85.82))
                ward = landmark
                method_confirmed = True

            created = utcnow() - timedelta(days=age_days + random.randint(0, 5),
                                           hours=random.randint(0, 23))
            source = random.choice(["form", "form", "chat", "voice"])
            c, token = await pipeline.create_complaint(
                db, description=desc, lat=lat, lon=lon,
                landmark_text=landmark, manual_location_confirmed=method_confirmed,
                language=lang, source=source,
                transcript=desc if source == "voice" else None,
                anonymous=random.random() < 0.1,
                category_override=cat_hint if random.random() < 0.3 else None,
            )
            # backdate created_at so SLA/waiting look realistic
            c.created_at = created
            c.updated_at = created
            # assign a random plausible status
            if random.random() < 0.5:
                c.status = random.choice(["in_progress", "inspection_scheduled",
                                          "awaiting_verification", "resolved", "closed"])
                if c.status in ("resolved", "closed"):
                    c.resolved_at = created + timedelta(days=random.randint(1, 6))
                    c.status = "closed" if random.random() < 0.5 else "resolved"
            else:
                c.status = random.choice(["received", "under_review", "under_review", "in_progress"])
            # regenerate SLA deadline relative to backdated created
            from app.models import SlaRule
            rules = list((await db.execute(select(SlaRule))).scalars().all())
            from app.services.sla import deadline_for
            c.sla_deadline = deadline_for(created, c.category, c.priority_band, rules)
            if c.sla_deadline < utcnow() and c.status not in ("resolved", "closed", "awaiting_verification"):
                c.sla_breached = True
            db.add(StatusHistory(complaint_id=c.id, incident_id=c.incident_id,
                                 from_status="", to_status=c.status,
                                 actor_type="system", note="seeded"))
            count += 1
            if count % 25 == 0:
                await db.commit()
                print(f"  seeded {count} complaints...")

    await db.commit()
    print(f"Done. {count} complaints seeded.")


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        await seed(db)


if __name__ == "__main__":
    asyncio.run(main())
