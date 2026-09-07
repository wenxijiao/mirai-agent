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


def test_category_change_preserves_id_sources_and_recall(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from yumi.core.features.assistant import router
    from yumi.core.platform.http.dependencies import current_identity_dependency
    from yumi.core.platform.plugins import Identity

    memory = Memory(session_id="personal_food", storage_dir=str(tmp_path / "memory"))
    store = AssistantStore(memory.sqlite, "alice")
    memory.sqlite.upsert_event_from_message(
        {
            "id": "food-source",
            "role": "user",
            "session_id": "personal_food",
            "content": "Remember my food dislikes: AVOIDS_SHALLOTS.",
        }
    )
    row = save_rule(store, "AVOIDS_SHALLOTS", source_ids=["food-source"])["memory"]
    monkeypatch.setattr(router, "_store", lambda _: store)
    monkeypatch.setattr(router, "get_memory_factory", lambda: SimpleNamespace(get_for_identity=lambda _: memory))
    app = FastAPI()
    app.include_router(router.router)
    app.dependency_overrides[current_identity_dependency] = lambda: Identity(user_id="alice")
    with TestClient(app) as client:
        result = client.put(f"/assistant/memories/{row['id']}", json={"kind": "profile", "content": row["content"]})
        assert result.status_code == 200
        saved = result.json()["memory"]
        assert saved["id"] == row["id"]
        assert saved["source_message_ids"] == ["food-source"]
        assert saved["kind"] == "profile"
        assert saved["created_at"] == row["created_at"]
        assert memory.can_recall(saved)
        assert len(store.memories(include_deleted=True)) == 1
        assert "AVOIDS_SHALLOTS" not in prompt_preferences(store)
        assert "AVOIDS_SHALLOTS" in str(memory.get_context(query="Suggest dinner"))
        # Returning it to behavior changes which prompt section contains it, without tombstones.
        returned = client.put(
            f"/assistant/memories/{row['id']}", json={"kind": "preference", "content": row["content"]}
        )
        assert returned.json()["memory"]["id"] == row["id"]
        assert "AVOIDS_SHALLOTS" in prompt_preferences(store)
        assert client.put("/assistant/memories/missing", json={"kind": "profile", "content": "x"}).status_code == 404


def test_personal_taste_and_behavior_tools_land_in_separate_prompt_sections(tmp_path, monkeypatch):
    memory = Memory(session_id="personal_test", storage_dir=str(tmp_path / "memory"))
    monkeypatch.setattr(user_context_tools, "_memory_store", lambda: memory)
    monkeypatch.setattr(user_context_tools, "get_chat_owner_user_id", lambda: "alice")
    user_context_tools.remember_user_context("AVOIDS_SHALLOTS", kind="profile")
    user_context_tools.remember_user_context("Use exactly three bullet points.", kind="communication_style")
    store = AssistantStore(memory.sqlite, "alice")
    assert {r["kind"] for r in store.memories()} == {"profile", "communication_style"}
    rules = prompt_preferences(store)
    assert "AVOIDS_SHALLOTS" not in rules
    assert "Use exactly three bullet points." in rules
    context = str(memory.get_context(query="Help choose dinner"))
    assert "AVOIDS_SHALLOTS" in context
