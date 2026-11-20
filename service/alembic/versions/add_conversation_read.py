"""add conversation member last read

Revision ID: add_conversation_read
Revises: 44609eff8cf4
Create Date: 2026-10-04 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_conversation_read'
down_revision = 'add_ticket_action_target'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'conversation_members',
        sa.Column('last_read_message_id', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('conversation_members', 'last_read_message_id')
