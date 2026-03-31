"""
Decisio — Memory Write Agent

Stores verified decision patterns into Decision Memory (Qdrant)
after successful incident resolution.  (§5 step 8, §11 of the draft).

Boundary: stores decision logic only (decision_taken, root_cause,
turning_point_signal, why_symptoms_misleading, escalation_rule, delay_risk).
Does NOT store: repair steps, operating instructions, setpoints.
Tenant: company_id in every stored pattern for isolation.
"""

from __future__ import annotations

import logging

from src.state.state import DecisioState

logger = logging.getLogger(__name__)


def memory_write_agent(state: DecisioState) -> DecisioState:
    """
    LangGraph node: Memory Write Agent.

    Stores verified decision patterns into Qdrant after successful resolution.
    Only writes when outcome is "success" and we have confirmed root cause.
    """
    outcome = state.get("outcome", "")
    if outcome != "success":
        return {
            "memory_written": False,
            "status": state.get("status", "CLOSED"),
            "current_node": "memory_write",
        }

    incident_card = state.get("incident_card", {})
    hypotheses = state.get("hypotheses", [])
    facts = state.get("facts", [])
    qa_history = state.get("qa_history", [])
    chosen = state.get("chosen_decision_option") or {}
    resolution_summary = state.get("resolution_summary", "")
    failed_attempts = state.get("failed_attempts", 0)
    escalation_reasons = state.get("escalation_reasons", [])

    # Extract the confirmed root cause and turning-point signal
    root_cause = ""
    turning_point = ""
    why_misleading = ""
    escalation_rule = ""
    delay_risk = ""
    for f in facts:
        if f.get("key") == "root_cause_confirmed":
            root_cause = f.get("value", "")
        if f.get("key") == "turning_point_signal":
            turning_point = f.get("value", "")
        if f.get("key") == "why_symptoms_misleading":
            why_misleading = f.get("value", "")
        if f.get("key") == "escalation_rule":
            escalation_rule = f.get("value", "")
        if f.get("key") == "delay_risk":
            delay_risk = f.get("value", "")

    # Build the decision pattern to store (§11 expert capture)
    # What we capture: decision logic, NOT repair steps
    signals = []
    for f in facts:
        if f.get("key") not in ("root_cause_confirmed", "turning_point_signal",
                                 "why_symptoms_misleading", "escalation_rule", "delay_risk"):
            signals.append(f"{f.get('key', '?')}: {f.get('value', '?')}")

    from datetime import datetime, timezone

    company_id = state.get("company_id")
    prob_line = (incident_card.get("normalized_summary") or incident_card.get("report") or "Unknown incident").strip()
    asset = (incident_card.get("asset_id") or "").strip()
    problem_summary = f"{prob_line} (asset: {asset})" if asset else prob_line

    if chosen:
        opt_title = (chosen.get("title") or "").strip()
        opt_desc = (chosen.get("description") or "").strip()
        solution_for_memory = f"{opt_title}: {opt_desc}".strip(": ").strip() if (opt_title or opt_desc) else resolution_summary
    else:
        solution_for_memory = resolution_summary

    if not (solution_for_memory or "").strip():
        solution_for_memory = "Success — see incident notes"

    sel_opt_id = chosen.get("option_id")
    try:
        sel_opt_id = int(sel_opt_id) if sel_opt_id is not None else None
    except (TypeError, ValueError):
        sel_opt_id = None

    pattern = {
        "title": problem_summary[:500],
        "problem_summary": problem_summary[:2000],
        "signals": signals[:10],  # Top 10 signals
        "decision_taken": (solution_for_memory or "")[:5000],
        "resolution_summary": (resolution_summary or "")[:5000],
        "selected_option_id": sel_opt_id,
        "selected_option_title": (chosen.get("title") or "")[:500],
        "must_escalate": failed_attempts >= 2,
        "root_cause": root_cause,
        "root_cause_category": _get_root_cause_category(hypotheses),
        "turning_point_signal": turning_point,
        "why_symptoms_misleading": why_misleading,
        "why_first_line_failed": (
            f"Failed {failed_attempts} times before resolution"
            if failed_attempts > 0
            else ""
        ),
        "escalation_required_when": (
            "; ".join(escalation_reasons[:3]) if escalation_reasons else ""
        ),
        "escalation_rule": escalation_rule,
        "delay_risk": delay_risk,
        "question_count": len(qa_history),
        "asset_id": incident_card.get("asset_id", ""),
        "severity": incident_card.get("severity", ""),
        "resolution_timestamp": datetime.now(timezone.utc).isoformat(),
        "company_id": company_id,  # Tenant isolation metadata
    }

    # Store in Qdrant
    stored = False
    try:
        from src.agents.retrieval_agent import _get_qdrant, _get_embedder, _collection_name
        from qdrant_client.models import PointStruct
        import uuid

        client = _get_qdrant()
        embedder = _get_embedder()

        if company_id is None:
            logger.warning("Skipping Qdrant upsert: company_id missing (tenant isolation).")
        elif client and embedder:
            text = (
                f"Problem: {pattern['problem_summary']}. "
                f"Chosen decision: {pattern['decision_taken']}. "
                f"Root cause: {root_cause or 'n/a'}. "
                f"Signals: {', '.join(pattern['signals'][:5])}"
            )
            vector = embedder.encode(text).tolist()

            point = PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload=pattern,
            )
            client.upsert(
                collection_name=_collection_name,
                points=[point],
            )
            stored = True
            logger.info(f"Decision pattern stored: {pattern['title']}")
    except Exception as e:
        logger.error("Failed to write to Decision Memory: %s", e, exc_info=True)

    return {
        "memory_written": stored,
        "status": "CLOSED" if stored else "CLOSED_NO_MEMORY",
        "current_node": "memory_write",
    }


def _get_root_cause_category(hypotheses: list[dict]) -> str:
    """Extract the top hypothesis category."""
    if not hypotheses:
        return "unknown"
    top = max(hypotheses, key=lambda h: h.get("probability", 0))
    return top.get("category", "unknown")
