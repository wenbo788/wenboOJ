"""add problem_attachments (题目附件)

Revision ID: add_problem_att
Revises: add_team_banned
Create Date: 2026-10-08

题目附件表：挂题目上，单文件上限 16MB，随题目级联删除。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_problem_att"
down_revision: Union[str, Sequence[str], None] = "add_team_banned"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("problem_attachments"):
        op.create_table(
            "problem_attachments",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("problem_id", sa.Integer(),
                      sa.ForeignKey("problems.id", ondelete="CASCADE"), nullable=False),
            sa.Column("uploader_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("orig_name", sa.String(length=255), nullable=False),
            sa.Column("stored_path", sa.String(length=500), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("content_type", sa.String(length=100), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
        )
        op.create_index("ix_problem_attachments_problem_id", "problem_attachments", ["problem_id"])
        op.create_index("ix_problem_attachments_uploader_id", "problem_attachments", ["uploader_id"])
        # 落盘按 problem_id 分目录，不同题目下同名文件合法存在，
        # 因此唯一性只在 (problem_id, stored_path) 范围内成立，不能建全局唯一。
        op.create_unique_constraint(
            "uq_problem_attachments_pid_path",
            "problem_attachments",
            ["problem_id", "stored_path"],
        )


def downgrade() -> None:
    op.drop_constraint("uq_problem_attachments_pid_path", "problem_attachments", type_="unique")
    op.drop_index("ix_problem_attachments_uploader_id", table_name="problem_attachments")
    op.drop_index("ix_problem_attachments_problem_id", table_name="problem_attachments")
    op.drop_table("problem_attachments")
