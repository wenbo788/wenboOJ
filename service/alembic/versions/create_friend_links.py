"""Create homepage friend links.

Revision ID: create_friend_links
Revises: merge_heads_reports
Create Date: 2026-10-03
"""

from alembic import op
import sqlalchemy as sa


revision = "create_friend_links"
down_revision = "merge_heads_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()
    if "friend_links" not in tables:
        op.create_table(
            "friend_links",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("title", sa.String(length=80), nullable=False),
            sa.Column("icon", sa.String(length=500), nullable=False),
            sa.Column("url", sa.String(length=500), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    op.drop_table("friend_links")