from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "add_subtask_support"
down_revision: Union[str, None] = "add_article_interactions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. problems: subtask_config
    cols_problems = {c["name"] for c in insp.get_columns("problems")}
    if "subtask_config" not in cols_problems:
        op.add_column("problems", sa.Column("subtask_config", sa.JSON(), nullable=True))

    # 2. submissions: subtask_results
    cols_submissions = {c["name"] for c in insp.get_columns("submissions")}
    if "subtask_results" not in cols_submissions:
        op.add_column("submissions", sa.Column("subtask_results", sa.JSON(), nullable=True))

    # 3. problem_test_cases: subtask_id, subtask_score
    cols_cases = {c["name"] for c in insp.get_columns("problem_test_cases")}
    if "subtask_id" not in cols_cases:
        op.add_column("problem_test_cases", sa.Column("subtask_id", sa.Integer(), nullable=True))
        op.create_index("ix_problem_test_cases_subtask_id", "problem_test_cases", ["subtask_id"])
    if "subtask_score" not in cols_cases:
        op.add_column("problem_test_cases", sa.Column("subtask_score", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("problem_test_cases") as b:
        b.drop_index("ix_problem_test_cases_subtask_id")
        b.drop_column("subtask_score")
        b.drop_column("subtask_id")

    with op.batch_alter_table("submissions") as b:
        b.drop_column("subtask_results")

    with op.batch_alter_table("problems") as b:
        b.drop_column("subtask_config")
