"""One account, one active conversation; account-owned management APIs."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from yumi.core.platform.http.dependencies import CurrentIdentity
from yumi.core.platform.plugins import get_edge_scope, get_memory_factory, get_session_scope
from yumi.core.platform.runtime import get_default_runtime
from yumi.core.platform.runtime.assistant_context import active_requests
from yumi.core.platform.storage.assistant_store import AssistantStore, StaleRevision
from yumi.core.platform.tools.tool import TOOL_REGISTRY

router = APIRouter(prefix="/assistant", tags=["Personal assistant"])


def _store(identity):
    return AssistantStore(get_memory_factory().get_for_identity(identity).sqlite, identity.user_id)


def _qualify(identity):
    return lambda sid: get_session_scope().qualify_session_http(identity, sid)


class ResetRequest(BaseModel):
    revision: int = Field(ge=1)


class InstructionsRequest(BaseModel):
    content: str = Field(max_length=16000)


class PreferencesRequest(BaseModel):
    response_language: str | None = Field(default=None, min_length=1, max_length=80)
    instructions: str | None = Field(default=None, max_length=16000)

    @field_validator("response_language")
    @classmethod
    def validate_response_language(cls, value):
        from .personalization import normalize_language

        return normalize_language(value) if value is not None else None


class MemoryRequest(BaseModel):
    content: str = Field(min_length=1, max_length=16000)
    kind: Literal[
        "preference",
        "profile",
        "fact",
        "constraint",
        "project",
        "routine",
        "relationship",
        "communication_style",
        "do_not_assume",
        "decision",
        "task_state",
        "summary",
    ] = "fact"
    source_message_ids: list[str] = Field(default_factory=list, max_length=30)


class PersonalToolRequest(BaseModel):
    disabled: bool
    require_confirmation: bool | None = None
    ai_access: Literal["none", "ask", "auto"] | None = None
    manual_require_confirmation: bool | None = None


@router.get("")
async def current(identity: CurrentIdentity, before: int | None = None, limit: int = Query(100, ge=1, le=200)):
    store = _store(identity)
    return store.snapshot(store.current(_qualify(identity)), before=before, limit=limit)


@router.post("/reset")
async def reset(identity: CurrentIdentity, body: ResetRequest):
    store = _store(identity)
    old = store.current(_qualify(identity))
    try:
        state = store.reset(body.revision, _qualify(identity))
    except StaleRevision as exc:
        raise HTTPException(409, str(exc)) from exc
    for task in tuple(active_requests.get(old["session_id"], ())):
        if task is not asyncio.current_task():
            task.cancel()
    return store.snapshot(state)


@router.get("/history")
async def history(
    identity: CurrentIdentity,
    q: str = "",
    channel: str = "",
    before: int | None = None,
    limit: int = Query(50, ge=1, le=200),
):
    return _store(identity).history(
        prefix=get_session_scope().session_id_prefix_for_identity(identity),
        query=q,
        channel=channel,
        before=before,
        limit=limit,
    )


@router.delete("/history/{message_id}")
async def delete_history(identity: CurrentIdentity, message_id: str):
    memory = get_memory_factory().get_for_identity(identity)
    row = memory.sqlite.get_message(message_id)
    if row is None:
        raise HTTPException(404, "Message not found")
    get_session_scope().ensure_message_owned_by_identity(identity, row)
    memory.delete_message(message_id)
    return {"status": "deleted"}


@router.get("/history/{message_id}")
async def history_detail(identity: CurrentIdentity, message_id: str):
    from yumi.core.platform.storage.assistant_store import is_group_session

    store = _store(identity)
    row = store.sqlite.get_message(message_id)
    if (
        row is None
        or row["event_type"] not in {"user_message", "assistant_message"}
        or is_group_session(row["session_id"])
    ):
        raise HTTPException(404, "Message not found")
    get_session_scope().ensure_message_owned_by_identity(identity, row)
    session = store.sqlite.get_session(row["session_id"])
    if session and session.get("status") == "deleted":
        raise HTTPException(404, "Message not found")
    return store.message_detail(row)


@router.get("/memories")
async def memories(identity: CurrentIdentity):
    # Index old rows once when upgrading; SQLite is authoritative thereafter.
    memory = get_memory_factory().get_for_identity(identity)
    memory.list_long_term_memories(limit=10000)
    from .personalization import BEHAVIOR_KINDS, explicit_language, preferences

    store = _store(identity)
    preferences(store)
    return {
        "memories": [
            r for r in store.memories() if not (r["kind"] in BEHAVIOR_KINDS and explicit_language(r["content"]))
        ]
    }


@router.post("/memories")
async def create_memory(identity: CurrentIdentity, body: MemoryRequest):
    if not body.content.strip():
        raise HTTPException(422, "Memory cannot be blank")
    memory = get_memory_factory().get_for_identity(identity)
    for mid in body.source_message_ids:
        source = memory.sqlite.get_message(mid)
        if source is None:
            raise HTTPException(404, "Source message not found")
        get_session_scope().ensure_message_owned_by_identity(identity, source)
    from .personalization import BEHAVIOR_KINDS, explicit_language, save_preferences, save_rule

    if body.kind in BEHAVIOR_KINDS:
        return save_rule(_store(identity), body.content, kind=body.kind, source_ids=body.source_message_ids)
    if language := explicit_language(body.content):
        saved = save_preferences(_store(identity), response_language=language)
        return {"preference": saved, "saved_as": "response_language"}
    row = memory.create_long_term_memory(
        kind=body.kind,
        content=body.content.strip(),
        session_id="__stable_user_context__",
        source_message_ids=body.source_message_ids,
        confidence=1.0,
        importance=0.9,
    )
    if row is None:
        raise HTTPException(500, "Could not save memory")
    return {"memory": row}


@router.delete("/memories/{memory_id}")
async def forget_memory(identity: CurrentIdentity, memory_id: str):
    memory = get_memory_factory().get_for_identity(identity)
    if memory_id not in {r["id"] for r in _store(identity).memories()}:
        raise HTTPException(404, "Memory not found")
    memory.delete_long_term_memory(memory_id)
    return {"status": "forgotten"}


@router.put("/memories/{memory_id}")
async def edit_memory(identity: CurrentIdentity, memory_id: str, body: MemoryRequest):
    if not body.content.strip():
        raise HTTPException(422, "Memory cannot be blank")
    if memory_id not in {r["id"] for r in _store(identity).memories()}:
        raise HTTPException(404, "Memory not found")
    existing = next(r for r in _store(identity).memories() if r["id"] == memory_id)
    if existing["content"].strip() == body.content.strip() and existing["kind"] == body.kind:
        return {"memory": existing}
    from .personalization import BEHAVIOR_KINDS, save_rule

    if (
        existing["kind"] in BEHAVIOR_KINDS
        and body.kind in BEHAVIOR_KINDS
        and existing["session_id"] == "__stable_user_context__"
    ):
        memory = get_memory_factory().get_for_identity(identity)
        for mid in body.source_message_ids:
            source = memory.sqlite.get_message(mid)
            if source is None:
                raise HTTPException(404, "Message not found")
            get_session_scope().ensure_message_owned_by_identity(identity, source)
        try:
            return save_rule(
                _store(identity), body.content, kind=body.kind, memory_id=memory_id, source_ids=body.source_message_ids
            )
        except ValueError as exc:
            raise HTTPException(404 if "not found" in str(exc) else 422, str(exc)) from exc
    # Save first; a failed save must not lose the original memory.
    result = await create_memory(identity, body)
    await forget_memory(identity, memory_id)
    return result


@router.get("/instructions")
async def instructions(identity: CurrentIdentity):
    from .personalization import preferences

    return {"content": preferences(_store(identity))["instructions"]}


@router.put("/instructions")
async def update_instructions(identity: CurrentIdentity, body: InstructionsRequest):
    from .personalization import save_preferences

    return {"content": save_preferences(_store(identity), instructions=body.content)["instructions"]}


@router.get("/preferences")
async def get_preferences(identity: CurrentIdentity):
    from .personalization import preferences

    return preferences(_store(identity))


@router.put("/preferences")
async def update_preferences(identity: CurrentIdentity, body: PreferencesRequest):
    from .personalization import save_preferences

    return save_preferences(_store(identity), **body.model_dump(exclude_unset=True))


@router.get("/usage")
async def usage(
    identity: CurrentIdentity,
    days: int = Query(7, ge=1, le=31),
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    timezone: str = Query("UTC", max_length=80),
):
    from yumi.core.features.memory.store import get_memory_store

    # UsageRecorder writes a shared ledger even with separate account stores.
    # Read that same ledger with owner filtering, not the per-user transcript DB.
    ledger = AssistantStore(get_memory_store().sqlite, identity.user_id)
    if month:
        try:
            return ledger.monthly_usage(month, timezone)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    return ledger.usage(days)


def visible_tools(identity) -> dict:
    runtime = get_default_runtime()
    policy = runtime.tool_policy
    saved = _store(identity).get("tools", {})
    visible = get_edge_scope().filter_edge_tool_schemas(identity, runtime.edge_registry.tools, set())
    edge_names = {s["function"]["name"] for s in visible}

    def item(name, fn, intrinsic=False, *, device=None, online=True, confirmation_template=None):
        from copy import deepcopy

        own = saved.get(name, {})
        locked = name in policy.disabled_tools
        required = (name in policy.confirmation_tools or intrinsic) and name not in policy.always_allowed_tools
        ai_access = own.get("ai_access", "ask" if own.get("require_confirmation", required) else "auto")
        if required and ai_access == "auto":
            ai_access = "ask"
        parameters = deepcopy(fn.get("parameters", {"type": "object", "properties": {}}))
        # These routing fields belong to the authenticated account, not a form.
        if device is None and name in {"set_timer", "schedule_task", "discover_app_tools"}:
            parameters.get("properties", {}).pop("session_id", None)
            parameters["required"] = [p for p in parameters.get("required", []) if p != "session_id"]
        return {
            "name": name,
            "description": fn.get("description", ""),
            "parameters": parameters,
            "confirmation_template": confirmation_template,
            "device": device,
            "online": online,
            "locked": locked,
            "disabled": locked or own.get("disabled", False),
            "confirmation_locked": required,
            "ai_access": ai_access,
            "require_confirmation": required or ai_access == "ask",
            "manual_require_confirmation": required or own.get("manual_require_confirmation", False),
        }

    server = [
        item(n, t["schema"]["function"], confirmation_template=t.get("confirmation_template"))
        for n, t in TOOL_REGISTRY.items()
    ]
    devices = []
    from yumi.core.platform.runtime.edge_naming import parse_edge_connection_key

    for device, entries in runtime.edge_registry.tools.items():
        rows = [
            item(
                n,
                e["schema"]["function"],
                e.get("require_confirmation", False),
                device=parse_edge_connection_key(device)[1],
                online=device in runtime.edge_registry.active_connections,
                confirmation_template=e.get("confirmation_template"),
            )
            for n, e in entries.items()
            if n in edge_names
        ]
        if rows:
            devices.append(
                {
                    "name": device,
                    "display_name": parse_edge_connection_key(device)[1],
                    "online": device in runtime.edge_registry.active_connections,
                    "tools": rows,
                }
            )
    return {"server_tools": server, "devices": devices}


@router.get("/tools")
async def tools(identity: CurrentIdentity):
    return visible_tools(identity)


@router.put("/tools/{name}")
async def update_tool(identity: CurrentIdentity, name: str, body: PersonalToolRequest):
    catalog = visible_tools(identity)
    available = catalog["server_tools"] + [t for d in catalog["devices"] for t in d["tools"]]
    tool = next((t for t in available if t["name"] == name), None)
    if tool is None:
        raise HTTPException(404, "Tool not available to this account")
    if tool["confirmation_locked"] and (body.ai_access == "auto" or body.manual_require_confirmation is False):
        raise HTTPException(403, "This tool requires confirmation")
    store = _store(identity)
    # Read/modify/write in one transaction so concurrent device changes survive.
    with store.sqlite.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        saved = store._read(conn, "tools", {})
        changes = body.model_dump(exclude_none=True)
        if body.ai_access is not None:
            changes["require_confirmation"] = body.ai_access == "ask"
        elif body.require_confirmation is not None:
            changes["ai_access"] = "ask" if body.require_confirmation else "auto"
        saved[name] = {**saved.get(name, {}), **changes}
        store._write(conn, "tools", saved)
    return {"status": "saved"}


from yumi.core.features.assistant.tool_runs import router as tool_runs_router  # noqa: E402

router.include_router(tool_runs_router)
