"""Problem model（题库）."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

# 审核状态：draft 草稿（未提交公开）/ pending 待审核 / approved 已通过 / rejected 已驳回
REVIEW_DRAFT = "draft"
REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
REVIEW_REJECTED = "rejected"
REVIEW_STATUSES = (REVIEW_DRAFT, REVIEW_PENDING, REVIEW_APPROVED, REVIEW_REJECTED)


class Problem(Base, TimestampMixin):
    __tablename__ = "problems"

    # Integer (not BigInteger) so the PK auto-increments on SQLite
    # (INTEGER PRIMARY KEY -> rowid alias) as well as PostgreSQL (SERIAL).
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # 洛谷 8 级难度（含「暂无评定」），存字符串便于直接展示/过滤
    difficulty: Mapped[str] = mapped_column(
        String(20), nullable=False, default="暂无评定",
        server_default=text("'暂无评定'"), index=True,
    )
    # 题目来源（NOIP / Codeforces / 自拟 ...）
    source: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    # 算法标签数组（plain JSON 跨 SQLite/Postgres 通用）
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 题面（Markdown），按洛谷习惯分节存储；样例 I/O 以代码块形式写在题面里
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    background: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    input_format: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    output_format: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    hint: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    # 样例组：[{"input": "...", "output": "..."}]
    samples: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # 限制：时间 ms / 内存 MB
    time_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1000, server_default=text("1000")
    )
    memory_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=128, server_default=text("128")
    )

    # 预留统计（评测对接后更新），本轮恒为 0
    submit_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    solved_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    # 下架开关：管理员可先建草稿再完善题面
    is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    # 题解通道开关：管理员可关闭，关闭后普通用户无法提交题解
    allow_solution_submission: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
        server_default=text("true"), index=True,
    )
    is_spj: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    spj_language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    spj_code: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 子任务（捆绑测试）配置：[{"id": 1, "score": 30, "name": "Subtask 1"}, ...]
    subtask_config: Mapped[list | None] = mapped_column(JSON, nullable=True)


    # 团队私有题库：team_id 为空 = 非团队题；非空 = 团队题（T 编号）
    team_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("teams.id", ondelete="CASCADE"),
        index=True, nullable=True,
    )
    # 团队题全局序号（跨团队共用序列，如 T1、T10）
    t_no: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)

    # 非团队题归属，随公开审核状态走：
    # 草稿/待审核/被驳回（未正式公开）= 用户题，U 编号（is_official=False）；
    # 审核通过正式公开 = 进入主题库，P 编号（is_official=True）。
    is_official: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
        server_default=text("true"), index=True,
    )

    # 出题人（存量题可能为 NULL）
    author_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"),
        index=True, nullable=True,
    )
    author: Mapped["User | None"] = relationship(  # noqa: F821
        "User", foreign_keys=[author_id], lazy="joined"
    )

    # 公开审核：普通用户把题置为公开后进入 pending，管理员通过后才真正公开
    # 存量题默认 approved（server_default 回填），不受新流程影响
    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=REVIEW_APPROVED,
        server_default=text(f"'{REVIEW_APPROVED}'"), index=True,
    )
    # 驳回原因（approve 时清空）
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # 附件（PDF 题面、数据表、素材等）。
    # lazy="selectin"：详情序列化（with_description=True）要读 attachments，
    # 而详情对象的来源分散（get_by_id / create / update / zip 导入），
    # 逐处 options(selectinload) 太脆，漏一处就是异步懒加载炸点。
    # 代价是每次加载 Problem 多发一条 SELECT——已由 list_problems 的
    # options(noload(Problem.attachments)) 消除：列表序列化本就不读附件。
    attachments: Mapped[list["ProblemAttachment"]] = relationship(
        back_populates="problem", cascade="all, delete-orphan",
        order_by="ProblemAttachment.id", lazy="selectin",
    )

    # 题号不落库：团队题 T{n}；未公开题 U{1000+id}；公开题 P{1000+id}
    @property
    def problem_number(self) -> str:
        if self.team_id is not None:
            return f"T{self.t_no}" if self.t_no is not None else f"T{self.id}"
        if not self.is_official:
            return f"U{1000 + self.id}"
        return f"P{1000 + self.id}"


class ProblemAttachment(Base, TimestampMixin):
    __tablename__ = "problem_attachments"
    # 附件按 problem_id 分目录落盘，不同题目下同名文件合法存在，
    # 因此唯一性只在 (problem_id, stored_path) 范围内成立。
    __table_args__ = (
        UniqueConstraint(
            "problem_id", "stored_path", name="uq_problem_attachments_pid_path"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    problem_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("problems.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    uploader_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"),
        index=True, nullable=True,
    )
    orig_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # 唯一性由 __table_args__ 的 (problem_id, stored_path) 复合约束保证，
    # 此处不能再写 unique=True，否则 create_all 建的表会多出全局唯一索引，
    # 与 add_problem_attachments 迁移的 schema 不一致（测试/生产漂移）。
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)

    problem: Mapped["Problem"] = relationship(back_populates="attachments")
    uploader: Mapped["User | None"] = relationship(  # noqa: F821
        "User", foreign_keys=[uploader_id], lazy="joined"
    )
