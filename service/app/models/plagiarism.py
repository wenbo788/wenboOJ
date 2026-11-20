"""提交查重（疑似抄袭）结果缓存。

只做**提示**，不自动判罚：查重结果仅供管理员人工确认，确认后再走既有的
「标记作弊者 / 取消成绩」流程。所以这张表只存「哪两份提交有多像」，
不存任何处罚状态。

为什么落库：同题同语言的提交两两比较是 O(n²)，把结果缓存下来管理后台才能
反复翻看、也能翻历史（每次重扫会覆盖同一范围内的旧结果）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class SimilarSubmissionPair(Base):
    """一对「疑似抄袭」的提交。

    ``submission_a_id < submission_b_id``（写入时排序），配合唯一约束保证
    同一对提交只会有一行，重扫时按 (a, b) upsert。
    """

    __tablename__ = "similar_submission_pairs"
    __table_args__ = (
        # 唯一性必须带上 scope：同一对提交既可能在「比赛扫描」里出现，
        # 也可能在「按题目扫描」里出现，两次都是合法结果（范围不同）。
        UniqueConstraint("scope", "submission_a_id", "submission_b_id",
                         name="uq_similar_pair"),
        # 管理后台按比赛/题目翻列表，这两个是最常用的过滤键
        Index("ix_similar_pairs_contest", "contest_id"),
        Index("ix_similar_pairs_problem", "problem_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 扫描范围标识：``contest:<id>`` 或 ``problem:<id>``。同一对提交在不同范围里
    # 都可能命中（比赛扫一次、按题目再扫一次），靠它区分归属、也用作唯一键前缀。
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    # NULL = 非比赛提交（按题目扫的常规提交）
    contest_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("contests.id", ondelete="SET NULL"), nullable=True
    )
    problem_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("problems.id", ondelete="CASCADE"), nullable=False
    )
    submission_a_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False
    )
    submission_b_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False
    )
    # 0..1 的相似度（Jaccard）
    score: Mapped[float] = mapped_column(Float, nullable=False)
    # 命中细节（共同的 k-gram 数 / 各自规模 / 阈值），便于解释「为什么判它像」
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # 三个关系都刻意 lazy="raise"（README 里那条约定）：这里的模型是给管理端
    # 一次性取出来展示的，漏了 eager load 直接报错，而不是在 async 会话里偷偷
    # 触发同步懒加载（MissingGreenlet）。见 api/admin_plagiarism.py 的 joinedload。
    problem: Mapped["Problem"] = relationship("Problem", lazy="raise")  # noqa: F821
    submission_a: Mapped["Submission"] = relationship(  # noqa: F821
        "Submission", foreign_keys=[submission_a_id], lazy="raise"
    )
    submission_b: Mapped["Submission"] = relationship(  # noqa: F821
        "Submission", foreign_keys=[submission_b_id], lazy="raise"
    )
