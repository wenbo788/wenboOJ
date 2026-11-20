"""虚拟参赛（virtual contest）。

一个人把一场**已结束**的比赛镜像出来自己再打一遍：题目、顺序、时长都一样，
但成绩只属于自己的这次虚拟赛 —— 不进原赛榜、不参与等级分结算。

这里只存「谁、对哪场比赛、从什么时候开始、到什么时候结束」；
提交通过 ``submissions.virtual_contest_id`` 关联过来。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class VirtualContest(Base):
    __tablename__ = "virtual_contests"
    __table_args__ = (
        # 查「我在这场比赛的虚拟赛」是最常用的入口
        Index("ix_virtual_user_source", "user_id", "source_contest_id"),
        # 同一个人在同一场比赛里**同时只能有一个进行中的虚拟赛**。
        # 光靠 start() 里的「先查后写」挡不住并发（两个请求同时查不到就会各插
        # 一条），这里用「部分唯一索引」在数据库层兜底（只约束 finished_at IS NULL
        # 的行，历史轮次不受影响）。
        Index(
            "uq_virtual_active",
            "user_id", "source_contest_id",
            unique=True,
            postgresql_where=text("finished_at IS NULL"),
            sqlite_where=text("finished_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source_contest_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contests.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 时长照抄原比赛（end_time - start_time），开始时间 + 时长
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 提前手动结束 / 到点后惰性标记；NULL = 仍在计时
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
