"""
Decisio — Safety Constraint Agent

Converts safety posture into constraints, blocks, and escalation
triggers.  Tightens caution after failed attempts.  (§6.7 of the guide).

Programmatic escalation (cannot be overridden by LLM):
- risk_score >= RISK_ESCALATION_THRESHOLD (8.0)
- confidence < threshold after question budget exhausted
- contradiction_count >= 3
- any safety_blocks active
- LLM returns requires_escalation
Tenant: company_id passed to get_all_applicable_rules for isolation.
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm import get_llm
from src.state.state import (
    CONFIDENCE_THRESHOLD,
    MAX_TOTAL_QUESTIONS,
    RISK_ESCALATION_THRESHOLD,
    DecisioState,
)
from src.data.assets import get_asset, get_asset_type
from src.data.safety_rules import get_all_applicable_rules

import logging
logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are the Safety Constraint Agent for Decisio, an operational decision-support system.

Given the incident state, facts, hypotheses, and risk score, you must:
1. Determine active safety constraints
2. Identify any safety blocks (hard stops that prevent proceeding)
3. Decide if escalation is required

You will be provided with EQUIPMENT-SPECIFIC SAFETY RULES — these are mandatory.
Incorporate them into your constraints output.

Return a JSON object:

{{
  "safety_constraints": [
    "constraint description — what must be observed"
  ],
  "safety_blocks": [
    "block description — hard stop, cannot proceed without resolution"
  ],
  "requires_escalation": true/false,
  "escalation_reasons": ["reason1", "reason2"],
  "updated_safety_level": "safe | caution | danger",
  "risk_adjustment": 0.0
}}

Escalation triggers (from §3.1):
- Safety red-line: hazard present, unknown safety, missing permits
- Risk score >= {risk_threshold}
- Attempt count exceeded
- Contradictions preventing stable hypotheses
- Mandatory escalation pattern from memory

Rules:
- If ANY safety block exists, requires_escalation MUST be true
- Each failed attempt should tighten constraints (add +1.0 to risk_adjustment)
- If safety_level is "danger", always add blocks
- ALWAYS include the equipment-specific safety rules as constraints
- Return ONLY the JSON object, no markdown fences, no extra text.
""".format(risk_threshold=RISK_ESCALATION_THRESHOLD)


