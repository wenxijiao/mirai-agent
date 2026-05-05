"""Application service for timer scheduling and event fanout."""

from __future__ import annotations

from mirai.core.runtime import RuntimeState, get_default_runtime


class TimerService:
    """Schedules and cancels timers against one runtime registry."""

    def __init__(self, runtime: RuntimeState | None = None):
        self.runtime = runtime or get_default_runtime()

    def schedule_timer(self, timer_id: str, delay: int, description: str, session_id: str) -> None:
        from mirai.core.api.timers import _schedule_timer_impl

        _schedule_timer_impl(timer_id, delay, description, session_id, runtime=self.runtime)

    def cancel_timer(self, timer_id: str) -> None:
        from mirai.core.api.timers import _cancel_timer_impl

        _cancel_timer_impl(timer_id, runtime=self.runtime)
