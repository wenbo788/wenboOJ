"""add contest rule_type

Revision ID: add_contest_rule_type
Revises: dm_recall_reply
Create Date: 2026-10-02

比赛赛制：acm / ioi / oi，默认 acm。
"""
from alembic import op
import sqlalchemy as sa

revision = "add_contest_rule_type"
down_revision = "add_training_featured"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contests",
        sa.Column("rule_type", sa.String(8), nullable=False,
                  server_default="'acm'"),
    )


def downgrade() -> None:
    op.drop_column("contests", "rule_type")
