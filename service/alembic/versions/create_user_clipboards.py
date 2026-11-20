"""create user_clipboards

Revision ID: create_user_clipboards
Revises: add_problem_att
Create Date: 2026-10-09 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "create_user_clipboards"
down_revision = "add_problem_att"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_clipboards",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="text"),
        sa.Column("title", sa.String(length=120), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_clipboards_user_id", "user_clipboards", ["user_id"])
    op.create_index("ix_user_clipboards_kind", "user_clipboards", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_user_clipboards_kind", table_name="user_clipboards")
    op.drop_index("ix_user_clipboards_user_id", table_name="user_clipboards")
    op.drop_table("user_clipboards")
