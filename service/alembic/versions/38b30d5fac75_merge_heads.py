"""merge heads

Revision ID: 38b30d5fac75
Revises: add_site_documents, merge_site_friend_links
Create Date: 2026-10-03 15:30:43.901146

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '38b30d5fac75'
down_revision: Union[str, Sequence[str], None] = ('add_site_documents', 'merge_site_friend_links')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
