"""merge subtask and group chat heads

Revision ID: 44609eff8cf4
Revises: add_subtask_support, f3a91c7e52b8
Create Date: 2026-10-04 17:04:57.797144

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '44609eff8cf4'
down_revision: Union[str, Sequence[str], None] = ('add_subtask_support', 'f3a91c7e52b8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
