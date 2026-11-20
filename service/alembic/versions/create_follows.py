"""create follows table

Revision ID: create_follows
Revises: ticket_action_txt
Create Date: 2026-10-01 00:00:00.000000

注意：这条迁移早期漏建了 updated_at，而 Follow 模型经 TimestampMixin 必然有
这一列，导致 select(Follow) 引用不存在的 follows.updated_at、关注接口 500。
线上库已经跑过这条迁移（改它不会重跑），补列由 follows_updated_at 负责；
这里补上这一列，是让「全新数据库」一次就建对。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'create_follows'
down_revision: Union[str, None] = 'ticket_action_txt'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 幂等保护：这张表可能被手工 SQL / 修复脚本先建过（当时迁移链还没跑到
    # 这里），再 create_table 会撞 "relation already exists"，容器直接起不来。
    if sa.inspect(op.get_bind()).has_table('follows'):
        return

    op.create_table(
        'follows',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('follower_id', sa.Integer(), nullable=False),
        sa.Column('followee_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['follower_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['followee_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('follower_id', 'followee_id', name='uq_follows_follower_followee'),
    )
    op.create_index('ix_follows_follower_id', 'follows', ['follower_id'])
    op.create_index('ix_follows_followee_id', 'follows', ['followee_id'])


def downgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table('follows'):
        return
    op.drop_index('ix_follows_followee_id', table_name='follows')
    op.drop_index('ix_follows_follower_id', table_name='follows')
    op.drop_table('follows')
