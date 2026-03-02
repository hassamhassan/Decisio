"""
Decisio — CRUD Operations

Database read/write operations for incidents.
Converts between LangGraph state dicts and SQLAlchemy models.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import Incident, QARecord, OutcomeRecord


# ── State ↔ DB conversion ──────────────────────────────────────────

def state_to_incident(state: dict, incident_id: str) -> Incident:
    """Convert a LangGraph state dict to an Incident ORM object."""
    ic = state.get("incident_card", {})

    return Incident(
        id=incident_id,
        company_id=state.get("company_id"),
        report=state.get("report", ""),
        normalized_summary=ic.get("normalized_summary", ""),
        asset_id=ic.get("asset_id", ""),
        symptoms=ic.get("symptoms", []),
        severity=ic.get("severity", "medium"),
        safety_level=ic.get("safety_level", "unknown"),
        impact=ic.get("impact", ""),
        scope=ic.get("scope", "localized"),
        initial_risk_score=ic.get("initial_risk_score", 5.0),
        reported_by=ic.get("reported_by", ""),
        root_cause_category=ic.get("root_cause_category", ""),

        status=state.get("status", "OPEN"),
        risk_score=state.get("risk_score", 5.0),
        confidence=state.get("confidence", 0.0),
        current_diagnostic_step=state.get("current_diagnostic_step", 1),
        questions_asked_count=state.get("questions_asked_count", 0),
        failed_attempts=state.get("failed_attempts", 0),
        outcome=state.get("outcome", "pending"),
        resolution_summary=state.get("resolution_summary", ""),
        memory_written=state.get("memory_written", False),
        verification_confirmed=state.get("verification_confirmed", False),

        escalation_triggered=state.get("escalation_triggered", False),
        process_failure_suspected=state.get("process_failure_suspected", False),

        incident_card=ic,
        questions=state.get("questions", []),
        hypotheses=state.get("hypotheses", []),
        facts=state.get("facts", []),
        contradictions=state.get("contradictions", []),
        safety_constraints=state.get("safety_constraints", []),
        safety_blocks=state.get("safety_blocks", []),
        escalation_reasons=state.get("escalation_reasons", []),
        process_failure_indicators=state.get("process_failure_indicators", []),
        retrieved_patterns=state.get("retrieved_patterns", []),
        decision_brief=state.get("decision_brief"),
        escalation=state.get("escalation"),

        full_state=_clean_state_for_json(state),

        diagnosis_start_time=state.get("diagnosis_start_time", ""),
        diagnosis_end_time=state.get("diagnosis_end_time", ""),
        mttd_seconds=state.get("mttd_seconds"),
    )


def incident_to_state(inc: Incident) -> dict:
    """Convert an Incident ORM object back to a LangGraph state dict."""
    # Start from the full state snapshot if available
    state = dict(inc.full_state) if inc.full_state else {}

    # Overlay the indexed columns (they're the source of truth)
    state.update({
        "report": inc.report or "",
        "incident_card": inc.incident_card or {},
        "status": inc.status or "OPEN",
        "risk_score": inc.risk_score or 5.0,
        "confidence": inc.confidence or 0.0,
        "current_diagnostic_step": inc.current_diagnostic_step or 1,
        "questions_asked_count": inc.questions_asked_count or 0,
        "failed_attempts": inc.failed_attempts or 0,
        "outcome": inc.outcome or "pending",
        "resolution_summary": inc.resolution_summary or "",
        "memory_written": inc.memory_written or False,
        "verification_confirmed": inc.verification_confirmed or False,

        "escalation_triggered": inc.escalation_triggered or False,
        "process_failure_suspected": inc.process_failure_suspected or False,

        "questions": inc.questions or [],
        "hypotheses": inc.hypotheses or [],
        "facts": inc.facts or [],
        "contradictions": inc.contradictions or [],
        "safety_constraints": inc.safety_constraints or [],
        "safety_blocks": inc.safety_blocks or [],
        "escalation_reasons": inc.escalation_reasons or [],
        "process_failure_indicators": inc.process_failure_indicators or [],
        "retrieved_patterns": inc.retrieved_patterns or [],
        "decision_brief": inc.decision_brief,
        "escalation": inc.escalation,

        "diagnosis_start_time": inc.diagnosis_start_time or "",
        "diagnosis_end_time": inc.diagnosis_end_time or "",
        "mttd_seconds": inc.mttd_seconds,

        "_session_id": inc.id,
        "company_id": inc.company_id,
    })

    # Rebuild qa_history from QARecord rows (if loaded)
    qa_list = getattr(inc, 'qa_history', None)
    if qa_list:
        state["qa_history"] = [
            {
                "question": qa.question,
                "answer": qa.answer,
                "category": qa.category,
                "diagnostic_step": qa.diagnostic_step,
                "signals": qa.signals or [],
            }
            for qa in qa_list
        ]
    elif "qa_history" not in state:
        state["qa_history"] = []

    return state


def _clean_state_for_json(state: dict) -> dict:
    """Remove non-serializable items from state before storing as JSONB."""
    clean = {}
    skip_keys = {"_session_id", "messages"}
    for k, v in state.items():
        if k in skip_keys:
            continue
        try:
            import json
            json.dumps(v)
            clean[k] = v
        except (TypeError, ValueError):
            clean[k] = str(v)
    return clean


# ── CRUD Operations ─────────────────────────────────────────────────


async def create_incident(session: AsyncSession, state: dict, incident_id: str) -> Incident:
    """Create a new incident from a LangGraph state dict."""
    inc = state_to_incident(state, incident_id)
    session.add(inc)
    await session.flush()

    # Save QA history as separate rows
    for qa in state.get("qa_history", []):
        session.add(QARecord(
            incident_id=incident_id,
            question=qa.get("question", ""),
            answer=qa.get("answer", ""),
            category=qa.get("category", "general"),
            diagnostic_step=qa.get("diagnostic_step", 1),
            signals=qa.get("signals", []),
        ))

    return inc


async def get_incident(
    session: AsyncSession, incident_id: str, company_id: int | None = None,
) -> Incident | None:
    """Get an incident by ID with eagerly loaded relationships.
    If company_id is given, also validates ownership.
    """
    query = (
        select(Incident)
        .where(Incident.id == incident_id)
        .options(
            selectinload(Incident.qa_history),
            selectinload(Incident.outcome_records),
        )
    )
    if company_id is not None:
        query = query.where(Incident.company_id == company_id)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def update_incident(session: AsyncSession, incident_id: str, state: dict) -> Incident:
    """Update an incident from an updated LangGraph state dict."""
    inc = await get_incident(session, incident_id)
    if not inc:
        raise ValueError(f"Incident {incident_id} not found")

    ic = state.get("incident_card", inc.incident_card or {})

    # Update indexed columns
    inc.normalized_summary = ic.get("normalized_summary", inc.normalized_summary)
    inc.asset_id = ic.get("asset_id", inc.asset_id)
    inc.symptoms = ic.get("symptoms", inc.symptoms)
    inc.severity = ic.get("severity", inc.severity)
    inc.safety_level = ic.get("safety_level", inc.safety_level)
    inc.impact = ic.get("impact", inc.impact)
    inc.scope = ic.get("scope", inc.scope)
    inc.root_cause_category = ic.get("root_cause_category", inc.root_cause_category)

    inc.status = state.get("status", inc.status)
    inc.risk_score = state.get("risk_score", inc.risk_score)
    inc.confidence = state.get("confidence", inc.confidence)
    inc.current_diagnostic_step = state.get("current_diagnostic_step", inc.current_diagnostic_step)
    inc.questions_asked_count = state.get("questions_asked_count", inc.questions_asked_count)
    inc.failed_attempts = state.get("failed_attempts", inc.failed_attempts)
    inc.outcome = state.get("outcome", inc.outcome)
    inc.resolution_summary = state.get("resolution_summary", inc.resolution_summary)
    inc.memory_written = state.get("memory_written", inc.memory_written)
    inc.verification_confirmed = state.get("verification_confirmed", inc.verification_confirmed)

    inc.escalation_triggered = state.get("escalation_triggered", inc.escalation_triggered)
    inc.process_failure_suspected = state.get("process_failure_suspected", inc.process_failure_suspected)

    inc.incident_card = state.get("incident_card", inc.incident_card)
    inc.questions = state.get("questions", inc.questions)
    inc.hypotheses = state.get("hypotheses", inc.hypotheses)
    inc.facts = state.get("facts", inc.facts)
    inc.contradictions = state.get("contradictions", inc.contradictions)
    inc.safety_constraints = state.get("safety_constraints", inc.safety_constraints)
    inc.safety_blocks = state.get("safety_blocks", inc.safety_blocks)
    inc.escalation_reasons = state.get("escalation_reasons", inc.escalation_reasons)
    inc.process_failure_indicators = state.get("process_failure_indicators", inc.process_failure_indicators)
    inc.retrieved_patterns = state.get("retrieved_patterns", inc.retrieved_patterns)
    inc.decision_brief = state.get("decision_brief", inc.decision_brief)
    inc.escalation = state.get("escalation", inc.escalation)

    inc.full_state = _clean_state_for_json(state)

    inc.diagnosis_start_time = state.get("diagnosis_start_time", inc.diagnosis_start_time)
    inc.diagnosis_end_time = state.get("diagnosis_end_time", inc.diagnosis_end_time)
    inc.mttd_seconds = state.get("mttd_seconds", inc.mttd_seconds)

    await session.flush()
    return inc


async def add_qa_record(
    session: AsyncSession,
    incident_id: str,
    question: str,
    answer: str,
    category: str = "general",
    diagnostic_step: int = 1,
    signals: list | None = None,
) -> QARecord:
    """Add a Q&A record to an incident."""
    qa = QARecord(
        incident_id=incident_id,
        question=question,
        answer=answer,
        category=category,
        diagnostic_step=diagnostic_step,
        signals=signals or [],
    )
    session.add(qa)
    await session.flush()
    return qa


async def add_outcome_record(
    session: AsyncSession,
    incident_id: str,
    attempt_number: int,
    outcome: str,
    notes: str = "",
    root_cause_confirmed: str = "",
    root_cause_category: str = "",
    turning_point_signal: str = "",
    why_previous_failed: str = "",
    risk_adjustment: float = 0.0,
) -> OutcomeRecord:
    """Add an outcome attempt record."""
    rec = OutcomeRecord(
        incident_id=incident_id,
        attempt_number=attempt_number,
        outcome=outcome,
        notes=notes,
        root_cause_confirmed=root_cause_confirmed,
        root_cause_category=root_cause_category,
        turning_point_signal=turning_point_signal,
        why_previous_failed=why_previous_failed,
        risk_adjustment=risk_adjustment,
    )
    session.add(rec)
    await session.flush()
    return rec


async def list_incidents(
    session: AsyncSession,
    company_id: int | None = None,
    status_filter: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """List incidents (summary view), scoped to company."""
    query = select(
        Incident.id,
        Incident.company_id,
        Incident.normalized_summary,
        Incident.asset_id,
        Incident.severity,
        Incident.status,
        Incident.confidence,
        Incident.risk_score,
        Incident.created_at,
        Incident.mttd_seconds,
    ).order_by(Incident.created_at.desc()).limit(limit)

    if company_id is not None:
        query = query.where(Incident.company_id == company_id)
    if status_filter:
        query = query.where(Incident.status == status_filter)

    result = await session.execute(query)
    rows = result.all()

    return [
        {
            "incident_id": row.id,
            "summary": row.normalized_summary or "",
            "asset_id": row.asset_id or "",
            "severity": row.severity or "",
            "status": row.status or "",
            "confidence": row.confidence or 0,
            "risk_score": row.risk_score or 0,
            "created_at": row.created_at.isoformat() if row.created_at else "",
            "mttd_seconds": row.mttd_seconds,
        }
        for row in rows
    ]
