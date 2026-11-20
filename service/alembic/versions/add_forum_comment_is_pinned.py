"""add forum_comments.is_pinned（讨论回复置顶）

Revision ID: add_forum_comment_pinned
Revises: add_contest_teams
Create Date: 2026-10-15

需求：讨论区支持「回复置顶」（仅秩序管理可设置），置顶回复在帖子详情页
排在普通回复之前。

纯新增列，默认 false，非空；SQLite 支持 ADD COLUMN 带默认值，无需 batch。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_forum_comment_pinned"
# 接在当前 main 的 head 之后（保持单 head）。注意：另一个在途 PR 的迁移
# rename_diff_pj_plus 同样以 add_contest_teams 为父；两者先合并的一方生效后，
# 另一分支 rebase 时需把 down_revision 改为已合并的那个 revision，避免双 head。
down_revision: Union[str, None] = "add_contest_teams"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("forum_comments")}
    # 幂等：create_all 建表的库（或重复执行）已有该列则跳过
    if "is_pinned" not in cols:
        op.add_column(
            "forum_comments",
            sa.Column(
                "is_pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("forum_comments")}
    if "is_pinned" in cols:
        op.drop_column("forum_comments", "is_pinned")
