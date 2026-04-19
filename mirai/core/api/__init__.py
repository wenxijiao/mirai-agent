"""Mirai core HTTP API package.

Heavy logic is split into sub-modules:
- state   — shared mutable state & helpers
- chat    — chat generation loop
- edge    — edge connection lifecycle
- timers  — timer scheduling
- peers   — peer abstractions
- schemas — request/response Pydantic models
- routes  — FastAPI application and route definitions
"""

from mirai.core.api.routes import app, create_app
from mirai.core.api.state import stream_event

__all__ = ["app", "create_app", "stream_event"]
