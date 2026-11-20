"""user last username change

Revision ID: user_last_username_change
Revises: merge_heads
Create Date: 2026-10-03

用户 30 天改名冷却：记录上次改名时间，NULL 表示从未改过或冷却已过。
"""
from alembic import op
import sqlalchemy as sa

revision = "user_last_username_change"
down_revision = "merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_username_change", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "last_username_change")
