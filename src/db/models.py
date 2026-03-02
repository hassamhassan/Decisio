"""
Decisio — SQLAlchemy Models

Persistent storage for incidents, Q&A history, decision briefs,
escalations, and outcome records.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base for all Decisio ORM models."""
    pass


class Company(Base):
    """Tenant / Company entity for multi-tenant isolation."""

    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), unique=True, nullable=False)
    slug = Column(String(64), unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    users = relationship("User", back_populates="company")
    incidents = relationship("Incident", back_populates="company")
    equipment = relationship("Equipment", back_populates="company")
    escalation_sessions = relationship("EscalationSession", back_populates="company")


class User(Base):
    """System user with role-based access.
    super_admin users have company_id=None; all others belong to a company.
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(
        Integer, ForeignKey("companies.id"), nullable=True, index=True,
    )
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(128), unique=True, nullable=False)
    hashed_password = Column(String(256), nullable=False)
    full_name = Column(String(128), default="")
    user_type = Column(String(16), default="operator")  # admin/operator/engineer/viewer
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    company = relationship("Company", back_populates="users")


class Incident(Base):
    """Core incident record — maps to the IncidentCard + session state."""

    __tablename__ = "incidents"

    id = Column(String(64), primary_key=True)
    company_id = Column(
        Integer, ForeignKey("companies.id"), nullable=False, index=True,
    )
    report = Column(Text, nullable=False)
    normalized_summary = Column(Text, default="")
    asset_id = Column(String(32), index=True)
    symptoms = Column(JSONB, default=list)
    severity = Column(String(16), default="medium")
    safety_level = Column(String(16), default="unknown")
    impact = Column(Text, default="")
    scope = Column(String(32), default="localized")
    initial_risk_score = Column(Float, default=5.0)
    reported_by = Column(String(128), default="")
    root_cause_category = Column(String(32), default="")
    process_line = Column(String(32), default="")

    # Current state
    status = Column(String(32), default="OPEN", index=True)
    risk_score = Column(Float, default=5.0)
    confidence = Column(Float, default=0.0)
    current_diagnostic_step = Column(Integer, default=1)
    questions_asked_count = Column(Integer, default=0)
    failed_attempts = Column(Integer, default=0)
    outcome = Column(String(16), default="pending")
    resolution_summary = Column(Text, default="")
    memory_written = Column(Boolean, default=False)
    verification_confirmed = Column(Boolean, default=False)

    # Flags
    escalation_triggered = Column(Boolean, default=False)
    process_failure_suspected = Column(Boolean, default=False)

    # Structured data stored as JSON
    incident_card = Column(JSONB, default=dict)
    questions = Column(JSONB, default=list)
    hypotheses = Column(JSONB, default=list)
    facts = Column(JSONB, default=list)
    contradictions = Column(JSONB, default=list)
    safety_constraints = Column(JSONB, default=list)
    safety_blocks = Column(JSONB, default=list)
    escalation_reasons = Column(JSONB, default=list)
    process_failure_indicators = Column(JSONB, default=list)
    retrieved_patterns = Column(JSONB, default=list)
    decision_brief = Column(JSONB, nullable=True)
    escalation = Column(JSONB, nullable=True)

    # Full state snapshot (for LangGraph compatibility)
    full_state = Column(JSONB, default=dict)

    # KPI timing
    diagnosis_start_time = Column(String(64), default="")
    diagnosis_end_time = Column(String(64), default="")
    mttd_seconds = Column(Float, nullable=True)

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    qa_history = relationship(
        "QARecord", back_populates="incident", cascade="all, delete-orphan",
        order_by="QARecord.created_at",
    )
    outcome_records = relationship(
        "OutcomeRecord", back_populates="incident", cascade="all, delete-orphan",
        order_by="OutcomeRecord.created_at",
    )
    company = relationship("Company", back_populates="incidents")


class QARecord(Base):
    """Individual question-answer exchange."""

    __tablename__ = "qa_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    incident_id = Column(
        String(64), ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    question = Column(Text, nullable=False)
    answer = Column(Text, default="")
    category = Column(String(32), default="general")
    diagnostic_step = Column(Integer, default=1)
    signals = Column(JSONB, default=list)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    incident = relationship("Incident", back_populates="qa_history")


class OutcomeRecord(Base):
    """Outcome attempt record (success/failure/partial)."""

    __tablename__ = "outcome_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    incident_id = Column(
        String(64), ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    attempt_number = Column(Integer, default=1)
    outcome = Column(String(16), nullable=False)  # success/failure/partial
    notes = Column(Text, default="")
    root_cause_confirmed = Column(Text, default="")
    root_cause_category = Column(String(32), default="")
    turning_point_signal = Column(Text, default="")
    why_previous_failed = Column(Text, default="")
    risk_adjustment = Column(Float, default=0.0)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    incident = relationship("Incident", back_populates="outcome_records")


# ═══════════════════════════════════════════════════════════════════
# Operational Data Tables
# ═══════════════════════════════════════════════════════════════════


class Equipment(Base):
    """Equipment / Asset registry (§24 tech stack data layer)."""

    __tablename__ = "equipment"

    id = Column(String(32), primary_key=True)           # e.g. "CMP-01"
    company_id = Column(
        Integer, ForeignKey("companies.id"), nullable=False, index=True,
    )
    name = Column(String(128), nullable=False)
    equipment_type = Column(String(32), nullable=False)  # rotating, pressure_vessel, etc.
    process_line = Column(String(32), default="")
    criticality = Column(String(16), default="medium")   # low/medium/high/critical
    description = Column(Text, default="")

    # Upstream / downstream IDs (stored as-is; no FK so equipment can be added before references exist)
    upstream_id = Column(String(32), nullable=True, index=True)
    downstream_id = Column(String(32), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    company = relationship("Company", back_populates="equipment")


class SafetyRule(Base):
    """Safety rules per equipment type (§9)."""

    __tablename__ = "safety_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(
        Integer, ForeignKey("companies.id"), nullable=False, index=True,
    )
    equipment_type = Column(String(32), nullable=False, index=True)  # "rotating", "general", etc.
    rule_text = Column(Text, nullable=False)
    severity_class = Column(
        String(16), default="constraint",
    )  # "block" (hard stop) / "constraint" (must-follow) / "warning"
    is_general = Column(Boolean, default=False)  # True = applies to ALL equipment
    sort_order = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class EscalationLevel(Base):
    """Escalation hierarchy levels (§10). Composite PK (company_id, level) for multi-tenant."""

    __tablename__ = "escalation_levels"

    company_id = Column(
        Integer, ForeignKey("companies.id"), nullable=False, primary_key=True,
    )
    level = Column(Integer, nullable=False, primary_key=True)  # 1, 2, 3, ...
    name = Column(String(64), nullable=False)
    description = Column(Text, default="")

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class EscalationRule(Base):
    """Condition-based escalation routing rules (§10)."""

    __tablename__ = "escalation_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(
        Integer, ForeignKey("companies.id"), nullable=False, index=True,
    )
    condition = Column(String(128), nullable=False)
    confidence_min = Column(Float, default=0.0)
    confidence_max = Column(Float, default=1.0)
    safety_impact = Column(String(16), default="low")     # low/medium/high
    escalation_level = Column(Integer, default=0)
    description = Column(Text, default="")
    sort_order = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class IncidentReport(Base):
    """Historical incident reports for Decision Memory (§6, §11)."""

    __tablename__ = "incident_reports"

    id = Column(String(32), primary_key=True)             # e.g. "IR-2024-017"
    company_id = Column(
        Integer, ForeignKey("companies.id"), nullable=False, index=True,
    )
    title = Column(String(256), nullable=False)
    asset_id = Column(String(32), ForeignKey("equipment.id"), nullable=True, index=True)
    process_line = Column(String(32), default="")
    symptoms = Column(JSONB, default=list)
    trigger_condition = Column(Text, default="")
    root_cause = Column(Text, default="")
    root_cause_category = Column(String(32), default="")  # downstream/upstream/control/process
    resolution = Column(Text, default="")
    turning_point_signal = Column(Text, default="")
    decision_taken = Column(Text, default="")
    signals = Column(JSONB, default=list)
    lessons = Column(JSONB, default=list)

    # Escalation
    escalation_required = Column(Boolean, default=False)
    escalation_level = Column(Integer, default=0)
    escalation_reason = Column(Text, default="")

    # Severity
    severity = Column(String(16), default="medium")
    safety_level = Column(String(16), default="caution")

    # Diagnosis time comparison
    diagnosis_time_traditional = Column(Integer, nullable=True)  # minutes
    diagnosis_time_structured = Column(Integer, nullable=True)    # minutes

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship to equipment
    equipment = relationship("Equipment", foreign_keys=[asset_id])


# ── Escalation Chat (WebSocket) ─────────────────────────────────────

class EscalationSessionStatus:
    WAITING = "waiting"
    ACTIVE = "active"
    CLOSED = "closed"


class EscalationMessageSenderRole:
    USER = "user"
    EXPERT = "expert"
    SYSTEM = "system"


class EscalationSession(Base):
    """Real-time escalation chat session. Multi-tenant by company_id."""

    __tablename__ = "escalation_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        Integer, ForeignKey("companies.id"), nullable=False, index=True,
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    expert_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    status = Column(
        String(16), nullable=False, default=EscalationSessionStatus.WAITING, index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    closed_at = Column(DateTime(timezone=True), nullable=True)

    company = relationship("Company", back_populates="escalation_sessions")
    user = relationship("User", foreign_keys=[user_id])
    expert = relationship("User", foreign_keys=[expert_id])
    messages = relationship(
        "EscalationMessage",
        back_populates="session",
        order_by="EscalationMessage.created_at",
    )


class EscalationMessage(Base):
    """Single message in an escalation chat session. Persisted for audit."""

    __tablename__ = "escalation_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("escalation_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id = Column(
        Integer, ForeignKey("companies.id"), nullable=False, index=True,
    )
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    sender_role = Column(String(16), nullable=False, index=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("EscalationSession", back_populates="messages")

