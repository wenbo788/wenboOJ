"""direct messages: recall + quote reply (撤回与引用回复)

Revision ID: dm_recall_reply
Revises: direct_messages
Create Date: 2026-10-02

NLNOC 私信的两列扩展：
  - is_recalled  撤回状态位（撤回后正文在任何接口不再下发）
  - reply_to_id  引用回复指向的消息 id（刻意裸列、不加 FK 约束：
                 SQLite/PG 都能直接 ALTER TABLE 加列，归属合法性由
                 发送端点校验；用户级联删除造成的悬空引用在出参侧
                 降级为「无引用」渲染）
"""
from alembic import op
import sqlalchemy as sa

revision = "dm_recall_reply"
down_revision = "direct_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "direct_messages",
        sa.Column(
            "is_recalled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "direct_messages",
        sa.Column("reply_to_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("direct_messages", "reply_to_id")
    op.drop_column("direct_messages", "is_recalled")
