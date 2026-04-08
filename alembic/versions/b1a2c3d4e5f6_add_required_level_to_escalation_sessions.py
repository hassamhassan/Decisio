"""add required_level to escalation_sessions

Escalation sessions should be routed to matching L1/L2/L3/L4 handlers only.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "b1a2c3d4e5f6"
# This migration must run after the current head so Alembic has a single linear chain.
down_revision: Union[str, Sequence[str], None] = "3d867abfd16b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    if "escalation_sessions" not in inspector.get_table_names():
        return

    cols = {c["name"] for c in inspector.get_columns("escalation_sessions")}
    if "required_level" not in cols:
        op.add_column(
            "escalation_sessions",
            sa.Column("required_level", sa.Integer(), nullable=True),
        )

    idx_name = "ix_escalation_sessions_required_level"
    existing_indexes = {idx.get("name") for idx in inspector.get_indexes("escalation_sessions")}
    if idx_name not in existing_indexes:
        op.create_index(
            idx_name,
            "escalation_sessions",
            ["required_level"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index(
        "ix_escalation_sessions_required_level",
        table_name="escalation_sessions",
    )
    op.drop_column("escalation_sessions", "required_level")

