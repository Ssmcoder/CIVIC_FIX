"""Chat endpoints: sessions, messages (SSE streaming), feedback, actions."""
from __future__ import annotations

import asyncio
import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..models import ChatMessage, ChatSession, MlFeedback
from ..schemas import ChatFeedbackIn, ChatMessageIn, ChatSessionCreate
from ..services import chat as chat_svc

router = APIRouter(prefix="/chat", tags=["chat"])

RATE_LIMIT = 30  # messages per session per minute (simple in-memory)
_hits: dict[str, list[float]] = {}


def _rate_ok(session_id: str) -> bool:
    import time
    now = time.time()
    hits = [t for t in _hits.get(session_id, []) if now - t < 60]
    if len(hits) >= RATE_LIMIT:
        return False
    hits.append(now)
    _hits[session_id] = hits
    return True


def _ip_hash(request: Request) -> str:
    ip = request.client.host if request.client else "unknown"
    return hashlib.sha256(ip.encode()).hexdigest()[:32]


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(body: ChatSessionCreate | None = None,
                         request: Request = None,
                         db: AsyncSession = Depends(get_db)):
    ip = _ip_hash(request) if request else ""
    s = ChatSession(ip_hash=ip, state="{}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    greeting = ("Namaste! I'm the CivicFix assistant. I can help you report a civic problem "
                "(road, waste, drainage, water, electricity, safety), track a complaint, or "
                "find nearby issues. What do you need?")
    db.add(ChatMessage(session_id=s.id, role="assistant", content=greeting, scope="civic"))
    await db.commit()
    return {"session_id": s.id, "greeting": greeting, "quick_replies": chat_svc.QUICK_REPLIES}


@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, body: ChatMessageIn,
                       request: Request = None,
                       db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session = res.scalar_one_or_none()
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    if not _rate_ok(session_id):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Slow down — too many messages")

    user_text = (body.audio_transcript or body.content or "").strip()
    if not user_text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty message")

    db.add(ChatMessage(session_id=session_id, role="user", content=user_text))
    await db.commit()

    turn = await chat_svc.handle_message(
        db, session, body.content, audio_transcript=body.audio_transcript,
        image_data_url=body.image_data_url)

    # log assistant message with tool calls + scope
    db.add(ChatMessage(
        session_id=session_id, role="assistant", content=turn.reply,
        model_version=get_settings().ollama_model if get_settings().llm_provider == "ollama" else "rules-v1",
        tool_calls=json.dumps(turn.tool_calls), scope=turn.scope))
    # log out-of-scope/feedback-relevant turns for ML
    if turn.scope in ("out_of_scope", "unclear"):
        db.add(MlFeedback(kind="chat_scope", chat_message_id=None,
                          input_text=user_text[:500], predicted_label=turn.scope,
                          confirmed_label=None, model_version="rules-v1"))
    await db.commit()

    return {
        "reply": turn.reply,
        "quick_replies": turn.quick_replies,
        "card": turn.card,
        "scope": turn.scope,
        "state": turn.state,
        "ai_generated": True,
        "use_form_instead": "/#report",
    }


@router.post("/sessions/{session_id}/stream")
async def send_message_stream(session_id: str, body: ChatMessageIn,
                              request: Request = None,
                              db: AsyncSession = Depends(get_db)):
    """SSE streaming variant — emits tokens then the final structured payload."""
    res = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session = res.scalar_one_or_none()
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    if not _rate_ok(session_id):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Slow down")

    user_text = (body.audio_transcript or body.content or "").strip()
    db.add(ChatMessage(session_id=session_id, role="user", content=user_text))
    await db.commit()

    async def gen():
        # run the full turn (deterministic core), then stream it word-by-word
        # so the UX feels live even without an LLM token stream
        turn = await chat_svc.handle_message(
            db, session, body.content, audio_transcript=body.audio_transcript,
            image_data_url=body.image_data_url)
        db.add(ChatMessage(session_id=session_id, role="assistant", content=turn.reply,
                           model_version="rules-v1", tool_calls=json.dumps(turn.tool_calls),
                           scope=turn.scope))
        await db.commit()
        payload = {
            "reply": turn.reply, "quick_replies": turn.quick_replies,
            "card": turn.card, "scope": turn.scope, "state": turn.state,
            "ai_generated": True, "use_form_instead": "/#report",
        }
        # SSE: chunk the reply text for typing effect, then send full payload
        words = turn.reply.split(" ")
        buf = ""
        for i, w in enumerate(words):
            buf += (" " if i else "") + w
            yield f"data: {json.dumps({'delta': w + ' '})}\n\n"
            await asyncio.sleep(0.02)
        yield f"data: {json.dumps({'done': True, 'payload': payload})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.post("/feedback")
