"""Runtime construction helpers."""

from __future__ import annotations

from mirai.core.runtime.state import RuntimeState


def build_runtime() -> RuntimeState:
    """Create an isolated Mirai runtime context."""
    return RuntimeState()
