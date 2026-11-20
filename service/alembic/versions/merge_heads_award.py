"""merge heads for award certification

Revision ID: merge_heads_award
Revises: add_team_discussions, ticket_action_txt
Create Date: 2026-10-03

合并 add_team_discussions 与 ticket_action_txt 两个链头。
（原写作 ticket_action_text_text，但该文件的 revision 实为 ticket_action_txt，
悬空引用会让 alembic 无法构建迁移图，此处修正。）
"""
from alembic import op
import sqlalchemy as sa


revision = "merge_heads_award"
down_revision = ("add_team_discussions", "ticket_action_txt")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
