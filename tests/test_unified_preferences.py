from concurrent.futures import ThreadPoolExecutor

import pytest
from yumi.core.features.assistant.personalization import preferences, prompt_preferences, save_preferences, save_rule
from yumi.core.features.memory.memory import Memory
from yumi.core.platform.storage.assistant_store import AssistantStore
from yumi.core.platform.storage.sqlite_store import SQLiteStore
from yumi.tools import user_context_tools


@pytest.fixture
def store(tmp_path):
    return AssistantStore(SQLiteStore(tmp_path / "rules.db"), "alice")


def test_legacy_block_migrates_without_loss_and_edits_share_one_entry(store):
    text = "Keep replies concise.\n\nWhen making plans, allow time for rest."
    store.put("instructions", text)
    assert preferences(store)["instructions"] == text
    row = store.memories()[0]
    assert row["content"] == text
    assert store.get("instructions") == ""
    preferences(store)
    assert len(store.memories()) == 1
    save_rule(store, "Use detailed explanations.", memory_id=row["id"])
    assert preferences(store)["instructions"] == "Use detailed explanations."
    assert "Keep replies concise" not in prompt_preferences(store)
    assert prompt_preferences(store).count("Use detailed explanations.") == 1
    # An older client also edits the same canonical item.
    save_preferences(store, instructions="Use short paragraphs.")
    assert store.memories()[0]["id"] == row["id"]
    assert len(store.memories()) == 1
    store.sqlite.delete_memory(row["id"])
    assert preferences(store)["instructions"] == ""
    assert store.memories() == []


def test_migration_deduplicates_existing_rule_and_keeps_long_content(store):
    row = save_rule(store, "Keep replies concise.")["memory"]
    store.put("instructions", "  Keep replies concise.  ")
    preferences(store)
    assert [r["id"] for r in store.memories()] == [row["id"]]
    long_text = "A detailed rule.\n" * 900
    save_preferences(store, instructions=long_text)
    assert store.memories()[0]["content"] == long_text.strip()


def test_duplicate_saves_are_atomic_and_edits_can_merge(store):
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: save_rule(store, "Use short paragraphs."), range(2)))
    assert rows[0]["memory"]["id"] == rows[1]["memory"]["id"]
    other = save_rule(store, "Use bullet lists.")["memory"]
    merged = save_rule(store, "Use short paragraphs.", memory_id=other["id"])
    assert len(store.memories()) == 1
    assert merged["memory"]["id"] == rows[0]["memory"]["id"]


def test_fresh_reply_default_is_auto_and_existing_choice_is_preserved(store):
    assert preferences(store)["response_language"] == "auto"
    save_preferences(store, response_language="ja")
    save_rule(store, "Be concise.")
    assert preferences(store)["response_language"] == "ja"
    assert "most natural language or combination" in prompt_preferences(store)


def test_chat_updates_the_same_preference_as_the_app(tmp_path, monkeypatch):
    memory = Memory(session_id="personal_test", storage_dir=str(tmp_path / "memory"))
    monkeypatch.setattr(user_context_tools, "_memory_store", lambda: memory)
    monkeypatch.setattr(user_context_tools, "get_chat_owner_user_id", lambda: "alice")
    store = AssistantStore(memory.sqlite, "alice")
    store.put("instructions", "Use concise replies.")
    listed = user_context_tools.list_user_context()
    row = store.memories()[0]
    assert row["id"] in listed
    user_context_tools.update_user_context(row["id"], "Use detailed explanations.")
    assert preferences(store)["instructions"] == "Use detailed explanations."
    assert len(store.memories()) == 1
    user_context_tools.remember_user_context("Use detailed explanations.", kind="preference")
    assert len(store.memories()) == 1
    save_rule(store, "Prefer examples.", memory_id=row["id"])
    assert "Prefer examples." in user_context_tools.list_user_context()
    user_context_tools.update_user_context(row["id"], "Always reply in English")
    assert preferences(store)["response_language"] == "en"
    assert store.memories() == []
    with pytest.raises(ValueError, match="not found"):
        user_context_tools.update_user_context(row["id"], "A new rule")


def test_legacy_vector_rows_do_not_overwrite_canonical_edits(tmp_path):
    memory = Memory(session_id="personal_test", storage_dir=str(tmp_path / "memory"))
    row = memory.create_long_term_memory(
        kind="preference", content="Use terse replies.", session_id="__stable_user_context__"
    )
    store = AssistantStore(memory.sqlite, "alice")
    save_rule(store, "Use detailed replies.", memory_id=row["id"])
    assert memory.list_long_term_memories()[0]["content"] == "Use detailed replies."
    memory.sqlite.delete_memory(row["id"])
    assert memory.list_long_term_memories() == []
    assert "Use detailed replies." not in prompt_preferences(store)


def test_rule_api_edits_preserve_id_and_reject_blank_or_missing_sources(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from yumi.core.features.assistant import router
    from yumi.core.platform.http.dependencies import current_identity_dependency
    from yumi.core.platform.plugins import Identity

    memory = Memory(session_id="personal_test", storage_dir=str(tmp_path / "memory"))
    store = AssistantStore(memory.sqlite, "alice")
    monkeypatch.setattr(router, "_store", lambda _: store)
    monkeypatch.setattr(router, "get_memory_factory", lambda: SimpleNamespace(get_for_identity=lambda _: memory))
    app = FastAPI()
    app.include_router(router.router)
    app.dependency_overrides[current_identity_dependency] = lambda: Identity(user_id="alice")
    with TestClient(app) as client:
        row = client.post("/assistant/memories", json={"kind": "preference", "content": "Be concise."}).json()["memory"]
        path = f"/assistant/memories/{row['id']}"
        updated = client.put(path, json={"kind": "preference", "content": "Use detailed replies."})
        assert updated.status_code == 200
        assert updated.json()["memory"]["id"] == row["id"]
        assert client.put(path, json={"kind": "preference", "content": "  "}).status_code == 422
        assert (
            client.put(
                path, json={"kind": "preference", "content": "Another rule.", "source_message_ids": ["not-found"]}
            ).status_code
            == 404
        )
        assert len(client.get("/assistant/memories").json()["memories"]) == 1
        assert client.delete(path).status_code == 200
        assert client.get("/assistant/memories").json()["memories"] == []
