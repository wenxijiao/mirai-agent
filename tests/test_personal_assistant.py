from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from yumi.core.features.assistant import router as assistant
from yumi.core.features.chat import router as chat
from yumi.core.features.memory.memory import Memory
from yumi.core.features.tools.router import confirm_tool_endpoint
from yumi.core.platform.dispatch.confirmation import ConfirmationGate
from yumi.core.platform.dispatch.context import ToolInvocation, TurnContext
from yumi.core.platform.http.dependencies import current_identity_dependency
from yumi.core.platform.http.schemas import ChatRequest, ToolConfirmationResponse
from yumi.core.platform.plugins import Identity
from yumi.core.platform.runtime import get_default_runtime
from yumi.core.platform.runtime.assistant_context import source_channel
from yumi.core.platform.storage.assistant_store import AssistantStore, StaleRevision, meaningful_recall_query
from yumi.core.platform.storage.sqlite_store import SQLiteStore


def qualify(sid):
    return f"u_alice__{sid}"


@pytest.fixture
def store(tmp_path):
    return AssistantStore(SQLiteStore(tmp_path / "yumi.db"), "alice")


def test_pointer_is_stable_and_reset_keeps_history_and_memories(store):
    first = store.current(qualify)
    store.sqlite.upsert_event_from_message(
        {"id": "hello", "session_id": first["session_id"], "role": "user", "content": "hello"}
    )
    store.sqlite.upsert_memory({"id": "pref", "kind": "preference", "content": "Chinese please"})
    assert store.current(qualify) == first
    after = store.reset(first["revision"], qualify)
    assert after["revision"] == 2 and after["session_id"] != first["session_id"]
    assert store.snapshot(after)["messages"] == []
    assert store.history()["messages"][0]["id"] == "hello"
    assert store.memories()[0]["id"] == "pref"


def test_reset_compare_and_swap_accepts_exactly_one_writer(store):
    first = store.current(qualify)

    def run(_):
        try:
            return store.reset(first["revision"], qualify)["revision"]
        except StaleRevision:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, range(2)), key=str) == [2, "stale"]


def test_separate_accounts_have_separate_pointer_and_settings(store):
    other = AssistantStore(store.sqlite, "bob")
    store.put("instructions", "Answer in Chinese")
    store.put("tools", {"delete_file": {"disabled": True}})
    assert other.get("instructions", "") == ""
    assert other.get("tools", {}) == {}
    assert other.current(lambda sid: f"u_bob__{sid}")["session_id"] != store.current(qualify)["session_id"]


def test_snapshot_latest_page_and_channel_metadata_survive_index_roundtrip(store):
    current = store.current(qualify)
    for i, channel in enumerate(["app", "telegram", "discord"]):
        token = source_channel.set(channel)
        try:
            store.sqlite.upsert_event_from_message(
                {"id": str(i), "session_id": current["session_id"], "role": "user", "content": f"hello {i}"}
            )
        finally:
            source_channel.reset(token)
    page = store.snapshot(current, limit=2)
    assert [m["channel"] for m in page["messages"]] == ["telegram", "discord"]
    assert page["has_more"] is True
    before = page["messages"][0]["seq"]
    assert store.snapshot(current, before=before)["messages"][0]["channel"] == "app"
    assert len(store.history(channel="telegram")["messages"]) == 1


def test_history_hides_deleted_and_group_records_and_literal_search(store):
    for sid, mid, content in [
        ("personal_1", "p", "hello %_"),
        ("group_dc_1", "g", "private group"),
        ("personal_1", "d", "deleted"),
    ]:
        store.sqlite.upsert_event_from_message(
            {"id": mid, "session_id": qualify(sid), "role": "user", "content": content}
        )
    store.sqlite.delete_message("d")
    assert [r["id"] for r in store.history(query="%_")["messages"]] == ["p"]
    assert [r["id"] for r in store.history()["messages"]] == ["p"]


@pytest.mark.parametrize("query", ["接下来呢", "第二个呢", "continue", "what next?"])
def test_vague_followup_does_not_recall_old_segment(query):
    assert not meaningful_recall_query(query)


