"""站内投票（poll）。

谁能发起：任意管理员（白名单/超管/大管/题管/社管/泛管理员，口径就是
``permissions.is_any_admin``）。谁能投：登录用户，一人一票（多选则一份多选）。

三张表：
- ``polls``        投票主体（问题、截止时间、是否匿名、是否多选、结果何时公开）
- ``poll_options`` 选项
- ``poll_votes``   投票记录（多选时一人多行，一个选项一行）
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
    text as sa_text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Poll(Base):
    __tablename__ = "polls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 多选（False = 单选，一人只能选一个；改票会替换旧选择）
    allow_multiple: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    # 匿名：不展示投票人名单（票数照样统计）
    anonymous: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    # 投票结束前是否公开票数；关掉的话只有发起者/管理员能看到实时结果
    show_results_before_end: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 截止时间（NULL = 不自动截止，靠手动关闭）
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 手动关闭时间（提前结束）
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    options: Mapped[list["PollOption"]] = relationship(
        "PollOption", back_populates="poll", cascade="all, delete-orphan",
        order_by="PollOption.sort_order", lazy="selectin",
    )


class PollOption(Base):
    __tablename__ = "poll_options"
    __table_args__ = (
        UniqueConstraint("poll_id", "sort_order", name="uq_poll_option_order"),
        Index("ix_poll_options_poll", "poll_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    poll_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("polls.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(String(200), nullable=False)
    # server_default 与迁移脚本保持一致（直接 INSERT 时也有默认值）。
    # 注意用 sa_text：这个类里 `text` 是选项文本列，会把 sqlalchemy.text 遮住。
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sa_text("0")
    )

    poll: Mapped["Poll"] = relationship("Poll", back_populates="options")


class PollVote(Base):
    __tablename__ = "poll_votes"
    __table_args__ = (
        # 一个人对同一个选项只能投一票（多选时是「每个选项一行」）
        UniqueConstraint("poll_id", "user_id", "option_id", name="uq_poll_vote"),
        Index("ix_poll_votes_poll", "poll_id"),
        Index("ix_poll_votes_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    poll_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("polls.id", ondelete="CASCADE"), nullable=False
    )
    option_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("poll_options.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
