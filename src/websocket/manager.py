"""
Decisio — WebSocket Connection Manager

In-memory room-based manager for escalation chat.
Tracks active connections and expert presence for auto-assignment.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


def _room_key(company_id: int, session_id: str) -> str:
    return f"company_{company_id}_session_{session_id}"


class WebSocketManager:
    """
    In-memory connection manager. One instance per process.
    active_connections: room_key -> list of WebSocket
    expert_presence: (company_id, user_id) set for experts currently connected to any WS.
    """

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._expert_presence: set[tuple[int, int]] = set()

    async def connect(
        self,
        company_id: int,
        session_id: str,
        websocket: WebSocket,
        is_expert: bool = False,
        user_id: int | None = None,
    ) -> None:
        """Accept and register a connection in the room."""
        await websocket.accept()
        room = _room_key(company_id, session_id)
        async with self._lock:
            self._connections[room].append(websocket)
            if is_expert and user_id is not None:
                self._expert_presence.add((company_id, user_id))
        logger.info("WS connect: room=%s is_expert=%s", room, is_expert)

    async def disconnect(
        self,
        company_id: int,
        session_id: str,
        websocket: WebSocket,
        is_expert: bool = False,
        user_id: int | None = None,
    ) -> None:
        """Remove connection from room and expert presence if applicable."""
        room = _room_key(company_id, session_id)
        async with self._lock:
            if room in self._connections:
                try:
                    self._connections[room].remove(websocket)
                except ValueError:
                    pass
                if not self._connections[room]:
                    del self._connections[room]
            if is_expert and user_id is not None:
                self._expert_presence.discard((company_id, user_id))
        logger.info("WS disconnect: room=%s", room)

    async def broadcast(
        self,
        company_id: int,
        session_id: str,
        message: dict[str, Any],
    ) -> None:
        """Send message to all connections in the room. Skips closed connections."""
        room = _room_key(company_id, session_id)
        payload = json.dumps(message)
        async with self._lock:
            conns = list(self._connections.get(room, []))
        for ws in conns:
            try:
                await ws.send_text(payload)
            except Exception as e:
                logger.debug("broadcast send failed: %s", e)

    def get_online_experts(self, company_id: int) -> set[int]:
        """Return set of user_ids that are experts and currently connected (any room for this company)."""
        return {uid for (cid, uid) in self._expert_presence if cid == company_id}


# Singleton for the app
ws_manager = WebSocketManager()
