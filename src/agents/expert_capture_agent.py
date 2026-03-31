"""
Decisio — Expert Knowledge Capture Agent

Interactive flow to capture expert decision logic after resolution.
(§11 of the draft).

Boundary: prompt forbids repair steps, setpoints, execution guidance.
Stored payload: company_id, decision_taken, must_escalate, root_cause,
turning_point_signal, why_symptoms_misleading, escalation_rule, delay_risk
(governance/audit compliant). No repair or command sequences stored.
"""

from __future__ import annotations

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm import get_llm
from src.agents.prompt_context import format_qa_history_for_llm

EXPERT_CAPTURE_QA_PROMPT_WINDOW = 10
from src.state.state import DecisioState

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are the Expert Knowledge Capture Agent for Decisio.

An expert has resolved an incident and provided their input. Your job is to extract
structured decision knowledge — NOT repair steps.

From the expert's input, extract a JSON object:

{{
  "confirmed_root_cause": "The actual root cause confirmed by the expert",
  "root_cause_category": "technical | process | external",
  "turning_point_signal": "The key signal/observation that confirmed the root cause — the 'aha moment'",
  "why_symptoms_misleading": "Why initial symptoms pointed in wrong direction, if applicable",
  "why_first_line_failed": "Why the first-line technician couldn't resolve it",
  "escalation_rule": "When should similar cases be escalated in the future (specific conditions)",
  "delay_risk": "What would have happened if the decision was delayed further",
  "confidence_boundary": "At what level/role should this type of incident be handled",
  "pattern_signals": ["list of signals that should trigger early recognition of this pattern"],
  "must_escalate_in_future": true/false
}}

CRITICAL BOUNDARIES — do NOT extract:
- How the fix was performed (repair steps)
- Disassembly or installation instructions
- Operating procedures or setpoints
- Any direct execution guidance

You capture WHY the decision succeeded, not HOW the fix was done.

