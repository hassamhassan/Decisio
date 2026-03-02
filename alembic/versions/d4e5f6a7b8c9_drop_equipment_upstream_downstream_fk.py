"""drop equipment upstream/downstream FK

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-02-24

Drops FK constraints on equipment.upstream_id and equipment.downstream_id
so upstream/downstream IDs can be stored without requiring referenced equipment to exist.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("equipment_upstream_id_fkey", "equipment", type_="foreignkey")
    op.drop_constraint("equipment_downstream_id_fkey", "equipment", type_="foreignkey")


def downgrade() -> None:
    op.create_foreign_key(
        "equipment_upstream_id_fkey", "equipment", "equipment",
        ["upstream_id"], ["id"]
    )
    op.create_foreign_key(
        "equipment_downstream_id_fkey", "equipment", "equipment",
        ["downstream_id"], ["id"]
    )
