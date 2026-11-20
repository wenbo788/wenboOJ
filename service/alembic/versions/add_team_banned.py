"""add is_banned to teams

Revision ID: add_team_banned
Revises: merge_team_heads
Create Date: 2026-10-06 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_team_banned"
down_revision: Union[str, Sequence[str], None] = "merge_team_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "teams",
        sa.Column(
            "is_banned",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("teams", "is_banned")
