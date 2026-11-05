"""End-to-end API tests: jurisdiction access, dedup, priority, scope guard,
no-silent-rejection."""
import json
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_civicfix.db"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["TRACKING_TOKEN_SECRET"] = "test-tracking"
os.environ["EMBEDDING_BACKEND"] = "tfidf"  # no model downloads in CI

from app.main import app  # noqa: E402
from app.database import Base, engine, SessionLocal  # noqa: E402


@pytest_asyncio.fixture()
async def client():
    # fresh schema (drop/create); file stays open on Windows so no unlink
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    # seed reference data via lifespan-less manual call
    async with SessionLocal() as db:
        from app.main import _ensure_seed
        await _ensure_seed(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _login(client, username="ward12_admin", password="admin123"):
    r = await client.post("/admin/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# --------------------------------------------------------------- complaints

@pytest.mark.asyncio
async def test_submit_complaint_returns_id_and_secret(client):
    r = await client.post("/complaints", json={
        "description": "Huge pothole outside engineering college gate, two-wheelers falling",
        "lat": 20.2969, "lon": 85.8242, "manual_location_confirmed": True,
        "language": "en", "source": "form"})
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["public_id"].startswith("CFX-")
    assert data["tracking_token"]
    assert data["category"] == "roads"
    assert data["priority_band"] in ("critical", "high", "medium", "low")
    assert data["priority_factors"]  # explanation present


@pytest.mark.asyncio
async def test_track_requires_secret(client):
    r = await client.post("/complaints", json={
        "description": "Garbage bin overflowing near temple", "language": "en"})
    pid = r.json()["public_id"]
    # guessing ID alone must NOT work
    r2 = await client.get(f"/complaints/track/{pid}")
    assert r2.status_code == 404
    # with secret works
    r3 = await client.get(f"/complaints/track/{r.json()['tracking_token']}")
    assert r3.status_code == 200
    assert r3.json()["public_id"] == pid


@pytest.mark.asyncio
async def test_duplicate_grouping(client):
    """Three differently-worded reports of the same pothole -> one incident."""
    ids = []
    for desc in [
        "Huge pothole outside engineering college gate, bikes falling",
        "Road damaged near college gate, big hole troubling vehicles",
        "Big hole near engineering college, two wheelers almost falling daily",
    ]:
        r = await client.post("/complaints", json={
            "description": desc, "lat": 20.2969, "lon": 85.8242,
            "manual_location_confirmed": True, "language": "en"})
        assert r.status_code == 201
        ids.append(r.json())
    inc_ids = {d["incident_id"] for d in ids}
    assert len(inc_ids) == 1, f"expected 1 incident, got {inc_ids}"


@pytest.mark.asyncio
async def test_no_silent_rejection_on_garbage_input(client):
    r = await client.post("/complaints", json={
        "description": "asdfqwer zxcv !!! ???", "language": "en"})
    assert r.status_code == 201  # NEVER rejected
    d = r.json()
    assert d["category"] in ("other", "roads", "waste", "drainage", "water", "electricity", "public_safety")


@pytest.mark.asyncio
async def test_priority_score_transparent(client):
    r = await client.post("/complaints", json={
        "description": "Exposed live wires near school boundary, children at risk of electrocution",
        "lat": 20.298, "lon": 85.82, "manual_location_confirmed": True})
    d = r.json()
    assert d["priority_score"] > 0
    f = d["priority_factors"]
    assert "severity" in f and "safety_risk" in f and "corroboration" in f


# --------------------------------------------------------------- admin auth

@pytest.mark.asyncio
async def test_admin_login_and_jurisdiction_isolation(client):
    headers = await _login(client)
    # ward12 admin sees dashboard scoped to ward 12
    r = await client.get("/admin/dashboard", headers=headers)
    assert r.status_code == 200

    # create a complaint outside ward 12 (railway station ~ ward 8)
    r2 = await client.post("/complaints", json={
        "description": "Pothole near railway station crossing", "language": "en",
        "lat": 20.2560, "lon": 85.8440, "manual_location_confirmed": True})
    outside_id = r2.json()["public_id"]

    # ward12 admin must NOT see it in list
    r3 = await client.get("/admin/complaints", headers=headers)
    ids = [i["public_id"] for i in r3.json()["items"]]
    assert outside_id not in ids, "Ward admin leaked out-of-jurisdiction complaint"

    # and direct access must 403
    r4 = await client.get(f"/admin/complaints/{outside_id}", headers=headers)
    assert r4.status_code == 403


@pytest.mark.asyncio
async def test_super_admin_sees_everything(client):
    headers = await _login(client, "super_admin")
    r = await client.get("/admin/dashboard", headers=headers)
    assert r.status_code == 200
    assert r.json()["jurisdiction"]["role"] == "super_admin"


@pytest.mark.asyncio
async def test_resolve_requires_evidence(client):
    headers = await _login(client, "super_admin")
    r = await client.post("/complaints", json={
        "description": "Blocked drain near bus stand", "language": "en"})
    pid = r.json()["public_id"]
    r2 = await client.post(f"/admin/complaints/{pid}/resolve", headers=headers,
                           json={"note": "fixed"})
    assert r2.status_code == 400  # no evidence -> refused


# ------------------------------------------------------------------ chat

@pytest.mark.asyncio
async def test_chat_scope_guard_redirects_offtopic(client):
    r = await client.post("/chat/sessions", json={})
    sid = r.json()["session_id"]
    r2 = await client.post(f"/chat/sessions/{sid}/messages",
                           json={"content": "write me a python script to scrape websites"})
    assert r2.status_code == 200
    assert "civic" in r2.json()["reply"].lower() or "CivicFix" in r2.json()["reply"]
    assert r2.json()["scope"] in ("out_of_scope", "unclear")


@pytest.mark.asyncio
async def test_chat_reports_civic_issue(client):
    r = await client.post("/chat/sessions", json={})
    sid = r.json()["session_id"]
    r2 = await client.post(f"/chat/sessions/{sid}/messages",
                           json={"content": "There's a huge pothole outside the engineering college gate"})
    assert r2.status_code == 200
    d = r2.json()
    assert d["scope"] == "civic"
    # should ask follow-up or produce intake card
    assert d["card"] or "location" in d["reply"].lower() or "describe" in d["reply"].lower()


@pytest.mark.asyncio
async def test_chat_never_invents_status(client):
    r = await client.post("/chat/sessions", json={})
    sid = r.json()["session_id"]
    r2 = await client.post(f"/chat/sessions/{sid}/messages",
                           json={"content": "what's the status of CFX-2026-00001?"})
    d = r2.json()
    # must ask for secret or say not found — never fabricate
    assert "secret" in d["reply"].lower() or "couldn't" in d["reply"].lower()
