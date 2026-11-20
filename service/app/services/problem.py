"""题目服务。"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

from app.models.problem import Problem, ProblemAttachment
from app.models.submission import Submission
from app.models.user import User


def attachment_dict(att: ProblemAttachment, problem_id: int | None = None) -> dict[str, Any]:
    """题目附件对外结构。

    download_url 由 problem_id 拼出，指向带可见性鉴权的下载接口，
    不再暴露磁盘相对路径或任何可直链下载的地址。
    """
    url = None
    if problem_id is not None:
        url = f"/problems/{problem_id}/attachments/{att.id}/download"
    return {
        "id": att.id,
        "orig_name": att.orig_name,
        "download_url": url,
        "size_bytes": att.size_bytes,
        "content_type": att.content_type,
        "uploader_name": (att.uploader.username if att.uploader else None),
        "created_at": att.created_at.isoformat() if att.created_at else None,
    }


def _user_brief(user: User | None) -> dict[str, Any] | None:
    """出题人简要信息（全站配色判定字段齐全；无出题人返回 None）。"""
    if user is None:
        return None
    return {
        "user_id": user.id,
        "username": user.username,
        "user_tag": user.display_tag,
        "is_admin": bool(user.is_admin),
        "is_super_admin": bool(user.is_super_admin),
        "is_banned": bool(user.is_banned),
        "is_cheater": bool(user.is_cheater),
        "can_manage_users": bool(user.can_manage_users),
        "can_manage_posts": bool(user.can_manage_posts),
        "can_manage_problems": bool(user.can_manage_problems),
        "color_tier": user.color_tier or "gray",
        "name_color": user.name_color,
        "user_number": user.user_number,
        "avatar_url": user.avatar_url or "",
        # 题解/出题人头像的在线点靠它判断；漏了就一直显示离线
        "last_seen": user.last_seen.isoformat() if user.last_seen else None,
    }


DIFFICULTY_RANKS: dict[str, int] = {
    "入门": 1,
    "普及-": 2,
    "普及": 3,
    "普及+/提高-": 4,
    # 历史别名（同 XP_BY_DIFFICULTY）：存量数据/部署窗口期仍可能是旧串，
    # 缺了它会按「未知难度」降级排序，造成题目列表/难度排序错位
    "普及+/提高": 4,
    "提高": 5,
    "提高+/省选-": 6,
    "省选/NOI-": 7,
    "NOI/NOI+/CTSC": 8,
}
PROBLEM_SUBMIT_THRESHOLD = 15


class ProblemService:
    """题库查询与增删改（静态方法，仿 TicketService）。"""

    DIFFICULTY_RANKS = DIFFICULTY_RANKS
    PROBLEM_SUBMIT_THRESHOLD = PROBLEM_SUBMIT_THRESHOLD

    @classmethod
    async def get_user_ac_count_ge_difficulty(
        cls, db: AsyncSession, user_id: int, target_difficulty: str
    ) -> tuple[int, list[str]]:
        """统计用户在目标难度及以上区间的主题库去重 AC 题数。"""
        rank = DIFFICULTY_RANKS.get(target_difficulty, 1)
        eligible = [d for d, r in DIFFICULTY_RANKS.items() if r >= rank]
        stmt = (
            select(func.count(func.distinct(Submission.problem_id)))
            .select_from(Submission)
            .join(Problem, Problem.id == Submission.problem_id)
            .where(
                Submission.user_id == user_id,
                Submission.status == "accepted",
                Problem.team_id.is_(None),
                Problem.difficulty.in_(eligible),
            )
        )
        count = (await db.execute(stmt)).scalar() or 0
        return count, eligible

    @classmethod
    async def get_problem_submit_eligibility(
        cls, db: AsyncSession, user: User
    ) -> dict[str, Any]:
        """获取当前用户投题审核门槛与各难度完成状态。"""
        can_bypass = bool(user.is_super_admin or user.can_manage_problems)
        stmt = (
            select(
                Problem.difficulty,
                func.count(func.distinct(Submission.problem_id)),
            )
            .select_from(Submission)
            .join(Problem, Problem.id == Submission.problem_id)
            .where(
                Submission.user_id == user.id,
                Submission.status == "accepted",
                Problem.team_id.is_(None),
                Problem.difficulty.in_(list(DIFFICULTY_RANKS.keys())),
            )
            .group_by(Problem.difficulty)
        )
        rows = (await db.execute(stmt)).all()
        exact_counts = {diff: count for diff, count in rows}

        stats = {}
        for diff, rank in DIFFICULTY_RANKS.items():
            ge_count = sum(
                exact_counts.get(other_diff, 0)
                for other_diff, other_rank in DIFFICULTY_RANKS.items()
                if other_rank >= rank
            )
            stats[diff] = {
                "exact_count": exact_counts.get(diff, 0),
                "ge_count": ge_count,
                "threshold": PROBLEM_SUBMIT_THRESHOLD,
                "qualified": can_bypass or (ge_count >= PROBLEM_SUBMIT_THRESHOLD),
            }

        return {
            "can_bypass": can_bypass,
            "threshold": PROBLEM_SUBMIT_THRESHOLD,
            "stats": stats,
        }

    @classmethod
    async def check_submit_eligibility(
        cls, db: AsyncSession, user: User, difficulty: str
    ) -> None:
        """检查用户是否有资格投递指定难度的公开题目进行审核。"""
        if user.is_super_admin or user.can_manage_problems:
            return
        count, _ = await cls.get_user_ac_count_ge_difficulty(db, user.id, difficulty)
        if count < PROBLEM_SUBMIT_THRESHOLD:
            diff_label = difficulty if difficulty in DIFFICULTY_RANKS else "入门"
            raise PermissionError(
                f"投递「{diff_label}」难度题目需在主题库通过至少 {PROBLEM_SUBMIT_THRESHOLD} 道该难度及以上题目（当前已通过 {count} 道）"
            )

    @staticmethod
    def _dict(p: Problem, *, with_description: bool = False) -> dict[str, Any]:
        d = {
            "id": p.id,
            "problem_number": p.problem_number,
            "title": p.title,
            "difficulty": p.difficulty,
            "source": p.source,
            "tags": p.tags or [],
            "author": _user_brief(getattr(p, "author", None)),
            "time_limit": p.time_limit,
            "memory_limit": p.memory_limit,
            "submit_count": p.submit_count,
            "solved_count": p.solved_count,
            # 通过率（0-100），无提交时为 None → 前端显示「暂无」
            "pass_rate": (
                round(p.solved_count / p.submit_count * 100, 1)
                if p.submit_count
                else None
            ),
            "is_public": p.is_public,
            "allow_solution_submission": bool(getattr(p, "allow_solution_submission", True)),
            "team_id": p.team_id,
            "t_no": p.t_no,
            "is_spj": bool(p.is_spj),
            "spj_language": p.spj_language,
            "subtask_config": p.subtask_config or [],
            # 审核状态：approved 才真正公开；pending/rejected 仅作者与管理员可见
            "review_status": p.review_status,
            "review_reason": p.review_reason,
            "reviewed_at": p.reviewed_at.isoformat() if p.reviewed_at else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        }
        if with_description:
            d["description"] = p.description
            d["background"] = p.background
            d["input_format"] = p.input_format
            d["output_format"] = p.output_format
            d["hint"] = p.hint
            d["spj_code"] = p.spj_code
            d["samples"] = [
                {"input": s.get("input", ""), "output": s.get("output", "")}
                for s in (p.samples or [])
                if isinstance(s, dict)
            ]
            d["attachments"] = [attachment_dict(a, problem_id=p.id) for a in (p.attachments or [])]
        return d

    @staticmethod
    async def get_by_id(db: AsyncSession, problem_id: int) -> Optional[Problem]:
        # selectinload：详情序列化（with_description=True）会读 attachments，
        # 这里按需一次性加载，避免模型默认 selectin 拖慢所有列表查询
        result = await db.execute(
            select(Problem)
            .options(selectinload(Problem.attachments))
            .where(Problem.id == problem_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def attach_user_status(
        db: AsyncSession, problems: list[Problem], user_id: Optional[int]
    ) -> dict[int, str]:
        """批量查询当前用户在这批题目上的完成状态。

        返回 ``{problem_id: "accepted" | "attempted"}``（未提交的题不在结果里）。
        一页题目只发一条 SQL，走 submissions 的 (problem_id, user_id) 索引；
        accepted 优先于 attempted（同题既有 AC 又有非 AC 时算 AC）。
        """
        if not user_id or not problems:
            return {}
        ids = [p.id for p in problems]
        rows = (await db.execute(
            select(Submission.problem_id, Submission.status)
            .where(
                Submission.user_id == user_id,
                Submission.problem_id.in_(ids),
            )
            .distinct()
        )).all()
        accepted: set[int] = set()
        attempted: set[int] = set()
        for problem_id, st in rows:
            (accepted if st == "accepted" else attempted).add(problem_id)
        return {
            problem_id: ("accepted" if problem_id in accepted else "attempted")
            for problem_id in (accepted | attempted)
        }

    @staticmethod
    async def list_problems(
        db: AsyncSession,
        *,
        difficulty: Optional[str] = None,
        source: Optional[str] = None,
        tag: Optional[str] = None,
        keyword: Optional[str] = None,
        include_private: bool = False,
        user_id: Optional[int] = None,
        page: int = 0,
        page_size: int = 20,
        mine: bool = False,
        review_status: Optional[str] = None,
        review_scope: bool = False,
    ) -> dict[str, Any]:
        """题目列表：筛选 → 计数 → 分页（按题号升序，洛谷习惯）。

        只含主题库题（team_id 为空）；团队私有题走团队页的独立列表。
        传入 ``user_id`` 时，每条 item 附带 ``my_status``：accepted /
        attempted / None（从未提交），供题库列表展示做题状态。

        可见性四种口径：
        - ``mine=True``：**我的题库** —— 只看自己出的题（草稿/待审核/被驳回/
          已进主题库全都在）。U 题归这里，不进主题库列表
        - ``review_scope=True``：审核后台（题目管理权限），全部状态可见，
          再由 ``review_status`` 过滤
        - ``include_private=True``：只放宽「公开且已通过」这一层，仍然**只含
          已进主题库的题**（is_official=True / P 编号）
        - 默认：仅 ``is_public=True`` 且 ``review_status=approved`` 的题
        """
        # noload：列表序列化（with_description=False）不读 attachments，
        # 关闭 selectin 的额外 SELECT，消除列表查询的 N+1
        query = select(Problem).options(noload(Problem.attachments)).where(Problem.team_id.is_(None))
        if mine:
            # 「我的题库」必须有明确的作者；未登录直接给空集
            query = query.where(Problem.author_id == (user_id or -1))
        elif review_scope:
            # 审核队列：全部审核状态都可见（U 题都在这一侧），由 review_status 过滤
            pass
        else:
            # 主题库列表只含「已进主题库」的题（is_official=True，即 P 编号）。
            # U 题（草稿 / 待审核 / 被驳回）不属于主题库——它们归作者自己的
            # 「我的题库」。此前这里会把 U 题一并列出（题目管理员视角尤其明显），
            # 主题库里因此混着 U 编号的题。
            query = query.where(Problem.is_official.is_(True))
            if not include_private:
                query = query.where(
                    Problem.is_public.is_(True),
                    Problem.review_status == "approved",
                )
        if review_status:
            query = query.where(Problem.review_status == review_status)

        if difficulty:
            query = query.where(Problem.difficulty == difficulty.replace(" ", "+"))
        if source:
            query = query.where(Problem.source == source)
        if tag:
            # 跨库写法：SQLite 中 JSON 即 TEXT，PG 上 CAST 合法；
            # 引号定界避免「DP」误命中「DP优化」
            query = query.where(cast(Problem.tags, String).ilike(f'%"{tag}"%'))
        if keyword:
            kw = keyword.strip()
            cond = Problem.title.ilike(f"%{kw}%")
            # 支持 P1001 / U1001 / 1001 搜法定位题号（题号 = 1000 + id）
            upper = kw.upper()
            digits = kw[1:] if upper.startswith(("P", "U")) else kw
            if digits.isdigit():
                ids = {int(digits), int(digits) - 1000}
                cond = or_(cond, Problem.id.in_({i for i in ids if i > 0}))
            query = query.where(cond)

        total_result = await db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = total_result.scalar() or 0

        result = await db.execute(
            query.order_by(Problem.id.asc())
            .offset(page * page_size)
            .limit(page_size)
        )
        problems = result.scalars().all()

        status_map = await ProblemService.attach_user_status(db, problems, user_id)
        items = []
        for p in problems:
            item = ProblemService._dict(p)
            item["my_status"] = status_map.get(p.id)
            items.append(item)

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items,
        }

    @staticmethod
    async def list_sources(db: AsyncSession) -> list[str]:
        """去重后的非空来源列表（仅已通过审核的主题库题，筛选下拉用）。"""
        result = await db.execute(
            select(Problem.source)
            .where(Problem.source.isnot(None), Problem.source != "",
                   Problem.team_id.is_(None),
                   Problem.is_public.is_(True),
                   Problem.review_status == "approved")
            .distinct()
            .order_by(Problem.source.asc())
        )
        return [s for s in result.scalars().all() if s]

    @staticmethod
    async def create(db: AsyncSession, data: dict[str, Any]) -> Problem:
        problem = Problem(**data)
        db.add(problem)
        await db.commit()
        await db.refresh(problem)
        return problem

    @staticmethod
    async def create_without_commit(db: AsyncSession, data: dict[str, Any]) -> Problem:
        problem = Problem(**data)
        db.add(problem)
        await db.flush()
        await db.refresh(problem)
        return problem

    @staticmethod
    async def update(
        db: AsyncSession, problem: Problem, data: dict[str, Any]
    ) -> Problem:
        for field, value in data.items():
            setattr(problem, field, value)
        await db.commit()
        await db.refresh(problem)
        return problem
