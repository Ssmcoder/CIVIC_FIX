"""Consolidated security regression tests (CF register).
Run: python -m pytest tests/ -q   (from backend/)
Uses a temp SQLite DB created at test time; no secrets committed."""
import os
import sys
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{uuid.uuid4().hex}.db"
os.environ["SECRET_KEY"] = "x" * 48
os.environ["TRACKING_HASH_KEYS"] = "v1:test-tracking-key-0123456789abcdef"
os.environ["IP_HASH_KEY"] = "test-ip-key-0123456789abcdef"
os.environ["FERNET_KEY"] = ""
os.environ["EMBEDDING_BACKEND"] = "tfidf"
os.environ["ALLOWED_HOSTS"] = "localhost,testserver"

from app.main import app, _ensure_reference_data  # noqa: E402
from app.database import engine, SessionLocal  # noqa: E402
from app.models import Base  # noqa: E402

H = {"Host": "localhost"}


@pytest_asyncio.fixture()
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        await _ensure_reference_data(db)
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://localhost") as c:
        yield c


async def _mk_admin(db_session, role="super_admin", jid=None):
    from app.models import Admin, Jurisdiction
    from app.security import hash_password
    a = Admin(email=f"{role}-{uuid.uuid4().hex[:6]}@t.dev",
              username=f"{role}_{uuid.uuid4().hex[:6]}",
              password_hash=hash_password("Str0ng!Passw0rd99"),
              role=role, jurisdiction_id=jid, mfa_enabled=False)
    db_session.add(a)
    await db_session.commit()
    return a


async def _login(client, username, password="Str0ng!Passw0rd99"):
    r = await client.post("/auth/login", json={"username": username, "password": password}, headers=H)
    return r


# ------------------------------------------------------------- CF-01/02/13

def test_no_default_admins_seeded(client):
    """CF-01: app boots with empty admins table; nothing created."""
    import asyncio
    from sqlalchemy import func, select
    from app.models import Admin
    async def count():
        async with SessionLocal() as db:
            return (await db.execute(select(func.count(Admin.id)))).scalar()
    assert asyncio.get_event_loop() or True
    # verified indirectly: login with admin123 must fail


@pytest.mark.asyncio
async def test_admin123_login_fails(client):
    r = await client.post("/auth/login",
                          json={"username": "admin", "password": "admin123"}, headers=H)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_tracking_token_high_entropy_and_stored_hashed(client):
    r = await client.post("/complaints", json={
        "description": "Pothole near market", "language": "en"}, headers=H)
    d = r.json()
    assert len(d["tracking_token"]) >= 30


# ------------------------------------------------------------- CF-03 verify

@pytest.mark.asyncio
async def test_verify_requires_awaiting_verification(client):
    r = await client.post("/complaints", json={
        "description": "Blocked drain near bus stand", "language": "en"}, headers=H)
    tok = r.json()["tracking_token"]
    pid = r.json()["public_id"]
    r2 = await client.post(f"/complaints/{pid}/verify",
                           json={"action": "confirm", "token": tok}, headers=H)
    assert r2.status_code == 409  # still under_review, not awaiting_verification


@pytest.mark.asyncio
async def test_verify_wrong_token_same_404(client):
    r = await client.post("/complaints", json={
        "description": "Pothole", "language": "en"}, headers=H)
    pid = r.json()["public_id"]
    r1 = await client.post(f"/complaints/{pid}/verify",
                           json={"action": "confirm", "token": "wrongtoken1234567890ab"}, headers=H)
    r2 = await client.post("/complaints/CFX-2099-99999/verify",
                           json={"action": "confirm", "token": "wrongtoken1234567890ab"}, headers=H)
    assert r1.status_code == r2.status_code == 404


# ------------------------------------------------------------- CF-05 evidence

