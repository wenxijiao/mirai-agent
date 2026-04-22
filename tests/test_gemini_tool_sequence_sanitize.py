"""_sanitize_gemini_tool_sequence must drop orphan tool rows (Gemini 400 on bad ordering)."""

from mirai.core.providers.gemini_provider import _sanitize_gemini_tool_sequence


def test_drops_tool_rows_after_system_when_window_starts_mid_turn():
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "system", "content": "Extra context."},
        {"role": "tool", "name": "lights", "content": '{"on": true}'},
        {"role": "user", "content": "[12:00] Timer fired"},
    ]
    out = _sanitize_gemini_tool_sequence(messages)
    assert [m.get("role") for m in out] == ["system", "system", "user"]


def test_keeps_paired_assistant_tool_block():
    messages = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "1", "function": {"name": "ping", "arguments": "{}"}}],
        },
        {"role": "tool", "name": "ping", "content": "pong"},
        {"role": "user", "content": "thanks"},
    ]
    out = _sanitize_gemini_tool_sequence(messages)
    assert len(out) == 4
    assert out[1]["role"] == "assistant" and out[1].get("tool_calls")
    assert out[2]["role"] == "tool"


def test_drops_incomplete_assistant_tool_calls_tail():
    messages = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "1", "function": {"name": "a", "arguments": "{}"}},
                {"id": "2", "function": {"name": "b", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "name": "a", "content": "1"},
        {"role": "user", "content": "next"},
    ]
    out = _sanitize_gemini_tool_sequence(messages)
    assert [m.get("role") for m in out] == ["user", "user"]
