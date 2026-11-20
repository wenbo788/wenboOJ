"""Add column inclusion requests table.

Revision ID: add_column_inclusion_requests
Revises: 44609eff8cf4
Create Date: 2026-10-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_column_inclusion_requests"
down_revision: Union[str, Sequence[str], None] = "44609eff8cf4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "column_inclusion_requests" not in tables:
        op.create_table(
            "column_inclusion_requests",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("column_id", sa.Integer(), nullable=False),
            sa.Column("article_id", sa.Integer(), nullable=False),
            sa.Column("applicant_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
            sa.Column("message", sa.String(length=500), nullable=True),
            sa.Column("reply", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.ForeignKeyConstraint(["column_id"], ["columns.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["article_id"], ["column_articles.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["applicant_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_column_inclusion_requests_column_id_status", "column_inclusion_requests", ["column_id", "status"])
        op.create_index("ix_column_inclusion_requests_article_id_status", "column_inclusion_requests", ["article_id", "status"])
        op.create_index("ix_column_inclusion_requests_applicant_id", "column_inclusion_requests", ["applicant_id"])
        op.create_index("ix_column_inclusion_requests_status", "column_inclusion_requests", ["status"])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "column_inclusion_requests" in tables:
        op.drop_table("column_inclusion_requests")
