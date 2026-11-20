"""add user problem bank (U prefix)

Revision ID: add_user_problem_bank
Revises: create_reports
Create Date: 2026-10-03

题目编号体系区分「用户题」与「主题库题」：
- 草稿 / 待审核 / 被驳回（未正式公开）= 用户题，U 编号；
- 审核通过正式公开 = 进入主题库，P 编号。
- 团队题 T 编号不变。

problems 新增 is_official 标识（True=主题库 P / False=用户题 U），
存量非团队题按「审核是否通过」一次性归位。
幂等：缺列才补，重复执行安全。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_user_problem_bank"
down_revision: Union[str, None] = "create_reports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(bind, table: str, column: str) -> bool:
    inspector = sa.inspect(bind)
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_column(bind, "problems", "is_official"):
        # 先以 true（主题库）兜底全部存量题
        op.add_column(
            "problems",
            sa.Column(
                "is_official",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )
        op.create_index("ix_problems_is_official", "problems", ["is_official"])

        # 存量归位：已审核通过（正式公开）的非团队题属主题库 P；
        # 草稿 / 待审核 / 被驳回的题是用户题 U。
        op.execute(
            sa.text(
                """
                UPDATE problems
                SET is_official = (review_status = 'approved')
                WHERE team_id IS NULL
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, "problems", "is_official"):
        op.drop_index("ix_problems_is_official", table_name="problems")
        op.drop_column("problems", "is_official")
