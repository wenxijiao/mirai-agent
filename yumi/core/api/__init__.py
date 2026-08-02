"""Yumi core HTTP API package.

The implementation is split into:

- ``runtime``     — explicit mutable runtime state and registries
- ``app_factory`` — FastAPI application assembly and lifespan
- ``routers``     — one module per resource group (chat, config, edge, ...)
- ``state``       — module-level facade over the default runtime
- ``schemas``     — request/response Pydantic models

``app`` and ``create_app`` are resolved lazily via PEP 562 ``__getattr__`` so
lightweight core modules can be imported without spinning up the full FastAPI
app or creating an HTTP-layer import cycle.
"""

from typing import TYPE_CHECKING, Any

from yumi.core.platform.runtime.accessors import stream_event

if TYPE_CHECKING:
    from fastapi import FastAPI

    app: "FastAPI"

    def create_app() -> "FastAPI": ...


__all__ = ["app", "create_app", "stream_event"]


def __getattr__(name: str) -> Any:
    if name in ("app", "create_app"):
        from yumi.core.api.app_factory import app, create_app

        return {"app": app, "create_app": create_app}[name]
    raise AttributeError(f"module 'yumi.core.api' has no attribute {name!r}")
