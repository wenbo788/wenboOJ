"""比赛等级分：users 三列 + contests.is_rated + contest_ratings 表

Revision ID: add_contest_rating
Revises: add_article_is_draft
Create Date: 2026-10-17

需求：比赛等级分（rating）。只在后台勾了「计入等级分」且**已结束**的个人赛里
结算，不回填历史；`contest_ratings` 存每场每人的 before/after/delta 便于追溯。

三列都有 server_default，SQLite 支持 ADD COLUMN 带默认值，无需 batch。
`users.rating` 加索引：排行榜/资料页会按它排序。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_contest_rating"
# 接在 #110（查重表 similar_submission_pairs）之后，保持单链头
down_revision: Union[str, None] = "add_polls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(bind, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    cols = _columns(bind, "users")
    if "rating" not in cols:
        op.add_column("users", sa.Column("rating", sa.Integer(), nullable=False,
                                         server_default="1500"))
        op.create_index("ix_users_rating", "users", ["rating"])
    if "max_rating" not in cols:
        op.add_column("users", sa.Column("max_rating", sa.Integer(), nullable=False,
                                         server_default="1500"))
    if "rated_contests" not in cols:
        op.add_column("users", sa.Column("rated_contests", sa.Integer(), nullable=False,
                                         server_default="0"))

    if "is_rated" not in _columns(bind, "contests"):
        op.add_column("contests", sa.Column("is_rated", sa.Boolean(), nullable=False,
                                            server_default=sa.text("false")))

    if "contest_ratings" not in tables:
        op.create_table(
            "contest_ratings",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("contest_id", sa.Integer(),
                      sa.ForeignKey("contests.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("rank", sa.Integer(), nullable=False),
            sa.Column("participants", sa.Integer(), nullable=False),
            sa.Column("rating_before", sa.Integer(), nullable=False),
            sa.Column("rating_after", sa.Integer(), nullable=False),
            sa.Column("delta", sa.Integer(), nullable=False),
            sa.Column("rated_contests_before", sa.Integer(), nullable=False,
                      server_default="0"),
            sa.Column("rated_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("contest_id", "user_id", name="uq_contest_rating_user"),
        )
        op.create_index("ix_contest_ratings_contest_id", "contest_ratings", ["contest_id"])
        op.create_index("ix_contest_ratings_user_id", "contest_ratings", ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "contest_ratings" in tables:
        op.drop_index("ix_contest_ratings_user_id", table_name="contest_ratings")
        op.drop_index("ix_contest_ratings_contest_id", table_name="contest_ratings")
        op.drop_table("contest_ratings")
    if "is_rated" in _columns(bind, "contests"):
        op.drop_column("contests", "is_rated")
    cols = _columns(bind, "users")
    if "rated_contests" in cols:
        op.drop_column("users", "rated_contests")
    if "max_rating" in cols:
        op.drop_column("users", "max_rating")
    if "rating" in cols:
        op.drop_index("ix_users_rating", table_name="users")
        op.drop_column("users", "rating")
