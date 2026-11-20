"""forum post related problem

Revision ID: forum_post_problem
Revises: add_contest_rule_type, add_training_featured
Create Date: 2026-10-02

讨论区帖子关联题目：发帖关联后无需在标题里写题号。
同时合并 add_contest_rule_type 与 add_training_featured 两条 head
（两者都以 dm_recall_reply 为父，造成多链头）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "forum_post_problem"
down_revision: Union[str, Sequence[str], None] = (
    "add_contest_rule_type",
    "add_training_featured",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("forum_posts")}
    if "problem_id" not in cols:
        op.add_column(
            "forum_posts",
            sa.Column("problem_id", sa.Integer(), nullable=True),
        )
        op.create_index(
            "ix_forum_posts_problem_id", "forum_posts", ["problem_id"], unique=False,
        )


def downgrade() -> None:
    op.drop_constraint("fk_forum_posts_problem_id", "forum_posts", type_="foreignkey")
    op.drop_index("ix_forum_posts_problem_id", table_name="forum_posts")
    op.drop_column("forum_posts", "problem_id")
