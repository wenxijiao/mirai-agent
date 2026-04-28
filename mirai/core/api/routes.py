"""Mirai core HTTP API — FastAPI application and route definitions.

This is the single-user OSS surface. Multi-tenant routes (admin, auth,
relay HTTP dispatch, per-user model overrides, edge sharing, usage / audit
exports) live in the ``mirai-enterprise`` package and attach themselves
through the plugin layer:

- ``get_route_extender().mount(app)`` — mount additional FastAPI routers
- ``get_middleware_extender().middlewares()`` — add ASGI middleware classes
"""

from __future__ import annotations

import asyncio
import json
import signal
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import mirai.core.api.state as _state
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from mirai.core.api.chat import clear_session, generate_chat_events
from mirai.core.api.docs_middleware import DocsAccessMiddleware
from mirai.core.api.edge import (
    apply_local_tool_confirmation_from_saved_config,
    handle_edge_peer,
    persist_local_tool_confirmation_to_config,
    push_confirmation_policy_to_edge,
)
from mirai.core.api.http_errors import model_apply_failed_http, provider_not_ready_http, unknown_provider_http
from mirai.core.api.http_helpers import get_session_payload, get_system_prompt_payload
from mirai.core.api.peers import LocalEdgePeer
from mirai.core.api.schemas import (
    ChatRequest,
    FileUploadRequest,
    MemoryCreateRequest,
    MemoryUpdateRequest,
    ModelConfigUpdateRequest,
    SessionCreateRequest,
    SessionPromptRequest,
    SessionUpdateRequest,
    SystemPromptUpdateRequest,
    ToolConfirmationResponse,
    ToolConfirmationToggleRequest,
    ToolToggleRequest,
    TranscribeRequest,
    UIPreferencesRequest,
)
from mirai.core.api.state import (
    ACTIVE_CONNECTIONS,
    ALWAYS_ALLOWED_TOOLS,
    CONFIRMATION_TOOLS,
    DISABLED_TOOLS,
    EDGE_TOOLS_REGISTRY,
    PENDING_CONFIRMATIONS,
    TIMER_SUBSCRIBERS,
    get_memory_store_for_identity,
    resolve_edge_for_prefixed_tool_name,
    stream_event,
)
from mirai.core.api.task_logging import log_task_exc_on_done
from mirai.core.api.timers import cancel_timer, schedule_timer
from mirai.core.api.uploads import decode_upload_payload, save_uploaded_file
from mirai.core.audit import audit_event
from mirai.core.chatbot import MiraiBot
from mirai.core.config import (
    CONFIG_PATH,
    delete_session_prompt,
    ensure_chat_model_configured,
    ensure_config_dir,
    ensure_provider_available,
    get_api_credentials,
    get_session_prompt,
    load_model_config,
    load_saved_model_config,
    reset_system_prompt,
    save_model_config,
    set_session_prompt,
    set_system_prompt,
)
from mirai.core.exceptions import ProviderNotReadyError
from mirai.core.http_config import get_cors_settings
from mirai.core.memories.embedding_state import set_embed_provider
from mirai.core.plugins import (
    Identity,
    get_bot_pool,
    get_current_identity,
    get_middleware_extender,
    get_route_extender,
    get_session_scope,
    load_entry_point_plugins,
)
from mirai.core.providers import SUPPORTED_PROVIDERS, create_provider
from mirai.core.tool import TOOL_REGISTRY
from mirai.core.tool_trace import export_traces_json_lines, list_traces
from mirai.logging_config import configure_logging, get_logger
from mirai.tools.bootstrap import init_mirai
from mirai.tools.timer_tools import restore_schedules, set_timer_callbacks

logger = get_logger(__name__)


def current_identity_dependency() -> Identity:
    """FastAPI dependency for the active :class:`Identity`."""
    return get_current_identity()


CurrentIdentity = Annotated[Identity, Depends(current_identity_dependency)]


