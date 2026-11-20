"""评测提交 API（提交 / 记录 / 详情 / 测试点管理）。"""

from __future__ import annotations

import logging
import re
from typing import Optional

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, status, UploadFile
from sqlalchemy import delete, func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.problems import (
    _can_view_main_problem,
    _resolve_contest_problem_access,
)
from app.core.database import get_db
from app.deps import get_current_user
from app.models.contest import Contest, ContestParticipant, ContestProblem
from app.models.problem import Problem, REVIEW_APPROVED
from app.models.submission import Submission, TestCase
from app.models.team import Team, TeamMember
from app.models.user import User
from app.schemas.submission import (
    ProblemSubtasksUpdateRequest,
    SubmissionCancelScoreRequest,
    SubmissionCreate,
    SubmissionRejudgeRequest,
    TestCaseBatchDeleteRequest,
    TestCaseCreate,
    TestCaseUpdate,
)
from app.services.contest import (
    is_contest_organizer,
    get_shielded_contest_for_problem,
    is_team_organizing_shielded_contest,
)
from app.services.judge import XP_BY_DIFFICULTY, judge_submission, judge_submissions
from app.services import virtual_contest as virtual_service
from app.utils.ratelimit import check

logger = logging.getLogger(__name__)

router = APIRouter(tags=["submissions"])


def _can_manage(user: User) -> bool:
    return bool(user.can_manage_problems)


def _require_problem_manage(user: User) -> None:
    if not _can_manage(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="需要题目管理权限"
        )


async def _is_team_admin(db: AsyncSession, team_id: int, user: User) -> bool:
    """当前用户是否为该团队的团主/团队管理员。"""
    if user.is_super_admin:
        if not await is_team_organizing_shielded_contest(db, team_id, user):
            return True
    is_owner = (await db.execute(
        select(Team.id).where(Team.id == team_id, Team.owner_id == user.id)
    )).scalar_one_or_none()
    if is_owner is not None:
        return True
    return (await db.execute(
        select(TeamMember.id).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == user.id,
            TeamMember.role == "admin",
        )
    )).scalar_one_or_none() is not None


async def _is_problem_in_accessible_contest(
    db: AsyncSession, problem_id: int, user: User, contest_id: Optional[int] = None
) -> bool:
    """检查题目是否在用户有权访问的比赛中。"""
    now = datetime.now(timezone.utc)
    if contest_id is not None:
        c_prob = (await db.execute(
            select(ContestProblem.id).where(
                ContestProblem.contest_id == contest_id,
                ContestProblem.problem_id == problem_id,
            )
        )).first()
        if c_prob is not None:
            return True
    rows = (await db.execute(
        select(Contest.id, Contest.visibility, Contest.start_time, Contest.end_time)
        .join(ContestProblem, ContestProblem.contest_id == Contest.id)
        .where(ContestProblem.problem_id == problem_id)
    )).all()
    for cid, vis, st, en in rows:
        en_aware = _aware(en) if en else None
        st_aware = _aware(st) if st else None
        if en_aware and now >= en_aware and vis in ("public", "team_public"):
            return True
        if st_aware and en_aware and st_aware <= now <= en_aware:
            reg = (await db.execute(
                select(ContestParticipant.id).where(
                    ContestParticipant.contest_id == cid,
                    ContestParticipant.user_id == user.id,
                )
            )).first()
            if reg is not None:
                return True
    return False


async def _require_team_member_for_problem(
    db: AsyncSession, problem: Problem, user: User, contest_id: Optional[int] = None
) -> None:
    """团队题目访问与提交权：
    1. 非团队题或站方管理员直接放行；
    2. 团队公开题（is_public 为 True）直接放行；
    3. 团队成员 / 团队管理员直接放行；
    4. 题目属于当前比赛且用户有权访问（如进行中已报名 / 已结束公开赛）；
    其余非成员按不存在处理。
    """
    if problem.team_id is None or _can_manage(user):
        return
    if problem.is_public:
        return
    if await _is_team_admin(db, problem.team_id, user):
        return
    row = (await db.execute(
        select(TeamMember.id).where(
            TeamMember.team_id == problem.team_id,
            TeamMember.user_id == user.id)
    )).scalar_one_or_none()
    if row is not None:
        return
    if await _is_problem_in_accessible_contest(db, problem.id, user, contest_id=contest_id):
        return
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在"
    )


async def _require_manage_for_problem(
    db: AsyncSession, problem: Problem, user: User
) -> None:
    """题目管理权：主题库题要题目管理权限；团队题团队管理员亦可。

    非团队成员按不存在处理（404 防探测）；成员但非管理员 403。
    """
    shielded = await get_shielded_contest_for_problem(db, problem.id, user)
    if shielded is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该题属于未结束的比赛，比赛结束前非举办方不可管理此题目",
        )
    if problem.team_id is None:
        _require_problem_manage(user)
        return
    if _can_manage(user):
        return
    if await _is_team_admin(db, problem.team_id, user):
        return
    member = (await db.execute(
        select(TeamMember.id).where(
            TeamMember.team_id == problem.team_id,
            TeamMember.user_id == user.id)
    )).scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在"
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="需要团队管理权限"
    )


async def _require_testcase_manage(
    db: AsyncSession, problem: Problem, user: User
) -> None:
    """测试点管理权限：主题库题的出题人本人也可维护自己题目的测试数据；
    其余情况与题目管理权限一致（团队管理员 / 题目管理员）。
    """
    shielded = await get_shielded_contest_for_problem(db, problem.id, user)
    if shielded is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该题属于未结束的比赛，比赛结束前非举办方不可查看或管理测试点",
        )
    if problem.team_id is None:
        if _can_manage(user) or problem.author_id == user.id:
            return
        # 非作者按不存在处理，避免通过测试点接口探测题目
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在"
        )
    await _require_manage_for_problem(db, problem, user)


