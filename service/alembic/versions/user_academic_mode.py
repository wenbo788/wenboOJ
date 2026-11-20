"""users add academic_mode

Revision ID: user_academic_mode
Revises: add_user_history
Create Date: 2026-10-11

学术模式开关（个人设置里的自律开关）：
开启后前端隐藏犇犇与灌水区，题目难度默认隐藏（可在题库页手动展开）。
默认关闭，因此存量用户行为完全不变。

注意 Revises：本迁移最初挂在 f9a2b3c4d5e6 后面，但 main 上已经先合入了
同样以它为父的 add_user_history，两边并排就成两个 head（upgrade 会报
"Multiple head revisions"）。所以这里改挂在 add_user_history 之后，
保持单链单头。
"""
from alembic import op
import sqlalchemy as sa

revision = "user_academic_mode"
down_revision = "add_user_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    # 幂等：create_all 建过表 / 重复执行时跳过
    if "academic_mode" in cols:
        return
    op.add_column(
        "users",
        sa.Column(
            "academic_mode",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    # 与 upgrade 一样做存在性检查：重复执行 / 列已被删掉时不该直接报错
    if "academic_mode" not in cols:
        return
    op.drop_column("users", "academic_mode")
