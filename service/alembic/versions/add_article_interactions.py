"""Add article interactions: article_likes, article_stars, article_comments.

Revision ID: add_article_interactions
Revises: make_articles_standalone
Create Date: 2026-10-04
"""

from alembic import op
import sqlalchemy as sa


revision = "add_article_interactions"
down_revision = "make_articles_standalone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    # 1. 创建文章点赞表
    if "article_likes" not in tables:
        op.create_table(
            "article_likes",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("article_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.ForeignKeyConstraint(["article_id"], ["column_articles.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("article_id", "user_id", name="uq_article_likes_article_user"),
        )
        op.create_index("ix_article_likes_article_id", "article_likes", ["article_id"])
        op.create_index("ix_article_likes_user_id", "article_likes", ["user_id"])

    # 2. 创建文章收藏表
    if "article_stars" not in tables:
        op.create_table(
            "article_stars",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("article_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.ForeignKeyConstraint(["article_id"], ["column_articles.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("article_id", "user_id", name="uq_article_stars_article_user"),
        )
        op.create_index("ix_article_stars_article_id", "article_stars", ["article_id"])
        op.create_index("ix_article_stars_user_id", "article_stars", ["user_id"])

    # 3. 创建文章评论表
    if "article_comments" not in tables:
        op.create_table(
            "article_comments",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("article_id", sa.Integer(), nullable=False),
            sa.Column("author_id", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.ForeignKeyConstraint(["article_id"], ["column_articles.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_article_comments_article_id", "article_comments", ["article_id"])
        op.create_index("ix_article_comments_author_id", "article_comments", ["author_id"])
        op.create_index("ix_article_comments_is_deleted", "article_comments", ["is_deleted"])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "article_comments" in tables:
        op.drop_table("article_comments")
    if "article_stars" in tables:
        op.drop_table("article_stars")
    if "article_likes" in tables:
        op.drop_table("article_likes")
