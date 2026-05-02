from __future__ import annotations

import json
import os
import traceback
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from mirai.logging_config import get_logger

_logger = get_logger(__name__)
_DIAGNOSED_ATTR = "_mirai_provider_failure_diagnostic_path"


def debug_dir() -> str:
    """Return the directory used for provider failure diagnostics."""
    override = (os.getenv("MIRAI_DEBUG_DIR") or "").strip()
    if override:
        return os.path.expanduser(override)
    return os.path.expanduser("~/.mirai/debug")


def short_text(value: Any, limit: int = 500) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[truncated {len(text) - limit} chars]"


def summarize_openai_message(msg: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "role": msg.get("role"),
        "content_type": type(msg.get("content")).__name__,
        "content_preview": short_text(msg.get("content")),
    }
    if msg.get("name"):
        out["name"] = msg.get("name")
    tool_calls = msg.get("tool_calls")
    if isinstance(tool_calls, list):
        out["tool_calls"] = []
        for tc in tool_calls:
            fn = tc.get("function", {}) if isinstance(tc, dict) else {}
            out["tool_calls"].append(
                {
                    "id": tc.get("id") if isinstance(tc, dict) else None,
                    "name": fn.get("name"),
                    "arguments_preview": short_text(fn.get("arguments"), limit=300),
                    "has_thought_signature": bool(
                        isinstance(tc, dict) and (tc.get("thought_signature") or tc.get("thoughtSignature"))
                    ),
                }
            )
    return out


def summarize_tools(tools: list[dict] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tool in tools or []:
        fn = tool.get("function", {}) if isinstance(tool, dict) else {}
        params = fn.get("parameters", {}) if isinstance(fn, dict) else {}
        properties = params.get("properties", {}) if isinstance(params, dict) else {}
        out.append(
            {
                "name": fn.get("name"),
                "description_preview": short_text(fn.get("description"), limit=300),
                "parameter_names": list(properties.keys()) if isinstance(properties, dict) else [],
            }
        )
    return out


def provider_name(provider: Any) -> str:
    name = type(provider).__name__ if provider is not None else "unknown"
    if name.endswith("Provider"):
        name = name[: -len("Provider")]
    return name.lower() or "unknown"


def provider_failure_diagnostic_path(exc: Exception) -> str | None:
    value = getattr(exc, _DIAGNOSED_ATTR, None)
    return value if isinstance(value, str) and value else None


def write_provider_failure_diagnostic(
    *,
    exc: Exception,
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict] | None = None,
    session_id: str | None = None,
    prompt: str | None = None,
    phase: str = "chat_stream",
    extra: dict[str, Any] | None = None,
) -> str | None:
    """Write a compact, redacted request snapshot for provider failures."""
    existing = provider_failure_diagnostic_path(exc)
    if existing:
        return existing

    try:
        directory = debug_dir()
        os.makedirs(directory, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_provider = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in provider or "provider")
        path = os.path.join(directory, f"{safe_provider}_request_failed_{stamp}_{uuid4().hex[:8]}.json")
        payload: dict[str, Any] = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "provider": provider,
            "model": model,
            "phase": phase,
            "session_id": session_id,
            "prompt_preview": short_text(prompt),
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
                "repr": repr(exc),
                "traceback": traceback.format_exception(type(exc), exc, exc.__traceback__),
            },
            "counts": {
                "messages": len(messages),
                "tools": len(tools or []),
            },
            "messages": [summarize_openai_message(m) for m in messages],
            "tools": summarize_tools(tools),
        }
        if extra:
            payload["extra"] = extra
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        try:
            setattr(exc, _DIAGNOSED_ATTR, path)
        except Exception:
            pass
        return path
    except Exception:
        _logger.debug("Failed to write provider request diagnostic", exc_info=True)
        return None
