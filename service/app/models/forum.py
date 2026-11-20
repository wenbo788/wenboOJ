"""讨论区模型（参照原站：站务版/题目总版/学术版/灌水区）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Text, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class ForumPost(Base, TimestampMixin):
    __tablename__ = "forum_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # siteaffairs 站务版 / problem 题目总版 / academics 学术版 / relevantaffairs 灌水区
    forum: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    author_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), index=True, nullable=False
    )
    # 置顶（列表最前）与锁定（禁止回复）——仅秩序管理可设置
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 关联题目（可选）：发帖时关联后无需在标题里写题号
    problem_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("problems.id", ondelete="SET NULL"),
        index=True, nullable=True,
    )

    # 软删除：删除后内容仍保留，供秩序管理在举报后台查看
    # delete_reason: multi_report 多人举报自动删除 / moderator 秩序管理删除 / self 作者自删
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False, index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delete_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)

    author: Mapped["User"] = relationship(  # noqa: F821
        "User", foreign_keys=[author_id], lazy="joined"
    )
    problem: Mapped["Problem"] = relationship(  # noqa: F821
        "Problem", foreign_keys=[problem_id], lazy="joined"
    )
    comments: Mapped[list["ForumComment"]] = relationship(
        back_populates="post", cascade="all, delete-orphan", order_by="ForumComment.id"
    )

    __table_args__ = (
        Index("ix_forum_posts_created_at", "created_at"),
        Index("ix_forum_posts_is_pinned", "is_pinned"),
    )


class ForumComment(Base, TimestampMixin):
    __tablename__ = "forum_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("forum_posts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    author_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), index=True, nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # 回复置顶（仅秩序管理可设置）：置顶回复在帖子详情页排在普通回复之前
    is_pinned: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )

    # 软删除（同 ForumPost）
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False, index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delete_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)

    author: Mapped["User"] = relationship(  # noqa: F821
        "User", foreign_keys=[author_id], lazy="joined"
    )
    post: Mapped["ForumPost"] = relationship(back_populates="comments")
