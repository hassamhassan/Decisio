"""
Decisio — Problem & Machine Intake Agent

Guided two-phase intake:
  Phase 1 "symptoms"  — collect what the operator is observing.
  Phase 2 "machine"   — collect which machine is affected.
  Phase 3 "complete"  — both confirmed; proceed to incident_intake.

Memory / phase-persistence rules
----------------------------------
• reported_symptoms in state is the authoritative lock for phase 1.
  Once it is set, the agent NEVER re-asks for symptoms regardless of
  what intake_phase says or what the LLM returns.

• intake_phase in state is the authoritative lock for phase 2.
  Once it is "machine" or "complete", symptoms are never asked again.

• In "machine" phase the LLM only looks at the LATEST user answer
  (not the full history) to extract the machine ID. This prevents it
  from being confused by earlier symptom-description turns.

Why the loop happened
----------------------
The old code passed the full qa_history to _ask_symptoms on every
re-entry. When the machine-answer turn was in that history, the LLM
sometimes returned has_symptoms=False (because the machine name looked
like new context, not a symptom). That reset intake_phase to "symptoms"
and re-asked for the issue.
"""

from __future__ import annotations

import json
import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.llm import get_llm
from src.state.state import DecisioState
from src.data.assets import get_asset
from src.db.sync_queries import fetch_all_equipment

logger = logging.getLogger(__name__)


# ── Prompts ───────────────────────────────────────────────────────────

_SYMPTOMS_SYSTEM = """\
You are the intake assistant for Decisio, an operational decision-support system.

Your ONLY task right now: determine whether the operator has described any symptoms
or operational problems.

A symptom is ANY of: equipment stops, alarms, unusual noises, vibration, smoke,
smell, temperature change, pressure change, visible damage, unexpected behaviour.
A greeting ("hello", "hi") with NO issue description is NOT a symptom.

Analyse the conversation so far and return ONLY this JSON:
{{
  "has_symptoms": true or false,
  "symptoms_summary": "1-2 sentence plain-language summary of symptoms, or empty string",
  "next_message": "Your reply to the operator. If no symptoms yet, ask them to describe what they observe. If symptoms are clear, leave empty."
}}

IMPORTANT: Do NOT ask about machines. Do NOT advance to any other topic.
Return ONLY the JSON, no markdown."""

_MACHINE_SYSTEM = """\
You are the intake assistant for Decisio, an operational decision-support system.

The operator's symptoms have already been recorded: {symptoms}

Your ONLY task: identify which machine or piece of equipment is affected based on
the operator's latest message shown below.

{machine_list}

Return ONLY this JSON — no markdown:
{{
  "machine_name": "the exact machine ID or name the operator mentioned, or empty string if unclear",
  "next_message": "Your reply. If the machine is clear, leave empty. If unclear, ask the operator to pick from the list above."
}}

IMPORTANT: Do NOT ask about symptoms again. Focus only on the machine."""


# ── Helpers ───────────────────────────────────────────────────────────

def _original_report(full_report: str) -> str:
    """Strip API-appended [User Clarification]: blocks — return only the original message."""
    return full_report.split("[User Clarification]:")[0].strip()


def _latest_user_answer(qa_history: list[dict]) -> str:
    """Return the text of the most recent clarification answer."""
    for qa in reversed(qa_history):
        if qa.get("category") == "clarification":
            ans = (qa.get("answer") or "").strip()
            if ans:
                return ans
    return ""


def _clarification_history(qa_history: list[dict]) -> list:
    """Build AI/Human LangChain message pairs from clarification qa_history."""
    msgs = []
    for qa in qa_history:
        if qa.get("category") != "clarification":
            continue
        q = (qa.get("question") or "").strip()
        a = (qa.get("answer") or "").strip()
        if q:
            msgs.append(AIMessage(content=q))
        if a:
            msgs.append(HumanMessage(content=a))
    return msgs


