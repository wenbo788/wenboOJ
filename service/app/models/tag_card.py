"""Tag 卡模型：用户可佩戴的称号卡（参照洛谷勋章）。

显示优先级见 User.display_tag：启用中的卡 > user_tag（管理后台设置）
> 管理员默认「管理员」；作弊者（非管理员）强制显示「作弊者」不被卡掩盖。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class UserTagCard(Base):
    __tablename__ = "user_tag_cards"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_tag_card"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    # 是否佩戴（同一用户同时只有一张启用：开启一张会自动停用其他）
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 授予者 ID（管理员授予时为管理员 ID，商店兑换为 NULL）
    granter_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # 授予者。刻意 lazy="raise"（别改回 joined/selectin，会复现线上 500）：
    # 这是自引用关系（User → 卡 → User），急切加载时 SQLAlchemy 的递归守卫会
    # 截断这条链，把「tag_cards 尚未加载」的半成品 User 实例塞进身份映射；
    # 之后任何地方命中该实例再读 display_tag（→ self.tag_cards）就会触发同步
    # 懒加载，async 下直接 MissingGreenlet → 500。线上表现：只有「对方恰好是
    # 自己某张卡的授予人」时，打开和他的私信才 500，与别人私信正常。
    # 需要授予人名字的地方一律显式 eager load（见 user_profile.py 的
    # joinedload 与公开资料接口的 selectinload 链），漏了会立刻报错而不是静默 IO。
    granter: Mapped["User | None"] = relationship(
        "User", foreign_keys=[granter_id], lazy="raise"
    )  # noqa: F821

    @property
    def granter_name(self) -> str | None:
        return self.granter.username if self.granter else None

