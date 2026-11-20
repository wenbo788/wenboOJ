"""merge_award_and_main_heads

Revision ID: 9ea61b0afa4d
Revises: 21f9c6df791a, add_award_certification
Create Date: 2026-10-03 13:48:00.230254

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9ea61b0afa4d'
down_revision: Union[str, Sequence[str], None] = ('21f9c6df791a', 'add_award_certification')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
