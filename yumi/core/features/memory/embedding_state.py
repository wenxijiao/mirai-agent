"""Process-wide embedding provider for Memory (set by API lifespan)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yumi.core.platform.providers.base import BaseLLMProvider

_embed_provider: "BaseLLMProvider | None" = None


class _MeteringEmbedWrapper:
    """Wrap ``embed()`` and forward usage estimates through the quota plugin."""

    def __init__(self, inner: "BaseLLMProvider"):
        self._inner = inner

    def embed(self, model: str, text: str) -> list[float]:
        from yumi.core.platform.dispatch.auxiliary_usage import record_auxiliary_usage
        from yumi.core.platform.providers.budget import token_estimate
        from yumi.core.platform.runtime.usage_context import embedding_tokens, usage_operation

        token = embedding_tokens.set(None)
        try:
            out = self._inner.embed(model, text)
            actual = embedding_tokens.get()
            record_auxiliary_usage(
                kind=usage_operation.get(),
                model=model or "unknown",
                prompt_tokens=actual if actual is not None else max(1, token_estimate(text)),
                estimated=actual is None,
            )
            return out
        finally:
            embedding_tokens.reset(token)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


def set_embed_provider(provider: "BaseLLMProvider | None") -> None:
    global _embed_provider
    if provider is None:
        _embed_provider = None
        return
    _embed_provider = _MeteringEmbedWrapper(provider)


def get_embed_provider() -> "BaseLLMProvider | None":
    return _embed_provider


def is_degenerate_vector(vec: list | tuple | None) -> bool:
    """True if vector is missing or all near-zero (unsuitable for ANN search)."""
    if vec is None:
        return True
    try:
        return all(abs(float(x)) < 1e-12 for x in vec)
    except (TypeError, ValueError):
        return True
