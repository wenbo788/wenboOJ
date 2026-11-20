"""tickets add assignee_id

Revision ID: ticket_assignee
Revises: ticket_action_text
Create Date: 2026-08-28

责任人字段。
"""
from alembic import op
import sqlalchemy as sa

revision = "ticket_assignee"
down_revision = "ticket_action_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("assignee_id", sa.Integer(), nullable=True))
    # SQLite 不支持 ALTER TABLE ADD CONSTRAINT（alembic 直接 NotImplementedError），
    # 用 batch 模式：SQLite 走 copy-and-move，其他方言（生产 PG）退化为普通
    # ALTER，语义等价。否则全新库从零跑迁移链会卡死在这一步。
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.create_foreign_key(
            "fk_tickets_assignee", "users", ["assignee_id"], ["id"]
        )


def downgrade() -> None:
    op.drop_constraint("fk_tickets_assignee", "tickets", type_="foreignkey")
    op.drop_column("tickets", "assignee_id")
