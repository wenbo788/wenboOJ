"""users 补 code_template / code_font 列：偏好设置的持久化值.

code_template 存 JSON 字符串（各语言代码模板，null = 用内置默认），
code_font 存等宽字体 key（null = 默认 JetBrains Mono）。两列均可空，
存量行拿到 NULL 即可，无需 server_default。

（沿用本仓库惯例：只做「表在、列缺」的幂等补列；revision id ≤ 32 字符。）

Revision ID: add_user_prefs
Revises: add_action_target
Create Date: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_user_prefs"
down_revision: Union[str, Sequence[str], None] = "add_action_target"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "users" not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "code_template" not in cols:
        op.add_column("users", sa.Column("code_template", sa.Text(), nullable=True))
    if "code_font" not in cols:
        op.add_column(
            "users", sa.Column("code_font", sa.String(length=40), nullable=True)
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "users" not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "code_font" in cols:
        op.drop_column("users", "code_font")
    if "code_template" in cols:
        op.drop_column("users", "code_template")
