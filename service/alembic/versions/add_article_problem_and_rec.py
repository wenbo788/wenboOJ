"""column_articles 增加关联题目与推荐审核字段。

- problem_id: 关联题目ID（外键 problems.id）
- recommend_status: 全站推荐状态（none / pending / approved / rejected）
- recommend_reason: 推荐说明或驳回理由
- reviewed_at: 审核时间
- reviewer_id: 审核管理员用户ID

Revision ID: add_article_problem_and_rec
Revises: add_theme_mode
Create Date: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_article_problem_and_rec"
down_revision: Union[str, Sequence[str], None] = "add_site_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "column_articles" not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns("column_articles")}
    if "problem_id" not in cols:
        op.add_column(
            "column_articles",
            sa.Column(
                "problem_id",
                sa.Integer(),
                sa.ForeignKey("problems.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index("ix_column_articles_problem_id", "column_articles", ["problem_id"])
    if "recommend_status" not in cols:
        op.add_column(
            "column_articles",
            sa.Column(
                "recommend_status",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'none'"),
            ),
        )
        op.create_index("ix_column_articles_recommend_status", "column_articles", ["recommend_status"])
    if "recommend_reason" not in cols:
        op.add_column(
            "column_articles",
            sa.Column("recommend_reason", sa.String(length=500), nullable=True),
        )
    if "reviewed_at" not in cols:
        op.add_column(
            "column_articles",
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "reviewer_id" not in cols:
        op.add_column(
            "column_articles",
            sa.Column(
                "reviewer_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "column_articles" not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns("column_articles")}
    if "problem_id" in cols:
        op.drop_index("ix_column_articles_problem_id", table_name="column_articles")
        op.drop_column("column_articles", "problem_id")
    if "recommend_status" in cols:
        op.drop_index("ix_column_articles_recommend_status", table_name="column_articles")
        op.drop_column("column_articles", "recommend_status")
    if "recommend_reason" in cols:
        op.drop_column("column_articles", "recommend_reason")
    if "reviewed_at" in cols:
        op.drop_column("column_articles", "reviewed_at")
    if "reviewer_id" in cols:
        op.drop_column("column_articles", "reviewer_id")
