"""Chat streaming and durable turn-detail HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from yumi.core.features.chat.pipeline import clear_session, generate_chat_events
from yumi.core.platform.http.dependencies import CurrentIdentity
from yumi.core.platform.http.schemas import ChatRequest
from yumi.core.platform.observability.turn_inspector import get_turn, list_turns
from yumi.core.platform.plugins import get_memory_factory, get_quota_policy, get_session_scope
from yumi.core.platform.runtime.accessors import stream_event
from yumi.core.platform.security.audit import audit_event

router = APIRouter()


@router.post("/chat")
async def chat_endpoint(request: Request, identity: CurrentIdentity, body: ChatRequest):
    quota = get_quota_policy()
    allowed, qerr = quota.check_chat_allowed(identity)
    if not allowed:
        raise HTTPException(status_code=429, detail=qerr)
    tok_ok, tok_err = quota.check_token_quota(identity)
    if not tok_ok:
        raise HTTPException(status_code=429, detail=tok_err)
    sid = get_session_scope().qualify_session_http(identity, body.session_id)
    audit_event("chat_request", identity.user_id, session_id=sid)

    async def generate():
        # Tests monkey-patch ``yumi.core.features.chat.router.generate_chat_events``
        # to substitute a fake generator. The lookup happens here (via module
        # globals) so the patch is honored on every request.
        charged = False
        async for event in generate_chat_events(body.prompt, sid, think=body.think):
            if not charged and event.get("type") != "error":
                quota.record_chat_turn(identity)
                charged = True
            yield stream_event(event["type"], **{k: v for k, v in event.items() if k != "type"})

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@router.post("/clear")
async def clear_endpoint(identity: CurrentIdentity, session_id: str = "default"):
    sid = get_session_scope().qualify_session_http(identity, session_id)
    return await clear_session(sid)


@router.get("/chat/turns")
async def list_chat_turns_endpoint(
    identity: CurrentIdentity,
    session_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
):
    """List durable execution summaries, with a live running turn overlay."""
    scope = get_session_scope()
    sid = scope.qualify_session_http(identity, session_id) if session_id else None
    sqlite = get_memory_factory().get_for_identity(identity).sqlite
    durable = sqlite.list_turn_traces(
        session_id=sid,
        owner_user_id=identity.user_id,
        limit=limit,
    )
    live = list_turns(session_id=sid, limit=limit)
    merged = {str(row.get("id") or ""): row for row in durable}
    for row in live:
        if row.get("owner_user_id") in (None, "", identity.user_id):
            merged[str(row.get("id") or "")] = row
    rows = sorted(merged.values(), key=lambda row: str(row.get("started_at") or ""), reverse=True)[:limit]
    return {"turns": rows, "retention": {"kind": "durable", "message": "Saved with conversation history."}}


@router.get("/chat/turns/{turn_id}")
async def get_chat_turn_endpoint(identity: CurrentIdentity, turn_id: str):
    """Return one complete execution trace after enforcing session ownership."""
    sqlite = get_memory_factory().get_for_identity(identity).sqlite
    turn = get_turn(turn_id) or sqlite.get_turn_trace(turn_id)
    if turn is None:
        raise HTTPException(status_code=404, detail="Turn not found.")
    get_session_scope().ensure_session_owned_by_identity(identity, str(turn.get("session_id") or ""))
    return {"turn": turn}
