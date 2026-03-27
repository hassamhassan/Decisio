"""
Decisio — Escalation Session Service

Production-ready service for creating escalation sessions,
assigning experts, and multi-tenant isolation.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import (
    EscalationSession,
    EscalationSessionStatus,
    EscalationMessage,
    EscalationMessageSenderRole,
    User,
)
from src.tracing import emit_trace

from sqlalchemy import or_ as sa_or
from src.auth import is_escalation_type, _LEGACY_ESCALATION_TYPES

logger = logging.getLogger(__name__)


class EscalationService:
    """
    Service layer for escalation chat sessions.
    All operations are company-scoped (multi-tenant).
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_session(
        self,
        company_id: int,
        user_id: int,
    ) -> EscalationSession:
        """
        Create a new escalation session for the given company and user.
        Caller must ensure company_id and user_id belong to the same tenant.
        """
        session_id = uuid.uuid4()
        esc = EscalationSession(
            id=session_id,
            company_id=company_id,
            user_id=user_id,
            expert_id=None,
            status=EscalationSessionStatus.WAITING,
        )
        self.session.add(esc)
        await self.session.flush()
        emit_trace("escalation.created", {
            "session_id": str(esc.id),
            "company_id": company_id,
            "user_id": user_id,
        })
        logger.info("Escalation session created: session_id=%s company_id=%s", esc.id, company_id)
        return esc

    async def assign_available_expert(
        self,
        company_id: int,
        session_id: uuid.UUID,
        online_expert_ids: set[int] | None = None,
    ) -> Optional[int]:
        """
        Try to assign an available expert to the session.
        If online_expert_ids is provided (from WebSocketManager), only those experts are considered.
        Otherwise queries DB for users with expert role in the company (is_active).
        Returns expert_id if assigned, else None.
        """
        esc = await self.session.get(EscalationSession, session_id)
        if not esc or esc.company_id != company_id:
            return None
        if esc.expert_id is not None:
            return esc.expert_id

        if online_expert_ids is not None:
            # Prefer online experts
            candidate_ids = list(online_expert_ids)
        else:
            candidate_ids = []

        if not candidate_ids:
            # Fallback: any expert role user in company
            result = await self.session.execute(
                sa_select(User.id).where(
                    User.company_id == company_id,
                    User.is_active.is_(True),
                    sa_or(
                        User.user_type.like("L%"),
                        User.user_type.in_(list(_LEGACY_ESCALATION_TYPES)),
                    ),
                ).limit(1)
            )
            expert_id_val = result.scalar_one_or_none()
            if expert_id_val is not None:
                candidate_ids = [expert_id_val]

        if not candidate_ids:
            logger.info("No available expert for company_id=%s", company_id)
            return None

        expert_id = candidate_ids[0]
        esc.expert_id = expert_id
        esc.status = EscalationSessionStatus.ACTIVE
        await self.session.flush()
        emit_trace("escalation.expert_assigned", {
            "session_id": str(session_id),
            "company_id": company_id,
            "expert_id": expert_id,
        })
        logger.info("Expert assigned: session_id=%s expert_id=%s", session_id, expert_id)
        return expert_id

    async def claim_session(
        self,
        session_id: uuid.UUID,
        company_id: int,
        expert_id: int,
    ) -> EscalationSession | None:
        """
        Let an expert claim an unassigned session (first-come-first-served).
        If the session already has a different expert_id, do nothing and return as-is.
        Returns the session if the expert is now the assigned expert, else None.
        """
        esc = await self.get_session(session_id, company_id)
        if not esc:
            return None
        if esc.expert_id is None:
            esc.expert_id = expert_id
            esc.status = EscalationSessionStatus.ACTIVE
            await self.session.flush()
            emit_trace("escalation.expert_claimed", {
                "session_id": str(session_id),
                "company_id": company_id,
                "expert_id": expert_id,
            })
            logger.info("Expert claimed session: session_id=%s expert_id=%s", session_id, expert_id)
        # Allow only the assigned expert to proceed
        if esc.expert_id != expert_id:
            return None
        return esc

    async def get_session(
        self,
        session_id: uuid.UUID,
        company_id: int,
    ) -> EscalationSession | None:
        """Load session by id; must belong to company (tenant isolation)."""
        esc = await self.session.get(EscalationSession, session_id)
        if esc is None or esc.company_id != company_id:
            return None
        return esc

    async def close_session(
        self,
        session_id: uuid.UUID,
        company_id: int,
    ) -> bool:
        """Set session status to closed and closed_at. Returns True if updated."""
        esc = await self.get_session(session_id, company_id)
        if not esc or esc.status == EscalationSessionStatus.CLOSED:
            return False
        esc.status = EscalationSessionStatus.CLOSED
        esc.closed_at = datetime.now(timezone.utc)
        await self.session.flush()
        # Message count and duration can be computed from DB if needed
        emit_trace("escalation.closed", {
            "session_id": str(session_id),
            "company_id": company_id,
            "closed_at": esc.closed_at.isoformat(),
        })
        return True

    async def add_message(
        self,
        session_id: uuid.UUID,
        company_id: int,
        sender_id: int,
        sender_role: str,
        message: str,
    ) -> EscalationMessage | None:
        """Persist a chat message. Returns the created message or None if session invalid."""
        esc = await self.get_session(session_id, company_id)
        if not esc:
            return None
        msg = EscalationMessage(
            session_id=session_id,
            company_id=company_id,
            sender_id=sender_id,
            sender_role=sender_role,
            message=message,
        )
        self.session.add(msg)
        await self.session.flush()
        emit_trace("escalation.message_sent", {
            "session_id": str(session_id),
            "message_id": str(msg.id),
            "sender_role": sender_role,
        })
        return msg
