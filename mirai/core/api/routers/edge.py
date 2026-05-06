"""Edge websocket routes."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket
from mirai.core.api.edge import handle_edge_peer
from mirai.core.api.peers import LocalEdgePeer

router = APIRouter()


@router.websocket("/ws/edge")
async def websocket_edge_endpoint(websocket: WebSocket):
    await websocket.accept()
    peer = LocalEdgePeer(websocket)
    await handle_edge_peer(peer)
