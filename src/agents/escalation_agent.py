"""
Decisio — Escalation Agent

Creates a full-context expert handoff package when escalation is
triggered.  Routes to the correct escalation level.  (§10 of the draft).

Boundary: prompt forbids repair instructions in handoff; decision context only.
Tenant: get_escalation_levels/rules and get_asset use company_id for isolation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm import get_llm
from src.state.state import DecisioState
from src.data.assets import get_asset, get_upstream_downstream
from src.data.escalation_matrix import get_escalation_levels, get_escalation_rules

import logging
logger = logging.getLogger(__name__)


# ── Escalation level routing ────────────────────────────────────────


def _determine_escalation_level(state: DecisioState) -> int:
    """
    Determine the appropriate escalation level based on state.
    Uses DB-driven escalation rules.
    """
    if state is None:
        state = {}
    incident_card = state.get("incident_card") or {}
    safety_level = incident_card.get("safety_level", "unknown")
    severity = incident_card.get("severity", "medium")
    risk_score = state.get("risk_score") if state.get("risk_score") is not None else 5.0
    failed_attempts = state.get("failed_attempts", 0)
    contradictions = state.get("contradictions") or []
    confidence = state.get("confidence") if state.get("confidence") is not None else 0.0
    safety_blocks = state.get("safety_blocks") or []
    retrieved_patterns = state.get("retrieved_patterns") or []

    company_id = state.get("company_id")
    levels = get_escalation_levels(company_id=company_id)
    max_level = max(levels.keys()) if levels else 5

    # Level max: Safety-critical shutdown
    if safety_level == "danger" or safety_blocks:
        return max_level

    # Try DB-driven rules (tenant-scoped)
    db_rules = get_escalation_rules(company_id=company_id)
    safety_impact = "high" if safety_blocks else (
        "medium" if incident_card.get("safety_level") == "caution" else "low"
    )
    for rule in db_rules:
        if rule.get("confidence_min", 0) <= confidence <= rule.get("confidence_max", 1):
            if rule.get("safety_impact") == safety_impact or rule.get("safety_impact") == "high":
                lvl = rule.get("escalation_level", 1)
                if lvl == 0:
                    return 0  # No escalation scenario
                return min(lvl, max_level)

    # Repeated failure detection (§10)
    for p in retrieved_patterns:
        if p.get("must_escalate") and p.get("similarity_score", 0) >= 0.7:
            return min(4, max_level)

    # High risk
    if risk_score >= 8.0:
        return min(4, max_level)

    # Conflicting signals
    if len(contradictions) >= 3:
        return min(3, max_level)
    if confidence < 0.3 and failed_attempts >= 1:
        return min(3, max_level)

    # Specialized team
    if failed_attempts >= 2:
        return min(2, max_level)
    if severity in ("high", "critical"):
        return min(2, max_level)

    # Default: lowest level
    return 1


# ── System prompt ────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are the Escalation Agent for Decisio, an operational decision-support system.

An escalation has been triggered. Build a complete handoff package so the receiving
expert can start ahead of zero — they should understand the full situation immediately.

Return a JSON object:

{{
  "escalation_summary": "Brief 2-3 sentence summary of why escalation is needed",
  "recommended_expertise": "What type of expertise is needed (use the authority/role name from the COMPANY ESCALATION MATRIX if provided)",
  "decision_authority": "The role name from the escalation matrix who should make the decision (e.g. 'L1 — Field Technician')",
  "escalation_target": "The next-level role from the escalation matrix to escalate to if unresolved",
  "urgency": "immediate | within_1_hour | within_shift | next_business_day",
  "key_findings": ["list of the most important findings from diagnosis so far"],
  "what_was_tried": ["list of what was attempted and why it failed"],
  "open_questions": ["list of unresolved diagnostic questions"],
  "safety_warnings": ["list of active safety concerns the expert must know"],
  "sla_target_hours": <number>
}}

Rules:
- Include ALL relevant context — the expert should NOT need to re-ask basic questions
- Safety warnings must be prominent and complete
- Do NOT include repair instructions — only decision context
- If a COMPANY ESCALATION MATRIX is provided, use ONLY those role names for decision_authority and escalation_target. Do NOT invent roles like "Shift Engineer" or "Maintenance Manager".
- Return ONLY the JSON object, no markdown fences, no extra text.
"""


