"""add company_id to tenant tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-24

Adds company_id to incidents, equipment, safety_rules, escalation_levels,
escalation_rules, incident_reports for tenant isolation. No default company.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(conn, table: str, column: str) -> bool:
    inspector = inspect(conn)
    if table not in inspector.get_table_names():
        return False
    return column in [c["name"] for c in inspector.get_columns(table)]


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    tables_config = [
        "incidents",
        "equipment",
        "safety_rules",
        "escalation_levels",
        "escalation_rules",
        "incident_reports",
    ]

    for table_name in tables_config:
        if table_name not in tables:
            continue
        if not _has_column(conn, table_name, "company_id"):
            op.add_column(
                table_name,
                sa.Column("company_id", sa.Integer(), nullable=True),
            )
            try:
                op.create_foreign_key(
                    f"fk_{table_name}_company_id",
                    table_name,
                    "companies",
                    ["company_id"],
                    ["id"],
                )
            except Exception:
                pass
            op.create_index(
                op.f(f"ix_{table_name}_company_id"),
                table_name,
                ["company_id"],
                unique=False,
            )

    # escalation_levels: original table has PK(level) only; for multi-tenant we need (company_id, level)
    if "escalation_levels" in tables and _has_column(conn, "escalation_levels", "company_id"):
        op.execute(sa.text("ALTER TABLE escalation_levels DROP CONSTRAINT IF EXISTS escalation_levels_pkey"))
        op.create_primary_key("escalation_levels_pkey", "escalation_levels", ["company_id", "level"])


def downgrade() -> None:
    conn = op.get_bind()
    tables = [
        "incident_reports",
        "escalation_rules",
        "escalation_levels",
        "safety_rules",
        "equipment",
        "incidents",
    ]
    for table_name in tables:
        if _has_column(conn, table_name, "company_id"):
            if table_name == "escalation_levels":
                op.execute(sa.text("ALTER TABLE escalation_levels DROP CONSTRAINT IF EXISTS escalation_levels_pkey"))
                op.create_primary_key("escalation_levels_pkey", "escalation_levels", ["level"])
            op.drop_index(op.f(f"ix_{table_name}_company_id"), table_name=table_name)
            try:
                op.drop_constraint(f"fk_{table_name}_company_id", table_name, type_="foreignkey")
            except Exception:
                pass
            op.drop_column(table_name, "company_id")