def test_forgetting_source_removes_prompt_but_keeps_history(tmp_path):
    memory = Memory(session_id="personal_first", storage_dir=tmp_path)
    mid = memory.add_message("user", "my preferred theme is violet")
    row = memory.create_long_term_memory(
        kind="preference",
        content="my preferred theme is violet",
        session_id="__stable_user_context__",
        source_message_ids=[mid],
    )
    memory.update_session_summary("The user prefers violet themes.")
    assert memory.delete_long_term_memory(row["id"])
    assert memory.sqlite.get_message(mid) is not None
    assert not memory.can_recall(memory.sqlite.get_message(mid))
    assert memory.get_session_summary() is None
    assert row["id"] not in {r["id"] for r in memory.list_long_term_memories()}
    # Simulate a stale vector index: it must not resurrect a tombstone.
    memory.long_term.list = lambda **_: [row]
    assert row["id"] not in {r["id"] for r in memory.list_long_term_memories()}
    assert all("violet" not in m.get("content", "") for m in memory.get_context())


def test_personal_context_uses_durable_preferences_not_old_decisions(tmp_path):
    memory = Memory(session_id="personal_new", storage_dir=tmp_path)
    memory.create_long_term_memory(kind="decision", content="Buy the red car", session_id="old")
    memory.create_long_term_memory(kind="preference", content="Use Chinese", session_id="__stable_user_context__")
    rendered = str(memory.get_context(query="接下来呢"))
    assert 'Saved response language label: "Chinese"' in rendered
    assert "Buy the red car" not in rendered


def test_private_channels_route_to_same_server_pointer(monkeypatch, store):
    factory = SimpleNamespace(get_for_identity=lambda _: SimpleNamespace(sqlite=store.sqlite))
    monkeypatch.setattr(chat, "get_memory_factory", lambda: factory)
    monkeypatch.setattr(
        chat, "get_session_scope", lambda: SimpleNamespace(qualify_session_http=lambda _, sid: qualify(sid))
    )
    seen = []

    async def events(prompt, sid, think=False):
        seen.append((sid, source_channel.get()))
        yield {"type": "text", "content": "hello"}

    monkeypatch.setattr(chat, "generate_chat_events", events)

    async def run():
        for channel in ["app", "telegram", "discord"]:
            response = await chat.chat_endpoint(
                None, Identity(user_id="alice"), ChatRequest(prompt="hi", personal=True, channel=channel)
            )
            async for _ in response.body_iterator:
                pass
        with pytest.raises(HTTPException) as exc:
            await chat.chat_endpoint(
                None, Identity(user_id="alice"), ChatRequest(prompt="stale", personal=True, revision=999)
            )
        assert exc.value.status_code == 409

    asyncio.run(run())
    assert len({sid for sid, _ in seen}) == 1
    assert [channel for _, channel in seen] == ["app", "telegram", "discord"]


def test_confirmation_owned_by_account_and_personal_always_allow_is_not_global(monkeypatch, store):
    import yumi.core.platform.runtime.assistant_context as runtime_context

    monkeypatch.setattr(runtime_context, "personal_store", lambda _: store)
    current = store.current(qualify)
    store.put("tools", {"demo": {"require_confirmation": True}})
    runtime = get_default_runtime()
    runtime.tool_policy.always_allowed_tools.discard("demo")
    ctx = TurnContext(prompt="hi", session_id=current["session_id"], owner_uid="alice")
    inv = ToolInvocation(kind="local", func_name="demo", tool_message_name="demo", args={})

    async def run():
        events = ConfirmationGate(runtime).filter([inv], ctx)
        event, _ = await anext(events)
        with pytest.raises(HTTPException) as exc:
            await confirm_tool_endpoint(
                ToolConfirmationResponse(call_id=event.call_id, decision="allow"), Identity(user_id="bob")
            )
        assert exc.value.status_code == 404
        await confirm_tool_endpoint(
            ToolConfirmationResponse(call_id=event.call_id, decision="always_allow"), Identity(user_id="alice")
        )
        assert [x async for x in events] == [(None, inv)]

    asyncio.run(run())
    assert store.get("tools")["demo"]["require_confirmation"] is False
    assert "demo" not in runtime.tool_policy.always_allowed_tools


