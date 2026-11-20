"""widen contests.visibility to varchar(14)

Revision ID: widen_contest_visibility
Revises: add_conversation_dissolved
Create Date: 2026-10-07

工单 #1251：比赛修改完设置无法保存（保存失败 / 500）。

根因：contests.visibility 列由 add_contest_visibility 建为 VARCHAR(10)，
后来 add_contest_team 引入 team_public（11 字符）/ team_private（12 字符）
取值时只改了模型（String(10)→String(14)）没改列宽——凡写入
team_public / team_private 都触发 StringDataRightTruncationError 500。

本迁移幂等地把列宽扩到 14（与模型一致）；已是 14 的库（create_all 建表）
跳过，重复执行安全。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "widen_contest_visibility"
down_revision: Union[str, None] = "add_conversation_dissolved"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {
        c["name"]: c
        for c in sa.inspect(bind).get_columns("contests")
    }
    col = cols.get("visibility")
    # 已是 varchar(14)（create_all 建表 / 重复执行）则跳过
    if col is not None and (col.get("type") is None or getattr(col["type"], "length", 14) < 14):
        op.alter_column(
            "contests",
            "visibility",
            existing_type=sa.String(10),
            type_=sa.String(14),
            existing_nullable=False,
        )


def downgrade() -> None:
    # 收窄可能截断存量 team_public/team_private 数据，不做实质回退
    pass
