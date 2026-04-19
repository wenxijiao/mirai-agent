"""Unit tests for mirai.core.prompts.http_bridge helpers."""

from mirai.core.prompts.http_bridge import format_effective_prompt_reply, truncate_for_bot_display


def test_truncate_for_bot_display() -> None:
    assert truncate_for_bot_display("ab", max_chars=10) == "ab"
    long = "x" * 100
    out = truncate_for_bot_display(long, max_chars=20)
    assert len(out) == 20
    assert out.endswith("…")


def test_format_effective_prompt_reply() -> None:
    text = format_effective_prompt_reply(effective="hi", source_label="全局默认")
    assert "全局默认" in text
    assert "hi" in text
