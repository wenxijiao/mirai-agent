"""Cost reductions must preserve recent work, recoverability and owner boundaries."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event
from types import SimpleNamespace as NS

import pytest
from yumi.core.features.config import ModelConfig
from yumi.core.features.memory.constants import YUMI_V1_TOOL_RESULT
from yumi.core.features.memory.context import ContextBuilder, _format_transcript_rows
from yumi.core.features.memory.embedding_runner import EmbeddingProcessor
from yumi.core.features.memory.history_payloads import REFERENCE_END, REFERENCE_START, split_tool_reference
from yumi.core.features.prompts.composer import compose_messages
from yumi.core.platform.providers.budget import token_estimate
from yumi.core.platform.runtime.assistant_context import PromptSnapshot
from yumi.core.platform.runtime.embedding_cache import RequestEmbeddingCache, request_embedding_cache
from yumi.core.platform.runtime.usage_context import usage_owner_id
from yumi.core.platform.storage.sqlite_store import SQLiteStore
from yumi.core.platform.tools.replay import normalize_tool_history
from yumi.tools import conversation_tools


def test_detailed_category_guidance_is_not_repeated_in_fixed_rules(tmp_path):
    from yumi.core.features.assistant.personalization import MEMORY_CLASSIFICATION_GUIDANCE, prompt_preferences
    from yumi.core.platform.storage.assistant_store import AssistantStore

    store = AssistantStore(SQLiteStore(tmp_path / "preferences.sqlite3"), "alice")
    rules = prompt_preferences(store)
    assert MEMORY_CLASSIFICATION_GUIDANCE not in rules
    assert "dietary needs" in rules and "response and workflow rules" in rules


def test_stable_facts_are_only_injected_once_and_overflow_facts_still_recalled(monkeypatch):
    rows = [
        dict(
            id=str(i),
            kind="profile",
            content=f"Food preference number {i}",
            session_id="__stable_user_context__",
            importance=i,
        )
        for i in range(5)
    ]
    memory = NS(
        session_id="personal_test",
        list_long_term_memories=lambda **kwargs: rows,
        can_recall=lambda row: True,
        get_system_message=lambda: {"role": "system", "content": "BASE"},
        get_session_summary=lambda sid: None,
        _table_exists=lambda: False,
        build_related_memory_message=lambda *args, **kwargs: None,
    )
    builder = ContextBuilder(memory)
    monkeypatch.setattr(builder.retriever, "_long_term_candidates", lambda *args, **kwargs: [NS(id="0", score=0.99)])
    messages = builder.build("Food preference", max_cross_session=10)
    text = json.dumps(messages)
    assert all(text.count(row["content"]) == 1 for row in rows)
    assert "number 0" in messages[-1]["content"]
    rows.pop(0)
    monkeypatch.setattr(
        builder.retriever, "_long_term_candidates", lambda *args, **kwargs: pytest.fail("all facts are already present")
    )
    assert len(builder.build("Food preference", max_cross_session=10)) == 2


def tool_rows(payload):
    return [
        dict(id="request", role="user", content="Read the records", timestamp="t0"),
        dict(id="call", role="assistant", content="[YUMI_TOOL_CALLS]"),
        dict(
            id="result",
            role="tool",
            content=YUMI_V1_TOOL_RESULT + json.dumps({"name": "read", "tool_call_id": "c1", "content": payload}),
        ),
        dict(id="answer", role="assistant", content="Done"),
    ]


def test_only_older_payloads_are_compacted_and_current_loop_stays_verbatim():
    from yumi.core.features.memory.constants import YUMI_V1_TOOL_CALLS

    payload = "original result; " * 700
    rows = tool_rows(payload)
    rows[1]["content"] = YUMI_V1_TOOL_CALLS + json.dumps(
        {"tool_calls": [{"id": "c1", "function": {"name": "read", "arguments": {}}}]}
    )
    original = deepcopy(rows)
    assert next(m["content"] for m in _format_transcript_rows(rows) if m["role"] == "tool") == payload
    rows += [
        dict(id="recent", role="user", content="Hello", timestamp="t1"),
        dict(id="recent-answer", role="assistant", content="Hi"),
    ]
    formatted = _format_transcript_rows(rows)
    compact = next(m for m in formatted if m["role"] == "tool")
    assert len(compact["content"]) < 1300
    assert 'event_id="result"' in compact["content"]
    assert compact["tool_call_id"] == "c1"
    assert token_estimate(compact) < token_estimate({**compact, "content": payload}) / 3
    assert rows[:4] == original
    assert normalize_tool_history(formatted, strict=True) == formatted

    memory = NS(session_id="personal_test", get_context=lambda **kwargs: formatted)
    snapshot = PromptSnapshot()
    cfg = ModelConfig(chat_append_current_time=False)
    first = compose_messages(
        memory,
        prompt="Current task",
        tools=None,
        ephemeral_messages=[],
        cfg=cfg,
        upload_mode="vision",
        prompt_snapshot=snapshot,
    )
    snapshot.tool_messages = [{"role": "tool", "tool_call_id": "new", "content": payload}]
    second = compose_messages(
        memory, prompt=None, tools=None, ephemeral_messages=[], cfg=cfg, upload_mode="vision", prompt_snapshot=snapshot
    )
    assert second[: len(first)] == first
    assert second[-1]["content"] == payload


def test_old_manual_attachment_retains_question_and_recoverable_reference():
    payload = {"items": [{"text": "vocabulary" * 30, "id": i} for i in range(80)]}
    text = (
        "Are these useful?"
        + REFERENCE_START
        + json.dumps({"tool": "list_items", "result": json.dumps(payload)})
        + REFERENCE_END
    )
    rows = [
        dict(id="attachment", role="user", content=text, timestamp="t0"),
        dict(id="new", role="user", content="Hello", timestamp="t1"),
    ]
    formatted = _format_transcript_rows(rows)
    question, data = split_tool_reference(formatted[0]["content"])
    assert "Are these useful?" in question
    assert "read_conversation_record" in data["result"] and 'event_id="attachment"' in data["result"]
    assert len(formatted[0]["content"]) < 1500
    assert rows[0]["content"] == text
    malformed = {**rows[0], "content": text[: -len(REFERENCE_END)]}
    assert text[: -len(REFERENCE_END)] in _format_transcript_rows([malformed, rows[1]])[0]["content"]


def test_saved_payload_pages_are_exact_and_access_is_scoped(tmp_path, monkeypatch):
    store = SQLiteStore(tmp_path / "records.sqlite3")
    payload = '"quoted"\n中文\x01' * 2000
    row = dict(
        id="result",
        session_id="u_alice__personal_1",
        role="tool",
        content=YUMI_V1_TOOL_RESULT + json.dumps({"content": payload}),
        timestamp_num=1,
    )
    store.upsert_event_from_message(row)
    memory = NS(sqlite=store, can_recall=lambda row: True)
    monkeypatch.setattr(conversation_tools, "get_chat_owner_user_id", lambda: "alice")
    monkeypatch.setattr(conversation_tools, "get_current_identity", lambda: NS(user_id="alice"))
    monkeypatch.setattr(
        conversation_tools, "get_memory_factory", lambda: NS(get_for_session_owner=lambda owner: memory)
    )
    monkeypatch.setattr(
        conversation_tools,
        "get_session_scope",
        lambda: NS(owner_user_from_session_id=lambda sid: sid.split("__")[0][2:]),
    )
    chunks = []
    offset = 0
    while offset is not None:
        result = conversation_tools.read_conversation_record("result", offset, 4000)
        assert len(result) <= 7000
        page = json.loads(result)
        chunks.append(page["content"])
        offset = page["next_offset"]
    assert "".join(chunks) == payload
    for changes in [
        dict(session_id="u_bob__personal_1"),
        dict(role="assistant", content="private reasoning"),
        dict(session_id="u_alice__group_1"),
    ]:
        store.upsert_event_from_message({**row, **changes})
        assert "error" in json.loads(conversation_tools.read_conversation_record("result"))
    store.upsert_event_from_message(row)
    memory.can_recall = lambda row: False
    assert "error" in json.loads(conversation_tools.read_conversation_record("result"))
    memory.can_recall = lambda row: True
    with store.connect() as conn:
        conn.execute("UPDATE sessions SET status='deleted' WHERE session_id=?", (row["session_id"],))
    assert "error" in json.loads(conversation_tools.read_conversation_record("result"))


def test_vector_reuse_counts_only_actual_provider_calls_and_is_request_scoped():
    calls = []
    processor = EmbeddingProcessor.__new__(EmbeddingProcessor)
    processor.embed_model = "model-a"
    processor.embedding_available = True
    processor.fallback_vector_size = 2
    processor.embed_provider = NS(embed=lambda model, text: calls.append((model, text)) or [1.0, 2.0])
    cache = RequestEmbeddingCache()
    token = request_embedding_cache.set(cache)
    owner = usage_owner_id.set("alice")
    try:
        processor.get_vector("same")[0] = 99
        assert processor.get_vector("same") == [1.0, 2.0]
        assert len(calls) == 1
        processor.embed_model = "model-b"
        processor.get_vector("same")
        other = usage_owner_id.set("bob")
        try:
            processor.get_vector("same")
        finally:
            usage_owner_id.reset(other)
        assert len(calls) == 3
        cache.close()
        processor.get_vector("same")
        assert len(calls) == 4
    finally:
        request_embedding_cache.reset(token)
        usage_owner_id.reset(owner)
    processor.get_vector("same")
    assert len(calls) == 5


def test_fact_search_history_search_and_message_write_share_one_billed_embedding(tmp_path, monkeypatch):
    from yumi.core.features.memory.embedding_state import _MeteringEmbedWrapper
    from yumi.core.features.memory.memory import Memory
    from yumi.core.platform.runtime.usage_context import embedding_tokens

    calls, billed = [], []

    def embed(model, text):
        calls.append(text)
        embedding_tokens.set(7)
        return [1.0, 2.0]

    cfg = ModelConfig(embedding_provider="openai", embedding_model="test", embedding_dim=2)
    provider = _MeteringEmbedWrapper(NS(embed=embed))
    monkeypatch.setattr("yumi.core.features.memory.memory.load_model_config", lambda: cfg)
    monkeypatch.setattr("yumi.core.features.memory.context.load_model_config", lambda: cfg)
    monkeypatch.setattr("yumi.core.features.memory.embedding_runner.load_model_config", lambda: cfg)
    monkeypatch.setattr("yumi.core.features.memory.memory.get_embed_provider", lambda: provider)
    monkeypatch.setattr(
        "yumi.core.platform.dispatch.auxiliary_usage.record_auxiliary_usage", lambda **kwargs: billed.append(kwargs)
    )
    memory = Memory(session_id="personal_cost_test", storage_dir=str(tmp_path / "memory"))
    memory.create_long_term_memory(kind="fact", content="Trip plans include a train", session_id="personal_old")
    memory.messages.create("personal_old", "user", "Trip plans are for next month")
    calls.clear()
    billed.clear()
    cache = RequestEmbeddingCache()
    token = request_embedding_cache.set(cache)
    owner = usage_owner_id.set("alice")
    try:
        memory.get_context(query="Find my trip plans")
        memory.add_message("user", "Find my trip plans")
    finally:
        cache.close()
        request_embedding_cache.reset(token)
        usage_owner_id.reset(owner)
    assert calls == ["Find my trip plans"]
    assert len(billed) == 1 and billed[0]["prompt_tokens"] == 7


def test_concurrent_vector_requests_share_one_call_but_failures_can_retry():
    cache = RequestEmbeddingCache()
    provider = object()
    entered = Event()
    release = Event()
    calls = []

    def compute():
        calls.append(1)
        entered.set()
        assert release.wait(3)
        return [1.0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.get, "alice", provider, "model", "same", compute)
        assert entered.wait(3)
        second = pool.submit(cache.get, "alice", provider, "model", "same", compute)
        release.set()
        assert first.result() == second.result() == [1.0]
    assert len(calls) == 1
    with pytest.raises(RuntimeError):
        cache.get("alice", provider, "model", "retry", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    assert cache.get("alice", provider, "model", "retry", lambda: [2.0]) == [2.0]


def test_chat_request_clears_vector_cache_even_when_cancelled(monkeypatch):
    from yumi.core.features.chat.service import ChatTurnService
    from yumi.core.platform.runtime import RuntimeState

    captured = []

    async def run(self, ctx, sink):
        captured.append(request_embedding_cache.get())
        raise asyncio.CancelledError()
        yield {}

    monkeypatch.setattr(ChatTurnService, "_run_turn", run)

    async def check():
        with pytest.raises(asyncio.CancelledError):
            async for _ in ChatTurnService(RuntimeState()).stream_chat_turn("hello", "test"):
                pass
        assert request_embedding_cache.get() is None

    asyncio.run(check())
    assert captured and not captured[0]._active
