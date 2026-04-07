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
from src.data.escalation_matrix import get_escalation_levels
from src.agents.prompt_context import format_retrieved_patterns_for_llm

DECISION_BRIEF_PATTERN_PROMPT_CAP = 4

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are the Decision Brief Agent for Decisio, an operational decision-support system.

You are advising on a specific piece of equipment (for example CMP-01) that has
already gone through a structured diagnostic question flow. Your job is to
summarise the findings and propose clear, machine-focused decision options.

CRITICAL BOUNDARY: You must NEVER include:
- Repair steps or procedures
- Disassembly instructions
- Command sequences
- Operational execution steps

You provide DECISION OPTIONS only — what to decide, not how to execute.

FOCUS:
- Make every option specific to the actual machine/asset in the incident_card
  (e.g. refer to "CMP-01 air compressor" instead of generic "the equipment").
- Use the hypotheses and facts to distinguish between HUMAN / TECHNICAL /
  EXTERNAL causes, but do NOT output generic buckets like "Investigate human
  error", "Inspect for technical failure", or "Check external factors" as
  standalone option titles.
- Each option must describe a concrete decision about HOW TO HANDLE the machine
  (e.g. "Keep CMP-01 down and schedule expert inspection this shift",
  "Restart CMP-01 under enhanced monitoring and vibration limits enforced").

SAFETY:
- Do NOT recommend internal machine actions before isolating the trigger
  condition. If only symptom-level hypotheses exist, warn that root cause is
  not isolated and recommend further diagnosis before any restart or change of
  operating conditions.
- Always respect active safety_constraints and safety_blocks.

Return a JSON object:

{
  "analysis_summary": "Brief 2-3 sentence analysis summary of what was found, explicitly referencing the asset ID/name",
  "root_cause_hypothesis": "Primary root cause hypothesis with confidence level",
  "options": [
    {
      "option_id": 1,
      "title": "Short, machine-specific title (e.g. 'Keep CMP-01 Down for Expert Inspection')",
      "description": "Decision-level description of how CMP-01 should be handled (shutdown, restarted with conditions, monitored, etc.)",
      "risks": ["risk1", "risk2"],
      "constraints": ["constraint1"],
      "confidence": 0.0 to 1.0,
      "recommended": true/false,
      "risk_level": "low | medium | medium-high | high",
      "eta": "Estimated time, e.g. '10-15 min'"
    }
  ],
  "risk_summary": "Overall risk assessment summary, explicitly tied to this asset",
  "escalation_guidance": "When/why to escalate if this decision does not resolve the issue",
  "requires_escalation": true/false,
  "decision_authority": "Role name from the COMPANY ESCALATION MATRIX (if provided)",
  "escalation_path": "Next escalation level if this decision fails (role name from the COMPANY ESCALATION MATRIX, if provided)"
}

Rules:
- You MUST provide exactly 3 decision options, covering different approaches (e.g. conservative, moderate, aggressive).
- Exactly ONE option should have "recommended": true.
- If escalation is already triggered, set requires_escalation to true.
- Include safety constraints in each relevant option.
- Risk descriptions should be specific and actionable and refer to this machine
  (e.g. "further damage to CMP-01 drive motor if restarted without inspection").
- decision_authority and escalation_path MUST use specific roles defined in
  the COMPANY ESCALATION MATRIX, if provided. Do NOT invent generic titles.
- analysis_summary: always fill this with a concise analysis of the situation.
- root_cause_hypothesis: state the primary suspected root cause.
- risk_level: low for safe options, medium for standard, medium-high for options
  with notable risk, high for dangerous options.
- NOT RECOMMENDED options MUST have risk_level medium-high or high and include
  explicit risk explanation in risks[].
