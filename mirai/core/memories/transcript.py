"""Transcript helpers for replay-safe chat history windows."""

from __future__ import annotations

import json

from mirai.core.memories.constants import MIRAI_V1_TOOL_CALLS


def assistant_tool_call_count_from_stored_raw(raw: str) -> int | None:
    """Return the persisted assistant tool-call count, if *raw* stores one."""

    if not raw.startswith(MIRAI_V1_TOOL_CALLS):
        return None
    try:
        data = json.loads(raw[len(MIRAI_V1_TOOL_CALLS) :])
        tcalls = data.get("tool_calls")
        if isinstance(tcalls, list) and len(tcalls) > 0:
            return len(tcalls)
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def trim_trailing_incomplete_tool_rows(rows: list[dict]) -> list[dict]:
    """Drop a suffix that starts at an assistant tool-call row without enough tool rows."""

    if not rows:
        return rows
    out = list(rows)
    i = 0
    while i < len(out):
        if out[i].get("role") != "assistant":
            i += 1
            continue
        raw = out[i].get("content") or ""
        n = assistant_tool_call_count_from_stored_raw(raw)
        if not n:
            i += 1
            continue
        j = i + 1
        got = 0
        while j < len(out) and out[j].get("role") == "tool" and got < n:
            got += 1
            j += 1
        if got < n:
            return out[:i]
        i = j
    return out


def trim_leading_orphan_tool_rows(rows: list[dict]) -> list[dict]:
    """Drop tool rows whose preceding assistant tool-call turn was outside the window."""

    out = list(rows)
    while out and out[0].get("role") == "tool":
        out.pop(0)
    return out
