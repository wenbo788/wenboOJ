"""merge

Revision ID: 9a188982f9ac
Revises: add_forum_comment_pinned, rename_diff_pj_plus
Create Date: 2026-10-17 09:21:17.553467

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a188982f9ac'
down_revision: Union[str, Sequence[str], None] = ('add_forum_comment_pinned', 'rename_diff_pj_plus')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
