"""Regression scenarios from the prompt/agent-loop review."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from yumi.core.chatbot import YumiBot
from yumi.core.features.chat.service import ChatTurnService, _persist_tool_ephemeral_spans
from yumi.core.features.config import ModelConfig
from yumi.core.features.memory.memory import Memory
from yumi.core.platform.dispatch import TurnContext
from yumi.core.platform.providers.openai_provider import OpenAIProvider, _normalize_messages_for_strict_openai_compat
from yumi.core.platform.runtime import RuntimeState
from yumi.core.platform.runtime.assistant_context import PromptSnapshot
from yumi.core.platform.tools.replay import normalize_tool_history


def call(cid, city):
    return {"id": cid, "type": "function", "function": {"name": "weather", "arguments": {"city": city}}}


def schema(name):
    return {
        "type": "function",
        "function": {"name": name, "description": name, "parameters": {"type": "object", "properties": {}}},
    }


@pytest.fixture
def memory(tmp_path, monkeypatch):
    cfg = ModelConfig(embedding_model=None, memory_max_recent_messages=30)
    monkeypatch.setattr("yumi.core.features.memory.memory.load_model_config", lambda: cfg)
    monkeypatch.setattr("yumi.core.features.memory.context.load_model_config", lambda: cfg)
    return Memory(session_id="review_test", storage_dir=str(tmp_path / "memory"))


def test_mixed_result_ids_survive_storage_reopen_and_wire(memory):
    spans = [
        {"role": "assistant", "content": "", "tool_calls": [call("a", "Auckland"), call("b", "Wellington")]},
        {"role": "tool", "tool_call_id": "b", "name": "weather", "content": "Denied by user"},
        {
            "role": "tool",
            "tool_call_id": "a",
            "name": "weather",
            "content": "Auckland: sunny",
            "yumi_tool_metrics": {"duration_ms": 9, "status": "success"},
        },
    ]
    memory.add_message("user", "Check the weather in both cities")
    memory.persist_openai_messages(spans)
    reopened = Memory(session_id=memory.session_id, storage_dir=memory.db_dir)
    wire = _normalize_messages_for_strict_openai_compat(reopened.get_context())
    results = {m["tool_call_id"]: m["content"] for m in wire if m["role"] == "tool"}
    assert results == {"a": "Auckland: sunny", "b": "Denied by user"}
    observations = {m["call_id"]: m for m in reopened.list_tool_observations()}
    assert "Auckland" in observations["a"]["args_summary"]
    assert "Wellington" in observations["b"]["args_summary"]


def test_ambiguous_legacy_results_are_not_guessed():
    messages = [
        {"role": "assistant", "tool_calls": [call("a", "A"), call("b", "B")]},
        {"role": "tool", "name": "weather", "content": "approved"},
        {"role": "tool", "name": "weather", "content": "denied"},
    ]
    fixed = normalize_tool_history(messages)
    assert all("unknown" in m["content"] for m in fixed[1:])
    with pytest.raises(ValueError, match="Missing tool result ID"):
        normalize_tool_history(messages, strict=True)
    with pytest.raises(ValueError, match="unique pending call"):
        normalize_tool_history([messages[0], {"role": "tool", "tool_call_id": "unrelated"}])


def test_full_turn_keeps_recall_and_current_task_after_six_batches(memory, monkeypatch):
    recalled = "RECALLED_HOME_LOCATION_AUCKLAND"
    monkeypatch.setattr(
        memory, "build_related_memory_message", lambda *args, **kwargs: {"role": "system", "content": recalled}
    )
    captured = []

    class Provider:
        async def chat_stream(self, **kwargs):
            captured.append(kwargs["messages"])
            yield {"type": "finish", "reason": "stop"}

    bot = YumiBot(Provider(), "test", runtime_config=ModelConfig())
    monkeypatch.setattr(bot, "_get_memory", lambda sid: memory)
    snapshot = PromptSnapshot()

    async def run():
        for _ in [0]:
            async for _chunk in bot.chat_stream(
                prompt="CURRENT_TASK check weather where I live", session_id=memory.session_id, prompt_snapshot=snapshot
            ):
                pass
        for batch in range(6):
            calls = [call(f"{batch}_{i}", "Auckland") for i in range(4)]
            spans = [{"role": "assistant", "tool_calls": calls}]
            spans += [{"role": "tool", "tool_call_id": c["id"], "name": "weather", "content": "sunny"} for c in calls]
            _persist_tool_ephemeral_spans(spans, memory.session_id, bot, prompt_snapshot=snapshot)
            assert spans == []
            async for _chunk in bot.chat_stream(session_id=memory.session_id, prompt_snapshot=snapshot):
                pass

    asyncio.run(run())
    assert len(captured) == 7
    assert all(recalled in str(messages) and "CURRENT_TASK" in str(messages) for messages in captured)
    assert sum(m["role"] == "tool" for m in captured[-1]) == 24
    assert sum(m["role"] == "user" for m in captured[-1]) == 1


def test_runtime_context_never_lists_invisible_edge(monkeypatch):
    from yumi.core.platform.tools import context_prefetch as prefetch
    from yumi.core.platform.tools import routing

    registry = {
        "alice": {"allowed": {"schema": schema("allowed")}},
        "bob-private-device": {"hidden": {"schema": schema("hidden")}},
    }
    monkeypatch.setattr(prefetch, "EDGE_TOOLS_REGISTRY", registry)
    monkeypatch.setattr(prefetch, "ACTIVE_CONNECTIONS", dict.fromkeys(registry))
    monkeypatch.setattr(prefetch, "context_prefetch_items", AsyncMock(return_value=[]))
    scope = SimpleNamespace(filter_edge_tool_schemas=lambda *args: [schema("allowed")])
    monkeypatch.setattr(routing, "get_edge_scope", lambda: scope)
    block = asyncio.run(prefetch.runtime_context_prompt_block())
    assert block is not None
    assert "alice" in block
    assert "bob-private-device" not in block and "hidden" not in block


def test_forced_tools_reapply_scope_and_disabled_policy(monkeypatch):
    from yumi.core.platform.tools import routing

    runtime = RuntimeState()
    runtime.edge_registry.tools["device"] = {n: {"schema": schema(n)} for n in ["allowed", "disabled", "unentitled"]}
    runtime.tool_policy.disabled_tools.add("disabled")
    scope = SimpleNamespace(
        filter_edge_tool_schemas=lambda identity, registry, disabled: [
            schema(n) for n in ["allowed", "disabled"] if n not in disabled
        ]
    )
    monkeypatch.setattr(routing, "get_edge_scope", lambda: scope)
    ctx = TurnContext(prompt="read", session_id="review")
    ctx.active_edge_tool_names.update(["allowed", "disabled", "unentitled"])
    out = ChatTurnService(runtime)._with_forced_edge_tools([schema("unentitled")], ctx)
    assert out is not None
    assert [s["function"]["name"] for s in out] == ["allowed"]


def test_deepseek_thinking_controls_wire_and_preserves_prior_reasoning():
    captured = []

    async def empty_stream():
        if False:
            yield None

    async def create(**kwargs):
        captured.append(kwargs)
        return empty_stream()

    provider = object.__new__(OpenAIProvider)
    provider.api_family = "deepseek"
    provider.max_output_tokens = 4096
    provider._async_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    async def run():
        for enabled in [False, True]:
            async for _ in provider.chat_stream(
                model="deepseek-v4-pro",
                tools=[schema("weather")],
                messages=[
                    {"role": "assistant", "content": "old", "reasoning_content": "saved"},
                    {"role": "user", "content": "now"},
                ],
                think=enabled,
            ):
                pass

    asyncio.run(run())
    assert captured[0]["extra_body"]["thinking"] == {"type": "disabled"}
    assert captured[1]["extra_body"]["thinking"] == {"type": "enabled"}
    assert captured[0]["extra_body"]["user_id"] == captured[1]["extra_body"]["user_id"]
    assert captured[1]["messages"][0]["reasoning_content"] == "saved"
