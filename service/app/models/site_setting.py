"""站点级键值配置模型（顶栏公告 / 首页云图栏目等）。"""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SiteSetting(Base, TimestampMixin):
    __tablename__ = "site_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 配置键，如 announcement / home_cloud；唯一
    key: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    # 配置内容，JSON 结构
    value: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # 冗余文本，便于排查/备份时直接看
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
