"""add dissolved / dissolved_at to conversations

Revision ID: add_conversation_dissolved
Revises: create_battle_tables
Create Date: 2026-10-07

群聊解散功能：
- conversations 补 dissolved（是否已解散，默认 false）与 dissolved_at（解散时间）；
- 解散不可逆，成员保留、历史消息可读，仅禁止再发送；
- 解散时由服务层插入一条 sender_id 为空的系统消息
  「群主 {username} 解散了群聊」，前端渲染为居中系统提示。

幂等：缺列才补，重复执行安全（兼容 create_all 建库后再跑迁移的部署方式）。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_conversation_dissolved"
down_revision: Union[str, None] = "create_battle_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _missing_columns(bind, table: str, expected: set[str]) -> set[str]:
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns(table)}
    return expected - existing


def upgrade() -> None:
    bind = op.get_bind()
    missing = _missing_columns(bind, "conversations", {"dissolved", "dissolved_at"})

    if "dissolved" in missing:
        op.add_column(
            "conversations",
            sa.Column(
                "dissolved",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if "dissolved_at" in missing:
        op.add_column(
            "conversations",
            sa.Column("dissolved_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("conversations")}
    for column in ("dissolved_at", "dissolved"):
        if column in cols:
            op.drop_column("conversations", column)