# ── lifespan ──


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()

    from mirai.core.api.line_webhook import try_register_line_webhook

    try_register_line_webhook(app)

    set_timer_callbacks(schedule_timer, cancel_timer)
    restore_schedules()

    init_mirai()
    apply_local_tool_confirmation_from_saved_config()

    config = ensure_chat_model_configured(interactive=False)

    chat_provider = create_provider(config.chat_provider)

    embed_provider = (
        chat_provider
        if config.embedding_provider == config.chat_provider
        else create_provider(config.embedding_provider)
    )
    set_embed_provider(embed_provider)

    _state.bot = MiraiBot(provider=chat_provider, model_name=config.chat_model, think=False)
    await _state.bot.warm_up()

    # Plugin background sweeps (default: no-op).
    get_bot_pool().start_idle_sweep()

    async def _broadcast_edge_drain():
        for _k, peer in list(ACTIVE_CONNECTIONS.items()):
            try:
                await peer.send_json({"type": "server_draining", "message": "Server is shutting down; reconnect."})
            except Exception:
                pass

    _loop = asyncio.get_running_loop()

    def _on_sigterm() -> None:
        _state.server_draining = True
        t = _loop.create_task(_broadcast_edge_drain())
        log_task_exc_on_done(t, "broadcast_edge_drain")

    try:
        _loop.add_signal_handler(signal.SIGTERM, _on_sigterm)
    except (NotImplementedError, RuntimeError, ValueError):
        pass

    yield

    logger.info("Shutting down server; cleaning up...")
    if _state.RELAY_CLIENT is not None:
        try:
            await _state.RELAY_CLIENT.stop()
        except Exception:
            pass
    if _state.bot is not None:
        await _state.bot.provider.shutdown(_state.bot.model_name)


# ── FastAPI application ──

# Discover and register plugins (enterprise tenancy/admin/relay etc.) BEFORE
# constructing the app so their middleware/routes can attach below.
load_entry_point_plugins()

app = FastAPI(lifespan=lifespan)
app.add_middleware(DocsAccessMiddleware)
app.add_middleware(
    CORSMiddleware,
    **get_cors_settings("MIRAI_CORS_ORIGINS", "MIRAI_CORS_ALLOW_CREDENTIALS"),
)

# Plugin-supplied middleware (registered by `MiddlewareExtender` plugins).
for mw in get_middleware_extender().middlewares():
    if isinstance(mw, tuple):
        cls, kwargs = mw
        app.add_middleware(cls, **(kwargs or {}))
    else:
        app.add_middleware(mw)

# Plugin-supplied routes (admin, auth, relay HTTP dispatch, ...).
get_route_extender().mount(app)


# ── routes ──


@app.websocket("/ws/edge")
async def websocket_edge_endpoint(websocket: WebSocket):
    await websocket.accept()
    peer = LocalEdgePeer(websocket)
    await handle_edge_peer(peer)


@app.post("/chat")
async def chat_endpoint(request: Request, identity: CurrentIdentity, body: ChatRequest):
    from mirai.core.plugins import get_quota_policy

    quota = get_quota_policy()
    allowed, qerr = quota.check_chat_allowed(identity)
    if not allowed:
        raise HTTPException(status_code=429, detail=qerr)
    tok_ok, tok_err = quota.check_token_quota(identity)
    if not tok_ok:
        raise HTTPException(status_code=429, detail=tok_err)
    sid = get_session_scope().qualify_session_http(identity, body.session_id)
    quota.record_chat_turn(identity)
    audit_event("chat_request", identity.user_id, session_id=sid)

    async def generate():
        async for event in generate_chat_events(body.prompt, sid, think=body.think):
            yield stream_event(event["type"], **{k: v for k, v in event.items() if k != "type"})

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.get("/timer-events")
async def timer_events_endpoint(identity: CurrentIdentity):
    queue: asyncio.Queue = asyncio.Queue(maxsize=64)
    # OSS single-user gets all timers; enterprise route extender narrows the
    # subscription per identity if needed.
    sub = (queue, None)
    TIMER_SUBSCRIBERS.append(sub)

    async def event_stream():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=30)
                    yield json.dumps(payload, ensure_ascii=False) + "\n"
                except asyncio.TimeoutError:
                    yield json.dumps({"type": "heartbeat"}) + "\n"
        except asyncio.CancelledError:
            pass
        finally:
            try:
                TIMER_SUBSCRIBERS.remove(sub)
            except ValueError:
                pass

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@app.post("/clear")
async def clear_endpoint(identity: CurrentIdentity, session_id: str = "default"):
    sid = get_session_scope().qualify_session_http(identity, session_id)
    return await clear_session(sid)


