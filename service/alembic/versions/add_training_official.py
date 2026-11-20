"""trainings.is_official（官方题单显式标记）

Revision ID: add_training_official
Revises: create_user_clipboards
Create Date: 2026-10-11

背景：原先 official / user 题单分类靠 TrainingPlan.owner 的**实时**角色推导，
管理员被撤权后其历史题单会整块从官方 tab 消失并漂到用户 tab。
改为创建时把归属落库到 is_official，列表过滤只读该字段。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_training_official"
down_revision: Union[str, Sequence[str], None] = "create_user_clipboards"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("trainings") as batch:
        batch.add_column(
            sa.Column(
                "is_official",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.create_index(
            "ix_trainings_is_official", ["is_official"], unique=False
        )

    # 回填历史数据：作者当前为管理员/超管/题目管理者的题单归为官方，
    # 一次性固化，之后不再随权限变化漂移。
    op.execute(
        """
        UPDATE trainings
           SET is_official = true
         WHERE owner_id IN (
            SELECT id FROM users
             WHERE is_admin = true OR is_super_admin = true OR can_manage_problems = true
         )
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("trainings") as batch:
        batch.drop_index("ix_trainings_is_official")
        batch.drop_column("is_official")
