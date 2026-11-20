"""add team problems

Revision ID: add_team_problems
Revises: add_team_join_requests
Create Date: 2026-09-12

团队私有题库：problems.team_id（归属团队，NULL=主题库）+ t_no（
团队题全局序号，跨团队共用一个序列：A 团 T1、B 团 T2……）。
"""
from alembic import op
import sqlalchemy as sa

revision = "add_team_problems"
down_revision = "add_team_join_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 约束类操作走 batch：SQLite 不支持 ALTER TABLE ADD CONSTRAINT（同 ticket_assignee）
    op.add_column(
        "problems",
        sa.Column("team_id", sa.Integer(), nullable=True),
    )
    op.add_column("problems", sa.Column("t_no", sa.Integer(), nullable=True))
    op.create_index("ix_problems_team_id", "problems", ["team_id"])
    with op.batch_alter_table("problems") as batch_op:
        batch_op.create_foreign_key(
            "fk_problems_team_id", "teams", ["team_id"], ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_unique_constraint("uq_problems_t_no", ["t_no"])


def downgrade() -> None:
    op.drop_constraint("uq_problems_t_no", "problems", type_="unique")
    op.drop_index("ix_problems_team_id", table_name="problems")
    op.drop_column("problems", "t_no")
    op.drop_column("problems", "team_id")
