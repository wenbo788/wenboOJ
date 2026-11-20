"""merge 比赛管理员提交保护与题单官方标记两条支线

Revision ID: f9a2b3c4d5e6
Revises: add_contest_hide_admin, e7b3c50891fa
Create Date: 2026-10-11

main 新增 add_contest_hide_admin（文件名 add_contest_hide_submissions_from_admin.py，
与 revision id 不一致），本分支已有 e7b3c50891fa 收束链，两支并行导致
Multiple head revisions。本迁移只合流，不含 schema 变更。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f9a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = (
    "add_contest_hide_admin",
    "e7b3c50891fa",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
