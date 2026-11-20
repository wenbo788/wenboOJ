"""Battle & Rank models for 1v1 Arena."""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

# Tier definitions
TIER_BRONZE = "bronze"
TIER_SILVER = "silver"
TIER_GOLD = "gold"
TIER_PLATINUM = "platinum"
TIER_DIAMOND = "diamond"

TIER_ORDER = [TIER_BRONZE, TIER_SILVER, TIER_GOLD, TIER_PLATINUM, TIER_DIAMOND]

TIER_NAMES = {
    TIER_BRONZE: "青铜",
    TIER_SILVER: "白银",
    TIER_GOLD: "黄金",
    TIER_PLATINUM: "铂金",
    TIER_DIAMOND: "钻石",
}


class UserBattleStats(Base, TimestampMixin):
    """User rank stats and battle records."""

    __tablename__ = "user_battle_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )

    # Current tier: bronze / silver / gold / platinum / diamond
    tier: Mapped[str] = mapped_column(
        String(20), default=TIER_BRONZE, server_default=text("'bronze'"), nullable=False
    )
    # Sub-tier: 3 -> 2 -> 1 (III -> II -> I)
    sub_tier: Mapped[int] = mapped_column(
        Integer, default=3, server_default=text("3"), nullable=False
    )
    # Points in current sub-tier (0 - 100)
    points: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )

    # Battle match statistics
    total_matches: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    wins: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    losses: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    draws: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )

    win_streak: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    max_win_streak: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )

    # Relationship to User
    user: Mapped["User"] = relationship("User", lazy="selectin")  # noqa: F821

    @property
    def rank_score(self) -> int:
        """Global ladder rating score for matchmaking and ranking."""
        tier_idx = TIER_ORDER.index(self.tier) if self.tier in TIER_ORDER else 0
        sub_idx = max(0, 3 - self.sub_tier)  # III=0, II=1, I=2
        return tier_idx * 300 + sub_idx * 100 + self.points


class Battle(Base, TimestampMixin):
    """1v1 Battle match session."""

    __tablename__ = "battles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Mode: casual (normal) / ranked
    mode: Mapped[str] = mapped_column(
        String(20), default="casual", server_default=text("'casual'"), nullable=False
    )
    # Status: matching / ongoing / finished / cancelled
    status: Mapped[str] = mapped_column(
        String(20), default="ongoing", server_default=text("'ongoing'"), index=True, nullable=False
    )

    user1_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), index=True, nullable=False
    )
    user2_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), index=True, nullable=False
    )
    problem_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("problems.id"), index=True, nullable=False
    )

    # Winner user_id, or None if draw / ongoing
    winner_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )

    # Real-time state of players: coding / submitted / accepted / surrendered
    user1_status: Mapped[str] = mapped_column(
        String(20), default="coding", server_default=text("'coding'"), nullable=False
    )
    user2_status: Mapped[str] = mapped_column(
        String(20), default="coding", server_default=text("'coding'"), nullable=False
    )

    user1_submission_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user2_submission_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_seconds: Mapped[int] = mapped_column(
        Integer, default=1800, server_default=text("1800"), nullable=False
    )

    # Settlement detail: points changes, xp reward, finish reason
    settlement: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Relationships
    user1: Mapped["User"] = relationship("User", foreign_keys=[user1_id], lazy="selectin")  # noqa: F821
    user2: Mapped["User"] = relationship("User", foreign_keys=[user2_id], lazy="selectin")  # noqa: F821
    problem: Mapped["Problem"] = relationship("Problem", lazy="selectin")  # noqa: F821
