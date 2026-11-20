"""Follow model for user follow relationships."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func as sa_func

from app.models.base import Base, TimestampMixin


class Follow(Base, TimestampMixin):
    __tablename__ = "follows"
    __table_args__ = (
        UniqueConstraint("follower_id", "followee_id", name="uq_follows_follower_followee"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    follower_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    followee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa_func.now(), nullable=False
    )

    # Relationships
    follower: Mapped["User"] = relationship(  # noqa: F821
        "User", foreign_keys=[follower_id], back_populates="following"
    )
    followee: Mapped["User"] = relationship(  # noqa: F821
        "User", foreign_keys=[followee_id], back_populates="followers"
    )