def _machine_list_text(company_id: int | None) -> str:
    """Return a formatted machine list for the prompt."""
    try:
        equipment = fetch_all_equipment(company_id=company_id)
    except Exception:
        equipment = []

    if not equipment:
        return "No machines are currently registered in the database."

    lines = []
    for eq in (equipment[:12]):
        label = eq["id"]
        if eq.get("name") and eq["name"] != eq["id"]:
            label += f" — {eq['name']}"
        if eq.get("process_line"):
            label += f" (Line: {eq['process_line']})"
        lines.append(f"  • {label}")

    if len(equipment) > 12:
        lines.append(f"  … and {len(equipment) - 12} more.")

    return "Registered machines:\n" + "\n".join(lines)


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw[: raw.rfind("```")].strip()
    try:
        return json.loads(raw)
    except Exception:
        return {}


# ── Phase-specific LLM calls ──────────────────────────────────────────

def _run_symptoms_phase(original_report: str, qa_history: list[dict], llm) -> dict:
    """
    Ask the LLM: do we have symptoms yet? If yes, summarise them.
    Only passes turns that happened BEFORE a machine was first mentioned
    to avoid the LLM confusing machine names with symptom context.
    """
    messages: list = [SystemMessage(content=_SYMPTOMS_SYSTEM)]
    if original_report:
        messages.append(HumanMessage(content=original_report))
    # Only add clarification turns — this is already filtered to category="clarification"
    messages.extend(_clarification_history(qa_history))
    try:
        resp = llm.invoke(messages)
        return _parse_json(resp.content or "")
    except Exception as e:
        logger.warning(f"Symptoms LLM call failed: {e}")
        return {"has_symptoms": False, "symptoms_summary": "", "next_message": ""}


def _run_machine_phase(latest_answer: str, symptoms: str, machine_list: str, llm) -> dict:
    """
    Ask the LLM: what machine did the operator just name?
    Only passes the LATEST single answer — not the full history — so
    earlier symptom turns cannot confuse the extraction.
    """
    prompt = _MACHINE_SYSTEM.format(symptoms=symptoms, machine_list=machine_list)
    messages: list = [
        SystemMessage(content=prompt),
        HumanMessage(content=latest_answer or "(no answer provided yet)"),
    ]
    try:
        resp = llm.invoke(messages)
        return _parse_json(resp.content or "")
    except Exception as e:
        logger.warning(f"Machine LLM call failed: {e}")
        return {"machine_name": "", "next_message": ""}


# ── Agent ─────────────────────────────────────────────────────────────

