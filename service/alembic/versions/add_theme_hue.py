"""users 补 theme_hue 列：主题商店「色相调整」的持久化值.

-180..180（色相偏移角度），0 = 默认配色；独立于 theme_enabled
（未启用背景主题时色相同样生效）。server_default "0" 让存量行
直接拿到默认值。

（沿用本仓库惯例：只做「表在、列缺」的幂等补列，新库由建表分支
或本迁移的 add_column 同样兜住；revision id ≤ 32 字符。）

Revision ID: add_theme_hue
Revises: add_likes_stars_updated_at
Create Date: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_theme_hue"
down_revision: Union[str, Sequence[str], None] = "add_likes_stars_updated_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "users" not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "theme_hue" not in cols:
        op.add_column(
            "users",
            sa.Column(
                "theme_hue",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "users" not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "theme_hue" in cols:
        op.drop_column("users", "theme_hue")
