"""add training featured and public fields

Revision ID: add_training_featured
Revises: direct_messages
Create Date: 2026-10-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "add_training_featured"
down_revision: Union[str, None] = "dm_recall_reply"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = [c["name"] for c in inspector.get_columns("trainings")]

    with op.batch_alter_table("trainings") as batch_op:
        if "is_featured" not in columns:
            batch_op.add_column(
                sa.Column("is_featured", sa.Boolean(), server_default=sa.text("false"), nullable=False)
            )
            batch_op.create_index("ix_trainings_is_featured", ["is_featured"])
        if "is_public" not in columns:
            batch_op.add_column(
                sa.Column("is_public", sa.Boolean(), server_default=sa.text("true"), nullable=False)
            )
        if "updated_at" not in columns:
            batch_op.add_column(
                sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)
            )


def downgrade() -> None:
    with op.batch_alter_table("trainings") as batch_op:
        batch_op.drop_index("ix_trainings_is_featured")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("is_public")
        batch_op.drop_column("is_featured")
