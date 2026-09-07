from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from yumi.core.features.assistant import router as assistant
from yumi.core.features.assistant import tool_runs
from yumi.core.platform.dispatch.confirmation import ConfirmationGate
from yumi.core.platform.dispatch.context import ToolInvocation, TurnContext
from yumi.core.platform.http.dependencies import current_identity_dependency
from yumi.core.platform.plugins import Identity
from yumi.core.platform.runtime import get_default_runtime
from yumi.core.platform.storage.assistant_store import AssistantStore
from yumi.core.platform.storage.sqlite_store import SQLiteStore
from yumi.core.platform.tools.tool import TOOL_REGISTRY, register_tool


@pytest.fixture
def env(tmp_path, monkeypatch):
    sqlite = SQLiteStore(tmp_path / "tools.db")
    stores = {u: AssistantStore(sqlite, u) for u in ["alice", "bob"]}
    monkeypatch.setattr(assistant, "_store", lambda identity: stores[identity.user_id])
    monkeypatch.setattr(assistant, "_qualify", lambda identity: lambda sid: f"u_{identity.user_id}__{sid}")
    scope = SimpleNamespace(owner_user_from_session_id=lambda sid: sid.split("__")[0].removeprefix("u_"))
    monkeypatch.setattr(tool_runs, "get_session_scope", lambda: scope)
    from yumi.core.platform.runtime import assistant_context

    monkeypatch.setattr(assistant_context, "personal_store", lambda owner: stores[owner])
    original = dict(TOOL_REGISTRY)
    TOOL_REGISTRY.clear()
    seen = []

    async def echo(text: str, count: int = 1):
        seen.append((text, count))
        await asyncio.sleep(0.01)
        return text * count

    register_tool(echo, name="demo_echo", params={"text": "Text to repeat", "count": "Repeat count"})
    runtime = get_default_runtime()
    old_disabled = set(runtime.tool_policy.disabled_tools)
    old_confirm = set(runtime.tool_policy.confirmation_tools)
    old_always = set(runtime.tool_policy.always_allowed_tools)
    app = FastAPI()
    app.include_router(assistant.router)

    def identity(x_user: str = Header("alice")):
        return Identity(user_id=x_user)

    app.dependency_overrides[current_identity_dependency] = identity
    with TestClient(app) as client:
        yield client, stores, seen, runtime
    TOOL_REGISTRY.clear()
    TOOL_REGISTRY.update(original)
    runtime.tool_policy.disabled_tools = old_disabled
    runtime.tool_policy.confirmation_tools = old_confirm
    runtime.tool_policy.always_allowed_tools = old_always


def submit(client, arguments=None, request_id=None, **kwargs):
    return client.post(
        "/assistant/tools/demo_echo/runs",
        json={"arguments": arguments or {"text": "hi"}, "request_id": str(request_id or uuid4())},
        **kwargs,
    )


def finish(client, run_id):
    for _ in range(100):
        row = client.get(f"/assistant/tool-runs/{run_id}").json()["run"]
        if row["status"] not in {"queued", "running"}:
            return row
        time.sleep(0.01)
    pytest.fail("Run did not finish")


def test_catalog_schema_defaults_and_direct_run_without_chat(env):
    client, stores, seen, _ = env
    tool = client.get("/assistant/tools").json()["server_tools"][0]
    assert tool["parameters"]["properties"]["count"]["default"] == 1
    assert tool["parameters"]["required"] == ["text"]
    client.put("/assistant/tools/demo_echo", json={"disabled": False, "ai_access": "none"})
    reply = submit(client, {"text": "hello", "count": 2})
    assert reply.status_code == 202
    row = finish(client, reply.json()["run"]["id"])
    assert row["status"] == "success" and row["result"] == "hellohello"
    assert seen == [("hello", 2)]
    assert stores["alice"].history()["messages"] == []
    assert client.get("/assistant/tools/demo_echo/runs").json()["runs"][0]["origin"] == "manual"


def test_strict_parameters_and_disabled_tools_never_execute(env):
    client, _, seen, runtime = env
    for args in [{"count": 1}, {"text": "x", "count": "2"}, {"text": "x", "unknown": 1}, {"text": "x", "count": True}]:
        assert submit(client, args).status_code == 422
    runtime.tool_policy.disabled_tools.add("demo_echo")
    assert submit(client).status_code == 403
    assert seen == []


def test_confirmation_owner_recheck_and_idempotency(env):
    client, _, seen, _ = env
    client.put(
        "/assistant/tools/demo_echo", json={"disabled": False, "ai_access": "ask", "manual_require_confirmation": True}
    )
    request_id = uuid4()
    row = submit(client, request_id=request_id).json()["run"]
    run_id = row["id"]
    assert row["status"] == "awaiting_confirmation" and seen == []
    assert submit(client, request_id=request_id).json()["run"]["id"] == run_id
    assert submit(client, {"text": "different"}, request_id=request_id).status_code == 409
    assert client.get(f"/assistant/tool-runs/{run_id}", headers={"x-user": "bob"}).status_code == 404
    assert (
        client.post(
            f"/assistant/tool-runs/{run_id}/decision", json={"decision": "allow"}, headers={"x-user": "bob"}
        ).status_code
        == 404
    )
    assert client.get("/assistant/tools/demo_echo/runs", headers={"x-user": "bob"}).json()["runs"] == []
    client.put("/assistant/tools/demo_echo", json={"disabled": True})
    assert client.post(f"/assistant/tool-runs/{run_id}/decision", json={"decision": "allow"}).status_code == 403
    client.put("/assistant/tools/demo_echo", json={"disabled": False})
    for _ in range(2):
        assert client.post(f"/assistant/tool-runs/{run_id}/decision", json={"decision": "allow"}).status_code == 200
    assert finish(client, run_id)["status"] == "success"
    assert seen == [("hi", 1)]
    assert submit(client, request_id=request_id).json()["run"]["id"] == run_id


