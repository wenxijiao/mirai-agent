import asyncio
from datetime import datetime, timedelta, timezone

from mirai.core.config import ModelConfig
from mirai.core.config.store import load_model_config
from mirai.core.proactive.planner import ProactiveDecision, decide_proactive_send, in_quiet_hours
from mirai.core.proactive.prompt import build_proactive_prompt
from mirai.core.proactive.service import ProactiveMessageService
from mirai.core.proactive.state import ProactiveSessionState, ProactiveStateStore
from mirai.core.proactive.tools import proactive_context_lines, proactive_tool_schemas
from mirai.core.tool import TOOL_REGISTRY, register_tool


def test_proactive_config_defaults_disabled():
    cfg = ModelConfig()
    assert cfg.proactive_enabled is False
    assert cfg.proactive_channels == ["telegram"]
    assert cfg.proactive_session_ids == []
    assert cfg.proactive_profile == "default"


def test_proactive_env_overrides(monkeypatch, tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("mirai.core.config.paths.CONFIG_PATH", p)
    monkeypatch.setattr("mirai.core.config.store.CONFIG_PATH", p)
    monkeypatch.setenv("MIRAI_PROACTIVE_ENABLED", "1")
    monkeypatch.setenv("MIRAI_PROACTIVE_SESSION_IDS", "tg_1,tg_2")
    monkeypatch.setenv("MIRAI_PROACTIVE_PROFILE", "writing_partner")
    monkeypatch.setenv("MIRAI_PROACTIVE_PROFILE_PROMPT", "Check on the draft.")
    monkeypatch.setenv("MIRAI_PROACTIVE_TONE_INTENSITY", "medium")

    cfg = load_model_config()

    assert cfg.proactive_enabled is True
    assert cfg.proactive_session_ids == ["tg_1", "tg_2"]
    assert cfg.proactive_profile == "writing_partner"
    assert cfg.proactive_profile_prompt == "Check on the draft."
    assert cfg.proactive_tone_intensity == "medium"


def test_proactive_planner_respects_quiet_hours_and_limits():
    cfg = ModelConfig(proactive_enabled=True, proactive_daily_limit=1, proactive_quiet_hours="00:30-08:30")
    quiet_now = datetime(2026, 5, 3, 1, 0, tzinfo=timezone.utc)
    assert in_quiet_hours(quiet_now, cfg.proactive_quiet_hours) is True
    assert decide_proactive_send(cfg, ProactiveSessionState("tg_1"), now=quiet_now).reason == "quiet_hours"

    active_now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    state = ProactiveSessionState("tg_1", date="2026-05-03", sent_today=1)
    assert decide_proactive_send(cfg, state, now=active_now).reason == "daily_limit"


def test_proactive_planner_unreplied_followup():
    cfg = ModelConfig(
        proactive_enabled=True,
        proactive_quiet_hours="",
        proactive_min_idle_minutes=10,
        proactive_unreplied_escalation_minutes=30,
    )
    now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    state = ProactiveSessionState(
        "tg_1",
        date="2026-05-03",
        last_proactive_at=(now - timedelta(minutes=31)).isoformat(),
        unreplied_count=1,
    )

    decision = decide_proactive_send(cfg, state, now=now)

    assert decision.should_send is True
    assert decision.trigger == "unreplied_followup"


def test_proactive_tool_policy_and_context(monkeypatch):
    TOOL_REGISTRY.clear()

    def status() -> str:
        return "all good"

    def hidden() -> str:
        return "hidden"

    register_tool(status, "Read status", allow_proactive=True, proactive_context=True)
    register_tool(hidden, "Hidden")

    assert [t["function"]["name"] for t in proactive_tool_schemas()] == ["status"]

    lines = asyncio.run(proactive_context_lines())
    assert lines == ["status: all good"]


def test_proactive_prompt_always_includes_current_time_context():
    now = datetime(2026, 5, 3, 12, 30, tzinfo=timezone.utc)
    prompt = build_proactive_prompt(
        ModelConfig(),
        ProactiveSessionState("tg_1"),
        decision=ProactiveDecision(True, trigger="check_in", reason="test"),
        now=now,
        context_lines=[],
    )

    assert "[Proactive Context]" in prompt
    assert "- Current time: 2026-05-03 12:30:00 Sunday" in prompt


def test_proactive_service_sends_and_records(monkeypatch, tmp_path):
    class FakeMemory:
        def __init__(self):
            self.added = []

        def get_context(self, query=None):
            return [{"role": "system", "content": "Be concise."}]

        def add_message(self, role, content, thought=None):
            self.added.append((role, content))

    class FakeProvider:
        async def chat_stream(self, **_kwargs):
            yield {"type": "text", "content": "<msg>Hello there</msg><msg>Small check-in</msg>"}

    class FakeBot:
        def __init__(self):
            self.provider = FakeProvider()
            self.model_name = "fake"
            self.memory = FakeMemory()

        def session_memory(self, session_id):
            return self.memory

    sent = []

    async def fake_send(session_id, text, prefix=""):
        sent.append((session_id, text, prefix))
        return True

    monkeypatch.setattr("mirai.telegram.notify.send_text_to_telegram", fake_send)
    store = ProactiveStateStore(tmp_path / "state.json")
    now = datetime.now(timezone.utc)
    store.put(
        ProactiveSessionState(
            "tg_1",
            date=now.date().isoformat(),
            last_proactive_at=(now - timedelta(minutes=200)).isoformat(),
            unreplied_count=1,
        )
    )
    cfg = ModelConfig(
        proactive_enabled=True,
        proactive_session_ids=["tg_1"],
        proactive_quiet_hours="",
        proactive_min_idle_minutes=1,
        proactive_unreplied_escalation_minutes=30,
    )

    asyncio.run(ProactiveMessageService(FakeBot(), state_store=store)._maybe_send_for_session("tg_1", cfg=cfg))

    assert sent == [("tg_1", "Hello there", ""), ("tg_1", "Small check-in", "")]
    assert store.get("tg_1").sent_today == 1
