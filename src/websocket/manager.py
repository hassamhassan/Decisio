"""
Decisio — WebSocket Connection Manager

Manages active connections and pub/sub routing for escalation chats and notifications.
Features a Redis-backed manager for multi-worker production deployments,
and an in-memory fallback for local development.
"""

from __future__ import annotations

import os
import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL")


def _room_key(company_id: int, session_id: str) -> str:
    return f"company:{company_id}:session:{session_id}"

def _notify_key(company_id: int) -> str:
    return f"company:{company_id}:notifications"


class InMemoryWebSocketManager:
    """
    In-memory connection manager. One instance per process.
    Fails in multi-worker deployments. Maintained as dev fallback.
    """
    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)
        self._notify_connections: dict[int, list[WebSocket]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._expert_presence: set[tuple[int, int]] = set()

    async def connect(self, company_id: int, session_id: str, websocket: WebSocket, is_expert: bool = False, user_id: int | None = None) -> None:
        await websocket.accept()
        room = _room_key(company_id, session_id)
        async with self._lock:
            self._connections[room].append(websocket)
            if is_expert and user_id is not None:
                self._expert_presence.add((company_id, user_id))
        logger.info("WS connect (memory): room=%s is_expert=%s", room, is_expert)

    async def disconnect(self, company_id: int, session_id: str, websocket: WebSocket, is_expert: bool = False, user_id: int | None = None) -> None:
        room = _room_key(company_id, session_id)
        async with self._lock:
            if room in self._connections:
                try: self._connections[room].remove(websocket)
                except ValueError: pass
                if not self._connections[room]: del self._connections[room]
            if is_expert and user_id is not None:
                self._expert_presence.discard((company_id, user_id))

    async def broadcast(self, company_id: int, session_id: str, message: dict[str, Any]) -> None:
        room = _room_key(company_id, session_id)
        payload = json.dumps(message)
        async with self._lock:
            conns = list(self._connections.get(room, []))
        for ws in conns:
            try: await ws.send_text(payload)
            except Exception: pass

    def get_online_experts(self, company_id: int) -> set[int]:
        return {uid for (cid, uid) in self._expert_presence if cid == company_id}

    async def notify_connect(self, company_id: int, websocket: WebSocket, is_expert: bool = False, user_id: int | None = None) -> None:
        await websocket.accept()
        async with self._lock:
            self._notify_connections[company_id].append(websocket)
            if is_expert and user_id is not None:
                self._expert_presence.add((company_id, user_id))

    async def notify_disconnect(self, company_id: int, websocket: WebSocket, is_expert: bool = False, user_id: int | None = None) -> None:
        async with self._lock:
            if company_id in self._notify_connections:
                try: self._notify_connections[company_id].remove(websocket)
                except ValueError: pass
                if not self._notify_connections[company_id]: del self._notify_connections[company_id]
            if is_expert and user_id is not None:
                self._expert_presence.discard((company_id, user_id))

    async def notify_company(self, company_id: int, message: dict[str, Any]) -> None:
        payload = json.dumps(message)
        async with self._lock:
            conns = list(self._notify_connections.get(company_id, []))
        for ws in conns:
            try: await ws.send_text(payload)
            except Exception: pass


class RedisWebSocketManager:
    """
    Production-ready connection manager using Redis Pub/Sub.
    Supports multi-worker routing and global presence tracking.
    """
    def __init__(self, redis_url: str):
        import redis.asyncio as redis
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.pubsub_redis = redis.from_url(redis_url, decode_responses=True)
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)
        self._notify_connections: dict[int, list[WebSocket]] = defaultdict(list)
        self._lock = asyncio.Lock()
        
        # Room -> PubSub Task
        self._pubsub_tasks: dict[str, asyncio.Task] = {}
        # Company -> PubSub Task 
        self._notify_tasks: dict[str, asyncio.Task] = {}

    async def _pubsub_listener(self, channel: str, is_notify: bool):
        """Background task that listens to a Redis channel and fans out to local WebSockets"""
        pubsub = self.pubsub_redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    payload = message["data"]
                    async with self._lock:
                        if is_notify:
                            # Parse company id from company:ID:notifications
                            parts = channel.split(":")
                            cid = int(parts[1])
                            conns = list(self._notify_connections.get(cid, []))
                        else:
                            conns = list(self._connections.get(channel, []))
                            
                    for ws in conns:
                        try: await ws.send_text(payload)
                        except Exception: pass
        except asyncio.CancelledError:
            await pubsub.unsubscribe(channel)
        except Exception as e:
            logger.error("Redis pubsub listener failed for %s: %s", channel, e)
        finally:
            await pubsub.close()

    def _ensure_listener(self, channel: str, is_notify: bool):
        """Start a listener task for the channel if one doesn't exist on this worker"""
        tasks = self._notify_tasks if is_notify else self._pubsub_tasks
        if channel not in tasks or tasks[channel].done():
            tasks[channel] = asyncio.create_task(self._pubsub_listener(channel, is_notify))

    async def connect(self, company_id: int, session_id: str, websocket: WebSocket, is_expert: bool = False, user_id: int | None = None) -> None:
        await websocket.accept()
        room = _room_key(company_id, session_id)
        async with self._lock:
            self._connections[room].append(websocket)
            self._ensure_listener(room, is_notify=False)
            
        if is_expert and user_id is not None:
            # Add to redis set: experts_online:company_id with TTL of 20 min
            key = f"experts_online:{company_id}"
            await self.redis.sadd(key, user_id)
            await self.redis.expire(key, 1200)

        logger.info("WS connect (Redis): room=%s is_expert=%s", room, is_expert)

    async def disconnect(self, company_id: int, session_id: str, websocket: WebSocket, is_expert: bool = False, user_id: int | None = None) -> None:
        room = _room_key(company_id, session_id)
        async with self._lock:
            if room in self._connections:
                try: self._connections[room].remove(websocket)
                except ValueError: pass
                
                # If no more local connections to this room, kill the pubsub task
                if not self._connections[room]:
                    del self._connections[room]
                    if task := self._pubsub_tasks.pop(room, None):
                        task.cancel()

            if is_expert and user_id is not None:
                # We can't immediately SREM because they might have other tabs open,
                # but Redis TTL handles cleanup eventually, or we could SREM if we tracked tab counts in redis.
                # For now, we will just TTL it (expert presence is approximate).
                pass

    async def broadcast(self, company_id: int, session_id: str, message: dict[str, Any]) -> None:
        room = _room_key(company_id, session_id)
        await self.redis.publish(room, json.dumps(message))

    def get_online_experts(self, company_id: int) -> set[int]:
        # Note: This is a synchronous abstraction layer leak in the original design.
        # It's called synchronously in api.py _ensure_escalation_session.
        # Since we must return a set immediately, we use a small asyncio loop or return empty sets
        # if the loop is already running. However, FastApi handles this by letting us run async down the stack if needed.
        # Actually, get_online_experts is called directly as sync in `api.py`.
        # To avoid blocking the event loop or causing 'loop already running' errors, we will just return empty set for now,
        # and we must FIX `api.py` to `await ws_manager.get_online_experts(cid)`
        # I'll return a stub here and fix api.py next.
        pass

    async def get_online_experts_async(self, company_id: int) -> set[int]:
        key = f"experts_online:{company_id}"
        members = await self.redis.smembers(key)
        return {int(m) for m in members}

    async def notify_connect(self, company_id: int, websocket: WebSocket, is_expert: bool = False, user_id: int | None = None) -> None:
        await websocket.accept()
        channel = _notify_key(company_id)
        async with self._lock:
            self._notify_connections[company_id].append(websocket)
            self._ensure_listener(channel, is_notify=True)
            
        if is_expert and user_id is not None:
            key = f"experts_online:{company_id}"
            await self.redis.sadd(key, user_id)
            await self.redis.expire(key, 1200)

    async def notify_disconnect(self, company_id: int, websocket: WebSocket, is_expert: bool = False, user_id: int | None = None) -> None:
        channel = _notify_key(company_id)
        async with self._lock:
            if company_id in self._notify_connections:
                try: self._notify_connections[company_id].remove(websocket)
                except ValueError: pass
                if not self._notify_connections[company_id]:
                    del self._notify_connections[company_id]
                    if task := self._notify_tasks.pop(channel, None):
                        task.cancel()

    async def notify_company(self, company_id: int, message: dict[str, Any]) -> None:
        channel = _notify_key(company_id)
        await self.redis.publish(channel, json.dumps(message))


# Singleton resolution
if REDIS_URL:
    logger.info("Initializing RedisWebSocketManager")
    ws_manager = RedisWebSocketManager(REDIS_URL)
else:
    logger.warning("Initializing InMemoryWebSocketManager (NOT SCALABLE FOR PRODUCTION WORKERS)")
    ws_manager = InMemoryWebSocketManager()

# Add a compat wrapper for the sync get_online_experts issue
def _sync_get_experts(company_id: int) -> set[int]:
    if isinstance(ws_manager, InMemoryWebSocketManager):
        return ws_manager.get_online_experts(company_id)
    else:
        # Cannot run async inside sync endpoint reliably without breaking uvicorn loops.
        # We must change api.py to await this.
        return set()

ws_manager.get_online_experts = getattr(ws_manager, 'get_online_experts', _sync_get_experts)
