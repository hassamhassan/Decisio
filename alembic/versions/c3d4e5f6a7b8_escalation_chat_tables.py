"""escalation chat tables (sessions + messages)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-02-24

Adds escalation_sessions and escalation_messages for WebSocket escalation chat.
Multi-tenant isolation via company_id. Indexes for (company_id, session_id) and (session_id, created_at).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "escalation_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("expert_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="waiting"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["expert_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_escalation_sessions_company_id", "escalation_sessions", ["company_id"], unique=False)
    op.create_index("ix_escalation_sessions_user_id", "escalation_sessions", ["user_id"], unique=False)
    op.create_index("ix_escalation_sessions_expert_id", "escalation_sessions", ["expert_id"], unique=False)
    op.create_index("ix_escalation_sessions_status", "escalation_sessions", ["status"], unique=False)

    op.create_table(
        "escalation_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("sender_id", sa.Integer(), nullable=False),
        sa.Column("sender_role", sa.String(16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["escalation_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_escalation_messages_company_id", "escalation_messages", ["company_id"], unique=False)
    op.create_index("ix_escalation_messages_session_id", "escalation_messages", ["session_id"], unique=False)
    op.create_index("ix_escalation_messages_sender_id", "escalation_messages", ["sender_id"], unique=False)
    op.create_index("ix_escalation_messages_sender_role", "escalation_messages", ["sender_role"], unique=False)
    op.create_index(
        "ix_escalation_messages_session_created",
        "escalation_messages",
        ["session_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_escalation_messages_company_session",
        "escalation_messages",
        ["company_id", "session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_escalation_messages_company_session", table_name="escalation_messages")
    op.drop_index("ix_escalation_messages_session_created", table_name="escalation_messages")
    op.drop_index("ix_escalation_messages_sender_role", table_name="escalation_messages")
    op.drop_index("ix_escalation_messages_sender_id", table_name="escalation_messages")
    op.drop_index("ix_escalation_messages_session_id", table_name="escalation_messages")
    op.drop_index("ix_escalation_messages_company_id", table_name="escalation_messages")
    op.drop_table("escalation_messages")
    op.drop_index("ix_escalation_sessions_status", table_name="escalation_sessions")
    op.drop_index("ix_escalation_sessions_expert_id", table_name="escalation_sessions")
    op.drop_index("ix_escalation_sessions_user_id", table_name="escalation_sessions")
    op.drop_index("ix_escalation_sessions_company_id", table_name="escalation_sessions")
    op.drop_table("escalation_sessions")
