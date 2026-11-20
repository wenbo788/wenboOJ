"""提交查重结果表 similar_submission_pairs（疑似抄袭榜）

Revision ID: add_similar_submission_pairs
Revises: add_article_is_draft
Create Date: 2026-10-17

需求：管理后台出一张「疑似抄袭」榜 —— 同题同语言的提交两两算相似度，
超过阈值就记一笔给管理员人工确认（只提示，不自动判罚）。

为什么落库而不是每次现算：两两比是 O(n²)，后台还要反复翻看、看历史。
本表只存「哪两份提交有多像」，不存任何处罚状态。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_similar_submission_pairs"
# 接在当前 head（文章草稿）之后，保持单链头
down_revision: Union[str, None] = "add_article_is_draft"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "similar_submission_pairs" in tables:
        return

    op.create_table(
        "similar_submission_pairs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("contest_id", sa.Integer(),
                  sa.ForeignKey("contests.id", ondelete="SET NULL"), nullable=True),
        sa.Column("problem_id", sa.Integer(),
                  sa.ForeignKey("problems.id", ondelete="CASCADE"), nullable=False),
        sa.Column("submission_a_id", sa.Integer(),
                  sa.ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("submission_b_id", sa.Integer(),
                  sa.ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("scope", "submission_a_id", "submission_b_id",
                            name="uq_similar_pair"),
    )
    op.create_index("ix_similar_pairs_contest", "similar_submission_pairs",
                    ["contest_id"])
    op.create_index("ix_similar_pairs_problem", "similar_submission_pairs",
                    ["problem_id"])
    op.create_index("ix_similar_pairs_scope", "similar_submission_pairs", ["scope"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "similar_submission_pairs" not in tables:
        return
    op.drop_index("ix_similar_pairs_scope", table_name="similar_submission_pairs")
    op.drop_index("ix_similar_pairs_problem", table_name="similar_submission_pairs")
    op.drop_index("ix_similar_pairs_contest", table_name="similar_submission_pairs")
    op.drop_table("similar_submission_pairs")
