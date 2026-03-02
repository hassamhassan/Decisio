"""
Decisio — Safety Rules (DB-only)

All safety rule lookups go to PostgreSQL via sync_queries.
No hardcoded fallback — if it's not in the DB, it returns empty lists.
"""

from __future__ import annotations

from src.db.sync_queries import fetch_safety_rules


def get_safety_rules(equipment_type: str, company_id: int | None = None) -> list[str]:
    """
    Get safety rules for a specific equipment type from the database.
    Returns list of rule text strings. Scoped by company_id when provided.
    """
    db_rules = fetch_safety_rules(equipment_type, company_id=company_id)
    return [r["rule_text"] for r in db_rules]


def get_all_applicable_rules(
    equipment_type: str,
    severity: str = "medium",
    company_id: int | None = None,
) -> dict:
    """
    Get structured safety constraints for an equipment type from the database.
    company_id is required for multi-tenant isolation; when None, no filter is applied.

    Returns dict with: blocks (hard stops), constraints (must-follow),
    and warnings (should-follow).
    """
    db_rules = fetch_safety_rules(equipment_type, company_id=company_id)

    blocks = []
    constraints = []
    warnings = []

    for r in db_rules:
        text = r["rule_text"]
        sev_class = r.get("severity_class", "constraint")
        is_general = r.get("is_general", False)

        if sev_class == "block" or severity in ("high", "critical"):
            blocks.append(text)
        elif is_general:
            warnings.append(text)
        else:
            constraints.append(text)

    return {"blocks": blocks, "constraints": constraints, "warnings": warnings}
