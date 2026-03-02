"""
Decisio — Equipment / Asset Registry (DB-only)

All equipment lookups go to PostgreSQL via sync_queries.
No hardcoded fallback — if it's not in the DB, it returns None/empty.
"""

from __future__ import annotations

from src.db.sync_queries import fetch_equipment, fetch_equipment_upstream_downstream


def get_asset(asset_id: str, company_id: int | None = None) -> dict | None:
    """Look up an asset by ID from the database. Scoped by company_id when provided."""
    if not asset_id:
        return None
    return fetch_equipment(asset_id, company_id=company_id)


def get_asset_type(asset_id: str, company_id: int | None = None) -> str | None:
    """Get the equipment type for an asset from the database. Scoped by company_id when provided."""
    asset = get_asset(asset_id, company_id=company_id)
    return asset["type"] if asset else None


def get_upstream_downstream(asset_id: str, company_id: int | None = None) -> dict:
    """Get the upstream/downstream context for an asset from the database.
    Note: fetch_equipment_upstream_downstream does not filter by company; asset_id lookup is scoped via get_asset.
    """
    if not asset_id:
        return {"upstream": None, "upstream_id": None, "downstream": None, "downstream_id": None}
    return fetch_equipment_upstream_downstream(asset_id)