@app.post("/uploads")
async def uploads_endpoint(identity: CurrentIdentity, request: FileUploadRequest):
    """Save a file for the current chat session (JSON + base64). Used by the web UI."""
    raw = decode_upload_payload(request.content_base64)
    sid = get_session_scope().qualify_session_http(identity, request.session_id)
    return save_uploaded_file(
        sid,
        request.filename,
        raw,
        owner_user_id=identity.user_id if identity.user_id != "_local" else None,
    )


@app.post("/stt/transcribe")
async def stt_transcribe_endpoint(identity: CurrentIdentity, request: TranscribeRequest):
    """Transcribe audio bytes for chat clients before they call ``/chat``."""
    _ = get_session_scope().qualify_session_http(identity, request.session_id)
    raw = decode_upload_payload(request.content_base64)
    try:
        from mirai.core.stt import SttError, SttNotConfiguredError, transcribe_audio

        result = await transcribe_audio(raw, filename=request.filename, language=request.language)
    except SttNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SttError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not result.text:
        raise HTTPException(status_code=422, detail="No speech could be transcribed from the audio.")
    return {
        "text": result.text,
        "language": result.language,
        "duration_seconds": result.duration_seconds,
    }


@app.get("/config/system-prompt")
async def get_system_prompt_endpoint():
    return get_system_prompt_payload()


@app.put("/config/system-prompt")
async def update_system_prompt_endpoint(request: SystemPromptUpdateRequest):
    try:
        system_prompt = set_system_prompt(request.system_prompt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "success", "system_prompt": system_prompt}


@app.delete("/config/system-prompt")
async def reset_system_prompt_endpoint():
    system_prompt = reset_system_prompt()
    return {"status": "success", "system_prompt": system_prompt, "is_default": True}


@app.get("/memory/sessions")
async def list_memory_sessions_endpoint(identity: CurrentIdentity, status: str = Query(default="active")):
    prefix = get_session_scope().session_id_prefix_for_identity(identity)
    try:
        sessions = get_memory_store_for_identity(identity).list_sessions(status=status, session_id_prefix=prefix)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"sessions": sessions}


@app.post("/memory/sessions")
async def create_memory_session_endpoint(
    identity: CurrentIdentity,
    request: SessionCreateRequest | None = None,
):
    new_id = get_session_scope().qualify_session_http(identity, str(uuid.uuid4()))
    session = get_memory_store_for_identity(identity).create_session(
        title=request.title if request else None, session_id=new_id
    )
    return {"status": "success", "session": session}


@app.get("/memory/sessions/{session_id}")
async def get_memory_session_endpoint(identity: CurrentIdentity, session_id: str):
    sid = get_session_scope().qualify_session_http(identity, session_id)
    return get_session_payload(sid)


@app.put("/memory/sessions/{session_id}")
async def update_memory_session_endpoint(identity: CurrentIdentity, session_id: str, request: SessionUpdateRequest):
    sid = get_session_scope().qualify_session_http(identity, session_id)
    try:
        session = get_memory_store_for_identity(identity).update_session(
            session_id=sid,
            title=request.title,
            is_pinned=request.is_pinned,
            status=request.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"status": "success", "session": session}


