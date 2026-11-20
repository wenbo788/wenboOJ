"""add battle_id to submissions

Revision ID: add_battle_id_to_submissions
Revises: widen_contest_visibility
Create Date: 2026-10-07
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "add_battle_id_to_submissions"
down_revision = "widen_contest_visibility"  
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "submissions",
        sa.Column("battle_id", sa.Integer(), nullable=True),
    )
    # 使用 batch_alter_table 保证 SQLite 兼容
    with op.batch_alter_table("submissions") as batch_op:
        batch_op.create_foreign_key(
            "fk_submissions_battle_id",
            "battles",
            ["battle_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_submissions_battle_id", ["battle_id"])


def downgrade() -> None:
    with op.batch_alter_table("submissions") as batch_op:
        batch_op.drop_index("ix_submissions_battle_id", if_exists=True)
        batch_op.drop_constraint("fk_submissions_battle_id", type_="foreignkey")
    op.drop_column("submissions", "battle_id")