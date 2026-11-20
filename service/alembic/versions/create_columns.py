"""Create columns and column_articles tables.

Revision ID: create_columns
Revises: merge_site_friend_links
Create Date: 2026-10-03
"""

from alembic import op
import sqlalchemy as sa


revision = "create_columns"
down_revision = "create_site_doc_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "columns" not in existing_tables:
        op.create_table(
            "columns",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("title", sa.String(length=100), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("cover_url", sa.String(length=500), nullable=True),
            sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("is_recommended", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_columns_author_id", "columns", ["author_id"])
        op.create_index("ix_columns_is_recommended", "columns", ["is_recommended"])

    if "column_articles" not in existing_tables:
        op.create_table(
            "column_articles",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("column_id", sa.Integer(), sa.ForeignKey("columns.id", ondelete="CASCADE"), nullable=False),
            sa.Column("title", sa.String(length=150), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("summary", sa.String(length=500), nullable=True),
            sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_column_articles_column_id", "column_articles", ["column_id"])
        op.create_index("ix_column_articles_author_id", "column_articles", ["author_id"])
        op.create_index("ix_column_articles_created_at", "column_articles", ["created_at"])


def downgrade() -> None:
    op.drop_table("column_articles")
    op.drop_table("columns")