def test_assistant_http_roundtrip_and_revision_conflict(monkeypatch, store):
    monkeypatch.setattr(assistant, "_store", lambda _: store)
    monkeypatch.setattr(assistant, "_qualify", lambda _: qualify)
    app = FastAPI()
    app.include_router(assistant.router)
    app.dependency_overrides[current_identity_dependency] = lambda: Identity(user_id="alice")
    with TestClient(app) as client:
        state = client.get("/assistant").json()
        assert client.post("/assistant/reset", json={"revision": state["revision"]}).status_code == 200
        assert client.post("/assistant/reset", json={"revision": state["revision"]}).status_code == 409
        assert client.put("/assistant/instructions", json={"content": "Be concise"}).status_code == 200
        assert client.get("/assistant/instructions").json()["content"] == "Be concise"


def test_compaction_rebuilds_summary_without_forgotten_sources(monkeypatch, tmp_path):
    from yumi.core.features.memory import compaction

    memory = Memory(session_id="personal_new", storage_dir=tmp_path)
    source = memory.create_message(
        session_id=memory.session_id, role="user", content="secret preference", timestamp_num=1
    )
    item = memory.create_long_term_memory(
        kind="preference",
        content="secret preference",
        session_id="__stable_user_context__",
        source_message_ids=[source["id"]],
    )
    memory.update_session_summary("secret preference")
    memory.delete_long_term_memory(item["id"])
    for i in range(6):
        memory.create_message(
            session_id=memory.session_id,
            role="user" if i % 2 == 0 else "assistant",
            content=f"new topic {i}",
            timestamp_num=100 + i,
        )
    monkeypatch.setattr(
        compaction,
        "load_model_config",
        lambda: SimpleNamespace(
            memory_compaction_enabled=True,
            memory_transcript_token_budget=8000,
            memory_compaction_keep_tail_messages=2,
            memory_max_recent_messages=4,
        ),
    )

    async def summarize(bot, prompt):
        assert "secret preference" not in prompt
        return "A summary of the new topic"

    monkeypatch.setattr(compaction, "_summarize", summarize)
    assert asyncio.run(
        compaction.compact_session_if_needed(SimpleNamespace(session_memory=lambda _: memory), memory.session_id)
    )
    assert memory.get_session_summary()["summary"] == "A summary of the new topic"


def test_reset_cancels_active_request_and_old_segment_cannot_be_reused(monkeypatch, store):
    from yumi.core.platform.runtime.assistant_context import active_requests

    current = store.current(qualify)
    monkeypatch.setattr(assistant, "_store", lambda _: store)
    monkeypatch.setattr(assistant, "_qualify", lambda _: qualify)

    async def run():
        ready = asyncio.Event()

        async def old_request():
            task = asyncio.current_task()
            active_requests.setdefault(current["session_id"], set()).add(task)
            ready.set()
            try:
                await asyncio.Event().wait()
            finally:
                active_requests[current["session_id"]].discard(task)

        task = asyncio.create_task(old_request())
        await ready.wait()
        new = await assistant.reset(Identity(user_id="alice"), assistant.ResetRequest(revision=1))
        with pytest.raises(asyncio.CancelledError):
            await task
        assert new["session_id"] != current["session_id"]
        active_requests.pop(current["session_id"], None)

    asyncio.run(run())


def test_explicitly_saving_again_restores_preference_without_old_sources(tmp_path):
    memory = Memory(session_id="personal_new", storage_dir=tmp_path)
    old = memory.create_long_term_memory(
        kind="preference", content="Please speak Chinese", session_id="__stable_user_context__"
    )
    memory.delete_long_term_memory(old["id"])
    restored = memory.create_long_term_memory(
        kind="preference", content="Please speak Chinese", session_id="__stable_user_context__"
    )
    assert memory.can_recall(restored)
    assert "Please speak Chinese" in str(memory.get_context())