Return ONLY the JSON object, no markdown fences, no extra text.
"""


def expert_capture_agent(state: DecisioState) -> DecisioState:
    """
    LangGraph node: Expert Knowledge Capture Agent.

    Takes the expert's input after resolution and extracts structured
    decision knowledge for Decision Memory.
    """
    expert_input = state.get("outcome_notes", "")
    incident_card = state.get("incident_card", {})
    hypotheses = state.get("hypotheses", [])
    facts = state.get("facts", [])
    qa_history = state.get("qa_history", [])
    escalation = state.get("escalation", {})
    failed_attempts = state.get("failed_attempts", 0)

    if not expert_input:
        return {"current_node": "expert_capture"}

    # Build context
    context_parts = [
        "=== INCIDENT ===",
        f"Summary: {incident_card.get('normalized_summary', '')}",
        f"Asset: {incident_card.get('asset_id', 'unknown')}",
        f"Severity: {incident_card.get('severity', 'unknown')}",
        f"Failed attempts before expert: {failed_attempts}",
    ]

    if hypotheses:
        context_parts.append("\n=== HYPOTHESES AT TIME OF ESCALATION ===")
        for h in hypotheses[:3]:
            context_parts.append(f"- {h.get('description', '')} ({h.get('probability', 0):.0%})")

    if facts:
        context_parts.append(f"\n=== KNOWN FACTS ({len(facts)}) ===")
        for f in facts[-10:]:
            context_parts.append(f"- {f.get('key', '?')}: {f.get('value', '?')}")

    qa_block = format_qa_history_for_llm(
        qa_history,
        max_exchanges=EXPERT_CAPTURE_QA_PROMPT_WINDOW,
        heading=f"Q&A HISTORY ({len(qa_history)} exchanges)",
        mode="escalation",
    )
    if qa_block:
        context_parts.append("\n" + qa_block)

    # Decision brief options that were presented
    decision_brief = state.get("decision_brief", {})
    if decision_brief.get("options"):
        context_parts.append("\n=== DECISION OPTIONS PRESENTED ===")
        for opt in decision_brief["options"]:
            rec = " [RECOMMENDED]" if opt.get("recommended") else ""
            context_parts.append(f"- {opt.get('title', '')}{rec}: {opt.get('description', '')}")

    # Safety and escalation context
    safety_constraints = state.get("safety_constraints", [])
    if safety_constraints:
        context_parts.append("\n=== ACTIVE SAFETY CONSTRAINTS ===")
        for c in safety_constraints:
            context_parts.append(f"- {c}")

    if escalation:
        context_parts.append(f"\n=== ESCALATION DETAILS ===")
        context_parts.append(f"Level: {escalation.get('escalation_level', '?')} — {escalation.get('escalation_level_name', '')}")
        context_parts.append(f"Reasons: {', '.join(escalation.get('escalation_reasons', []))}")

    context_parts.append(f"\n=== EXPERT'S INPUT ===")
    context_parts.append(expert_input)

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
        capture = json.loads(raw)
    except json.JSONDecodeError:
        capture = {
            "confirmed_root_cause": expert_input,
            "root_cause_category": "unknown",
            "turning_point_signal": "",
            "why_symptoms_misleading": "",
            "why_first_line_failed": f"Required escalation after {failed_attempts} attempts",
            "escalation_rule": "Escalate similar incidents",
            "delay_risk": "Unknown",
            "confidence_boundary": "Expert level",
            "pattern_signals": [],
            "must_escalate_in_future": True,
        }

    # Store captured knowledge into facts for Memory Write Agent
    new_facts = list(facts)
    knowledge_facts = [
        ("root_cause_confirmed", capture.get("confirmed_root_cause", "")),
        ("turning_point_signal", capture.get("turning_point_signal", "")),
        ("why_symptoms_misleading", capture.get("why_symptoms_misleading", "")),
        ("escalation_rule", capture.get("escalation_rule", "")),
        ("delay_risk", capture.get("delay_risk", "")),
    ]

    for key, value in knowledge_facts:
        if value:
            new_facts.append({
                "key": key,
                "value": value,
                "confidence": 1.0,
                "source_step": 10,
                "contradiction": False,
            })

    # Write to Qdrant via Memory Write Agent logic
    stored = _store_expert_pattern(state, capture)

    return {
        "facts": new_facts,
        "outcome": "success",
        "resolution_summary": capture.get("confirmed_root_cause", expert_input),
        "memory_written": stored,
        "status": "CLOSED" if stored else "CLOSED_NO_MEMORY",
        "current_node": "expert_capture",
    }


def _store_expert_pattern(state: DecisioState, capture: dict) -> bool:
    """Store the expert's decision pattern into Qdrant."""
    incident_card = state.get("incident_card", {})
    qa_history = state.get("qa_history", [])
    failed_attempts = state.get("failed_attempts", 0)

    company_id = state.get("company_id")
    pattern = {
        "title": f"{incident_card.get('normalized_summary', 'Unknown')} — {capture.get('confirmed_root_cause', 'resolved')}",
        "signals": capture.get("pattern_signals", []),
        "decision_taken": capture.get("confirmed_root_cause", ""),
        "must_escalate": capture.get("must_escalate_in_future", True),
        "root_cause": capture.get("confirmed_root_cause", ""),
        "root_cause_category": capture.get("root_cause_category", "unknown"),
        "turning_point_signal": capture.get("turning_point_signal", ""),
        "why_first_line_failed": capture.get("why_first_line_failed", ""),
        "escalation_rule": capture.get("escalation_rule", ""),
        "delay_risk": capture.get("delay_risk", ""),
        "confidence_boundary": capture.get("confidence_boundary", ""),
        "why_symptoms_misleading": capture.get("why_symptoms_misleading", ""),
        "question_count": len(qa_history),
        "failed_attempts": failed_attempts,
        "company_id": company_id,  # Tenant isolation for Decision Memory
    }

    try:
        from src.agents.retrieval_agent import _get_qdrant, _get_embedder, _collection_name
        from qdrant_client.models import PointStruct
        import uuid

        client = _get_qdrant()
        embedder = _get_embedder()

        if client and embedder:
            text = f"{pattern['title']}. Signals: {', '.join(pattern['signals'][:5])}"
            vector = embedder.encode(text).tolist()

            point = PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload=pattern,
            )
            client.upsert(collection_name=_collection_name, points=[point])
            logger.info(f"Expert pattern stored: {pattern['title']}")
            return True
    except Exception as e:
        logger.warning(f"Failed to store expert pattern: {e}")

    return False
