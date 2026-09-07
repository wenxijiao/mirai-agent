from datetime import datetime, timezone

import pytest
from yumi.core.features.assistant.personalization import explicit_language, preferences, save_preferences
from yumi.core.features.chat.language import build_turn_language_note
from yumi.core.platform.observability import turn_inspector
from yumi.core.platform.runtime.tool_catalog import model_visible_tool_schema
from yumi.core.platform.storage.assistant_store import AssistantStore
from yumi.core.platform.storage.sqlite_store import SQLiteStore
from yumi.core.platform.tools.presentation import render_action_summary


@pytest.fixture
def store(tmp_path):
    return AssistantStore(SQLiteStore(tmp_path / "assistant.db"), "alice")


def test_language_preference_is_canonical_and_overridable_for_current_task(store):
    store.put("instructions", "以后用中文回答我")
    assert preferences(store) == {"response_language": "zh", "instructions": ""}
    save_preferences(store, response_language="en", instructions="Be concise")
    assert preferences(store) == {"response_language": "en", "instructions": "Be concise"}
    assert AssistantStore(store.sqlite, "bob").get("response_language") is None
    note = build_turn_language_note("你好，帮我写封信", "en")
    assert "English" in note and "takes priority" in note
    assert "MUST be in Chinese" not in note
    assert explicit_language("不要以后用中文回答我") is None
    assert explicit_language("翻译“以后用中文回答我”") is None
    assert explicit_language("以后用中文回答我，同时保持简洁") is None
    assert explicit_language("Always reply in English") == "en"


def test_month_buckets_use_timezone_and_dst_and_do_not_count_next_month(store):
    def insert(identity, millis, tokens):
        stamp = datetime.fromisoformat(millis).replace(tzinfo=timezone.utc)
        with store.sqlite.connect() as conn:
            conn.execute(
                "INSERT INTO token_usage(id,owner_user_id,model,prompt_tokens,completion_tokens,total_tokens,created_at,created_at_num) VALUES(?,?,?,?,?,?,?,?)",
                (
                    identity,
                    "bob" if identity == "other-owner" else "alice",
                    "model",
                    tokens - 1,
                    1,
                    tokens,
                    stamp.isoformat(),
                    int(stamp.timestamp() * 1000),
                ),
            )

    insert("start", "2026-08-31T12:00:00", 10)  # Sep 1 in Auckland
    insert("before-start", "2026-08-31T11:59:59", 99)
    insert("dst", "2026-09-27T11:00:00", 20)  # Sep 28 after DST
    insert("next-month", "2026-09-30T11:00:00", 99)
    insert("other-owner", "2026-09-10T00:00:00", 999)
    result = store.monthly_usage("2026-09", "Pacific/Auckland")
    assert result["total_tokens"] == 30 and result["requests"] == 2
    assert len(result["daily"]) == 30
    assert result["daily"]["2026-09-01"] == 10
    assert result["daily"]["2026-09-28"] == 20
    assert result["daily"]["2026-09-02"] == 0
    assert result["by_day"]["2026-09-28"]["models"] == {"model": 20}
    assert len(store.monthly_usage("2024-02", "UTC")["daily"]) == 29
    with pytest.raises(ValueError):
        store.monthly_usage("2026-13", "UTC")
    with pytest.raises(ValueError):
        store.monthly_usage("2026-09", "not/a/timezone")


def test_action_summary_uses_actual_args_defaults_and_redacts_secrets():
    schema = {"properties": {"date": {"default": "后天"}}}
    template = {"zh": "查询「{city}」「{date}」的天气", "en": "Weather in {city} for {date}"}
    assert render_action_summary(template, {"city": "奥克兰"}, schema, locale="zh") == "查询「奥克兰」「后天」的天气"
    assert render_action_summary("Send {secret}", {"secret": "never show me"}) == "Send [redacted]"
    assert render_action_summary("{missing}", {}) is None
    assert render_action_summary("{city.__class__}", {"city": "Auckland"}) is None
    assert render_action_summary("{city:>10000000}", {"city": "Auckland"}) is None
    assert render_action_summary("{city!r}", {"city": "Auckland"}) is None
    assert render_action_summary("{body}", {"body": "x" * 241}) is None
    assert "confirmation_template" not in model_visible_tool_schema(
        {"type": "function", "function": {}, "confirmation_template": template}
    )


def test_turn_timing_survives_message_detail_and_does_not_cross_sessions(store):
    import time

    sid = "personal_test"
    turn_inspector.begin_turn(
        started_monotonic=time.perf_counter() - 2,  # Includes time spent waiting for another channel.
        turn_id="test-timing",
        session_id=sid,
        prompt="hello",
        think=False,
        timer_callback=False,
        owner_user_id="alice",
    )
    turn_inspector.record_confirmation_wait(sid, 24)
    turn_inspector.record_confirmation_wait(sid, 10)
    detail = turn_inspector.end_turn(sid, total_prompt_tokens=5, total_completion_tokens=3, usage_model="test")
    assert detail["duration_ms"] >= 2000 and detail["confirmation_wait_ms"] == 34
    store.sqlite.upsert_turn_trace(detail, owner_user_id="alice")
    row = {"id": "reply", "role": "assistant", "content": "hello", "turn_id": "test-timing", "session_id": sid}
    public = store.message_detail(row)
    assert public["confirmation_wait_ms"] == 34
    assert "model_input" not in public
    assert store.message_detail({**row, "session_id": "personal_other"})["activity_available"] is False


def test_related_personal_facts_use_canonical_rows_and_skip_old_rules(tmp_path):
    from yumi.core.features.memory.context import ContextBuilder
    from yumi.core.features.memory.memory import Memory

    memory = Memory(session_id="personal_test", storage_dir=str(tmp_path / "memory"))
    for content, kind in [
        ("Auckland trip is in October", "fact"),
        ("Auckland replies must be in French", "preference"),
        ("Auckland address was deleted", "fact"),
        ("Favorite food is sushi", "fact"),
    ]:
        row = memory.create_long_term_memory(kind=kind, content=content, session_id="__stable_user_context__")
        if "deleted" in content:
            memory.delete_long_term_memory(row["id"])
    builder = ContextBuilder(memory)
    result = builder._personal_facts_message("Auckland", limit=8)
    assert "October" in result["content"]
    assert "French" not in result["content"] and "deleted" not in result["content"] and "sushi" not in result["content"]
    assert builder._personal_facts_message("continue", limit=8) is None


def test_public_trace_redacts_action_summary():
    from yumi.core.platform.tools.trace import redact_trace_content

    result = redact_trace_content({"action_summary": "Read private.txt", "arguments": {}, "status": "success"})
    assert "action_summary" not in result


def test_concurrent_partial_preference_updates_do_not_erase_each_other(store, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from yumi.core.features.assistant import personalization

    preferences(store)
    original = personalization.preferences
    barrier = Barrier(2)

    def synchronize_reads(store):
        result = original(store)
        barrier.wait(timeout=3)
        return result

    monkeypatch.setattr(personalization, "preferences", synchronize_reads)
    with ThreadPoolExecutor(max_workers=2) as executor:
        lang = executor.submit(save_preferences, store, response_language="zh")
        rules = executor.submit(save_preferences, store, instructions="Keep it concise")
        lang.result(timeout=5)
        rules.result(timeout=5)
    assert original(store) == {"response_language": "zh", "instructions": "Keep it concise"}
