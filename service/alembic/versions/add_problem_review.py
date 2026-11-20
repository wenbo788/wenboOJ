"""add problem review fields

Revision ID: add_problem_review
Revises: create_trainings
Create Date: 2026-10-02

题目公开审核：problems 增加 review_status / review_reason / reviewed_at /
reviewer_id。普通用户提交的主题库题置为公开后先进 pending，管理员审核通过
才对外可见。

存量题一律回填 approved，保证上线后行为不变。幂等：缺列才补，重复执行安全。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "add_problem_review"
down_revision: Union[str, None] = "add_contest_rule_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("problems")}

    if "review_status" not in columns:
        op.add_column(
            "problems",
            sa.Column(
                "review_status",
                sa.String(length=20),
                nullable=False,
                server_default="approved",
            ),
        )
        op.create_index("ix_problems_review_status", "problems", ["review_status"])
    if "review_reason" not in columns:
        op.add_column("problems", sa.Column("review_reason", sa.Text(), nullable=True))
    if "reviewed_at" not in columns:
        op.add_column(
            "problems", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
        )
    if "reviewer_id" not in columns:
        # FK 走 batch：SQLite 不支持 ALTER TABLE ADD CONSTRAINT（同 ticket_assignee）
        op.add_column(
            "problems",
            sa.Column("reviewer_id", sa.Integer(), nullable=True),
        )
        with op.batch_alter_table("problems") as batch_op:
            batch_op.create_foreign_key(
                "fk_problems_reviewer_id", "users", ["reviewer_id"], ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    op.drop_column("problems", "reviewer_id")
    op.drop_column("problems", "reviewed_at")
    op.drop_column("problems", "review_reason")
    op.drop_index("ix_problems_review_status", table_name="problems")
    op.drop_column("problems", "review_status")
