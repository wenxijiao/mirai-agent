"""ToolDispatcher: argument parsing, local/edge classification, parallel run."""

from __future__ import annotations

import asyncio

import pytest
import yumi.core.platform.tools.trace as trace_mod
from yumi.core.platform.dispatch.context import ToolInvocation, ToolResult, TurnContext
from yumi.core.platform.dispatch.dispatcher import ToolDispatcher, canonical_local_tool_name
from yumi.core.platform.dispatch.edge import EdgeToolExecutor
from yumi.core.platform.dispatch.local import LocalToolExecutor
from yumi.core.platform.runtime import get_default_runtime
from yumi.core.platform.tools.tool import TOOL_REGISTRY
from yumi.core.platform.tools.trace import clear_memory_buffer, list_traces


@pytest.fixture
def runtime():
    return get_default_runtime()


@pytest.fixture
def dispatcher(runtime):
    return ToolDispatcher(
        runtime,
        local_executor=LocalToolExecutor(timeout=5),
        edge_executor=EdgeToolExecutor(runtime, default_timeout=5),
    )


@pytest.fixture(autouse=True)
def isolated_tool_trace(monkeypatch):
    clear_memory_buffer()
    monkeypatch.setattr(trace_mod, "_disk_bootstrapped", True)
    monkeypatch.setattr(trace_mod, "_append_jsonl_line", lambda _rec: None)
    yield
    clear_memory_buffer()


def _ctx() -> TurnContext:
    return TurnContext(prompt="hi", session_id="s1")


def _tcall(name: str, args: str | dict) -> dict:
    return {"id": "c1", "function": {"name": name, "arguments": args}}


def test_disabling_tool_while_waiting_prevents_execution(dispatcher, monkeypatch):
    calls = []
    monkeypatch.setitem(TOOL_REGISTRY, "echo", {"callable": lambda: calls.append("executed")})
    invocations, errors = dispatcher.prepare([_tcall("echo", {})], _ctx())
    assert not errors
    monkeypatch.setattr("yumi.core.platform.tools.visibility.model_disabled_tools", lambda *args, **kwargs: {"echo"})
    result = asyncio.run(dispatcher.run_all(invocations, _ctx()))
    assert calls == []
    assert result[0].status == "error"
    assert "disabled before execution" in result[0].result


def test_timeout_is_an_unknown_outcome(monkeypatch):
    async def timeout(*args, **kwargs):
        raise asyncio.TimeoutError

    monkeypatch.setattr("yumi.core.platform.dispatch.local.execute_registered_tool", timeout)
    invocation = ToolInvocation(kind="local", func_name="write", tool_message_name="write", args={})
    result = asyncio.run(LocalToolExecutor(timeout=1).run(invocation))
    assert result.status == "unknown"
    assert "may still complete" in result.result


def test_canonical_strips_functions_prefix(monkeypatch):
    monkeypatch.setitem(TOOL_REGISTRY, "echo", {})
    assert canonical_local_tool_name("functions.echo") == "echo"
    monkeypatch.delitem(TOOL_REGISTRY, "echo", raising=False)


def test_canonical_lowercases_when_only_lower_present(monkeypatch):
    monkeypatch.setitem(TOOL_REGISTRY, "echo", {})
    assert canonical_local_tool_name("ECHO") == "echo"
    monkeypatch.delitem(TOOL_REGISTRY, "echo", raising=False)


def test_canonical_passes_edge_prefix_through():
    assert canonical_local_tool_name("edge_dev__do_thing") == "edge_dev__do_thing"


def test_prepare_local_tool_classified_as_local(dispatcher, monkeypatch):
    monkeypatch.setitem(TOOL_REGISTRY, "echo", {})
    invs, events = dispatcher.prepare([_tcall("echo", '{"a":1}')], _ctx())
    assert events == []
    assert len(invs) == 1
    assert invs[0].kind == "local"
    assert invs[0].tool_call_id == "c1"
    assert invs[0].args == {"a": 1}
    monkeypatch.delitem(TOOL_REGISTRY, "echo", raising=False)


def test_prepare_unknown_tool_yields_error_and_message(dispatcher):
    ctx = _ctx()
    invs, events = dispatcher.prepare([_tcall("nope", "{}")], ctx)
    assert invs == []
    assert len(events) == 1
    assert events[0].status == "error"
    assert ctx.ephemeral_messages and ctx.ephemeral_messages[-1]["role"] == "tool"
    assert ctx.ephemeral_messages[-1]["tool_call_id"] == "c1"


