"""create battle tables (user_battle_stats / battles)

Revision ID: create_battle_tables
Revises: add_conversation_read (7fcd521be258)
Create Date: 2026-10-07

1v1 天梯对战：
- 新建 user_battle_stats 表（用户段位/积分/胜负统计）；
- 新建 battles 表（对战会话：双方、题目、状态、结算）；
- submissions 补 battle_id 列（1v1 对战提交关联，对战删除时置空）。

此前这些表/列没有任何迁移创建，只有手动脚本 scripts/init_battle_tables.py，
部署库上从未执行，导致天梯匹配接口一查 Battle 表就 UndefinedTable 500，
房间详情与对战提交一碰 submissions.battle_id 就 UndefinedColumn 500。

幂等：缺表才建、缺列才补，重复执行安全（兼容 create_all 建库后再跑迁移的部署方式）。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


def _missing_columns(bind, table: str, expected: set[str]) -> set[str]:
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns(table)}
    return expected - existing


revision: str = "create_battle_tables"
down_revision: Union[str, None] = "7fcd521be258"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ---- user_battle_stats 建表 ----
    if not inspector.has_table("user_battle_stats"):
        op.create_table(
            "user_battle_stats",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "tier",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'bronze'"),
            ),
            sa.Column(
                "sub_tier",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("3"),
            ),
            sa.Column(
                "points",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "total_matches",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "wins",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "losses",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "draws",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "win_streak",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "max_win_streak",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("user_id", name="uq_user_battle_stats_user_id"),
        )
        op.create_index(
            "ix_user_battle_stats_user_id", "user_battle_stats", ["user_id"]
        )

    # ---- battles 建表 ----
    if not inspector.has_table("battles"):
        op.create_table(
            "battles",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "mode",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'casual'"),
            ),
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'ongoing'"),
            ),
            sa.Column(
                "user1_id",
                sa.Integer(),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column(
                "user2_id",
                sa.Integer(),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column(
                "problem_id",
                sa.Integer(),
                sa.ForeignKey("problems.id"),
                nullable=False,
            ),
            sa.Column("winner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column(
                "user1_status",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'coding'"),
            ),
            sa.Column(
                "user2_status",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'coding'"),
            ),
            sa.Column("user1_submission_id", sa.Integer(), nullable=True),
            sa.Column("user2_submission_id", sa.Integer(), nullable=True),
            sa.Column(
                "started_at", sa.DateTime(timezone=True), nullable=False
            ),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "duration_seconds",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1800"),
            ),
            sa.Column("settlement", sa.JSON(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index("ix_battles_status", "battles", ["status"])
        op.create_index("ix_battles_user1_id", "battles", ["user1_id"])
        op.create_index("ix_battles_user2_id", "battles", ["user2_id"])
        op.create_index("ix_battles_problem_id", "battles", ["problem_id"])

    # ---- submissions 补 battle_id 列 ----
    if "battle_id" in _missing_columns(bind, "submissions", {"battle_id"}):
        op.add_column(
            "submissions",
            sa.Column(
                "battle_id",
                sa.Integer(),
                sa.ForeignKey("battles.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index("ix_submissions_battle_id", "submissions", ["battle_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    cols = {c["name"] for c in inspector.get_columns("submissions")}
    if "battle_id" in cols:
        op.drop_column("submissions", "battle_id")

    if inspector.has_table("battles"):
        op.drop_table("battles")
    if inspector.has_table("user_battle_stats"):
        op.drop_table("user_battle_stats")
