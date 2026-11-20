"""训练题单模型。

- TrainingPlan：题单（标题/说明/创建者）
- TrainingProblem：题单题目（按 sort_order 展示顺序）
- 完成进度复用 submissions：用户对题单内某题存在 accepted 提交即视为完成
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class TrainingPlan(Base):
    __tablename__ = "trainings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 创建者；拥有编辑/删除自己题单的权限
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), index=True, nullable=False
    )
    is_featured: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=func.false(), nullable=False, index=True
    )
    is_public: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=func.true(), nullable=False
    )
    # 官方题单(P)标记：创建时按创建者角色一次性落库。
    # 不能靠 owner 当前角色实时推导——管理员被撤权后其历史题单会整块漂移到用户 tab。
    is_official: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=func.false(), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    owner: Mapped["User"] = relationship(  # noqa: F821
        "User", foreign_keys=[owner_id], lazy="joined"
    )
    problems: Mapped[list["TrainingProblem"]] = relationship(
        back_populates="training", cascade="all, delete-orphan",
        order_by="TrainingProblem.sort_order", lazy="selectin",
    )


# Alias for backward/naming compatibility
TrainingList = TrainingPlan


class TrainingProblem(Base):
    __tablename__ = "training_problems"
    __table_args__ = (
        UniqueConstraint("training_id", "problem_id", name="uq_training_problem"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    training_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("trainings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    problem_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("problems.id"), index=True, nullable=False
    )
    # 显示顺序 0,1,2…
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    training: Mapped["TrainingPlan"] = relationship(back_populates="problems")
    problem: Mapped["Problem"] = relationship("Problem", lazy="joined")  # noqa: F821
