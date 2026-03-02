"""
Decisio — Escalation Matrix (DB-only)

All escalation level/rule lookups go to PostgreSQL via sync_queries.
No hardcoded fallback — if it's not in the DB, it returns empty/defaults.
"""

from __future__ import annotations

from src.db.sync_queries import fetch_escalation_levels, fetch_escalation_rules


def get_escalation_levels(company_id: int | None = None) -> dict[int, dict]:
    """Get escalation level definitions from the database. Scoped by company_id when provided."""
    return fetch_escalation_levels(company_id=company_id)


def get_escalation_rules(company_id: int | None = None) -> list[dict]:
    """Get escalation rules from the database. Scoped by company_id when provided."""
    return fetch_escalation_rules(company_id=company_id)


def determine_escalation(
    confidence: float,
    safety_impact: str,
    is_recurring: bool = False,
    safety_interlock: bool = False,
    equipment_damage_risk: bool = False,
    company_id: int | None = None,
) -> dict:
    """
    Determine the escalation level based on conditions.
    Uses DB-driven levels and rules. company_id for tenant-scoped lookup.
    """
    levels = get_escalation_levels(company_id=company_id)

    # Priority 1: Equipment damage risk → highest level
    if equipment_damage_risk:
        top_level = max(levels.keys()) if levels else 4
        info = levels.get(top_level, {"name": "Unknown"})
        return {
            "level": top_level,
            "level_name": info["name"],
            "reason": "Potential equipment damage",
            "description": f"Escalate to {info['name']} — equipment integrity at risk",
        }

    # Priority 2: Safety interlock
    if safety_interlock:
        level = max(levels.keys()) - 1 if len(levels) > 1 else 3
        level = max(1, level)
        info = levels.get(level, {"name": "Unknown"})
        return {
            "level": level,
            "level_name": info["name"],
            "reason": "Safety interlock triggered",
            "description": f"Escalate to {info['name']} — safety event requires review",
        }

    # Priority 3: Recurring fault
    if is_recurring:
        info = levels.get(2, {"name": "Unknown"})
        return {
            "level": 2,
            "level_name": info["name"],
            "reason": "Recurring fault within 24h",
            "description": "Pattern recurrence detected — shift-level review needed",
        }

    # Priority 4: Low confidence
    if confidence < 0.60:
        level = max(levels.keys()) - 1 if len(levels) > 1 else 3
        level = max(1, level)
        info = levels.get(level, {"name": "Unknown"})
        return {
            "level": level,
            "level_name": info["name"],
            "reason": "Uncertain root cause",
            "description": f"Confidence {confidence:.0%} below threshold — expert diagnosis needed",
        }

    # No escalation needed
    return {
        "level": 0,
        "level_name": "No escalation",
        "reason": "Resolved at technician level",
        "description": "Confidence sufficient, no safety concerns",
    }
