"""clamp negative contribution to zero

Revision ID: clamp_negative_contribution
Revises: user_academic_mode
Create Date: 2026-10-13

把已经被扣成负数的贡献值抬回 0。

来龙去脉：出题拿到贡献后，用户可能已经在贡献商店兑换了 Tag 卡 / 买了
用户名颜色；此后题目被删、换出题人或难度调低，系统仍按原难度扣回贡献，
余额就被扣穿（services/judge.py 的 _add_contribution 原先没有下限）。
代码那边已经补上「扣到 0 为止」，这里把存量已经被扣负的记录修回来，
免得这些人一直卡在负数上（在贡献商店里连最便宜的东西都兑换不了）。
"""
from alembic import op
import sqlalchemy as sa

revision = "clamp_negative_contribution"
down_revision = "user_academic_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    # 幂等：表/列不在（比如空库先 create_all 了别的版本）时直接跳过
    if "contribution" not in cols:
        return
    bind.execute(sa.text("UPDATE users SET contribution = 0 WHERE contribution < 0"))


def downgrade() -> None:
    # 数据修复不可逆，也拿不回原来的负数，故不提供回滚
    pass
