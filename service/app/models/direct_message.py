"""私信（NLNOC 直聊）消息模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class DirectMessage(Base):
    """一条私信。

    刻意不建会话表：同两个人之间的一组消息就是一个会话，
    「会话列表」由查询端按对方聚合得出（数据量级小，两条聚合 SQL 足够）。
    消息发出后除「撤回」外不再修改，因此只有 created_at，不需要 updated_at。
    """

    __tablename__ = "direct_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sender_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recipient_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    # 撤回状态位：撤回后正文在任何接口都不再下发（_message_out 统一遮蔽）
    is_recalled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )
    # 引用回复目标：裸列不加 FK（SQLite/PG 增量迁移都能直接 ALTER），
    # 归属校验在发送端点做；悬空引用（对方账号被删）出参侧降级为无引用
    reply_to_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 除撤回外消息发出后不再修改，因此只有 created_at，不需要 updated_at
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    sender: Mapped["User"] = relationship(  # noqa: F821
        "User", foreign_keys=[sender_id]
    )
    recipient: Mapped["User"] = relationship(  # noqa: F821
        "User", foreign_keys=[recipient_id]
    )
