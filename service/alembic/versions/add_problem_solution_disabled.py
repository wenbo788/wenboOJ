from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'add_prob_solution_sub'
down_revision: Union[str, None] = 'add_battle_id_to_submissions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('problems')}
    if 'allow_solution_submission' not in cols:
        op.add_column(
            'problems',
            sa.Column(
                'allow_solution_submission',
                sa.Boolean(),
                server_default=sa.text('true'),
                nullable=False,
            ),
        )
        with op.batch_alter_table('problems') as batch_op:
            batch_op.create_index(
                'ix_problems_allow_solution_submission',
                ['allow_solution_submission'],
            )


def downgrade() -> None:
    with op.batch_alter_table('problems') as batch_op:
        batch_op.drop_index('ix_problems_allow_solution_submission', if_exists=True)
        batch_op.drop_column('allow_solution_submission')
