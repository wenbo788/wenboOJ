"""add team discussions (team_posts and team_post_comments)

Revision ID: add_team_discussions
Revises: add_contest_rule_type
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "add_team_discussions"
down_revision = "add_contest_rule_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "team_posts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_pinned", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_locked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_team_posts_team_id", "team_posts", ["team_id"], unique=False)
    op.create_index("ix_team_posts_author_id", "team_posts", ["author_id"], unique=False)
    op.create_index("ix_team_posts_team_id_created_at", "team_posts", ["team_id", "created_at"], unique=False)
    op.create_index("ix_team_posts_is_pinned", "team_posts", ["is_pinned"], unique=False)

    op.create_table(
        "team_post_comments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["post_id"], ["team_posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_team_post_comments_post_id", "team_post_comments", ["post_id"], unique=False)
    op.create_index("ix_team_post_comments_author_id", "team_post_comments", ["author_id"], unique=False)
    op.create_index("ix_team_post_comments_post_id_id", "team_post_comments", ["post_id", "id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_team_post_comments_post_id_id", table_name="team_post_comments")
    op.drop_index("ix_team_post_comments_author_id", table_name="team_post_comments")
    op.drop_index("ix_team_post_comments_post_id", table_name="team_post_comments")
    op.drop_table("team_post_comments")

    op.drop_index("ix_team_posts_is_pinned", table_name="team_posts")
    op.drop_index("ix_team_posts_team_id_created_at", table_name="team_posts")
    op.drop_index("ix_team_posts_author_id", table_name="team_posts")
    op.drop_index("ix_team_posts_team_id", table_name="team_posts")
    op.drop_table("team_posts")
