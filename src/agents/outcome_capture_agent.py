"""
Decisio — Outcome Capture Agent

Handles the outcome loop after execution (§5 steps 6-8):
- User reports success or failure
- On failure: tightens safety, increments failed attempts, triggers escalation
- On success: prepares for memory write and closure

Per the draft §4.6: "Failure is information, not an ending"
Per the draft §9: "When safety tightens: automatically upon decision-path failure"
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm import get_llm
from src.state.state import DecisioState

SYSTEM_PROMPT = """\
You are the Outcome Capture Agent for Decisio, an operational decision-support system.

The operator has attempted to execute a decision. You need to analyze their outcome report.

Return a JSON object:

{{
  "outcome": "success | failure | partial",
  "resolution_summary": "Brief description of what happened",
  "root_cause_confirmed": "The confirmed root cause, if success. Empty if failure.",
  "root_cause_category": "technical | process | external | unknown",
  "turning_point_signal": "The key signal/fact that confirmed the root cause (for expert capture §11)",
  "why_previous_failed": "Why earlier attempts failed, if applicable. Empty if first attempt succeeded.",
  "escalation_needed": true/false,
  "safety_tightening": ["list of additional safety constraints to add, if failure"],
  "risk_adjustment": 0.0
}}

Rules:
- If the outcome is "failure", always add risk_adjustment of +1.0 or more
- If the outcome is "failure", always recommend at least one safety tightening
- If the outcome is "partial", add +0.5 risk_adjustment
- If "success", capture the root_cause_confirmed and turning_point_signal
- The turning_point_signal is critical — it captures WHY the fix succeeded (§11)
- Return ONLY the JSON object, no markdown fences, no extra text.
"""


def outcome_capture_agent(state: DecisioState) -> DecisioState:
    """
    LangGraph node: Outcome Capture Agent.

    Processes the operator's outcome report after execution attempt.
    On failure: tightens safety, increments attempts, may escalate.
    On success: captures root cause and turning point for Decision Memory.
    """
    outcome_notes = state.get("outcome_notes", "")
    incident_card = state.get("incident_card", {})
    hypotheses = state.get("hypotheses", [])
    facts = state.get("facts", [])
    decision_brief = state.get("decision_brief", {})
    failed_attempts = state.get("failed_attempts", 0)
    risk_score = state.get("risk_score", 5.0)

    if not outcome_notes:
        return {"current_node": "outcome_capture"}

    # Build context
    context_parts = [
        "=== INCIDENT ===",
        f"Summary: {incident_card.get('normalized_summary', '')}",
        f"Current risk: {risk_score}",
        f"Failed attempts so far: {failed_attempts}",
        f"\n=== OPERATOR OUTCOME REPORT ===",
        outcome_notes,
    ]

    if hypotheses:
        context_parts.append("\n=== HYPOTHESES ===")
        for h in hypotheses[:3]:
            context_parts.append(f"- {h.get('description', '')} ({h.get('probability', 0):.0%})")

    if decision_brief.get("options"):
        context_parts.append("\n=== DECISION OPTIONS THAT WERE PRESENTED ===")
        for opt in decision_brief["options"]:
            rec = " [RECOMMENDED]" if opt.get("recommended") else ""
            context_parts.append(f"- {opt.get('title', '')}{rec}")

    context = "\n".join(context_parts)

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
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {
            "outcome": "failure",
            "resolution_summary": outcome_notes,
            "root_cause_confirmed": "",
            "root_cause_category": "unknown",
            "turning_point_signal": "",
            "why_previous_failed": "",
            "escalation_needed": True,
            "safety_tightening": ["Manual review required"],
            "risk_adjustment": 1.0,
        }

    outcome = result.get("outcome", "failure")

    # Update state based on outcome
    updated_risk = risk_score + float(result.get("risk_adjustment", 0.0))
    updated_risk = max(0.0, min(10.0, updated_risk))

    # Merge safety constraints
    existing_constraints = state.get("safety_constraints", [])
    new_constraints = list(set(existing_constraints + result.get("safety_tightening", [])))

    # Update escalation
    escalation_triggered = state.get("escalation_triggered", False)
    escalation_reasons = list(state.get("escalation_reasons", []))

    if outcome == "failure":
        failed_attempts += 1
        # Do not escalate on the first failed attempt – tighten safety and allow retry.
        # Escalate only after repeated failures or when the model strongly recommends it
        # on a subsequent attempt.
        if failed_attempts >= 2 and result.get("escalation_needed"):
            escalation_triggered = True
            escalation_reasons.append(
                f"Decision path failed (attempt #{failed_attempts}): {result.get('why_previous_failed', 'unknown')}"
            )
        # Per §9: multiple failures increase caution and should trigger escalation.
        if failed_attempts >= 3:
            escalation_triggered = True
            escalation_reasons.append(f"Multiple failed attempts ({failed_attempts})")

    # ── Gap A: Verification Gate (§13) ──────────────────────────────
    # An incident is NOT resolved until trigger conditions normalize,
    # verification steps are completed, and recorded.
    verification_confirmed = state.get("verification_confirmed", False)

    if outcome == "success" and not verification_confirmed:
        # Require verification before closing
        status = "AWAITING_VERIFICATION"
    elif outcome == "success" and verification_confirmed:
        status = "RESOLVED_PENDING_MEMORY"
    elif escalation_triggered:
        status = "ESCALATION_REQUIRED"
    else:
        status = "RETRY_DIAGNOSIS"

    # Update incident card with root_cause_category (Gap F)
    updated_card = dict(incident_card)
    if outcome == "success":
        updated_card["root_cause_category"] = result.get("root_cause_category", "unknown")

    output = {
        "outcome": outcome,
        "resolution_summary": result.get("resolution_summary", outcome_notes),
        "failed_attempts": failed_attempts,
        "risk_score": updated_risk,
        "safety_constraints": new_constraints,
        "escalation_triggered": escalation_triggered,
        "escalation_reasons": escalation_reasons,
        "incident_card": updated_card,
        "status": status,
        "current_node": "outcome_capture",
    }

    # Store confirmed root cause and turning point for memory write
    if outcome == "success":
        output["facts"] = list(state.get("facts", [])) + [
            {
                "key": "root_cause_confirmed",
                "value": result.get("root_cause_confirmed", ""),
                "confidence": 1.0,
                "source_step": 10,
                "contradiction": False,
            },
            {
                "key": "turning_point_signal",
                "value": result.get("turning_point_signal", ""),
                "confidence": 1.0,
                "source_step": 10,
                "contradiction": False,
            },
        ]

    return output

