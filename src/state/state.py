"""
Decisio — LangGraph State Model

Defines the shared state schema used across all agents in the Decisio
decision-support workflow.  Sub-models are Pydantic BaseModels for
validation; the top-level `DecisioState` is a TypedDict consumed by
LangGraph's StateGraph.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


# ── 10-Step Diagnostic Framework Categories ─────────────────────────

DIAGNOSTIC_CATEGORIES = [
    "trigger_condition",
    "internal_equipment",
    "upstream_equipment",
    "downstream_equipment",
    "control_system",
    "instrumentation",
    "utilities",
    "process_conditions",
    "procedure_human",
    "verification_closure",
]

DIAGNOSTIC_CATEGORY_LABELS = {
    "trigger_condition": "1. Check Trigger Condition",
    "internal_equipment": "2. Check Internal Equipment",
    "upstream_equipment": "3. Check Upstream Equipment",
    "downstream_equipment": "4. Check Downstream Equipment",
    "control_system": "5. Check Control System",
    "instrumentation": "6. Check Instrumentation",
    "utilities": "7. Check Utilities",
    "process_conditions": "8. Check Process Conditions",
    "procedure_human": "9. Check Procedure/Human",
    "verification_closure": "10. Verification and Closure",
}

# ── Escalation / confidence thresholds ──────────────────────────────

CONFIDENCE_THRESHOLD = 0.80       # Stop diagnosis loop when confidence >= this
RISK_ESCALATION_THRESHOLD = 8.0   # Escalate when risk score >= this
MAX_QUESTIONS_PER_STEP = 3        # Max questions per diagnostic step
MAX_TOTAL_QUESTIONS = 20          # Hard question budget across all steps

# ── Incident status lifecycle (§5) ──────────────────────────────────

INCIDENT_STATUSES = [
    "OPEN",               # Just reported via Webchat
    "SCREENING",          # Being classified by Screening Agent
    "DIAGNOSING",         # In the iterative Q&A loop
    "BRIEF_GENERATED",    # Decision Brief ready for operator
    "EXECUTING",          # Operator is attempting chosen decision
    "RESOLVED",           # Outcome = success, pending memory write
    "ESCALATED",          # Escalation triggered, sent to expert
    "CLOSED",             # Fully closed, decision memory written
    "CLOSED_NO_MEMORY",   # Closed but memory write failed
]


# ── Pydantic sub-models ─────────────────────────────────────────────


class IncidentCard(BaseModel):
    """Structured summary of an operational incident."""

    incident_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    report: str = Field(
        ..., description="Original free-text report from the user"
    )
    normalized_summary: str = Field(
        default="", description="LLM-cleaned summary of the report"
    )
    asset_id: Optional[str] = Field(
        default=None, description="Identified asset / equipment ID"
    )
    symptoms: list[str] = Field(
        default_factory=list, description="Extracted symptom keywords"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 timestamp of incident creation",
    )
    severity: Optional[str] = Field(
        default=None,
        description="Severity level: low / medium / high / critical",
    )
    safety_level: Optional[str] = Field(
        default=None,
        description="Safety posture: safe / caution / danger / unknown",
    )
    status: str = Field(
        default="NEW_INCIDENT",
        description="Current workflow status of the incident",
    )
    impact: Optional[str] = Field(
        default=None, description="Impact assessment from screening"
    )
    scope: Optional[str] = Field(
        default=None, description="Scope of the incident"
    )
    initial_risk_score: Optional[float] = Field(
        default=None, description="Initial numeric risk score (0-10)"
    )
    reported_by: str = Field(
        default="",
        description="Who reported the incident (§19.2)",
    )
    root_cause_category: str = Field(
        default="",
        description="Root cause category: technical / process / external (§19.2)",
    )


class Question(BaseModel):
    """A single diagnostic question produced by the Question Agent."""

    question: str = Field(..., description="The question text")
    category: str = Field(
        ...,
        description=(
            "Diagnostic category: trigger_condition / internal_equipment / "
            "upstream_equipment / downstream_equipment / control_system / "
            "instrumentation / utilities / process_conditions / "
            "procedure_human / verification_closure"
        ),
    )
    diagnostic_step: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Step number (1-10) in the diagnostic framework",
    )
    rationale: str = Field(
        default="",
        description="Why this question was chosen",
    )
    expected_answer_type: str = Field(
        default="free_text",
        description="Expected answer format: yes_no / numeric / free_text / multiple_choice",
    )
    blocking_safety_flag: bool = Field(
        default=False,
        description="True if a bad answer should force escalation",
    )


class QAPair(BaseModel):
    """A question–answer pair recorded during the diagnosis loop."""

    question: str
    answer: str
    category: str = "general"
    diagnostic_step: int = 1
    signals: list[str] = Field(
        default_factory=list,
        description="Signal flags extracted from the answer",
    )


class Fact(BaseModel):
    """A structured fact extracted from an answer."""

    key: str = Field(..., description="Fact identifier, e.g. 'vibration_level'")
    value: str = Field(..., description="Extracted value")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    source_step: int = Field(default=1, description="Which diagnostic step produced this")
    contradiction: bool = Field(default=False, description="Contradicts a previous fact")


class Hypothesis(BaseModel):
    """A single ranked hypothesis."""

    description: str
    probability: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Confidence 0-1"
    )
    category: str = Field(
        default="technical",
        description="technical / process / external",
    )
    supporting_facts: list[str] = Field(
        default_factory=list,
        description="Fact keys that support this hypothesis",
    )
    contradicting_facts: list[str] = Field(
        default_factory=list,
        description="Fact keys that contradict this hypothesis",
    )
    root_cause_layer: str = Field(
        default="symptom",
        description="Hypothesis layer: symptom / trigger / root_cause (§13). Default symptom for safety.",
    )


class DecisionOption(BaseModel):
    """A single decision option in the Decision Brief."""

    option_id: int = Field(..., description="Option number")
    title: str = Field(..., description="Short title of the option")
    description: str = Field(..., description="What this option involves")
    risks: list[str] = Field(default_factory=list, description="Associated risks")
    constraints: list[str] = Field(default_factory=list, description="Safety/operational constraints")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence in this option")
    recommended: bool = Field(default=False, description="Whether this is the top recommendation")
    risk_level: str = Field(default="medium", description="Risk level: low / medium / medium-high / high (§19.3)")
    eta: str = Field(default="", description="Estimated time for this option, e.g. '10-15 min' (§19.3)")
    blocked_by_safety: bool = Field(
        default=False,
        description="True when option violates active safety blocks; must not be recommended (§6.7)",
    )


class DecisionBrief(BaseModel):
    """The Decision Brief output artifact (§19.3)."""

    incident_id: str
    analysis_summary: str = Field(
        default="",
        description="Brief analysis summary paragraph (§19.3)",
    )
    root_cause_hypothesis: str = Field(
        default="",
        description="Primary root cause hypothesis with confidence (§19.3)",
    )
    options: list[DecisionOption] = Field(default_factory=list)
    overall_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_summary: str = Field(default="")
    safety_constraints: list[str] = Field(default_factory=list)
    escalation_guidance: str = Field(default="")
    requires_escalation: bool = Field(default=False)
    decision_authority: str = Field(
        default="",
        description="Who has authority to approve this decision (§19.3). Should match a role from the escalation matrix.",
    )
    escalation_path: str = Field(
        default="",
        description="Next escalation level if decision fails (§19.3)",
    )


class RetrievedPattern(BaseModel):
    """A decision pattern retrieved from memory."""

    pattern_id: str = Field(default="")
    title: str = Field(default="")
    similarity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    signals: list[str] = Field(default_factory=list)
    decision_taken: str = Field(default="")
    must_escalate: bool = Field(default=False)


# ── LangGraph top-level state (TypedDict) ───────────────────────────


class DecisioState(TypedDict, total=False):
    """
    Top-level state passed through every LangGraph node.

    All fields are optional (total=False) so that each agent only needs
    to return the keys it modifies.
    """

    # ── Tenant ──────────────────────────────────────────────────────
    company_id: int  # Company / tenant ID for multi-tenant isolation
    language: str  # UI language code ("en" or "ar") — agents respond in this language

    # ── Raw input ────────────────────────────────────────────────────
    report: str  # Free-text incident report from the user
    user_answer: str  # Latest user answer to a diagnostic question

    # Enriched input from Problem & Machine Intake agent
    problem_description: str  # Clean 1–3 sentence description of the issue
    machine_name: str  # Machine / asset name or ID, if identified
    clarification_question: str  # Direct question asked during the problem intake phase

    # Guided intake phase tracking (problem_intake_agent)
    # Phase lifecycle:  "symptoms" → "machine" → "complete"
    #   "symptoms"  – first run; agent asks about symptoms
    #   "machine"   – symptoms collected; agent asks about machine
    #   "complete"  – both collected; proceed to incident_intake
    intake_phase: str
    reported_symptoms: str  # Symptoms described by the user in their own words

    # ── Incident Card (structured) ───────────────────────────────────
    incident_card: dict[str, Any]  # Serialised IncidentCard

    # ── Screening ────────────────────────────────────────────────────
    screening_complete: bool
    process_failure_suspected: bool
    process_failure_indicators: list[str]

    # ── Retrieval / Memory ───────────────────────────────────────────
    retrieved_patterns: list[dict[str, Any]]  # List of RetrievedPattern dicts

    # ── Diagnosis Loop ───────────────────────────────────────────────
    questions: list[dict[str, Any]]  # List of Question dicts
    current_question: dict[str, Any]  # The active question being asked
    answers: list[str]  # Raw user answers
    qa_history: list[dict[str, Any]]  # List of QAPair dicts
    facts: list[dict[str, Any]]  # Extracted structured facts (Fact dicts)
    contradictions: list[str]  # Detected contradictions
    current_diagnostic_step: int  # Which of the 10 steps we are on (1-10)
    step_cleared: bool  # Whether the current diagnostic step has been fully resolved
    questions_asked_count: int  # Total questions asked so far

    # ── Hypotheses & Confidence ──────────────────────────────────────
    hypotheses: list[dict[str, Any]]  # List of Hypothesis dicts
    confidence: float  # Overall confidence score (0-1)
    risk_score: float  # Computed risk score (0-10)

    # ── Safety & Constraints ─────────────────────────────────────────
    safety_constraints: list[str]
    safety_blocks: list[str]
    escalation_triggered: bool
    escalation_reasons: list[str]

    # ── Decision Brief ───────────────────────────────────────────────
    decision_brief: dict[str, Any]  # Serialised DecisionBrief
    chosen_decision_option: dict[str, Any]  # Brief option the operator executed (before Success)

    # ── Escalation ───────────────────────────────────────────────────
    escalation: dict[str, Any]

    # ── Outcome Capture (§5 steps 6-8) ───────────────────────────────
    outcome: str  # "success" | "failure" | "partial" | "pending"
    outcome_notes: str  # User's description of what happened
    user_solution_notes: str  # Operator-typed solution text — highest-priority input for Decision Memory
    failed_attempts: int  # Count of failed resolution attempts
    resolution_summary: str  # Final resolution description (LLM-generated; may be overwritten)
    memory_written: bool  # Whether verified pattern was stored
    verification_confirmed: bool  # Whether trigger normalization was verified
    verification_notes: str  # Notes recorded during verification
    verification_timestamp: str  # When verification was completed

    # ── KPI Tracking (§27) ───────────────────────────────────────────
    diagnosis_start_time: str  # ISO timestamp when diagnosis began
    diagnosis_end_time: str  # ISO timestamp when brief was generated
    mttd_seconds: float  # Mean Time To Diagnosis in seconds

    # ── Control Flow ─────────────────────────────────────────────────
    current_node: str
    status: str  # Maps to graph states in §5.1
    should_continue_diagnosis: bool  # Router flag for the diagnosis loop
    diagnostic_steps_completed: list[int]  # Which of the 10 steps have been answered
    retrieval_confidence: float  # How well Decision Memory patterns matched
    memory_guidance: str  # Human-readable hint when a strong memory match exists

    # ── Messages (LLM chat history) ─────────────────────────────────
    messages: list[Any]
