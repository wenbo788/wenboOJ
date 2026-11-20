"""add award certification fields

Revision ID: add_award_certification
Revises: merge_heads_award
Create Date: 2026-10-03

用户奖项认证：real_name、oierdb_uid、oi_awards、oi_level、award_cert_status。
"""
from alembic import op
import sqlalchemy as sa


revision = "add_award_certification"
down_revision = "merge_heads_award"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("real_name", sa.String(50), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("oierdb_uid", sa.String(100), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("oi_awards", sa.JSON, nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("oi_level", sa.String(100), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "award_cert_status", sa.String(20),
            nullable=False, server_default=sa.text("'none'"),
        ),
    )
    op.create_index(
        "ix_users_award_cert_status", "users", ["award_cert_status"]
    )


def downgrade() -> None:
    op.drop_index("ix_users_award_cert_status", table_name="users")
    op.drop_column("users", "award_cert_status")
    op.drop_column("users", "oi_level")
    op.drop_column("users", "oi_awards")
    op.drop_column("users", "oierdb_uid")
    op.drop_column("users", "real_name")
