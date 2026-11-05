# CivicFix 360 — Phase 0 Security Audit

Date: 2026-11-05 · Branch: `hardening/cf-register` · Auditor: Devin
Scope: `backend/` (FastAPI + SQLAlchemy + SQLite). No frontend exists yet.
Register source: `vunrebility_register_1.docx` was **not attached**; CF-01…CF-24
were verified against the behaviour descriptions inlined in the master prompt.
The two reference images were also not attached (needed for Phase 3).

---

## 1. Endpoint inventory

| Method | Path | Auth | Role | Rate limit | Jurisdiction |
|---|---|---|---|---|---|
| POST | `/complaints` | none | — | none | n/a |
| GET | `/complaints/track/{token}` | tracking secret (URL) | — | none | n/a |
| POST | `/complaints/{id}/evidence` | tracking token (form) | — | none | n/a |
| POST | `/complaints/{id}/verify` | tracking token (body) | — | none | n/a |
| GET | `/incidents/nearby` | none | — | none | n/a (public) |
| POST | `/incidents/{id}/support` | tracking token (body) | — | none | n/a |
| POST | `/chat/sessions` | none | — | per-session msg limit only | n/a |
| POST | `/chat/sessions/{id}/messages` | session id in URL | — | 30/min per session (in-memory) | n/a |
| POST | `/chat/sessions/{id}/stream` | session id in URL | — | same | n/a |
| POST | `/chat/feedback` | message id (unguessable-ish) | — | none | n/a |
| GET | `/chat/sessions/{id}` | **none — id is the credential** | — | none | n/a |
| POST | `/chat/sessions/{id}/action` | session id | — | none | n/a |
| POST | `/admin/login` | none | — | none | n/a |
| POST | `/admin/admins` | admin JWT | super_admin | none | n/a |
| GET | `/admin/me` | admin JWT | any | none | self |
| GET | `/admin/dashboard` | admin JWT | any | none | yes |
| GET | `/admin/complaints` | admin JWT | any | none | yes |
| GET | `/admin/complaints/{id}` | admin JWT | any | none | yes (403 outside) |
| PATCH | `/admin/complaints/{id}` | admin JWT | any in-jurisdiction | none | yes |
| POST | `/admin/complaints/{id}/assign` | admin JWT | any in-jurisdiction | none | yes |
| POST | `/admin/complaints/{id}/resolve` | admin JWT | any in-jurisdiction | none | yes |
| GET | `/admin/incidents` | admin JWT | any | none | yes |
| GET | `/admin/map` | admin JWT | any | none | yes |
| GET | `/admin/departments` | admin JWT | any | none | no (global list — fine) |
| GET | `/admin/jurisdictions` | admin JWT | any | none | scoped to chain |
| GET | `/admin/sla-rules` | admin JWT | any | none | no (config — acceptable) |
| GET | `/admin/priority-config` | admin JWT | any | none | no |
| PUT | `/admin/priority-config/{key}` | admin JWT | super_admin | none | n/a |
| GET | `/admin/ml/metrics` | admin JWT | any | none | no |
| POST | `/admin/ml/retrain` | admin JWT | district_admin+ | none | n/a |
| GET | `/admin/notifications` | admin JWT | any | none | **no — leaks all** |
| GET | `/health`, `/` | none | — | none | n/a |
| GET | `/docs`, `/redoc`, `/openapi.json` | none | — | none | n/a (always on) |

No endpoint declares `response_model`, `operation_id`, or typed error responses.

## 2. Data model summary

All PKs use `new_id()` = `uuid4().hex[:12]` → **48-bit IDs everywhere**
(`models.py:22-24`). Tables: `admins`, `jurisdictions`, `departments`,
`sla_rules`, `priority_config`, `ml_models`, `faq_documents`, `complaints`,
`evidence`, `incidents`, `incident_reports`, `assignments`, `sla_records`,
`status_history`, `notifications`, `audit_logs`, `chat_sessions`,
`chat_messages`, `ml_feedback`.

Bearer secrets / identifiers:
- `complaints.tracking_token_hash` — SHA256(token+static key); raw token shown once (`pipeline.py:120-124`). High-entropy (192-bit) → OK entropy, weak KDF/key management.
- `chat_sessions.id` — **the session id itself is the only credential** for `GET /chat/sessions/{id}`, `/messages`, `/stream`, `/action`. 48-bit, enumerable-ish, no token.
- `admins.id` — 48-bit, appears in JWT `sub` (not a bearer secret per se).

Personal data columns: `complaints.contact_phone`, `contact_email`,
`lat`/`lon` (exact GPS), `description`, `transcript`, `landmark_text`,
`chat_sessions.ip_hash` (unsalted SHA-256 of IP — CF-18),
`chat_messages.content` (may contain pasted secrets), `evidence.file_path`
(uploaded binaries may carry EXIF GPS — never stripped).

## 3. Status workflow as implemented

Complaint `status` writers:
- `pipeline.create_complaint` → `received`→ immediately `under_review`
  (`pipeline.py:~272`); `review_reason` set on AI uncertainty.
