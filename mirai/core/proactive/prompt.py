from __future__ import annotations

import re
from datetime import datetime

from mirai.core.config.model import ModelConfig
from mirai.core.proactive.planner import ProactiveDecision
from mirai.core.proactive.profiles import profile_hint
from mirai.core.proactive.state import ProactiveSessionState

_MSG_RE = re.compile(r"<msg>(.*?)</msg>", re.DOTALL | re.IGNORECASE)


def build_proactive_prompt(
    cfg: ModelConfig,
    state: ProactiveSessionState,
    decision: ProactiveDecision,
    *,
    now: datetime,
    context_lines: list[str] | None = None,
) -> str:
    current_time = f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S %A')}"
    context_items = [current_time, *[line for line in (context_lines or []) if line.strip()]]
    context = "\n".join(f"- {line}" for line in context_items)
    context_block = f"\n[Proactive Context]\n{context}\n"
    return (
        "[Proactive message request]\n"
        "Generate a short proactive outbound message for this session.\n"
        "Follow the active system prompt and session persona. Do not invent a different role.\n"
        f"Profile guidance: {profile_hint(cfg)}\n"
        f"Tone intensity: {cfg.proactive_tone_intensity}\n"
        f"Trigger: {decision.trigger or 'check_in'} ({decision.reason})\n"
        f"Unreplied proactive count: {state.unreplied_count}\n"
        f"{context_block}"
        "Rules:\n"
        "- Output only the message text, or <skip/> if now is not a good time.\n"
        "- Keep it natural for the configured persona and use the user's likely language.\n"
        "- Prefer 1-3 short chat messages using <msg>...</msg> blocks when multiple bubbles feel natural.\n"
        "- Do not mention this scheduler, configuration, or background job.\n"
        "- Do not claim you used tools unless the context explicitly contains that information.\n"
    )


def split_proactive_messages(text: str, *, max_parts: int = 3) -> list[str]:
    raw = (text or "").strip()
    if not raw or raw.lower() == "<skip/>":
        return []
    tagged = [m.group(1).strip() for m in _MSG_RE.finditer(raw) if m.group(1).strip()]
    if tagged:
        return tagged[:max_parts]
    chunks = [p.strip() for p in re.split(r"\n\s*\n+", raw) if p.strip()]
    if len(chunks) > 1:
        return chunks[:max_parts]
    return [raw]
