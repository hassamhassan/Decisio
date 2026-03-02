"""add companies and users.company_id

Revision ID: f8a91b2c4d5e
Revises: e1241273ac5f
Create Date: 2026-02-24

Adds companies table (tenant isolation) and users.company_id FK.
No default company is created; companies are created by super_admin via API.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "f8a91b2c4d5e"
down_revision: Union[str, Sequence[str], None] = "e1241273ac5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    # Create companies table only if it doesn't exist (e.g. already created by create_all)
    if "companies" not in inspector.get_table_names():
        op.create_table(
            "companies",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("slug", sa.String(length=64), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
            sa.UniqueConstraint("slug"),
        )
        op.create_index(op.f("ix_companies_slug"), "companies", ["slug"], unique=True)

    # Add company_id to users if not already present (nullable; super_admin has no company)
    if "users" in inspector.get_table_names():
        cols = [c["name"] for c in inspector.get_columns("users")]
        if "company_id" not in cols:
            op.add_column("users", sa.Column("company_id", sa.Integer(), nullable=True))
            op.create_foreign_key(
                "fk_users_company_id",
                "users",
                "companies",
                ["company_id"],
                ["id"],
            )
            op.create_index(op.f("ix_users_company_id"), "users", ["company_id"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    cols = [c["name"] for c in inspector.get_columns("users")]
    if "company_id" in cols:
        op.drop_index(op.f("ix_users_company_id"), table_name="users")
        op.drop_constraint("fk_users_company_id", "users", type_="foreignkey")
        op.drop_column("users", "company_id")
    # Do not drop companies: it may have been created by create_all or hold tenant data.
