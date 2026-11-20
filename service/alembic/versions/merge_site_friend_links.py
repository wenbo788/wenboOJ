"""merge site management and reports/award migration heads

Revision ID: merge_site_friend_links
Revises: 74827c0073a2, create_friend_links
Create Date: 2026-10-03

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "merge_site_friend_links"
down_revision = ("74827c0073a2", "create_friend_links")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
