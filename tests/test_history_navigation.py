from datetime import datetime, timezone

import pytest
from yumi.core.platform.storage.assistant_store import AssistantStore
from yumi.core.platform.storage.sqlite_store import SQLiteStore


def test_calendar_anchor_pages_both_ways_and_keeps_scope_and_filters(tmp_path):
    store = AssistantStore(SQLiteStore(tmp_path / "history.db"), "alice")
    for i in range(1, 8):
        store.sqlite.upsert_event_from_message(
            {
                "id": f"a{i}",
                "role": "user",
                "content": f"photo {i}",
                "session_id": "alice_personal",
                "timestamp_num": i * 1000,
            }
        )
    store.sqlite.upsert_event_from_message(
        {"id": "private", "role": "user", "content": "private", "session_id": "bob_personal", "timestamp_num": 4000}
    )
    args = {"prefix": "alice_", "query": "photo", "limit": 2}
    page = store.history(anchor=5000, **args)
    assert [r["id"] for r in page["messages"]] == ["a4", "a3"]
    older = store.history(before=page["next_before"], **args)
    newer = store.history(after=page["next_after"], **args)
    assert [r["id"] for r in older["messages"]] == ["a2", "a1"]
    assert older["next_before"] is None
    assert [r["id"] for r in newer["messages"]] == ["a6", "a5"]
    last = store.history(after=newer["next_after"], **args)
    assert [r["id"] for r in last["messages"]] == ["a7"]
    assert last["next_after"] is None
    assert [r["id"] for r in store.history(anchor=1, **args)["messages"]] == ["a2", "a1"]
    assert store.history(query="missing", prefix="alice_", anchor=5000)["messages"] == []
    with pytest.raises(ValueError):
        store.history(before=1, after=2)


def test_usage_pagination_ties_timezone_and_total_reconciliation(tmp_path):
    store = AssistantStore(SQLiteStore(tmp_path / "usage.db"), "alice")
    # Auckland DST makes this date 23 hours long. Equal timestamps must not skip rows.
    stamps = ["2026-09-26T12:00:00+00:00"] * 12 + ["2026-09-27T10:59:59+00:00"]
    for i, stamp in enumerate(stamps + ["2026-09-27T11:00:00+00:00"]):
        row = store.sqlite.record_token_usage(
            session_id="s",
            owner_user_id="alice",
            model="test",
            prompt_tokens=i + 1,
            completion_tokens=2,
            usage_kind="chat" if i == 0 else "embedding",
        )
        with store.sqlite.connect() as conn:
            conn.execute(
                "UPDATE token_usage SET created_at_num=? WHERE id=?",
                (int(datetime.fromisoformat(stamp).timestamp() * 1000), row["id"]),
            )
    foreign = store.sqlite.record_token_usage(session_id="s", owner_user_id="bob", prompt_tokens=9999)
    with store.sqlite.connect() as conn:
        conn.execute(
            "UPDATE token_usage SET created_at_num=? WHERE id=?",
            (int(datetime(2026, 9, 27, tzinfo=timezone.utc).timestamp() * 1000), foreign["id"]),
        )
    entries = []
    cursor = ""
    while True:
        page = store.usage_requests("2026-09-27", "Pacific/Auckland", before=cursor, limit=3)
        entries.extend(page["entries"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    day = store.monthly_usage("2026-09", "Pacific/Auckland")["by_day"]["2026-09-27"]
    assert len(entries) == len({r["id"] for r in entries}) == day["entry_count"] == 13
    assert sum(r["total_tokens"] for r in entries) == day["total_tokens"] == sum(day["models"].values())
    assert len(day["recent"]) == 10
    assert day["requests"] == 1
    for invalid in ("bad", "123", "x:y"):
        with pytest.raises(ValueError):
            store.usage_requests("2026-09-27", "Pacific/Auckland", before=invalid)


def test_usage_snapshot_excludes_new_work_while_browsing(tmp_path):
    store = AssistantStore(SQLiteStore(tmp_path / "snapshot.db"), "alice")
    first = store.sqlite.record_token_usage(session_id="s", owner_user_id="alice", prompt_tokens=10)
    stamp = datetime.fromtimestamp(first["created_at_num"] / 1000, timezone.utc)
    month, day = stamp.strftime("%Y-%m"), stamp.strftime("%Y-%m-%d")
    snapshot = store.monthly_usage(month, "UTC")
    store.sqlite.record_token_usage(session_id="s", owner_user_id="alice", prompt_tokens=20)
    page = store.usage_requests(day, "UTC", snapshot=snapshot["snapshot_seq"])
    assert [row["id"] for row in page["entries"]] == [first["id"]]
    assert sum(row["total_tokens"] for row in page["entries"]) == snapshot["total_tokens"]
