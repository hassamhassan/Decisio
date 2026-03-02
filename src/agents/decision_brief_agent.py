"""
Decisio — Decision Brief Agent

Generates the Decision Brief: decision options with risks, constraints,
and escalation guidance.  Never includes repair steps.  (§6.8 of the guide).

Boundary enforcement: prompt + programmatic sanitization (see sanitization.py).
Safety: options violating active safety_blocks are marked blocked_by_safety and non-recommended.
"""

from __future__ import annotations

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm import get_llm_for_brief
from src.state.state import DecisionBrief, DecisionOption, DecisioState
from src.sanitization import sanitize_decision_brief

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are the Decision Brief Agent for Decisio, an operational decision-support system.

Generate a Decision Brief with 2-4 decision options for the operator, based on
the incident analysis, hypotheses, facts, and safety constraints.

CRITICAL BOUNDARY: You must NEVER include:
- Repair steps or procedures
- Disassembly instructions
- Command sequences
- Operational execution steps

You provide DECISION OPTIONS only — what to decide, not how to execute.

CRITICAL: Do NOT recommend internal machine actions before isolating the trigger
condition. If only symptom-level hypotheses exist, warn that root cause is not
isolated and recommend further diagnosis before action.

Return a JSON object:

{{
  "analysis_summary": "Brief 2-3 sentence analysis summary of what was found",
  "root_cause_hypothesis": "Primary root cause hypothesis with confidence level",
  "options": [
    {{
      "option_id": 1,
      "title": "Short title",
      "description": "What this decision option involves (decision-level, not execution)",
      "risks": ["risk1", "risk2"],
      "constraints": ["constraint1"],
      "confidence": 0.0 to 1.0,
      "recommended": true/false,
      "risk_level": "low | medium | medium-high | high",
      "eta": "Estimated time, e.g. '10-15 min'"
    }}
  ],
  "risk_summary": "Overall risk assessment summary",
  "escalation_guidance": "When/why to escalate if this option doesn't work",
  "requires_escalation": true/false,
  "decision_authority": "Technician | Shift Engineer | Maintenance Manager | Plant Manager",
  "escalation_path": "Next escalation level if this decision fails"
}}

