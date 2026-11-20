"""create reports table and soft-delete / timed-mute columns

Revision ID: create_reports
Revises: add_problem_review
Create Date: 2026-10-03

举报系统：
- 新建 reports 表（犇犇 / 帖子 / 帖子回复的举报记录）；
- benben / forum_posts / forum_comments 增加软删除四列
  （is_deleted / deleted_at / deleted_by_id / delete_reason），
  删除后内容保留，供秩序管理在举报后台查看；
- users 增加 speak_until（限时禁言到期时间）、
  malicious_report_count（恶意举报次数）、
  content_violation_count（内容违规次数）。

幂等：缺表才建、缺列才补，重复执行安全（兼容 create_all 建库后
再跑迁移的部署方式）。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "create_reports"
down_revision: Union[str, None] = "add_problem_review"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _missing_columns(bind, table: str, expected: set[str]) -> set[str]:
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns(table)}
    return expected - existing


def _add_soft_delete_columns(bind, table: str) -> None:
    missing = _missing_columns(
        bind,
        table,
        {"is_deleted", "deleted_at", "deleted_by_id", "delete_reason"},
    )
    if "is_deleted" in missing:
        op.add_column(
            table,
            sa.Column(
                "is_deleted",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
        op.create_index(f"ix_{table}_is_deleted", table, ["is_deleted"])
    if "deleted_at" in missing:
        op.add_column(
            table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
        )
    if "deleted_by_id" in missing:
        op.add_column(table, sa.Column("deleted_by_id", sa.Integer(), nullable=True))
    if "delete_reason" in missing:
        op.add_column(table, sa.Column("delete_reason", sa.String(length=30), nullable=True))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ---- reports 建表 ----
    if not inspector.has_table("reports"):
        op.create_table(
            "reports",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "reporter_id",
                sa.Integer(),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column("target_type", sa.String(length=20), nullable=False),
            sa.Column("target_id", sa.Integer(), nullable=False),
            sa.Column("category", sa.String(length=30), nullable=False),
            sa.Column("detail", sa.Text(), nullable=True),
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default="active",
            ),
            sa.Column("verdict", sa.String(length=20), nullable=True),
            sa.Column(
                "reviewed_by_id",
                sa.Integer(),
                sa.ForeignKey("users.id"),
                nullable=True,
            ),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        op.create_index("ix_reports_reporter_id", "reports", ["reporter_id"])
        op.create_index("ix_reports_target", "reports", ["target_type", "target_id"])
        op.create_index("ix_reports_status", "reports", ["status"])
        op.create_index("ix_reports_verdict", "reports", ["verdict"])
        # batch：SQLite 不支持 ALTER TABLE ADD CONSTRAINT（同 ticket_assignee）
        with op.batch_alter_table("reports") as batch_op:
            batch_op.create_unique_constraint(
                "uq_reports_once",
                ["reporter_id", "target_type", "target_id"],
            )

    # ---- 三张内容表的软删除列 ----
    _add_soft_delete_columns(bind, "benben")
    _add_soft_delete_columns(bind, "forum_posts")
    _add_soft_delete_columns(bind, "forum_comments")

    # ---- users：限时禁言与违规计数 ----
    user_missing = _missing_columns(
        bind,
        "users",
        {"speak_until", "malicious_report_count", "content_violation_count"},
    )
    if "speak_until" in user_missing:
        op.add_column(
            "users", sa.Column("speak_until", sa.DateTime(timezone=True), nullable=True)
        )
    if "malicious_report_count" in user_missing:
        op.add_column(
            "users",
            sa.Column(
                "malicious_report_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    if "content_violation_count" in user_missing:
        op.add_column(
            "users",
            sa.Column(
                "content_violation_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for column in ("content_violation_count", "malicious_report_count", "speak_until"):
        cols = {c["name"] for c in inspector.get_columns("users")}
        if column in cols:
            op.drop_column("users", column)

    for table in ("forum_comments", "forum_posts", "benben"):
        for column in ("delete_reason", "deleted_by_id", "deleted_at", "is_deleted"):
            cols = {c["name"] for c in inspector.get_columns(table)}
            if column in cols:
                op.drop_column(table, column)

    if inspector.has_table("reports"):
        op.drop_table("reports")
