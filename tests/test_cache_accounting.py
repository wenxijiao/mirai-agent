"""Account cache boundaries, unknown telemetry and recorded price arithmetic."""

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace as NS

from yumi.core.platform.providers.usage_pricing import price_usage
from yumi.core.platform.runtime.cache_identity import provider_cache_user_id
from yumi.core.platform.runtime.embedding_cache import RequestEmbeddingCache, request_embedding_cache
from yumi.core.platform.runtime.usage_context import usage_owner_id
from yumi.core.platform.storage.assistant_store import AssistantStore
from yumi.core.platform.storage.sqlite_store import SQLiteStore
from yumi.core.platform.storage.usage_details import present_usage, summarize_usage


def priced(*, hour=2, day=8, cached=800, provider="deepseek", base_url="https://api.deepseek.com"):
    payload = {"prompt_tokens": 1000, "completion_tokens": 100, "model": "deepseek-v4-pro"}
    if cached is not None:
        payload["cached_prompt_tokens"] = cached
    return price_usage(
        payload,
        provider=provider,
        base_url=base_url,
        started_at=datetime(2026, 9, day, hour, tzinfo=timezone.utc).timestamp(),
    )


def test_pricing_peak_boundaries_snapshot_unknown_and_proxy():
    peak = priced()["pricing"]
    assert peak["cost_nano_usd"] == 695200
    assert peak["cache_savings_nano_usd"] == 1020800
    assert peak["covered_tokens"] == 1100
    for hour in (0, 4, 5, 10, 23):
        assert priced(hour=hour)["pricing"]["cost_nano_usd"] == 347600
    for hour in (1, 3, 6, 9):
        assert priced(hour=hour)["pricing"]["cost_nano_usd"] == 695200
    assert priced(day=12)["pricing"]["cost_nano_usd"] == 347600  # Saturday
    assert priced(cached=None)["pricing"]["covered_tokens"] == 100
    assert priced(cached=None)["pricing"]["cost_nano_usd"] == 396000
    assert priced(cached=None)["pricing"]["cache_savings_nano_usd"] is None
    for cached, expected_savings in ((None, None), (0, 0.0)):
        summary = summarize_usage(
            [
                {
                    "prompt_tokens": 1000,
                    "completion_tokens": 100,
                    "usage_details_json": json.dumps([priced(cached=cached)]),
                }
            ]
        )
        assert summary["cache_savings_usd"] == expected_savings
    assert "pricing" not in priced(base_url="https://compatible.example/v1")
    assert "pricing" not in priced(provider="openai")


def test_ledger_month_day_and_pages_share_cache_totals_and_preserve_unknown(tmp_path):
    db = SQLiteStore(tmp_path / "ledger.db")
    first = db.record_token_usage(
        session_id="personal-test",
        owner_user_id="alice",
        model="deepseek-v4-pro",
        prompt_tokens=1000,
        completion_tokens=100,
        usage_parts=[priced()],
    )
    second = db.record_token_usage(
        session_id="personal-test", owner_user_id="alice", prompt_tokens=200, completion_tokens=10
    )
    db.record_token_usage(
        session_id="personal-test",
        owner_user_id="bob",
        prompt_tokens=5000,
        completion_tokens=2,
        usage_parts=[{"prompt_tokens": 5000, "completion_tokens": 2, "cached_prompt_tokens": 5000}],
    )
    stamp = int(datetime(2026, 9, 8, 2, tzinfo=timezone.utc).timestamp() * 1000)
    with db.connect() as conn:
        conn.execute("UPDATE token_usage SET created_at_num=?", (stamp,))
    store = AssistantStore(db, "alice")
    month = store.monthly_usage("2026-09", "Pacific/Auckland")
    day = month["by_day"]["2026-09-08"]
    pages = store.usage_requests("2026-09-08", "Pacific/Auckland", limit=1, snapshot=month["snapshot_seq"])
    remaining = store.usage_requests(
        "2026-09-08", "Pacific/Auckland", before=pages["next_cursor"], limit=1, snapshot=month["snapshot_seq"]
    )
    assert {r["id"] for r in pages["entries"] + remaining["entries"]} == {first["id"], second["id"]}
    data = month["cache"]
    assert data == day["cache"]
    assert month["total_tokens"] == 1310
    assert data["cached_input_tokens"] == 800 and data["uncached_input_tokens"] == 200
    assert data["unknown_input_tokens"] == 200 and data["cache_hit_percent"] == 80
    assert data["cache_coverage_percent"] == 83.3
    assert data["priced_tokens"] == 1100 and data["unpriced_tokens"] == 210
    assert data["estimated_cost_usd"] == 0.0006952 and data["cache_savings_usd"] == 0.0010208
    assert all("usage_details_json" not in r for r in month["recent"])
    assert present_usage(second)["cache"]["cache_hit_percent"] is None