Rules:
- Exactly ONE option should have "recommended": true
- If escalation is already triggered, set requires_escalation to true
- Include safety constraints in each relevant option
- Risk descriptions should be specific and actionable
- decision_authority: for low/medium severity = Technician, high = Shift Engineer, critical = Plant Manager
- escalation_path: specify the next person/role to escalate to if the decision fails
- analysis_summary: always fill this with a concise analysis of the situation
- root_cause_hypothesis: state the primary suspected root cause
- risk_level: low for safe options, medium for standard, medium-high for options with notable risk, high for dangerous options
- NOT RECOMMENDED options MUST have risk_level medium-high or high and include explicit risk explanation in risks[]
- eta: provide realistic time estimate per option
- Return ONLY the JSON object, no markdown fences, no extra text.
"""


def decision_brief_agent(state: DecisioState) -> DecisioState:
    """
    LangGraph node: Decision Brief Agent.

    Generates the Decision Brief with options, risks, and constraints.
    """
    if state is None:
        state = {}
    incident_card = state.get("incident_card") or {}
    hypotheses = state.get("hypotheses") or []
    facts = state.get("facts") or []
    safety_constraints = state.get("safety_constraints") or []
    safety_blocks = state.get("safety_blocks") or []
    risk_score = state.get("risk_score") if state.get("risk_score") is not None else 5.0
    confidence = state.get("confidence") if state.get("confidence") is not None else 0.0
    qa_history = state.get("qa_history") or []
    retrieved_patterns = state.get("retrieved_patterns") or []
    escalation_triggered = state.get("escalation_triggered", False)

    context_parts = [
        "=== INCIDENT ===",
        f"Summary: {incident_card.get('normalized_summary', '')}",
        f"Asset: {incident_card.get('asset_id', 'unknown')}",
        f"Severity: {incident_card.get('severity', 'unknown')}",
        f"Safety: {incident_card.get('safety_level', 'unknown')}",
        f"Risk Score: {risk_score:.1f}/10",
        f"Confidence: {confidence:.0%}",
        f"Escalation Triggered: {escalation_triggered}",
    ]

    if hypotheses:
        context_parts.append("\n=== TOP HYPOTHESES ===")
        for h in hypotheses[:3]:
            context_parts.append(
                f"- {h.get('description', '')} ({h.get('probability', 0):.0%}, {h.get('category', '')})"
            )

    if facts:
        context_parts.append(f"\n=== KEY FACTS ({len(facts)} total) ===")
        for f in facts[-8:]:
            context_parts.append(f"- {f.get('key', '?')}: {f.get('value', '?')}")

    if safety_constraints:
        context_parts.append("\n=== SAFETY CONSTRAINTS ===")
        for c in safety_constraints:
            context_parts.append(f"- {c}")

    if safety_blocks:
        context_parts.append("\n=== SAFETY BLOCKS (HARD STOPS) ===")
        for b in safety_blocks:
            context_parts.append(f"- ⛔ {b}")

    if retrieved_patterns:
        context_parts.append("\n=== SIMILAR PAST DECISIONS ===")
        for p in retrieved_patterns:
            context_parts.append(f"- {p.get('title', '')}: {p.get('decision_taken', '')}")

    # Warn if only symptom-level hypotheses
    symptom_only = all(h.get("root_cause_layer") == "symptom" for h in hypotheses) if hypotheses else False
    if symptom_only:
        context_parts.append("\n=== ⚠️ WARNING ===")
        context_parts.append("All hypotheses are at SYMPTOM level. Root cause is NOT isolated.")
        context_parts.append("Recommend further diagnosis before action. Do NOT recommend internal machine actions.")

    context = "\n".join(context_parts)

    llm = get_llm_for_brief(temperature=0.2)
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
            "analysis_summary": "Unable to generate detailed analysis. Manual assessment required.",
            "root_cause_hypothesis": "Unknown — further diagnosis needed",
            "options": [
                {
                    "option_id": 1,
                    "title": "Escalate to specialist",
                    "description": "Refer incident to a subject-matter expert for detailed assessment",
                    "risks": ["Delay in resolution"],
                    "constraints": safety_constraints,
                    "confidence": 0.5,
                    "recommended": True,
                    "risk_level": "medium",
                    "eta": "Depends on expert availability",
                }
            ],
            "risk_summary": "Unable to generate detailed brief. Manual assessment required.",
            "escalation_guidance": "Escalate if no progress within 1 hour.",
            "requires_escalation": True,
        }

    # ── Boundary: programmatic sanitization (no execution instructions) ──
    result, _ = sanitize_decision_brief(result, safety_constraints, safety_blocks)

    # Validate options and apply safety blocking: options that violate active safety_blocks
    # (e.g. high-risk when blocks exist) are marked blocked_by_safety and must not be recommended (§6.7).
    validated_options = []
    has_safety_blocks = bool(safety_blocks)
    for opt in (result.get("options") or []):
        try:
            risk_level = (opt.get("risk_level") or "medium").lower()
            blocked = False
            if has_safety_blocks and risk_level == "high":
                blocked = True
                opt = {**opt, "blocked_by_safety": True, "recommended": False}
            else:
                opt = {**opt, "blocked_by_safety": opt.get("blocked_by_safety", False)}
            o = DecisionOption(**opt)
            validated_options.append(o.model_dump())
        except Exception:
            continue

    # If safety blocks active and LLM recommended a high-risk option, ensure exactly one recommended
    if has_safety_blocks and validated_options:
        recommended_count = sum(1 for o in validated_options if o.get("recommended"))
        if recommended_count == 0:
            # Pick first non-blocked option as recommended (safest path)
            for o in validated_options:
                if not o.get("blocked_by_safety"):
                    o["recommended"] = True
                    break
        elif recommended_count > 1:
            # Keep only first recommended
            first = True
            for o in validated_options:
                if o.get("recommended"):
                    o["recommended"] = first
                    first = False

    if not validated_options:
        validated_options.append(DecisionOption(
            option_id=1,
            title="Manual assessment required",
            description="Insufficient data for automated decision options",
            risks=["Potential delay"],
            recommended=True,
            risk_level="medium",
            eta="N/A",
        ).model_dump())

    brief = DecisionBrief(
        incident_id=incident_card.get("incident_id", "unknown"),
        analysis_summary=result.get("analysis_summary", ""),
        root_cause_hypothesis=result.get("root_cause_hypothesis", ""),
        options=validated_options,
        overall_confidence=confidence,
        risk_summary=result.get("risk_summary", ""),
        safety_constraints=safety_constraints,
        escalation_guidance=result.get("escalation_guidance", ""),
        requires_escalation=escalation_triggered or result.get("requires_escalation", False),
        decision_authority=result.get("decision_authority", "Technician level"),
        escalation_path=result.get("escalation_path", ""),
    )

    # Calculate MTTD (§27)
    from datetime import datetime, timezone
    diagnosis_end = datetime.now(timezone.utc).isoformat()
    mttd = 0.0
    start = state.get("diagnosis_start_time", "")
    if start:
        try:
            t0 = datetime.fromisoformat(start)
            t1 = datetime.now(timezone.utc)
            mttd = (t1 - t0).total_seconds()
        except Exception:
            pass

    return {
        "decision_brief": brief.model_dump(),
        "status": "BRIEF_GENERATED",
        "current_node": "decision_brief",
        "diagnosis_end_time": diagnosis_end,
        "mttd_seconds": mttd,
    }
