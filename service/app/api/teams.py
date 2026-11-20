"""团队 API：列表 / 详情 / 创建 / 加入 / 退出 / 解散 / 成员管理。

设计参照 Jason227 站的团队功能适配本站：
- owner 记录在 teams.owner_id，不在 team_members（渲染时以 role='owner' 拼入）
- 团队管理员（role='admin'）可管理成员（改备注/设管理员/移除）；解散仅 owner
- 加入自由，退出自由（owner 不可退出，只能解散）
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.deps import get_current_user, get_current_user_optional
from app.models.notification import Notification
from app.models.team import Team, TeamMember, TeamJoinRequest, TeamPost, TeamPostComment
from app.models.user import User
from app.services.notification import add_notification, notify_mentions, clip, TITLE_MAX

router = APIRouter(prefix="/teams", tags=["teams"])

MAX_TEAMS_NORMAL = 5      # 普通用户可创建的团队数上限
MAX_TEAMS_ADMIN = 10      # 管理员（非全权限）可创建的团队数上限
MAX_MEMBERS_PER_TEAM = 200


def _team_create_limit(user: User) -> int | None:
    """按身份返回可创建团队数上限；None = 不限制（全权限超管）。"""
    if user.is_super_admin:
        return None
    if (user.is_admin or user.can_manage_users
            or user.can_manage_posts or user.can_manage_problems):
        return MAX_TEAMS_ADMIN
    return MAX_TEAMS_NORMAL


def _user_brief(user: User | None) -> dict[str, Any]:
    """成员卡片所需的全站统一用户信息（配色判定字段齐全）。"""
    if user is None:
        return {
            "user_id": None, "username": "已删除用户", "user_tag": "",
            "is_admin": False, "is_super_admin": False, "is_banned": False,
            "is_cheater": False, "can_manage_users": False,
            "can_manage_posts": False, "can_manage_problems": False,
            "color_tier": "gray",
            "name_color": "",
            "user_number": None, "avatar_url": "",
        }
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
    }


def _member_dict(member: TeamMember) -> dict[str, Any]:
    return {
        "user_id": member.user_id,
        "role": member.role,
        "note": member.note or "",
        "joined_at": member.joined_at.isoformat() if member.joined_at else None,
        "user": _user_brief(member.user),
    }


def _team_dict(team: Team, member_count: int, current_user: User | None) -> dict[str, Any]:
    d = {
        "id": team.id,
        "name": team.name,
        "description": team.description or "",
        "owner": _user_brief(team.owner),
        "owner_id": team.owner_id,
        "member_count": member_count,
        "is_banned": bool(team.is_banned),
        "created_at": team.created_at.isoformat() if team.created_at else None,
    }
    if current_user is not None:
        d["is_owner"] = team.owner_id == current_user.id
        d["is_member"] = d["is_owner"] or any(
            m.user_id == current_user.id for m in team.members
        )
        d["is_team_admin"] = d["is_owner"] or any(
            m.user_id == current_user.id and m.role == "admin"
            for m in team.members
        )
    else:
        d.update({"is_owner": False, "is_member": False, "is_team_admin": False})
    return d


async def _load_team(db: AsyncSession, team_id: int) -> Optional[Team]:
    return (await db.execute(
        select(Team).where(Team.id == team_id)
    )).scalar_one_or_none()


async def _member_count(db: AsyncSession, team_id: int) -> int:
    return (await db.execute(
        select(sa_func.count()).select_from(TeamMember)
        .where(TeamMember.team_id == team_id)
    )).scalar() or 0


def _require_team_active(team: Team) -> None:
    """被封禁团队禁止发帖/加入/创建题目等操作。"""
    if team.is_banned:
        raise HTTPException(status_code=403, detail="该团队已被封禁，无法进行此操作")


async def _require_team_manage(
    db: AsyncSession, team: Team, user: User
) -> None:
    """校验当前用户可管理该团队（owner 或团队管理员）。"""
    if team.owner_id == user.id:
        return
    self_row = (await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team.id,
            TeamMember.user_id == user.id,
            TeamMember.role == "admin",
        )
    )).scalar_one_or_none()
    if self_row is None:
        raise HTTPException(status_code=403, detail="需要团队管理权限")


def _notify(
    db: AsyncSession,
    user_id: int,
    content: str,
    actor_id: int | None = None,
    link: str | None = None,
) -> None:
    """发一条站内通知（type=team，进顶栏铃铛）。"""
    db.add(Notification(user_id=user_id, type="team", content=content,
                        actor_id=actor_id, link=link))


@router.get("", summary="团队列表")
async def list_teams(
    page: int = Query(0, ge=0),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> dict:
    total = (await db.execute(
        select(sa_func.count()).select_from(Team)
    )).scalar() or 0
    teams = (await db.execute(
        select(Team).order_by(Team.id.desc())
        .offset(page * page_size).limit(page_size)
    )).scalars().all()
    # 人数 = team_members 行数 + owner（owner 不在成员表，需手动计入）
    items = [
        _team_dict(t, await _member_count(db, t.id) + 1, current_user) for t in teams
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("", status_code=201, summary="创建团队")
async def create_team(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if current_user.is_banned:
        raise HTTPException(status_code=403, detail="你已被封禁，无法创建团队")
    name = (payload.get("name") or "").strip()
    description = (payload.get("description") or "").strip() or None
    if not name:
        raise HTTPException(status_code=400, detail="团队名称不能为空")
    if len(name) > 50:
        raise HTTPException(status_code=400, detail="团队名称过长（≤50 字）")
    if description and len(description) > 500:
        raise HTTPException(status_code=400, detail="团队简介过长（≤500 字）")

    my_count = (await db.execute(
        select(sa_func.count()).select_from(Team)
        .where(Team.owner_id == current_user.id)
    )).scalar() or 0
    # 解散即物理删除，不会计入现存数量
    limit = _team_create_limit(current_user)
    if limit is not None and my_count >= limit:
        raise HTTPException(status_code=400, detail=f"你最多可创建 {limit} 个团队（解散的不计入）")

    team = Team(name=name, description=description, owner_id=current_user.id)
    db.add(team)
    await db.commit()
    await db.refresh(team)
    # 创建者即首位成员（owner 不在成员表，人数按 1 计）
    return _team_dict(team, 1, current_user)


@router.get("/my/problems", summary="我所在团队的全部题目（T 系列）")
async def list_my_team_problems(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """当前用户所在（创建/加入）的所有团队的私有题汇总，按 T 编号倒序。"""
    from app.models.problem import Problem
    from app.services.problem import ProblemService

    member_team_ids = (await db.execute(
        select(TeamMember.team_id).where(TeamMember.user_id == current_user.id)
    )).scalars().all()
    owned_team_ids = (await db.execute(
        select(Team.id).where(Team.owner_id == current_user.id)
    )).scalars().all()
    team_ids = set(member_team_ids) | set(owned_team_ids)
    if not team_ids:
        return {"items": []}
    rows = (await db.execute(
        select(Problem, Team.name).join(Team, Problem.team_id == Team.id)
        .where(Problem.team_id.in_(team_ids))
        .order_by(Problem.t_no.desc())
    )).all()
    return {
        "items": [{**ProblemService._dict(p), "team_name": name} for p, name in rows]
    }


@router.get("/my/manageable", summary="我可管理的团队（团主/管理员，办赛下拉用）")
async def my_manageable_teams(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if current_user.is_super_admin:
        teams = (await db.execute(
            select(Team).order_by(Team.id.desc())
        )).scalars().all()
        return {"items": [{"id": t.id, "name": t.name, "is_owner": t.owner_id == current_user.id} for t in teams]}
    owned = (await db.execute(
        select(Team).where(Team.owner_id == current_user.id)
        .order_by(Team.id.desc())
    )).scalars().unique().all()
    admin_rows = (await db.execute(
        select(Team).join(TeamMember, TeamMember.team_id == Team.id).where(
            TeamMember.user_id == current_user.id,
            TeamMember.role == "admin")
        .order_by(Team.id.desc())
    )).scalars().unique().all()
    seen: set[int] = set()
    items = []
    for t in [*owned, *admin_rows]:
        if t.id in seen:
            continue
        seen.add(t.id)
        items.append({"id": t.id, "name": t.name, "is_owner": t.owner_id == current_user.id})
    return {"items": items}


async def _get_user_joined_teams(
    db: AsyncSession, target_user_id: int, current_user: Optional[User]
) -> dict:
    owned_teams = (await db.execute(
        select(Team)
        .options(selectinload(Team.members))
        .where(Team.owner_id == target_user_id)
        .order_by(Team.id.desc())
    )).scalars().all()

    member_rows = (await db.execute(
        select(TeamMember, Team)
        .options(selectinload(Team.members))
        .join(Team, Team.id == TeamMember.team_id)
        .where(TeamMember.user_id == target_user_id)
        .order_by(TeamMember.joined_at.desc())
    )).all()

    teams_map: dict[int, tuple[Team, str, Any]] = {}
    for t in owned_teams:
        teams_map[t.id] = (t, "owner", t.created_at)

    for tm, t in member_rows:
        if t.id not in teams_map:
            teams_map[t.id] = (t, tm.role, tm.joined_at)

    if not teams_map:
        return {"items": [], "total": 0}

    team_ids = list(teams_map.keys())
    count_rows = (await db.execute(
        select(TeamMember.team_id, sa_func.count(TeamMember.id))
        .where(TeamMember.team_id.in_(team_ids))
        .group_by(TeamMember.team_id)
    )).all()
    counts = {tid: c + 1 for tid, c in count_rows}

    sorted_teams = sorted(
        teams_map.values(),
        key=lambda x: x[2] if x[2] is not None else x[0].created_at,
        reverse=True
    )
    items = []
    for t, role, joined_at in sorted_teams:
        d = _team_dict(t, counts.get(t.id, 1), current_user)
        d["user_role"] = role
        d["joined_at"] = joined_at.isoformat() if joined_at else None
        if current_user is not None and current_user.id == target_user_id:
            d["is_owner"] = (role == "owner")
            d["is_team_admin"] = (role in ("owner", "admin"))
            d["is_member"] = True
        items.append(d)

    return {"items": items, "total": len(items)}


@router.get("/my", summary="我加入/创建的团队列表")
async def my_joined_teams(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return await _get_user_joined_teams(db, current_user.id, current_user)


@router.get("/user/{user_id}", summary="指定用户加入/创建的团队列表")
async def get_user_teams(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> dict:
    return await _get_user_joined_teams(db, user_id, current_user)



@router.get("/{team_id}/problems", summary="团队私有题库（成员可见）")
async def list_team_problems(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> list[dict]:
    from app.models.problem import Problem
    from app.services.problem import ProblemService
    from app.services.contest import (
        is_team_organizing_shielded_contest,
        get_shielded_contest_for_problem,
        get_unstarted_contest_for_problem,
    )

    team = await _load_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    # 真实团队成员判定（团主 / 团队成员）
    is_real_member = False
    if current_user is not None:
        if team.owner_id == current_user.id:
            is_real_member = True
        else:
            is_real_member = (await db.execute(
                select(TeamMember.id).where(
                    TeamMember.team_id == team_id,
                    TeamMember.user_id == current_user.id)
            )).scalar_one_or_none() is not None

    # 团队私有题仅成员（及团队管理员）可见；管理员另有题目管理权限
    # 若该团队正在举办开启了管理员参赛保护的比赛，非举办方管理员不得以团队成员身份穿透私有题库
    is_member = is_real_member
    if not is_member and current_user is not None:
        if current_user.can_manage_problems or current_user.is_super_admin:
            if not await is_team_organizing_shielded_contest(db, team_id, current_user):
                is_member = True

    if not is_member:
        rows = (await db.execute(
            select(Problem).where(Problem.team_id == team_id, Problem.is_public == True)
            .order_by(Problem.t_no.asc())
        )).scalars().all()
    else:
        rows = (await db.execute(
            select(Problem).where(Problem.team_id == team_id)
            .order_by(Problem.t_no.asc())
        )).scalars().all()

    visible_problems = []
    for p in rows:
        # 1. 尚未开赛的比赛题目，非举办方不可在团队列表中提前看到（防止赛前看题）
        if await get_unstarted_contest_for_problem(db, p.id, current_user) is not None:
            continue
        # 2. 受保护的未结束比赛题目，非举办方在非真实团队成员时不可见
        if not is_real_member:
            if await get_shielded_contest_for_problem(db, p.id, current_user) is not None:
                continue
        visible_problems.append(p)

    return [ProblemService._dict(p) for p in visible_problems]


@router.get("/{team_id}", summary="团队详情")
async def team_detail(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> dict:
    team = await _load_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    members = (await db.execute(
        select(TeamMember).where(TeamMember.team_id == team_id)
        .order_by(TeamMember.id)
    )).scalars().all()
    # 人数 = 成员行数 + owner（与下方 members 列表拼入 owner 保持一致）
    d = _team_dict(team, len(members) + 1, current_user)
    # 成员列表：owner 拼在最前（role='owner'），其余按加入顺序
    d["members"] = [{
        "user_id": team.owner_id,
        "role": "owner",
        "note": "",
        "joined_at": d["created_at"],
        "user": d["owner"],
    }] + [_member_dict(m) for m in members]
    # 加入申请：待审核数量（管理员侧徽标）与当前用户的申请状态
    pending_rows = (await db.execute(
        select(TeamJoinRequest).where(TeamJoinRequest.team_id == team_id)
        .order_by(TeamJoinRequest.id)
    )).scalars().all()
    d["pending_count"] = len(pending_rows)
    d["is_pending"] = current_user is not None and any(
        r.user_id == current_user.id for r in pending_rows
    )
    return d


@router.put("/{team_id}", summary="更新团队概览（团主 / 团队管理员）")
async def update_team(
    team_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """更新团队概览（名称 / 简介）。

    权限：团主与团队管理员（role='admin'）可编辑；被封禁团队禁止编辑。
    只更新 payload 中显式出现的字段，未出现的保持原值。
    """
    team = await _load_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    await _require_team_manage(db, team, current_user)
    _require_team_active(team)

    if "name" in payload:
        name = (payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="团队名称不能为空")
        if len(name) > 50:
            raise HTTPException(status_code=400, detail="团队名称过长（≤50 字）")
        team.name = name
    if "description" in payload:
        description = (payload.get("description") or "").strip() or None
        if description and len(description) > 500:
            raise HTTPException(status_code=400, detail="团队简介过长（≤500 字）")
        team.description = description

    team.updated_at = datetime.now(UTC)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    # 不 refresh：expire_on_commit=False 下属性仍在；refresh 会 expire 关系属性，
    # 之后访问 team.members 会在异步上下文外触发懒加载（MissingGreenlet）。
    member_count = await _member_count(db, team_id) + 1
    return _team_dict(team, member_count, current_user)


@router.post("/{team_id}/join", summary="申请加入团队（需管理员审核）")
async def join_team(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if current_user.is_banned:
        raise HTTPException(status_code=403, detail="你已被封禁，无法加入团队")
    team = await _load_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    _require_team_active(team)
    if team.owner_id == current_user.id:
        raise HTTPException(status_code=400, detail="你是团队主，无需加入")
    exists = (await db.execute(
        select(TeamMember.id).where(
            TeamMember.team_id == team_id, TeamMember.user_id == current_user.id)
    )).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=400, detail="你已经是团队成员")
    count = await _member_count(db, team_id)
    if count + 1 > MAX_MEMBERS_PER_TEAM:
        raise HTTPException(status_code=400, detail=f"团队成员已达上限（{MAX_MEMBERS_PER_TEAM} 人）")
    # 加入需审核：已有待审申请则不重复提交
    pending = (await db.execute(
        select(TeamJoinRequest.id).where(
            TeamJoinRequest.team_id == team_id,
            TeamJoinRequest.user_id == current_user.id)
    )).scalar_one_or_none()
    if pending is not None:
        raise HTTPException(status_code=400, detail="已提交申请，等待审核中")
    db.add(TeamJoinRequest(team_id=team_id, user_id=current_user.id))

    # 通知团队主与所有团队管理员
    content = (f"{current_user.username} 申请加入团队「{team.name}」，"
               f"请前往团队页审核")
    admins = (await db.execute(
        select(TeamMember.user_id).where(
            TeamMember.team_id == team_id, TeamMember.role == "admin")
    )).scalars().all()
    _notify(db, team.owner_id, content, actor_id=current_user.id)
    for admin_id in admins:
        _notify(db, admin_id, content, actor_id=current_user.id)
    await db.commit()
    return {"pending": True}


@router.post("/{team_id}/leave", summary="退出团队")
async def leave_team(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    team = await _load_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    if team.owner_id == current_user.id:
        raise HTTPException(status_code=400, detail="团队主不能退出，如需退出请先解散团队")
    row = (await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id, TeamMember.user_id == current_user.id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=400, detail="你还不是团队成员")
    await db.delete(row)
    await db.commit()
    return {"success": True}


@router.post("/{team_id}/transfer/{user_id}", summary="转让团队（仅团主）")
async def transfer_team(
    team_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """把团队所有权转给指定成员。

    数据模型约束：owner 不在 team_members 表（成员列表渲染时拼入），
    因此转让 = 新团主从成员表移出 + 原团主以普通成员身份写入成员表。
    """
    team = await _load_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    if team.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="仅团队主可以转让团队")
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能转让给自己")
    target = (await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id, TeamMember.user_id == user_id)
    )).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=400, detail="对方不是团队成员")

    old_owner_id = team.owner_id
    team.owner_id = user_id
    # 新团主移出成员表（owner 不在成员表）；原团主降为普通成员
    await db.delete(target)
    db.add(TeamMember(team_id=team_id, user_id=old_owner_id, role="member"))
    _notify(db, user_id,
            f"{current_user.username} 已将团队「{team.name}」转让给你，你现在是团队主",
            actor_id=current_user.id)
    await db.commit()
    return {"success": True}


@router.delete("/{team_id}", summary="解散团队")
async def dissolve_team(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    team = await _load_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    if team.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="仅团队主可以解散团队")
    await db.delete(team)
    await db.commit()
    return {"success": True}


@router.get("/{team_id}/requests", summary="待审核申请列表（团队管理员）")
async def list_requests(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    team = await _load_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    await _require_team_manage(db, team, current_user)
    rows = (await db.execute(
        select(TeamJoinRequest).where(TeamJoinRequest.team_id == team_id)
        .order_by(TeamJoinRequest.id)
    )).scalars().all()
    return {
        "items": [{
            "user_id": r.user_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "user": _user_brief(r.user),
        } for r in rows]
    }


@router.post("/{team_id}/requests/{user_id}/approve", summary="通过加入申请")
async def approve_request(
    team_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    team = await _load_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    await _require_team_manage(db, team, current_user)
    req = (await db.execute(
        select(TeamJoinRequest).where(
            TeamJoinRequest.team_id == team_id, TeamJoinRequest.user_id == user_id)
    )).scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=404, detail="该申请不存在或已处理")
    _require_team_active(team)
    # 申请人在等待审核期间被封禁：拒绝入团并清掉申请
    applicant = await db.get(User, user_id)
    if applicant is None or applicant.is_banned:
        await db.delete(req)
        await db.commit()
        raise HTTPException(status_code=403, detail="该用户已被封禁，无法加入团队")
    count = await _member_count(db, team_id)
    if count + 1 > MAX_MEMBERS_PER_TEAM:
        raise HTTPException(status_code=400, detail=f"团队成员已达上限（{MAX_MEMBERS_PER_TEAM} 人）")
    db.add(TeamMember(team_id=team_id, user_id=user_id))
    await db.delete(req)
    _notify(db, user_id,
            f"你申请加入团队「{team.name}」已通过，欢迎加入！",
            actor_id=current_user.id)
    await db.commit()
    return {"success": True}


@router.post("/{team_id}/requests/{user_id}/reject", summary="拒绝加入申请")
async def reject_request(
    team_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    team = await _load_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    await _require_team_manage(db, team, current_user)
    req = (await db.execute(
        select(TeamJoinRequest).where(
            TeamJoinRequest.team_id == team_id, TeamJoinRequest.user_id == user_id)
    )).scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=404, detail="该申请不存在或已处理")
    await db.delete(req)
    _notify(db, user_id,
            f"你申请加入团队「{team.name}」未通过",
            actor_id=current_user.id)
    await db.commit()
    return {"success": True}


@router.put("/{team_id}/members/{user_id}", summary="管理成员（备注 / 设或撤管理员）")
async def update_member(
    team_id: int,
    user_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    team = await _load_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    await _require_team_manage(db, team, current_user)

    member = (await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id, TeamMember.user_id == user_id)
    )).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="该用户不是团队成员")

    new_role = payload.get("role")
    if new_role is not None and new_role != member.role:
        # 设/撤团队管理员是团主专属权限（管理员只能改备注、踢人）
        if team.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="仅团队主可以设置团队管理员")
        if new_role not in ("member", "admin"):
            raise HTTPException(status_code=400, detail="无效的角色")
        member.role = new_role
    if "note" in payload:
        note = (payload["note"] or "").strip()
        if len(note) > 50:
            raise HTTPException(status_code=400, detail="备注名过长（≤50 字）")
        member.note = note or None
    await db.commit()
    return _member_dict(member)


@router.delete("/{team_id}/members/{user_id}", summary="移除成员")
async def remove_member(
    team_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    team = await _load_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    await _require_team_manage(db, team, current_user)
    member = (await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id, TeamMember.user_id == user_id)
    )).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="该用户不是团队成员")
    await db.delete(member)
    await db.commit()
    return {"success": True}


def _team_post_dict(post: TeamPost, reply_count: int = 0) -> dict[str, Any]:
    return {
        "id": post.id,
        "team_id": post.team_id,
        "title": post.title,
        "content": post.content,
        "is_pinned": bool(post.is_pinned),
        "is_locked": bool(post.is_locked),
        "created_at": post.created_at.isoformat() if post.created_at else None,
        "updated_at": post.updated_at.isoformat() if post.updated_at else None,
        "author": _user_brief(post.author),
        "reply_count": reply_count,
    }


def _team_comment_dict(comment: TeamPostComment) -> dict[str, Any]:
    return {
        "id": comment.id,
        "post_id": comment.post_id,
        "content": comment.content,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
        "updated_at": comment.updated_at.isoformat() if comment.updated_at else None,
        "author": _user_brief(comment.author),
    }


async def _is_team_member(db: AsyncSession, team: Team, user: User) -> bool:
    if team.owner_id == user.id:
        return True
    return bool((await db.execute(
        select(TeamMember.id).where(
            TeamMember.team_id == team.id,
            TeamMember.user_id == user.id,
        )
    )).scalar_one_or_none())


async def _is_team_admin(db: AsyncSession, team: Team, user: User) -> bool:
    if team.owner_id == user.id:
        return True
    return bool((await db.execute(
        select(TeamMember.id).where(
            TeamMember.team_id == team.id,
            TeamMember.user_id == user.id,
            TeamMember.role == "admin",
        )
    )).scalar_one_or_none())


@router.get("/{team_id}/posts", summary="团队讨论列表")
async def list_team_posts(
    team_id: int,
    page: int = Query(0, ge=0),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    team = await _load_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    if not await _is_team_member(db, team, current_user):
        raise HTTPException(status_code=403, detail="需要团队成员身份")

    total = (await db.execute(
        select(sa_func.count()).select_from(TeamPost)
        .where(TeamPost.team_id == team_id)
    )).scalar() or 0

    posts = (await db.execute(
        select(TeamPost)
        .options(selectinload(TeamPost.author))
        .where(TeamPost.team_id == team_id)
        .order_by(TeamPost.is_pinned.desc(), TeamPost.created_at.desc())
        .offset(page * page_size).limit(page_size)
    )).scalars().all()

    post_ids = [p.id for p in posts]
    counts: dict[int, int] = {}
    if post_ids:
        rows = (await db.execute(
            select(TeamPostComment.post_id, sa_func.count(TeamPostComment.id))
            .where(TeamPostComment.post_id.in_(post_ids))
            .group_by(TeamPostComment.post_id)
        )).all()
        counts = {pid: cnt for pid, cnt in rows}

    return {
        "total": total,
        "items": [_team_post_dict(p, counts.get(p.id, 0)) for p in posts],
    }


@router.post("/{team_id}/posts", summary="创建团队讨论")
async def create_team_post(
    team_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if current_user.is_banned:
        raise HTTPException(status_code=403, detail="你已被封禁，无法发帖")
    team = await _load_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    _require_team_active(team)
    if not await _is_team_member(db, team, current_user):
        raise HTTPException(status_code=403, detail="需要团队成员身份")

    title = (payload.get("title") or "").strip()
    content = (payload.get("content") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    if len(title) > 100:
        raise HTTPException(status_code=400, detail="标题过长（≤100 字）")
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    if len(content) > 20000:
        raise HTTPException(status_code=400, detail="内容过长（≤20000 字）")

    post = TeamPost(
        team_id=team_id,
        author_id=current_user.id,
        title=title,
        content=content,
    )
    db.add(post)
    await db.flush()

    link = f"/teams/{team.id}?tab=讨论&post={post.id}"
    title_clipped = clip(title, TITLE_MAX)
    # ── 广播：新帖子铃铛，发给团队全体成员（作者除外）
    # owner 不在 team_members 表，需要连同成员一起收集
    member_ids = set((await db.execute(
        select(TeamMember.user_id).where(TeamMember.team_id == team_id)
    )).scalars().all())
    member_ids.add(team.owner_id)
    for uid in member_ids:
        if uid == current_user.id:
            continue
        _notify(
            db, uid,
            f"@{current_user.username} 在团队「{team.name}」发起了新讨论「{title_clipped}」",
            actor_id=current_user.id,
            link=link,
        )
    await notify_mentions(
        db, post.content, actor=current_user, link=link,
        where=f"团队「{team.name}」讨论「{title_clipped}」",
        allowed_user_ids=member_ids,
    )
    await db.commit()
    await db.refresh(post)
    return _team_post_dict(post, 0)


@router.get("/{team_id}/posts/{post_id}", summary="获取团队讨论")
async def get_team_post(
    team_id: int,
    post_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    team = await _load_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    if not await _is_team_member(db, team, current_user):
        raise HTTPException(status_code=403, detail="需要团队成员身份")

    post = (await db.execute(
        select(TeamPost)
        .options(
            selectinload(TeamPost.author),
            selectinload(TeamPost.comments).selectinload(TeamPostComment.author),
        )
        .where(TeamPost.id == post_id, TeamPost.team_id == team_id)
    )).scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=404, detail="讨论不存在")

    d = _team_post_dict(post, len(post.comments))
    d["comments"] = [_team_comment_dict(c) for c in post.comments]
    return d


@router.put("/{team_id}/posts/{post_id}", summary="修改团队讨论")
async def update_team_post(
    team_id: int,
    post_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    team = await _load_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    post = (await db.execute(
        select(TeamPost).where(TeamPost.id == post_id, TeamPost.team_id == team_id)
    )).scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=404, detail="讨论不存在")

    if post.author_id != current_user.id and not await _is_team_admin(db, team, current_user):
        raise HTTPException(status_code=403, detail="无权修改该讨论")

    title = (payload.get("title") or "").strip()
    content = (payload.get("content") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    if len(title) > 100:
        raise HTTPException(status_code=400, detail="标题过长（≤100 字）")
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    if len(content) > 20000:
        raise HTTPException(status_code=400, detail="内容过长（≤20000 字）")

    post.title = title
    post.content = content
    await db.commit()
    await db.refresh(post)
    return _team_post_dict(post)


@router.delete("/{team_id}/posts/{post_id}", summary="删除团队讨论")
async def delete_team_post(
    team_id: int,
    post_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    team = await _load_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    post = (await db.execute(
        select(TeamPost).where(TeamPost.id == post_id, TeamPost.team_id == team_id)
    )).scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=404, detail="讨论不存在")

    if post.author_id != current_user.id and not await _is_team_admin(db, team, current_user):
        raise HTTPException(status_code=403, detail="无权删除该讨论")

    await db.delete(post)
    await db.commit()
    return {"success": True}


@router.post("/{team_id}/posts/{post_id}/comments", summary="发表讨论回复")
async def create_team_comment(
    team_id: int,
    post_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if current_user.is_banned:
        raise HTTPException(status_code=403, detail="你已被封禁，无法回复")
    team = await _load_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    _require_team_active(team)
    if not await _is_team_member(db, team, current_user):
        raise HTTPException(status_code=403, detail="需要团队成员身份")

    post = (await db.execute(
        select(TeamPost).where(TeamPost.id == post_id, TeamPost.team_id == team_id)
    )).scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=404, detail="讨论不存在")

    if post.is_locked and not await _is_team_admin(db, team, current_user):
        raise HTTPException(status_code=403, detail="该讨论已被锁定，禁止回复")

    content = (payload.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="回复内容不能为空")
    if len(content) > 10000:
        raise HTTPException(status_code=400, detail="回复内容过长（≤10000 字）")

    comment = TeamPostComment(
        post_id=post_id,
        author_id=current_user.id,
        content=content,
    )
    db.add(comment)
    await db.flush()

    link = f"/teams/{team.id}?tab=讨论&post={post.id}"
    title_clipped = clip(post.title, TITLE_MAX)
    if post.author_id != current_user.id:
        add_notification(
            db,
            user_id=post.author_id,
            ntype="reply",
            actor_id=current_user.id,
            link=link,
            content=f"@{current_user.username} 回复了你在团队「{team.name}」中的讨论「{title_clipped}」",
        )
    member_ids = set((await db.execute(
        select(TeamMember.user_id).where(TeamMember.team_id == team_id)
    )).scalars().all())
    member_ids.add(team.owner_id)
    await notify_mentions(
        db, comment.content, actor=current_user, link=link,
        where=f"团队「{team.name}」讨论「{title_clipped}」",
        allowed_user_ids=member_ids,
    )

    await db.commit()
    await db.refresh(comment)
    return _team_comment_dict(comment)


@router.delete("/{team_id}/posts/{post_id}/comments/{comment_id}", summary="删除讨论回复")
async def delete_team_comment(
    team_id: int,
    post_id: int,
    comment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    team = await _load_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    comment = (await db.execute(
        select(TeamPostComment).where(
            TeamPostComment.id == comment_id,
            TeamPostComment.post_id == post_id,
        )
    )).scalar_one_or_none()
    if comment is None:
        raise HTTPException(status_code=404, detail="回复不存在")

    if comment.author_id != current_user.id and not await _is_team_admin(db, team, current_user):
        raise HTTPException(status_code=403, detail="无权删除该回复")

    await db.delete(comment)
    await db.commit()
    return {"success": True}


@router.post("/{team_id}/posts/{post_id}/pin", summary="置顶团队讨论")
async def toggle_pin_team_post(
    team_id: int,
    post_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    team = await _load_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    if not await _is_team_admin(db, team, current_user):
        raise HTTPException(status_code=403, detail="需要团队管理权限")

    post = (await db.execute(
        select(TeamPost).where(TeamPost.id == post_id, TeamPost.team_id == team_id)
    )).scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=404, detail="讨论不存在")

    post.is_pinned = not post.is_pinned
    await db.commit()
    return {"is_pinned": post.is_pinned}


@router.post("/{team_id}/posts/{post_id}/lock", summary="锁定团队讨论")
async def toggle_lock_team_post(
    team_id: int,
    post_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    team = await _load_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    if not await _is_team_admin(db, team, current_user):
        raise HTTPException(status_code=403, detail="需要团队管理权限")

    post = (await db.execute(
        select(TeamPost).where(TeamPost.id == post_id, TeamPost.team_id == team_id)
    )).scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=404, detail="讨论不存在")

    post.is_locked = not post.is_locked
    await db.commit()
    return {"is_locked": post.is_locked}
