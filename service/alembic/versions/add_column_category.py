"""Add category to columns table.

Revision ID: add_column_category
Revises: create_columns
Create Date: 2026-10-03
"""

from alembic import op
import sqlalchemy as sa


revision = "add_column_category"
down_revision = "create_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = [c["name"] for c in inspector.get_columns("columns")] if "columns" in inspector.get_table_names() else []

    if "category" not in existing_columns:
        op.add_column(
            "columns",
            sa.Column(
                "category",
                sa.String(length=50),
                nullable=False,
                server_default="算法理论",
            ),
        )
        op.create_index("ix_columns_category", "columns", ["category"])


def downgrade() -> None:
    op.drop_index("ix_columns_category", table_name="columns")
    op.drop_column("columns", "category")
