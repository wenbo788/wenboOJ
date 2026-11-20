"""举报模型（犇犇 / 帖子 / 帖子回复）。

举报按 (举报人, 目标类型, 目标 id) 唯一：撤销后重新举报会重新激活
同一行，而不是新建。审核以「内容」为单位：同一目标下所有举报的
verdict 统一由秩序管理一次判定。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

# 目标类型
REPORT_BENBEN = "benben"
REPORT_POST = "post"
REPORT_COMMENT = "comment"
TARGET_TYPES = (REPORT_BENBEN, REPORT_POST, REPORT_COMMENT)

# 举报状态（举报人维度）
STATUS_ACTIVE = "active"      # 有效举报
STATUS_REVOKED = "revoked"    # 举报人撤销

# 审核判定（内容维度，整组一致）
VERDICT_GUILTY = "guilty"            # 举报成立：内容违规
VERDICT_FALSE = "false_report"       # 举报不成立：恶意举报


class Report(Base, TimestampMixin):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    reporter_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), index=True, nullable=False
    )
    # benben / post / comment
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # 举报分类（辱骂攻击/人肉、广告刷屏、色情违法、侵权抄袭/其他）
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    # 补充说明（选填）
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # active / revoked
    status: Mapped[str] = mapped_column(
        String(20), default=STATUS_ACTIVE, server_default=STATUS_ACTIVE, nullable=False
    )
    # null 未审核 / guilty / false_report
    verdict: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    reviewed_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    reporter: Mapped["User"] = relationship(  # noqa: F821
        "User", foreign_keys=[reporter_id], lazy="joined"
    )

    __table_args__ = (
        UniqueConstraint(
            "reporter_id", "target_type", "target_id", name="uq_reports_once"
        ),
        Index("ix_reports_target", "target_type", "target_id"),
        Index("ix_reports_status", "status"),
    )
