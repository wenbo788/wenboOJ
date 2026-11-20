"""users 补 theme_mode 列：深色主题开关（light / dark）。

非空列带 server_default 'light'：存量行自动落到浅色，行为零变化。
theme_mode 独立于 theme_enabled（背景开关），dark 时前端挂
html[data-theme="dark"] 覆盖设计令牌。

（沿用本仓库惯例：只做「表在、列缺」的幂等补列；revision id ≤ 32 字符。）

Revision ID: add_theme_mode
Revises: add_user_prefs
Create Date: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_theme_mode"
down_revision: Union[str, Sequence[str], None] = "add_user_prefs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "users" not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "theme_mode" not in cols:
        op.add_column(
            "users",
            sa.Column(
                "theme_mode",
                sa.String(length=10),
                nullable=False,
                server_default=sa.text("'light'"),
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "users" not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "theme_mode" in cols:
        op.drop_column("users", "theme_mode")