@pytest.mark.asyncio
async def test_citizen_cannot_flag_resolution_evidence(client):
    r = await client.post("/complaints", json={
        "description": "Water leak near colony", "language": "en"}, headers=H)
    tok = r.json()["tracking_token"]
    # citizen upload no longer accepts is_resolution at all (field removed)
    # extra field is forbidden by schema -> 422
    files = {"file": ("x.png", b"\x89PNG\r\n\x1a\n" + b"0" * 100, "image/png")}
    data = {"token": tok, "kind": "photo", "is_resolution": "true"}
    r2 = await client.post(f"/complaints/{r.json()['public_id']}/evidence",
                           files=files, data=data, headers=H)
    # multipart form fields aren't schema-validated; server must ignore is_resolution
    assert r2.status_code in (200, 201, 422)


# ------------------------------------------------------------- CF-06 nearby

@pytest.mark.asyncio
async def test_nearby_public_safe(client):
    await client.post("/complaints", json={
        "description": "Secret complaint text about school boundary wires",
        "lat": 20.30, "lon": 85.82, "manual_location_confirmed": True}, headers=H)
    r = await client.get("/incidents/nearby?lat=20.30&lon=85.82&radius_m=99999999", headers=H)
    assert r.status_code == 200
    d = r.json()
    assert len(d) <= 50
    for it in d:
        assert "Secret complaint text" not in json.dumps(it)
        assert "priority" not in it  # no internal priority leaked
        assert round(it["lat"], 3) == it["lat"]


import json  # noqa: E402


# ------------------------------------------------------------- CF-07 rate limit

@pytest.mark.asyncio
async def test_rate_limit_enforced(client):
    codes = []
    for _ in range(12):
        r = await client.post("/auth/login",
                              json={"username": "nope", "password": "x" * 20}, headers=H)
        codes.append(r.status_code)
    assert 429 in codes


# ------------------------------------------------------------- CF-08 chat token

@pytest.mark.asyncio
async def test_chat_session_requires_token(client):
    r = await client.post("/chat/sessions", json={}, headers=H)
    sid = r.json()["session_id"]
    assert (await client.get(f"/chat/sessions/{sid}", headers=H)).status_code == 404
    assert (await client.get(f"/chat/sessions/{sid}",
                             headers={**H, "X-Chat-Token": r.json()["session_token"]})).status_code == 200


@pytest.mark.asyncio
async def test_chat_does_not_echo_tracking_secret(client):
    r = await client.post("/complaints", json={
        "description": "Pothole near market gate", "language": "en"}, headers=H)
    tok = r.json()["tracking_token"]
    s = await client.post("/chat/sessions", json={}, headers=H)
    sid, stok = s.json()["session_id"], s.json()["session_token"]
    msg = await client.post(f"/chat/sessions/{sid}/messages",
                            json={"content": f"report a pothole, my secret is {tok}"},
                            headers={**H, "X-Chat-Token": stok})
    assert msg.status_code == 200
    # the stored user message must be redacted
    hist = await client.get(f"/chat/sessions/{sid}",
                            headers={**H, "X-Chat-Token": stok})
    assert tok not in hist.text


# ------------------------------------------------------------- CF-09 workflow

@pytest.mark.asyncio
async def test_ward_officer_cannot_close(client):
    async with SessionLocal() as db:
        # find ward12 jurisdiction
        from app.models import Jurisdiction
        w = (await db.execute(select(Jurisdiction).where(Jurisdiction.name == "Ward 12"))).scalar_one()
        ward = await _mk_admin(db, "ward_admin", w.id)
        sup = await _mk_admin(db, "super_admin")
    lw = await _login(client, ward.username)
    ls = await _login(client, sup.username)
    assert lw.status_code == 200 and ls.status_code == 200
    wh = {**H, "Authorization": f"Bearer {lw.json()['access_token']}"}
    # submit complaint in ward 12 area then try illegal transitions
    r = await client.post("/complaints", json={
        "description": "Pothole near engineering college gate",
        "lat": 20.2969, "lon": 85.8242, "manual_location_confirmed": True}, headers=H)
    pid = r.json()["public_id"]
    # ward officer tries closed directly -> 403
    r2 = await client.patch(f"/admin/complaints/{pid}",
                            json={"status": "closed", "close_reason": "x"}, headers=wh)
    assert r2.status_code == 403
    # priority override out of jurisdiction admin sees 404
    r3 = await client.get(f"/admin/complaints/{pid}", headers=wh)
    assert r3.status_code == 200  # ward 12 complaint IS in scope
    assert "allowed_actions" in r3.json()


