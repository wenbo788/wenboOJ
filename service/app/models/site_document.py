"""站点文档（帮助中心 / 社区规则等）模型。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class SiteDocument(Base, TimestampMixin):
    """站点静态页面，按 ``key`` 唯一定位（如 help / rules）。

    编辑权限为秩序管理（can_manage_posts，管理员/超管默认具备）。
    """

    __tablename__ = "site_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(
        String(100), nullable=False, default="", server_default=text("''")
    )
    # 正文（Markdown）
    content: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class SiteDocLog(Base, TimestampMixin):
    """站点文档修改日志：每次保存记录前后快照，仅秩序管理可见。"""

    __tablename__ = "site_doc_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 文档 key（help / rules）
    key: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    editor_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    old_title: Mapped[str] = mapped_column(
        String(100), nullable=False, default="", server_default=text("''")
    )
    new_title: Mapped[str] = mapped_column(
        String(100), nullable=False, default="", server_default=text("''")
    )
    old_content: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    new_content: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )

    editor: Mapped["User"] = relationship(  # noqa: F821
        "User", foreign_keys=[editor_id], lazy="joined"
    )
