"""merge team_banned and restored head

Revision ID: 7fcd521be258
Revises: add_team_banned, c28c09b5b89a
Create Date: 2026-10-07 12:40:03.764782

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7fcd521be258'
down_revision: Union[str, Sequence[str], None] = ('add_team_banned', 'c28c09b5b89a')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
