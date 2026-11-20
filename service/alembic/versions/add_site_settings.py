"""site_settings 表：站点级键值配置（顶栏公告 / 首页云图栏目）。

revision id ≤ 32 字符；沿用本仓库惯例：表不存在才建，幂等。
（表本身就是新增，无「表在列缺」场景，但建表判断仍然无害。）

Revises 用元组合流：add_conversation_read 与 add_ticket_action_target
此前是两个并列链头，把新迁移同时挂在它们之后，整条链收成单头，
`alembic upgrade head` 才能跑（否则报 Multiple head revisions）。

Revision ID: add_site_settings
Revises: add_conversation_read, add_ticket_action_target
Create Date: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_site_settings"
down_revision: Union[str, Sequence[str], None] = (
    "add_conversation_read",
    "add_ticket_action_target",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "site_settings" in set(inspector.get_table_names()):
        return
    op.create_table(
        "site_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column(
            "updated_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_site_settings_key", "site_settings", ["key"], unique=True)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "site_settings" not in set(inspector.get_table_names()):
        return
    op.drop_index("ix_site_settings_key", table_name="site_settings")
    op.drop_table("site_settings")