- `admin.patch_complaint` → **any value in STATUSES, no transition rules, no
  role gate** (`admin.py:291-330`).
- `admin.assign_complaint` → sets `under_review` if `received` (`admin.py:~348`).
- `admin.resolve_complaint` → `awaiting_verification`, requires ≥1
  `is_resolution` evidence **but evidence_ids not scoped to the complaint**
  (`admin.py:362`).
- `complaints.verify_fix` → `closed` or `reopened`; **also sets the shared
  incident to `resolved` directly** (`complaints.py:~296-300`); no status precondition.
- `complaints.support_incident` → inserts `IncidentReport` (unique
  `complaint_id` → second support of same complaint 500s — CF-23).

Incident `status` writers: default `open`; `_refresh_incident_status`
(`admin.py:388`) derives open/in_progress/awaiting_verification;
`verify_fix` forces `resolved`; nothing sets `closed`/`reopened` on incidents
except `verify_fix` reopen path.

## 4. CF verification table

| CF | Status | Location (current) | Note |
|----|--------|--------------------|------|
| CF-01 default admins `admin123` | **Confirmed** | `main.py:80-96` seeds 4 admins; `main.py:113` logs the password | `_ensure_seed` runs on every startup when admins table empty |
| CF-02 default JWT/tracking keys | **Confirmed** | `config.py:10,14`; `auth.py:36,46`; `pipeline.py:37-38` | JWT alg pinned but no iss/aud/jti/type claims; single static tracking key, fast SHA-256 |
| CF-03 `/verify` abuse | **Confirmed** | `complaints.py:286-310` | No `awaiting_verification` gate; `confirmed:bool` not confirm/reject; citizen confirm sets incident `resolved`; wrong-secret vs unknown-ID both 404 but timing not equalised |
| CF-04 `evidence_ids` unscoped | **Confirmed** | `admin.py:362-364` | `Evidence.id.in_(ids)` not constrained to `complaint_id`; no jurisdiction re-check on evidence rows; no `marked_by/at` |
| CF-05 citizen `is_resolution` | **Confirmed** | `complaints.py:193,226` | `is_resolution` accepted as public form field; stored verbatim; feeds resolve gate and tracking view |
| CF-06 `/incidents/nearby` leaks | **Confirmed** | `complaints.py:233-253` | Returns exact lat/lon, `title`=raw complaint description, `priority_band/score`; `radius_m`/`limit` unbounded |
| CF-07 no rate limiting | **Confirmed** | only `routers/chat.py:25-33` per-session in-memory limiter | No login/submit/track/upload limits; per-IP chat aggregate absent (new session resets) |
| CF-08 tracking secret exposure | **Confirmed** | `services/chat.py:_submit_intake` puts `tracking_token` in card AND echoes it in reply text; `routers/chat.py:172` `GET /sessions/{id}` unauthenticated; no message redaction | Secret persisted into `chat_messages` via card/reply |
| CF-09 role separation on writes | **Confirmed** | `admin.py:291` patch allows any status; `schemas.py` `priority_override_score: float` unbounded; no transition matrix; `audit_logs` minimal (no before/after, no request id) | Ward officer can set `closed`; no `allowed_actions` in responses |
| CF-10 notifications unscoped | **Confirmed** | `admin.py:555-560` | Returns all notifications to any admin regardless of jurisdiction; includes title/body with complaint details |
| CF-11 upload handling | **Confirmed** | `complaints.py:206-231` | `await file.read()` whole file into memory; trusts client MIME; no magic-byte sniffing, no Pillow validation, no EXIF strip, no size abort mid-stream, no ClamAV hook, no image-count cap |
| CF-12 pickle model load | **Confirmed** | `classify.py:34`, `services/chat.py:107` | `pickle.load` on `category_head.pkl`/`scope_head.pkl` from `../ml/models` (relative path), no hash manifest, loaded lazily per call |
| CF-13 DB URL logged | **Confirmed** | `main.py:22` `log.info("DB: %s", settings.database_url)` | Password-bearing URL logged verbatim; no redaction filter anywhere |
| CF-14 unvalidated input | **Confirmed** | `schemas.py` — no `extra="forbid"`, no lat/lon bounds, no EmailStr/E.164; `ChatMessageIn.image_data_url` accepted unvalidated (`chat.py` router); `session_action(body: dict)` untyped (`routers/chat.py:190`); no body-size middleware | `page_size`/`radius_m`/`limit` unbounded |
| CF-15 admin login weaknesses | **Confirmed** | `admin.py:43-51`, `auth.py` | No dummy-hash timing equalisation, no lockout, no MFA use (`totp_secret` column unused), bcrypt default cost, no session table/refresh/revocation, 8h tokens |
| CF-16 `/ml/retrain` blocking | **Confirmed** | `admin.py:513-544` | `subprocess.run(timeout=600)` on event loop; stderr tail returned to client; no enable flag, no job record, district_admin allowed |
| CF-17 48-bit IDs as secrets | **Confirmed** | `models.py:22-24` `new_id()` everywhere incl. `chat_sessions.id`, `admins.id` | Only tracking token (192-bit) is adequate; session id doubles as bearer credential |
| CF-18 weak IP hash | **Confirmed** | `routers/chat.py:36-38` | Unsalted `sha256(ip)`; no `IP_HASH_KEY` HMAC; no trusted-proxy handling (`request.client.host` only — XFF ignored entirely, so no spoofing but also no proxy support) |
| CF-19 CORS/headers/docs | **Confirmed** | `config.py:44-45`, `main.py:128-133` | `allow_methods=["*"]`, `allow_headers=["*"]`, credentials with wildcard origins list incl. localhost defaults; no security-headers middleware, no TrustedHost; docs always enabled |
| CF-20 exception text to citizens | **Confirmed** | `pipeline.py:162` (`ai_explanation=f"...{e}"`), `:203,230` (`review_reason=f"...{e}"`), `:268` (`priority_factors={"error": str(e)}`) | Raw exception strings persisted and returned via track/admin APIs; no global handlers/envelope |
| CF-21 public ID gen | **Confirmed** | `pipeline.py:_next_public_id` (~lines 45-62) | SELECTs every `public_id` and parses in Python — O(n) per submit, race-prone (two concurrent submits can collide → IntegrityError 500) |
| CF-22 repo hygiene | **Confirmed** | repo was not under git; `.gitignore` existed but `.venv/`, `backend/venv/`, `*.db`, `.env` coverage incomplete; `backend/civicfix.db`, `test_civicfix.db`, `.pytest_cache` present | No `.env.example`, no pre-commit/secret scanning, `backend/.env` present (gitignored now) |
| CF-23 functional bugs | **Confirmed** | `services/chat.py:133-134` — `Incident.status.in_([...], Incident.lat.isnot(None), Incident.lon.isnot(None))` passes 3 args to `in_()` → runtime TypeError on nearby-incident chat tool; `complaints.py:268-272` support inserts duplicate `IncidentReport` row → IntegrityError on second support | Both reproduced by inspection; chat tool path currently broken |
| CF-24 dependencies | **Confirmed** | `backend/requirements.txt` single file mixing runtime+dev+ML (pytest, torch, sentence-transformers); no lockfile, no pip-audit/bandit config | `sentence-transformers`/`torch` imported lazily — could move to `requirements-ml.txt` |

