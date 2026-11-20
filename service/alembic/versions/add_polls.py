"""站内投票：polls / poll_options / poll_votes

Revision ID: add_polls
Revises: add_similar_submission_pairs
Create Date: 2026-10-17

需求：管理名单上的人发起站内投票，登录用户一人一票（多选可勾多个、可改票）。

三张表全新建，纯新增，不动既有表。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_polls"
# 接在当前 main 的 head（查重表）之后，保持单链头
down_revision: Union[str, None] = "add_virtual_contest"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "polls" not in tables:
        op.create_table(
            "polls",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("allow_multiple", sa.Boolean(), nullable=False,
                      server_default=sa.text("false")),
            sa.Column("anonymous", sa.Boolean(), nullable=False,
                      server_default=sa.text("false")),
            sa.Column("show_results_before_end", sa.Boolean(), nullable=False,
                      server_default=sa.text("true")),
            sa.Column("created_by", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_polls_created_by", "polls", ["created_by"])

    if "poll_options" not in tables:
        op.create_table(
            "poll_options",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("poll_id", sa.Integer(),
                      sa.ForeignKey("polls.id", ondelete="CASCADE"), nullable=False),
            sa.Column("text", sa.String(length=200), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False,
                      server_default="0"),
            sa.UniqueConstraint("poll_id", "sort_order", name="uq_poll_option_order"),
        )
        op.create_index("ix_poll_options_poll", "poll_options", ["poll_id"])

    if "poll_votes" not in tables:
        op.create_table(
            "poll_votes",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("poll_id", sa.Integer(),
                      sa.ForeignKey("polls.id", ondelete="CASCADE"), nullable=False),
            sa.Column("option_id", sa.Integer(),
                      sa.ForeignKey("poll_options.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("poll_id", "user_id", "option_id", name="uq_poll_vote"),
        )
        op.create_index("ix_poll_votes_poll", "poll_votes", ["poll_id"])
        op.create_index("ix_poll_votes_user", "poll_votes", ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for t in ("poll_votes", "poll_options", "polls"):
        if t in tables:
            op.drop_table(t)
