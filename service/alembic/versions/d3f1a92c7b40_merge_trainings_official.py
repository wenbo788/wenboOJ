"""merge trainings.is_official 与题解提交通道开关两条支线

Revision ID: d3f1a92c7b40
Revises: add_prob_solution_sub, add_training_official
Create Date: 2026-10-11

背景：本分支新增 trainings.is_official（官方题单显式标记），
main 同时新增了题解提交通道开关一支迁移，两支都挂在合并前的同一链头上。
不收成单头时 `alembic upgrade head` 报 Multiple head revisions are present，
部署流水线在对齐数据库那一步必挂。

本迁移只做链的合流，不含任何 schema 变更 —— 两侧的列/索引已各自在
add_training_official 与 add_prob_solution_sub 中落好。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d3f1a92c7b40"
down_revision: Union[str, Sequence[str], None] = (
    "add_prob_solution_sub",
    "add_training_official",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