async def feedback(body: ChatFeedbackIn, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(ChatMessage).where(ChatMessage.id == body.message_id))
    msg = res.scalar_one_or_none()
    if msg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    if body.score not in (1, -1):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "score must be 1 or -1")
    msg.feedback = body.score
    # find the preceding user message for training signal
    prev = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == msg.session_id,
                                  ChatMessage.role == "user",
                                  ChatMessage.created_at < msg.created_at)
        .order_by(ChatMessage.created_at.desc()).limit(1))
    user_msg = prev.scalar_one_or_none()
    db.add(MlFeedback(kind="chat_feedback", chat_message_id=msg.id,
                      input_text=(user_msg.content[:500] if user_msg else ""),
                      predicted_label=msg.scope, confirmed_label="up" if body.score == 1 else "down",
                      model_version=msg.model_version))
    await db.commit()
    return {"ok": True}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    s = res.scalar_one_or_none()
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    msgs = (await db.execute(select(ChatMessage).where(ChatMessage.session_id == session_id)
                           .order_by(ChatMessage.created_at))).scalars().all()
    return {"session_id": s.id, "state": json.loads(s.state or "{}"),
            "messages": [{"id": m.id, "role": m.role, "content": m.content,
                          "scope": m.scope, "feedback": m.feedback,
                          "at": m.created_at.isoformat() if m.created_at else None}
                         for m in msgs]}


# ------------------------------------------------------------- actions

@router.post("/sessions/{session_id}/action")
async def session_action(session_id: str, body: dict,
                         db: AsyncSession = Depends(get_db)):
    """Structured UI actions: set_location, confirm_location, submit_intake,
    set_category, set_contact, cancel."""
    res = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session = res.scalar_one_or_none()
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    state = json.loads(session.state or "{}")
    action = body.get("action")
    intake = chat_svc.IntakeState.from_dict(state.get("intake", {}))

    if action == "set_location":
        intake.lat = body.get("lat")
        intake.lon = body.get("lon")
        intake.location_confirmed = True
        state["intake"] = intake.to_dict()
        session.state = json.dumps(state)
        await db.commit()
        return {"ok": True, "next": chat_svc._ask_next_slot(intake)}

    if action == "confirm_location_candidate":
        name = body.get("name", "")
        from ..services import location as loc_svc
        for gname, aliases, glat, glon, gward in loc_svc.GAZETTEER:
            if gname.lower() == name.lower():
                intake.lat, intake.lon = glat, glon
                intake.landmark = gname
                intake.location_confirmed = True
                state["intake"] = intake.to_dict()
                session.state = json.dumps(state)
                await db.commit()
                return {"ok": True, "next": chat_svc._ask_next_slot(intake),
                        "location": {"lat": glat, "lon": glon, "name": gname}}
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown landmark")

    if action == "set_category":
        cat = body.get("category", "")
        if cat in chat_svc.CATEGORIES:
            intake.category = cat
            state["intake"] = intake.to_dict()
            session.state = json.dumps(state)
            await db.commit()
            return {"ok": True, "next": chat_svc._ask_next_slot(intake)}
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid category")

    if action == "submit_intake":
        tools_used = [{"tool": "create_complaint", "args": {"description": intake.description[:120]}}]
        turn = await chat_svc._submit_intake(db, session, state, intake, tools_used)
        return {"ok": True, "reply": turn.reply, "card": turn.card,
                "quick_replies": turn.quick_replies}

    if action == "cancel_intake":
        state["mode"] = "chat"
        state.pop("intake", None)
        session.state = json.dumps(state)
        await db.commit()
        return {"ok": True, "reply": "No problem — intake cancelled. What else can I help with?"}

    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown action: {action}")
