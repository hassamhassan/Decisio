"""
Decisio — Server-Side Safety Policy Validator

Deterministic safety guardrail that runs AFTER the LLM generates structured
decision options and BEFORE the brief is returned to the UI.

Flow:
  1. LLM generates structured DecisionOption list.
  2. validate_options() checks each option against incident severity.
  3. If violations found → caller regenerates once with explicit violation feedback.
  4. If still invalid → caller calls build_safe_fallback_brief().
  5. build_safe_fallback_brief() ALWAYS returns safe options only.

Danger condition baseline
─────────────────────────
An incident is treated as safety-critical when ANY of:
  - incident_card.safety_level == "danger"
  - risk_score >= 8
  - escalation_level is L3 or L4 (escalation["escalation_level"] in (3, 4))
  - a safety rule explicitly prohibits an action (passed via safety_blocks)

Prohibited action types for danger-level incidents (as standalone Decision Options):
  - continue_operation
  - restart_equipment
  - bypass_protection
  - physical_intervention_while_running
  - add_lubricant_while_running
  - reduce_load

  reduce_load may appear only as non-selectable explanatory wording inside an
  allowed action (e.g. transfer_to_standby_equipment description), never as its
  own action_type on a Decision Option.

Allowed safe action types:
  - controlled_shutdown
  - isolate_and_lockout
  - transfer_to_standby_equipment
  - authorized_inspection
  - escalate_to_maintenance
  - hold_restart_pending_clearance
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────

DANGER_RISK_THRESHOLD = 8.0
DANGER_ESCALATION_LEVELS = {3, 4}

ALWAYS_PROHIBITED_DANGER = frozenset({
    "continue_operation",
    "restart_equipment",
    "bypass_protection",
    "physical_intervention_while_running",
    "add_lubricant_while_running",
    "reduce_load",
})

# Phrases in safety_blocks that indicate stricter danger posture
_SAFETY_BLOCK_DANGER_PHRASES = (
    "do not operate",
    "do not restart",
    "no restart",
    "shutdown required",
    "must shut down",
    "prohibited",
    "no continued operation",
    "do not continue",
)

SAFE_ACTION_TYPES = frozenset({
    "controlled_shutdown",
    "isolate_and_lockout",
    "transfer_to_standby_equipment",
    "authorized_inspection",
    "escalate_to_maintenance",
    "hold_restart_pending_clearance",
})


def _safety_blocks_indicate_danger(safety_blocks: list[str] | None) -> bool:
    """True when an applicable safety rule explicitly prohibits continued operation."""
    if not safety_blocks:
        return False
    combined = " ".join(str(b).lower() for b in safety_blocks)
    return any(phrase in combined for phrase in _SAFETY_BLOCK_DANGER_PHRASES)


def is_danger_incident(
    incident_card: dict[str, Any],
    risk_score: float,
    escalation: dict[str, Any] | None,
    safety_blocks: list[str] | None = None,
) -> bool:
    """Return True when the incident is classified as safety-critical."""
    if (incident_card or {}).get("safety_level") == "danger":
        return True
    if risk_score >= DANGER_RISK_THRESHOLD:
        return True
    level = (escalation or {}).get("escalation_level")
    if level is not None:
        try:
            if int(level) in DANGER_ESCALATION_LEVELS:
                return True
        except (TypeError, ValueError):
            pass
    if _safety_blocks_indicate_danger(safety_blocks):
        return True
    return False


def get_violations(
    options: list[dict[str, Any]],
    is_danger: bool,
    safety_blocks: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Return a list of violation records for options that violate the safety policy.

    Each record: {"option_id": int, "action_type": str, "reason": str}
    """
    if not is_danger:
        return []

    violations = []
    for opt in options:
        action = (opt.get("action_type") or "unknown").lower()
        oid = opt.get("option_id", "?")

        if action in ALWAYS_PROHIBITED_DANGER:
            reason = (
                f"Action '{action}' is prohibited for danger-level incidents."
            )
            if action == "reduce_load":
                reason = (
                    "'reduce_load' cannot be returned as a standalone Decision Option "
                    "for a danger-level incident. It may only appear as explanatory "
                    "wording inside an allowed action such as transfer_to_standby_equipment."
                )
            violations.append({
                "option_id": oid,
                "action_type": action,
                "reason": reason,
            })

    return violations


def validate_options(
    options: list[dict[str, Any]],
    incident_card: dict[str, Any],
    risk_score: float,
    escalation: dict[str, Any] | None,
    safety_blocks: list[str] | None = None,
) -> tuple[bool, list[dict[str, Any]]]:
    """
    Validate decision options against the safety policy.

    Returns (is_valid, violations).
    is_valid is True when there are no violations.
    """
    danger = is_danger_incident(incident_card, risk_score, escalation, safety_blocks)
    violations = get_violations(options, danger, safety_blocks)
    return len(violations) == 0, violations


