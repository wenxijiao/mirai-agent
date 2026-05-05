"""Application service for edge peer lifecycle."""

from __future__ import annotations

from mirai.core.runtime import RuntimeState, get_default_runtime


class EdgeService:
    """Handles edge peer registration and messages for one runtime."""

    def __init__(self, runtime: RuntimeState | None = None):
        self.runtime = runtime or get_default_runtime()

    async def handle_peer(self, peer) -> None:
        from mirai.core.api.edge import _handle_edge_peer_impl

        await _handle_edge_peer_impl(peer, runtime=self.runtime)
