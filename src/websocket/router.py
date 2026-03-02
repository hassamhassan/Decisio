"""
Decisio — WebSocket Router for Escalation Chat

Production-ready endpoint with JWT validation, multi-tenant isolation,
message persistence, and heartbeat.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.auth import decode_access_token, TokenData
from src.db.session import get_session
from src.db.models import EscalationSession
from src.services.escalation_service import EscalationService
from src.websocket.manager import ws_manager
from src.websocket.schemas import ChatMessageIn, ChatMessageOut

logger = logging.getLogger(__name__)

router = APIRouter()

# Heartbeat interval (seconds)
HEARTBEAT_INTERVAL = 30.0

# Expert role for presence
EXPERT_USER_TYPES = ("expert", "escalation_owner")


def _is_participant(session: EscalationSession, user: TokenData) -> bool:
    """User is the reporter or the assigned expert."""
    if session.user_id == user.user_id:
        return True
    if session.expert_id == user.user_id:
        return True
    return False


async def _get_session_and_validate(
    company_id: int,
    session_id: str,
    token_data: TokenData,
) -> EscalationSession | None:
    """Load session; validate company and participant. Returns None if invalid."""
    from uuid import UUID

    try:
        sid = UUID(session_id)
    except ValueError:
        return None
    if token_data.company_id is not None and token_data.company_id != company_id:
        return None
    async with get_session() as session:
        svc = EscalationService(session)
        esc = await svc.get_session(sid, company_id)
        if esc is None:
            return None
        if not _is_participant(esc, token_data):
            return None
        return esc


@router.websocket("/ws/chat/{company_id}/{session_id}")
async def escalation_chat(websocket: WebSocket, company_id: int, session_id: str):
    """
    Real-time escalation chat. Query param: token=<JWT>.
    Multi-tenant: company_id and session must match; user must be participant.
    """
    token_str = websocket.query_params.get("token") or websocket.headers.get("Authorization", "").replace("Bearer ", "")
    if not token_str:
        await websocket.close(code=4001, reason="Missing token")
        return

    try:
        token_data = decode_access_token(token_str)
    except Exception:
        await websocket.close(code=4001, reason="Invalid token")
        return

    if token_data.company_id is not None and token_data.company_id != company_id:
        await websocket.close(code=4003, reason="Company mismatch")
        return

    esc = await _get_session_and_validate(company_id, session_id, token_data)
    if esc is None:
        await websocket.close(code=4004, reason="Session not found or access denied")
        return

    session_uuid = esc.id
    is_expert = token_data.user_type in EXPERT_USER_TYPES
    sender_role = "expert" if is_expert else "user"

    await ws_manager.connect(
        company_id=company_id,
        session_id=session_id,
        websocket=websocket,
        is_expert=is_expert,
        user_id=token_data.user_id,
    )

    try:
        heartbeat_task = asyncio.create_task(asyncio.sleep(HEARTBEAT_INTERVAL))
        while True:
            receive_task = asyncio.create_task(websocket.receive_text())
            done, pending = await asyncio.wait(
                [receive_task, heartbeat_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat_task in done:
                heartbeat_task.cancel()
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    break
                heartbeat_task = asyncio.create_task(asyncio.sleep(HEARTBEAT_INTERVAL))
            if receive_task in done:
                heartbeat_task.cancel()
                heartbeat_task = asyncio.create_task(asyncio.sleep(HEARTBEAT_INTERVAL))
                try:
                    text = receive_task.result()
                except Exception:
                    break
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    await websocket.send_text(json.dumps({"error": "Invalid JSON"}))
                    continue

                msg_type = data.get("type", "message")
                if msg_type == "ping":
                    await websocket.send_text(json.dumps({"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()}))
                    continue
                if msg_type == "close":
                    if is_expert or token_data.user_type == "admin":
                        async with get_session() as s:
                            svc = EscalationService(s)
                            await svc.close_session(session_uuid, company_id)
                    await ws_manager.broadcast(company_id, session_id, {
                        "type": "session_closed",
                        "closed_by": token_data.user_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                    break
                if msg_type != "message":
                    continue

                try:
                    parsed = ChatMessageIn(message=data.get("message", "").strip())
                except Exception:
                    await websocket.send_text(json.dumps({"error": "Invalid message schema"}))
                    continue
                if not parsed.message:
                    continue

                async with get_session() as s:
                    svc = EscalationService(s)
                    msg = await svc.add_message(
                        session_id=session_uuid,
                        company_id=company_id,
                        sender_id=token_data.user_id,
                        sender_role=sender_role,
                        message=parsed.message,
                    )
                if msg:
                    out = ChatMessageOut(
                        sender_id=token_data.user_id,
                        sender_role=sender_role,
                        message=parsed.message,
                        timestamp=msg.created_at.isoformat() if msg.created_at else datetime.now(timezone.utc).isoformat(),
                    )
                    await ws_manager.broadcast(company_id, session_id, out.model_dump())
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("Escalation WS error: %s", e, exc_info=True)
    finally:
        await ws_manager.disconnect(
            company_id=company_id,
            session_id=session_id,
            websocket=websocket,
            is_expert=is_expert,
            user_id=token_data.user_id,
        )
