"""Tool-dispatch domain layer for one chat turn.

Decomposed from the legacy ``_generate_chat_events_impl`` god function:

* ``TurnContext``           — turn-scoped mutable state.
* ``ToolInvocation``/``ToolResult`` — value objects across the boundary.
* ``ChatTraceSink``         — observability (debug trace + diagnostics).
* ``UsageRecorder``         — token accounting (context manager).
* ``ToolCallNormalizer``    — model-emit format normalization + retry budget.
* ``ConfirmationGate``      — user-confirmation flow for sensitive tools.
* ``LocalToolExecutor``     — registered local-Python tool runner.
* ``EdgeToolExecutor``      — WebSocket RPC to an edge peer.
* ``ToolDispatcher``        — orchestrates prepare → run for one model turn.
"""

from mirai.core.dispatch.confirmation import ConfirmationGate
from mirai.core.dispatch.context import ToolInvocation, ToolResult, TurnContext
from mirai.core.dispatch.dispatcher import ToolDispatcher, canonical_local_tool_name
from mirai.core.dispatch.edge import EdgeToolExecutor
from mirai.core.dispatch.limits import (
    LOCAL_TOOL_TIMEOUT_DEFAULT,
    MAX_TOOL_CALL_FORMAT_RETRIES,
    MAX_TOOL_LOOPS,
    TOOL_CALL_TIMEOUT_DEFAULT,
)
from mirai.core.dispatch.local import LocalToolExecutor
from mirai.core.dispatch.normalizer import NormalizationOutcome, ToolCallNormalizer, summarize_tool_args
from mirai.core.dispatch.trace_sink import ChatTraceSink
from mirai.core.dispatch.usage import UsageRecorder

__all__ = [
    "ChatTraceSink",
    "ConfirmationGate",
    "EdgeToolExecutor",
    "LOCAL_TOOL_TIMEOUT_DEFAULT",
    "LocalToolExecutor",
    "MAX_TOOL_CALL_FORMAT_RETRIES",
    "MAX_TOOL_LOOPS",
    "NormalizationOutcome",
    "TOOL_CALL_TIMEOUT_DEFAULT",
    "ToolCallNormalizer",
    "ToolDispatcher",
    "ToolInvocation",
    "ToolResult",
    "TurnContext",
    "UsageRecorder",
    "canonical_local_tool_name",
    "summarize_tool_args",
]
