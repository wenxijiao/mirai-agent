"""Application service boundary for tool execution.

The detailed local/edge execution logic is still migrated incrementally from
``mirai.core.api.chat``. This class gives new code a stable dependency target.
"""

from __future__ import annotations

from mirai.core.runtime import RuntimeState, get_default_runtime


class ToolExecutionService:
    """Coordinates tool policy and edge registry access for a runtime."""

    def __init__(self, runtime: RuntimeState | None = None):
        self.runtime = runtime or get_default_runtime()
