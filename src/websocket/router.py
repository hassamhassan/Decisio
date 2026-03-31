"""
Decisio — WebSocket Router for Escalation Chat

Production-ready endpoint with JWT validation, multi-tenant isolation,
message persistence, and heartbeat.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.auth import decode_access_token, TokenData, is_escalation_type
from src.db.session import get_session
from src.db.models import EscalationSession, EscalationSessionStatus
from src.services.escalation_service import EscalationService
from src.websocket.manager import ws_manager
from src.websocket.schemas import ChatMessageIn, ChatMessageOut
from src.sanitize import sanitize_user_input

logger = logging.getLogger(__name__)

router = APIRouter()

# Heartbeat interval (seconds)
HEARTBEAT_INTERVAL = 30.0



def _is_expert_user(user: TokenData) -> bool:
    return is_escalation_type(user.user_type) or user.user_type == "admin"


def _parse_user_level(user_type: str) -> int | None:
    """Extract integer from user_type like 'L1'."""
    if not user_type:
        return None
    m = re.match(r"^L(\d+)$", user_type.strip())
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


async def _get_session_and_validate(
    company_id: int,
    session_id: str,
    token_data: TokenData,
) -> EscalationSession | None:
    """
    Load session and validate access:
    - Reporter (user_id match) always allowed.
    - Experts with the same company can join ANY open session (first-come-first-served).
      The first expert to connect gets auto-assigned; a second expert is rejected
      unless they are the already-assigned expert_id.
    Returns None if the user must not be admitted.
    """
    from uuid import UUID

    try:
        sid = UUID(session_id)
    except ValueError:
        return None
    if token_data.company_id is not None and token_data.company_id != company_id:
        return None
    async with get_session() as db_session:
        svc = EscalationService(db_session)
        esc = await svc.get_session(sid, company_id)
        if esc is None:
            return None

        # Original reporter always admitted
        if esc.user_id == token_data.user_id:
            return esc

        # Expert path: allow any expert in the same company
        if _is_expert_user(token_data):
            was_unassigned = esc.expert_id is None and esc.status == EscalationSessionStatus.WAITING

            # Level-specific routing: only L{required_level} can claim.
            # If required_level is NULL (older sessions), allow any escalation expert.
            if token_data.user_type != "admin" and esc.required_level is not None:
                user_level = _parse_user_level(token_data.user_type)
                if user_level is None or user_level != esc.required_level:
                    return None

            # Claim the session (assigns expert_id if unset, or confirms existing assignment)
            claimed = await svc.claim_session(sid, company_id, token_data.user_id)
            # Notify other experts instantly so the first accept "wins"
            # and the others see the status change (waiting -> active).
            if claimed is not None and was_unassigned:
                try:
                    await ws_manager.notify_company(company_id, {
                        "type": "session_claimed",
                        "session_id": str(sid),
                        "company_id": company_id,
                        "expert_id": token_data.user_id,
                        "required_level": esc.required_level,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                except Exception as e:
                    logger.warning("Failed to broadcast session_claimed event: %s", e, exc_info=True)
            return claimed  # None if a different expert already claimed it

        return None  # All other roles denied


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
    except Exception as e:
        logger.warning("WebSocket token decoding failed: %s", e, exc_info=True)
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
    is_expert = is_escalation_type(token_data.user_type)
    is_admin = token_data.user_type == "admin"
    # EC8: Admin gets "admin" role, escalation-level users get "expert", others get "user"
    sender_role = "admin" if is_admin else ("expert" if is_expert else "user")

    await ws_manager.connect(
        company_id=company_id,
        session_id=session_id,
        websocket=websocket,
        is_expert=is_expert or is_admin,  # track admin presence too
        user_id=token_data.user_id,
    )

    # Notify everyone in the room that the expert has joined
    if is_expert:
        await ws_manager.broadcast(company_id, session_id, {
            "type": "expert_joined",
            "expert_id": token_data.user_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    try:
        heartbeat_task = asyncio.create_task(asyncio.sleep(HEARTBEAT_INTERVAL))
        receive_task = asyncio.create_task(websocket.receive_text())
        while True:
            done, pending = await asyncio.wait(
                [receive_task, heartbeat_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat_task in done:
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                except Exception as e:
                    logger.debug("Failed to send ping: %s", e)
                    break
                heartbeat_task = asyncio.create_task(asyncio.sleep(HEARTBEAT_INTERVAL))
            if receive_task in done:
                try:
                    text = receive_task.result()
                except Exception as e:
                    logger.debug("Failed to receive from websocket: %s", e)
                    break
                
                # Setup next receive_task IMMEDIATELY so we don't forget it
                receive_task = asyncio.create_task(websocket.receive_text())
                
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

                sanitized_msg = sanitize_user_input(parsed.message, max_length=16_000)
                if not sanitized_msg:
                    continue

                async with get_session() as s:
                    svc = EscalationService(s)
                    msg = await svc.add_message(
                        session_id=session_uuid,
                        company_id=company_id,
                        sender_id=token_data.user_id,
                        sender_role=sender_role,
                        message=sanitized_msg,
                    )
                if msg:
                    try:
                        await websocket.send_text(json.dumps({
                            "id": str(msg.id),
                            "session_id": str(msg.session_id),
                            "sender": msg.sender_id, # Corrected from msg.sender
                            "content": msg.message, # Corrected from msg.content
                            "created_at": msg.created_at.isoformat(),
                        }))
                    except Exception as e:
                        logger.debug("Failed to echo message back to sender: %s", e)
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
        # Cancel dangling tasks to prevent InvalidState errors and task leaks
        if heartbeat_task and not heartbeat_task.done():
            heartbeat_task.cancel()
        if receive_task and not receive_task.done():
            receive_task.cancel()

        await ws_manager.disconnect(
            company_id=company_id,
            session_id=session_id,
            websocket=websocket,
            is_expert=is_expert,
            user_id=token_data.user_id,
        )


# ── Company-wide notification channel ──────────────────────────────


@router.websocket("/ws/notifications/{company_id}")
async def escalation_notifications(websocket: WebSocket, company_id: int):
    """
    Company-wide notification feed for experts / admins.
    Pushes real-time events like new_escalation so the Expert Console
    doesn't need to poll.
    Query param: token=<JWT>
    """
    token_str = (
        websocket.query_params.get("token")
        or websocket.headers.get("Authorization", "").replace("Bearer ", "")
    )
    if not token_str:
        await websocket.close(code=4001, reason="Missing token")
        return
    try:
        token_data = decode_access_token(token_str)
    except Exception as e:
        logger.warning("WebSocket token decoding failed for notification router: %s", e, exc_info=True)
        await websocket.close(code=4001, reason="Invalid token")
        return

    # Only experts / admins may subscribe
    if not is_escalation_type(token_data.user_type) and token_data.user_type != "admin":
        await websocket.close(code=4003, reason="Not authorized for notifications")
        return

    if token_data.company_id is not None and token_data.company_id != company_id:
        await websocket.close(code=4003, reason="Company mismatch")
        return

    # EC9: track expert presence on notification channel
    _is_expert = is_escalation_type(token_data.user_type)
    await ws_manager.notify_connect(
        company_id, websocket,
        is_expert=_is_expert, user_id=token_data.user_id,
    )

    heartbeat_task = None
    receive_task = None
    try:
        heartbeat_task = asyncio.create_task(asyncio.sleep(HEARTBEAT_INTERVAL))
        receive_task = asyncio.create_task(websocket.receive_text())
        while True:
            done, _pending = await asyncio.wait(
                [receive_task, heartbeat_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat_task in done:
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                except Exception as e:
                    logger.debug("Failed to send notification ping: %s", e)
                    break
                heartbeat_task = asyncio.create_task(asyncio.sleep(HEARTBEAT_INTERVAL))
            if receive_task in done:
                try:
                    text = receive_task.result()
                except Exception as e:
                    logger.debug("Failed to receive from notification websocket: %s", e)
                    break
                
                # Setup next receive_task
                receive_task = asyncio.create_task(websocket.receive_text())
                
                # Only handle pong / ping from client
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "ping":
                    await websocket.send_text(
                        json.dumps({"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()})
                    )
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("Notification WS error: %s", e, exc_info=True)
    finally:
        if heartbeat_task and not heartbeat_task.done():
            heartbeat_task.cancel()
        if receive_task and not receive_task.done():
            receive_task.cancel()
            
        await ws_manager.notify_disconnect(
            company_id, websocket,
            is_expert=_is_expert, user_id=token_data.user_id,
        )