- eta: provide realistic time estimate per option.
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

    company_id = state.get("company_id")
    levels = get_escalation_levels(company_id=company_id)

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

    pat_block = format_retrieved_patterns_for_llm(
        retrieved_patterns,
        max_patterns=DECISION_BRIEF_PATTERN_PROMPT_CAP,
        heading="SIMILAR PAST DECISIONS",
    )
    if pat_block:
        context_parts.append("\n" + pat_block)

    if levels:
        context_parts.append("\n=== COMPANY ESCALATION MATRIX ===")
        # levels is a dict[int, dict] from get_escalation_levels
        for level_num, info in sorted(levels.items()):
            context_parts.append(
                f"- Level {level_num}: {info.get('name', '')}"
            )

    # Warn if only symptom-level hypotheses
    symptom_only = all(h.get("root_cause_layer") == "symptom" for h in hypotheses) if hypotheses else False
    if symptom_only:
        context_parts.append("\n=== ⚠️ WARNING ===")
        context_parts.append("All hypotheses are at SYMPTOM level. Root cause is NOT isolated.")
        context_parts.append("Recommend further diagnosis before action. Do NOT recommend internal machine actions.")

    context = "\n".join(context_parts)

    llm = get_llm_for_brief(model="gpt-4", temperature=0.2)
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
        except Exception as e:
            logger.warning("Failed to validate decision option: %s", e, exc_info=True)
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

    def _ensure_three_options(options: list[dict]) -> list[dict]:
        """
        Guarantee exactly 3 options with stable option_id 1..3 and exactly one recommended.
        This protects the UI and downstream agents from LLM variance and avoids the
        prior behavior of collapsing to a single option when escalation is triggered.
        """
        if not options:
            options = []

        # Prefer keeping recommended first, then the rest in original order.
        recommended = [o for o in options if o.get("recommended")]
        non_recommended = [o for o in options if not o.get("recommended")]
        ordered = (recommended[:1] + non_recommended + recommended[1:])

        # Trim to 3 if too many.
        ordered = ordered[:3]

        # Pad to 3 with safe, decision-level placeholders if too few.
        # (No procedures; just "what to decide".)
        pad_templates = [
            {
                "title": "Hold the asset in a safe state pending review",
                "description": "Keep the asset offline / in a safe state until decision authority reviews the findings and confirms next steps.",
                "risks": ["Extended downtime while awaiting decision authority review"],
                "constraints": [],
                "confidence": 0.5,
                "recommended": False,
                "risk_level": "low",
                "eta": "Until review is completed",
            },
            {
                "title": "Continue diagnosis before committing to action",
                "description": "Defer operational changes and gather additional evidence to isolate the root cause before any restart or load change decision.",
                "risks": ["Delayed restoration if the issue is benign"],
                "constraints": [],
                "confidence": 0.5,
                "recommended": False,
                "risk_level": "medium",
                "eta": "30–60 min",
            },
            {
                "title": "Transfer operations to an alternative asset / fallback plan",
                "description": "Route demand to an alternative asset or fallback plan while keeping the affected asset out of service until cleared.",
                "risks": ["Capacity constraints or secondary impacts on other assets"],
                "constraints": [],
                "confidence": 0.5,
                "recommended": False,
                "risk_level": "medium",
                "eta": "15–30 min",
            },
        ]

        while len(ordered) < 3:
            ordered.append({**pad_templates[len(ordered)]})

        # Enforce exactly one recommended.
        for i, o in enumerate(ordered):
            o["recommended"] = (i == 0)
            o["option_id"] = i + 1
            o.setdefault("constraints", [])
            o.setdefault("risks", [])
            o.setdefault("confidence", 0.5)
            o.setdefault("eta", "N/A")
            o.setdefault("risk_level", "medium")
            o["risk_level"] = (o.get("risk_level") or "medium").lower()

        return ordered

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

    # Map decision authority and escalation label from DB escalation levels.
    authority = result.get("decision_authority", "") or ""
    escalation_label = ""
    escalation_info = state.get("escalation") or {}
    current_level = escalation_info.get("escalation_level")

    if levels:
        level_keys = sorted(levels.keys())

        if escalation_triggered and current_level in levels:
            # Escalated: use the concrete level chosen by escalation_agent,
            # and show that SAME level both as authority and escalation label.
            auth_level = int(current_level)
            level_name = levels[auth_level].get("name", "") or authority
            authority = level_name
            escalation_label = level_name
        else:
            # Non-escalated: use lowest level as authority; no escalation label.
            if level_keys:
                auth_level = level_keys[0]
                authority = levels[auth_level].get("name", authority or "")

    # Always provide exactly 3 options.
    validated_options = _ensure_three_options(validated_options)

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
        decision_authority=authority or "Technician level",
        escalation_path=escalation_label,
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
        except Exception as e:
            logger.warning("Failed to calculate MTTD: %s", e, exc_info=True)

    return {
        "decision_brief": brief.model_dump(),
        "status": "BRIEF_GENERATED",
        "current_node": "decision_brief",
        "diagnosis_end_time": diagnosis_end,
        "mttd_seconds": mttd,
    }
