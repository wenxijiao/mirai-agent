"""Health routes."""

from __future__ import annotations

from functools import cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version

import yumi.core.platform.runtime.accessors as _state
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from yumi.core.platform.http.dependencies import CurrentIdentity
from yumi.core.platform.plugins.discovery import _iter_entry_points

router = APIRouter()

_SELF = "yumi-agent"


@cache
def installed_versions() -> dict[str, str]:
    """This package's version, plus that of anything registered above it.

    A version declared in a source file describes the working copy; this
    describes the artefact that is running, which is the question worth being
    able to answer about a deployment.

    The packages above are found by asking which distributions provide a
    ``yumi.plugins`` entry point, never by naming them — this layer does not
    know what is installed on top of it, and a boundary test enforces that.
    Cached because the answer cannot change without the process restarting.
    """
    found: dict[str, str] = {}
    try:
        found[_SELF] = _installed_version(_SELF)
    except PackageNotFoundError:
        pass

    for ep in _iter_entry_points():
        dist = getattr(ep, "dist", None)
        if dist is None or not dist.name or dist.name in found:
            continue
        found[dist.name] = dist.version
    return found


@router.get("/health")
async def health_check(identity: CurrentIdentity):
    if getattr(_state, "server_draining", False):
        return JSONResponse(
            {"status": "draining", "message": "Server is shutting down"},
            status_code=503,
        )
    return {
        "status": "ok",
        "identity_user_id": identity.user_id,
        "versions": installed_versions(),
    }
