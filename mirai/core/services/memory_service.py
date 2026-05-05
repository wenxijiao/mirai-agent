"""Application service placeholder for memory use cases."""

from __future__ import annotations

from mirai.core.runtime import RuntimeState, get_default_runtime


class MemoryService:
    def __init__(self, runtime: RuntimeState | None = None):
        self.runtime = runtime or get_default_runtime()
