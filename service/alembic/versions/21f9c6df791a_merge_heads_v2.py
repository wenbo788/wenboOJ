"""merge_heads_v2

Revision ID: 21f9c6df791a
Revises: add_problem_review, forum_post_problem, user_last_username_change
Create Date: 2026-10-03 10:09:03.454096

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '21f9c6df791a'
down_revision: Union[str, Sequence[str], None] = ('add_problem_review', 'forum_post_problem', 'user_last_username_change')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
