"""
Decisio — Hypothesis Update Agent

Maintains ranked hypotheses across technical/process causes.
Computes confidence and risk delta after each new fact.
(§6.6 of the guide).
"""

from __future__ import annotations

import json
import os

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm import get_llm
from src.state.state import DecisioState, Hypothesis
from src.agents.prompt_context import (
    format_qa_history_for_llm,
    format_retrieved_patterns_for_llm,
)

HYPOTHESIS_QA_PROMPT_WINDOW = 6
HYPOTHESIS_PATTERN_PROMPT_CAP = 4

SYSTEM_PROMPT = """\
Hypothesis Update Agent for Decisio. Maintain ranked root-cause hypotheses.

Return ONLY JSON:
{{
  "hypotheses": [{{
    "description": "root cause hypothesis",
    "probability": 0.0-1.0,
    "category": "technical|process|external",
    "root_cause_layer": "symptom|trigger|root_cause",
    "supporting_facts": ["fact_key_1"],
    "contradicting_facts": []
  }}],
  "overall_confidence": 0.0-1.0,
  "risk_score": 0.0-10.0,
  "reasoning": "brief explanation of confidence/risk change"
}}

Root Cause Layers: "symptom"=observable effect, "trigger"=condition causing trip/alarm, "root_cause"=underlying reason. You MUST classify each correctly.

Evidence priority (highest→lowest): safety constraints > operator observation > expert knowledge > memory patterns > technical manuals > system readings > cross-facility patterns.
Operator observations outweigh pattern matches. Safety facts increase risk, never decrease.

Rules: 2-5 hypotheses ranked by probability (sum≈1.0). Process failures are first-class hypotheses.
Contradictions → lower confidence, raise risk. Strong retrieved pattern → boost that hypothesis.
If process failure suspected → ensure ≥1 process hypothesis ranks highly.
Return ONLY JSON, no markdown fences.
"""


def hypothesis_update_agent(state: DecisioState) -> DecisioState:
    """
    LangGraph node: Hypothesis Update Agent.

    Updates ranked hypotheses based on current facts, Q&A history,
    and retrieved patterns.
    """
    if state is None:
        state = {}

    # Latency control: hypothesis updates are expensive and usually don't need to run
    # on every single turn. Default: run every 2 answers once hypotheses exist.
    try:
        every_n = int(os.getenv("DECISIO_HYPOTHESIS_EVERY_N", "2"))
    except Exception:
        every_n = 2
    every_n = max(1, every_n)
    questions_asked = int(state.get("questions_asked_count", 0) or 0)
    existing_hypotheses = state.get("hypotheses") or []
    if existing_hypotheses and every_n > 1 and (questions_asked % every_n) != 0:
        return {"current_node": "hypothesis_update"}

    incident_card = state.get("incident_card") or {}
    facts = state.get("facts") or []
    qa_history = state.get("qa_history") or []
    retrieved_patterns = state.get("retrieved_patterns") or []
    existing_hypotheses = existing_hypotheses
    contradictions = state.get("contradictions") or []
    process_failure_suspected = state.get("process_failure_suspected", False)

    # Build context
    context_parts = [
        "=== INCIDENT ===",
        f"Summary: {incident_card.get('normalized_summary', '')}",
        f"Severity: {incident_card.get('severity', 'unknown')}",
        f"Safety: {incident_card.get('safety_level', 'unknown')}",
    ]

    # Gap D: Process failure bias
    if process_failure_suspected:
        context_parts.append("\n=== ⚠️ PROCESS FAILURE SUSPECTED ===")
        indicators = state.get("process_failure_indicators") or []
        context_parts.append("Process failure is suspected as a first-class root cause.")
        context_parts.append("Ensure at least one process/human hypothesis ranks highly.")
        if indicators:
            for ind in indicators:
                context_parts.append(f"- Indicator: {ind}")

    if facts:
        context_parts.append("\n=== KNOWN FACTS ===")
        # Cap to keep prompts small and fast.
        for f in facts[-14:]:
            context_parts.append(f"- {f.get('key', '?')}: {f.get('value', '?')} (confidence: {f.get('confidence', 0)})")

    qa_block = format_qa_history_for_llm(
        qa_history,
        max_exchanges=HYPOTHESIS_QA_PROMPT_WINDOW,
        heading=f"Q&A HISTORY ({len(qa_history)} total)",
        mode="plain",
    )
    if qa_block:
        context_parts.append("\n" + qa_block)

    pat_block = format_retrieved_patterns_for_llm(
        retrieved_patterns,
        max_patterns=HYPOTHESIS_PATTERN_PROMPT_CAP,
        heading="SIMILAR PAST INCIDENTS",
    )
    if pat_block:
        context_parts.append("\n" + pat_block)

    if existing_hypotheses:
        context_parts.append("\n=== CURRENT HYPOTHESES ===")
        for h in existing_hypotheses:
            context_parts.append(f"- {h.get('description', '')} ({h.get('probability', 0):.0%})")

    if contradictions:
        context_parts.append(f"\n=== CONTRADICTIONS ===")
        for c in contradictions:
            context_parts.append(f"- {c}")

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
        return {
            "confidence": state.get("confidence") if state.get("confidence") is not None else 0.3,
            "risk_score": state.get("risk_score") if state.get("risk_score") is not None else 5.0,
            "current_node": "hypothesis_update",
        }

    # Validate hypotheses; ensure root_cause_layer is always set (default "symptom" for safety §13).
    # symptom_only check in decision_brief_agent prevents recommending internal machine actions until isolated.
    validated = []
    for h_data in result.get("hypotheses", []):
        try:
            layer = (h_data.get("root_cause_layer") or "symptom").strip().lower()
            if layer not in ("symptom", "trigger", "root_cause"):
                layer = "symptom"
            h_data = {**h_data, "root_cause_layer": layer}
            h = Hypothesis(**h_data)
            validated.append(h.model_dump())
        except Exception:
            continue

    confidence = float(result.get("overall_confidence", 0.3))
    risk_score = float(result.get("risk_score") or state.get("risk_score") or 5.0)

    return {
        "hypotheses": validated if validated else existing_hypotheses,
        "confidence": confidence,
        "risk_score": risk_score,
        "current_node": "hypothesis_update",
    }
