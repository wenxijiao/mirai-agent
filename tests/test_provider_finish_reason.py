"""Provider stop reasons are normalized before they reach chat orchestration."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
import yumi.core.platform.providers.ollama_provider as ollama_mod
from yumi.core.chatbot import YumiBot
from yumi.core.features.config.model import ModelConfig
from yumi.core.platform.providers.claude_provider import _normalize_claude_finish_reason
from yumi.core.platform.providers.gemini_provider import _normalize_gemini_finish_reason
from yumi.core.platform.providers.ollama_provider import OllamaProvider, _normalize_ollama_finish_reason
from yumi.core.platform.providers.openai_provider import OpenAIProvider, _normalize_openai_finish_reason


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "stop"),
        ("stop", "stop"),
        ("length", "length"),
        ("content_filter", "blocked"),
        ("tool_calls", "unknown"),
    ],
)
def test_openai_finish_reason_mapping(raw, expected) -> None:
    assert _normalize_openai_finish_reason(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("end_turn", "stop"),
        ("stop_sequence", "stop"),
        ("max_tokens", "length"),
        ("refusal", "blocked"),
        ("pause_turn", "unknown"),
    ],
)
def test_claude_finish_reason_mapping(raw, expected) -> None:
    assert _normalize_claude_finish_reason(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("STOP", "stop"),
        ("MAX_TOKENS", "length"),
        ("SAFETY", "blocked"),
        ("MALFORMED_FUNCTION_CALL", "unknown"),
    ],
)
def test_gemini_finish_reason_mapping(raw, expected) -> None:
    assert _normalize_gemini_finish_reason(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "stop"),
        ("stop", "stop"),
        ("length", "length"),
        ("safety", "blocked"),
        ("load", "unknown"),
    ],
)
def test_ollama_finish_reason_mapping(raw, expected) -> None:
    assert _normalize_ollama_finish_reason(raw) == expected


class _AsyncChunks:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        async def generate():
            for chunk in self._chunks:
                yield chunk

        return generate()


async def _collect(stream):
    return [chunk async for chunk in stream]


def test_yumi_bot_forwards_finish_and_persists_visible_text() -> None:
    class _Provider:
        async def chat_stream(self, **_kwargs):
            yield {"type": "text", "content": "hello"}
            yield {"type": "finish", "reason": "stop", "provider_reason": "stop"}

    class _Memory:
        session_id = "s_finish"

        def __init__(self):
            self.saved = []

        def get_context(self, **_kwargs):
            return [{"role": "system", "content": "system"}]

        def add_message(self, role, content, **kwargs):
            self.saved.append((role, content, kwargs))
            return f"m{len(self.saved)}"

    memory = _Memory()
    bot = YumiBot(
        provider=_Provider(),
        model_name="m",
        runtime_config=ModelConfig(chat_append_current_time=False),
    )
    bot._get_memory = lambda _session_id="default": memory

    out = asyncio.run(_collect(bot.chat_stream(prompt="hi", session_id=memory.session_id)))

    assert [chunk["type"] for chunk in out] == ["text", "finish"]
    assert [(role, content) for role, content, _ in memory.saved] == [("user", "hi"), ("assistant", "hello")]


def test_openai_stream_emits_normalized_length_finish() -> None:
    text_delta = SimpleNamespace(content="partial", tool_calls=None, reasoning_content=None)
    final_delta = SimpleNamespace(content=None, tool_calls=None, reasoning_content=None)
    chunks = [
        SimpleNamespace(usage=None, choices=[SimpleNamespace(delta=text_delta, finish_reason=None)]),
        SimpleNamespace(usage=None, choices=[SimpleNamespace(delta=final_delta, finish_reason="length")]),
    ]

    class _Completions:
        async def create(self, **_kwargs):
            return _AsyncChunks(chunks)

    provider = object.__new__(OpenAIProvider)
    provider._async_client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))

    out = asyncio.run(_collect(provider.chat_stream(model="m", messages=[])))

    assert out[-1] == {"type": "finish", "reason": "length", "provider_reason": "length"}


def test_ollama_stream_emits_normalized_blocked_finish(monkeypatch) -> None:
    chunks = [
        {"message": {"content": "partial"}},
        {"message": {}, "done": True, "done_reason": "safety"},
    ]

    class _Client:
        async def chat(self, **_kwargs):
            return _AsyncChunks(chunks)

    monkeypatch.setattr(ollama_mod.ollama, "AsyncClient", lambda: _Client())

    out = asyncio.run(_collect(OllamaProvider().chat_stream(model="m", messages=[])))

    assert out[-1] == {"type": "finish", "reason": "blocked", "provider_reason": "safety"}
