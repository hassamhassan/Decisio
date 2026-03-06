"""
Decisio — Question Generation Agent

Generates ranked diagnostic questions following the 10-step diagnostic
framework to systematically reduce uncertainty about an incident.
This is the Question Engine node in the LangGraph workflow (§6.4).

10-Step Diagnostic Framework
-----------------------------
1. Check Trigger Condition
2. Check Internal Equipment
3. Check Upstream Equipment
4. Check Downstream Equipment
5. Check Control System
6. Check Instrumentation
7. Check Utilities
8. Check Process Conditions
9. Check Procedure/Human (when applicable)
10. Verification and Closure
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm import get_llm
from src.db.sync_queries import fetch_all_equipment
from src.state.state import (
    DIAGNOSTIC_CATEGORIES,
    DIAGNOSTIC_CATEGORY_LABELS,
    DecisioState,
    Question,
)


# ── Deduplication and context-aware narrowing ─────────────────────────
# Questions are filtered by _is_duplicate against qa_history; prompt instructs
# current diagnostic step and no repeat of already-completed steps.

def _is_duplicate(new_q: str, history: list[dict], threshold: float = 0.7) -> bool:
    """Check if a question is too similar to one already asked."""
    new_lower = new_q.lower().strip()
    new_words = set(new_lower.split())
    for qa in history:
        old_lower = qa.get("question", "").lower().strip()
        old_words = set(old_lower.split())
        if not new_words or not old_words:
            continue
        overlap = len(new_words & old_words) / max(len(new_words | old_words), 1)
        if overlap >= threshold:
            return True
    return False

# ── System prompt ────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are the Question Generation Agent for Decisio, an operational decision-support system.

Your job is to generate diagnostic questions following the **10-Step Diagnostic Framework**.
Each question MUST belong to one of these diagnostic steps (in priority order):

 1. **Trigger Condition** — What event/alarm/signal triggered awareness of the problem?
 2. **Internal Equipment** — Is the equipment itself functioning correctly (mechanical, electrical, structural)?
 3. **Upstream Equipment** — Are upstream feeds, supplies, or connected systems operating normally?
 4. **Downstream Equipment** — Are downstream processes, receivers, or consumers affected or causing back-pressure?
 5. **Control System** — Are DCS/PLC/SCADA logic, setpoints, tuning, and outputs correct?
 6. **Instrumentation** — Are sensors, transmitters, gauges, and analyzers reading accurately?
 7. **Utilities** — Are utilities (power, air, steam, cooling water, nitrogen, etc.) available and within spec?
 8. **Process Conditions** — Are process parameters (flow, pressure, temperature, composition) within normal range?
 9. **Procedure/Human** — Was a procedure missed, performed out of order, or was there a human error factor?
10. **Verification & Closure** — Confirm that the root cause is addressed and the system is stable.

You will receive:
- The Incident Card (structured summary)
- The current diagnostic step to focus on (1-10)
- Whether a process failure is suspected (important!)
- Any previous Q&A history
- Current hypotheses and confidence level (if available)

**Rules:**
1. Generate exactly 1 question for the CURRENT diagnostic step.
2. If safety_level is "unknown" or "danger", prefer a safety-related question when appropriate.
3. Do NOT repeat questions already asked in the Q&A history.
4. Questions must be answerable by the on-site operator.
5. Start from the current diagnostic step — do not repeat already-completed steps.

**CRITICAL — Process Failure Early Detection (§8):**
Process failures (missed procedures, incomplete handovers, human errors) are FIRST-CLASS
root causes. If process_failure_suspected is true, OR if the current step is 1-3,
consider asking a process/human question (category "procedure_human"). Examples:
- "Was there a recent shift change or handover before this incident?"
- "Were all standard procedures followed before the failure occurred?"

Return a JSON array of exactly 1 question object:

[
  {{
    "question": "The question text",
    "category": "<category_key>",
    "diagnostic_step": <step_number>,
    "rationale": "Why this question is important",
    "expected_answer_type": "yes_no | numeric | free_text | multiple_choice",
    "blocking_safety_flag": false
  }}
]

Valid category keys: trigger_condition, internal_equipment, upstream_equipment,
downstream_equipment, control_system, instrumentation, utilities,
process_conditions, procedure_human, verification_closure

Return ONLY the JSON array, no markdown fences, no extra text.
"""


# ── Agent function (LangGraph node) ──────────────────────────────────


