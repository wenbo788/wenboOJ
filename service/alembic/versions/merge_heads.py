"""merge heads

Revision ID: merge_heads
Revises: ticket_action_txt, add_team_discussions, dm_recall_reply, add_contest_team
Create Date: 2026-10-03

合并 ticket_action_txt / add_team_discussions / dm_recall_reply /
add_contest_team 四个链头，恢复单 head 状态。
"""
from alembic import op

revision = "merge_heads"
down_revision = (
    "ticket_action_txt",
    "add_team_discussions",
    "dm_recall_reply",
    "add_contest_team",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
