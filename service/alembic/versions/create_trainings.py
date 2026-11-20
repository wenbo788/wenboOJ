"""create trainings

Revision ID: create_trainings
Revises: follows_updated_at
Create Date: 2026-10-02

训练题单功能：trainings + training_problems。

背景：题单功能提交（0a1f776）误删了 alembic/versions 下全部历史迁移，
且该功能本身从未补过建表迁移——部分环境（如生产库）的这两张表是
create_all 带出来的。因此这里按「现状」幂等建表，重复执行安全：

    表不存在 → 按模型完整建表（含索引/唯一约束）
    表已存在 → 空跑
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "create_trainings"
down_revision: Union[str, None] = "add_problem_spj"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_trainings_table() -> None:
    """按 TrainingPlan 模型口径建表。"""
    op.create_table(
        "trainings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.Integer(),
                  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_trainings_owner_id", "trainings", ["owner_id"])


def _create_training_problems_table() -> None:
    """按 TrainingProblem 模型口径建表。"""
    op.create_table(
        "training_problems",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("training_id", sa.Integer(),
                  sa.ForeignKey("trainings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("problem_id", sa.Integer(),
                  sa.ForeignKey("problems.id"), nullable=False),
        # 显示顺序 0,1,2…；与模型一致：仅 Python 侧 default=0，无 server_default
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.UniqueConstraint("training_id", "problem_id", name="uq_training_problem"),
    )
    op.create_index("ix_training_problems_training_id", "training_problems", ["training_id"])
    op.create_index("ix_training_problems_problem_id", "training_problems", ["problem_id"])


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if not inspector.has_table("trainings"):
        _create_trainings_table()
    if not inspector.has_table("training_problems"):
        _create_training_problems_table()


def downgrade() -> None:
    op.drop_table("training_problems")
    op.drop_table("trainings")
