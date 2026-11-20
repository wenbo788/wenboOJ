"""专栏与专栏文章模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Column(Base, TimestampMixin):
    """用户专栏模型。"""

    __tablename__ = "columns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    author_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # 管理员设置的全站推荐（主页/文章广场展示）
    is_recommended: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False, index=True
    )
    # 专栏分类：算法理论，科技工程，娱乐，题解
    category: Mapped[str] = mapped_column(
        String(50), default="算法理论", server_default="算法理论", nullable=False, index=True
    )

    author: Mapped["User"] = relationship(  # noqa: F821
        "User", foreign_keys=[author_id], lazy="joined"
    )
    articles: Mapped[list["ColumnArticle"]] = relationship(
        back_populates="column",
        order_by="ColumnArticle.id.desc()", lazy="selectin",
        passive_deletes=True,
    )
    likes: Mapped[list["ColumnLike"]] = relationship(
        back_populates="column", cascade="all, delete-orphan", lazy="select",
        passive_deletes=True,
    )
    stars: Mapped[list["ColumnStar"]] = relationship(
        back_populates="column", cascade="all, delete-orphan", lazy="select",
        passive_deletes=True,
    )
    inclusion_requests: Mapped[list["ColumnInclusionRequest"]] = relationship(
        back_populates="column", cascade="all, delete-orphan", lazy="select",
        passive_deletes=True,
    )


class ColumnArticle(Base, TimestampMixin):
    """文章模型（支持独立文章与专栏文章）。"""

    __tablename__ = "column_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 可选归属专栏：NULL 表示独立文章，非 NULL 表示收录于专栏
    column_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("columns.id", ondelete="SET NULL"), index=True, nullable=True
    )
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 分类：算法理论，科技工程，娱乐，题解
    category: Mapped[str] = mapped_column(
        String(50), default="算法理论", server_default="算法理论", nullable=False, index=True
    )
    # 单篇文章推荐标记（文章广场精选推荐）
    is_recommended: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False, index=True
    )
    # 草稿标记：true 表示尚未发布，仅作者本人可见（所有公开列表/详情均须排除）
    is_draft: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False, index=True
    )
    author_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    view_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    # 关联题目：NULL 表示独立文章，非 NULL 表示针对某道题目的题解
    problem_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("problems.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # 全站推荐申请与审核状态：none（未申请）, pending（待审核）, approved（已通过）, rejected（已驳回）
    recommend_status: Mapped[str] = mapped_column(
        String(20), default="none", server_default=text("'none'"), nullable=False, index=True
    )
    # 推荐申请说明或驳回理由
    recommend_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    column: Mapped["Column | None"] = relationship(
        back_populates="articles", foreign_keys=[column_id], lazy="joined"
    )
    author: Mapped["User"] = relationship(  # noqa: F821
        "User", foreign_keys=[author_id], lazy="joined"
    )
    problem: Mapped["Problem | None"] = relationship(  # noqa: F821
        "Problem", foreign_keys=[problem_id], lazy="joined"
    )
    reviewer: Mapped["User | None"] = relationship(  # noqa: F821
        "User", foreign_keys=[reviewer_id], lazy="joined"
    )

    likes: Mapped[list["ArticleLike"]] = relationship(
        back_populates="article", cascade="all, delete-orphan", lazy="select",
        passive_deletes=True,
    )
    stars: Mapped[list["ArticleStar"]] = relationship(
        back_populates="article", cascade="all, delete-orphan", lazy="select",
        passive_deletes=True,
    )
    comments: Mapped[list["ArticleComment"]] = relationship(
        back_populates="article", cascade="all, delete-orphan",
        order_by="ArticleComment.id.asc()", lazy="select",
        passive_deletes=True,
    )
    inclusion_requests: Mapped[list["ColumnInclusionRequest"]] = relationship(
        back_populates="article", cascade="all, delete-orphan", lazy="select",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_column_articles_created_at", "created_at"),
    )


# 别名供通用文章接口使用
Article = ColumnArticle


class ColumnLike(Base, TimestampMixin):
    """专栏点赞。"""

    __tablename__ = "column_likes"
    __table_args__ = (
        UniqueConstraint("column_id", "user_id", name="uq_column_likes_column_user"),
        Index("ix_column_likes_column_id", "column_id"),
        Index("ix_column_likes_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    column_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("columns.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    column: Mapped["Column"] = relationship(back_populates="likes")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id], lazy="joined")  # noqa: F821


class ColumnStar(Base, TimestampMixin):
    """专栏收藏。"""

    __tablename__ = "column_stars"
    __table_args__ = (
        UniqueConstraint("column_id", "user_id", name="uq_column_stars_column_user"),
        Index("ix_column_stars_column_id", "column_id"),
        Index("ix_column_stars_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    column_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("columns.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    column: Mapped["Column"] = relationship(back_populates="stars")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id], lazy="joined")  # noqa: F821


class ArticleLike(Base, TimestampMixin):
    """文章点赞。"""

    __tablename__ = "article_likes"
    __table_args__ = (
        UniqueConstraint("article_id", "user_id", name="uq_article_likes_article_user"),
        Index("ix_article_likes_article_id", "article_id"),
        Index("ix_article_likes_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("column_articles.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    article: Mapped["ColumnArticle"] = relationship(back_populates="likes")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id], lazy="joined")  # noqa: F821


class ArticleStar(Base, TimestampMixin):
    """文章收藏。"""

    __tablename__ = "article_stars"
    __table_args__ = (
        UniqueConstraint("article_id", "user_id", name="uq_article_stars_article_user"),
        Index("ix_article_stars_article_id", "article_id"),
        Index("ix_article_stars_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("column_articles.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    article: Mapped["ColumnArticle"] = relationship(back_populates="stars")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id], lazy="joined")  # noqa: F821


class ArticleComment(Base, TimestampMixin):
    """文章评论。"""

    __tablename__ = "article_comments"
    __table_args__ = (
        Index("ix_article_comments_article_id", "article_id"),
        Index("ix_article_comments_author_id", "author_id"),
        Index("ix_article_comments_is_deleted", "is_deleted"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("column_articles.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )

    article: Mapped["ColumnArticle"] = relationship(back_populates="comments")
    author: Mapped["User"] = relationship("User", foreign_keys=[author_id], lazy="joined")  # noqa: F821


# 兼容别名
ColumnArticleLike = ArticleLike
ColumnArticleStar = ArticleStar
ColumnArticleComment = ArticleComment
ColumnComment = ArticleComment


class ColumnInclusionRequest(Base, TimestampMixin):
    """文章收录至专栏的申请。"""

    __tablename__ = "column_inclusion_requests"
    __table_args__ = (
        Index("ix_column_inclusion_requests_column_id_status", "column_id", "status"),
        Index("ix_column_inclusion_requests_article_id_status", "article_id", "status"),
        Index("ix_column_inclusion_requests_applicant_id", "applicant_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    column_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("columns.id", ondelete="CASCADE"), nullable=False
    )
    article_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("column_articles.id", ondelete="CASCADE"), nullable=False
    )
    applicant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # 状态：pending（待审核）, approved（已同意）, rejected（已拒绝）, cancelled（已撤回）
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", nullable=False, index=True
    )
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reply: Mapped[str | None] = mapped_column(String(500), nullable=True)

    column: Mapped["Column"] = relationship("Column", back_populates="inclusion_requests", foreign_keys=[column_id])
    article: Mapped["ColumnArticle"] = relationship("ColumnArticle", back_populates="inclusion_requests", foreign_keys=[article_id])
    applicant: Mapped["User"] = relationship("User", foreign_keys=[applicant_id], lazy="joined")  # noqa: F821