**Result: 24/24 confirmed** (CF-23 partially — the `in_()` bug confirmed;
support-duplicate confirmed by unique constraint on `incident_reports.complaint_id`).

## 5. Roles & jurisdiction

Roles (`taxonomy.py`): `super_admin`, `state_admin`, `district_admin`,
`municipal_admin`, `ward_admin`. Seeded: state/district/ward12/super only.
`Admin.jurisdiction_id` → `Jurisdictions` tree (state→district→municipality→ward
with bbox columns). `auth.jurisdiction_chain` returns self+descendants;
`assert_can_access_*` checks ward/municipality/district membership. Enforced
server-side on reads; **not** on `PATCH` transitions beyond jurisdiction, and
notifications/evidence-ids bypass it (CF-10, CF-04).

## 6. Sensitive-text flows

`description`/`transcript`/`landmark_text` → `pipeline.create_complaint` →
classify (keywords+embedding), severity rules, location resolve (gazetteer),
dedup embeddings, priority factors, incident title (**raw description stored as
`incident.title`** → leaked publicly via `/incidents/nearby`, CF-06).
`image_data_url` accepted in chat schema but unused. EXIF GPS: **never used** —
evidence bytes are stored raw; so CF-11 fix = strip all EXIF unconditionally.

## 7. Assumptions & gaps

- Register docx + images not provided → verified from inline descriptions;
  file:line refs are current as of this commit.
- Alembic absent → will be introduced in Phase 1 (all changes need migrations).
- Postgres/Redis/PostGIS assumed for production; SQLite is the dev/test path —
  several fixes (row locking, sequences, RLS) need dialect-aware fallbacks.
- `muni`/`municipal_admin` role seeded? No — schema supports it.

---

## Audit summary (for review before Phase 1)

- **Attack surface**: 30 endpoints; only admin routes have auth; citizen side
  relies on a single tracking secret and an unauthenticated 48-bit chat session id.
- **Worst findings**: CF-08 (secret echoed into chat + session id = credential),
  CF-06 (public endpoint leaks raw complaint text + exact coords),
  CF-03/CF-05/CF-04 (lifecycle/evidence integrity), CF-15 (no lockout/MFA/sessions),
  CF-01/CF-02/CF-13 (bootstrap secrets + logging).
- **Functional bugs**: CF-23 (`in_()` TypeError breaks chat nearby tool;
  support endpoint 500s on repeat).
- **No rate limiting** anywhere except a per-session chat counter.
- **No error envelope, no response models, docs always on.**

Stopping here per instructions — awaiting approval to start Phase 1.