def safety_constraint_agent(state: DecisioState) -> DecisioState:
    """
    LangGraph node: Safety Constraint Agent.

    Evaluates safety posture, enforces constraints, and triggers
    escalation when safety red-lines are crossed.
    """
    if state is None:
        state = {}
    incident_card = state.get("incident_card") or {}
    facts = state.get("facts") or []
    hypotheses = state.get("hypotheses") or []
    risk_score = state.get("risk_score") if state.get("risk_score") is not None else 5.0
    confidence = state.get("confidence") if state.get("confidence") is not None else 0.0
    contradictions = state.get("contradictions") or []
    questions_asked = state.get("questions_asked_count", 0)
    retrieved_patterns = state.get("retrieved_patterns") or []

    # Look up equipment-specific safety rules from DB (tenant-scoped)
    company_id = state.get("company_id")
    asset_id = incident_card.get("asset_id", "")
    equipment_type = get_asset_type(asset_id, company_id=company_id) if asset_id else None
    severity = incident_card.get("severity", "medium")

    equipment_rules = []
    rules_applied: list[str] = []  # Audit trail

    # Fetch rules from DB via data layer (company_id for multi-tenant isolation)
    if equipment_type:
        applicable = get_all_applicable_rules(equipment_type, severity, company_id=company_id) or {}
        for rule in applicable.get("blocks", []):
            equipment_rules.append(rule)
            rules_applied.append(f"DB block: {rule[:80]}")
        for rule in applicable.get("constraints", []):
            equipment_rules.append(rule)
            rules_applied.append(f"DB constraint: {rule[:80]}")
        for rule in applicable.get("warnings", []):
            equipment_rules.append(rule)
            rules_applied.append(f"DB warning: {rule[:80]}")

    context_parts = [
        "=== INCIDENT ===",
        f"Severity: {incident_card.get('severity', 'unknown')}",
        f"Safety Level: {incident_card.get('safety_level', 'unknown')}",
        f"Asset: {asset_id or 'unknown'} (type: {equipment_type or 'unknown'})",
        f"Risk Score: {risk_score}",
        f"Confidence: {confidence:.0%}",
        f"Questions Asked: {questions_asked}/{MAX_TOTAL_QUESTIONS}",
        f"Contradictions: {len(contradictions)}",
    ]

    # Inject equipment-specific rules
    if equipment_rules:
        context_parts.append(f"\n=== EQUIPMENT SAFETY RULES ({equipment_type}) ===")
        for rule in equipment_rules:
            context_parts.append(f"- ⚠️ {rule}")

    if facts:
        context_parts.append("\n=== FACTS ===")
        for f in facts[-10:]:
            context_parts.append(f"- {f.get('key', '?')}: {f.get('value', '?')}")

    if hypotheses:
        context_parts.append("\n=== HYPOTHESES ===")
        for h in hypotheses[:3]:
            context_parts.append(f"- {h.get('description', '')} ({h.get('probability', 0):.0%})")

    if contradictions:
        context_parts.append("\n=== CONTRADICTIONS ===")
        for c in contradictions:
            context_parts.append(f"- {c}")

    # Check pattern escalation flags
    mandatory_escalation_patterns = [
        p for p in retrieved_patterns if p.get("must_escalate")
    ]
    if mandatory_escalation_patterns:
        context_parts.append("\n=== MANDATORY ESCALATION PATTERNS ===")
        for p in mandatory_escalation_patterns:
            context_parts.append(f"- {p.get('title', 'unknown')}")

    context = "\n".join(context_parts)

    llm = get_llm(temperature=0.1)
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
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {
            "safety_constraints": [],
            "safety_blocks": [],
            "requires_escalation": False,
            "escalation_reasons": [],
            "risk_adjustment": 0.0,
        }

    # Merge with existing state
    existing_constraints = state.get("safety_constraints") or []
    existing_blocks = state.get("safety_blocks") or []
    escalation_triggered = state.get("escalation_triggered", False)
    escalation_reasons = list(state.get("escalation_reasons") or [])

    new_constraints = list(set(existing_constraints + result.get("safety_constraints", [])))
    new_blocks = list(set(existing_blocks + result.get("safety_blocks", [])))

    # Apply risk adjustment
    adjusted_risk = risk_score + float(result.get("risk_adjustment", 0.0))
    adjusted_risk = max(0.0, min(10.0, adjusted_risk))

    # Programmatic escalation checks
    if adjusted_risk >= RISK_ESCALATION_THRESHOLD:
        escalation_triggered = True
        escalation_reasons.append(f"Risk score {adjusted_risk:.1f} >= threshold {RISK_ESCALATION_THRESHOLD}")

    if confidence < CONFIDENCE_THRESHOLD and questions_asked >= MAX_TOTAL_QUESTIONS:
        escalation_triggered = True
        escalation_reasons.append(f"Low confidence ({confidence:.0%}) after question budget exhausted")

    if len(contradictions) >= 3:
        escalation_triggered = True
        escalation_reasons.append(f"{len(contradictions)} contradictions prevent stable hypotheses")

    if result.get("requires_escalation"):
        escalation_triggered = True
        escalation_reasons.extend(result.get("escalation_reasons", []))

    if new_blocks:
        escalation_triggered = True
        escalation_reasons.append(f"Safety blocks active: {', '.join(new_blocks[:2])}")

    # Update incident card safety level
    updated_card = dict(incident_card) if incident_card else {}
    if result.get("updated_safety_level"):
        updated_card["safety_level"] = result["updated_safety_level"]

    return {
        "incident_card": updated_card,
        "safety_constraints": new_constraints,
        "safety_blocks": new_blocks,
        "risk_score": adjusted_risk,
        "escalation_triggered": escalation_triggered,
        "escalation_reasons": list(set(escalation_reasons)),
        "current_node": "safety_constraint",
        "rules_applied": rules_applied,
    }
