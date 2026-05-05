"""Mirai core HTTP API package.

Heavy logic is split into sub-modules:
- runtime     — explicit mutable runtime state and registries
- services    — application use-case boundaries
- app_factory — FastAPI application assembly
- routes      — compatibility alias for the app factory
- state       — legacy facade over the default runtime
- schemas     — request/response Pydantic models
"""

from mirai.core.api.routes import app, create_app
from mirai.core.api.state import stream_event

__all__ = ["app", "create_app", "stream_event"]
