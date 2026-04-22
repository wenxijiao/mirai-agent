"""Session row trimming for tool replay (sliding window must not split tool turns)."""

import json

from mirai.core.memories.constants import MIRAI_V1_TOOL_CALLS, MIRAI_V1_TOOL_RESULT
from mirai.core.memories.memory import (
    _assistant_tool_call_count_from_stored_raw,
    _trim_leading_orphan_tool_rows,
    _trim_trailing_incomplete_tool_rows,
)


def _tc_payload(n: int) -> str:
    calls = [{"id": str(i), "type": "function", "function": {"name": f"t{i}", "arguments": "{}"}} for i in range(n)]
    return MIRAI_V1_TOOL_CALLS + json.dumps({"content": "", "tool_calls": calls})


def test_trailing_incomplete_drops_suffix():
    rows = [
        {"role": "user", "content": "hi", "timestamp": "1"},
        {"role": "assistant", "content": _tc_payload(2), "timestamp": "2"},
        {
            "role": "tool",
            "content": MIRAI_V1_TOOL_RESULT + json.dumps({"name": "t0", "content": "x"}),
            "timestamp": "3",
        },
    ]
    out = _trim_trailing_incomplete_tool_rows(rows)
    assert len(out) == 1 and out[0]["role"] == "user"


def test_complete_tool_block_kept():
    t1 = MIRAI_V1_TOOL_CALLS + json.dumps(
        {
            "content": "",
            "tool_calls": [{"id": "1", "type": "function", "function": {"name": "a", "arguments": "{}"}}],
        }
    )
    rows = [
        {"role": "user", "content": "hi", "timestamp": "1"},
        {"role": "assistant", "content": t1, "timestamp": "2"},
        {"role": "tool", "content": MIRAI_V1_TOOL_RESULT + json.dumps({"name": "a", "content": "x"}), "timestamp": "3"},
    ]
    out = _trim_trailing_incomplete_tool_rows(rows)
    assert len(out) == 3


def test_leading_orphan_tools_removed():
    rows = [
        {"role": "tool", "content": "x"},
        {"role": "user", "content": "hi"},
    ]
    out = _trim_leading_orphan_tool_rows(rows)
    assert [r["role"] for r in out] == ["user"]


def test_assistant_tool_call_count_parsed():
    assert _assistant_tool_call_count_from_stored_raw("plain") is None
    raw = _tc_payload(3)
    assert _assistant_tool_call_count_from_stored_raw(raw) == 3
