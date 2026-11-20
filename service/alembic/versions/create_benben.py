"""create benben table

Revision ID: create_benben
Revises: ticket_identity_snapshot
Create Date: 2026-10-02

笨笨表（社交动态）建表迁移。此前该表一直靠 Base.metadata.create_all 补齐，
导致空库上 alembic upgrade head 跑到 perf_indexes 时因 benben 不存在而失败。
按「现状」幂等建表，重复执行安全。
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    inspect,
)

revision = "create_benben"
down_revision = "ticket_identity_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("benben"):
        return
    op.create_table(
        "benben",
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column(
            "user_number",
            Integer,
            ForeignKey("users.user_number"),
            nullable=False,
            index=True,
        ),
        Column("content", Text, nullable=False),
        Column(
            "reply_to",
            Integer,
            ForeignKey("benben.id"),
            nullable=True,
            index=True,
        ),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default="now()"),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default="now()"),
    )


def downgrade() -> None:
    if inspect(op.get_bind()).has_table("benben"):
        op.drop_table("benben")
