"""merge 大管角色与题单官方标记两条支线

Revision ID: e7b3c50891fa
Revises: add_user_is_big_admin, d3f1a92c7b40
Create Date: 2026-10-11

main 合入 add_user_is_big_admin（四级管理角色）时，本分支已有
d3f1a92c7b40 收束的双头链，两支并行导致 Multiple head revisions。
本迁移只合流，不含 schema 变更。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7b3c50891fa"
down_revision: Union[str, Sequence[str], None] = (
    "add_user_is_big_admin",
    "d3f1a92c7b40",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
