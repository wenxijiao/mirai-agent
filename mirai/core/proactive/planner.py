from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import datetime, timezone

from mirai.core.config.model import ModelConfig
from mirai.core.proactive.state import ProactiveSessionState, parse_iso
from mirai.core.proactive.timezone_utils import (
    in_quiet_hours,
    proactive_calendar_date_iso,
)


@dataclass
class ProactiveDecision:
    should_send: bool
    trigger: str = ""
    reason: str = ""


def _minutes_since(now: datetime, value: str | None) -> float | None:
    dt = parse_iso(value)
    if dt is None:
        return None
    return max(0.0, (now.astimezone(timezone.utc) - dt).total_seconds() / 60.0)


def _effective_unreplied_escalation_minutes(cfg: ModelConfig, state: ProactiveSessionState) -> float:
    base = float(cfg.proactive_unreplied_escalation_minutes)
    j = float(cfg.proactive_unreplied_escalation_jitter_ratio)
    if j <= 0:
        return base
    digest = hashlib.sha256(f"{state.session_id}\0{state.last_proactive_at or ''}".encode()).digest()
    seed = int.from_bytes(digest[:8], "big")
    rng = random.Random(seed)
    lo = max(0.0, 1.0 - j)
    hi = 1.0 + j
    return base * rng.uniform(lo, hi)


def decide_proactive_send(
    cfg: ModelConfig,
    state: ProactiveSessionState,
    *,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> ProactiveDecision:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rng = rng or random.Random()
    tz = cfg.local_timezone

    if not cfg.proactive_enabled:
        return ProactiveDecision(False, reason="disabled")
    if cfg.proactive_daily_limit <= 0:
        return ProactiveDecision(False, reason="daily_limit_zero")
    if in_quiet_hours(now, cfg.proactive_quiet_hours, tz):
        return ProactiveDecision(False, reason="quiet_hours")

    today = proactive_calendar_date_iso(now, tz)
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
        need = _effective_unreplied_escalation_minutes(cfg, state)
        if since_proactive is None or since_proactive >= need:
            return ProactiveDecision(True, trigger="unreplied_followup", reason="user_has_not_replied")
        return ProactiveDecision(False, reason="waiting_before_unreplied_followup")

    # Low-frequency surprise/check-in. The service runs periodically, so keep
    # this probabilistic to avoid mechanical messages.
    p = float(cfg.proactive_check_in_probability)
    if rng.random() < p:
        return ProactiveDecision(True, trigger="check_in", reason="random_check_in")
    return ProactiveDecision(False, reason="random_skip")
