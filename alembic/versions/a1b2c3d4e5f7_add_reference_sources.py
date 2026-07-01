"""add reference_sources and reference_equipment_links tables

Revision ID: a1b2c3d4e5f7
Revises: f1a2b3c4d5e6
Create Date: 2026-06-30 00:00:00.000000

Adds the unified reference_sources and reference_equipment_links tables.
Legacy knowledge_entries table is left intact for rollback safety.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reference_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),   # text | file
        sa.Column("category", sa.String(32), nullable=False),      # manual | document | sop | knowledge
        sa.Column("scope", sa.String(24), nullable=False),         # company_wide | equipment_specific
        # Text KB fields (nullable for file sources)
        sa.Column("problem", sa.Text(), nullable=True),
        sa.Column("solution", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # File metadata
        sa.Column("source_filename", sa.String(255), nullable=True),
        # Content integrity
        sa.Column("content_hash", sa.String(64), nullable=True),
        # Processing state
        sa.Column("status", sa.String(16), nullable=False, server_default="processing"),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        # Migration audit
        sa.Column("legacy_manual_key", sa.String(64), nullable=True),
        sa.Column("legacy_knowledge_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Ownership
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reference_sources_company_id", "reference_sources", ["company_id"])
    op.create_index("ix_reference_sources_status", "reference_sources", ["status"])
    op.create_index("ix_reference_sources_scope", "reference_sources", ["scope"])
    op.create_index("ix_reference_sources_legacy_knowledge_id", "reference_sources", ["legacy_knowledge_id"])
    op.create_index("ix_reference_sources_legacy_manual_key", "reference_sources", ["legacy_manual_key"])

    op.create_table(
        "reference_equipment_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("reference_source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("equipment_id", sa.String(32), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["reference_source_id"], ["reference_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference_source_id", "equipment_id", name="uq_ref_equip_link"),
    )
    op.create_index(
        "ix_reference_equipment_links_reference_source_id",
        "reference_equipment_links",
        ["reference_source_id"],
    )
    op.create_index(
        "ix_reference_equipment_links_equipment_company",
        "reference_equipment_links",
        ["equipment_id", "company_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_reference_equipment_links_equipment_company", table_name="reference_equipment_links")
    op.drop_index("ix_reference_equipment_links_reference_source_id", table_name="reference_equipment_links")
    op.drop_table("reference_equipment_links")

    op.drop_index("ix_reference_sources_legacy_manual_key", table_name="reference_sources")
    op.drop_index("ix_reference_sources_legacy_knowledge_id", table_name="reference_sources")
    op.drop_index("ix_reference_sources_scope", table_name="reference_sources")
    op.drop_index("ix_reference_sources_status", table_name="reference_sources")
    op.drop_index("ix_reference_sources_company_id", table_name="reference_sources")
    op.drop_table("reference_sources")
