"""follows 表对齐 Follow 模型：补 updated_at，并兜底补表/索引

Revision ID: follows_updated_at
Revises: create_follows
Create Date: 2026-10-01

背景：create_follows 当初漏建了 updated_at，而 Follow 模型继承 TimestampMixin
必然有这一列，于是关注接口查重用的

    SELECT follows.id, ..., follows.updated_at FROM follows

在 Postgres 上报 column "follows.updated_at" does not exist ——
POST/DELETE /users/{id}/follow 一律 500。而关注统计/粉丝列表只查 count 或
单列（id / created_at），全都不碰 updated_at，所以页面一切正常、
只有点「关注」才炸，前端弹的是兜底文案「操作失败」。

这张表历史上有过三种来源：alembic 迁移（缺列）、手工 SQL、
scripts/init_follows_table.py（SQLite 方言，Postgres 上根本跑不了）。
所以这里按「现状」幂等修复，重复执行安全：

    表不存在 → 按模型完整建表（含 updated_at + 两条索引）
    表在缺列 → 补列并回填，再收紧为 NOT NULL
    一切正常 → 空跑
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'follows_updated_at'
down_revision: Union[str, None] = 'create_follows'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 与 create_follows 建的两条二级索引保持一致（手工建表的库可能漏了它们）
FOLLOW_INDEXES = (
    ('ix_follows_follower_id', ['follower_id']),
    ('ix_follows_followee_id', ['followee_id']),
)


def _create_follows_table() -> None:
    """按 Follow 模型口径完整建表（库被手工清过 / 迁移没跑过时走这里）。"""
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


def _ensure_indexes() -> None:
    """缺哪条补哪条（已存在则跳过，避免 duplicate index）。"""
    existing = {ix['name'] for ix in sa.inspect(op.get_bind()).get_indexes('follows')}
    for name, columns in FOLLOW_INDEXES:
        if name not in existing:
            op.create_index(name, 'follows', columns)


def _add_updated_at(bind, columns: set) -> None:
    """补 updated_at 列并回填历史行。"""
    if bind.dialect.name == 'sqlite':
        # SQLite 的 ADD COLUMN 只接受常量默认值，「NOT NULL + DEFAULT
        # CURRENT_TIMESTAMP」会被直接拒掉，所以拆三步：
        # 加可空列 → 用 created_at 回填 → batch 模式重建表收紧成 NOT NULL。
        op.add_column('follows', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))
        if 'created_at' in columns:
            op.execute(sa.text('UPDATE follows SET updated_at = created_at'))
        with op.batch_alter_table('follows', recreate='always') as batch_op:
            batch_op.alter_column(
                'updated_at',
                existing_type=sa.DateTime(timezone=True),
                existing_nullable=True,
                nullable=False,
                server_default=sa.text('CURRENT_TIMESTAMP'),
            )
    else:
        # PostgreSQL：带默认值加列是元数据操作（PG11+ fast default），瞬间完成；
        # 再用 created_at 语义化回填历史行（这张表是新表，行数可忽略）。
        op.add_column(
            'follows',
            sa.Column(
                'updated_at',
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        if 'created_at' in columns:
            op.execute(sa.text('UPDATE follows SET updated_at = created_at'))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table('follows'):
        _create_follows_table()
        _ensure_indexes()
        return

    columns = {c['name'] for c in inspector.get_columns('follows')}
    if 'updated_at' not in columns:
        _add_updated_at(bind, columns)
    _ensure_indexes()


def downgrade() -> None:
    """结构对齐没有安全的逆操作：这条迁移可能压根没改表（列本来就存在），
    无条件删列会把原本完好的表弄坏。需要回退请先手工确认列的来历。
    """
