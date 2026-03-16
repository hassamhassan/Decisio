"""
Decisio — Screening Agent

Auto-classifies incident severity, safety posture, impact, scope,
and computes an initial risk score.  This is the second node in the
workflow, run immediately after Incident Intake (§6.2 of the guide).
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm import get_llm
from src.state.state import DecisioState
from src.data.assets import get_asset, get_upstream_downstream

SYSTEM_PROMPT = """\
You are the Screening Agent for Decisio, an operational decision-support system.

Given an Incident Card (with equipment details if available), assess the incident and return a JSON object with:

{{
  "severity": "low | medium | high | critical",
  "safety_level": "safe | caution | danger | unknown",
  "impact": "Brief description of operational impact",
  "scope": "localized | unit-wide | plant-wide | multi-site",
  "initial_risk_score": <float 0-10>,
  "gating_flags": ["list of any safety flags that may force immediate escalation"],
  "process_failure_suspected": true/false,
  "process_failure_indicators": ["list of indicators suggesting a process/procedural/human failure"]
}}

Scoring guidelines:
- Risk = severity_weight × safety_weight × uncertainty_factor
- "critical" severity + "danger" safety → risk 8-10
- "high" severity + "caution" safety → risk 5-7
- "medium" severity + "safe" safety → risk 2-4
- "low" severity + "safe" safety → risk 0-2
- If safety is "unknown", add +2 to risk score
- If equipment criticality is "critical", add +1 to risk score
- Consider upstream/downstream equipment impact in scope assessment
- If multiple symptoms or asset failure indicators, increase severity

Process failure detection (§8 — critical, check EARLY):
A process failure is NOT a direct technical fault — it is a breakdown in procedures,
sequencing, approvals, or human roles. Look for these indicators:
- "no alarms" or "no error" with equipment stopped → possible missed procedure
- Mention of shift change, handover, recent configuration change
- "worked fine yesterday" or "was working before shift change"
- No clear technical cause from the symptoms
- Manual step was mentioned or implied
- Multiple systems affected without a common technical root cause
If ANY of these are present, set process_failure_suspected to true.

Return ONLY the JSON object, no markdown fences, no extra text.
"""


def screening_agent(state: DecisioState) -> DecisioState:
    """
    LangGraph node: Screening Agent.

    Reads the incident card and produces severity, safety, impact,
    scope, initial risk score, and process failure assessment.
    """
    incident_card = state.get("incident_card", {})
    if not incident_card:
        raise ValueError("No incident_card in state.")

    context_lines = [
        f"Incident Summary: {incident_card.get('normalized_summary', incident_card.get('report', ''))}",
        f"Asset: {incident_card.get('asset_id', 'unknown')}",
        f"Symptoms: {', '.join(incident_card.get('symptoms', []))}",
        f"Initial Severity: {incident_card.get('severity', 'unknown')}",
        f"Initial Safety: {incident_card.get('safety_level', 'unknown')}",
    ]

    # Enrich with asset registry data (tenant-scoped)
    company_id = state.get("company_id")
    asset_id = incident_card.get("asset_id", "")
    asset_info = get_asset(asset_id, company_id=company_id) if asset_id else None
    if asset_info:
        context_lines.append(f"\nEquipment Details:")
        context_lines.append(f"  Name: {asset_info['name']}")
        context_lines.append(f"  Type: {asset_info['type']}")
        context_lines.append(f"  Criticality: {asset_info['criticality']}")
        context_lines.append(f"  Process Line: {asset_info['process_line']}")

        ud = get_upstream_downstream(asset_id, company_id=company_id)
        if ud.get("upstream"):
            context_lines.append(f"  Upstream: {ud['upstream_id']} ({ud['upstream']['name']})")
        if ud.get("downstream"):
            context_lines.append(f"  Downstream: {ud['downstream_id']} ({ud['downstream']['name']})")
    elif asset_id:
        # Machine/equipment was named in the incident, but is not in the
        # equipment registry. Flag this so the API layer can raise an
        # admin notification (bell icon) and the admin can add it.
        state["asset_not_registered"] = True
        state["asset_not_registered_id"] = asset_id

    context = "\n".join(context_lines)

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
        screening = json.loads(raw)
    except json.JSONDecodeError:
        screening = {
            "severity": incident_card.get("severity", "medium"),
            "safety_level": incident_card.get("safety_level", "unknown"),
            "impact": "Unable to assess — manual review needed",
            "scope": "localized",
            "initial_risk_score": 5.0,
            "gating_flags": [],
            "process_failure_suspected": False,
            "process_failure_indicators": [],
        }

    # Update the incident card with screening results
    updated_card = dict(incident_card)
    updated_card["severity"] = screening.get("severity", "medium")
    updated_card["safety_level"] = screening.get("safety_level", "unknown")
    updated_card["impact"] = screening.get("impact", "")
    updated_card["scope"] = screening.get("scope", "localized")
    updated_card["initial_risk_score"] = float(screening.get("initial_risk_score", 5.0))
    updated_card["status"] = "DIAGNOSIS_LOOP"

    risk_score = float(screening.get("initial_risk_score", 5.0))
    gating_flags = screening.get("gating_flags", [])

    # Check for immediate escalation
    escalation_triggered = False
    escalation_reasons = []
    if screening.get("safety_level") == "danger":
        escalation_reasons.append("Safety level: DANGER")
    if risk_score >= 8.0:
        escalation_reasons.append(f"Risk score {risk_score} exceeds threshold")
    if gating_flags:
        escalation_reasons.extend(gating_flags)
    if escalation_reasons:
        escalation_triggered = True

    return {
        "incident_card": updated_card,
        "risk_score": risk_score,
        "screening_complete": True,
        "process_failure_suspected": screening.get("process_failure_suspected", False),
        "process_failure_indicators": screening.get("process_failure_indicators", []),
        "escalation_triggered": escalation_triggered,
        "escalation_reasons": escalation_reasons,
        "status": "DIAGNOSIS_LOOP",
        "current_node": "screening",
    }
