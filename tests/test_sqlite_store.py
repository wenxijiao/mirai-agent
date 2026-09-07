import json
import sqlite3

import pytest
from yumi.core.features.config.store import load_saved_model_config, save_model_config
from yumi.core.features.memory.memory import Memory
from yumi.core.features.proactive.state import ProactiveStateStore
from yumi.core.features.proactive.timer_tools import SchedulerService
from yumi.core.features.uploads import service as upload_service
from yumi.core.platform.storage.sqlite_store import SQLiteStore, db_path_for_config_path


def test_sqlite_schema_creates_canonical_tables(tmp_path):
    db_path = tmp_path / "yumi.db"
    SQLiteStore(db_path)

    with sqlite3.connect(db_path) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    assert {
        "db_meta",
        "settings",
        "secrets",
        "model_profiles",
        "prompts",
        "tool_policies",
        "sessions",
        "events",
        "turn_traces",
        "memories",
        "session_summaries",
        "files",
        "schedules",
        "audit_log",
    }.issubset(names)


def test_config_json_migrates_to_sqlite_and_save_keeps_legacy_mirror(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"chat_model": "old", "openai_api_key": "sk-old"}), encoding="utf-8")
    monkeypatch.setattr("yumi.core.features.config.store.CONFIG_PATH", config_path)

    cfg = load_saved_model_config()
    assert cfg.chat_model == "old"
    assert cfg.openai_api_key == "sk-old"

    cfg.chat_model = "new"
    save_model_config(cfg)

    assert load_saved_model_config().chat_model == "new"
    assert json.loads(config_path.read_text(encoding="utf-8"))["chat_model"] == "new"

    store = SQLiteStore(db_path_for_config_path(config_path))
    data = store.load_model_config_dict()
    assert data["chat_model"] == "new"
    assert data["openai_api_key"] == "sk-old"


def test_memory_writes_sqlite_events(tmp_path):
    m = Memory(session_id="s", storage_dir=tmp_path, max_recent=50)
    user_id = m.add_message("user", "hello", turn_id="turn-1")
    m.persist_openai_messages(
        [
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "demo", "arguments": {}}}]},
            {"role": "tool", "name": "demo", "content": "done"},
        ]
    )

    rows = m.list_messages(session_id="s", limit=10)
    assert rows[0]["id"] == user_id
    assert rows[0]["turn_id"] == "turn-1"
    assert [row["role"] for row in rows] == ["user", "assistant", "tool"]

    ctx = m.get_context(query=None)
    assert any(item.get("role") == "assistant" and item.get("tool_calls") for item in ctx)
    assert any(item.get("role") == "tool" and item.get("name") == "demo" for item in ctx)

    with sqlite3.connect(tmp_path / "yumi.db") as conn:
        event_types = [row[0] for row in conn.execute("SELECT event_type FROM events ORDER BY seq")]

    assert event_types == ["user_message", "assistant_tool_calls", "tool_result"]


def test_turn_trace_round_trips_complete_json(tmp_path):
    store = SQLiteStore(tmp_path / "yumi.db")
    trace = {
        "id": "turn-1",
        "session_id": "s",
        "owner_user_id": "_local",
        "status": "complete",
        "started_at": "2026-08-02T01:02:03+00:00",
        "ended_at": "2026-08-02T01:02:04+00:00",
        "rounds": [{"messages": [{"role": "system", "content": "full prompt"}], "tools": []}],
        "summary": {
            "id": "turn-1",
            "session_id": "s",
            "status": "complete",
            "started_at": "2026-08-02T01:02:03+00:00",
            "provider": "openai",
            "model": "gpt-test",
        },
    }

    store.upsert_turn_trace(trace, owner_user_id="_local")

    assert store.get_turn_trace("turn-1") == trace
    assert store.list_turn_traces(session_id="s", owner_user_id="_local")[0]["id"] == "turn-1"


