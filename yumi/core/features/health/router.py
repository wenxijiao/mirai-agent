"""Health routes."""

from __future__ import annotations

from functools import cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version

import yumi.core.platform.runtime.accessors as _state
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from yumi.core.platform.http.dependencies import CurrentIdentity

router = APIRouter()

# The layers that may be installed alongside this one. Each is optional:
# yumi-agent runs on its own, and the platform above it is not always present.
_LAYERS = ("yumi-agent", "yumi-enterprise", "yumi-nexus")


@cache
def installed_versions() -> dict[str, str]:
    """What is actually installed, read from package metadata.

    A version declared in a source file describes the working copy; this
    describes the artefact that is running, which is the question worth being
    able to answer about a deployment. Cached because the answer cannot change
    without the process restarting.
    """
    found: dict[str, str] = {}
    for name in _LAYERS:
        try:
            found[name] = _installed_version(name)
        except PackageNotFoundError:
            continue
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
