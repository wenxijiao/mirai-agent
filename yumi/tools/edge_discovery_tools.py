"""Find visible core/app/device functions and activate only the relevant matches."""

from __future__ import annotations

import json

from yumi.core.platform.plugins import get_current_identity
from yumi.core.platform.runtime import get_default_runtime
from yumi.core.platform.tools.routing import activate_edge_for_session, search_edge_tools
from yumi.logging_config import get_logger

logger = get_logger(__name__)


def discover_app_tools(need: str, session_id: str = "default") -> str:
    """Find visible core/app/device tools and make matching functions available.

    Args:
        need: What you're trying to do, in natural language.
        session_id: Leave default; the server stamps the current session.
    """
    from yumi.core.platform.runtime.assistant_context import conversation_session

    session_id = conversation_session.get() or session_id
    need = (need or "").strip()
    if not need:
        return json.dumps({"ok": False, "error": "need is required"})

    runtime = get_default_runtime()
    matches = search_edge_tools(
        need,
        identity=get_current_identity(),
        disabled_tools=runtime.tool_policy.disabled_tools,
        edge_registry=runtime.edge_registry.tools,
        limit=6,
        include_core=True,
    )
    if not matches:
        return json.dumps(
            {
                "ok": True,
                "matches": [],
                "note": "no available tool matches this need — answer directly or tell the user",
            }
        )

    from yumi.core.features.config import load_model_config
    from yumi.core.platform.providers.budget import fit_tool_schemas
    from yumi.core.platform.runtime.tool_catalog import model_visible_tool_schema
    from yumi.core.platform.tools.routing import ToolCatalog

    catalog = ToolCatalog(
        identity=get_current_identity(),
        disabled_tools=runtime.tool_policy.disabled_tools,
        edge_registry=runtime.edge_registry.tools,
    )
    visible = {entry.name: entry for entry in catalog.core_tools() + catalog.edge_tools()}
    names = [m["name"] for m in matches]
    candidates = [
        model_visible_tool_schema(visible[n].schema)
        for n in dict.fromkeys(["discover_app_tools", *names])
        if n in visible
    ]
    admitted = {
        s["function"]["name"]
        for s in fit_tool_schemas(candidates, budget=load_model_config().tool_schema_token_budget, priority_names=names)
    }
    matches = [m for m in matches if m["name"] in admitted]
    if not matches:
        return json.dumps(
            {
                "ok": True,
                "matches": [],
                "note": "Matching functions exceed the tool schema budget; narrow the search or ask the operator to adjust it.",
            }
        )

    # Activate only the matched functions. Edge activation remains useful to
    # legacy sticky mode, but never broadens disclosure beyond visible matches.
    activated_tool_names = [m["name"] for m in matches[:6]]
    for edge_key in {m.get("edge_key") for m in matches[:6] if m.get("edge_key")}:
        activate_edge_for_session(session_id, edge_key)

    return json.dumps(
        {
            "ok": True,
            "matches": [
                {k: m[k] for k in ("name", "description", "device") if m.get(k) is not None} for m in matches[:8]
            ],
            "activated_device": matches[0].get("device") or "",
            "activated_tool_names": activated_tool_names,
            "note": "the listed activated functions are available now; use only those needed for the task",
        },
        ensure_ascii=False,
    )
