"""UsageRecorder: token accumulation + on-exit recording hook."""

from __future__ import annotations

import yumi.core.platform.dispatch.usage as usage_mod
from yumi.core.platform.dispatch.context import TurnContext
from yumi.core.platform.dispatch.usage import UsageRecorder


def _ctx() -> TurnContext:
    return TurnContext(prompt="hi", session_id="s1")


def test_add_accumulates_tokens_and_model():
    rec = UsageRecorder(_ctx())
    rec.add({"prompt_tokens": 10, "completion_tokens": 4, "model": "m1"})
    rec.add({"prompt_tokens": 7, "completion_tokens": 2})
    assert rec.total_prompt_tokens == 17
    assert rec.total_completion_tokens == 6
    assert rec.usage_model == "m1"


def test_add_handles_missing_fields():
    rec = UsageRecorder(_ctx())
    rec.add({})
    rec.add({"prompt_tokens": None, "completion_tokens": None})
    assert rec.total_prompt_tokens == 0
    assert rec.total_completion_tokens == 0


def test_exit_calls_record_tool_routing_usage(monkeypatch):
    captured: dict = {}

    def fake_record(*, session_id, prompt_tokens, completion_tokens, model):
        captured["sid"] = session_id
        captured["pt"] = prompt_tokens
        captured["ct"] = completion_tokens
        captured["model"] = model

    monkeypatch.setattr(usage_mod, "record_tool_routing_usage", fake_record)

    rec = UsageRecorder(_ctx())
    rec.add({"prompt_tokens": 3, "completion_tokens": 1, "model": "m2"})
    with rec:
        pass
    assert captured == {"sid": "s1", "pt": 3, "ct": 1, "model": "m2"}


def test_context_manager_swallows_record_failures(monkeypatch):
    def boom(**_):
        raise RuntimeError("downstream broke")

    monkeypatch.setattr(usage_mod, "record_tool_routing_usage", boom)
    rec = UsageRecorder(_ctx())
    with rec:
        pass  # should not raise


def test_account_usage_reads_the_recorder_ledger_without_other_or_unowned_rows(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from yumi.core.features.assistant import router as assistant
    from yumi.core.features.memory import store as memory_store
    from yumi.core.platform.http.dependencies import current_identity_dependency
    from yumi.core.platform.plugins import Identity
    from yumi.core.platform.storage.sqlite_store import SQLiteStore

    ledger = SQLiteStore(tmp_path / "global.db")
    private = SQLiteStore(tmp_path / "account.db")
    monkeypatch.setattr(memory_store, "get_memory_store", lambda: SimpleNamespace(sqlite=ledger))
    monkeypatch.setattr(
        assistant,
        "get_memory_factory",
        lambda: SimpleNamespace(get_for_identity=lambda _: SimpleNamespace(sqlite=private)),
    )
    for owner, tokens in [("alice", 13), ("bob", 700), ("", 1000), ("_local", 500)]:
        recorder = UsageRecorder(TurnContext(prompt="test", session_id=f"u_{owner}__personal_1"), owner_uid=owner)
        with recorder:
            recorder.add({"prompt_tokens": tokens - 1, "completion_tokens": 1, "model": "test"})

    app = FastAPI()
    app.include_router(assistant.router)
    app.dependency_overrides[current_identity_dependency] = lambda: Identity(user_id="alice")
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    with TestClient(app) as client:
        for params in ({"days": 31}, {"month": month, "timezone": "UTC"}):
            result = client.get("/assistant/usage", params=params)
            assert result.status_code == 200
            body = result.json()
            assert body["total_tokens"] == 13
            assert len(body["recent"]) == 1
            assert body["recent"][0]["owner_user_id"] == "alice"
        app.dependency_overrides[current_identity_dependency] = lambda: Identity(user_id="_local")
        assert client.get("/assistant/usage").json()["total_tokens"] == 1500
        assert client.get("/assistant/usage", params={"month": month}).json()["total_tokens"] == 1500
