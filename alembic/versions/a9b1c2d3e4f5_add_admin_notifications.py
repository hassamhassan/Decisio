"""add admin_notifications table

Revision ID: a9b1c2d3e4f5
Revises: f50750debff7
Create Date: 2026-02-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a9b1c2d3e4f5'
down_revision: Union[str, Sequence[str], None] = 'f50750debff7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'admin_notifications',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('notification_type', sa.String(64), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('incident_id', sa.String(64), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_admin_notifications_company_id', 'admin_notifications', ['company_id'])
    op.create_index('ix_admin_notifications_notification_type', 'admin_notifications', ['notification_type'])
    op.create_index('ix_admin_notifications_incident_id', 'admin_notifications', ['incident_id'])
    op.create_index('ix_admin_notifications_is_read', 'admin_notifications', ['is_read'])


def downgrade() -> None:
    op.drop_index('ix_admin_notifications_is_read', table_name='admin_notifications')
    op.drop_index('ix_admin_notifications_incident_id', table_name='admin_notifications')
    op.drop_index('ix_admin_notifications_notification_type', table_name='admin_notifications')
    op.drop_index('ix_admin_notifications_company_id', table_name='admin_notifications')
    op.drop_table('admin_notifications')
