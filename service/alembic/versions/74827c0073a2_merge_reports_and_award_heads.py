"""merge_reports_and_award_heads

Revision ID: 74827c0073a2
Revises: 9ea61b0afa4d, merge_heads_reports
Create Date: 2026-10-03 14:18:31.380544

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '74827c0073a2'
down_revision: Union[str, Sequence[str], None] = ('9ea61b0afa4d', 'merge_heads_reports')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
