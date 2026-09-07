"""Warm reusable tool vectors after registration, away from chat requests."""

import asyncio

from yumi.logging_config import get_logger

logger = get_logger(__name__)
_TASKS: set[asyncio.Task] = set()


def schedule_tool_index(connection_key: str, registry: dict) -> None:
    from yumi.core.platform.tools.routing import get_embed_provider, load_model_config

    if len(_TASKS) >= 2 or get_embed_provider() is None:
        return
    model = load_model_config().embedding_model
    if not model:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def run():
        try:
            await asyncio.to_thread(_warm, connection_key, registry, model)
        except Exception:
            logger.debug("Tool index warm-up skipped", exc_info=True)

    task = loop.create_task(run(), name="yumi-tool-index")
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def _warm(connection_key: str, registry: dict, model: str) -> None:
    from yumi.core.platform.tools.routing import (
        ToolCatalogEntry,
        _cached_embedding,
        _edge_aliases,
        _edge_display_name,
        _parameter_text,
        _tool_description,
    )

    device = _edge_display_name(connection_key)
    for name, raw in registry.items():
        schema = raw.get("schema") or {}
        entry = ToolCatalogEntry(
            name=name,
            kind="edge",
            schema=schema,
            description=_tool_description(schema),
            parameters_text=_parameter_text(schema),
            namespace=f"device:{device}",
            edge_key=connection_key,
            device_name=device,
            device_aliases=_edge_aliases(connection_key, name),
        )
        # Cache only metadata vectors. Search still builds a fresh, scoped catalog.
        _cached_embedding(model, entry.search_text, persistent=True)
        _cached_embedding(model, entry.device_text, persistent=True)
