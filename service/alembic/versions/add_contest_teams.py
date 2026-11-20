"""add contest teams support

Revision ID: add_contest_teams
Revises: clamp_negative_contribution
Create Date: 2026-10-13

支持组队参赛模式：
1. contests 表增加 is_team_contest (bool) 和 max_team_members (int) 字段；
2. 新增 contest_teams 表记录比赛参赛队伍及队长、加入口令；
3. contest_participants 表增加 team_id 外键关联；
4. submissions 表增加 contest_team_id 外键关联。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_contest_teams"
down_revision: Union[str, Sequence[str], None] = "clamp_negative_contribution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. contests 表增加 is_team_contest, max_team_members
    contests_cols = [c["name"] for c in insp.get_columns("contests")]
    with op.batch_alter_table("contests") as batch_op:
        if "is_team_contest" not in contests_cols:
            batch_op.add_column(
                sa.Column("is_team_contest", sa.Boolean(), nullable=False, server_default=sa.text("false"))
            )
        if "max_team_members" not in contests_cols:
            batch_op.add_column(
                sa.Column("max_team_members", sa.Integer(), nullable=False, server_default=sa.text("3"))
            )

    # 2. 创建 contest_teams 表
    if not insp.has_table("contest_teams"):
        op.create_table(
            "contest_teams",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "contest_id",
                sa.Integer(),
                sa.ForeignKey("contests.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("name", sa.String(length=50), nullable=False),
            sa.Column(
                "leader_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("invite_code", sa.String(length=32), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint("contest_id", "name", name="uq_contest_team_name"),
        )

    # 3. contest_participants 增加 team_id 字段
    part_cols = [c["name"] for c in insp.get_columns("contest_participants")]
    with op.batch_alter_table("contest_participants") as batch_op:
        if "team_id" not in part_cols:
            batch_op.add_column(
                sa.Column("team_id", sa.Integer(), nullable=True)
            )
            batch_op.create_foreign_key(
                "fk_contest_participants_team_id",
                "contest_teams",
                ["team_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_index("ix_contest_participants_team_id", ["team_id"])

    # 4. submissions 增加 contest_team_id 字段
    sub_cols = [c["name"] for c in insp.get_columns("submissions")]
    with op.batch_alter_table("submissions") as batch_op:
        if "contest_team_id" not in sub_cols:
            batch_op.add_column(
                sa.Column("contest_team_id", sa.Integer(), nullable=True)
            )
            batch_op.create_foreign_key(
                "fk_submissions_contest_team_id",
                "contest_teams",
                ["contest_team_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_index("ix_submissions_contest_team_id", ["contest_team_id"])


def downgrade() -> None:
    with op.batch_alter_table("submissions") as batch_op:
        batch_op.drop_constraint("fk_submissions_contest_team_id", type_="foreignkey")
        batch_op.drop_index("ix_submissions_contest_team_id")
        batch_op.drop_column("contest_team_id")

    with op.batch_alter_table("contest_participants") as batch_op:
        batch_op.drop_constraint("fk_contest_participants_team_id", type_="foreignkey")
        batch_op.drop_index("ix_contest_participants_team_id")
        batch_op.drop_column("team_id")

    op.drop_table("contest_teams")

    with op.batch_alter_table("contests") as batch_op:
        batch_op.drop_column("max_team_members")
        batch_op.drop_column("is_team_contest")