def test_denial_and_mandatory_confirmation(env):
    client, _, seen, runtime = env
    runtime.tool_policy.confirmation_tools.add("demo_echo")
    assert client.put("/assistant/tools/demo_echo", json={"disabled": False, "ai_access": "auto"}).status_code == 403
    row = submit(client).json()["run"]
    assert row["status"] == "awaiting_confirmation"
    result = client.post(f"/assistant/tool-runs/{row['id']}/decision", json={"decision": "deny"}).json()["run"]
    assert result["status"] == "denied" and seen == []
    assert client.get("/assistant/tools/demo_echo/runs").json()["runs"][0]["status"] == "denied"


def test_ai_gate_denies_even_if_model_emits_disabled_ai_tool(env):
    _, stores, seen, runtime = env
    store = stores["alice"]
    state = store.current(lambda sid: f"u_alice__{sid}")
    store.put("tools", {"demo_echo": {"ai_access": "none"}})
    inv = ToolInvocation(kind="local", func_name="demo_echo", tool_message_name="demo_echo", args={"text": "hi"})
    ctx = TurnContext(prompt="hi", session_id=state["session_id"], owner_uid="alice")

    async def run():
        return [r async for r in ConfirmationGate(runtime).filter([inv], ctx)]

    assert all(accepted is None for _, accepted in asyncio.run(run()))
    assert seen == []


def test_history_backfill_deduplicates_and_orders_by_call_time(env):
    from yumi.core.platform.storage.tool_run_store import ToolRunStore

    client, stores, _, _ = env
    sqlite = stores["alice"].sqlite
    history = ToolRunStore(sqlite, "alice")
    history.create(
        {
            "id": "ai-recent-call",
            "tool_name": "demo_echo",
            "status": "success",
            "approval": "confirmed",
            "created_at": "2026-09-06T12:00:00+00:00",
        }
    )
    for ident, owner, date in [
        ("recent", "alice", "2026-09-06"),
        ("old", "alice", "2026-09-01"),
        ("private", "bob", "2026-09-06"),
    ]:
        sqlite.upsert_turn_trace(
            {
                "id": ident,
                "session_id": f"u_{owner}__personal-1",
                "started_at": f"{date}T12:00:00+00:00",
                "rounds": [
                    {
                        "tool_calls": [
                            {"id": "call", "function": {"arguments": '{"text":"hello","password":"hidden"}'}}
                        ],
                        "tool_results": [
                            {
                                "tool": "legacy_alias",
                                "resolved_tool": "demo_echo",
                                "call_id": "call",
                                "status": "success",
                                "result_preview": "hello",
                            }
                        ],
                    }
                ],
            },
            owner_user_id=owner,
        )
    page = client.get("/assistant/tools/demo_echo/runs?limit=1").json()
    assert page["runs"][0]["id"] == "ai-recent-call"
    assert page["runs"][0]["approval"] == "confirmed"
    older = client.get(f"/assistant/tools/demo_echo/runs?before={page['next_before']}").json()
    assert [r["id"] for r in older["runs"]] == ["ai-old-call"]
    assert older["runs"][0]["arguments"]["password"] == "[redacted]"
    assert len(history.history("demo_echo")["runs"]) == 2


def test_expired_confirmation_and_lost_execution_are_not_retried(env):
    from yumi.core.platform.storage.tool_run_store import ToolRunStore

    client, stores, seen, _ = env
    client.put("/assistant/tools/demo_echo", json={"disabled": False, "manual_require_confirmation": True})
    row = submit(client).json()["run"]
    history = ToolRunStore(stores["alice"].sqlite, "alice")
    history.transition(row["id"], {"awaiting_confirmation"}, expires_at=0)
    expired = client.post(f"/assistant/tool-runs/{row['id']}/decision", json={"decision": "allow"}).json()["run"]
    assert expired["status"] == "expired" and seen == []
    history.transition(row["id"], {"expired"}, status="running", expires_at=0)
    assert client.get(f"/assistant/tool-runs/{row['id']}").json()["run"]["status"] == "unknown"
    assert seen == []


def test_ai_confirmation_rechecks_global_disable(env):
    _, stores, _, runtime = env
    store = stores["alice"]
    state = store.current(lambda sid: f"u_alice__{sid}")
    store.put("tools", {"demo_echo": {"ai_access": "ask"}})
    inv = ToolInvocation(kind="local", func_name="demo_echo", tool_message_name="demo_echo", args={"text": "hi"})
    ctx = TurnContext(prompt="hi", session_id=state["session_id"], owner_uid="alice")

    async def run():
        accepted = []
        async for event, invocation in ConfirmationGate(runtime).filter([inv], ctx):
            if getattr(event, "call_id", None):
                runtime.tool_policy.disabled_tools.add("demo_echo")
                runtime.tool_policy.pending_confirmations[event.call_id].set_result("allow")
            if invocation:
                accepted.append(invocation)
        return accepted

    assert asyncio.run(run()) == []
