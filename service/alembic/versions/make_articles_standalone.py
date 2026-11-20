"""Make articles standalone with optional column, category and is_recommended.

Revision ID: make_articles_standalone
Revises: add_column_interactions
Create Date: 2026-10-04
"""

from alembic import op
import sqlalchemy as sa


revision = "make_articles_standalone"
down_revision = "add_column_interactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "column_articles" in tables:
        cols = [c["name"] for c in inspector.get_columns("column_articles")]
        with op.batch_alter_table("column_articles") as batch_op:
            # 1. 允许 column_id 为空（独立文章时 column_id 为 NULL）
            batch_op.alter_column("column_id", existing_type=sa.Integer(), nullable=True)

            # 2. 增加 category 字段（文章分类）
            if "category" not in cols:
                batch_op.add_column(
                    sa.Column("category", sa.String(50), nullable=False, server_default="算法理论")
                )
                batch_op.create_index("ix_column_articles_category", ["category"])

            # 3. 增加 is_recommended 字段（支持单篇文章独立推荐）
            if "is_recommended" not in cols:
                batch_op.add_column(
                    sa.Column("is_recommended", sa.Boolean(), nullable=False, server_default=sa.text("false"))
                )
                batch_op.create_index("ix_column_articles_is_recommended", ["is_recommended"])

            # 4. 增加 cover_url 字段（文章封面）
            if "cover_url" not in cols:
                batch_op.add_column(
                    sa.Column("cover_url", sa.String(500), nullable=True)
                )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "column_articles" in tables:
        cols = [c["name"] for c in inspector.get_columns("column_articles")]
        with op.batch_alter_table("column_articles") as batch_op:
            if "cover_url" in cols:
                batch_op.drop_column("cover_url")
            if "is_recommended" in cols:
                batch_op.drop_index("ix_column_articles_is_recommended")
                batch_op.drop_column("is_recommended")
            if "category" in cols:
                batch_op.drop_index("ix_column_articles_category")
                batch_op.drop_column("category")
            batch_op.alter_column("column_id", existing_type=sa.Integer(), nullable=False)
