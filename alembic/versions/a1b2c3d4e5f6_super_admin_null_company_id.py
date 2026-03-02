"""super_admin null company_id

Revision ID: a1b2c3d4e5f6
Revises: f8a91b2c4d5e
Create Date: 2026-02-24

Makes users.company_id nullable so super_admin users can have company_id = NULL.
Sets company_id = NULL for existing users with user_type = 'super_admin'.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f8a91b2c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Allow NULL for super_admin users
    op.alter_column(
        "users",
        "company_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.execute(sa.text(
        "UPDATE users SET company_id = NULL WHERE user_type = 'super_admin'"
    ))


def downgrade() -> None:
    # Set any NULL company_id to 1 before making column NOT NULL again
    op.execute(sa.text(
        "UPDATE users SET company_id = 1 WHERE company_id IS NULL"
    ))
    op.alter_column(
        "users",
        "company_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
