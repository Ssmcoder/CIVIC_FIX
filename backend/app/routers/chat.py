"""Chat endpoints: sessions (token-authed), messages, feedback, actions.
CF-08: session id is a public handle; a separate bearer token (hashed at rest)
is required for history/actions. Secrets are redacted before persistence."""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..models import ChatMessage, ChatSession, MlFeedback
from ..ratelimit import check as rl_check, limited
from ..schemas import ChatActionIn, ChatFeedbackIn, ChatMessageIn
from ..security import ip_hash, client_ip, redact_text as redact
from ..services import chat as chat_svc
from .. import gatekeeper

router = APIRouter(prefix="/chat", tags=["chat"])

_RATE = 30
_hits: dict[str, list[float]] = {}

def _hash(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


async def _get_session(db: AsyncSession, sid: str, token: str | None) -> ChatSession:
    res = await db.execute(select(ChatSession).where(ChatSession.id == sid))
    s = res.scalar_one_or_none()
    if s is None or not token or not secrets.compare_digest(s.token_hash, _hash(token)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    return s


def _ip_rate_ok(iph: str) -> bool:
    import time
    now = time.time()
    hits = [t for t in _hits.get(iph, []) if now - t < 60]
    if len(hits) >= _RATE:
        return False
    hits.append(now)
    _hits[iph] = hits
    return True


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(request: Request, db: AsyncSession = Depends(get_db)):
    s = get_settings()
    ok, retry = rl_check(request, "chat_session", s.rl_chat_session_per_hour, 3600)
    if not ok:
        return limited(retry)
    token = secrets.token_urlsafe(24)
    sess = ChatSession(ip_hash=ip_hash(client_ip(request.scope)),
                       token_hash=_hash(token), state="{}")
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    greeting = ("Namaste! I'm the CivicFix assistant. I can help you report a civic problem "
                "(road, waste, drainage, water, electricity, safety), track a complaint, or "
                "find nearby issues. What do you need?")
    db.add(ChatMessage(session_id=sess.id, role="assistant", content=greeting, scope="civic"))
    await db.commit()
    return {"session_id": sess.id, "session_token": token,  # shown once
            "greeting": greeting, "quick_replies": chat_svc.QUICK_REPLIES}


@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, body: ChatMessageIn, request: Request,
                       x_chat_token: str | None = Header(None),
                       db: AsyncSession = Depends(get_db)):
    session = await _get_session(db, session_id, x_chat_token)
    ok, retry = rl_check(request, "chat_ip", get_settings().rl_chat_ip_per_min, 60)
    if not ok:
        return limited(retry)
    user_text = (body.audio_transcript or body.content or "").strip()
    if not user_text:
        raise HTTPException(400, "Empty message")
    # ---- gatekeeper: validate before the chatbot sees anything ----
    state = json.loads(session.state or "{}")
    gres = await gatekeeper.gate_text(user_text, state)
    session.state = json.dumps(state)
    if not gres.ok:
        await db.commit()
        return {"reply": gres.payload()["message"], "quick_replies": [],
                "card": {"type": "rejected", **gres.payload()},
                "scope": "rejected", "state": "chatting",
                "ai_generated": False, "rejected": True}
    db.add(ChatMessage(session_id=session_id, role="user", content=redact(user_text)))
    await db.commit()
    turn = await chat_svc.handle_message(db, session, body.content,
                                         audio_transcript=body.audio_transcript)
    db.add(ChatMessage(session_id=session_id, role="assistant",
                       content=redact(turn.reply),
                       model_version="rules-v1",
                       tool_calls=json.dumps(turn.tool_calls), scope=turn.scope))
    if turn.scope in ("out_of_scope", "unclear"):
        db.add(MlFeedback(kind="chat_scope", input_text=redact(user_text)[:500],
                          predicted_label=turn.scope, model_version="rules-v1"))
    await db.commit()
    return {"reply": turn.reply, "quick_replies": turn.quick_replies,
            "card": turn.card, "scope": turn.scope, "state": turn.state,
            "ai_generated": True, "use_form_instead": "/#report"}


@router.post("/sessions/{session_id}/stream")
async def send_message_stream(session_id: str, body: ChatMessageIn, request: Request,
                              x_chat_token: str | None = Header(None),
                              db: AsyncSession = Depends(get_db)):
    session = await _get_session(db, session_id, x_chat_token)
    ok, retry = rl_check(request, "chat_ip", get_settings().rl_chat_ip_per_min, 60)
    if not ok:
        return limited(retry)
    user_text = (body.audio_transcript or body.content or "").strip()
    _state = json.loads(session.state or "{}")
    _gres = await gatekeeper.gate_text(user_text, _state)
    session.state = json.dumps(_state)
    if not _gres.ok:
        await db.commit()
        payload = {"reply": _gres.payload()["message"], "quick_replies": [],
                   "card": {"type": "rejected", **_gres.payload()},
                   "scope": "rejected", "state": "chatting",
                   "ai_generated": False, "rejected": True}

        async def _rej():
            yield f"data: {json.dumps({'done': True, 'payload': payload})}\n\n"
        return StreamingResponse(_rej(), media_type="text/event-stream")
    db.add(ChatMessage(session_id=session_id, role="user", content=redact(user_text)))
    await db.commit()

    async def gen():
        turn = await chat_svc.handle_message(db, session, body.content,
                                             audio_transcript=body.audio_transcript)
        db.add(ChatMessage(session_id=session_id, role="assistant",
                           content=redact(turn.reply), model_version="rules-v1",
                           tool_calls=json.dumps(turn.tool_calls), scope=turn.scope))
        await db.commit()
        payload = {"reply": turn.reply, "quick_replies": turn.quick_replies,
                   "card": turn.card, "scope": turn.scope, "state": turn.state,
                   "ai_generated": True, "use_form_instead": "/#report"}
        for w in turn.reply.split(" "):
            yield f"data: {json.dumps({'delta': w + ' '})}\n\n"
            await asyncio.sleep(0.02)
        yield f"data: {json.dumps({'done': True, 'payload': payload})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/feedback")
