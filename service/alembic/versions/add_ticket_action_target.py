"""add ticket_replies.action_target_user_id

Revision ID: add_ticket_action_target
Revises: add_theme_mode
Create Date: 2026-10-04

模型 TicketReply 新增动作目标用户列（如「将责任人指派为 X」里的 X），
此前模型已使用但缺少建列迁移，导致创建工单/回复 INSERT 500。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_ticket_action_target'
down_revision = 'add_theme_mode'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c['name'] for c in sa.inspect(bind).get_columns('ticket_replies')}
    if 'action_target_user_id' not in cols:
        op.add_column(
            'ticket_replies',
            sa.Column('action_target_user_id', sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            'fk_ticket_replies_action_target_user',
            'ticket_replies', 'users',
            ['action_target_user_id'], ['id'],
        )


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c['name'] for c in sa.inspect(bind).get_columns('ticket_replies')}
    if 'action_target_user_id' in cols:
        op.drop_constraint(
            'fk_ticket_replies_action_target_user',
            'ticket_replies', type_='foreignkey')
        op.drop_column('ticket_replies', 'action_target_user_id')
