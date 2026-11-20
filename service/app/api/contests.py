"""比赛 API（ACM 赛制 MVP）。

- 状态：pending 未开始 / running 进行中 / ended 已结束（按当前时间判定）
- 报名：未开始或进行中均可报名；已结束不可
- 提交：进行中且已报名才计成绩（走 submissions 的 contest_id 挂钩）
- 排名：ACM 规则——通过题数 desc → 罚时 asc（每题首次 AC 分钟数
  + 该题错误提交次数 × 20）
- 创建/删除：题目管理权限或站内管理员
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import secrets
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func as sa_func, select, update, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app import permissions as perm
from app.core.database import get_db
from app.deps import get_current_user, get_current_user_optional
from app.models.contest import Contest, ContestParticipant, ContestProblem, ContestTeam
from app.models.problem import Problem, REVIEW_APPROVED
from app.models.submission import Submission
from app.models.team import Team, TeamMember
from app.models.user import User
from app import permissions as perm
from app.services.contest import is_contest_organizer
from app.services import contest_rank as contest_rank_service
from app.services import contest_rating as rating_service
from app.services.contest_rank import ALIAS, RULE_LABELS, _aware, _user_rank_dict
from sqlalchemy.exc import IntegrityError
from app.services import virtual_contest as virtual_service
from app.services.problem import ProblemService

router = APIRouter(prefix="/contests", tags=["contests"])


# visibility → 展示名；团队赛支持 team_public / team / team_private
VISIBILITY_LABELS = {
    ("public", False): "公开赛",
    ("private", False): "邀请赛",
    ("public", True): "团队公开赛",
    ("team_public", True): "团队公开赛",
    ("team", True): "团队内部赛",
    ("team_private", True): "团队邀请赛",
}

def _can_manage_contest(user: User) -> bool:
    """建赛/改赛权限 =「管理名单 → 题目管理」列（与 problems 里同口径）。

    泛管理员 `is_admin` 不再算：它没有被名单公示在题目管理列里。
    """
    return perm.can_manage_problems(user)


async def _is_team_admin(db: AsyncSession, team_id: int, user: User) -> bool:
    """当前用户是否为该团队的团主/团队管理员。"""
    if user.is_super_admin:
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


async def _is_team_member(db: AsyncSession, team_id: int, user: User) -> bool:
    """当前用户是否为团队成员（含团主与管理员）。"""
    if user.is_super_admin or await _is_team_admin(db, team_id, user):
        return True
    return (await db.execute(
        select(TeamMember.id).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == user.id,
        )
    )).scalar_one_or_none() is not None


async def _can_edit_contest(db: AsyncSession, contest: Contest, user: User) -> bool:
    """当前用户是否有权编辑/删除该比赛。"""
    if user.is_super_admin or _can_manage_contest(user):
        return True
    if contest.owner_id == user.id:
        return True
    if contest.team_id is not None and await _is_team_admin(db, contest.team_id, user):
        return True
    return False


def _type_label(visibility: str, has_team: bool) -> str:
    if has_team:
        if visibility == "team":
            return "团队内部赛"
        if visibility == "team_private":
            return "团队邀请赛"
        return "团队公开赛"
    return "邀请赛" if visibility == "private" else "公开赛"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _status(contest: Contest) -> str:
    now = _utcnow()
    if now < _aware(contest.start_time):
        return "pending"
    if now > _aware(contest.end_time):
        return "ended"
    return "running"


def _contest_dict(
    contest: Contest, current_user: User | None, *,
    with_problems: bool = False, show_hidden_problems: bool = False,
    can_view_problems: bool | None = None,
    can_edit: bool | None = None,
) -> dict[str, Any]:
    visibility = getattr(contest, "visibility", "public") or "public"
    has_team = contest.team_id is not None
    is_owner = bool(current_user and contest.owner_id == current_user.id)
    can_manage = bool(current_user and _can_manage_contest(current_user))
    can_edit_flag = can_edit if can_edit is not None else bool(is_owner or can_manage)
    d: dict[str, Any] = {
        "id": contest.id,
        "title": contest.title,
        "description": contest.description or "",
        "visibility": visibility,
        "type_label": _type_label(visibility, has_team),
        "team_id": contest.team_id,
        # team relationship 已随查询加载（lazy joined）
        "team_name": (contest.team.name if has_team and contest.team else None),
        # 赛制：xcpc / ioi / oi
        "rule_type": "xcpc" if (getattr(contest, "rule_type", "xcpc") or "xcpc") == "acm" else (getattr(contest, "rule_type", "xcpc") or "xcpc"),
        "rule_type_label": RULE_LABELS.get(getattr(contest, "rule_type", "xcpc") or "xcpc", "XCPC 赛制"),
        # 是否为组队赛及每队上限
        "is_team_contest": bool(getattr(contest, "is_team_contest", False)),
        "max_team_members": int(getattr(contest, "max_team_members", 3) or 3),
        "team_count": len(getattr(contest, "teams", []) or []),
        # 一律带上 UTC 偏移量再下发。Postgres 的 timestamptz 读回来本来就是 aware，
        # 但 SQLite 会丢时区，isoformat() 出来的串没有后缀，前端 new Date() 会当成
        # 本地时间解析 —— 开发环境和线上表现就不一致了。
        "start_time": _aware(contest.start_time).isoformat() if contest.start_time else None,
        "end_time": _aware(contest.end_time).isoformat() if contest.end_time else None,
        "status": _status(contest),
        "owner": {
            "user_id": contest.owner_id,
            "username": contest.owner.username if contest.owner else "未知",
            # 对外展示/跳转主页用用户编号（UID），user_id 仅作内部主键
            "user_number": contest.owner.user_number if contest.owner else None,
        },
        "participant_count": len(contest.participants),
        "problem_count": len(contest.problems),
        "is_owner": is_owner,
        "can_manage": can_manage,
        "can_edit": can_edit_flag,
        "hide_submissions_from_admin": getattr(contest, "hide_submissions_from_admin", False),
        # 是否计入比赛等级分（结算接口见 /{id}/rating/settle）
        "is_rated": bool(getattr(contest, "is_rated", False)),
    }
    # 邀请码对创建者/管理员/有编辑权限者可见
    if d["can_manage"] or d["is_owner"] or d["can_edit"]:
        d["invite_code"] = getattr(contest, "invite_code", None)
    if current_user:
        my_p = next((p for p in contest.participants if p.user_id == current_user.id), None)
        d["is_participant"] = my_p is not None
        if my_p and my_p.team_id and my_p.team:
            d["my_team"] = {
                "id": my_p.team.id,
                "name": my_p.team.name,
                "leader_id": my_p.team.leader_id,
                "is_leader": my_p.team.leader_id == current_user.id,
                "invite_code": my_p.team.invite_code,
                "members": [
                    {
                        "user_id": m.user.id,
                        "username": m.user.username,
                        "user_number": m.user.user_number,
                        "display_tag": m.user.display_tag,
                        "username_color": m.user.username_color,
                        "is_leader": m.user_id == my_p.team.leader_id,
                    }
                    for m in (my_p.team.members or []) if m.user
                ],
            }
        else:
            d["my_team"] = None
    else:
        d["is_participant"] = False
        d["my_team"] = None
    # 题目/排行榜可见性：已结束、或（进行中且已报名）、或创建者/比赛管理员。
    # 团队赛的成员判断需要查库，由调用端点算好传入（can_view_problems 参数）
    status_ = d["status"]
    if can_view_problems is not None:
        d["can_view_problems"] = can_view_problems
    else:
        d["can_view_problems"] = (
            status_ == "ended"
            or (status_ == "running" and (
                d["is_owner"] or d["can_manage"] or d["is_participant"]
            ))
        )
    if with_problems:
        if not d["can_view_problems"] and not d["can_edit"]:
            # 无权查看且无权编辑时不下发任何题目信息（防探测）
            d["problems"] = []
        else:
            hide_titles = status_ == "pending" and not show_hidden_problems
            problems = []
            for cp in contest.problems:
                problems.append({
                    "alias": ALIAS[cp.sort_order] if cp.sort_order < len(ALIAS) else str(cp.sort_order),
                    "problem_id": cp.problem_id,
                    "sort_order": cp.sort_order,
                    # 未开始时不暴露题目标题（防提前审题）
                    "title": "※" if hide_titles else cp.problem.title,
                    "difficulty": cp.problem.difficulty,
                    "problem_number": cp.problem.problem_number,
                })
            d["problems"] = problems
    return d


async def _load_contest(db: AsyncSession, contest_id: int) -> Optional[Contest]:
    return (await db.execute(
        select(Contest).where(Contest.id == contest_id)
    )).scalar_one_or_none()


def _parse_time(value: Any) -> datetime:
    try:
        t = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="时间格式不正确")
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t


@router.get("", summary="比赛列表")
async def list_contests(
    page: int = Query(0, ge=0),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> dict:
    total = (await db.execute(
        select(sa_func.count()).select_from(Contest)
    )).scalar() or 0
    contests = (await db.execute(
        select(Contest).order_by(Contest.start_time.desc())
        .offset(page * page_size).limit(page_size)
    )).scalars().unique().all()
    items = [_contest_dict(c, current_user) for c in contests]
    # 分区排序：进行中 → 未开始 → 已结束
    order = {"running": 0, "pending": 1, "ended": 2}
    items.sort(key=lambda x: (order[x["status"]], x["start_time"] or ""))
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def _resolve_problem_ids(
    db: AsyncSession, raw_codes: list[Any], current_user: User
) -> list[int]:
    if not raw_codes:
        raise HTTPException(status_code=400, detail="请至少添加一道比赛题目")
    seen: set[int] = set()
    unique_ids: list[int] = []
    for raw in raw_codes:
        code = str(raw).strip().upper()
        if code.isdigit():
            problem = await ProblemService.get_by_id(db, int(code))
        elif code.startswith("T") and code[1:].isdigit():
            t_val = int(code[1:])
            problem = (await db.execute(
                select(Problem).where(Problem.t_no == t_val)
            )).scalar_one_or_none()
            if problem is None:
                cand = await ProblemService.get_by_id(db, t_val)
                if cand is not None and cand.team_id is not None:
                    problem = cand
        elif code[:1] in ("P", "U") and code[1:].isdigit():
            problem = await ProblemService.get_by_id(db, int(code[1:]) - 1000)
            # 编号字母与题目归属一致，防止 P/U 串号
            if (problem is not None and problem.team_id is None
                    and bool(problem.is_official) != code.startswith("P")):
                problem = None
        else:
            problem = None
        is_author = problem is not None and problem.author_id == current_user.id
        is_site_admin = _can_manage_contest(current_user)
        # 主题库题必须审核通过且公开，或出题人本人/站方管理员可用；团队题遵循公开状态或团队管理权限
        if problem is None or (
            problem.team_id is None
            and not (problem.is_public and problem.review_status == REVIEW_APPROVED)
            and not (is_author or is_site_admin)
        ) or (
            problem.team_id is not None
            and not problem.is_public
            and not (await _is_team_admin(db, problem.team_id, current_user) or is_author or is_site_admin)
        ):
            raise HTTPException(status_code=400, detail=f"题目 {raw} 不存在或无权使用")
        if problem.id in seen:
            continue
        seen.add(problem.id)
        unique_ids.append(problem.id)
    return unique_ids


@router.post("", status_code=201, summary="创建比赛（站方赛需题目管理权限；团队赛需团队管理权限）")
async def create_contest(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="比赛名称不能为空")
    start_time = _parse_time(payload.get("start_time"))
    end_time = _parse_time(payload.get("end_time"))
    if end_time <= start_time:
        raise HTTPException(status_code=400, detail="结束时间必须晚于开始时间")

    # 举办方：团队赛（team_id 非空）由团队管理员创建，类型限团队公开赛/团队内部赛/团队邀请赛；
    # 站方赛由题目管理权限/站内管理员创建，类型限公开赛/邀请赛
    raw_team_id = payload.get("team_id")
    team_id = None
    if raw_team_id is not None and raw_team_id != "":
        try:
            team_id = int(raw_team_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="无效的团队")
    visibility = payload.get("visibility") or "public"
    invite_code = (payload.get("invite_code") or "").strip()
    # 赛制：xcpc / ioi / oi（兼容历史 acm）
    rule_type = (payload.get("rule_type") or "xcpc").strip().lower()
    if rule_type == "acm":
        rule_type = "xcpc"
    if rule_type not in ("xcpc", "ioi", "oi"):
        raise HTTPException(status_code=400, detail="赛制仅支持 xcpc / ioi / oi")
    if team_id is not None:
        if not await _is_team_admin(db, team_id, current_user):
            raise HTTPException(status_code=403, detail="需要团队管理权限")
        if visibility not in ("team_public", "team", "team_private", "public"):
            raise HTTPException(
                status_code=400,
                detail="团队比赛仅支持「团队公开赛」、「团队内部赛」或「团队邀请赛」",
            )
        if visibility == "public":
            visibility = "team_public"
        team = (await db.execute(
            select(Team).where(Team.id == team_id)
        )).scalar_one_or_none()
        if team is None:
            raise HTTPException(status_code=400, detail="团队不存在")
    else:
        if not _can_manage_contest(current_user):
            raise HTTPException(status_code=403, detail="需要比赛管理权限")
        if visibility not in ("public", "private"):
            raise HTTPException(
                status_code=400, detail="站方比赛仅支持「公开赛」或「邀请赛」"
            )
    if visibility in ("private", "team_private"):
        if not (3 <= len(invite_code) <= 32):
            raise HTTPException(
                status_code=400, detail="邀请赛需设置 3-32 位邀请码"
            )
    else:
        invite_code = ""

    # 题目按题号或 ID 输入（P1001 / U1001 / T10 / ID），顺序即比赛内 A/B/C/D
    raw_codes = payload.get("problem_codes") or payload.get("problem_ids") or []
    unique_ids = await _resolve_problem_ids(db, raw_codes, current_user)
    hide_submissions_from_admin = bool(payload.get("hide_submissions_from_admin", True))
    is_team_contest = bool(payload.get("is_team_contest", False))
    # 组队赛暂不支持等级分（结算口径歧义），勾了也不生效
    is_rated = bool(payload.get("is_rated", False)) and not is_team_contest
    raw_max_m = payload.get("max_team_members", 3)
    try:
        max_team_members = int(raw_max_m) if raw_max_m is not None else 3
    except (ValueError, TypeError):
        max_team_members = 3
    if not (1 <= max_team_members <= 10):
        raise HTTPException(status_code=400, detail="每队人数上限需在 1 到 10 之间")

    contest = Contest(
        title=title,
        description=(payload.get("description") or "").strip() or None,
        visibility=visibility,
        invite_code=invite_code if visibility in ("private", "team_private") else None,
        team_id=team_id if team_id is not None else None,
        rule_type=rule_type,
        hide_submissions_from_admin=hide_submissions_from_admin,
        is_team_contest=is_team_contest,
        is_rated=is_rated,
        max_team_members=max_team_members,
        start_time=start_time, end_time=end_time,
        owner_id=current_user.id,
    )
    db.add(contest)
    await db.flush()
    for order, pid in enumerate(unique_ids):
        db.add(ContestProblem(contest_id=contest.id, problem_id=pid, sort_order=order))
    if visibility in ("public", "team_public"):
        await db.execute(
            update(Problem)
            .where(Problem.id.in_(unique_ids), Problem.team_id.is_not(None))
            .values(is_public=True)
        )
    await db.commit()
    await db.refresh(contest)
    return _contest_dict(contest, current_user, with_problems=True,
                         show_hidden_problems=True,
                         can_view_problems=_status(contest) != "pending",
                         can_edit=True)


@router.get("/{contest_id}", summary="比赛详情")
async def contest_detail(
    contest_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> dict:
    contest = await _load_contest(db, contest_id)
    if contest is None:
        raise HTTPException(status_code=404, detail="比赛不存在")
    status_ = _status(contest)
    is_organizer = await is_contest_organizer(db, contest, current_user)
    shield_active = getattr(contest, "hide_submissions_from_admin", False)
    is_participant = bool(current_user and any(
        p.user_id == current_user.id for p in contest.participants))
    is_owner = bool(current_user and contest.owner_id == current_user.id)
    is_manager = bool(current_user and _can_manage_contest(current_user))
    team_member = bool(
        contest.team_id and current_user
        and await _is_team_member(db, contest.team_id, current_user)
    )
    team_admin = bool(
        contest.team_id and current_user
        and await _is_team_admin(db, contest.team_id, current_user)
    )
    can_bypass = is_organizer or (is_manager and not shield_active)
    can_view = (
        status_ == "ended"
        or (status_ == "running" and (
            can_bypass or team_admin
            or (is_participant and (contest.team_id is None
                                     or (contest.visibility or "") != "team"
                                     or team_member))
        ))
    )
    can_edit_val = is_owner or is_manager or team_admin
    show_hidden = can_bypass or (team_admin and not shield_active)
    return _contest_dict(contest, current_user,
                         with_problems=True, show_hidden_problems=show_hidden,
                         can_view_problems=can_view,
                         can_edit=can_edit_val)


@router.put("/{contest_id}", summary="编辑比赛")
async def update_contest(
    contest_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    contest = await _load_contest(db, contest_id)
    if contest is None:
        raise HTTPException(status_code=404, detail="比赛不存在")
    if not await _can_edit_contest(db, contest, current_user):
        raise HTTPException(status_code=403, detail="无权编辑该比赛")

    # 1. 标题
    if "title" in payload:
        title = (payload.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="比赛名称不能为空")
        contest.title = title

    # 2. 起止时间
    if "start_time" in payload or "end_time" in payload:
        st = _parse_time(payload["start_time"]) if "start_time" in payload else _aware(contest.start_time)
        et = _parse_time(payload["end_time"]) if "end_time" in payload else _aware(contest.end_time)
        if et <= st:
            raise HTTPException(status_code=400, detail="结束时间必须晚于开始时间")
        contest.start_time = st
        contest.end_time = et

    # 3. 描述
    if "description" in payload:
        contest.description = (payload.get("description") or "").strip() or None

    # 4. 赛制
    if "rule_type" in payload:
        rule_type = (payload.get("rule_type") or "xcpc").strip().lower()
        if rule_type == "acm":
            rule_type = "xcpc"
        if rule_type not in ("xcpc", "ioi", "oi"):
            raise HTTPException(status_code=400, detail="赛制仅支持 xcpc / ioi / oi")
        contest.rule_type = rule_type

    # 5. 举办方（个人/团队）与公开程度
    if "team_id" in payload or "visibility" in payload:
        raw_team_id = payload.get("team_id") if "team_id" in payload else contest.team_id
        target_team_id = None
        if raw_team_id is not None and raw_team_id != "":
            try:
                target_team_id = int(raw_team_id)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="无效的团队")
        target_visibility = payload.get("visibility") if "visibility" in payload else contest.visibility

        if target_visibility in ("team_public", "team", "team_private") and target_team_id is None:
            raise HTTPException(status_code=400, detail="举办团队比赛需指定举办团队")

        if target_team_id is not None:
            if not await _is_team_admin(db, target_team_id, current_user):
                raise HTTPException(status_code=403, detail="需要目标团队的管理权限")
            target_team = (await db.execute(
                select(Team).where(Team.id == target_team_id)
            )).scalar_one_or_none()
            if target_team is None:
                raise HTTPException(status_code=400, detail="团队不存在")
            if target_visibility not in ("team_public", "team", "team_private", "public"):
                raise HTTPException(
                    status_code=400,
                    detail="团队比赛仅支持「团队公开赛」、「团队内部赛」或「团队邀请赛」",
                )
            if target_visibility == "public":
                target_visibility = "team_public"
            contest.team_id = target_team_id
            contest.visibility = target_visibility
        else:
            # 切换为个人比赛
            if not _can_manage_contest(current_user):
                raise HTTPException(status_code=403, detail="个人比赛需要比赛管理权限")
            if target_visibility not in ("public", "private"):
                raise HTTPException(
                    status_code=400, detail="个人比赛仅支持「公开赛」或「邀请赛」"
                )
            contest.team_id = None
            contest.visibility = target_visibility

    # 6. 邀请码
    if contest.visibility in ("private", "team_private"):
        if "invite_code" in payload:
            code = (payload.get("invite_code") or "").strip()
            if not (3 <= len(code) <= 32):
                raise HTTPException(status_code=400, detail="邀请赛需设置 3-32 位邀请码")
            contest.invite_code = code
        elif not contest.invite_code:
            raise HTTPException(status_code=400, detail="邀请赛需设置 3-32 位邀请码")
    else:
        contest.invite_code = None

    # 7. 比赛题目增删改排序
    if "problem_codes" in payload or "problem_ids" in payload:
        raw_codes = payload.get("problem_codes") if "problem_codes" in payload else (payload.get("problem_ids") or [])
        unique_ids = await _resolve_problem_ids(db, raw_codes, current_user)
        contest.problems.clear()
        await db.flush()
        for order, pid in enumerate(unique_ids):
            contest.problems.append(ContestProblem(contest_id=contest.id, problem_id=pid, sort_order=order))
        await db.flush()

    if (contest.visibility or "") in ("public", "team_public"):
        c_pids = [cp.problem_id for cp in contest.problems]
        if c_pids:
            await db.execute(
                update(Problem)
                .where(Problem.id.in_(c_pids), Problem.team_id.is_not(None))
                .values(is_public=True)
            )

    # 8. 管理员参赛保护
    if "hide_submissions_from_admin" in payload:
        contest.hide_submissions_from_admin = bool(payload["hide_submissions_from_admin"])

    # 9. 组队赛设置
    if "is_team_contest" in payload:
        contest.is_team_contest = bool(payload["is_team_contest"])
    if "is_rated" in payload:
        contest.is_rated = bool(payload["is_rated"]) and not bool(
            getattr(contest, "is_team_contest", False))
    if "max_team_members" in payload:
        try:
            m = int(payload["max_team_members"])
            if 1 <= m <= 10:
                contest.max_team_members = m
            else:
                raise HTTPException(status_code=400, detail="每队人数上限需在 1 到 10 之间")
        except (ValueError, TypeError):
            pass

    await db.commit()
    contest = (await db.execute(
        select(Contest)
        .where(Contest.id == contest_id)
        .options(
            selectinload(Contest.problems).joinedload(ContestProblem.problem),
            selectinload(Contest.participants),
        )
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    return _contest_dict(
        contest, current_user, with_problems=True, show_hidden_problems=True,
        can_view_problems=_status(contest) != "pending", can_edit=True
    )


@router.delete("/{contest_id}", summary="删除比赛（创建者或站内管理员）")
async def delete_contest(
    contest_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    contest = await _load_contest(db, contest_id)
    if contest is None:
        raise HTTPException(status_code=404, detail="比赛不存在")
    if not await _can_edit_contest(db, contest, current_user):
        raise HTTPException(status_code=403, detail="无权删除该比赛")
    await db.delete(contest)
    await db.commit()
    return {"success": True}


@router.post("/{contest_id}/register", summary="报名比赛（邀请赛需邀请码）")
async def register_contest(
    contest_id: int,
    payload: Optional[dict] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    contest = await _load_contest(db, contest_id)
    if contest is None:
        raise HTTPException(status_code=404, detail="比赛不存在")
    if _status(contest) == "ended":
        raise HTTPException(status_code=400, detail="比赛已结束，无法报名")
    visibility = contest.visibility or "public"
    if visibility == "team":
        # 团队内部赛：仅团队成员可报名
        if not await _is_team_member(db, contest.team_id, current_user):
            raise HTTPException(status_code=403, detail="仅团队成员可报名内部赛")
    elif visibility in ("private", "team_private"):
        code = ((payload or {}).get("invite_code") or "").strip()
        if not code or code != contest.invite_code:
            raise HTTPException(status_code=403, detail="邀请码错误")
    exists = (await db.execute(
        select(ContestParticipant).where(
            ContestParticipant.contest_id == contest_id,
            ContestParticipant.user_id == current_user.id)
    )).scalar_one_or_none()

    if getattr(contest, "is_team_contest", False):
        if exists is not None and exists.team_id is not None:
            raise HTTPException(status_code=400, detail="你已报名该比赛并加入了队伍")

        team_name = ((payload or {}).get("team_name") or "").strip()
        team_invite_code = ((payload or {}).get("team_invite_code") or "").strip()

        target_team = None
        if team_invite_code:
            target_team = (await db.execute(
                select(ContestTeam).where(
                    ContestTeam.contest_id == contest_id,
                    ContestTeam.invite_code == team_invite_code,
                )
            )).scalar_one_or_none()
            if not target_team:
                raise HTTPException(status_code=404, detail="未找到对应的队伍或队伍邀请口令错误")
            mc = (await db.execute(
                select(sa_func.count(ContestParticipant.id)).where(
                    ContestParticipant.contest_id == contest_id,
                    ContestParticipant.team_id == target_team.id,
                )
            )).scalar() or 0
            max_m = contest.max_team_members or 3
            if mc >= max_m:
                raise HTTPException(status_code=400, detail=f"该队伍人数已达上限（{max_m} 人）")
            if exists is not None:
                exists.team_id = target_team.id
            else:
                db.add(ContestParticipant(
                    contest_id=contest_id,
                    user_id=current_user.id,
                    team_id=target_team.id,
                ))
            await db.commit()
            return {"success": True, "team_id": target_team.id, "team_name": target_team.name}
        elif team_name:
            dup = (await db.execute(
                select(ContestTeam.id).where(
                    ContestTeam.contest_id == contest_id,
                    ContestTeam.name == team_name,
                )
            )).scalar_one_or_none()
            if dup is not None:
                raise HTTPException(status_code=400, detail="该队伍名称在此比赛中已被使用，请换一个名称")
            code_gen = secrets.token_hex(3).upper()
            target_team = ContestTeam(
                contest_id=contest_id,
                name=team_name,
                leader_id=current_user.id,
                invite_code=code_gen,
            )
            db.add(target_team)
            await db.flush()

            if exists is not None:
                exists.team_id = target_team.id
            else:
                db.add(ContestParticipant(
                    contest_id=contest_id,
                    user_id=current_user.id,
                    team_id=target_team.id,
                ))
            await db.commit()
            return {"success": True, "team_id": target_team.id, "team_name": target_team.name, "invite_code": target_team.invite_code}
        else:
            if exists is not None:
                raise HTTPException(status_code=400, detail="你已报名该比赛")
            db.add(ContestParticipant(
                contest_id=contest_id,
                user_id=current_user.id,
                team_id=None,
            ))
            await db.commit()
            return {"success": True, "message": "报名成功，请创建或加入队伍"}

    if exists is not None:
        raise HTTPException(status_code=400, detail="你已报名该比赛")
    db.add(ContestParticipant(contest_id=contest_id, user_id=current_user.id))
    await db.commit()
    return {"success": True}


# ================================================================
# 组队赛队伍管理端点
# ================================================================

@router.post("/{contest_id}/teams", summary="创建参赛队伍（组队赛）")
async def create_contest_team(
    contest_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    contest = await _load_contest(db, contest_id)
    if contest is None:
        raise HTTPException(status_code=404, detail="比赛不存在")
    if not contest.is_team_contest:
        raise HTTPException(status_code=400, detail="该比赛不是组队赛，无需创建队伍")
    if _status(contest) == "ended":
        raise HTTPException(status_code=400, detail="比赛已结束，无法创建队伍")

    visibility = contest.visibility or "public"
    if visibility == "team":
        if not await _is_team_member(db, contest.team_id, current_user):
            raise HTTPException(status_code=403, detail="仅举办团队成员可参加该内部赛")
    elif visibility in ("private", "team_private"):
        p_exist = (await db.execute(
            select(ContestParticipant).where(
                ContestParticipant.contest_id == contest_id,
                ContestParticipant.user_id == current_user.id,
            )
        )).scalar_one_or_none()
        if p_exist is None:
            contest_code = ((payload.get("contest_invite_code") or payload.get("invite_code")) or "").strip()
            if not contest_code or contest_code != contest.invite_code:
                raise HTTPException(status_code=403, detail="比赛邀请码错误")

    existing_p = (await db.execute(
        select(ContestParticipant).where(
            ContestParticipant.contest_id == contest_id,
            ContestParticipant.user_id == current_user.id,
        )
    )).scalar_one_or_none()
    if existing_p is not None and existing_p.team_id is not None:
        raise HTTPException(status_code=400, detail="你已在当前比赛的另一支队伍中，请先退出再创建")

    name = (payload.get("name") or "").strip()
    if not (1 <= len(name) <= 50):
        raise HTTPException(status_code=400, detail="队伍名称长度需在 1 到 50 个字符之间")

    dup_team = (await db.execute(
        select(ContestTeam.id).where(
            ContestTeam.contest_id == contest_id,
            ContestTeam.name == name,
        )
    )).scalar_one_or_none()
    if dup_team is not None:
        raise HTTPException(status_code=400, detail="该队伍名称在此比赛中已被使用，请换一个名称")

    team_invite_code = (payload.get("team_invite_code") or "").strip()
    if not team_invite_code:
        team_invite_code = secrets.token_hex(3).upper()
    elif not (3 <= len(team_invite_code) <= 32):
        raise HTTPException(status_code=400, detail="队伍邀请口令需在 3 到 32 个字符之间")

    new_team = ContestTeam(
        contest_id=contest_id,
        name=name,
        leader_id=current_user.id,
        invite_code=team_invite_code,
    )
    db.add(new_team)
    await db.flush()

    if existing_p is not None:
        existing_p.team_id = new_team.id
    else:
        db.add(ContestParticipant(
            contest_id=contest_id,
            user_id=current_user.id,
            team_id=new_team.id,
        ))

    await db.commit()
    return {
        "success": True,
        "team_id": new_team.id,
        "name": new_team.name,
        "invite_code": new_team.invite_code,
    }


@router.post("/{contest_id}/teams/join", summary="加入参赛队伍（组队赛）")
async def join_contest_team(
    contest_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    contest = await _load_contest(db, contest_id)
    if contest is None:
        raise HTTPException(status_code=404, detail="比赛不存在")
    if not contest.is_team_contest:
        raise HTTPException(status_code=400, detail="该比赛不是组队赛")
    if _status(contest) == "ended":
        raise HTTPException(status_code=400, detail="比赛已结束，无法加入队伍")

    visibility = contest.visibility or "public"
    if visibility == "team":
        if not await _is_team_member(db, contest.team_id, current_user):
            raise HTTPException(status_code=403, detail="仅举办团队成员可参加该内部赛")
    elif visibility in ("private", "team_private"):
        p_exist = (await db.execute(
            select(ContestParticipant).where(
                ContestParticipant.contest_id == contest_id,
                ContestParticipant.user_id == current_user.id,
            )
        )).scalar_one_or_none()
        if p_exist is None:
            contest_code = (payload.get("contest_invite_code") or "").strip()
            if not contest_code or contest_code != contest.invite_code:
                raise HTTPException(status_code=403, detail="比赛邀请码错误")

    existing_p = (await db.execute(
        select(ContestParticipant).where(
            ContestParticipant.contest_id == contest_id,
            ContestParticipant.user_id == current_user.id,
        )
    )).scalar_one_or_none()
    if existing_p is not None and existing_p.team_id is not None:
        raise HTTPException(status_code=400, detail="你已在当前比赛的一支队伍中，请先退出原队伍")

    team_id = payload.get("team_id")
    invite_code = (payload.get("invite_code") or "").strip()
    if not invite_code and not team_id:
        raise HTTPException(status_code=400, detail="请输入队伍邀请口令")

    query = select(ContestTeam).where(ContestTeam.contest_id == contest_id)
    if team_id:
        query = query.where(ContestTeam.id == int(team_id))
    if invite_code:
        query = query.where(ContestTeam.invite_code == invite_code)

    target_team = (await db.execute(query)).scalar_one_or_none()
    if target_team is None:
        raise HTTPException(status_code=404, detail="未找到对应的队伍或队伍邀请口令错误")

    member_count = (await db.execute(
        select(sa_func.count(ContestParticipant.id)).where(
            ContestParticipant.contest_id == contest_id,
            ContestParticipant.team_id == target_team.id,
        )
    )).scalar() or 0

    max_m = contest.max_team_members or 3
    if member_count >= max_m:
        raise HTTPException(status_code=400, detail=f"该队伍人数已达上限（{max_m} 人）")

    if existing_p is not None:
        existing_p.team_id = target_team.id
    else:
        db.add(ContestParticipant(
            contest_id=contest_id,
            user_id=current_user.id,
            team_id=target_team.id,
        ))

    await db.commit()
    return {"success": True, "team_id": target_team.id, "name": target_team.name}


@router.post("/{contest_id}/teams/{team_id}/add_member", summary="队长添加队员（组队赛）")
async def add_contest_team_member(
    contest_id: int,
    team_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    contest = await _load_contest(db, contest_id)
    if contest is None:
        raise HTTPException(status_code=404, detail="比赛不存在")
    if _status(contest) == "ended":
        raise HTTPException(status_code=400, detail="比赛已结束，不可添加队员")

    team = (await db.execute(
        select(ContestTeam).where(
            ContestTeam.id == team_id,
            ContestTeam.contest_id == contest_id,
        )
    )).scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=404, detail="队伍不存在")
    if team.leader_id != current_user.id and not current_user.is_super_admin:
        raise HTTPException(status_code=403, detail="只有队长可以添加队员")

    username_or_uid = str(payload.get("username_or_uid") or "").strip()
    if not username_or_uid:
        raise HTTPException(status_code=400, detail="请输入队友的用户名或 UID")

    target_user_query = select(User)
    if username_or_uid.isdigit():
        target_user_query = target_user_query.where(
            or_(User.user_number == int(username_or_uid), User.username == username_or_uid)
        )
    else:
        target_user_query = target_user_query.where(User.username == username_or_uid)
    target_user = (await db.execute(target_user_query)).scalar_one_or_none()
    if target_user is None:
        raise HTTPException(status_code=404, detail=f"未找到用户「{username_or_uid}」")

    member_count = (await db.execute(
        select(sa_func.count(ContestParticipant.id)).where(
            ContestParticipant.contest_id == contest_id,
            ContestParticipant.team_id == team.id,
        )
    )).scalar() or 0
    max_m = contest.max_team_members or 3
    if member_count >= max_m:
        raise HTTPException(status_code=400, detail=f"队伍人数已达上限（{max_m} 人）")

    p_target = (await db.execute(
        select(ContestParticipant).where(
            ContestParticipant.contest_id == contest_id,
            ContestParticipant.user_id == target_user.id,
        )
    )).scalar_one_or_none()
    if p_target and p_target.team_id is not None:
        if p_target.team_id == team.id:
            raise HTTPException(status_code=400, detail="该用户已在队伍中")
        raise HTTPException(status_code=400, detail="该用户已加入本场比赛的其他队伍")

    if p_target:
        p_target.team_id = team.id
    else:
        db.add(ContestParticipant(
            contest_id=contest_id,
            user_id=target_user.id,
            team_id=team.id,
        ))

    await db.commit()
    return {"success": True, "added_user": target_user.username}


@router.post("/{contest_id}/teams/leave", summary="退出或解散参赛队伍")
async def leave_contest_team(
    contest_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    contest = await _load_contest(db, contest_id)
    if contest is None:
        raise HTTPException(status_code=404, detail="比赛不存在")
    if _status(contest) == "ended":
        raise HTTPException(status_code=400, detail="比赛已结束，不可退出队伍")

    p = (await db.execute(
        select(ContestParticipant).where(
            ContestParticipant.contest_id == contest_id,
            ContestParticipant.user_id == current_user.id,
        )
    )).scalar_one_or_none()
    if p is None or p.team_id is None:
        raise HTTPException(status_code=400, detail="你当前未加入任何队伍")

    team = (await db.execute(
        select(ContestTeam).where(ContestTeam.id == p.team_id)
    )).scalar_one_or_none()

    if team:
        other_members = (await db.execute(
            select(ContestParticipant).where(
                ContestParticipant.contest_id == contest_id,
                ContestParticipant.team_id == team.id,
                ContestParticipant.user_id != current_user.id,
            )
        )).scalars().all()

        if team.leader_id == current_user.id:
            if not other_members:
                # 队长且只有自己一人，直接解散队伍并退出比赛报名
                await db.delete(team)
                await db.delete(p)
            else:
                # 转移队长给下一位队员，自己退出
                team.leader_id = other_members[0].user_id
                await db.delete(p)
        else:
            await db.delete(p)
    else:
        await db.delete(p)

    await db.commit()
    return {"success": True}


@router.post("/{contest_id}/teams/{team_id}/kick", summary="队长移出队员")
async def kick_contest_team_member(
    contest_id: int,
    team_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    contest = await _load_contest(db, contest_id)
    if contest is None:
        raise HTTPException(status_code=404, detail="比赛不存在")
    if _status(contest) == "ended":
        raise HTTPException(status_code=400, detail="比赛已结束，不可操作")

    team = (await db.execute(
        select(ContestTeam).where(
            ContestTeam.id == team_id,
            ContestTeam.contest_id == contest_id,
        )
    )).scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=404, detail="队伍不存在")
    if team.leader_id != current_user.id and not current_user.is_super_admin:
        raise HTTPException(status_code=403, detail="只有队长可移出队员")

    target_user_id = payload.get("user_id")
    if not target_user_id or target_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能移出队长自己，若要解散请点击退出队伍")

    target_p = (await db.execute(
        select(ContestParticipant).where(
            ContestParticipant.contest_id == contest_id,
            ContestParticipant.team_id == team.id,
            ContestParticipant.user_id == target_user_id,
        )
    )).scalar_one_or_none()
    if target_p is None:
        raise HTTPException(status_code=404, detail="该队员不在此队伍中")

    await db.delete(target_p)
    await db.commit()
    return {"success": True}


@router.get("/{contest_id}/my-team", summary="获取当前用户的参赛队伍详情")
async def get_my_contest_team(
    contest_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Optional[dict]:
    p = (await db.execute(
        select(ContestParticipant).where(
            ContestParticipant.contest_id == contest_id,
            ContestParticipant.user_id == current_user.id,
        )
    )).scalar_one_or_none()
    if not p or not p.team_id:
        return None

    team = (await db.execute(
        select(ContestTeam).where(ContestTeam.id == p.team_id)
        .options(joinedload(ContestTeam.leader))
    )).scalar_one_or_none()
    if not team:
        return None

    members_p = (await db.execute(
        select(ContestParticipant).where(
            ContestParticipant.contest_id == contest_id,
            ContestParticipant.team_id == team.id,
        ).options(joinedload(ContestParticipant.user))
    )).scalars().all()

    return {
        "id": team.id,
        "name": team.name,
        "leader_id": team.leader_id,
        "is_leader": team.leader_id == current_user.id,
        "invite_code": team.invite_code,
        "created_at": _aware(team.created_at).isoformat() if team.created_at else None,
        "members": [
            {
                "user_id": mp.user.id,
                "user_number": mp.user.user_number,
                "username": mp.user.username,
                "display_tag": mp.user.display_tag,
                "username_color": mp.user.username_color,
                "color_tier": getattr(mp.user, "color_tier", None),
                "name_color": getattr(mp.user, "name_color", "") or "",
                "is_cheater": mp.user.is_cheater,
                "is_banned": mp.user.is_banned,
                "is_super_admin": mp.user.is_super_admin,
                "is_big_admin": getattr(mp.user, "is_big_admin", False),
                "can_manage_problems": mp.user.can_manage_problems,
                "can_manage_posts": mp.user.can_manage_posts,
                "is_leader": mp.user_id == team.leader_id,
            }
            for mp in members_p if mp.user
        ],
    }


@router.get("/{contest_id}/teams", summary="获取比赛参赛队伍列表")
async def list_contest_teams(
    contest_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> list[dict]:
    teams = (await db.execute(
        select(ContestTeam).where(ContestTeam.contest_id == contest_id)
        .options(joinedload(ContestTeam.leader))
        .order_by(ContestTeam.created_at.asc())
    )).scalars().all()

    all_members = (await db.execute(
        select(ContestParticipant).where(
            ContestParticipant.contest_id == contest_id,
            ContestParticipant.team_id.isnot(None),
        ).options(joinedload(ContestParticipant.user))
    )).scalars().all()

    members_by_team: dict[int, list] = {}
    for m in all_members:
        if m.team_id not in members_by_team:
            members_by_team[m.team_id] = []
        if m.user:
            members_by_team[m.team_id].append({
                "user_id": m.user.id,
                "user_number": m.user.user_number,
                "username": m.user.username,
                "display_tag": m.user.display_tag,
                "username_color": m.user.username_color,
                "color_tier": getattr(m.user, "color_tier", None),
                "name_color": getattr(m.user, "name_color", "") or "",
                "is_cheater": m.user.is_cheater,
                "is_banned": m.user.is_banned,
                "is_super_admin": m.user.is_super_admin,
                "is_big_admin": getattr(m.user, "is_big_admin", False),
                "can_manage_problems": m.user.can_manage_problems,
                "can_manage_posts": m.user.can_manage_posts,
                "is_leader": m.user_id == (next((t.leader_id for t in teams if t.id == m.team_id), None)),
            })

    result = []
    for t in teams:
        team_dict = {
            "id": t.id,
            "name": t.name,
            "leader_id": t.leader_id,
            "leader_name": t.leader.username if t.leader else "未知",
            "member_count": len(members_by_team.get(t.id, [])),
            "members": members_by_team.get(t.id, []),
            "created_at": _aware(t.created_at).isoformat() if t.created_at else None,
        }
        is_member = bool(current_user and any(m["user_id"] == current_user.id for m in team_dict["members"]))
        if is_member or (current_user and _can_manage_contest(current_user)):
            team_dict["invite_code"] = t.invite_code
        result.append(team_dict)
    return result


@router.get("/{contest_id}/rank", summary="比赛排名（按赛制：ACM / IOI / OI）")
async def contest_rank(
    contest_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> dict:
    contest = await _load_contest(db, contest_id)
    if contest is None:
        raise HTTPException(status_code=404, detail="比赛不存在")

    raw_rule = getattr(contest, "rule_type", "xcpc") or "xcpc"
    rule_type = "xcpc" if raw_rule == "acm" else raw_rule
    is_team_contest = bool(getattr(contest, "is_team_contest", False))

    # 排行榜可见性：已结束、创建者/比赛管理员、进行中且已报名；
    # 团队内部赛额外要求查看者为团队成员
    status_ = _status(contest)
    is_participant = bool(current_user and any(
        p.user_id == current_user.id for p in contest.participants))
    is_manager = bool(current_user and _can_manage_contest(current_user))
    is_owner = bool(current_user and contest.owner_id == current_user.id)
    team_member = bool(
        contest.team_id and current_user
        and await _is_team_member(db, contest.team_id, current_user)
    )
    team_admin = bool(
        contest.team_id and current_user
        and await _is_team_admin(db, contest.team_id, current_user)
    )
    allowed = (
        status_ == "ended"
        or (status_ == "running" and (
            is_manager or is_owner or team_admin
            or (is_participant
                and (contest.team_id is None
                     or (contest.visibility or "") != "team"
                     or team_member))
        ))
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="你无权进行此操作")

    cps = (await db.execute(
        select(ContestProblem).where(ContestProblem.contest_id == contest_id)
        .order_by(ContestProblem.sort_order)
    )).scalars().all()
    aliases = [
        ALIAS[cp.sort_order] if cp.sort_order < len(ALIAS) else str(cp.sort_order)
        for cp in cps
    ]

    # OI 赛制赛中防偷窥：普通参赛者在比赛未结束前不显示榜单
    is_organizer = await is_contest_organizer(db, contest, current_user)
    shield_active = getattr(contest, "hide_submissions_from_admin", False)
    can_view_oi_live_rank = is_organizer if shield_active else (is_manager or is_owner or is_organizer)
    if rule_type == "oi" and status_ == "running" and not can_view_oi_live_rank:
        return {
            "rule_type": rule_type,
            "rule_type_label": RULE_LABELS.get(rule_type, "OI 赛制"),
            "is_team_contest": is_team_contest,
            "is_frozen": True,
            "message": "OI 赛制比赛进行中，排行榜暂不公开，比赛结束后统一揭晓",
            "aliases": aliases,
            "rows": [],
        }

    # 名次计算统一走 services/contest_rank.py（与等级分结算共用同一套分制）
    data = await contest_rank_service.build_rank_rows(db, contest)
    return {
        **data,
        "rule_type_label": RULE_LABELS.get(data["rule_type"], "XCPC 赛制"),
        "is_frozen": False,
    }


# ===================== 虚拟参赛 =====================


@router.get("/{contest_id}/virtual/me", summary="我的虚拟参赛状态（含倒计时与成绩）")
async def my_virtual_contest(
    contest_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """返回这场比赛的虚拟参赛状态。

    - ``active``：还在计时（前端据此显示倒计时，并按自己的时间窗提交）
    - ``results``：只统计带 ``virtual_contest_id`` 的提交（按题：通过/最高分/次数）
    """
    contest = await _load_contest(db, contest_id)
    if contest is None:
        raise HTTPException(status_code=404, detail="比赛不存在")

    # 只读：不在这里写库（到期由 start/finish 这些写路径收尾）
    vc = await virtual_service.get_active_virtual(db, current_user.id, contest_id)
    if vc is None:
        return {"virtual": None, "active": False, "results": []}
    problem_ids = [cp.problem_id for cp in contest.problems]
    return {
        "virtual": virtual_service.to_dict(vc),
        "active": True,
        "results": await virtual_service.results(
            db, current_user.id, vc.id, problem_ids),
    }


@router.post("/{contest_id}/virtual/start", summary="开始虚拟参赛（镜像一场已结束的比赛）")
async def start_virtual_contest(
    contest_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """开始/继续自己的虚拟赛。

    时长照抄原比赛（10 分钟 ~ 12 小时封顶），从这一刻开始计时；
    同一场比赛同时只能有一个进行中的虚拟赛，重复调用直接返回当前那个。
    """
    contest = await _load_contest(db, contest_id)
    if contest is None:
        raise HTTPException(status_code=404, detail="比赛不存在")
    ok, reason = virtual_service.validate_startable(contest)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    vc = await virtual_service.start(db, contest, current_user.id)
    return {"success": True, "virtual": virtual_service.to_dict(vc)}


@router.post("/{contest_id}/virtual/finish", summary="提前结束虚拟参赛")
async def finish_virtual_contest(
    contest_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """提前交卷：之后这场比赛就不允许再以虚拟身份提交了。"""
    contest = await _load_contest(db, contest_id)
    if contest is None:
        raise HTTPException(status_code=404, detail="比赛不存在")
    vc = await virtual_service.get_active_virtual(db, current_user.id, contest_id)
    if vc is None:
        raise HTTPException(status_code=400, detail="当前没有进行中的虚拟参赛")
    vc = await virtual_service.finish(db, vc)
    problem_ids = [cp.problem_id for cp in contest.problems]
    return {
        "success": True,
        "virtual": virtual_service.to_dict(vc),
        "results": await virtual_service.results(
            db, current_user.id, vc.id, problem_ids),
    }


# ===================== 比赛等级分（rating） =====================


@router.get("/{contest_id}/rating", summary="比赛等级分变化（结算后可见）")
async def contest_rating_board(
    contest_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> dict[str, Any]:
    """列出这场比赛每个人的等级分变化。结算前 ``settled=False``。

    非公开比赛（private / team*）只有参与者、举办者、比赛管理员、团队成员能看
    —— 等级分明细带用户名与分数变化，不该对路人公开。
    """
    contest = await _load_contest(db, contest_id)
    if contest is None:
        raise HTTPException(status_code=404, detail="比赛不存在")

    visibility = getattr(contest, "visibility", "public") or "public"
    if visibility != "public":
        is_owner = bool(current_user and contest.owner_id == current_user.id)
        is_manager = bool(current_user and _can_manage_contest(current_user))
        is_participant = bool(current_user and any(
            p.user_id == current_user.id for p in contest.participants))
        team_member = bool(
            contest.team_id and current_user
            and await _is_team_member(db, contest.team_id, current_user)
        )
        team_admin = bool(
            contest.team_id and current_user
            and await _is_team_admin(db, contest.team_id, current_user)
        )
        if not (is_owner or is_manager or is_participant or team_member or team_admin):
            raise HTTPException(status_code=403, detail="无权查看这场比赛的等级分")

    # 尚未开始的公开赛也还没结算，别把参赛名单提前晾出来
    if _status(contest) == "pending" and not (
        current_user and (contest.owner_id == current_user.id
                          or _can_manage_contest(current_user))
    ):
        raise HTTPException(status_code=403, detail="比赛尚未开始")

    items = await rating_service.get_contest_rating(db, contest_id)
    return {
        "is_rated": bool(getattr(contest, "is_rated", False)),
        "is_team_contest": bool(getattr(contest, "is_team_contest", False)),
        "settled": bool(items),
        "items": items,
    }


@router.post("/{contest_id}/rating/settle", summary="结算比赛等级分（题目管理权限或举办者）")
async def settle_contest_rating(
    contest_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """按当前排行榜结算等级分；幂等：已结算过直接返回旧结果。"""
    contest = await _load_contest(db, contest_id)
    if contest is None:
        raise HTTPException(status_code=404, detail="比赛不存在")

    if not (perm.can_manage_problems(current_user) or contest.owner_id == current_user.id):
        raise HTTPException(status_code=403, detail="需要题目管理权限")

    already = await rating_service.get_contest_rating(db, contest_id)
    if already:
        return {"success": True, "already_settled": True,
                "settled": len(already), "items": already}

    try:
        changed = await rating_service.settle_contest(db, contest)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except IntegrityError:
        await db.rollback()
        items = await rating_service.get_contest_rating(db, contest_id)
        return {"success": True, "already_settled": True,
                "settled": len(items), "items": items}

    return {
        "success": True,
        "already_settled": False,
        "settled": len(changed),
        "items": await rating_service.get_contest_rating(db, contest_id),
    }
