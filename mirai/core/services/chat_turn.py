"""Application service for one Mirai chat turn."""

from __future__ import annotations

from mirai.core.runtime import RuntimeState, get_default_runtime


class ChatTurnService:
    """Thin service boundary around the existing chat loop during migration."""

    def __init__(self, runtime: RuntimeState | None = None):
        self.runtime = runtime or get_default_runtime()

    async def stream_chat_turn(
        self,
        prompt: str,
        session_id: str,
        *,
        think: bool = False,
        timer_callback: bool = False,
    ):
        from mirai.core.api.chat import _generate_chat_events_impl

        async for event in _generate_chat_events_impl(
            prompt,
            session_id,
            think=think,
            timer_callback=timer_callback,
            runtime=self.runtime,
        ):
            yield event
