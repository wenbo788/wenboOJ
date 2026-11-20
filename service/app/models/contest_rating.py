"""比赛等级分（rating）：结算结果表。

一笔一行 = 「某人在某场结算赛里的名次与分数变化」，可追溯、可重算对照。
``users.rating`` 存的是最新值，这里存的是历史（含 before/after）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ContestRating(Base):
    """一场比赛里某个参赛者的等级分变化。"""

    __tablename__ = "contest_ratings"
    __table_args__ = (
        # 一个人在一场比赛里只会有一条结算记录（重复结算靠它兜底）
        UniqueConstraint("contest_id", "user_id", name="uq_contest_rating_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contest_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contests.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # 本场名次（1 基）与参赛人数，便于事后核对「加分是否合理」
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    participants: Mapped[int] = mapped_column(Integer, nullable=False)
    rating_before: Mapped[int] = mapped_column(Integer, nullable=False)
    rating_after: Mapped[int] = mapped_column(Integer, nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    # 结算时该用户的「已结算场次」（决定 K 系数），留档便于复算
    rated_contests_before: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    rated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
