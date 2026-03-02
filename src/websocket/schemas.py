"""Pydantic schemas for WebSocket messages."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatMessageIn(BaseModel):
    """Incoming chat message from client."""
    message: str = Field(..., min_length=1, max_length=16_000)


class ChatMessageOut(BaseModel):
    """Outgoing chat message broadcast to room."""
    sender_id: int
    sender_role: str  # user | expert | system
    message: str
    timestamp: str  # ISO
