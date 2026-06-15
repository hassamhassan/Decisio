"""add equipment_id and equipment_name to knowledge_entries

Revision ID: f1a2b3c4d5e6
Revises: e7f8a9b0c1d2
Create Date: 2026-05-07 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e7f8a9b0c1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('knowledge_entries', sa.Column('equipment_id', sa.String(32), nullable=True))
    op.add_column('knowledge_entries', sa.Column('equipment_name', sa.String(128), nullable=True))
    op.create_index('ix_knowledge_entries_equipment_id', 'knowledge_entries', ['equipment_id'])


def downgrade() -> None:
    op.drop_index('ix_knowledge_entries_equipment_id', table_name='knowledge_entries')
    op.drop_column('knowledge_entries', 'equipment_name')
    op.drop_column('knowledge_entries', 'equipment_id')
