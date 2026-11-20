"""add site documents (help / rules)

Revision ID: add_site_documents
Revises: 21f9c6df791a, add_award_certification
Create Date: 2026-10-03

帮助中心 / 社区规则等站点文档（超级管理员可编辑）。
down_revision 用二元元组把 main 上两条并行链头（题目审核 / 奖项认证）
收敛为单一 head。
"""
from alembic import op
import sqlalchemy as sa


revision = "add_site_documents"
down_revision = ("21f9c6df791a", "add_award_certification")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_site_documents_key", "site_documents", ["key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_site_documents_key", table_name="site_documents")
    op.drop_table("site_documents")
