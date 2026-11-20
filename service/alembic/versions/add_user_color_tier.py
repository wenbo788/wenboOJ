"""users: 补上「购买名字颜色」功能漏掉的两列.

b9f6648 给 User 模型加了 color_tier / color_exp_spent 却没写迁移：
PostgreSQL 的 users 表没有这两列，任何 SELECT users.* 的查询都会报
column users.color_tier does not exist（几乎全站 500）。
oj-up 当时「全程成功」，是因为迁移链上根本没有这一步——补上后
alembic upgrade head 才会真正把列建出来。

Revision ID: add_user_color_tier
Revises: add_column_inclusion_requests
Create Date: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_user_color_tier"
down_revision: Union[str, Sequence[str], None] = "add_column_inclusion_requests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 先做存在性检查：万一有人已经手工补过列（或重放），别在半路报错。
    # server_default 与 models/user.py 的定义同源：既有用户统一落 gray / 0。
    conn = op.get_bind()
    cols = {c["name"] for c in sa.inspect(conn).get_columns("users")}
    if "color_tier" not in cols:
        op.add_column(
            "users",
            sa.Column(
                "color_tier",
                sa.String(10),
                nullable=False,
                server_default=sa.text("'gray'"),
            ),
        )
    if "color_exp_spent" not in cols:
        op.add_column(
            "users",
            sa.Column(
                "color_exp_spent",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    cols = {c["name"] for c in sa.inspect(conn).get_columns("users")}
    if "color_exp_spent" in cols:
        op.drop_column("users", "color_exp_spent")
    if "color_tier" in cols:
        op.drop_column("users", "color_tier")