def test_prepare_unknown_tool_records_trace(dispatcher, isolated_tool_trace):
    ctx = _ctx()
    invs, events = dispatcher.prepare([_tcall("nope", "{}")], ctx)

    assert invs == []
    assert events
    traces = list_traces(session_id="s1", limit=10)
    assert len(traces) == 1
    assert traces[0]["tool_name"] == "nope"
    assert traces[0]["status"] == "error"
    assert "not registered" in traces[0]["result_preview"]


def test_prepare_invalid_json_arguments_repaired(dispatcher, monkeypatch):
    monkeypatch.setitem(TOOL_REGISTRY, "echo", {})
    invs, events = dispatcher.prepare([_tcall("echo", "{a:1,}")], _ctx())
    assert events == []
    assert len(invs) == 1
    assert "a" in invs[0].args
    monkeypatch.delitem(TOOL_REGISTRY, "echo", raising=False)


def test_prepare_unrepairable_json_yields_error(dispatcher, monkeypatch):
    monkeypatch.setitem(TOOL_REGISTRY, "echo", {})
    ctx = _ctx()
    invs, events = dispatcher.prepare([_tcall("echo", "][not parseable")], ctx)
    assert invs == [] or all(i.args == {} for i in invs)
    monkeypatch.delitem(TOOL_REGISTRY, "echo", raising=False)


def test_prepare_unrepairable_json_records_trace(dispatcher, monkeypatch, isolated_tool_trace):
    monkeypatch.setitem(TOOL_REGISTRY, "echo", {})
    ctx = _ctx()
    invs, events = dispatcher.prepare([_tcall("echo", "][not parseable")], ctx)

    assert invs == []
    assert events
    traces = list_traces(session_id="s1", limit=10)
    assert len(traces) == 1
    assert traces[0]["tool_name"] == "echo"
    assert traces[0]["status"] == "error"
    assert "Invalid JSON" in traces[0]["result_preview"]
    monkeypatch.delitem(TOOL_REGISTRY, "echo", raising=False)


def test_prepare_set_timer_stamps_session_id(dispatcher, monkeypatch):
    monkeypatch.setitem(TOOL_REGISTRY, "set_timer", {})
    ctx = _ctx()
    ctx.session_id = "abc"
    invs, _ = dispatcher.prepare([_tcall("set_timer", '{"delay": 5}')], ctx)
    assert invs[0].args["session_id"] == "abc"
    monkeypatch.delitem(TOOL_REGISTRY, "set_timer", raising=False)


def test_run_all_executes_in_parallel(dispatcher):
    invs = [
        ToolInvocation(kind="local", func_name="t1", tool_message_name="t1", args={}),
        ToolInvocation(kind="local", func_name="t2", tool_message_name="t2", args={}),
    ]

    async def fake_run(inv):
        await asyncio.sleep(0.01)
        return ToolResult(func_name=inv.func_name, result="ok", status="success")

    dispatcher._run_one = fake_run  # type: ignore[assignment]
    results = asyncio.run(dispatcher.run_all(invs, _ctx()))
    assert [r.result for r in results] == ["ok", "ok"]
    assert results[0].func_name == "t1"
    assert results[1].func_name == "t2"


def test_edge_access_is_rechecked_after_preparation(dispatcher, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    scope = SimpleNamespace(filter_edge_tool_schemas=lambda *_: [])
    monkeypatch.setattr("yumi.core.platform.plugins.get_edge_scope", lambda: scope)
    run = AsyncMock()
    monkeypatch.setattr(dispatcher.edge_executor, "run", run)
    invocation = ToolInvocation(kind="edge", func_name="edge_home_weather", tool_message_name="weather", args={})
    result = asyncio.run(dispatcher._run_one(invocation))
    assert result.status == "error" and "no longer available" in result.result
    run.assert_not_called()


def test_internal_edge_execution_rechecks_the_actual_owner(dispatcher, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from yumi.core.platform.plugins.identity import Identity

    seen = []

    def visible(identity, *_):
        seen.append(identity.user_id)
        return [{"function": {"name": "edge_home_weather"}}]

    monkeypatch.setattr(
        "yumi.core.platform.plugins.get_edge_scope", lambda: SimpleNamespace(filter_edge_tool_schemas=visible)
    )
    monkeypatch.setattr(
        "yumi.core.platform.plugins.get_identity_provider",
        lambda: SimpleNamespace(current=lambda: Identity(user_id="system", source="internal")),
    )
    run = AsyncMock(return_value=ToolResult(func_name="edge_home_weather", result="sunny", status="success"))
    monkeypatch.setattr(dispatcher.edge_executor, "run", run)
    invocation = ToolInvocation(
        kind="edge", func_name="edge_home_weather", tool_message_name="weather", args={}, caller_user_id="alice"
    )
    result = asyncio.run(dispatcher._run_one(invocation))
    assert result.status == "success" and seen == ["alice"]
    run.assert_awaited_once_with(invocation)
