"""ticket_replies 补 action_target_user_id 列：工单动作关联目标用户.

模型（app/models/ticket.py）加这个字段时漏写了迁移 —— 生产库以非
alembic 路径拿到该列（oj-up 全表校验全绿为证），但全新库从零跑
迁移链会缺列，tickets 接口 SELECT 该列直接 500、oj-up 第 4 步校验
也会拦部署。

幂等策略：列已存在（生产）→ 整段跳过（绝不 batch copy 生产数据表）；
列缺失（全新库）→ add_column + batch 补 FK（SQLite 不支持
ALTER TABLE ADD CONSTRAINT，见 ticket_assignee）。

Revision ID: add_action_target
Revises: add_theme_hue
Create Date: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_action_target"
down_revision: Union[str, Sequence[str], None] = "add_theme_hue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "ticket_replies" not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns("ticket_replies")}
    if "action_target_user_id" in cols:
        return
    op.add_column(
        "ticket_replies",
        sa.Column("action_target_user_id", sa.Integer(), nullable=True),
    )
    with op.batch_alter_table("ticket_replies") as batch_op:
        batch_op.create_foreign_key(
            "fk_ticket_replies_action_target",
            "users", ["action_target_user_id"], ["id"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "ticket_replies" not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns("ticket_replies")}
    if "action_target_user_id" in cols:
        op.drop_column("ticket_replies", "action_target_user_id")
