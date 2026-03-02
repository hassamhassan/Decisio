"""
Unit tests for EscalationService: create_session, assign_available_expert.
Uses async pytest and a test DB or mocks; structured for production quality.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.escalation_service import EscalationService
from src.db.models import EscalationSession, EscalationSessionStatus, User


@pytest.mark.asyncio
async def test_create_session_returns_session_with_company_and_user():
    """Create session stores company_id and user_id and returns session."""
    # Use a mock or test fixture that provides an AsyncSession with committed data
    from unittest.mock import AsyncMock, MagicMock
    session = AsyncMock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.add = MagicMock()

    svc = EscalationService(session)
    esc = await svc.create_session(company_id=1, user_id=10)

    assert esc is not None
    assert esc.company_id == 1
    assert esc.user_id == 10
    assert esc.expert_id is None
    assert esc.status == EscalationSessionStatus.WAITING
    assert esc.id is not None
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_assign_available_expert_with_no_expert_leaves_waiting():
    """When no expert is available, assign_available_expert returns None and session stays waiting."""
    from unittest.mock import AsyncMock, MagicMock
    session = AsyncMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=None)
    session.flush = AsyncMock()

    svc = EscalationService(session)
    sid = uuid.uuid4()
    result = await svc.assign_available_expert(company_id=1, session_id=sid, online_expert_ids=set())

    assert result is None


@pytest.mark.asyncio
async def test_assign_available_expert_with_online_expert_assigns():
    """When online_expert_ids provided, first expert is assigned."""
    from unittest.mock import AsyncMock, MagicMock
    esc = EscalationSession(
        id=uuid.uuid4(),
        company_id=1,
        user_id=10,
        expert_id=None,
        status=EscalationSessionStatus.WAITING,
    )
    session = AsyncMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=esc)
    session.flush = AsyncMock()

    svc = EscalationService(session)
    result = await svc.assign_available_expert(
        company_id=1,
        session_id=esc.id,
        online_expert_ids={100},
    )

    assert result == 100
    assert esc.expert_id == 100
    assert esc.status == EscalationSessionStatus.ACTIVE


@pytest.mark.asyncio
async def test_get_session_wrong_company_returns_none():
    """get_session returns None when session belongs to another company."""
    from unittest.mock import AsyncMock
    esc = EscalationSession(
        id=uuid.uuid4(),
        company_id=1,
        user_id=10,
        expert_id=None,
        status=EscalationSessionStatus.WAITING,
    )
    session = AsyncMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=esc)

    svc = EscalationService(session)
    result = await svc.get_session(esc.id, company_id=2)
    assert result is None

    result_same = await svc.get_session(esc.id, company_id=1)
    assert result_same is esc
