"""群聊头像 URL + 群消息引用回复。

Revision ID: f3a91c7e52b8
Revises: d575c7fdcc94
Create Date: 2026-10-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f3a91c7e52b8"
down_revision = "d575c7fdcc94"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("reply_to_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "reply_to_id")
    op.drop_column("conversations", "avatar_url")
