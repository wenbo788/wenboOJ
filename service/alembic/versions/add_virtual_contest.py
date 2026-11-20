"""虚拟参赛：virtual_contests 表 + submissions.virtual_contest_id

Revision ID: add_virtual_contest
Revises: add_similar_submission_pairs
Create Date: 2026-10-17

需求：把一场**已结束**的比赛镜像出来自己再打一遍（个人计时）。
- 成绩只看得到自己的：虚拟提交不进原赛榜、不参与等级分结算；
- 提交仍带 contest_id（便于按比赛查询），用 virtual_contest_id 区分。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_virtual_contest"
# 接在当前 main 的 head（文章草稿）之后，保持单链头
down_revision: Union[str, None] = "add_similar_submission_pairs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "virtual_contests" not in tables:
        op.create_table(
            "virtual_contests",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_contest_id", sa.Integer(),
                      sa.ForeignKey("contests.id", ondelete="CASCADE"), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_virtual_user_source", "virtual_contests",
                        ["user_id", "source_contest_id"])
        # 「同一个人同一场比赛同时只能有一个进行中的虚拟赛」——应用层的
        # 「先查后写」挡不住并发，靠这个部分唯一索引在库里兜底。
        op.create_index(
            "uq_virtual_active", "virtual_contests",
            ["user_id", "source_contest_id"], unique=True,
            postgresql_where=sa.text("finished_at IS NULL"),
            sqlite_where=sa.text("finished_at IS NULL"),
        )

    sub_cols = {c["name"] for c in sa.inspect(bind).get_columns("submissions")}
    if "virtual_contest_id" not in sub_cols:
        op.add_column("submissions", sa.Column(
            "virtual_contest_id", sa.Integer(),
            sa.ForeignKey("virtual_contests.id", ondelete="SET NULL"), nullable=True))
        op.create_index("ix_submissions_virtual_contest_id", "submissions",
                        ["virtual_contest_id"])


def downgrade() -> None:
    bind = op.get_bind()
    sub_cols = {c["name"] for c in sa.inspect(bind).get_columns("submissions")}
    if "virtual_contest_id" in sub_cols:
        op.drop_index("ix_submissions_virtual_contest_id", table_name="submissions")
        op.drop_column("submissions", "virtual_contest_id")
    if "virtual_contests" in set(sa.inspect(bind).get_table_names()):
        op.drop_index("uq_virtual_active", table_name="virtual_contests")
        op.drop_index("ix_virtual_user_source", table_name="virtual_contests")
        op.drop_table("virtual_contests")