async def feedback(body: ChatFeedbackIn, x_chat_token: str | None = Header(None),
                   db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(ChatMessage).where(ChatMessage.id == body.message_id))
    msg = res.scalar_one_or_none()
    if msg is None:
        raise HTTPException(404, "Message not found")
    sess = await db.get(ChatSession, msg.session_id)
    if sess is None or not x_chat_token or not secrets.compare_digest(sess.token_hash, _hash(x_chat_token)):
        raise HTTPException(404, "Message not found")
    msg.feedback = body.score
    prev = await db.execute(select(ChatMessage).where(
        ChatMessage.session_id == msg.session_id, ChatMessage.role == "user",
        ChatMessage.created_at < msg.created_at).order_by(ChatMessage.created_at.desc()).limit(1))
    um = prev.scalar_one_or_none()
    db.add(MlFeedback(kind="chat_feedback", chat_message_id=msg.id,
                      input_text=(um.content[:500] if um else ""),
                      predicted_label=msg.scope,
                      confirmed_label="up" if body.score == 1 else "down",
                      model_version=msg.model_version))
    await db.commit()
    return {"ok": True}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, x_chat_token: str | None = Header(None),
                      db: AsyncSession = Depends(get_db)):
    s = await _get_session(db, session_id, x_chat_token)
    msgs = (await db.execute(select(ChatMessage).where(ChatMessage.session_id == session_id)
                           .order_by(ChatMessage.created_at))).scalars().all()
    return {"session_id": s.id, "state": json.loads(s.state or "{}"),
            "messages": [{"id": m.id, "role": m.role, "content": m.content,
                          "scope": m.scope, "feedback": m.feedback,
                          "at": m.created_at.isoformat() if m.created_at else None}
                         for m in msgs]}


@router.post("/sessions/{session_id}/action")
async def session_action(session_id: str, body: ChatActionIn,
                         x_chat_token: str | None = Header(None),
                         db: AsyncSession = Depends(get_db)):
    session = await _get_session(db, session_id, x_chat_token)
    state = json.loads(session.state or "{}")
    intake = chat_svc.IntakeState.from_dict(state.get("intake", {}))

    if body.action == "set_location":
        bad = gatekeeper.validate_location(body.lat, body.lon)
        if bad:
            await db.commit()
            return {"ok": False, "rejected": True, **bad.payload()}
        intake.lat, intake.lon = body.lat, body.lon
        intake.location_confirmed = body.lat is not None
        state["intake"] = intake.to_dict()
        session.state = json.dumps(state)
        await db.commit()
        return {"ok": True, "next": chat_svc._ask_next_slot(intake)}
    if body.action == "confirm_location_candidate":
        from ..services import location as loc_svc
        for gname, _a, glat, glon, _w in loc_svc.GAZETTEER:
            if gname.lower() == (body.name or "").lower():
                intake.lat, intake.lon, intake.landmark = glat, glon, gname
                intake.location_confirmed = True
                state["intake"] = intake.to_dict()
                session.state = json.dumps(state)
                await db.commit()
                return {"ok": True, "next": chat_svc._ask_next_slot(intake),
                        "location": {"lat": glat, "lon": glon, "name": gname}}
        raise HTTPException(404, "Unknown landmark")
    if body.action == "set_category":
        if body.category in chat_svc.CATEGORIES:
            intake.category = body.category
            state["intake"] = intake.to_dict()
            session.state = json.dumps(state)
            await db.commit()
            return {"ok": True, "next": chat_svc._ask_next_slot(intake)}
        raise HTTPException(422, "Invalid category")
    if body.action == "set_contact":
        intake.contact_phone = body.phone or ""
        intake.contact_email = body.email or ""
        intake.anonymous = bool(body.anonymous)
        state["intake"] = intake.to_dict()
        session.state = json.dumps(state)
        await db.commit()
        return {"ok": True}
    if body.action == "submit_intake":
        tools_used = [{"tool": "create_complaint"}]
        turn = await chat_svc._submit_intake(db, session, state, intake, tools_used)
        return {"ok": True, "reply": turn.reply, "card": turn.card,
                "quick_replies": turn.quick_replies}
    if body.action == "cancel_intake":
        state["mode"] = "chat"
        state.pop("intake", None)
        session.state = json.dumps(state)
        await db.commit()
        return {"ok": True, "reply": "No problem — intake cancelled."}
    raise HTTPException(400, "Unknown action")
