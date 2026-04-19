"""Structured HTTP error bodies for the Mirai API (FastAPI ``HTTPException`` ``detail`` dicts)."""

from __future__ import annotations

from fastapi import HTTPException
from mirai.core.exceptions import ProviderNotReadyError


def provider_not_ready_http(exc: ProviderNotReadyError) -> HTTPException:
    """Map :class:`ProviderNotReadyError` to an HTTP response with a stable ``code`` field."""
    status = 503 if exc.code == "MIRAI_OLLAMA_UNAVAILABLE" else 400
    return HTTPException(
        status_code=status,
        detail={
            "code": exc.code,
            "message": str(exc),
            "hint": exc.hint,
        },
    )


def unknown_provider_http(*, role: str, name: str, supported: tuple[str, ...]) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "code": "MIRAI_UNKNOWN_PROVIDER",
            "message": f"Unknown {role} provider: {name!r}.",
            "hint": f"Supported: {', '.join(supported)}",
        },
    )


def model_apply_failed_http(*, phase: str, exc: Exception) -> HTTPException:
    """Provider init or model switch failed after config was saved."""
    return HTTPException(
        status_code=502,
        detail={
            "code": "MIRAI_PROVIDER_MODEL_APPLY_FAILED",
            "message": f"Could not apply model configuration ({phase}).",
            "hint": str(exc)[:800],
        },
    )
