"""Single sink for durable chat-turn observability and failure diagnostics.

Callers ``sink.emit(event)`` with a typed :class:`~yumi.core.platform.http.events.ChatEvent`;
the sink records the event then returns it so the orchestrator can ``yield``
it directly. The HTTP boundary (``yumi.core.features.chat.pipeline.generate_chat_events``)
serialises models to dicts only at the public edge.
"""

from __future__ import annotations

from typing import Any

from yumi.core.features.prompts.catalog import prompt_catalog_metadata
from yumi.core.platform.dispatch.context import TurnContext
from yumi.core.platform.http.events import ChatEvent
from yumi.core.platform.observability import turn_inspector
from yumi.core.platform.providers.diagnostics import write_chat_diagnostic, write_chat_loop_diagnostic


class ChatTraceSink:
    """Wraps the trace recorder so collaborators don't need to know it exists."""

    def __init__(self, ctx: TurnContext, *, bot: Any | None = None) -> None:
        self.ctx = ctx
        self.bot = bot

    # ---- live event tracing -------------------------------------------------

    def emit(self, event: ChatEvent) -> ChatEvent:
        """Record *event* in the per-session debug trace if active and return it.

        Returns the event unchanged so the orchestrator can ``yield sink.emit(...)``
        in one expression and downstream code keeps the typed model.
        """
        payload = event.model_dump()
        turn_inspector.record_stream_event(self.ctx.session_id, payload)
        return event

    def record_provider_usage(self, chunk: dict) -> None:
        turn_inspector.record_usage(self.ctx.session_id, chunk)

    def record_provider_finish(self, chunk: dict) -> None:
        turn_inspector.record_finish(self.ctx.session_id, chunk)

    def record_turn_begin(self) -> None:
        turn_inspector.begin_turn(
            turn_id=self.ctx.turn_id,
            session_id=self.ctx.session_id,
            prompt=self.ctx.prompt,
            think=self.ctx.think,
            timer_callback=self.ctx.timer_callback,
            prompt_metadata=prompt_catalog_metadata(),
            owner_user_id=self.ctx.owner_uid or "",
        )

    def record_turn_end(
        self,
        *,
        total_prompt_tokens: int,
        total_completion_tokens: int,
        usage_model: str,
    ) -> None:
        detail = turn_inspector.end_turn(
            self.ctx.session_id,
            total_prompt_tokens=total_prompt_tokens,
            total_completion_tokens=total_completion_tokens,
            usage_model=usage_model,
            tool_loop_events=self.ctx.tool_loop_events,
        )
        if detail is None or self.bot is None:
            return
        try:
            self.bot.session_memory(self.ctx.session_id).sqlite.upsert_turn_trace(
                detail,
                owner_user_id=self.ctx.owner_uid or "",
            )
        except Exception:
            from yumi.logging_config import get_logger

            get_logger(__name__).debug("durable turn trace persistence skipped", exc_info=True)

    def record_routing(self) -> None:
        turn_inspector.record_routing(self.ctx.session_id, self.ctx.routing_summary)

    def record_tool_calls(self, tool_calls: list[dict]) -> None:
        turn_inspector.record_tool_calls(
            self.ctx.session_id,
            loop=self.ctx.loop_count,
            tool_calls=tool_calls,
        )

    def record_tool_result(self, inv: Any, result: Any) -> None:
        metrics = self.ctx.tool_metrics.get(str(getattr(inv, "tool_call_id", "") or ""), {})
        turn_inspector.record_tool_result(
            self.ctx.session_id,
            loop=self.ctx.loop_count,
            call_id=str(getattr(inv, "tool_call_id", "") or ""),
            tool=str(getattr(inv, "tool_message_name", "") or getattr(inv, "func_name", "")),
            resolved_tool=str(getattr(result, "func_name", "") or getattr(inv, "func_name", "")),
            kind=str(getattr(inv, "kind", "unknown")),
            edge=getattr(inv, "target_edge", None),
            status=str(getattr(result, "status", "unknown")),
            duration_ms=metrics.get("duration_ms"),
            result_preview=getattr(result, "result", ""),
        )

    # ---- diagnostics on failure ---------------------------------------------

    def write_diagnostic(
        self,
        phase: str,
        *,
        error: BaseException | None = None,
        extra: dict | None = None,
    ) -> str | None:
        return write_chat_diagnostic(
            phase=phase,
            session_id=self.ctx.session_id,
            prompt=self.ctx.prompt,
            model=self.bot.model_name if self.bot is not None else None,
            messages=self.ctx.ephemeral_messages,
            tools=self.ctx.last_tools,
            error=error,
            extra={
                "loop_count": self.ctx.loop_count,
                "active_edge_tool_names": sorted(self.ctx.active_edge_tool_names),
                "tool_loop_events": self.ctx.tool_loop_events[-80:],
                **(extra or {}),
            },
        )

    def write_loop_diagnostic(self, *, max_tool_loops: int) -> str | None:
        return write_chat_loop_diagnostic(
            session_id=self.ctx.session_id,
            prompt=self.ctx.prompt,
            model=self.bot.model_name if self.bot is not None else None,
            loop_count=self.ctx.loop_count - 1,
            messages=self.ctx.ephemeral_messages,
            tools=self.ctx.last_tools,
            extra={
                "reason": "maximum_tool_execution_iterations",
                "max_tool_loops": max_tool_loops,
                "active_edge_tool_names": sorted(self.ctx.active_edge_tool_names),
                "tool_loop_events": self.ctx.tool_loop_events[-80:],
            },
        )
