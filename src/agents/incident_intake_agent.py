"""
Decisio — Incident Intake Agent

Converts a raw free-text incident report into a structured Incident Card.
This is the first node in the LangGraph workflow (§6.1 of the guide).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm import get_llm
from src.state.state import DecisioState, IncidentCard

# ── System prompt ────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are the Incident Intake Agent for Decisio, an operational decision-support system.

Your job is to convert a raw incident report into a structured Incident Card.

Given the user's free-text incident report, extract the following information and return it as a JSON object:

{{
  "normalized_summary": "A clear, concise 2-3 sentence summary of the incident",
  "asset_id": "The equipment/system/asset ID if mentioned, otherwise null",
  "symptoms": ["list", "of", "key", "symptoms", "or", "observations"],
  "severity": "low | medium | high | critical (based on described impact)",
  "safety_level": "safe | caution | danger | unknown (based on safety indicators)"
}}

Rules:
- Preserve the original meaning; do not add information not in the report.
- If severity or safety cannot be determined, use "medium" for severity and "unknown" for safety_level.
- Extract ALL distinct symptoms mentioned.
- If the report is just a greeting (e.g., "hello", "hi") or lacks any specific issue description, set "normalized_summary" to "New Incident" and leave "asset_id" as null.
- Return ONLY the JSON object, no markdown fences, no extra text.
"""


# ── Agent function (LangGraph node) ──────────────────────────────────


def incident_intake_agent(state: DecisioState) -> DecisioState:
    """
    LangGraph node: Incident Intake Agent.

    Reads ``state["report"]`` and produces a structured Incident Card
    by calling the OpenAI LLM.

    Returns
    -------
    dict
        State update with ``incident_card``, ``status``, and ``current_node``.
    """
    # Original free-text report from the operator
    report = state.get("report", "") or ""
    if not report.strip():
        raise ValueError("No incident report provided in state['report'].")

    # Enrich with structured fields from the Problem & Machine Intake agent
    problem_description = (state.get("problem_description") or "").strip()
    machine_name = (state.get("machine_name") or "").strip()

    llm = get_llm(temperature=0.2)

    # Build a clearer prompt for the LLM, so the second agent always
    # sees an explicit problem + machine when they are known.
    enriched_report_lines = ["Incident Report:"]
    if problem_description:
        enriched_report_lines.append(f"Problem: {problem_description}")
    if machine_name:
        enriched_report_lines.append(f"Machine: {machine_name}")
    enriched_report_lines.append("")
    enriched_report_lines.append(report)
    enriched_report = "\n".join(enriched_report_lines)

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=enriched_report),
    ]

    response = llm.invoke(messages)
    raw_content = response.content.strip()

    # ── Parse the LLM JSON response ──────────────────────────────────
    # Strip markdown fences if the model wraps them anyway
    if raw_content.startswith("```"):
        raw_content = raw_content.split("\n", 1)[1]
        if raw_content.endswith("```"):
            raw_content = raw_content[: raw_content.rfind("```")]
        raw_content = raw_content.strip()

    try:
        extracted = json.loads(raw_content)
    except json.JSONDecodeError:
        # Fallback: treat the whole report as the summary
        extracted = {
            "normalized_summary": report,
            "symptoms": [],
            "severity": "medium",
            "safety_level": "unknown",
        }

    # ── Build the Incident Card ──────────────────────────────────────
    normalized_summary = extracted.get("normalized_summary", report)
    # If we have a clearer problem_description from the first agent,
    # prefer that over the generic fallback summaries.
    if problem_description and (
        normalized_summary.lower().startswith("new incident")
        or len(normalized_summary.split()) < len(problem_description.split())
    ):
        normalized_summary = problem_description

    asset_id = extracted.get("asset_id")
    if (not asset_id) and machine_name:
        asset_id = machine_name
    card = IncidentCard(
        incident_id=str(uuid.uuid4()),
        report=report,
        normalized_summary=normalized_summary,
        asset_id=asset_id,
        symptoms=extracted.get("symptoms", []),
        timestamp=datetime.now(timezone.utc).isoformat(),
        severity=extracted.get("severity", "medium"),
        safety_level=extracted.get("safety_level", "unknown"),
        status="SCREENING",
    )

    return {
        "incident_card": card.model_dump(),
        "status": "SCREENING",
        "current_node": "incident_intake",
    }
