"""merge group chat and article heads

Revision ID: d575c7fdcc94
Revises: create_group_chat, make_articles_standalone
Create Date: 2026-10-04 14:45:45.241694

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd575c7fdcc94'
down_revision: Union[str, Sequence[str], None] = ('create_group_chat', 'make_articles_standalone')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
