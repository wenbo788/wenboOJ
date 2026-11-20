"""merge

Revision ID: c28c09b5b89a
Revises: add_article_problem_and_rec, add_home_style
Create Date: 2026-10-06 13:49:08.643211

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c28c09b5b89a'
down_revision: Union[str, Sequence[str], None] = ('add_article_problem_and_rec', 'add_home_style')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
