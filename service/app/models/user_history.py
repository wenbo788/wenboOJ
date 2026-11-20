"""用户改名与 Tag 变动历史记录模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class UsernameHistory(Base):
    __tablename__ = "username_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    operator_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    old_username: Mapped[str] = mapped_column(String(50), nullable=False)
    new_username: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])  # noqa: F821
    operator: Mapped["User | None"] = relationship("User", foreign_keys=[operator_id], lazy="joined")  # noqa: F821


class UserTagHistory(Base):
    __tablename__ = "user_tag_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    operator_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # 操作动作：grant (授予Tag卡), revoke (删除Tag卡), shop_redeem (商店兑换), custom_tag (后台自定义头衔)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    tag_name: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])  # noqa: F821
    operator: Mapped["User | None"] = relationship("User", foreign_keys=[operator_id], lazy="joined")  # noqa: F821