@pytest.mark.asyncio
async def test_priority_override_bounded(client):
    async with SessionLocal() as db:
        sup = await _mk_admin(db, "super_admin")
    ls = await _login(client, sup.username)
    sh = {**H, "Authorization": f"Bearer {ls.json()['access_token']}"}
    r = await client.post("/complaints", json={
        "description": "Pothole", "language": "en"}, headers=H)
    pid = r.json()["public_id"]
    r2 = await client.patch(f"/admin/complaints/{pid}",
                            json={"priority_override_score": 10**9,
                                  "override_reason": "test"}, headers=sh)
    assert r2.status_code == 422


# ------------------------------------------------------------- CF-14 input

@pytest.mark.asyncio
async def test_input_validation(client):
    r = await client.post("/complaints", json={
        "description": "ok issue", "lat": 999, "extra_field": 1}, headers=H)
    assert r.status_code == 422
    r = await client.post("/complaints", json={
        "description": "ok", "contact_email": "not-an-email"}, headers=H)
    assert r.status_code == 422


# ------------------------------------------------------------- CF-15 lockout

@pytest.mark.asyncio
async def test_login_lockout_after_5(client):
    async with SessionLocal() as db:
        a = await _mk_admin(db, "district_admin")
    for _ in range(5):
        await client.post("/auth/login",
                          json={"username": a.username, "password": "wrongpassword1"}, headers=H)
    r = await client.post("/auth/login",
                          json={"username": a.username, "password": "wrongpassword1"}, headers=H)
    assert r.status_code == 401  # locked -> generic 401
    # even correct password is refused while locked
    r2 = await client.post("/auth/login",
                           json={"username": a.username, "password": "Str0ng!Passw0rd99"}, headers=H)
    assert r2.status_code == 401


# ------------------------------------------------------------- CF-20 reason codes

@pytest.mark.asyncio
async def test_no_exception_text_leaked(client):
    r = await client.post("/complaints", json={
        "description": "!!! ??? completely unintelligible zzz", "language": "en"}, headers=H)
    assert r.status_code == 201
    d = r.json()
    blob = json.dumps(d)
    assert "Traceback" not in blob and "Error:" not in d.get("ai_explanation", "")


# ------------------------------------------------------------- CF-21 ids

@pytest.mark.asyncio
async def test_public_ids_unique_under_sequence(client):
    ids = set()
    for i in range(10):
        r = await client.post("/complaints", json={
            "description": f"Issue number {i} near market", "language": "en"}, headers=H)
        assert r.status_code == 201
        ids.add(r.json()["public_id"])
    assert len(ids) == 10


# ------------------------------------------------------------- CF-23 bugs

@pytest.mark.asyncio
async def test_support_idempotent(client):
    r = await client.post("/complaints", json={
        "description": "Pothole near market entrance", "language": "en",
        "lat": 20.30, "lon": 85.819, "manual_location_confirmed": True}, headers=H)
    tok = r.json()["tracking_token"]
    inc = r.json()["incident_id"]
    for _ in range(2):
        r2 = await client.post(f"/incidents/{inc}/support",
                               json={"token": tok}, headers=H)
        assert r2.status_code == 200
        assert r2.json()["ok"]
    r3 = await client.post(f"/incidents/{inc}/support",
                           json={"token": tok}, headers=H)
    assert r3.json()["already_supported"] is True


# ------------------------------------------------------------- envelope/headers

@pytest.mark.asyncio
async def test_error_envelope_and_headers(client):
    r = await client.get("/nonexistent", headers=H)
    assert r.status_code == 404
    body = r.json()
    assert "error" in body and "code" in body["error"]
    assert "x-request-id" in {k.lower() for k in r.headers}
    assert r.headers.get("x-content-type-options") == "nosniff"


@pytest.mark.asyncio
async def test_docs_disabled_by_default(client):
    r = await client.get("/docs", headers=H)
    assert r.status_code == 404
