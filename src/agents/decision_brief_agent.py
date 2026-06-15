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
from src.agents.prompt_context import (
    format_fact_line,
    format_retrieved_patterns_for_llm,
    get_language_instruction,
)

DECISION_BRIEF_PATTERN_PROMPT_CAP = 4

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are the Decision Brief Agent for Decisio, an operational decision-support system.

You have access to a completed diagnostic Q&A session, hypotheses, facts, and
equipment manual excerpts. Your job is to deliver three CONCRETE, ACTIONABLE
decision options about what should be done with this specific asset RIGHT NOW.

━━━ ABSOLUTE PROHIBITION ━━━
NEVER write an option that says any of these:
  ✗ "Wait for expert / technician / specialist"
  ✗ "Consult the technical team"
  ✗ "Await further investigation"
  ✗ "Continue diagnosis"
  ✗ "Escalate and wait"
  ✗ Any option whose entire substance is deferring to a person or process

These are NON-DECISIONS. Every option MUST describe a concrete operational
outcome for the equipment (keep it down, restart it under conditions,
reduce load, isolate the fault loop, switch to standby, etc.).

━━━ WHAT YOU DO ━━━
Provide DECISION OPTIONS — what to decide and under what conditions,
NOT how to execute (no step-by-step repair or disassembly instructions).

Good option titles look like:
  ✓ "Shut Down {ASSET} and Inspect Bearings This Shift"
  ✓ "Restart {ASSET} at 60% Load Under Enhanced Vibration Monitoring"
  ✓ "Isolate {ASSET} and Switch Production to Standby Unit"
  ✓ "Restore {ASSET} with Forced Air Cooling and 2-Hour Observation Window"

Bad option titles (FORBIDDEN):
  ✗ "Escalate to Specialist"
  ✗ "Await Technical Review"
  ✗ "Continue Investigating"

━━━ OPTION STRUCTURE ━━━
Option 1 — Conservative (safest, lowest risk, possibly longer downtime)
Option 2 — Moderate (balanced; USE THIS as "recommended": true)
Option 3 — Aggressive (fastest restoration, higher operational risk)

Each option's description must:
- Name the asset explicitly (e.g. "CMP-01")
- State the immediate action (shutdown / restart / reduce load / isolate / switch)
- State the condition or monitoring requirement (e.g. "with vibration ≤ 3 mm/s")
- State the operational outcome (production continues / halted / partial capacity)

━━━ EVIDENCE USAGE ━━━
- Use the Q&A HISTORY to ground your options in confirmed symptoms and conditions
- Use KEY FACTS as hard constraints (e.g. if temperature was confirmed high, options must address cooling)
- Use EQUIPMENT MANUAL EXCERPTS for operating limits, reset procedures guidance
- Use SIMILAR PAST DECISIONS as precedent — prefer proven approaches when similarity ≥ 75%
- Use TOP HYPOTHESES to set risk levels — high-confidence root causes allow more decisive options

━━━ SAFETY RULES ━━━
- If SAFETY BLOCKS (HARD STOPS) are present, mark any option that triggers them as
  blocked_by_safety: true and recommended: false
- Always include active safety_constraints in the relevant option's constraints field
- If only symptom-level evidence exists (no confirmed root cause), the Conservative
  option MUST be the recommended one

Return a JSON object with no markdown fences:

