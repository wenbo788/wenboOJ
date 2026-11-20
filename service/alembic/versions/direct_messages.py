"""direct messages (NLNOC 私信)

Revision ID: direct_messages
Revises: create_trainings
Create Date: 2026-10-02

NLNOC 私信表。不建会话表：两个人之间的消息集即一个会话，
会话列表由 /api/messages/conversations 按对方聚合得出。
"""
from alembic import op
import sqlalchemy as sa

revision = "direct_messages"
down_revision = "create_trainings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "direct_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sender_id", sa.Integer(), nullable=False),
        sa.Column("recipient_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_direct_messages_sender_id", "direct_messages", ["sender_id"])
    op.create_index("ix_direct_messages_recipient_id", "direct_messages", ["recipient_id"])
    op.create_index("ix_direct_messages_is_read", "direct_messages", ["is_read"])
    op.create_index("ix_direct_messages_created_at", "direct_messages", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_direct_messages_created_at", table_name="direct_messages")
    op.drop_index("ix_direct_messages_is_read", table_name="direct_messages")
    op.drop_index("ix_direct_messages_recipient_id", table_name="direct_messages")
    op.drop_index("ix_direct_messages_sender_id", table_name="direct_messages")
    op.drop_table("direct_messages")