def build_violation_feedback(violations: list[dict[str, Any]]) -> str:
    """Build human-readable feedback string for LLM re-generation prompt."""
    lines = [
        "SAFETY POLICY VIOLATION — your previous options included unsafe action types "
        "for this danger-level incident. You MUST NOT use these action types:",
    ]
    for v in violations:
        lines.append(f"  ✗ Option {v['option_id']} (action_type={v['action_type']}): {v['reason']}")
    lines.append(
        "\nFor this danger-level incident, only use these action types: "
        + ", ".join(sorted(SAFE_ACTION_TYPES))
        + "."
    )
    return "\n".join(lines)


def build_safe_fallback_brief(
    asset_id: str,
    incident_card: dict[str, Any],
    risk_score: float,
) -> dict[str, Any]:
    """
    Build a deterministic safe fallback Decision Brief for danger-level incidents
    when the LLM repeatedly generates unsafe options.

    This brief NEVER includes an unsafe action.
    """
    _a = asset_id if asset_id and asset_id not in ("", "unknown") else "the asset"
    summary = (
        f"{_a} presents a safety-critical condition "
        f"(safety_level={incident_card.get('safety_level','danger')}, "
        f"risk_score={risk_score:.1f}/10). "
        "Due to policy violations in LLM-generated options, a deterministic safe brief is used."
    )
    options = [
        {
            "option_id": 1,
            "title": f"Initiate Controlled Shutdown of {_a}",
            "description": (
                f"Execute the approved shutdown procedure for {_a} immediately. "
                "Follow lockout/tagout protocols. Do not attempt restart without clearance."
            ),
            "action_type": "controlled_shutdown",
            "preconditions": ["Operator has access to the approved shutdown procedure"],
            "risks": ["Production downtime until inspection is complete"],
            "risks_or_tradeoffs": ["Extended downtime if root cause is not identified quickly"],
            "constraints": ["Follow LOTO procedure strictly"],
            "safety_notes": [
                "Do NOT bypass any interlock or protective device.",
                "Do NOT restart without formal clearance from maintenance.",
            ],
            "source_reference_ids": [],
            "confidence": 0.90,
            "recommended": True,
            "risk_level": "low",
            "eta": "15-30 min",
            "blocked_by_safety": False,
        },
        {
            "option_id": 2,
            "title": f"Transfer Production to Standby Unit (if available)",
            "description": (
                f"If a verified standby unit is available, transfer {_a}'s load and "
                f"isolate {_a} for inspection. Confirm standby unit is operational before transfer."
            ),
            "action_type": "transfer_to_standby_equipment",
            "preconditions": [
                "A verified standby unit is available and confirmed operational",
                "Switchover can be performed safely",
            ],
            "risks": ["Standby unit may have lower rated capacity"],
            "risks_or_tradeoffs": ["Temporary throughput reduction during switchover"],
            "constraints": ["Verify standby unit status before committing to transfer"],
            "safety_notes": [
                f"Isolate {_a} after transfer. Do not leave it in an indeterminate state.",
            ],
            "source_reference_ids": [],
            "confidence": 0.80,
            "recommended": False,
            "risk_level": "low",
            "eta": "15-30 min",
            "blocked_by_safety": False,
        },
        {
            "option_id": 3,
            "title": f"Isolate, Lock Out, and Escalate {_a} to Maintenance",
            "description": (
                f"Isolate {_a} from the process, apply lockout/tagout, and escalate "
                "immediately to authorized maintenance personnel and Plant Manager. "
                "Hold restart pending formal inspection and written clearance."
            ),
            "action_type": "isolate_and_lockout",
            "preconditions": ["LOTO kit and procedure are available"],
            "risks": ["Prolonged production impact until inspection and clearance are complete"],
            "risks_or_tradeoffs": ["Higher short-term impact but lowest long-term risk"],
            "constraints": [
                "Restart requires written clearance from Plant Manager or higher authority",
            ],
            "safety_notes": [
                "This is the maximum-safety option.",
                "Do NOT allow restart until inspection is complete and all safety interlocks are verified.",
            ],
            "source_reference_ids": [],
            "confidence": 0.95,
            "recommended": False,
            "risk_level": "low",
            "eta": "30-90 min",
            "blocked_by_safety": False,
        },
    ]
    return {
        "analysis_summary": summary,
        "root_cause_hypothesis": (
            "Safety-critical condition confirmed. Root cause under investigation. "
            "Deterministic safe options applied."
        ),
        "options": options,
        "overall_confidence": 0.90,
        "risk_summary": (
            f"Failure to act immediately on {_a} presents a high safety risk "
            f"(risk score {risk_score:.1f}/10). No unsafe operational continuance is acceptable."
        ),
        "safety_constraints": [
            f"Do NOT continue operation of {_a} under current conditions.",
            "Do NOT bypass protective devices or interlocks.",
            "Formal clearance required before any restart.",
        ],
        "escalation_guidance": (
            f"Escalate immediately if {_a} cannot be safely shut down or if any "
            "safety interlock is found to be inoperative."
        ),
        "requires_escalation": True,
        "decision_authority": "Plant Manager or Safety Officer",
        "escalation_path": "Plant Manager → Safety Officer → Plant Director",
        "_safety_fallback": True,
    }
