from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, time, timezone

from mirai.core.config.model import ModelConfig
from mirai.core.proactive.state import ProactiveSessionState, parse_iso


@dataclass
class ProactiveDecision:
    should_send: bool
    trigger: str = ""
    reason: str = ""


def _parse_clock(value: str) -> time | None:
    try:
        hour_s, minute_s = value.strip().split(":", 1)
        hour = int(hour_s)
        minute = int(minute_s)
    except (ValueError, TypeError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour=hour, minute=minute)


def in_quiet_hours(now: datetime, quiet_hours: str) -> bool:
    if not quiet_hours or "-" not in quiet_hours:
        return False
    start_s, end_s = quiet_hours.split("-", 1)
    start = _parse_clock(start_s)
    end = _parse_clock(end_s)
    if start is None or end is None:
        return False
    current = now.time().replace(second=0, microsecond=0)
    if start <= end:
        return start <= current < end
    return current >= start or current < end


def _minutes_since(now: datetime, value: str | None) -> float | None:
    dt = parse_iso(value)
    if dt is None:
        return None
    return max(0.0, (now.astimezone(timezone.utc) - dt).total_seconds() / 60.0)


def decide_proactive_send(
    cfg: ModelConfig,
    state: ProactiveSessionState,
    *,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> ProactiveDecision:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rng = rng or random.Random()

    if not cfg.proactive_enabled:
        return ProactiveDecision(False, reason="disabled")
    if cfg.proactive_daily_limit <= 0:
        return ProactiveDecision(False, reason="daily_limit_zero")
    if in_quiet_hours(now, cfg.proactive_quiet_hours):
        return ProactiveDecision(False, reason="quiet_hours")

    today = now.date().isoformat()
    sent_today = state.sent_today if state.date == today else 0
    if sent_today >= cfg.proactive_daily_limit:
        return ProactiveDecision(False, reason="daily_limit")

    since_user = _minutes_since(now, state.last_user_message_at)
    since_proactive = _minutes_since(now, state.last_proactive_at)

    if since_proactive is not None and since_proactive < cfg.proactive_min_idle_minutes:
        return ProactiveDecision(False, reason="recent_proactive")
    if since_user is not None and since_user < cfg.proactive_min_idle_minutes:
        return ProactiveDecision(False, reason="recent_user_message")

    if state.unreplied_count > 0:
        if since_proactive is None or since_proactive >= cfg.proactive_unreplied_escalation_minutes:
            return ProactiveDecision(True, trigger="unreplied_followup", reason="user_has_not_replied")
        return ProactiveDecision(False, reason="waiting_before_unreplied_followup")

    # Low-frequency surprise/check-in. The service runs periodically, so keep
    # this probabilistic to avoid mechanical messages.
    if rng.random() < 0.35:
        return ProactiveDecision(True, trigger="check_in", reason="random_check_in")
    return ProactiveDecision(False, reason="random_skip")
