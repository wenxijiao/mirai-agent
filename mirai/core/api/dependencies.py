"""FastAPI dependencies for Mirai API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from mirai.core.plugins import Identity, get_current_identity
from mirai.core.runtime import RuntimeState, get_default_runtime
from mirai.core.services import ChatTurnService, EdgeService, TimerService


def get_runtime(request: Request | None = None) -> RuntimeState:
    """Return the runtime attached to a FastAPI app, falling back to legacy default."""
    if request is not None:
        runtime = getattr(request.app.state, "runtime", None)
        if runtime is not None:
            return runtime
    return get_default_runtime()


def current_identity_dependency() -> Identity:
    return get_current_identity()


CurrentIdentity = Annotated[Identity, Depends(current_identity_dependency)]


def chat_turn_service_dependency(request: Request) -> ChatTurnService:
    return ChatTurnService(get_runtime(request))


def edge_service_dependency(request: Request) -> EdgeService:
    return EdgeService(get_runtime(request))


def timer_service_dependency(request: Request) -> TimerService:
    return TimerService(get_runtime(request))
