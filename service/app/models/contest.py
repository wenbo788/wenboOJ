"""比赛模型。

- Contest：标题/简介/起止时间/创建者/赛制
- ContestProblem：比赛题目（按 sort_order 显示为 A/B/C/D…）
- ContestParticipant：报名记录
- 比赛内提交复用 Submission，新增 contest_id 列（NULL=常规提交）

赛制 rule_type：
- acm：通过题数降序 → 总罚时升序（无部分分）
- ioi：部分分制，每题取最高分，总分降序（赛中实时反馈）
- oi：部分分制，每题取最后一次提交分数，总分降序（赛中不反馈结果）
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Contest(Base):
    __tablename__ = "contests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 公开程度：public 公开赛 / private 邀请赛 / team_public 团队公开赛 / team 团队内部赛 / team_private 团队邀请赛
    visibility: Mapped[str] = mapped_column(
        String(14), nullable=False, default="public", server_default="'public'"
    )
    # 邀请赛报名邀请码（private / team_private 时必填）
    invite_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 举办团队（NULL = 站方比赛）；团队解散时其比赛一并删除
    team_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("teams.id", ondelete="CASCADE"),
        index=True, nullable=True,
    )
    # 赛制：acm / ioi / oi，默认 acm
    rule_type: Mapped[str] = mapped_column(
        String(8), nullable=False, default="acm", server_default="'acm'"
    )
    # 是否开启管理员参赛保护（比赛期间对非举办方管理员隐藏他人提交与代码）
    hide_submissions_from_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    # 是否为组队赛
    is_team_contest: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    # 每队最大成员数（默认 3）
    max_team_members: Mapped[int] = mapped_column(
        Integer, default=3, server_default=text("3"), nullable=False
    )
    # 是否计入比赛等级分（只有个人赛能开；组队赛结算口径歧义，MVP 不支持）
    is_rated: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 创建者（可编辑/删除比赛）
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    owner: Mapped["User"] = relationship(  # noqa: F821
        "User", foreign_keys=[owner_id], lazy="joined"
    )
    # 举办团队（joined：详情/列表序列化需同步访问 team.name）
    team: Mapped["Team | None"] = relationship(
        "Team", foreign_keys=[team_id], lazy="joined"
    )  # noqa: F821
    problems: Mapped[list["ContestProblem"]] = relationship(
        back_populates="contest", cascade="all, delete-orphan",
        order_by="ContestProblem.sort_order", lazy="selectin",
    )
    participants: Mapped[list["ContestParticipant"]] = relationship(
        back_populates="contest", cascade="all, delete-orphan", lazy="selectin"
    )
    teams: Mapped[list["ContestTeam"]] = relationship(
        back_populates="contest", cascade="all, delete-orphan", lazy="selectin"
    )


class ContestProblem(Base):
    __tablename__ = "contest_problems"
    __table_args__ = (
        UniqueConstraint("contest_id", "problem_id", name="uq_contest_problem"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contest_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contests.id", ondelete="CASCADE"), index=True, nullable=False
    )
    problem_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("problems.id"), index=True, nullable=False
    )
    # 显示顺序 0,1,2… → 别名 A/B/C/D
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    contest: Mapped["Contest"] = relationship(back_populates="problems")
    problem: Mapped["Problem"] = relationship("Problem", lazy="joined")  # noqa: F821


class ContestTeam(Base):
    """比赛参赛队伍模型（用于组队赛）。"""

    __tablename__ = "contest_teams"
    __table_args__ = (
        UniqueConstraint("contest_id", "name", name="uq_contest_team_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contest_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contests.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    leader_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    invite_code: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    contest: Mapped["Contest"] = relationship(back_populates="teams")
    leader: Mapped["User"] = relationship("User", foreign_keys=[leader_id], lazy="joined")  # noqa: F821
    members: Mapped[list["ContestParticipant"]] = relationship(
        back_populates="team", foreign_keys="ContestParticipant.team_id", lazy="selectin"
    )


class ContestParticipant(Base):
    __tablename__ = "contest_participants"
    __table_args__ = (
        UniqueConstraint("contest_id", "user_id", name="uq_contest_participant"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contest_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contests.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), index=True, nullable=False
    )
    team_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("contest_teams.id", ondelete="SET NULL"), index=True, nullable=True
    )
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    contest: Mapped["Contest"] = relationship(back_populates="participants")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id], lazy="joined")  # noqa: F821
    team: Mapped["ContestTeam | None"] = relationship(
        "ContestTeam", back_populates="members", foreign_keys=[team_id], lazy="joined"
    )
