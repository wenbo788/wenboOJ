"""merge team feature heads (add_home_style, add_article_problem_and_rec)

Revision ID: merge_team_heads
Revises: add_home_style, add_article_problem_and_rec
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "merge_team_heads"
down_revision: Union[str, Sequence[str], None] = (
    "add_home_style",
    "add_article_problem_and_rec",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
