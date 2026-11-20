"""create site_doc_logs table

Revision ID: create_site_doc_logs
Revises: 38b30d5fac75
Create Date: 2026-10-03

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'create_site_doc_logs'
down_revision = '38b30d5fac75'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'site_doc_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('key', sa.String(length=50), nullable=False),
        sa.Column('editor_id', sa.Integer(), nullable=True),
        sa.Column('old_title', sa.String(length=100), nullable=False, server_default=sa.text("''")),
        sa.Column('new_title', sa.String(length=100), nullable=False, server_default=sa.text("''")),
        sa.Column('old_content', sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column('new_content', sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['editor_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_site_doc_logs_key'), 'site_doc_logs', ['key'])


def downgrade() -> None:
    op.drop_index(op.f('ix_site_doc_logs_key'), table_name='site_doc_logs')
    op.drop_table('site_doc_logs')