@app.get("/memory/messages")
async def list_memory_messages_endpoint(
    identity: CurrentIdentity,
    session_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    scope = get_session_scope()
    sid = scope.qualify_session_http(identity, session_id) if session_id else None
    return {
        "messages": get_memory_store_for_identity(identity).list_messages(
            session_id=sid,
            limit=limit,
            offset=offset,
        )
    }


@app.get("/memory/messages/{message_id}")
async def get_memory_message_endpoint(identity: CurrentIdentity, message_id: str):
    message = get_memory_store_for_identity(identity).get_message(message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Memory message not found.")
    get_session_scope().ensure_message_owned_by_identity(identity, message)
    return message


@app.post("/memory/messages")
async def create_memory_message_endpoint(identity: CurrentIdentity, request: MemoryCreateRequest):
    sid = get_session_scope().qualify_session_http(identity, request.session_id)
    try:
        message = get_memory_store_for_identity(identity).create_message(
            session_id=sid,
            role=request.role,
            content=request.content,
            thought=request.thought,
        )
    except ValueError as exc:
        if "memory_quota_exceeded" in str(exc):
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "success", "message": message}


@app.put("/memory/messages/{message_id}")
async def update_memory_message_endpoint(identity: CurrentIdentity, message_id: str, request: MemoryUpdateRequest):
    existing = get_memory_store_for_identity(identity).get_message(message_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Memory message not found.")
    get_session_scope().ensure_message_owned_by_identity(identity, existing)
    try:
        message = get_memory_store_for_identity(identity).update_message(
            message_id=message_id,
            content=request.content,
            role=request.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if message is None:
        raise HTTPException(status_code=404, detail="Memory message not found.")
    return {"status": "success", "message": message}


@app.delete("/memory/messages/{message_id}")
async def delete_memory_message_endpoint(identity: CurrentIdentity, message_id: str):
    existing = get_memory_store_for_identity(identity).get_message(message_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Memory message not found.")
    get_session_scope().ensure_message_owned_by_identity(identity, existing)
    deleted = get_memory_store_for_identity(identity).delete_message(message_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory message not found.")
    return {"status": "success", "message_id": message_id}


@app.get("/memory/search")
async def search_memory_endpoint(
    identity: CurrentIdentity,
    query: str,
    session_id: str | None = None,
    limit: int = Query(default=10, ge=1, le=100),
):
    scope = get_session_scope()
    sid = scope.qualify_session_http(identity, session_id) if session_id else None
    return {
        "messages": get_memory_store_for_identity(identity).search_messages(
            query=query,
            session_id=sid,
            limit=limit,
        )
    }


@app.get("/health")
async def health_check(identity: CurrentIdentity):
    if getattr(_state, "server_draining", False):
        return JSONResponse(
            {"status": "draining", "message": "Server is shutting down"},
            status_code=503,
        )
    payload: dict = {
        "status": "ok",
        "identity_user_id": identity.user_id,
    }
    return payload


@app.get("/monitor/topology")
async def monitor_topology_endpoint(identity: CurrentIdentity):  # noqa: ARG001
    edges: list[dict] = []
    for edge_key, tools_map in EDGE_TOOLS_REGISTRY.items():
        edges.append(
            {
                "edge_name": edge_key,
                "online": edge_key in ACTIVE_CONNECTIONS,
                "tool_count": len(tools_map),
                "shared": False,
            }
        )
    local_enabled = sum(1 for n in TOOL_REGISTRY if n not in DISABLED_TOOLS)
    return {
        "server": {"id": "mirai-core", "label": "Mirai Core", "role": "chat_server"},
        "local_tool_count": local_enabled,
        "edges": edges,
    }


@app.get("/monitor/traces")
async def monitor_traces_endpoint(
    identity: CurrentIdentity,
    session_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    scope = get_session_scope()
    sid = scope.qualify_session_http(identity, session_id) if session_id else None
    return {"traces": list_traces(session_id=sid, limit=limit)}


@app.get("/monitor/traces/export")
async def monitor_traces_export_endpoint(identity: CurrentIdentity, session_id: str | None = None):
    scope = get_session_scope()
    sid = scope.qualify_session_http(identity, session_id) if session_id else None
    body = export_traces_json_lines(session_id=sid)
    return StreamingResponse(
        iter([body]),
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="mirai_tool_traces.ndjson"'},
    )


@app.post("/tools/toggle")
async def toggle_tool_endpoint(request: ToolToggleRequest):
    if request.disabled:
        DISABLED_TOOLS.add(request.tool_name)
    else:
        DISABLED_TOOLS.discard(request.tool_name)
    return {"status": "success", "tool_name": request.tool_name, "disabled": request.disabled}


@app.post("/tools/set-confirmation")
async def set_tool_confirmation_endpoint(request: ToolConfirmationToggleRequest):
    if request.require_confirmation:
        ALWAYS_ALLOWED_TOOLS.discard(request.tool_name)
        CONFIRMATION_TOOLS.add(request.tool_name)
    else:
        CONFIRMATION_TOOLS.discard(request.tool_name)
        ALWAYS_ALLOWED_TOOLS.add(request.tool_name)

    edge_name = resolve_edge_for_prefixed_tool_name(request.tool_name)
    if edge_name:
        await push_confirmation_policy_to_edge(edge_name)
    else:
        persist_local_tool_confirmation_to_config()

    return {"status": "success", "tool_name": request.tool_name, "require_confirmation": request.require_confirmation}


@app.post("/tools/confirm")
async def confirm_tool_endpoint(request: ToolConfirmationResponse):
    future = PENDING_CONFIRMATIONS.get(request.call_id)
    if future is None or future.done():
        raise HTTPException(status_code=404, detail="No pending confirmation with that call_id.")
    if request.decision not in ("allow", "deny", "always_allow"):
        raise HTTPException(status_code=400, detail="Decision must be 'allow', 'deny', or 'always_allow'.")
    future.set_result(request.decision)
    return {"status": "success", "call_id": request.call_id, "decision": request.decision}


def _restore_config_file(backup_before: str | None) -> None:
    """Restore ~/.mirai/config.json after a failed provider validation (best-effort)."""
    if backup_before is None:
        if CONFIG_PATH.exists():
            CONFIG_PATH.unlink()
        return
    ensure_config_dir()
    CONFIG_PATH.write_text(backup_before, encoding="utf-8")


def _model_config_public_dict() -> dict:
    """Fields for GET /config/model and PUT response (env overrides runtime fields; secrets never returned)."""
    runtime = load_model_config()
    saved = load_saved_model_config()
    creds = get_api_credentials()
    return {
        "chat_provider": runtime.chat_provider,
        "chat_model": runtime.chat_model or "",
        "embedding_provider": runtime.embedding_provider,
        "embedding_model": runtime.embedding_model or "",
        "memory_max_recent_messages": runtime.memory_max_recent_messages,
        "memory_max_related_messages": runtime.memory_max_related_messages,
        "chat_append_current_time": runtime.chat_append_current_time,
        "chat_append_tool_use_instruction": runtime.chat_append_tool_use_instruction,
        "edge_tools_enable_dynamic_routing": runtime.edge_tools_enable_dynamic_routing,
        "edge_tools_retrieval_limit": runtime.edge_tools_retrieval_limit,
        "stt_provider": runtime.stt_provider,
        "stt_backend": runtime.stt_backend,
        "stt_model": runtime.stt_model or "",
        "stt_model_dir": runtime.stt_model_dir or "",
        "stt_language": runtime.stt_language,
        "openai_api_key_saved": bool(saved.openai_api_key and str(saved.openai_api_key).strip()),
        "gemini_api_key_saved": bool(saved.gemini_api_key and str(saved.gemini_api_key).strip()),
        "claude_api_key_saved": bool(saved.claude_api_key and str(saved.claude_api_key).strip()),
        "openai_api_key_effective": bool(creds.get("openai_api_key")),
        "gemini_api_key_effective": bool(creds.get("gemini_api_key")),
        "claude_api_key_effective": bool(creds.get("claude_api_key")),
        "openai_base_url": saved.openai_base_url or "",
    }


@app.get("/config/model")
async def get_model_config_endpoint():
    return _model_config_public_dict()


@app.put("/config/model")
async def update_model_config_endpoint(request: ModelConfigUpdateRequest):
    if request.chat_provider and request.chat_provider not in SUPPORTED_PROVIDERS:
        raise unknown_provider_http(role="chat", name=request.chat_provider, supported=SUPPORTED_PROVIDERS)
    if request.embedding_provider and request.embedding_provider not in SUPPORTED_PROVIDERS:
        raise unknown_provider_http(role="embedding", name=request.embedding_provider, supported=SUPPORTED_PROVIDERS)
    if request.stt_provider and request.stt_provider not in ("disabled", "whisper"):
        raise HTTPException(status_code=400, detail="Unsupported STT provider. Use 'disabled' or 'whisper'.")
    if request.stt_backend and request.stt_backend != "faster-whisper":
        raise HTTPException(status_code=400, detail="Unsupported STT backend. Use 'faster-whisper'.")
    if request.stt_model:
        from mirai.core.stt import WHISPER_MULTILINGUAL_MODELS

        if request.stt_model not in WHISPER_MULTILINGUAL_MODELS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported Whisper model. Use one of: {', '.join(WHISPER_MULTILINGUAL_MODELS)}.",
            )

    backup_before = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else None

    config = load_saved_model_config()
    provider_changed = False
    keys_or_base_changed = False

    if request.chat_provider and request.chat_provider != config.chat_provider:
        config.chat_provider = request.chat_provider
        provider_changed = True
    if request.chat_model:
        config.chat_model = request.chat_model
    if request.embedding_provider:
        config.embedding_provider = request.embedding_provider
    if request.embedding_model:
        config.embedding_model = request.embedding_model
    if request.memory_max_recent_messages is not None:
        config.memory_max_recent_messages = request.memory_max_recent_messages
    if request.memory_max_related_messages is not None:
        config.memory_max_related_messages = request.memory_max_related_messages
    if request.chat_append_current_time is not None:
        config.chat_append_current_time = request.chat_append_current_time
    if request.chat_append_tool_use_instruction is not None:
        config.chat_append_tool_use_instruction = request.chat_append_tool_use_instruction
    if request.edge_tools_enable_dynamic_routing is not None:
        config.edge_tools_enable_dynamic_routing = request.edge_tools_enable_dynamic_routing
    if request.edge_tools_retrieval_limit is not None:
        config.edge_tools_retrieval_limit = request.edge_tools_retrieval_limit
    if request.stt_provider is not None:
        config.stt_provider = request.stt_provider.strip() or "disabled"
    if request.stt_backend is not None:
        config.stt_backend = request.stt_backend.strip() or "faster-whisper"
    if request.stt_model is not None:
        v = request.stt_model.strip()
        config.stt_model = v if v else None
    if request.stt_model_dir is not None:
        v = request.stt_model_dir.strip()
        config.stt_model_dir = v if v else None
    if request.stt_language is not None:
        config.stt_language = request.stt_language.strip() or "auto"
    if request.openai_api_key is not None and request.openai_api_key.strip():
        config.openai_api_key = request.openai_api_key.strip()
        keys_or_base_changed = True
    if request.gemini_api_key is not None and request.gemini_api_key.strip():
        config.gemini_api_key = request.gemini_api_key.strip()
        keys_or_base_changed = True
    if request.claude_api_key is not None and request.claude_api_key.strip():
        config.claude_api_key = request.claude_api_key.strip()
        keys_or_base_changed = True
    if request.openai_base_url is not None:
        v = request.openai_base_url.strip()
        config.openai_base_url = v if v else None
        keys_or_base_changed = True

    try:
        save_model_config(config)
        seen: set[str] = set()
        for prov in (config.chat_provider, config.embedding_provider):
            if prov in seen:
                continue
            seen.add(prov)
            ensure_provider_available(prov)
    except ProviderNotReadyError as exc:
        _restore_config_file(backup_before)
        raise provider_not_ready_http(exc) from exc

    need_reinit = provider_changed or (keys_or_base_changed and config.chat_provider in ("openai", "gemini", "claude"))

    if _state.bot:
        try:
            if need_reinit:
                await _state.bot.provider.shutdown(_state.bot.model_name)
                _state.bot.provider = create_provider(config.chat_provider)
                _state.bot.model_name = config.chat_model
                await _state.bot.warm_up()
            elif request.chat_model:
                await _state.bot.change_model(config.chat_model)
        except Exception as exc:
            logger.exception("Failed to apply model change after PUT /config/model")
            raise model_apply_failed_http(phase="reload_provider_or_model", exc=exc) from exc

    return {"status": "success", **_model_config_public_dict()}


@app.get("/config/session-prompt/{session_id}")
async def get_session_prompt_endpoint(identity: CurrentIdentity, session_id: str):
    sid = get_session_scope().qualify_session_http(identity, session_id)
    prompt = get_session_prompt(sid)
    return {
        "session_id": sid,
        "system_prompt": prompt,
        "is_custom": prompt is not None,
    }


@app.put("/config/session-prompt/{session_id}")
async def update_session_prompt_endpoint(identity: CurrentIdentity, session_id: str, request: SessionPromptRequest):
    sid = get_session_scope().qualify_session_http(identity, session_id)
    prompt = set_session_prompt(sid, request.system_prompt)
    return {"status": "success", "session_id": sid, "system_prompt": prompt}


@app.delete("/config/session-prompt/{session_id}")
async def delete_session_prompt_endpoint(identity: CurrentIdentity, session_id: str):
    sid = get_session_scope().qualify_session_http(identity, session_id)
    delete_session_prompt(sid)
    return {"status": "success", "session_id": sid}


@app.get("/config/ui")
async def get_ui_preferences_endpoint():
    config = load_saved_model_config()
    return {"dark_mode": config.ui_dark_mode}


@app.put("/config/ui")
async def update_ui_preferences_endpoint(request: UIPreferencesRequest):
    config = load_saved_model_config()
    config.ui_dark_mode = request.dark_mode
    save_model_config(config)
    return {"status": "success", "dark_mode": config.ui_dark_mode}


# ── tool listing & policy (no HTTP-based tool source editing) ──


@app.get("/tools")
async def list_tools_endpoint(identity: CurrentIdentity):  # noqa: ARG001
    server_tools = []
    for name, tool_data in TOOL_REGISTRY.items():
        fn = tool_data["schema"]["function"]
        server_tools.append(
            {
                "name": name,
                "description": fn.get("description", ""),
                "disabled": name in DISABLED_TOOLS,
                "require_confirmation": name in CONFIRMATION_TOOLS and name not in ALWAYS_ALLOWED_TOOLS,
            }
        )

    edge_devices = []
    for edge_name, tools_dict in EDGE_TOOLS_REGISTRY.items():
        tools = []
        for prefixed_name, entry in tools_dict.items():
            fn = entry["schema"]["function"]
            original_name = prefixed_name.split("__", 1)[1] if "__" in prefixed_name else prefixed_name
            intrinsic = bool(entry.get("require_confirmation"))
            tools.append(
                {
                    "name": original_name,
                    "full_name": prefixed_name,
                    "description": fn.get("description", ""),
                    "disabled": prefixed_name in DISABLED_TOOLS,
                    "require_confirmation": (
                        prefixed_name not in ALWAYS_ALLOWED_TOOLS and (prefixed_name in CONFIRMATION_TOOLS or intrinsic)
                    ),
                }
            )
        edge_devices.append(
            {
                "edge_name": edge_name,
                "tools": tools,
                "online": edge_name in ACTIVE_CONNECTIONS,
                "shared": False,
            }
        )

    return {
        "server_tools": server_tools,
        "edge_devices": edge_devices,
        "edge": edge_devices,
        "disabled_tools": list(DISABLED_TOOLS),
        "confirmation_tools": list(CONFIRMATION_TOOLS),
        "always_allowed_tools": list(ALWAYS_ALLOWED_TOOLS),
    }


def create_app() -> FastAPI:
    """Return the configured FastAPI application (for ASGI servers and tests)."""
    return app


# Touch Path to keep the import (used elsewhere in some test fixtures).
_ = Path

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False)