def test_legacy_import_keeps_existing_events_and_deletion_tombstones(tmp_path):
    store = SQLiteStore(tmp_path / "yumi.db")
    original = {"id": "answer", "session_id": "s", "role": "assistant", "content": "Edited reply", "turn_id": "turn-1"}
    store.upsert_event_from_message(original)
    store.upsert_event_from_message({**original, "id": "deleted"})
    store.delete_message("deleted")
    before = store.get_message("answer")
    store.upsert_session({"session_id": "s", "title": "Edited title", "status": "deleted", "is_pinned": True})

    store.upsert_session({"session_id": "s", "title": "Stale title", "status": "active"}, overwrite=False)
    store.import_messages(
        [{**original, "id": mid, "turn_id": "", "content": "Stale index"} for mid in ("answer", "deleted", "legacy")]
    )

    assert store.get_message("answer") == before
    assert store.get_message("deleted") is None
    assert store.get_message("legacy")["content"] == "Stale index"
    session = store.get_session("s")
    assert session["title"] == "Edited title"
    assert session["status"] == "deleted"
    assert session["is_pinned"] is True


def test_first_legacy_import_preserves_session_metadata(tmp_path):
    memory = Memory(session_id="legacy", storage_dir=tmp_path)
    # Populate only the old index, as on a pre-SQLite installation.
    row = memory.messages.create(session_id="legacy", role="user", content="Old message")
    memory.sessions_repo.update("legacy", title="Saved title", is_pinned=True, status="deleted")
    assert memory.sqlite.event_count() == 0

    migrated = Memory(session_id="default", storage_dir=tmp_path)
    assert migrated.sqlite.get_message(row["id"])["content"] == "Old message"
    session = migrated.sqlite.get_session("legacy")
    assert session["title"] == "Saved title"
    assert session["status"] == "deleted"
    assert session["is_pinned"] is True


def test_interrupted_legacy_import_does_not_leave_a_partial_canonical_store(tmp_path):
    store = SQLiteStore(tmp_path / "yumi.db")
    row = {"id": "first", "session_id": "s", "role": "user", "content": "Legacy message", "timestamp_num": 1}
    malformed = {**row, "id": "second", "timestamp_num": 2, "metadata": {"invalid": object()}}
    with pytest.raises(TypeError):
        store.import_messages([row, malformed])
    assert store.event_count() == 0
    store.import_messages([row, {**malformed, "metadata": {}}])
    assert store.event_count() == 2


def test_lancedb_chat_history_can_rebuild_from_sqlite_events(tmp_path):
    m = Memory(session_id="s", storage_dir=tmp_path, max_recent=50)
    m.add_message("user", "canonical")
    m.db.drop_table("chat_history", ignore_missing=True)

    rebuilt = Memory(session_id="s", storage_dir=tmp_path, max_recent=50)

    rows = rebuilt.messages.list(session_id="s", limit=10)
    assert [row["content"] for row in rows] == ["canonical"]


def test_rebuild_index_from_sqlite_realigns_lancedb(tmp_path):
    m = Memory(session_id="s", storage_dir=tmp_path, max_recent=50)
    m.add_message("user", "first")
    m.add_message("assistant", "second")

    # Simulate LanceDB index drift/loss while SQLite (the source of truth) is intact.
    m.db.drop_table("chat_history", ignore_missing=True)

    count = m.rebuild_index_from_sqlite()

    assert count == 2
    rebuilt = m.messages.list(session_id="s", limit=10)
    assert [r["content"] for r in rebuilt] == ["first", "second"]


def test_verify_index_detects_and_repairs_drift(tmp_path):
    m = Memory(session_id="s", storage_dir=tmp_path, max_recent=50)
    m.add_message("user", "a")
    m.add_message("assistant", "b")
    assert m.verify_index()["ok"] is True

    # Simulate index drift/loss while SQLite (the source of truth) is intact.
    m.db.drop_table("chat_history", ignore_missing=True)
    status = m.verify_index()
    assert status["ok"] is False
    assert status["sqlite"] == 2

    repaired = m.verify_and_repair_index(background=False)
    assert repaired["repaired"] is True
    assert m.verify_index()["ok"] is True


