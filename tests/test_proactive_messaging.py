import asyncio
import random
from datetime import datetime, timedelta, timezone

from mirai.core.config import ModelConfig
from mirai.core.config.store import load_model_config
from mirai.core.proactive.planner import ProactiveDecision, decide_proactive_send, in_quiet_hours
from mirai.core.proactive.prompt import build_proactive_prompt
from mirai.core.proactive.service import ProactiveMessageService
from mirai.core.proactive.state import ProactiveSessionState, ProactiveStateStore
from mirai.core.proactive.timezone_utils import format_user_facing_time
from mirai.core.proactive.tools import proactive_context_lines, proactive_tool_schemas
from mirai.core.tool import TOOL_REGISTRY, register_tool


def test_proactive_config_defaults_disabled():
    cfg = ModelConfig()
    assert cfg.proactive_enabled is False
    assert cfg.proactive_channels == ["telegram"]
    assert cfg.proactive_session_ids == []
    assert cfg.proactive_profile == "default"
    assert cfg.local_timezone is None
    assert cfg.proactive_check_interval_jitter_ratio == 0.15
    assert cfg.proactive_unreplied_escalation_jitter_ratio == 0.0
    assert cfg.proactive_check_in_probability == 0.35


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
    monkeypatch.setenv("MIRAI_PROACTIVE_QUIET_HOURS_TIMEZONE", "Pacific/Auckland")
    monkeypatch.setenv("MIRAI_PROACTIVE_CHECK_INTERVAL_JITTER_RATIO", "0.2")
    monkeypatch.setenv("MIRAI_PROACTIVE_UNREPLIED_ESCALATION_JITTER_RATIO", "0.1")
    monkeypatch.setenv("MIRAI_PROACTIVE_CHECK_IN_PROBABILITY", "0.5")

    cfg = load_model_config()

    assert cfg.proactive_enabled is True
    assert cfg.proactive_session_ids == ["tg_1", "tg_2"]
    assert cfg.proactive_profile == "writing_partner"
    assert cfg.proactive_profile_prompt == "Check on the draft."
    assert cfg.proactive_tone_intensity == "medium"
    assert cfg.local_timezone == "Pacific/Auckland"
    assert cfg.proactive_check_interval_jitter_ratio == 0.2
    assert cfg.proactive_unreplied_escalation_jitter_ratio == 0.1
    assert cfg.proactive_check_in_probability == 0.5


def test_proactive_env_local_timezone_override_precedence(monkeypatch, tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("mirai.core.config.paths.CONFIG_PATH", p)
    monkeypatch.setattr("mirai.core.config.store.CONFIG_PATH", p)
    monkeypatch.setenv("MIRAI_LOCAL_TIMEZONE", "Europe/London")
    monkeypatch.setenv("MIRAI_PROACTIVE_QUIET_HOURS_TIMEZONE", "Pacific/Auckland")

    cfg = load_model_config()

    assert cfg.local_timezone == "Europe/London"


def test_proactive_planner_respects_quiet_hours_and_limits():
    cfg = ModelConfig(proactive_enabled=True, proactive_daily_limit=1, proactive_quiet_hours="00:30-08:30")
    quiet_now = datetime(2026, 5, 3, 1, 0, tzinfo=timezone.utc)
    assert in_quiet_hours(quiet_now, cfg.proactive_quiet_hours) is True
    assert decide_proactive_send(cfg, ProactiveSessionState("tg_1"), now=quiet_now).reason == "quiet_hours"

    active_now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    state = ProactiveSessionState("tg_1", date="2026-05-03", sent_today=1)
    assert decide_proactive_send(cfg, state, now=active_now).reason == "daily_limit"


def test_format_user_facing_time_uses_iana_when_configured():
    now = datetime(2026, 5, 3, 4, 46, tzinfo=timezone.utc)
    s = format_user_facing_time(now, "Pacific/Auckland")
    assert "2026-05-03 16:46:00" in s


def test_proactive_quiet_hours_uses_configured_timezone():
    utc_moment = datetime(2026, 5, 3, 14, 0, tzinfo=timezone.utc)
    assert in_quiet_hours(utc_moment, "00:30-08:30", None) is False
    assert in_quiet_hours(utc_moment, "00:30-08:30", "Pacific/Auckland") is True


def test_proactive_daily_limit_calendar_follows_timezone():
    cfg = ModelConfig(
        proactive_enabled=True,
        proactive_daily_limit=1,
        proactive_quiet_hours="",
        local_timezone="Pacific/Auckland",
    )
    now = datetime(2026, 5, 3, 14, 0, tzinfo=timezone.utc)
    state = ProactiveSessionState("tg_1", date="2026-05-04", sent_today=1)
    assert decide_proactive_send(cfg, state, now=now).reason == "daily_limit"


def test_proactive_unreplied_escalation_jitter_is_deterministic_per_state():
    cfg = ModelConfig(
        proactive_enabled=True,
        proactive_quiet_hours="",
        proactive_min_idle_minutes=1,
        proactive_unreplied_escalation_minutes=60,
        proactive_unreplied_escalation_jitter_ratio=0.25,
    )
    now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    last_p = (now - timedelta(minutes=50)).isoformat()
    state = ProactiveSessionState("tg_1", last_proactive_at=last_p, unreplied_count=1)
    a = decide_proactive_send(cfg, state, now=now, rng=random.Random(1))
    b = decide_proactive_send(cfg, state, now=now, rng=random.Random(999))
    assert a.should_send == b.should_send
    assert a.reason == b.reason


def test_proactive_check_in_respects_configured_probability():
    cfg = ModelConfig(
        proactive_enabled=True,
        proactive_quiet_hours="",
        proactive_min_idle_minutes=1,
        proactive_check_in_probability=0.0,
    )
    now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    state = ProactiveSessionState(
        "tg_1",
        last_proactive_at=(now - timedelta(minutes=120)).isoformat(),
        last_user_message_at=(now - timedelta(minutes=120)).isoformat(),
        unreplied_count=0,
    )
    decision = decide_proactive_send(cfg, state, now=now, rng=random.Random(42))
    assert decision.should_send is False
    assert decision.reason == "random_skip"


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
    expected = format_user_facing_time(now, None)
    assert f"- Current time: {expected}" in prompt


def test_proactive_service_sends_and_records(monkeypatch, tmp_path):
    p_cfg = tmp_path / "mirai_config.json"
    p_cfg.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("mirai.core.config.paths.CONFIG_PATH", p_cfg)
    monkeypatch.setattr("mirai.core.config.store.CONFIG_PATH", p_cfg)

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
