"""Add column likes, stars and comments tables.

Revision ID: add_column_interactions
Revises: add_column_category
Create Date: 2026-10-03
"""

from alembic import op
import sqlalchemy as sa


revision = "add_column_interactions"
down_revision = "add_column_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "column_likes" not in tables:
        op.create_table(
            "column_likes",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("column_id", sa.Integer(), sa.ForeignKey("columns.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.UniqueConstraint("column_id", "user_id", name="uq_column_likes_column_user"),
        )
        op.create_index("ix_column_likes_column_id", "column_likes", ["column_id"])
        op.create_index("ix_column_likes_user_id", "column_likes", ["user_id"])
    else:
        existing_cols = [c["name"] for c in inspector.get_columns("column_likes")]
        if "updated_at" not in existing_cols:
            op.add_column("column_likes", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False))

    if "column_stars" not in tables:
        op.create_table(
            "column_stars",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("column_id", sa.Integer(), sa.ForeignKey("columns.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.UniqueConstraint("column_id", "user_id", name="uq_column_stars_column_user"),
        )
        op.create_index("ix_column_stars_column_id", "column_stars", ["column_id"])
        op.create_index("ix_column_stars_user_id", "column_stars", ["user_id"])
    else:
        existing_cols = [c["name"] for c in inspector.get_columns("column_stars")]
        if "updated_at" not in existing_cols:
            op.add_column("column_stars", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False))

    if "column_comments" not in tables:
        op.create_table(
            "column_comments",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("column_id", sa.Integer(), sa.ForeignKey("columns.id", ondelete="CASCADE"), nullable=False),
            sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        )
        op.create_index("ix_column_comments_column_id", "column_comments", ["column_id"])
        op.create_index("ix_column_comments_author_id", "column_comments", ["author_id"])
        op.create_index("ix_column_comments_is_deleted", "column_comments", ["is_deleted"])
    else:
        existing_cols = [c["name"] for c in inspector.get_columns("column_comments")]
        if "updated_at" not in existing_cols:
            op.add_column("column_comments", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False))
        if "is_deleted" not in existing_cols:
            op.add_column("column_comments", sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False))


def downgrade() -> None:
    op.drop_table("column_comments")
    op.drop_table("column_stars")
    op.drop_table("column_likes")
