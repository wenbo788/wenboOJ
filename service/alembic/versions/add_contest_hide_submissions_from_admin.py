"""add hide_submissions_from_admin to contests

Revision ID: add_contest_hide_admin
Revises: add_user_is_big_admin
Create Date: 2026-10-11
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "add_contest_hide_admin"
down_revision: Union[str, None] = "add_user_is_big_admin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("contests")}
    if "hide_submissions_from_admin" not in cols:
        op.add_column(
            "contests",
            sa.Column(
                "hide_submissions_from_admin",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            ),
        )


def downgrade() -> None:
    op.drop_column("contests", "hide_submissions_from_admin")
