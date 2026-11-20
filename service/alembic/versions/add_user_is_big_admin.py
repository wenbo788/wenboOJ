"""add is_big_admin field

Revision ID: add_user_is_big_admin
Revises: add_prob_solution_sub
Create Date: 2026-10-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_user_is_big_admin'
down_revision = 'add_prob_solution_sub'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('is_big_admin', sa.Boolean(), nullable=False, server_default='false')
    )


def downgrade() -> None:
    op.drop_column('users', 'is_big_admin')