def _is_staff(user: User) -> bool:
    return bool(user.can_manage_users or user.is_admin or user.is_super_admin)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite 读回的是 naive datetime，统一按 UTC 处理。"""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _running_contest_for_problem(
    db: AsyncSession, problem_id: int
) -> Optional[Contest]:
    """该题目此刻是否正处在某场「进行中」的比赛里。

    比赛题目都取自题库，而题库里那些赛前写好的题解、AC 代码本身就是公开可见的。
    所以只要题目在比赛中，这段时间内的代码就按比赛规则收紧。
    一场以上比赛同时包含该题时取开始最早的那场。
    """
    now = datetime.now(timezone.utc)
    rows = (await db.execute(
        select(Contest)
        .join(ContestProblem, ContestProblem.contest_id == Contest.id)
        .where(ContestProblem.problem_id == problem_id)
        .order_by(Contest.start_time.asc())
    )).scalars().all()
    for c in rows:
        start, end = _aware(c.start_time), _aware(c.end_time)
        if start and end and start <= now <= end:
            return c
    return None


async def _unended_contests_for_problem(
    db: AsyncSession, problem_id: int
) -> list[Contest]:
    """该题目此刻所属、还没结束的全部比赛（含未开始的）。

    与 ``_running_contest_for_problem`` 的区别：这个连「未开始」也算，
    供普通提交通道的守卫用——比赛题在比赛结束前不该走普通通道
    拿真实测试数据调试（赛中还会绕过 OI 赛制的结果隐藏）。
    """
    now = datetime.now(timezone.utc)
    rows = (await db.execute(
        select(Contest)
        .join(ContestProblem, ContestProblem.contest_id == Contest.id)
        .where(ContestProblem.problem_id == problem_id)
        .order_by(Contest.start_time.asc())
    )).scalars().all()
    out: list[Contest] = []
    for c in rows:
        end = _aware(c.end_time)
        if end is not None and end >= now:
            out.append(c)
    return out


def _code_visible_to(
    sub: Submission,
    viewer: User,
    running: Optional[Contest],
    is_organizer: bool = False,
    is_teammate: bool = False,
) -> bool:
    """这条提交的代码能不能给 viewer 看。

    - 比赛进行中：本人及同队队友的代码只有属于这场比赛的提交才给看
    - 查看他人的代码：
      - 比赛进行中且开启了管理员保护（hide_submissions_from_admin）：
        - 仅举办方（is_organizer=True）可见全场代码；非举办方管理员亦不可见
      - 其余情况：
        - 站务管理员不受限
        - 普通选手不可见
    """
    # 比赛进行中：本人或同队队友的代码只有属于这场比赛的提交才给看
    if running is not None and (sub.user_id == viewer.id or is_teammate):
        return sub.contest_id == running.id

    # 查看他人的代码
    if sub.user_id != viewer.id and not is_teammate:
        if running is not None:
            if getattr(running, "hide_submissions_from_admin", False):
                return bool(is_organizer)
            return _is_staff(viewer)
        return _is_staff(viewer)

    # 查看自己的代码（非比赛期间）
    return True


def _code_hidden_reason(
    sub: Submission, viewer: User, running: Optional[Contest]
) -> Optional[str]:
    """代码被藏起来时给前端的说明，免得用户以为是 bug。"""
    if running is None:
        return None
    if sub.user_id == viewer.id:
        return "比赛进行中，赛前提交的代码暂不公开"
    return "比赛进行中，其他人的代码暂不公开"


def _apply_code_visibility(
    d: dict,
    sub: Submission,
    viewer: User,
    running: Optional[Contest],
    is_organizer: bool = False,
) -> dict:
    """把「给不给代码」和「为什么不给」写进响应体。"""
    visible = _code_visible_to(sub, viewer, running, is_organizer=is_organizer)
    d["code_visible"] = visible
    if visible:
        d["code"] = sub.code
    else:
        reason = _code_hidden_reason(sub, viewer, running)
        if reason:
            d["code_hidden_reason"] = reason
    return d


def _user_brief(user: User | None) -> dict:
    if user is None:
        return {
            "user_id": None,
            "username": "已删除用户",
            "user_number": None,
            "avatar_url": "",
            "is_admin": False,
        }
    return {
        "user_id": user.id,
        "username": user.username,
        "user_number": user.user_number,
        "avatar_url": user.avatar_url or "",
        "is_admin": bool(user.is_admin),
    }


def _dict(
    sub: Submission,
    *,
    problem: Optional[Problem] = None,
    with_code: bool = False,
) -> dict:
    d = {
        "id": sub.id,
        "problem_id": sub.problem_id,
        "contest_id": sub.contest_id,
        # 优先用题目真实编号（P 主题库 / U 用户题库 / T 团队题）
        "problem_number": (
            problem.problem_number if problem is not None
            else f"P{1000 + sub.problem_id}"
        ),
        "problem_title": problem.title if problem else None,
        "user": _user_brief(sub.user),
        "language": sub.language,
        "status": sub.status,
        "score": sub.score,
        "time_used": sub.time_used,
        "memory_used": sub.memory_used,
        "error_message": sub.error_message,
        "test_results": sub.test_results or [],
        "subtask_results": sub.subtask_results or [],
        "judged_at": sub.judged_at.isoformat() if sub.judged_at else None,
        "created_at": sub.created_at.isoformat() if sub.created_at else None,
    }
    if with_code:
        d["code"] = sub.code
    return d


async def _should_hide_oi_result(
    db: AsyncSession, sub: Submission, current_user: Optional[User],
) -> bool:
    """OI 赛制比赛进行中时，除举办方（或未开启保护时的管理员）外不可见评测结果。"""
    if not sub.contest_id:
        return False
    contest = (await db.execute(
        select(Contest).where(Contest.id == sub.contest_id)
    )).scalar_one_or_none()
    if contest is None:
        return False
    if (contest.rule_type or "xcpc") != "oi":
        return False

    now = datetime.now(timezone.utc)
    st = _aware(contest.start_time)
    en = _aware(contest.end_time)
    if not (st and en and st <= now <= en):
        return False

    if current_user:
        # 举办方（举办个人或举办团队全员）始终可见评测结果
        if await is_contest_organizer(db, contest, current_user):
            return False
        # 若未开启管理员保护，站务管理员可见
        if not getattr(contest, "hide_submissions_from_admin", False):
            if _can_manage(current_user) or current_user.is_admin or current_user.is_super_admin:
                return False

    return True


def _hide_result_fields(d: dict) -> None:
    """将评测结果字段置为隐藏态（OI 赛制赛中）。"""
    d["status"] = "submitted"
    d["score"] = 0
    d["time_used"] = None
    d["memory_used"] = None
    d["error_message"] = None
    d["test_results"] = []
    d["subtask_results"] = []
    d["judged_at"] = None


async def _load_submission(db: AsyncSession, submission_id: int) -> Optional[Submission]:
    result = await db.execute(
        select(Submission).options(selectinload(Submission.user)).where(
            Submission.id == submission_id)
    )
    return result.scalar_one_or_none()


async def _load_problem(db: AsyncSession, problem_id: int) -> Optional[Problem]:
    return (await db.execute(
        select(Problem).where(Problem.id == problem_id)
    )).scalar_one_or_none()


@router.post("/problems/{problem_id}/submissions", summary="提交代码")
async def create_submission(
    problem_id: int,
    payload: SubmissionCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    problem = await _load_problem(db, problem_id)
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")
    contest_id = payload.contest_id
    if problem.team_id is None:
        # 主题库题：提交权限与查看权限一致——
        # 已审核公开题所有人可提交；未审核题仅出题人本人/题目管理员可提交
        if not (problem.is_public and problem.review_status == REVIEW_APPROVED) \
                and not _can_manage(current_user) \
                and problem.author_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在"
            )
    elif not problem.is_public and not _can_manage(current_user) and contest_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")
    # 团队私有题仅成员可提交（公开题或比赛内提交直接放行）
    await _require_team_member_for_problem(db, problem, current_user, contest_id=contest_id)

    # 比赛内提交：进行中 + 已报名 + 题目属于该比赛
    virtual = None
    # 写库用的 contest_id：虚拟参赛时置空（不想就地改写 contest_id，
    # 后面的「比赛题守卫」还要用它判断题目归属）
    stored_contest_id = contest_id
    # 虚拟参赛没有 ContestParticipant（不报名原比赛），后面用到时保持 None
    participant = None
    if contest_id is not None:
        contest = (await db.execute(
            select(Contest).where(Contest.id == contest_id)
        )).scalar_one_or_none()
        if contest is None:
            raise HTTPException(status_code=404, detail="比赛不存在")

        # 虚拟参赛：源比赛早已结束，但用户自己那一份还在计时。这时不走
        # 「比赛已结束 / 请先报名」那套真实比赛的校验，改成按虚拟赛时间窗判断，
        # 并且**把 contest_id 置空**、只留 virtual_contest_id —— 原赛榜、等级分、
        # 查重扫描全都只认 contest_id，这样虚拟成绩天然不会污染真实成绩。
        virtual = await virtual_service.get_active_virtual(
            db, current_user.id, contest_id)
        if virtual is not None:
            # 防御纵深：直接复用开局校验（公开 + 非组队），别只判 visibility
            startable, why = virtual_service.validate_startable(contest)
            if not startable:
                raise HTTPException(status_code=403, detail=why)
            in_contest = (await db.execute(
                select(ContestProblem.id).where(
                    ContestProblem.contest_id == contest_id,
                    ContestProblem.problem_id == problem_id)
            )).scalar_one_or_none()
            if in_contest is None:
                raise HTTPException(status_code=400, detail="该题目不属于这场比赛")
            # 只改「写库用」的那个变量，contest_id 保持原样给后面的守卫用
            stored_contest_id = None
        else:
            now = datetime.now(timezone.utc)
            st_ = contest.start_time
            en = contest.end_time
            # SQLite 读回 naive datetime，统一按 UTC 处理
            if st_.tzinfo is None:
                st_ = st_.replace(tzinfo=timezone.utc)
            if en.tzinfo is None:
                en = en.replace(tzinfo=timezone.utc)
            if now < st_:
                raise HTTPException(status_code=400, detail="比赛尚未开始")
            if now > en:
                raise HTTPException(status_code=400, detail="比赛已结束，不计成绩")
            participant = (await db.execute(
                select(ContestParticipant).where(
                    ContestParticipant.contest_id == contest_id,
                    ContestParticipant.user_id == current_user.id)
            )).scalar_one_or_none()
            if participant is None:
                raise HTTPException(status_code=403, detail="请先报名比赛再提交")
            if getattr(contest, "is_team_contest", False) and participant.team_id is None:
                raise HTTPException(status_code=403, detail="本场为组队赛，请先创建或加入队伍后再提交")
            in_contest = (await db.execute(
                select(ContestProblem.id).where(
                    ContestProblem.contest_id == contest_id,
                    ContestProblem.problem_id == problem_id)
            )).scalar_one_or_none()
            if in_contest is None:
                raise HTTPException(status_code=400, detail="该题目不属于这场比赛")

    # 比赛题守卫：题目挂在未结束的比赛里时，普通提交通道关闭——
    # 否则赛前赛中都能拿真实测试数据反复调试（逐点结果/分数全可见），
    # OI 赛制「赛中隐藏结果」也会被这条 contest_id=None 的通道绕过。
    # 出题人 / 题目管理员 / 比赛创建者豁免（他们本来就能看到测试数据）。
    if contest_id is None:
        unended = await _unended_contests_for_problem(db, problem_id)
        # 受到管理员参赛保护的比赛，非举办方管理员不得豁免题库提交通道
        is_shielded = False
        for c in unended:
            if getattr(c, "hide_submissions_from_admin", False) and not await is_contest_organizer(db, c, current_user):
                is_shielded = True
                break
        exempt = not is_shielded and (
            _can_manage(current_user)
            or (problem.author_id is not None
                and problem.author_id == current_user.id)
            or any(c.owner_id == current_user.id for c in unended)
        )
        if unended and not exempt:
            now = datetime.now(timezone.utc)
            running = False
            for c in unended:
                st, en = _aware(c.start_time), _aware(c.end_time)
                if st and en and st <= now <= en:
                    running = True
                    break
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=("该题正在进行比赛，请从比赛页面提交"
                        if running else "该题为比赛题目，比赛开始后才能提交"),
            )

    if current_user.is_banned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="被封禁用户不能提交评测"
        )

    case_count = (await db.execute(
        select(sa_func.count()).select_from(TestCase).where(
            TestCase.problem_id == problem_id)
    )).scalar() or 0
    if case_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该题目暂无测试数据，无法提交评测",
        )

    # 5 分钟内最多 6 次提交
    ok, wait = check(f"submit:{current_user.user_number}", 6, 300)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"提交太频繁，请 {wait} 秒后再试",
        )

    team_id_val = None
    if contest_id and participant and getattr(contest, "is_team_contest", False):
        team_id_val = participant.team_id

    # 虚拟赛在这期间的极窄竞态（读到活动行 → 插入前刚好到期/被结束）：
    # 提交落库前再确认一次，避免打上「已经结束的那一轮」的标记
    if virtual is not None and virtual_service.is_finished(virtual):
        raise HTTPException(status_code=400, detail="虚拟参赛已结束，请重新开始")

    sub = Submission(
        problem_id=problem_id,
        user_id=current_user.id,
        code=payload.code,
        language=payload.language,
        status="pending",
        # 虚拟参赛走 stored_contest_id=None，只留 virtual_contest_id
        contest_id=stored_contest_id,
        contest_team_id=team_id_val,
        virtual_contest_id=virtual.id if virtual is not None else None,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)

    # 响应返回后后台评测
    background_tasks.add_task(judge_submission, sub.id)
    return _dict(sub, problem=problem, with_code=True)


@router.get("/problems/{problem_id}/submissions", summary="题目的提交记录")
async def list_problem_submissions(
    problem_id: int,
    page: int = Query(0, ge=0),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    # 与题面同口径的可见性校验：之前这里只查登录，遍历 problem_id 就能列出
    # 未公开题的标题/提交动态，比赛题的赛前赛中普通提交也全裸在这（分数、逐点结果）
    problem = await _load_problem(db, problem_id)
    if problem is None or (
        problem.team_id is None
        and not _can_view_main_problem(problem, current_user)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在"
        )
    # 团队私有题仅成员可见/可提交
    await _require_team_member_for_problem(db, problem, current_user)
    # 比赛守卫：未结束的比赛题，未报名/未开赛一律 403（与题面一条规则）
    await _resolve_contest_problem_access(db, problem, current_user)

    running = await _running_contest_for_problem(db, problem_id)
    is_organizer = False
    shield_active = False
    if running is not None and getattr(running, "hide_submissions_from_admin", False):
        shield_active = True
        is_organizer = await is_contest_organizer(db, running, current_user)

    base = select(Submission).options(selectinload(Submission.user)).where(
        Submission.problem_id == problem_id)

    # 比赛期间开启管理员保护：非举办方（普通用户及非举办方管理员）仅能看到自己的提交记录
    if shield_active and not is_organizer:
        base = base.where(Submission.user_id == current_user.id)

    total = (await db.execute(
        select(sa_func.count()).select_from(base.subquery())
    )).scalar() or 0
    rows = (await db.execute(
        base.offset(page * page_size).limit(page_size)
        .order_by(Submission.id.desc())
    )).scalars().all()

    items = []
    for sub in rows:
        d = _dict(sub, problem=problem)
        d = _apply_code_visibility(d, sub, current_user, running, is_organizer=is_organizer)
        if await _should_hide_oi_result(db, sub, current_user):
            _hide_result_fields(d)
        items.append(d)
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.post(
    "/problems/{problem_id}/submissions/rejudge",
    summary="批量重测题目提交",
)
async def rejudge_problem_submissions(
    problem_id: int,
    background_tasks: BackgroundTasks,
    payload: SubmissionRejudgeRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    problem = await _load_problem(db, problem_id)
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")
    running = await _running_contest_for_problem(db, problem_id)
    if running is not None and getattr(running, "hide_submissions_from_admin", False):
        if not await is_contest_organizer(db, running, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="比赛进行中，非举办方无法重测提交",
            )
    await _require_manage_for_problem(db, problem, current_user)

    sc = payload.score if payload else None
    query = select(Submission).where(Submission.problem_id == problem_id)
    if sc is not None:
        query = query.where(Submission.score == sc)
    rows = (await db.execute(query.order_by(Submission.id.asc()))).scalars().all()
    queued = [
        sub for sub in rows
        if sub.status not in ("pending", "judging")
    ]
    for sub in queued:
        sub.status = "pending"
        sub.score = 0
        sub.time_used = None
        sub.memory_used = None
        sub.error_message = None
        sub.test_results = None
        sub.judged_at = None
    await db.commit()

    if queued:
        background_tasks.add_task(
            judge_submissions,
            [sub.id for sub in queued],
            is_rejudge=True,
        )
    return {
        "queued": len(queued),
        "skipped": len(rows) - len(queued),
        "score": sc,
    }


@router.post(
    "/problems/{problem_id}/submissions/cancel-score",
    summary="批量取消题目提交成绩",
)
async def cancel_problem_submissions_score(
    problem_id: int,
    payload: SubmissionCancelScoreRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    problem = await _load_problem(db, problem_id)
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")
    running = await _running_contest_for_problem(db, problem_id)
    if running is not None and getattr(running, "hide_submissions_from_admin", False):
        if not await is_contest_organizer(db, running, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="比赛进行中，非举办方无法修改提交成绩",
            )
    await _require_manage_for_problem(db, problem, current_user)

    sc = payload.score if payload else None
    query = select(Submission).where(Submission.problem_id == problem_id)
    if sc is not None:
        query = query.where(Submission.score == sc)
    rows = (await db.execute(query.order_by(Submission.id.asc()))).scalars().all()

    queued = [
        sub for sub in rows
        if sub.status not in ("pending", "judging", "cancelled")
    ]
    cancelled_ids = [sub.id for sub in queued]
    ac_user_ids = list({sub.user_id for sub in queued if sub.status == "accepted"})

    for sub in queued:
        sub.status = "cancelled"
        sub.score = 0
        sub.time_used = None
        sub.memory_used = None
        sub.error_message = None
        sub.test_results = None
        sub.subtask_results = None
        sub.judged_at = None

    if queued:
        problem.submit_count = max(0, (problem.submit_count or 0) - len(queued))
        for uid in ac_user_ids:
            remaining_ac = (await db.execute(
                select(Submission.id).where(
                    Submission.problem_id == problem_id,
                    Submission.user_id == uid,
                    Submission.status == "accepted",
                    Submission.id.not_in(cancelled_ids),
                ).limit(1)
            )).scalar_one_or_none()
            if remaining_ac is None:
                problem.solved_count = max(0, (problem.solved_count or 0) - 1)
                if problem.team_id is None:
                    xp = XP_BY_DIFFICULTY.get(problem.difficulty, 0)
                    if xp > 0:
                        ac_user = await db.get(User, uid)
                        if ac_user is not None:
                            ac_user.experience = max(0, (ac_user.experience or 0) - xp)
                            logger.info("取消成绩：用户 %s P%s(%s) 最后一次 AC 被取消，-%d 经验",
                                        ac_user.username, 1000 + problem_id,
                                        problem.difficulty, xp)

    await db.commit()
    return {
        "cancelled": len(queued),
        "skipped": len(rows) - len(queued),
        "score": sc,
    }


@router.get(
    "/problems/{problem_id}/my-last-submission",
    summary="我在该题的最后一次提交（含代码）",
)
async def get_my_last_submission(
    problem_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Optional[dict]:
    """提交页回填用：返回当前用户在该题最近一次提交（含 code）。

    从未提交过时返回 ``null``（前端据此显示默认代码模板）。
    """
    problem = await _load_problem(db, problem_id)
    if problem is None or (
        not problem.is_public and not _can_manage(current_user)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")
    # 团队私有题仅成员可见/可提交
    await _require_team_member_for_problem(db, problem, current_user)

    sub = (await db.execute(
        select(Submission)
        .where(
            Submission.problem_id == problem_id,
            Submission.user_id == current_user.id,
        )
        .order_by(Submission.id.desc())
        .limit(1)
    )).scalar_one_or_none()
    if sub is None:
        return None
    # 比赛进行中不要用赛前的提交回填编辑器 ——
    # 那等于把选手赛前写好的题解直接送到他眼前。返回 null 让前端用默认模板。
    running = await _running_contest_for_problem(db, problem_id)
    is_organizer = await is_contest_organizer(db, running, current_user) if running else False
    if not _code_visible_to(sub, current_user, running, is_organizer=is_organizer):
        return None
    return _dict(sub, problem=problem, with_code=True)


@router.get("/submissions/mine", summary="我的提交记录")
async def list_my_submissions(
    problem_id: Optional[int] = Query(None),
    page: int = Query(0, ge=0),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    base = select(Submission).options(selectinload(Submission.user)).where(
        Submission.user_id == current_user.id)
    if problem_id:
        base = base.where(Submission.problem_id == problem_id)
    total = (await db.execute(
        select(sa_func.count()).select_from(base.subquery())
    )).scalar() or 0
    rows = (await db.execute(
        base.offset(page * page_size).limit(page_size)
        .order_by(Submission.id.desc())
    )).scalars().all()

    items = []
    for sub in rows:
        problem = await _load_problem(db, sub.problem_id)
        d = _dict(sub, problem=problem, with_code=False)
        if await _should_hide_oi_result(db, sub, current_user):
            _hide_result_fields(d)
        items.append(d)
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/submissions/{submission_id}", summary="提交详情")
async def get_submission(
    submission_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    sub = await _load_submission(db, submission_id)
    if sub is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提交不存在")
    problem = await _load_problem(db, sub.problem_id)
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")

    running = await _running_contest_for_problem(db, sub.problem_id)
    # 也检查 sub.contest_id 是否属于某个正在进行的比赛
    if sub.contest_id and (running is None or running.id != sub.contest_id):
        c_sub = (await db.execute(
            select(Contest).where(Contest.id == sub.contest_id)
        )).scalar_one_or_none()
        if c_sub:
            now = datetime.now(timezone.utc)
            st, en = _aware(c_sub.start_time), _aware(c_sub.end_time)
            if st and en and st <= now <= en:
                running = c_sub

    is_organizer = False
    shield_active = False
    if running is not None and getattr(running, "hide_submissions_from_admin", False):
        shield_active = True
        is_organizer = await is_contest_organizer(db, running, current_user)

    is_teammate = False
    if sub.contest_id and sub.contest_team_id and current_user:
        part = (await db.execute(
            select(ContestParticipant.id).where(
                ContestParticipant.contest_id == sub.contest_id,
                ContestParticipant.user_id == current_user.id,
                ContestParticipant.team_id == sub.contest_team_id,
            )
        )).scalar_one_or_none()
        is_teammate = (part is not None)

    # 比赛期间开启管理员保护：非举办方无法查看他人的提交详情
    if shield_active and not is_organizer and not is_teammate and sub.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="比赛进行中，无法查看其他选手的提交详情",
        )

    if not problem.is_public and not _can_manage(current_user) and not is_teammate and sub.user_id != current_user.id:
        if not is_organizer:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提交不存在")

    code_visible = _code_visible_to(
        sub, current_user, running, is_organizer=is_organizer, is_teammate=is_teammate
    )
    d = _dict(sub, problem=problem, with_code=code_visible)
    d["code_visible"] = code_visible
    if not code_visible:
        reason = _code_hidden_reason(sub, current_user, running)
        if reason:
            d["code_hidden_reason"] = reason
    # OI 赛制比赛进行中时，非管理员/非举办方不可见评测结果
    if await _should_hide_oi_result(db, sub, current_user):
        _hide_result_fields(d)
        d["result_hidden"] = True
    else:
        d["result_hidden"] = False
    return d


# ==================== 单条提交管理：重测 / 取消成绩 ====================

@router.post(
    "/submissions/{submission_id}/rejudge",
    summary="重测单条提交",
)
async def rejudge_submission(
    submission_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    sub = await _load_submission(db, submission_id)
    if sub is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提交不存在")
    problem = await _load_problem(db, sub.problem_id)
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")
    running = await _running_contest_for_problem(db, problem.id)
    if running is not None and getattr(running, "hide_submissions_from_admin", False):
        if not await is_contest_organizer(db, running, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="比赛进行中，非举办方无法重测提交",
            )
    await _require_manage_for_problem(db, problem, current_user)

    if sub.status in ("pending", "judging"):
        return {"queued": 0, "skipped": 1}

    sub.status = "pending"
    sub.score = 0
    sub.time_used = None
    sub.memory_used = None
    sub.error_message = None
    sub.test_results = None
    sub.subtask_results = None
    sub.judged_at = None
    await db.commit()

    background_tasks.add_task(judge_submission, sub.id, is_rejudge=True)
    return {"queued": 1, "skipped": 0}


@router.post(
    "/submissions/{submission_id}/cancel-score",
    summary="取消单条提交成绩",
)
async def cancel_submission_score(
    submission_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    sub = await _load_submission(db, submission_id)
    if sub is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提交不存在")
    problem = await _load_problem(db, sub.problem_id)
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")
    running = await _running_contest_for_problem(db, problem.id)
    if running is not None and getattr(running, "hide_submissions_from_admin", False):
        if not await is_contest_organizer(db, running, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="比赛进行中，非举办方无法修改提交成绩",
            )
    await _require_manage_for_problem(db, problem, current_user)

    if sub.status in ("pending", "judging", "cancelled"):
        return {"cancelled": 0, "skipped": 1}

    was_accepted = sub.status == "accepted"
    sub.status = "cancelled"
    sub.score = 0
    sub.time_used = None
    sub.memory_used = None
    sub.error_message = None
    sub.test_results = None
    sub.subtask_results = None
    sub.judged_at = None

    # 回滚统计：提交数 -1；若是该用户此题最后一次 AC，通过数 -1 并扣回经验
    problem.submit_count = max(0, (problem.submit_count or 0) - 1)
    if was_accepted:
        remaining_ac = (await db.execute(
            select(Submission.id).where(
                Submission.problem_id == sub.problem_id,
                Submission.user_id == sub.user_id,
                Submission.status == "accepted",
                Submission.id != sub.id,
            ).limit(1)
        )).scalar_one_or_none()
        if remaining_ac is None:
            problem.solved_count = max(0, (problem.solved_count or 0) - 1)
            if problem.team_id is None:
                xp = XP_BY_DIFFICULTY.get(problem.difficulty, 0)
                if xp > 0:
                    ac_user = await db.get(User, sub.user_id)
                    if ac_user is not None:
                        ac_user.experience = max(0, (ac_user.experience or 0) - xp)
                        logger.info("取消成绩：用户 %s P%s(%s) 最后一次 AC 被取消，-%d 经验",
                                    ac_user.username, 1000 + sub.problem_id,
                                    problem.difficulty, xp)

    await db.commit()
    return {"cancelled": 1, "skipped": 0}


# ==================== 测试点管理（题目管理权限） ====================

@router.get("/problems/{problem_id}/test-cases", summary="测试点列表")
async def list_test_cases(
    problem_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    problem = await _load_problem(db, problem_id)
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")
    await _require_testcase_manage(db, problem, current_user)
    rows = (await db.execute(
        select(TestCase).where(TestCase.problem_id == problem_id)
        .order_by(TestCase.sort_order.asc(), TestCase.id.asc())
    )).scalars().all()
    res = []
    for tc in rows:
        in_data = tc.input_data or ""
        out_data = tc.expected_output or ""
        in_len = len(in_data.encode("utf-8"))
        out_len = len(out_data.encode("utf-8"))
        # 列表接口提供轻量预览（前 300 字符），避免几十 MB 测试数据拖垮浏览器/导致请求超时被误判为无数据
        in_preview = in_data if len(in_data) <= 300 else in_data[:300] + f"\n... (共 {len(in_data)} 字符)"
        out_preview = out_data if len(out_data) <= 300 else out_data[:300] + f"\n... (共 {len(out_data)} 字符)"
        res.append({
            "id": tc.id,
            "input_data": in_preview,
            "expected_output": out_preview,
            "input_preview": in_preview,
            "expected_output_preview": out_preview,
            "input_size": in_len,
            "expected_output_size": out_len,
            "sort_order": tc.sort_order,
            "subtask_id": tc.subtask_id,
            "subtask_score": tc.subtask_score,
        })
    return res


@router.get("/problems/{problem_id}/test-cases/{case_id}", summary="单个测试点详情")
async def get_test_case(
    problem_id: int,
    case_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    problem = await _load_problem(db, problem_id)
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")
    await _require_testcase_manage(db, problem, current_user)
    tc = (await db.execute(
        select(TestCase).where(
            TestCase.id == case_id, TestCase.problem_id == problem_id)
    )).scalar_one_or_none()
    if tc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试点不存在")
    in_data = tc.input_data or ""
    out_data = tc.expected_output or ""
    return {
        "id": tc.id,
        "input_data": in_data,
        "expected_output": out_data,
        "input_size": len(in_data.encode("utf-8")),
        "expected_output_size": len(out_data.encode("utf-8")),
        "sort_order": tc.sort_order,
        "subtask_id": tc.subtask_id,
        "subtask_score": tc.subtask_score,
    }


@router.post("/problems/{problem_id}/test-cases", summary="新增测试点")
async def create_test_case(
    problem_id: int,
    payload: TestCaseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    problem = await _load_problem(db, problem_id)
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")
    await _require_testcase_manage(db, problem, current_user)
    count = (await db.execute(
        select(sa_func.count()).select_from(TestCase).where(
            TestCase.problem_id == problem_id)
    )).scalar() or 0
    if count >= 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="测试点最多 100 个"
        )
    max_order = (await db.execute(
        select(sa_func.max(TestCase.sort_order)).where(TestCase.problem_id == problem_id)
    )).scalar()
    next_order = 0 if max_order is None else max_order + 1
    tc = TestCase(
        problem_id=problem_id,
        input_data=payload.input_data,
        expected_output=payload.expected_output,
        subtask_id=payload.subtask_id,
        subtask_score=payload.subtask_score,
        sort_order=next_order,
    )
    db.add(tc)
    await db.commit()
    await db.refresh(tc)
    return {
        "id": tc.id,
        "input_data": tc.input_data,
        "expected_output": tc.expected_output,
        "sort_order": tc.sort_order,
        "subtask_id": tc.subtask_id,
        "subtask_score": tc.subtask_score,
    }


@router.patch("/problems/{problem_id}/test-cases/{case_id}", summary="修改单个测试点")
async def update_test_case(
    problem_id: int,
    case_id: int,
    payload: TestCaseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    problem = await _load_problem(db, problem_id)
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")
    await _require_testcase_manage(db, problem, current_user)
    tc = (await db.execute(
        select(TestCase).where(
            TestCase.id == case_id, TestCase.problem_id == problem_id)
    )).scalar_one_or_none()
    if tc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试点不存在")

    if payload.input_data is not None:
        tc.input_data = payload.input_data
    if payload.expected_output is not None:
        tc.expected_output = payload.expected_output
    if payload.subtask_id is not None:
        tc.subtask_id = payload.subtask_id
    if payload.subtask_score is not None:
        tc.subtask_score = payload.subtask_score
    if payload.sort_order is not None:
        tc.sort_order = payload.sort_order
    await db.commit()
    await db.refresh(tc)
    return {
        "id": tc.id,
        "input_data": tc.input_data,
        "expected_output": tc.expected_output,
        "sort_order": tc.sort_order,
        "subtask_id": tc.subtask_id,
        "subtask_score": tc.subtask_score,
    }


@router.put("/problems/{problem_id}/subtasks", summary="更新题目子任务配置及测试点归属")
async def update_problem_subtasks(
    problem_id: int,
    payload: ProblemSubtasksUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    problem = await _load_problem(db, problem_id)
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")
    await _require_testcase_manage(db, problem, current_user)

    cfg_list = [item.model_dump() for item in payload.subtask_config]
    problem.subtask_config = cfg_list

    if payload.case_subtasks:
        for cid_str, st_id in payload.case_subtasks.items():
            cid = int(cid_str)
            tc = (await db.execute(
                select(TestCase).where(
                    TestCase.id == cid, TestCase.problem_id == problem_id)
            )).scalar_one_or_none()
            if tc:
                tc.subtask_id = st_id

    await db.commit()
    return {"success": True, "subtask_config": problem.subtask_config}


@router.delete("/problems/{problem_id}/test-cases/{case_id}", summary="删除测试点")
async def delete_test_case(
    problem_id: int,
    case_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    problem = await _load_problem(db, problem_id)
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")
    await _require_testcase_manage(db, problem, current_user)
    tc = (await db.execute(
        select(TestCase).where(
            TestCase.id == case_id, TestCase.problem_id == problem_id)
    )).scalar_one_or_none()
    if tc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试点不存在")
    await db.delete(tc)
    await db.commit()
    return {"success": True}


@router.post("/problems/{problem_id}/test-cases/batch-delete", summary="批量删除测试点")
async def batch_delete_test_cases(
    problem_id: int,
    payload: TestCaseBatchDeleteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    problem = await _load_problem(db, problem_id)
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")
    await _require_testcase_manage(db, problem, current_user)
    if not payload.case_ids:
        return {"success": True, "deleted_count": 0}
    res = await db.execute(
        delete(TestCase).where(
            TestCase.problem_id == problem_id,
            TestCase.id.in_(payload.case_ids),
        )
    )
    await db.commit()
    return {"success": True, "deleted_count": res.rowcount or 0}


@router.delete("/problems/{problem_id}/test-cases", summary="清空测试点")
async def clear_test_cases(
    problem_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    problem = await _load_problem(db, problem_id)
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")
    await _require_testcase_manage(db, problem, current_user)
    res = await db.execute(delete(TestCase).where(TestCase.problem_id == problem_id))
    await db.commit()
    return {"success": True, "deleted_count": res.rowcount or 0}


_ZIP_MAX_UPLOAD = 50 * 1024 * 1024
_ZIP_MAX_TOTAL = 100 * 1024 * 1024
_NAME_RE = re.compile(r"^([^0-9]*)([0-9]+)$")


from app.services.problem_zip import parse_zip_case_entry as _parse_zip_case_entry


@router.post("/problems/{problem_id}/test-cases/upload-zip",
             summary="上传 zip 压缩包批量导入测试点（.in/.out 成对）")
async def upload_test_cases_zip(
    problem_id: int,
    file: UploadFile = File(...),
    clear_existing: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    import io
    import zipfile as zf
    problem = await _load_problem(db, problem_id)
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")
    await _require_testcase_manage(db, problem, current_user)
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="仅支持 zip 压缩包")
    content = await file.read()
    if len(content) > _ZIP_MAX_UPLOAD:
        raise HTTPException(status_code=400, detail="压缩包大小不能超过 50MB")
    try:
        archive = zf.ZipFile(io.BytesIO(content))
    except zf.BadZipFile:
        raise HTTPException(status_code=400, detail="无法解析压缩包，请使用 zip")
    infos = archive.infolist()
    if sum(i.file_size for i in infos) > _ZIP_MAX_TOTAL:
        raise HTTPException(status_code=400, detail="解压后总大小不能超过 100MB")

    entries: dict[tuple, dict[str, str]] = {}
    display_names: dict[tuple, str] = {}
    entry_subtasks: dict[tuple, Optional[int]] = {}

    for info in infos:
        parsed = _parse_zip_case_entry(info.filename)
        if parsed is None:
            continue
        subtask_id, sort_key, ext, disp_name = parsed
        key = (subtask_id, sort_key)
        try:
            data = archive.read(info).decode("utf-8", errors="replace")
        except Exception:
            raise HTTPException(status_code=400, detail=f"文件 {info.filename} 无法读取")
        entries.setdefault(key, {})[ext] = data
        display_names[key] = disp_name
        entry_subtasks[key] = subtask_id

    unpaired = [f"{display_names[k]}.in/.out" for k, v in entries.items()
                if "in" not in v or "out" not in v]
    if unpaired:
        raise HTTPException(
            status_code=400, detail="以下测试点缺少配对的输入/输出文件: " + ", ".join(unpaired[:5])
        )
    if not entries:
        raise HTTPException(status_code=400, detail="压缩包内没有有效测试点（需成对包含形如 1.in/1.out 或 data1.in/data1.ans）")

    if clear_existing:
        await db.execute(delete(TestCase).where(TestCase.problem_id == problem_id))
        await db.commit()
        existing_count = 0
        base_order = 0
    else:
        existing_count = (await db.execute(
            select(sa_func.count()).select_from(TestCase).where(
                TestCase.problem_id == problem_id)
        )).scalar() or 0
        max_order = (await db.execute(
            select(sa_func.max(TestCase.sort_order)).where(TestCase.problem_id == problem_id)
        )).scalar()
        base_order = 0 if max_order is None else max_order + 1

    if existing_count + len(entries) > 100:
        raise HTTPException(
            status_code=400,
            detail=f"测试点最多 100 个（现有 {existing_count} 个，本次尝试导入 {len(entries)} 个）",
        )

    keys = sorted(entries.keys(), key=lambda k: k[1])
    created = []
    detected_subtask_ids = set()
    for offset, key in enumerate(keys):
        st_id = entry_subtasks.get(key)
        if st_id is not None:
            detected_subtask_ids.add(st_id)
        tc = TestCase(
            problem_id=problem_id,
            input_data=entries[key]["in"],
            expected_output=entries[key]["out"],
            subtask_id=st_id,
            sort_order=base_order + offset,
        )
        db.add(tc)
        created.append(tc)

    # 自动识别并初始化题目子任务分值（若此前未配置）
    if detected_subtask_ids and not problem.subtask_config:
        st_list = sorted(list(detected_subtask_ids))
        n_st = len(st_list)
        each_sc = 100 // n_st
        auto_cfg = []
        for idx, sid in enumerate(st_list):
            sc = 100 - each_sc * (n_st - 1) if idx == n_st - 1 else each_sc
            auto_cfg.append({"id": sid, "score": sc, "name": f"Subtask #{sid}"})
        problem.subtask_config = auto_cfg

    await db.commit()
    return {
        "success": True,
        "imported": len(created),
        "detected_subtasks": sorted(list(detected_subtask_ids)),
        "subtask_config": problem.subtask_config,
    }

