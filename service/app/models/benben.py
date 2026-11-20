"""Benben (Social Media Post) model."""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func, text
from typing import TYPE_CHECKING

from app.models.base import Base, TimestampMixin

# 前向引用User类型（避免循环导入）
if TYPE_CHECKING:
    from app.models.user import User


class Benben(Base, TimestampMixin):
    __tablename__ = "benben"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_number: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.user_number"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    reply_to: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("benben.id"), nullable=True, index=True
    )
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 软删除：删除后内容仍保留在数据库，供秩序管理在举报后台查看
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False, index=True
    )
    deleted_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # multi_report 多人举报自动删除 / moderator 秩序管理删除 / self 作者自删
    delete_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # 关系
    user: Mapped["User"] = relationship("User", back_populates="benben_posts")
    replies: Mapped[list["Benben"]] = relationship(
        "Benben", back_populates="parent_post", remote_side=[id]
    )
    parent_post: Mapped["Benben | None"] = relationship(
        "Benben", remote_side=[id], foreign_keys=[reply_to]
    )