def test_real_zero_unknown_invalid_and_anthropic_writes_are_distinct():
    parts = [
        {"prompt_tokens": 100, "completion_tokens": 1, "cached_prompt_tokens": 0},
        {"prompt_tokens": 50, "completion_tokens": 0},
        {"prompt_tokens": 100, "completion_tokens": 1, "cached_prompt_tokens": 40, "cache_write_prompt_tokens": 20},
    ]
    row = {"prompt_tokens": 250, "completion_tokens": 2, "usage_details_json": json.dumps(parts)}
    cache = summarize_usage([row])
    assert cache["cached_input_tokens"] == 40 and cache["uncached_input_tokens"] == 140
    assert cache["cache_write_input_tokens"] == 20 and cache["unknown_input_tokens"] == 50
    assert cache["cache_hit_percent"] == 20
    assert cache["estimated_cost_usd"] is None
    parts[0]["cached_prompt_tokens"] = 101
    row["usage_details_json"] = json.dumps(parts)
    assert summarize_usage([row])["unknown_input_tokens"] == 150
    row["usage_details_json"] = "invalid"
    assert summarize_usage([row])["unknown_input_tokens"] == 250


def test_schema_upgrade_does_not_invent_old_cache_or_prices(tmp_path):
    db = SQLiteStore(tmp_path / "old.db")
    row = db.record_token_usage(session_id="personal-test", prompt_tokens=20, completion_tokens=2)
    with db.connect() as conn:
        conn.execute("ALTER TABLE token_usage DROP COLUMN usage_details_json")
    SQLiteStore._initialized.discard(db.db_path)
    upgraded = SQLiteStore(db.db_path)
    with upgraded.connect() as conn:
        saved = dict(conn.execute("SELECT * FROM token_usage WHERE id=?", (row["id"],)).fetchone())
    assert present_usage(saved)["cache"]["unknown_input_tokens"] == 20
    assert present_usage(saved)["cache"]["estimated_cost_usd"] is None


def test_tool_query_reuses_memory_vector_only_in_same_account_request(monkeypatch, tmp_path):
    from yumi.core.features.config import paths
    from yumi.core.features.memory.embedding_runner import EmbeddingProcessor
    from yumi.core.platform.tools import routing

    calls = []
    provider = NS(embed=lambda model, text: calls.append(text) or [1.0, 2.0])
    processor = EmbeddingProcessor.__new__(EmbeddingProcessor)
    processor.embed_provider, processor.embed_model, processor.embedding_available = provider, "test", True
    monkeypatch.setattr(routing, "get_embed_provider", lambda: provider)
    monkeypatch.setattr(routing, "_EMBED_CACHE", {})
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path)
    cache = RequestEmbeddingCache()
    token = request_embedding_cache.set(cache)
    owner = usage_owner_id.set("alice")
    try:
        assert processor.get_vector("private query") == routing._cached_embedding("test", "private query")
        assert len(calls) == 1 and not routing._EMBED_CACHE
        other = usage_owner_id.set("bob")
        try:
            routing._cached_embedding("test", "private query")
            assert len(calls) == 2
        finally:
            usage_owner_id.reset(other)
        routing._cached_embedding("test", "static tool", persistent=True)
        routing._cached_embedding("test", "static tool", persistent=True)
        assert len(calls) == 3 and len(routing._EMBED_CACHE) == 1
    finally:
        cache.close()
        request_embedding_cache.reset(token)
        usage_owner_id.reset(owner)


def test_deepseek_account_key_and_reported_zero_reach_wire():
    from yumi.core.platform.providers.openai_provider import OpenAIProvider
    from yumi.core.platform.runtime.assistant_context import conversation_session

    sent = []

    async def create(**kwargs):
        sent.append(kwargs)

        async def stream():
            yield NS(
                usage=NS(prompt_tokens=100, completion_tokens=2, prompt_cache_hit_tokens=0),
                choices=[NS(finish_reason="stop", delta=NS(content="OK", tool_calls=None))],
            )

        return stream()

    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider.api_family = "deepseek"
    provider._async_client = NS(base_url="https://api.deepseek.com", chat=NS(completions=NS(create=create)))

    async def run():
        return [part async for part in provider.chat_stream(model="deepseek-v4-pro", messages=[], think=True)]

    owner = usage_owner_id.set("alice@example.com")
    try:
        first = provider_cache_user_id()
        sid = conversation_session.set("telegram:alice")
        try:
            assert provider_cache_user_id() == first
            chunks = asyncio.run(run())
        finally:
            conversation_session.reset(sid)
        assert "alice" not in first and "@" not in first
        assert sent[0]["extra_body"] == {"thinking": {"type": "enabled"}, "user_id": first}
        usage = next(c for c in chunks if c["type"] == "usage")
        assert usage["cached_prompt_tokens"] == 0 and usage["pricing"]["covered_tokens"] == 102
        second = usage_owner_id.set("bob")
        try:
            assert provider_cache_user_id() != first
        finally:
            usage_owner_id.reset(second)
    finally:
        usage_owner_id.reset(owner)
