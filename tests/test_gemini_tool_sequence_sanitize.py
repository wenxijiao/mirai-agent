"""_sanitize_gemini_tool_sequence must drop orphan tool rows (Gemini 400 on bad ordering)."""

import base64

from mirai.core.providers.gemini_provider import GeminiProvider, _sanitize_gemini_tool_sequence
from mirai.core.tool_call_normalize import normalize_tool_calls


_SIG = base64.b64encode(b"gemini-thought-signature").decode("ascii")


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
            "tool_calls": [{"id": "1", "function": {"name": "ping", "arguments": "{}"}, "thought_signature": _SIG}],
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
                {"id": "1", "function": {"name": "a", "arguments": "{}"}, "thought_signature": _SIG},
                {"id": "2", "function": {"name": "b", "arguments": "{}"}, "thought_signature": _SIG},
            ],
        },
        {"role": "tool", "name": "a", "content": "1"},
        {"role": "user", "content": "next"},
    ]
    out = _sanitize_gemini_tool_sequence(messages)
    assert [m.get("role") for m in out] == ["user", "user"]


def test_drops_assistant_tool_block_without_gemini_thought_signature():
    messages = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "1", "function": {"name": "ping", "arguments": "{}"}}],
        },
        {"role": "tool", "name": "ping", "content": "pong"},
        {"role": "user", "content": "next"},
    ]

    out = _sanitize_gemini_tool_sequence(messages)
    assert [m.get("role") for m in out] == ["user", "user"]


def test_normalize_preserves_gemini_thought_signature():
    out = normalize_tool_calls(
        [{"function": {"name": "ping", "arguments": {}}, "thought_signature": _SIG}]
    )
    assert out[0]["thought_signature"] == _SIG


def test_build_contents_replays_gemini_thought_signature():
    provider = GeminiProvider.__new__(GeminiProvider)
    _, contents = provider._build_contents(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {"name": "ping", "arguments": {}},
                        "thought_signature": _SIG,
                    }
                ],
            }
        ]
    )

    part = contents[0].parts[0]
    assert part.thought_signature == base64.b64decode(_SIG)
