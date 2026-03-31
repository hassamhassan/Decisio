"""add required_level to escalation_sessions

Escalation sessions should be routed to matching L1/L2/L3/L4 handlers only.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1a2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "a9b1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "escalation_sessions",
        sa.Column("required_level", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_escalation_sessions_required_level",
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

