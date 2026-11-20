"""merge heads for reports feature

Revision ID: merge_heads_reports
Revises: 21f9c6df791a, add_award_certification, add_user_problem_bank
Create Date: 2026-10-03

合并举报/审核（fork）与上游奖项认证、题目审核后的多个链头，
使 problems / users 的分支迁移重新收敛为单一 head。
"""
from alembic import op
import sqlalchemy as sa


revision = "merge_heads_reports"
down_revision = (
    "21f9c6df791a",
    "add_award_certification",
    "add_user_problem_bank",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
