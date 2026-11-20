"""add username and tag history

Revision ID: add_user_history
Revises: f9a2b3c4d5e6
Create Date: 2026-10-13

新增用户改名记录表 (username_history) 与 Tag 变动历史记录表 (user_tag_history)，
并在 user_tag_cards 中新增 granter_id 记录授予管理员。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_user_history"
down_revision: Union[str, Sequence[str], None] = "f9a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. user_tag_cards 增加 granter_id 字段
    with op.batch_alter_table("user_tag_cards") as batch_op:
        batch_op.add_column(sa.Column("granter_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_user_tag_cards_granter",
            "users",
            ["granter_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # 2. 改名历史记录表
    op.create_table(
        "username_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "operator_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("old_username", sa.String(length=50), nullable=False),
        sa.Column("new_username", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 3. Tag 变动历史记录表
    op.create_table(
        "user_tag_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "operator_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("tag_name", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("user_tag_history")
    op.drop_table("username_history")
    with op.batch_alter_table("user_tag_cards") as batch_op:
        batch_op.drop_constraint("fk_user_tag_cards_granter", type_="foreignkey")
        batch_op.drop_column("granter_id")
