"""users 补 home_style 列：主题商店「洛谷风格主页」开关（cloud / luogu）。

非空列带 server_default 'cloud'：存量行默认新版云图首页，行为零变化。
home_style 只决定本人首页渲染哪套布局（Home.vue 按它分发到
HomeCloud / HomeLuogu），独立于 theme_mode / theme_enabled。

（沿用本仓库惯例：只做「表在、列缺」的幂等补列；revision id ≤ 32 字符。）

Revision ID: add_home_style
Revises: add_site_settings
Create Date: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_home_style"
down_revision: Union[str, Sequence[str], None] = "add_site_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "users" not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "home_style" not in cols:
        op.add_column(
            "users",
            sa.Column(
                "home_style",
                sa.String(length=10),
                nullable=False,
                server_default=sa.text("'cloud'"),
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "users" not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "home_style" in cols:
        op.drop_column("users", "home_style")