def escalation_agent(state: DecisioState) -> DecisioState:
    """
    LangGraph node: Escalation Agent.

    Creates a full-context handoff package and routes to the
    appropriate escalation level.
    """
    if state is None:
        state = {}
    incident_card = state.get("incident_card") or {}
    qa_history = state.get("qa_history") or []
    hypotheses = state.get("hypotheses") or []
    facts = state.get("facts") or []
    decision_brief = state.get("decision_brief") or {}
    safety_constraints = state.get("safety_constraints") or []
    safety_blocks = state.get("safety_blocks") or []
    escalation_reasons = state.get("escalation_reasons") or []
    failed_attempts = state.get("failed_attempts", 0)
    risk_score = state.get("risk_score") if state.get("risk_score") is not None else 5.0
    confidence = state.get("confidence") if state.get("confidence") is not None else 0.0
    contradictions = state.get("contradictions") or []

    # Determine escalation level from DB (tenant-scoped)
    company_id = state.get("company_id")
    levels = get_escalation_levels(company_id=company_id)
    db_rules = get_escalation_rules(company_id=company_id)

    # ── EDGE CASE: No escalation matrix configured for this company ──
    # If the admin hasn't set up any escalation levels or rules,
    # we cannot route the escalation. Park it in a waiting state
    # until the admin configures the matrix via the Admin Portal.
    if not levels:
        logger.warning(
            "Escalation triggered but company_id=%s has NO escalation levels configured. "
            "Parking escalation in PENDING_ESCALATION_CONFIG status.",
            company_id,
        )
        return {
            "escalation_triggered": True,
            "escalation": {
                "escalation_level": None,
                "escalation_level_name": "Pending Configuration",
                "escalation_level_description": (
                    "Escalation is required but no escalation matrix has been configured for this company. "
                    "Please ask your administrator to set up escalation levels and rules in the Admin Portal → Escalation section."
                ),
                "pending_config": True,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "incident_id": incident_card.get("incident_id", "unknown"),
                "escalation_reasons": escalation_reasons,
                "status": "PENDING_ESCALATION_CONFIG",
            },
            "status": "PENDING_ESCALATION_CONFIG",
            "current_node": "escalation",
        }

    level = _determine_escalation_level(state)
    level_info = levels.get(level, {"name": f"Level {level}", "description": "Escalation required"})

    # No escalation scenario (level 0): do not create session or handoff
    if level == 0:
        return {
            "escalation_triggered": False,
            "escalation": {
                "escalation_level": 0,
                "escalation_level_name": level_info.get("name", "No escalation"),
                "escalation_level_description": level_info.get("description", "Resolved at operator level — no escalation."),
                "no_escalation": True,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "incident_id": incident_card.get("incident_id", "unknown"),
                "status": "NO_ESCALATION",
            },
            "status": "NO_ESCALATION",
            "current_node": "escalation",
        }

    # Build context for LLM
    context_parts = [
        "=== INCIDENT ===",
        f"Summary: {incident_card.get('normalized_summary', '')}",
        f"Asset: {incident_card.get('asset_id', 'unknown')}",
        f"Severity: {incident_card.get('severity', 'unknown')}",
        f"Safety: {incident_card.get('safety_level', 'unknown')}",
        f"Risk: {risk_score:.1f}/10 | Confidence: {confidence:.0%}",
        f"Failed attempts: {failed_attempts}",
        f"\nEscalation Level: {level} — {level_info['name']}",
        f"Reason: {level_info['description']}",
    ]

    # ── Inject the FULL company escalation matrix from DB ──
    if levels:
        context_parts.append("\n=== COMPANY ESCALATION MATRIX ===")
        context_parts.append("Use ONLY the following authority/role names. Do NOT invent roles.")
        for lvl_num in sorted(levels.keys()):
            lvl_data = levels[lvl_num]
            context_parts.append(f"  Level {lvl_num}: {lvl_data['name']} — {lvl_data.get('description', '')}")

    db_rules = get_escalation_rules(company_id=company_id)
    if db_rules:
        context_parts.append("\n=== ESCALATION RULES ===")
        for rule in db_rules:
            context_parts.append(
                f"  [{rule.get('condition', '')}] confidence {rule.get('confidence_min', 0):.0%}-{rule.get('confidence_max', 1):.0%}, "
                f"safety={rule.get('safety_impact', 'low')} → Level {rule.get('escalation_level', 0)} ({rule.get('description', '')})"
            )

    # Add asset details from registry (tenant-scoped)
    asset_id = incident_card.get("asset_id", "")
    asset_info = get_asset(asset_id, company_id=company_id) if asset_id else None
    if asset_info:
        context_parts.append(f"\n=== ASSET DETAILS ===")
        context_parts.append(f"Name: {asset_info['name']}")
        context_parts.append(f"Type: {asset_info['type']}")
        context_parts.append(f"Process Line: {asset_info['process_line']}")
        context_parts.append(f"Criticality: {asset_info['criticality']}")

        ud = get_upstream_downstream(asset_id, company_id=company_id)
        if ud.get("upstream"):
            context_parts.append(f"Upstream: {ud['upstream_id']} ({ud['upstream']['name']})")
        if ud.get("downstream"):
            context_parts.append(f"Downstream: {ud['downstream_id']} ({ud['downstream']['name']})")

    if escalation_reasons:
        context_parts.append("\n=== ESCALATION TRIGGERS ===")
        for r in escalation_reasons:
            context_parts.append(f"- {r}")

    if qa_history:
        context_parts.append(f"\n=== Q&A HISTORY ({len(qa_history)} exchanges) ===")
        for qa in qa_history:
            step = qa.get("diagnostic_step", "?")
            context_parts.append(f"[Step {step}] Q: {qa.get('question', '')}")
            context_parts.append(f"         A: {qa.get('answer', '')}")
            if qa.get("signals"):
                context_parts.append(f"         Signals: {', '.join(qa['signals'])}")

    if facts:
        context_parts.append(f"\n=== KNOWN FACTS ({len(facts)}) ===")
        for f in facts:
            flag = " ⚠️ CONTRADICTION" if f.get("contradiction") else ""
            context_parts.append(f"- {f.get('key', '?')}: {f.get('value', '?')}{flag}")

    if hypotheses:
        context_parts.append("\n=== HYPOTHESES ===")
        for h in hypotheses:
            context_parts.append(f"- {h.get('description', '')} ({h.get('probability', 0):.0%}, {h.get('category', '')})")

    if contradictions:
        context_parts.append("\n=== CONTRADICTIONS ===")
        for c in contradictions:
            context_parts.append(f"- {c}")

    if safety_constraints:
        context_parts.append("\n=== SAFETY CONSTRAINTS ===")
        for c in safety_constraints:
            context_parts.append(f"- {c}")

    if safety_blocks:
        context_parts.append("\n=== SAFETY BLOCKS (HARD STOPS) ===")
        for b in safety_blocks:
            context_parts.append(f"- ⛔ {b}")

    if decision_brief.get("options"):
        context_parts.append("\n=== DECISION OPTIONS PRESENTED ===")
        for opt in decision_brief["options"]:
            rec = " [RECOMMENDED]" if opt.get("recommended") else ""
            context_parts.append(f"- {opt.get('title', '')}{rec}: {opt.get('description', '')}")

    context = "\n".join(context_parts)

    # Generate the handoff package
    llm = get_llm(temperature=0.2)
    response = llm.invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=context),
    ])

    raw = response.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw[: raw.rfind("```")]
        raw = raw.strip()

    try:
        handoff = json.loads(raw)
    except json.JSONDecodeError:
        handoff = {
            "escalation_summary": f"Escalation triggered: {'; '.join(escalation_reasons[:3])}",
            "recommended_expertise": "General technical specialist",
            "urgency": "within_1_hour",
            "key_findings": [f.get("value", "") for f in facts[:5]],
            "what_was_tried": [f"Attempt failed ({failed_attempts} total)"] if failed_attempts else [],
            "open_questions": [],
            "safety_warnings": safety_constraints[:3],
            "sla_target_hours": 4,
        }

    # Build the complete escalation document
    escalation = {
        "escalation_level": level,
        "escalation_level_name": level_info["name"],
        "escalation_level_description": level_info["description"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "incident_id": incident_card.get("incident_id", "unknown"),
        "incident_summary": incident_card.get("normalized_summary", ""),
        "asset_id": incident_card.get("asset_id", "unknown"),
        "severity": incident_card.get("severity", "unknown"),
        "safety_level": incident_card.get("safety_level", "unknown"),
        "risk_score": risk_score,
        "confidence": confidence,
        "failed_attempts": failed_attempts,
        "escalation_reasons": escalation_reasons,
        "escalation_summary": handoff.get("escalation_summary", ""),
        "recommended_expertise": handoff.get("recommended_expertise", ""),
        "decision_authority": handoff.get("decision_authority", level_info["name"]),
        "escalation_target": handoff.get("escalation_target", ""),
        "urgency": handoff.get("urgency", "within_1_hour"),
        "key_findings": handoff.get("key_findings", []),
        "what_was_tried": handoff.get("what_was_tried", []),
        "open_questions": handoff.get("open_questions", []),
        "safety_warnings": handoff.get("safety_warnings", []),
        "safety_constraints": safety_constraints,
        "safety_blocks": safety_blocks,
        "hypotheses": hypotheses,
        "qa_timeline": qa_history,
        "decision_options": decision_brief.get("options", []),
        "sla_target_hours": handoff.get("sla_target_hours", 4),
        "status": "AWAITING_EXPERT",
    }

    return {
        "escalation": escalation,
        "status": "ESCALATED",
        "current_node": "escalation",
    }
