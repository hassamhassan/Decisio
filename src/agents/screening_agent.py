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
Screening Agent for Decisio. Assess incident severity, safety, impact, scope, and risk.

Return ONLY JSON:
{{
  "severity":"low|medium|high|critical",
  "safety_level":"safe|caution|danger|unknown",
  "impact":"brief operational impact",
  "scope":"localized|unit-wide|plant-wide|multi-site",
  "initial_risk_score":<float 0-10>,
  "gating_flags":[], // leave empty unless immediate safety risk
  "process_failure_suspected":false, // default false
  "process_failure_indicators":[] // default empty
}}

Risk scoring: critical+danger→8-10, high+caution→5-7, medium+safe→2-4, low+safe→0-2.
If safety="unknown" add +2. If equipment criticality="critical" add +1.
Consider upstream/downstream impact for scope. Multiple symptoms → increase severity.

Process failure (NOT technical fault — breakdown in procedures/sequencing/human roles):
Indicators: no alarms with equipment stopped, shift change/handover, "worked fine yesterday",
no clear technical cause, manual step implied, multiple systems without common cause.
If ANY present → process_failure_suspected=true.

Return ONLY JSON, no markdown fences.
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
    # Track unregistered asset (returned via output dict, never mutate input state)
    asset_not_registered = False
    asset_not_registered_id = None
    if not asset_info and asset_id:
        # Machine/equipment was named in the incident, but is not in the
        # equipment registry. Flag this so the API layer can raise an
        # admin notification (bell icon) and the admin can add it.
        asset_not_registered = True
        asset_not_registered_id = asset_id

    context = "\n".join(context_lines)

    llm = get_llm(model="gpt-4", temperature=0.1)
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
    # Avoid leaving safety_level as "unknown" when screening didn't return a usable value.
    # Heuristic fallback (conservative): high/critical → caution; otherwise → safe.
    safety_level = (screening.get("safety_level") or "").strip().lower()
    if safety_level not in ("safe", "caution", "danger", "unknown"):
        safety_level = "unknown"
    if safety_level == "unknown":
        severity = (screening.get("severity") or updated_card.get("severity") or "medium").strip().lower()
        safety_level = "caution" if severity in ("high", "critical") else "safe"
    updated_card["safety_level"] = safety_level
    updated_card["impact"] = screening.get("impact", "")
    updated_card["scope"] = screening.get("scope", "localized")
    updated_card["initial_risk_score"] = float(screening.get("initial_risk_score", 5.0))
    updated_card["status"] = "DIAGNOSIS_LOOP"

    risk_score = float(screening.get("initial_risk_score", 5.0))
    gating_flags = screening.get("gating_flags", [])

    # Check for immediate escalation
    escalation_triggered = False
    escalation_reasons = []
    if updated_card.get("safety_level") == "danger":
        escalation_reasons.append("Safety level: DANGER")
    if risk_score >= 8.0:
        escalation_reasons.append(f"Risk score {risk_score} exceeds threshold")
    if gating_flags:
        escalation_reasons.extend(gating_flags)
    if escalation_reasons:
        escalation_triggered = True

    result_dict = {
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
    if asset_not_registered:
        result_dict["asset_not_registered"] = True
        result_dict["asset_not_registered_id"] = asset_not_registered_id
    return result_dict