{
  "analysis_summary": "2-3 sentences naming the asset, confirmed findings from the Q&A, and the primary fault mode",
  "root_cause_hypothesis": "Primary root cause with confidence level and supporting evidence from the Q&A",
  "options": [
    {
      "option_id": 1,
      "title": "Concrete, asset-specific title",
      "description": "What to do with the asset, under what conditions, with what outcome",
      "risks": ["Specific risk tied to this asset and this option"],
      "constraints": ["Specific safety or operational constraint"],
      "confidence": 0.0,
      "recommended": false,
      "risk_level": "low | medium | medium-high | high",
      "eta": "Realistic time estimate e.g. '15-20 min'"
    }
  ],
  "risk_summary": "Overall risk if no action is taken, tied to this specific asset",
  "escalation_guidance": "Specific trigger condition for escalation (e.g. 'escalate if vibration exceeds 5 mm/s after restart')",
  "requires_escalation": false,
  "decision_authority": "Role from COMPANY ESCALATION MATRIX or 'Shift Supervisor'",
  "escalation_path": "Next role from COMPANY ESCALATION MATRIX if decision fails"
}
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

    asset_id = incident_card.get("asset_id", "unknown")

    context_parts = [
        "=== INCIDENT ===",
        f"Summary: {incident_card.get('normalized_summary', '')}",
        f"Asset: {asset_id}",
        f"Severity: {incident_card.get('severity', 'unknown')}",
        f"Safety: {incident_card.get('safety_level', 'unknown')}",
        f"Risk Score: {risk_score:.1f}/10",
        f"Confidence: {confidence:.0%}",
        f"Escalation Triggered: {escalation_triggered}",
    ]

    # ── Q&A history (most critical context for concrete decisions) ────
    if qa_history:
        context_parts.append(f"\n=== DIAGNOSTIC Q&A HISTORY ({len(qa_history)} exchanges) ===")
        for i, qa in enumerate(qa_history, 1):
            q = qa.get("question", "")
            a = qa.get("answer", "")
            context_parts.append(f"Q{i}: {q}")
            context_parts.append(f"A{i}: {a}")

    if hypotheses:
        context_parts.append("\n=== TOP HYPOTHESES ===")
        for h in hypotheses[:3]:
            context_parts.append(
                f"- {h.get('description', '')} ({h.get('probability', 0):.0%}, "
                f"category={h.get('category', '')}, layer={h.get('root_cause_layer', '?')})"
            )

    if facts:
        context_parts.append(f"\n=== KEY FACTS ({len(facts)} total) ===")
        for f in facts[-10:]:
            context_parts.append(format_fact_line(f))

    if safety_constraints:
        context_parts.append("\n=== SAFETY CONSTRAINTS ===")
        for c in safety_constraints:
            context_parts.append(f"- {c}")

    if safety_blocks:
        context_parts.append("\n=== SAFETY BLOCKS (HARD STOPS) ===")
        for b in safety_blocks:
            context_parts.append(f"- ⛔ {b}")

    # ── Equipment manual context from Qdrant ──────────────────────────
    try:
        from src.services.manual_service import retrieve_manual_chunks
        manual_query = incident_card.get("normalized_summary", "") or asset_id
        manual_chunks = retrieve_manual_chunks(
            equipment_id=asset_id,
            query_text=manual_query,
            company_id=int(company_id) if company_id else 0,
            limit=4,
        )
        if manual_chunks:
            context_parts.append("\n=== EQUIPMENT MANUAL EXCERPTS ===")
            for chunk in manual_chunks:
                text = (chunk.get("text") or "").strip()
                score = chunk.get("score", 0)
                if text:
                    context_parts.append(f"[relevance {score:.0%}] {text[:600]}")
    except Exception as e:
        logger.debug("Manual context unavailable for brief: %s", e)

    pat_block = format_retrieved_patterns_for_llm(
        retrieved_patterns,
        max_patterns=DECISION_BRIEF_PATTERN_PROMPT_CAP,
        heading="SIMILAR PAST DECISIONS",
    )
    if pat_block:
        context_parts.append("\n" + pat_block)

    if levels:
        context_parts.append("\n=== COMPANY ESCALATION MATRIX ===")
        for level_num, info in sorted(levels.items()):
            context_parts.append(
                f"- Level {level_num}: {info.get('name', '')}"
            )

    # ── Symptom-only warning — conservative option must be recommended ─
    symptom_only = all(h.get("root_cause_layer") == "symptom" for h in hypotheses) if hypotheses else False
    if symptom_only:
        context_parts.append("\n=== ⚠️ NOTE ===")
        context_parts.append(
            "All hypotheses are symptom-level only — root cause not isolated. "
            "Conservative option MUST be recommended. Options must still be concrete "
            "operational decisions, NOT 'continue diagnosis' or 'wait for expert'."
        )

    context = "\n".join(context_parts)

    lang_instruction = get_language_instruction(state.get("language"))
    llm = get_llm_for_brief(model="gpt-4", temperature=0.2)

    def _strip_fences(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[: text.rfind("```")]
        return text.strip()

    response = llm.invoke([
        SystemMessage(content=SYSTEM_PROMPT + lang_instruction),
        HumanMessage(content=context),
    ])
    raw = _strip_fences(response.content)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # First attempt produced invalid JSON — retry with an explicit repair prompt
        logger.warning("Decision brief: first LLM response was not valid JSON, retrying.")
        repair_prompt = (
            "Your previous response was not valid JSON. "
            "Return ONLY a raw JSON object — no markdown, no code fences, no extra text. "
            "The JSON must follow this exact schema:\n"
            "{\n"
            '  "analysis_summary": "...",\n'
            '  "root_cause_hypothesis": "...",\n'
            '  "options": [\n'
            '    {"option_id":1,"title":"...","description":"...","risks":["..."],'
            '"constraints":[],"confidence":0.8,"recommended":true,"risk_level":"low","eta":"..."},\n'
            '    {"option_id":2,"title":"...","description":"...","risks":["..."],'
            '"constraints":[],"confidence":0.7,"recommended":false,"risk_level":"medium","eta":"..."},\n'
            '    {"option_id":3,"title":"...","description":"...","risks":["..."],'
            '"constraints":[],"confidence":0.6,"recommended":false,"risk_level":"medium-high","eta":"..."}\n'
            "  ],\n"
            '  "risk_summary": "...",\n'
            '  "escalation_guidance": "...",\n'
            '  "requires_escalation": false,\n'
            '  "decision_authority": "...",\n'
            '  "escalation_path": "..."\n'
            "}\n\n"
            f"Use the incident context already provided. Asset: {asset_id}. "
            "All options must be concrete operational decisions for this asset — "
            "NO 'wait for expert', NO 'continue diagnosis'."
        )
        retry_response = llm.invoke([
            SystemMessage(content=SYSTEM_PROMPT + lang_instruction),
            HumanMessage(content=context),
            HumanMessage(content=repair_prompt),
        ])
        raw2 = _strip_fences(retry_response.content)
        try:
            result = json.loads(raw2)
        except json.JSONDecodeError:
            logger.error("Decision brief: retry also failed to produce valid JSON. Raw: %s", raw2[:500])
            raise RuntimeError("Decision brief LLM returned invalid JSON on both attempts.")

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
        _a = asset_id if asset_id and asset_id != "unknown" else "the asset"
        pad_templates = [
            {
                "title": f"Keep {_a} Offline and Perform Targeted Inspection",
                "description": (
                    f"Shut down {_a} and perform a targeted inspection focused on "
                    "the confirmed fault symptoms. Clear the fault condition before "
                    "any restart attempt. Production impact must be managed separately."
                ),
                "risks": [f"Extended downtime for {_a} until inspection is complete"],
                "constraints": [],
                "confidence": 0.5,
                "recommended": False,
                "risk_level": "low",
                "eta": "30–90 min",
            },
            {
                "title": f"Restart {_a} at Reduced Load with Enhanced Monitoring",
                "description": (
                    f"Restart {_a} at 50–70% of rated load. Monitor critical parameters "
                    "(vibration, temperature, pressure) every 15 minutes for the first hour. "
                    "Return to full load only after one stable hour with no abnormal readings."
                ),
                "risks": [
                    f"Fault may recur on {_a} if root cause is not fully resolved",
                    "Risk of secondary damage if parameters exceed safe limits during monitored restart",
                ],
                "constraints": [],
                "confidence": 0.45,
                "recommended": False,
                "risk_level": "medium-high",
                "eta": "10–20 min to restart, 60 min monitoring",
            },
            {
                "title": f"Isolate {_a} and Route Load to Standby Unit",
                "description": (
                    f"Take {_a} fully out of service and redirect its production load "
                    "to the standby or backup unit. This preserves production continuity "
                    f"while {_a} undergoes a complete fault investigation at a safe pace."
                ),
                "risks": ["Standby unit may have lower rated capacity", "Switchover may temporarily reduce throughput"],
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
        _a = asset_id if asset_id and asset_id != "unknown" else "the asset"
        validated_options.append(DecisionOption(
            option_id=1,
            title=f"Keep {_a} in Safe Offline State",
            description=(
                f"Maintain {_a} offline. Perform a physical walkdown of the reported fault "
                "condition and verify all safety interlocks before any restart attempt."
            ),
            risks=[f"Downtime on {_a} until fault condition is physically cleared"],
            recommended=True,
            risk_level="low",
            eta="Until fault cleared",
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
        # Clear pending diagnostic questions so reload/API does not repeat the
        # last asked question alongside qa_history (brief path skips question_generation).
        "questions": [],
    }