def test_writes_during_rebuild_go_to_sqlite_and_are_caught_up(tmp_path):
    from yumi.core.features.memory import memory as memmod

    m = Memory(session_id="s", storage_dir=tmp_path, max_recent=50)
    m.add_message("user", "one")

    # Simulate a turn that writes while a rebuild is in progress: SQLite (the
    # source of truth) gets it, but the live LanceDB index write is skipped so it
    # can't duplicate a row the rebuild is also adding.
    memmod._mark_rebuild_active(m.db_dir)
    try:
        m.add_message("user", "two")
        assert m.sqlite.active_event_count() == 2
        assert m.messages.count() == 1  # index write skipped during the rebuild
    finally:
        memmod._clear_rebuild_active(m.db_dir)

    # A real rebuild indexes everything from SQLite, with no duplicates.
    assert m.rebuild_index_from_sqlite() == 2
    assert m.verify_index()["ok"] is True


def test_rebuild_marker_is_scoped_to_storage_dir(tmp_path):
    from yumi.core.features.memory import memory as memmod

    rebuilding = Memory(session_id="s1", storage_dir=tmp_path / "rebuilding", max_recent=50)
    other = Memory(session_id="s2", storage_dir=tmp_path / "other", max_recent=50)

    memmod._mark_rebuild_active(rebuilding.db_dir)
    try:
        other.add_message("user", "still indexed")
        assert other.messages.count() == 1
        assert other.search_messages("still indexed", session_id="s2", limit=5)
    finally:
        memmod._clear_rebuild_active(rebuilding.db_dir)


def test_rebuild_lock_is_scoped_to_storage_dir(tmp_path):
    from yumi.core.features.memory import memory as memmod

    rebuilding = Memory(session_id="s1", storage_dir=tmp_path / "rebuilding-lock", max_recent=50)
    other = Memory(session_id="s2", storage_dir=tmp_path / "other-lock", max_recent=50)
    other.add_message("user", "repair me")
    other.db.drop_table("chat_history", ignore_missing=True)

    lock = memmod._rebuild_lock_for(rebuilding.db_dir)
    assert lock.acquire(blocking=False) is True
    try:
        assert other.rebuild_index_from_sqlite() == 1
    finally:
        lock.release()


def test_upload_metadata_is_recorded_in_sqlite(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    monkeypatch.setattr(upload_service, "uploads_root", lambda: uploads)

    result = upload_service.save_uploaded_file("s", "note.txt", b"hello")

    with sqlite3.connect(tmp_path / "yumi.db") as conn:
        row = conn.execute("SELECT session_id, original_name, path, size_bytes, sha256 FROM files").fetchone()

    assert row[0] == "s"
    assert row[1] == "note.txt"
    assert row[2] == result["path"]
    assert row[3] == 5
    assert len(row[4]) == 64


def test_schedules_are_recorded_in_sqlite(tmp_path):
    schedules_path = tmp_path / "schedules.json"
    scheduler = SchedulerService(schedules_path=schedules_path)
    scheduler.active_timers["abc"] = {
        "id": "abc",
        "type": "scheduled",
        "description": "demo",
        "session_id": "s",
        "next_fire_at": "2030-01-01T00:00:00",
        "created_at": "2029-01-01T00:00:00",
    }

    scheduler._save_schedules()

    with sqlite3.connect(tmp_path / "yumi.db") as conn:
        count = conn.execute("SELECT COUNT(*) FROM schedules WHERE id='abc'").fetchone()[0]

    restored = SchedulerService(schedules_path=schedules_path)._load_schedules()
    assert count == 1
    assert restored[0]["id"] == "abc"


def test_proactive_state_is_recorded_in_sqlite(tmp_path):
    path = tmp_path / "proactive_state.json"
    store = ProactiveStateStore(path=path)

    store.record_user_message("s")

    with sqlite3.connect(tmp_path / "yumi.db") as conn:
        row = conn.execute("SELECT value_json FROM settings WHERE namespace='proactive_state' AND key='s'").fetchone()

    assert row is not None
    restored = ProactiveStateStore(path=path).get("s")
    assert restored.last_user_message_at is not None
