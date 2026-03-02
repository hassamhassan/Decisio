"""
Decisio — Answer Interpreter Agent

Parses user answers into structured facts, detects contradictions,
and produces signal flags.  (§6.5 of the guide).
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm import get_llm
from src.state.state import DecisioState, Fact, QAPair

SYSTEM_PROMPT = """\
You are the Answer Interpreter Agent for Decisio, an operational decision-support system.

You receive a diagnostic question and the operator's answer. Your job is to:
1. Extract structured facts from the answer
2. Detect any contradictions with previously known facts
3. Produce signal flags for safety and escalation

Return a JSON object:

{{
  "facts": [
    {{
      "key": "descriptive_fact_key",
      "value": "extracted value or observation",
      "confidence": 0.9
    }}
  ],
  "signals": ["list of signal flags, e.g. 'safety_concern', 'contradiction', 'needs_escalation', 'normal'"],
  "contradictions": ["list of contradictions with previous facts, empty if none"],
  "answer_quality": "complete | partial | unknown | irrelevant"
}}

Rules:
- Extract ALL distinct facts from the answer
- If the operator says "I don't know", set answer_quality to "unknown" and add "uncertainty" signal
- If the answer contradicts a previous fact, add "contradiction" signal
- If the answer reveals a safety concern, add "safety_concern" signal
- Return ONLY the JSON object, no markdown fences, no extra text.
"""


def answer_interpreter_agent(state: DecisioState) -> DecisioState:
    """
    LangGraph node: Answer Interpreter Agent.

    Takes the current question and user answer, extracts facts,
    detects contradictions, and produces signal flags.
    """
    if state is None:
        state = {}
    user_answer = state.get("user_answer", "")
    current_question = state.get("current_question") or {}
    qa_history = state.get("qa_history") or []
    existing_facts = state.get("facts") or []
    current_step = state.get("current_diagnostic_step", 1)

    if not user_answer or not current_question:
        return {"current_node": "answer_interpreter"}

    # Build context
    context_parts = [
        f"Question: {current_question.get('question', 'N/A')}",
        f"Category: {current_question.get('category', 'N/A')}",
        f"Diagnostic Step: {current_step}",
        f"\nOperator Answer: {user_answer}",
    ]

    if existing_facts:
        context_parts.append("\n=== PREVIOUSLY KNOWN FACTS ===")
        for f in existing_facts:
            context_parts.append(f"- {f.get('key', '?')}: {f.get('value', '?')}")

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
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {
            "facts": [{"key": "raw_answer", "value": user_answer, "confidence": 0.5}],
            "signals": [],
            "contradictions": [],
            "answer_quality": "partial",
        }

    # Build validated facts
    new_facts = list(existing_facts)
    for f_data in parsed.get("facts", []):
        try:
            fact = Fact(
                key=f_data.get("key", "unknown"),
                value=str(f_data.get("value", "")),
                confidence=float(f_data.get("confidence", 0.5)),
                source_step=current_step,
                contradiction=False,
            )
            new_facts.append(fact.model_dump())
        except Exception:
            continue

    # Record Q&A
    qa_pair = QAPair(
        question=current_question.get("question", ""),
        answer=user_answer,
        category=current_question.get("category", "general"),
        diagnostic_step=current_step,
        signals=parsed.get("signals", []),
    )

    updated_qa_history = list(qa_history)
    updated_qa_history.append(qa_pair.model_dump())

    # Track contradictions
    existing_contradictions = state.get("contradictions") or []
    new_contradictions = list(existing_contradictions)
    new_contradictions.extend(parsed.get("contradictions", []))

    # Check for escalation signals
    escalation_triggered = state.get("escalation_triggered", False)
    escalation_reasons = list(state.get("escalation_reasons") or [])
    signals = parsed.get("signals", [])

    if "needs_escalation" in signals:
        escalation_triggered = True
        escalation_reasons.append(f"Escalation signal from answer at step {current_step}")
    if "safety_concern" in signals:
        escalation_reasons.append(f"Safety concern detected at step {current_step}")

    questions_asked = state.get("questions_asked_count", 0) + 1

    return {
        "facts": new_facts,
        "qa_history": updated_qa_history,
        "contradictions": new_contradictions,
        "questions_asked_count": questions_asked,
        "escalation_triggered": escalation_triggered,
        "escalation_reasons": escalation_reasons,
        "current_node": "answer_interpreter",
    }
