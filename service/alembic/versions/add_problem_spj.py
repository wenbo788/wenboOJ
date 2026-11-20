from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'add_problem_spj'
down_revision: Union[str, None] = 'follows_updated_at'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('problems')}
    if 'is_spj' not in cols:
        op.add_column('problems', sa.Column('is_spj', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    if 'spj_language' not in cols:
        op.add_column('problems', sa.Column('spj_language', sa.String(20), nullable=True))
    if 'spj_code' not in cols:
        op.add_column('problems', sa.Column('spj_code', sa.Text(), nullable=True))

def downgrade() -> None:
    with op.batch_alter_table('problems') as b:
        b.drop_column('spj_code')
        b.drop_column('spj_language')
        b.drop_column('is_spj')
