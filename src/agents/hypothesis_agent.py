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

from src.llm import get_llm_fast
from src.state.state import DecisioState, Hypothesis
from src.agents.prompt_context import (
    format_fact_line,
    format_qa_history_for_llm,
    format_retrieved_patterns_for_llm,
)

HYPOTHESIS_QA_PROMPT_WINDOW = 6
HYPOTHESIS_PATTERN_PROMPT_CAP = 4

SYSTEM_PROMPT = """\
You are the Hypothesis Update Agent for Decisio, an operational decision-support system.

Given the incident details, current facts, Q&A history, and any retrieved patterns,
maintain a ranked list of root-cause hypotheses.

Return a JSON object:

{{
  "hypotheses": [
    {{
      "description": "Clear description of the root cause hypothesis",
      "probability": 0.0 to 1.0,
      "category": "technical | process | external",
      "root_cause_layer": "symptom | trigger | root_cause",
      "supporting_facts": ["fact_key_1", "fact_key_2"],
      "contradicting_facts": []
    }}
  ],
  "overall_confidence": 0.0 to 1.0,
  "risk_score": 0.0 to 10.0,
  "reasoning": "Brief explanation of why confidence/risk changed"
}}

Root Cause Layer Classification (§13 — CRITICAL):
- "symptom": Observable effect (e.g. "machine stopped", "temperature high")
- "trigger": The condition that caused the protective trip/alarm (e.g. "high discharge pressure")
- "root_cause": The underlying reason (e.g. "downstream valve closed", "filter blocked")

You MUST classify each hypothesis into the correct layer. The system will
prevent action on symptom-level hypotheses until trigger/root_cause is found.

Information Source Priority (§6 — rank facts by source weight):
1. Safety constraints (absolute — never override)
2. Human input from the field operator (direct observation = strongest evidence)
3. Expert knowledge from past interventions
4. Decision Memory patterns (from Qdrant retrieval)
5. Technical manual knowledge
6. System integration readings
7. Cross-facility patterns

When weighting evidence:
- A field operator's direct observation outweighs a pattern match
- Safety-flagged facts should increase risk, never decrease it
- If expert/memory patterns conflict with operator observations, prioritize operator
- Process failures are FIRST-CLASS hypotheses (§8), not secondary afterthoughts

Rules:
- Provide 2-5 hypotheses ranked by probability (highest first)
- Probabilities should sum to approximately 1.0
- Process failures are first-class hypotheses (not just technical)
- If contradictions exist, lower confidence and raise risk
- If a retrieved pattern matches strongly, boost that hypothesis
- If process failure is suspected, ensure at least one process hypothesis ranks highly
- Return ONLY the JSON object, no markdown fences, no extra text.
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
    # on every single turn. Default: run every 3 answers once hypotheses exist.
    try:
        every_n = int(os.getenv("DECISIO_HYPOTHESIS_EVERY_N", "3"))
    except Exception:
        every_n = 3
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
            context_parts.append(format_fact_line(f, confidence="raw"))

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

    llm = get_llm_fast(temperature=0.2)
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
