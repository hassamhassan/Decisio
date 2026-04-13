"""
Decisio — Synchronous DB Query Helpers

Centralised sync queries for LangGraph agents to fetch equipment,
safety rules, and escalation data from PostgreSQL.

All functions return sensible empty defaults on failure so callers
can transparently fall back to hardcoded data.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select as sa_select

logger = logging.getLogger(__name__)


# ── Helpers ─────────────────────────────────────────────────────────

def _get_session():
    """Get a sync session (import lazily to avoid circular imports)."""
    from src.db.session import SessionLocal
    return SessionLocal()


# ── Equipment Queries ───────────────────────────────────────────────

def fetch_equipment(asset_id: str, company_id: int | None = None) -> Optional[dict]:
    """Fetch a single equipment record by ID. Returns dict or None."""
    if not asset_id:
        return None
    try:
        from src.db.models import Equipment
        with _get_session() as session:
            from sqlalchemy import select as sa_select
            asset_clean = asset_id.upper().strip()
            stmt = sa_select(Equipment).where(Equipment.id == asset_clean)
            if company_id is not None:
                stmt = stmt.where(Equipment.company_id == company_id)
            eq = session.execute(stmt).scalar_one_or_none()
            if not eq:
                # Fallback: case-insensitive prefix match (e.g. "CMP-01" matches "CMP-01 (Air Compressor)")
                stmt_like = sa_select(Equipment).where(Equipment.id.ilike(f"{asset_clean}%"))
                if company_id is not None:
                    stmt_like = stmt_like.where(Equipment.company_id == company_id)
                eq = session.execute(stmt_like).scalars().first()
                if not eq:
                    return None
            return {
                "id": eq.id,
                "name": eq.name,
                "type": eq.equipment_type,
                "process_line": eq.process_line,
                "criticality": eq.criticality,
                "description": eq.description or "",
                "upstream": eq.upstream_id,
                "downstream": eq.downstream_id,
            }
    except Exception as e:
        logger.debug(f"sync_queries.fetch_equipment failed: {e}")
        return None


def fetch_equipment_upstream_downstream(asset_id: str) -> dict:
    """Fetch upstream/downstream equipment for an asset."""
    result = {"upstream": None, "upstream_id": None, "downstream": None, "downstream_id": None}
    if not asset_id:
        return result
    try:
        from src.db.models import Equipment
        with _get_session() as session:
            eq = session.get(Equipment, asset_id.upper().strip())
            if not eq:
                return result

            result["upstream_id"] = eq.upstream_id
            result["downstream_id"] = eq.downstream_id

            if eq.upstream_id:
                up = session.get(Equipment, eq.upstream_id)
                if up:
                    result["upstream"] = {
                        "id": up.id,
                        "name": up.name,
                        "type": up.equipment_type,
                    }
            if eq.downstream_id:
                down = session.get(Equipment, eq.downstream_id)
                if down:
                    result["downstream"] = {
                        "id": down.id,
                        "name": down.name,
                        "type": down.equipment_type,
                    }
        return result
    except Exception as e:
        logger.debug(f"sync_queries.fetch_equipment_upstream_downstream failed: {e}")
        return result


def fetch_all_equipment(company_id: int | None = None) -> list[dict]:
    """Fetch all equipment records (optionally scoped by company_id).

    Returns a list of lightweight dicts suitable for prompts and UIs.
    """
    try:
        from src.db.models import Equipment
        with _get_session() as session:
            stmt = sa_select(Equipment)
            if company_id is not None:
                stmt = stmt.where(Equipment.company_id == company_id)
            stmt = stmt.order_by(Equipment.process_line, Equipment.id)
            rows = session.execute(stmt).scalars().all()
            return [
                {
                    "id": eq.id,
                    "name": eq.name,
                    "type": eq.equipment_type,
                    "process_line": eq.process_line,
                }
                for eq in rows
            ]
    except Exception as e:
        logger.debug(f"sync_queries.fetch_all_equipment failed: {e}")
        return []


# ── Safety Rule Queries ─────────────────────────────────────────────

def fetch_safety_rules(equipment_type: str | None = None, company_id: int | None = None) -> list[dict]:
    """Fetch safety rules from DB, optionally filtered by equipment type and company."""
    try:
        from src.db.models import SafetyRule
        with _get_session() as session:
            stmt = sa_select(SafetyRule)
            if company_id is not None:
                stmt = stmt.where(SafetyRule.company_id == company_id)
            if equipment_type:
                stmt = stmt.where(
                    (SafetyRule.equipment_type == equipment_type.lower())
                    | (SafetyRule.is_general == True)  # noqa: E712
                )
            else:
                stmt = stmt.where(SafetyRule.is_general == True)  # noqa: E712
            stmt = stmt.order_by(SafetyRule.sort_order)
            rows = session.execute(stmt).scalars().all()
            return [
                {
                    "id": r.id,
                    "rule_text": r.rule_text,
                    "severity_class": r.severity_class,
                    "equipment_type": r.equipment_type,
                    "is_general": r.is_general,
                }
                for r in rows
            ]
    except Exception as e:
        logger.debug(f"sync_queries.fetch_safety_rules failed: {e}")
        return []


# ── Escalation Queries ──────────────────────────────────────────────

def fetch_escalation_levels(company_id: int | None = None) -> dict[int, dict]:
    """Fetch escalation level definitions from DB."""
    try:
        from src.db.models import EscalationLevel
        with _get_session() as session:
            stmt = sa_select(EscalationLevel).order_by(EscalationLevel.level)
            if company_id is not None:
                stmt = stmt.where(EscalationLevel.company_id == company_id)
            rows = session.execute(stmt).scalars().all()
            if not rows:
                return {}
            return {
                r.level: {"name": r.name, "description": r.description}
                for r in rows
            }
    except Exception as e:
        logger.debug(f"sync_queries.fetch_escalation_levels failed: {e}")
        return {}


def fetch_escalation_rules(company_id: int | None = None) -> list[dict]:
    """Fetch escalation rules from DB."""
    try:
        from src.db.models import EscalationRule
        with _get_session() as session:
            stmt = sa_select(EscalationRule).order_by(EscalationRule.sort_order)
            if company_id is not None:
                stmt = stmt.where(EscalationRule.company_id == company_id)
            rows = session.execute(stmt).scalars().all()
            return [
                {
                    "id": r.id,
                    "condition": r.condition,
                    "confidence_min": r.confidence_min,
                    "confidence_max": r.confidence_max,
                    "safety_impact": r.safety_impact,
                    "escalation_level": r.escalation_level,
                    "description": r.description,
                }
                for r in rows
            ]
    except Exception as e:
        logger.debug(f"sync_queries.fetch_escalation_rules failed: {e}")
        return []
