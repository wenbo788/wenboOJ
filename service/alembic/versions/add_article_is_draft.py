"""add column_articles.is_draft（文章草稿）

Revision ID: add_article_is_draft
Revises: 9a188982f9ac
Create Date: 2026-10-15

需求：文章支持「保存草稿」——未发布的草稿仅作者本人可见，可继续编辑后再发布。

纯新增列，默认 false，非空；SQLite 支持 ADD COLUMN 带默认值，无需 batch。
索引用于公开列表过滤（is_draft=false）与「我的草稿」查询。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_article_is_draft"
# 接在当前 main 的 head（难度改名与多链合并后的 9a188982f9ac）之后，保持单 head。
down_revision: Union[str, None] = "9a188982f9ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("column_articles")}
    if "is_draft" not in cols:
        op.add_column(
            "column_articles",
            sa.Column(
                "is_draft", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
        )
        op.create_index("ix_column_articles_is_draft", "column_articles", ["is_draft"])


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("column_articles")}
    if "is_draft" in cols:
        with op.batch_alter_table("column_articles") as batch:
            batch.drop_index("ix_column_articles_is_draft")
            batch.drop_column("is_draft")