def question_agent(state: DecisioState) -> DecisioState:
    """
    LangGraph node: Question Generation Agent.

    Generates diagnostic questions following the 10-step framework,
    starting from the current diagnostic step.

    Returns
    -------
    dict
        State update with ``questions``, ``current_diagnostic_step``,
        ``current_node``, and ``status``.
    """
    if state is None:
        state = {}
    incident_card = state.get("incident_card") or {}
    qa_history = state.get("qa_history") or []
    hypotheses = state.get("hypotheses") or []
    confidence = state.get("confidence") if state.get("confidence") is not None else 0.0
    current_step = state.get("current_diagnostic_step", 1)
    process_failure_suspected = state.get("process_failure_suspected", False)
    process_failure_indicators = state.get("process_failure_indicators") or []

    if not incident_card:
        raise ValueError("No incident_card in state. Run intake first.")

    # Clamp step to valid range
    current_step = max(1, min(current_step, 10))
    step_index = current_step - 1
    step_category = DIAGNOSTIC_CATEGORIES[step_index]
    step_label = DIAGNOSTIC_CATEGORY_LABELS[step_category]

    # ── Build context for the LLM ────────────────────────────────────
    context_parts = [
        "=== INCIDENT CARD ===",
        f"Summary: {incident_card.get('normalized_summary', incident_card.get('report', 'N/A'))}",
        f"Severity: {incident_card.get('severity', 'unknown')}",
        f"Safety Level: {incident_card.get('safety_level', 'unknown')}",
        f"Symptoms: {', '.join(incident_card.get('symptoms') or [])}",
        f"Asset: {incident_card.get('asset_id', 'not specified')}",
        "",
        f"=== PROCESS FAILURE ASSESSMENT ===",
        f"Process failure suspected: {'YES — include process question!' if process_failure_suspected else 'No'}",
    ]
    if process_failure_indicators:
        context_parts.append(f"Indicators: {', '.join(process_failure_indicators)}")

    context_parts.extend([
        "",
        f"=== CURRENT DIAGNOSTIC STEP ===",
        f"Step {current_step}/10: {step_label}",
        f"Category key: {step_category}",
    ])

    if qa_history:
        context_parts.append("\n=== PREVIOUS Q&A ===")
        for i, qa in enumerate(qa_history, 1):
            step_info = f" [Step {qa.get('diagnostic_step', '?')}]" if qa.get("diagnostic_step") else ""
            context_parts.append(
                f"Q{i}{step_info}: {qa.get('question', 'N/A')}\n"
                f"A{i}: {qa.get('answer', 'N/A')}"
            )

    if hypotheses:
        context_parts.append("\n=== CURRENT HYPOTHESES ===")
        for h in hypotheses:
            context_parts.append(
                f"- {h.get('description', 'N/A')} "
                f"(probability: {h.get('probability', 0):.0%})"
            )
        context_parts.append(f"\nOverall confidence: {confidence:.0%}")

    # Show remaining steps
    context_parts.append("\n=== DIAGNOSTIC STEPS REMAINING ===")
    for i in range(step_index, len(DIAGNOSTIC_CATEGORIES)):
        cat = DIAGNOSTIC_CATEGORIES[i]
        marker = " ← CURRENT" if i == step_index else ""
        context_parts.append(f"  {DIAGNOSTIC_CATEGORY_LABELS[cat]}{marker}")

    context = "\n".join(context_parts)

    llm = get_llm(temperature=0.3)

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=context),
    ]

    response = llm.invoke(messages)
    raw_content = response.content.strip()

    # ── Parse the LLM JSON response ──────────────────────────────────
    if raw_content.startswith("```"):
        raw_content = raw_content.split("\n", 1)[1]
        if raw_content.endswith("```"):
            raw_content = raw_content[: raw_content.rfind("```")]
        raw_content = raw_content.strip()

    try:
        questions_raw = json.loads(raw_content)
    except json.JSONDecodeError:
        raise ValueError(f"LLM did not return valid JSON: {raw_content}")

    # ── Validate through Pydantic ────────────────────────────────────
    validated_questions: list[dict] = []
    for q_data in questions_raw:
        try:
            # Ensure category and step are set correctly
            if "diagnostic_step" not in q_data:
                q_data["diagnostic_step"] = current_step
            q = Question(**q_data)
            validated_questions.append(q.model_dump())
        except Exception:
            continue

    # ── If machine is unclear, prepend a machine list question ────────
    incident_asset = (incident_card.get("asset_id") or "").strip()
    company_id = state.get("company_id")
    if (not incident_asset) and company_id is not None:
        equipment = fetch_all_equipment(company_id=company_id)
        if equipment:
            max_list = 8
            lines: list[str] = []
            for eq in equipment[:max_list]:
                label = f"{eq['id']} — {eq['name']}"
                if eq.get("process_line"):
                    label += f" (Line: {eq['process_line']})"
                lines.append(label)
            more_suffix = ""
            if len(equipment) > max_list:
                more_suffix = f"\n... and {len(equipment) - max_list} more machines."
            machine_list = "\n".join(f"- {ln}" for ln in lines) + more_suffix

            machine_question = Question(
                question=(
                    "Which machine is this incident about?\n"
                    "Please choose one machine from the list below and reply with its exact ID "
                    "(for example: CMP-01).\n\n"
                    f"Available machines:\n{machine_list}"
                ),
                category="trigger_condition",
                diagnostic_step=current_step,
                rationale="Clarify the affected equipment before detailed diagnosis.",
                expected_answer_type="free_text",
                blocking_safety_flag=False,
            )
            validated_questions.insert(0, machine_question.model_dump())

    # ── Deduplicate against Q&A history ────────────────────────────────
    deduped: list[dict] = []
    for q in validated_questions:
        if not _is_duplicate(q["question"], qa_history):
            deduped.append(q)
    validated_questions = deduped if deduped else validated_questions[:1]

    # Ask only 1 question at a time
    validated_questions = validated_questions[:1]

    # Guarantee at least one question
    if not validated_questions:
        raise ValueError("LLM generated questions, but none were valid or all were duplicates.")

    # ── Track completed steps + increment count ──────────────────────
    steps_completed = list(state.get("diagnostic_steps_completed") or [])
    if current_step not in steps_completed:
        steps_completed.append(current_step)

    prev_count = state.get("questions_asked_count", 0)

    return {
        "questions": validated_questions,
        "current_diagnostic_step": current_step,
        "questions_asked_count": prev_count + len(validated_questions),
        "diagnostic_steps_completed": steps_completed,
        "status": "DIAGNOSIS_LOOP",
        "current_node": "question_generation",
    }


