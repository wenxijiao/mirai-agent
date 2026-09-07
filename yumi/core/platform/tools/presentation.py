"""Deterministic, side-effect-free descriptions of the arguments being approved."""

from __future__ import annotations

import json
import re
from string import Formatter


def render_action_summary(template, arguments, parameters=None, *, locale="en") -> str | None:
    if isinstance(template, dict):
        template = template.get(locale) or template.get("en") or next(iter(template.values()), None)
    if not isinstance(template, str) or not template.strip() or len(template) > 1000:
        return None
    from yumi.core.platform.tools.trace import _redact_sensitive

    values = {
        name: prop["default"]
        for name, prop in (parameters or {}).get("properties", {}).items()
        if isinstance(prop, dict) and "default" in prop
    }
    values.update(arguments)
    values = _redact_sensitive(values)
    parts = []
    try:
        for literal, key, spec, conversion in Formatter().parse(template):
            parts.append(literal)
            if key is None:
                continue
            if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", key) or spec or conversion or key not in values:
                return None
            value = values[key]
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            text = re.sub(r"[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]", " ", text)
            if len(text) > 240:
                return None  # Show full parameters instead of a misleading truncated action.
            parts.append(text)
        result = "".join(parts).strip()
        return result if result and len(result) <= 600 else None
    except (ValueError, TypeError):
        return None


def action_for_invocation(invocation, runtime, *, locale="en") -> str | None:
    from yumi.core.platform.tools.tool import TOOL_REGISTRY

    if invocation.kind == "edge":
        entry = runtime.edge_registry.tools.get(invocation.target_edge, {}).get(invocation.func_name, {})
    else:
        entry = TOOL_REGISTRY.get(invocation.func_name, {})
    schema = entry.get("schema", {})
    return render_action_summary(
        entry.get("confirmation_template") or schema.get("confirmation_template"),
        invocation.args,
        schema.get("function", {}).get("parameters", {}),
        locale=locale,
    )
