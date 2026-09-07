"""Attribution propagated to model, embedding and background work."""

from contextvars import ContextVar

usage_turn_id: ContextVar[str] = ContextVar("usage_turn_id", default="")
usage_owner_id: ContextVar[str] = ContextVar("usage_owner_id", default="")
usage_operation: ContextVar[str] = ContextVar("usage_operation", default="embedding")
embedding_tokens: ContextVar[int | None] = ContextVar("embedding_tokens", default=None)
