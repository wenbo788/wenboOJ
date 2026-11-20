"""column_likes / column_stars 补 updated_at 列.

add_column_interactions 的 upgrade 里其实带了补列的 else 分支，但那是
后来改进「已应用的迁移文件」里的 —— 该 revision 在生产早已 applied，
alembic 不会重放旧迁移，补丁永远跑不到，两张表的 updated_at 一直缺着。

教训：
  1. 改已生效的迁移文件对存量库无效，补列必须走新迁移；
  2. revision id 必须 ≤ 32 字符 —— alembic_version.version_num 是
     VARCHAR(32)，超长在 PostgreSQL 上写版本号直接报
     StringDataRightTruncationError，而 SQLite 不强制 VARCHAR 长度、
     本地能跑通（本文件初版 add_column_interactions_updated_at 34 字符
     就是这样在生产炸的，已改名为 add_likes_stars_updated_at）。

（TimestampMixin 的口径：DateTime(timezone=True)，默认值取当前时间。）

Revision ID: add_likes_stars_updated_at
Revises: add_user_color_tier
Create Date: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_likes_stars_updated_at"
down_revision: Union[str, Sequence[str], None] = "add_user_color_tier"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("column_likes", "column_stars")


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())
    for table in TABLES:
        # 全新库由 add_column_interactions 的建表分支负责（本身就带 updated_at），
        # 这里只处理「表在、列缺」的存量库；存在性检查也让重放不会报错。
        if table not in existing_tables:
            continue
        cols = {c["name"] for c in inspector.get_columns(table)}
        if "updated_at" not in cols:
            op.add_column(
                table,
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.text("CURRENT_TIMESTAMP"),
                    nullable=False,
                ),
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())
    for table in TABLES:
        if table not in existing_tables:
            continue
        cols = {c["name"] for c in inspector.get_columns(table)}
        if "updated_at" in cols:
            op.drop_column(table, "updated_at")
