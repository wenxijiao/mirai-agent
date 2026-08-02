from __future__ import annotations

from typing import Any, AsyncIterator, Literal

ProviderFinishReason = Literal["stop", "length", "blocked", "unknown"]


def provider_reason_text(reason: Any) -> str | None:
    """Return a stable text form for SDK strings/enums used as stop reasons."""
    if reason is None:
        return None
    name = getattr(reason, "name", None)
    if isinstance(name, str) and name:
        return name
    value = getattr(reason, "value", None)
    if isinstance(value, str) and value:
        return value
    text = str(reason).strip()
    if not text:
        return None
    # Enum stringification commonly produces ``FinishReason.STOP``.
    return text.rsplit(".", 1)[-1]


def provider_finish_chunk(
    reason: ProviderFinishReason,
    *,
    provider_reason: Any = None,
) -> dict[str, Any]:
    """Build the provider-independent terminal event consumed by Yumi."""
    chunk: dict[str, Any] = {"type": "finish", "reason": reason}
    raw = provider_reason_text(provider_reason)
    if raw:
        chunk["provider_reason"] = raw
    return chunk


class BaseLLMProvider:
    """Protocol for LLM providers.

    Every provider must implement at least ``chat_stream`` and ``embed``.
    ``list_models`` / ``pull_model`` / ``warm_up`` / ``shutdown`` are
    optional and default to no-ops.
    """

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict] | None = None,
        think: bool = False,
    ) -> AsyncIterator[dict]:
        """Yield normalized chunks.

        Text chunks::

            {"type": "text", "content": "partial text"}

        Tool-call chunks (terminates the stream)::

            {"type": "tool_call", "tool_calls": [
                {"function": {"name": "...", "arguments": {...}}}
            ]}

        The ``tool_calls`` list must use OpenAI-style structure regardless
        of the underlying provider.

        A stream without a tool call ends with a normalized finish chunk::

            {"type": "finish", "reason": "stop"}

        ``reason`` is one of ``stop`` / ``length`` / ``blocked`` / ``unknown``.
        Provider-specific raw reasons may be included as ``provider_reason``.
        """
        raise NotImplementedError
        yield  # pragma: no cover – make this an async generator

    def embed(self, model: str, text: str) -> list[float]:
        """Return a single embedding vector for *text*."""
        raise NotImplementedError

    def list_models(self) -> list[str]:
        """Return available model names (best-effort, may be empty)."""
        return []

    def pull_model(self, model_name: str) -> None:
        """Download / prepare a model.  No-op for cloud providers."""

    async def warm_up(self, model: str) -> None:
        """Optional: pre-load a model into memory."""

    async def shutdown(self, model: str) -> None:
        """Optional: release model resources."""


__all__ = [
    "BaseLLMProvider",
    "ProviderFinishReason",
    "provider_finish_chunk",
    "provider_reason_text",
]
