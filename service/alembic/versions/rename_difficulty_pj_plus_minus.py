"""rename problem difficulty 普及+/提高 -> 普及+/提高-

Revision ID: rename_diff_pj_plus
Revises: add_contest_teams
Create Date: 2026-10-15

需求：题目难度档位名称修正——原「普及+/提高」改为「普及+/提高-」。

代码侧（DIFFICULTIES / DIFFICULTY_COLORS / 各难度映射表）已同步改名，
本迁移负责把**存量数据**里的旧档位名改成新名，否则列表筛选、难度配色、
经验/贡献映射都会因取不到键而失配（旧串在新表里不再是合法档位）。

幂等：按值替换，重复执行不会二次匹配（第二次已无旧值行），因此可安全重跑。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "rename_diff_pj_plus"
down_revision: Union[str, None] = "add_contest_teams"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = "普及+/提高"
_NEW = "普及+/提高-"


def upgrade() -> None:
    op.get_bind().execute(
        sa.text("UPDATE problems SET difficulty = :new WHERE difficulty = :old"),
        {"new": _NEW, "old": _OLD},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("UPDATE problems SET difficulty = :old WHERE difficulty = :new"),
        {"new": _NEW, "old": _OLD},
    )