def problem_intake_agent(state: DecisioState) -> DecisioState:
    """
    LangGraph node: Problem & Machine Intake.

    Phase determination (checked in order — cannot go backwards):

    1. If intake_phase == "complete"     → pass through (re-entry guard).
    2. If reported_symptoms is set       → skip to machine phase regardless
                                           of what intake_phase says.
    3. If intake_phase == "machine"      → machine phase.
    4. Otherwise                         → symptoms phase.
    """
    full_report: str = (state.get("report") or "").strip()
    if not full_report:
        return {
            "intake_phase": "symptoms",
            "problem_description": "",
            "machine_name": "",
            "current_node": "problem_intake",
        }

    # Re-entry guard
    if state.get("intake_phase") == "complete":
        return {"intake_phase": "complete", "current_node": "problem_intake"}

    llm = get_llm(temperature=0.4)
    company_id = state.get("company_id")

    # Only clarification turns — proper conversation memory
    qa_history: list[dict] = [
        qa for qa in (state.get("qa_history") or [])
        if qa.get("category") == "clarification"
    ]

    original = _original_report(full_report)
    machine_list = _machine_list_text(company_id)

    # ── Absolute phase lock: if symptoms already saved → go to machine ─
    # This prevents the LLM from re-asking symptoms on any re-entry.
    saved_symptoms: str = (
        state.get("reported_symptoms") or state.get("problem_description") or ""
    ).strip()

    in_machine_phase = (
        bool(saved_symptoms)                          # symptoms already saved
        or state.get("intake_phase") == "machine"    # or phase explicitly set
    )

    # ══════════════════════════════════════════════════════════════════
    # SYMPTOMS PHASE
    # ══════════════════════════════════════════════════════════════════
    if not in_machine_phase:
        result = _run_symptoms_phase(original, qa_history, llm)
        has_symptoms: bool = bool(result.get("has_symptoms"))
        symptoms_summary: str = (result.get("symptoms_summary") or "").strip()
        next_msg: str = (result.get("next_message") or "").strip()

        if not has_symptoms or not symptoms_summary:
            # Still waiting for symptoms
            return {
                "intake_phase": "symptoms",
                "problem_description": "",
                "machine_name": "",
                "reported_symptoms": "",
                "clarification_question": next_msg,
                "status": "CLARIFICATION_NEEDED",
                "current_node": "problem_intake",
            }

        # Symptoms confirmed — save them and ask about the machine.
        # (We do NOT try to extract the machine in the same LLM call;
        #  we let the next explicit turn handle that cleanly.)
        result_m = _run_machine_phase(original, symptoms_summary, machine_list, llm)
        machine_name: str = (result_m.get("machine_name") or "").strip()
        machine_msg: str = (result_m.get("next_message") or "").strip()

        # If the initial report already contained a valid machine, skip to complete
        if machine_name:
            asset_info = get_asset(machine_name, company_id=company_id)
            if asset_info:
                return {
                    "intake_phase": "complete",
                    "problem_description": symptoms_summary,
                    "reported_symptoms": symptoms_summary,
                    "machine_name": machine_name,
                    "clarification_question": None,
                    "status": "OPEN",
                    "current_node": "problem_intake",
                }

        return {
            "intake_phase": "machine",
            "problem_description": symptoms_summary,
            "reported_symptoms": symptoms_summary,    # ← locked; never re-asked
            "machine_name": "",
            "clarification_question": machine_msg,
            "status": "CLARIFICATION_NEEDED",
            "current_node": "problem_intake",
        }

    # ══════════════════════════════════════════════════════════════════
    # MACHINE PHASE
    # (symptoms are already locked in saved_symptoms / state)
    # ══════════════════════════════════════════════════════════════════
    symptoms_to_use = saved_symptoms

    # Only use the LATEST user answer for machine extraction.
    # Using the full history caused earlier symptom descriptions to
    # interfere with machine name extraction.
    latest = _latest_user_answer(qa_history)

    result = _run_machine_phase(latest, symptoms_to_use, machine_list, llm)
    machine_name = (result.get("machine_name") or "").strip()
    next_msg = (result.get("next_message") or "").strip()

    if not machine_name:
        return {
            "intake_phase": "machine",
            "problem_description": symptoms_to_use,
            "reported_symptoms": symptoms_to_use,
            "machine_name": "",
            "clarification_question": next_msg,
            "status": "CLARIFICATION_NEEDED",
            "current_node": "problem_intake",
        }

    # Validate against DB
    asset_info = get_asset(machine_name, company_id=company_id)
    if not asset_info:
        return {
            "intake_phase": "machine",
            "problem_description": symptoms_to_use,
            "reported_symptoms": symptoms_to_use,
            "machine_name": "",
            "clarification_question": next_msg,
            "status": "CLARIFICATION_NEEDED",
            "current_node": "problem_intake",
        }

    # Both symptoms and a valid machine — proceed to incident_intake
    return {
        "intake_phase": "complete",
        "problem_description": symptoms_to_use,
        "reported_symptoms": symptoms_to_use,
        "machine_name": machine_name,
        "clarification_question": None,
        "status": "OPEN",
        "current_node": "problem_intake",
    }
