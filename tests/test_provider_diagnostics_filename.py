"""Diagnostic log filenames include UTC time, provider, phase, model, and error hint."""

from __future__ import annotations

from datetime import datetime, timezone

from mirai.core.providers.diagnostics import build_provider_diagnostic_filename


def test_diagnostic_filename_includes_stamp_provider_phase_model_hint():
    fixed = datetime(2026, 5, 4, 12, 23, 56, tzinfo=timezone.utc)
    name = build_provider_diagnostic_filename(
        provider="gemini",
        phase="chat_stream",
        exc=RuntimeError("400 INVALID_ARGUMENT. something"),
        model="gemini-3-flash-preview",
        now=fixed,
        unique_suffix_len=8,
    )
    assert name.startswith("20260504T122356Z_gemini_chat_stream_gemini-3-flash-preview_")
    assert "INVALID_ARGUMENT" in name
    assert name.endswith(".json")
    assert len(name.rsplit("_", 1)[-1].removesuffix(".json")) == 8


def test_diagnostic_filename_optional_note():
    fixed = datetime(2026, 5, 3, 0, 0, 0, tzinfo=timezone.utc)
    name = build_provider_diagnostic_filename(
        provider="openai",
        phase="chat_stream_text_only_fallback",
        exc=ValueError("rate limited"),
        note="vision-retry",
        now=fixed,
        unique_suffix_len=6,
    )
    assert name.startswith("20260503T000000Z_openai_chat_stream_text_only_fallback_")
    assert "rate-limited" in name
    assert "vision-retry" in name
