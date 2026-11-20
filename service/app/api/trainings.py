"""训练题单 API。

- 题单浏览：所有用户（含未登录）可浏览公开题单与精选推荐
- 题单创建：所有登录用户均可在个人中心「我的」或题单广场新建个人题单
- 题目添加：支持智能解析题号（P1001、T1001、1001、1 等多种输入习惯）
- 管理员推荐：超级管理员/管理员可推荐题单（is_featured），被推荐的题单展示在主页与精选推荐中
- 权限控制：拥有者可编辑/删除/加题，超级管理员与管理员拥有全局管理权限
- 同时暴露 /api/trainings 与 /api/training 兼容别名
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func as sa_func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.deps import get_current_user, get_current_user_optional
from app.models.problem import Problem, REVIEW_APPROVED
from app.models.submission import Submission
from app.models.training import TrainingPlan, TrainingProblem
from app.models.user import User
from app.services.problem import ProblemService

router = APIRouter(prefix="/trainings", tags=["trainings"])
alias_router = APIRouter(prefix="/training", tags=["trainings"])


def _is_admin(user: User | None) -> bool:
    if not user:
        return False
    return bool(user.is_super_admin or user.is_admin)


def _can_manage(training: TrainingPlan, user: User | None) -> bool:
    if not user:
        return False
    return bool(user.is_super_admin or user.is_admin or training.owner_id == user.id)


async def _get_training(db: AsyncSession, training_id: int) -> Optional[TrainingPlan]:
    return (await db.execute(
        select(TrainingPlan)
        .options(
            selectinload(TrainingPlan.owner),
            selectinload(TrainingPlan.problems).selectinload(TrainingProblem.problem),
        )
        .where(TrainingPlan.id == training_id)
    )).scalar_one_or_none()


async def _solved_counts(db: AsyncSession, user_id: int) -> dict[int, int]:
    """当前用户在每个题单里的完成题数：{training_id: solved_count}。"""
    rows = (await db.execute(
        select(
            TrainingProblem.training_id,
            sa_func.count(sa_func.distinct(TrainingProblem.problem_id)),
        )
        .join(Submission, (
            (Submission.problem_id == TrainingProblem.problem_id)
            & (Submission.user_id == user_id)
            & (Submission.status == "accepted")
        ))
        .group_by(TrainingProblem.training_id)
    )).all()
    return {tid: n for tid, n in rows}


async def _problem_counts(db: AsyncSession) -> dict[int, int]:
    """每个题单的题目总数：{training_id: problem_count}。"""
    rows = (await db.execute(
        select(TrainingProblem.training_id, sa_func.count())
        .group_by(TrainingProblem.training_id)
    )).all()
    return {tid: n for tid, n in rows}


def _training_dict(
    training: TrainingPlan,
    current_user: User | None,
    *,
    problem_count: int,
    solved_count: int = 0,
    with_problems: bool = False,
    status_map: dict[int, str] | None = None,
) -> dict[str, Any]:
    owner_info = {
        "id": training.owner_id,
        "user_id": training.owner_id,
        "username": training.owner.username if training.owner else "未知",
        "avatar_url": getattr(training.owner, "avatar_url", "") or "",
        "user_number": getattr(training.owner, "user_number", None),
        "user_tag": getattr(training.owner, "display_tag", ""),
        "display_tag": getattr(training.owner, "display_tag", ""),
        "username_color": getattr(training.owner, "username_color", ""),
        "color_tier": getattr(training.owner, "color_tier", "gray"),
        "name_color": getattr(training.owner, "name_color", ""),
        "is_admin": bool(getattr(training.owner, "is_admin", False)),
        "is_super_admin": bool(getattr(training.owner, "is_super_admin", False)),
    }

    d: dict[str, Any] = {
        "id": training.id,
        "title": training.title,
        "description": training.description or "",
        "is_featured": bool(training.is_featured),
        "is_public": bool(training.is_public),
        "is_official": bool(training.is_official),
        "scope": "official" if training.is_official else "user",
        "owner": owner_info,
        "author": owner_info,  # 兼容前端 author/owner 两种取值习惯
        "created_at": training.created_at.isoformat() if training.created_at else None,
        "updated_at": training.updated_at.isoformat() if training.updated_at else (training.created_at.isoformat() if training.created_at else None),
        "problem_count": problem_count,
        "solved_count": solved_count,
        "user_solved_count": solved_count,
        "can_edit": _can_manage(training, current_user),
        "can_feature": _is_admin(current_user),
        "is_super_admin": bool(current_user and current_user.is_super_admin),
        "is_admin": _is_admin(current_user),
    }

    if with_problems:
        problems = []
        for tp in training.problems:
            p = tp.problem
            if not p:
                continue
            acc = getattr(p, "accepted_count", 0)
            sub = getattr(p, "submission_count", 0)
            problems.append({
                "problem_id": p.id,
                "id": p.id,
                "sort_order": tp.sort_order,
                "problem_number": p.problem_number,
                "title": p.title,
                "difficulty": p.difficulty,
                "accepted_count": acc,
                "submission_count": sub,
                "solved_count": acc,
                "submit_count": sub,
                "my_status": (status_map or {}).get(p.id),
                "status": (status_map or {}).get(p.id),
            })
        d["problems"] = problems
    return d


async def _resolve_problem_by_code(db: AsyncSession, raw_code: str) -> Problem | None:
    """智能解析题号输入，支持 P1001、T1001、1001、1 等多种输入习惯。"""
    code = str(raw_code).strip()
    if not code:
        return None
    code_upper = code.upper()

    # 1. 团队题编号 T{t_no} 或 T{id}
    if code_upper.startswith("T") and code_upper[1:].isdigit():
        t_no = int(code_upper[1:])
        p = (await db.execute(select(Problem).where(Problem.t_no == t_no))).scalar_one_or_none()
        if p:
            return p
        p = await db.get(Problem, t_no)
        if p:
            return p

    # 2. 主题库 P / 用户题库 U：{1000 + id} 或 {id}
    if code_upper[:1] in ("P", "U") and code_upper[1:].isdigit():
        num = int(code_upper[1:])
        expect_official = code_upper.startswith("P")

        def _matches(p) -> bool:
            return (p is not None and p.team_id is None
                    and bool(p.is_official) == expect_official)

        if num >= 1000:
            p = await db.get(Problem, num - 1000)
            if _matches(p):
                return p
        p = await db.get(Problem, num)
        if _matches(p):
            return p

    # 3. 纯数字
    if code.isdigit():
        num = int(code)
        # 3.1 传统 1000 + id 风格 (例如 1001 -> id 1)
        if num >= 1000:
            p = await db.get(Problem, num - 1000)
            if p:
                return p
        # 3.2 直接作为 id
        p = await db.get(Problem, num)
        if p:
            return p
        # 3.3 匹配团队题全局编号 t_no
        p = (await db.execute(select(Problem).where(Problem.t_no == num))).scalar_one_or_none()
        if p:
            return p

    return None


async def _resolve_codes(db: AsyncSession, raw_codes: list) -> list[int]:
    """题号列表 → 题目 id 列表（保持顺序、去重）。仅接受公开且非私有团队题目。"""
    seen: set[int] = set()
    unique_ids: list[int] = []
    for raw in raw_codes:
        p = await _resolve_problem_by_code(db, str(raw))
        if (p is None or p.team_id is not None
                or not p.is_public or p.review_status != REVIEW_APPROVED):
            raise HTTPException(status_code=400, detail=f"题目 {raw} 不存在或不可用")
        if p.id in seen:
            continue
        seen.add(p.id)
        unique_ids.append(p.id)
    return unique_ids


@router.get("", summary="题单列表")
@alias_router.get("", summary="题单列表")
async def list_trainings(
    page: int = Query(0, ge=0, description="页码，支持 0 或 1 开始"),
    page_size: int = Query(50, ge=1, le=100),
    hide_completed: bool = Query(False, description="不显示已完成的题单"),
    featured_only: bool = Query(False, description="仅显示管理员推荐题单"),
    scope: Optional[str] = Query(None, description="official=官方题单(P, 管理员创建) / user=用户题单(U, 普通用户创建)"),
    owner_id: Optional[int] = Query(None, description="作者用户 ID 筛选"),
    author_id: Optional[int] = Query(None, description="作者用户 ID 筛选（别名）"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    search: Optional[str] = Query(None, description="关键词搜索（别名）"),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> dict:
    query = select(TrainingPlan).options(selectinload(TrainingPlan.owner))

    # 权限可见性：管理员看所有；普通用户仅看公开或自己创建的
    if not _is_admin(current_user):
        if current_user:
            query = query.where(or_(TrainingPlan.is_public.is_(True), TrainingPlan.owner_id == current_user.id))
        else:
            query = query.where(TrainingPlan.is_public.is_(True))

    if featured_only:
        query = query.where(TrainingPlan.is_featured.is_(True))

    # 官方题单(P) / 用户题单(U)：以落库的 is_official 为准，
    # 不再用 owner 的实时角色推导（撤权会导致历史题单归属漂移）。
    # 未传 scope 时不过滤，交由上面的可见性条件决定。
    if scope is not None and scope not in ("official", "user"):
        raise HTTPException(status_code=400, detail="scope 仅支持 official / user")
    if scope == "official":
        query = query.where(TrainingPlan.is_official.is_(True))
    elif scope == "user":
        query = query.where(TrainingPlan.is_official.is_(False))

    target_owner = owner_id if owner_id is not None else author_id
    if target_owner is not None:
        query = query.where(TrainingPlan.owner_id == target_owner)

    kw = (keyword or search or "").strip()
    if kw:
        query = query.where(
            or_(
                TrainingPlan.title.ilike(f"%{kw}%"),
                TrainingPlan.description.ilike(f"%{kw}%"),
            )
        )

    # 排序：推荐优先，后按 id 倒序
    query = query.order_by(TrainingPlan.is_featured.desc(), TrainingPlan.id.desc())

    trainings = (await db.execute(query)).scalars().unique().all()
    counts = await _problem_counts(db)
    solved = await _solved_counts(db, current_user.id) if current_user else {}

    items = []
    for t in trainings:
        p_count = counts.get(t.id, 0)
        s_count = solved.get(t.id, 0)
        if hide_completed and p_count > 0 and s_count >= p_count:
            continue
        items.append(_training_dict(
            t, current_user,
            problem_count=p_count,
            solved_count=s_count,
        ))

    total = len(items)
    # 兼容 0 开始与 1 开始的分页传参
    page_index = page if page == 0 else (page - 1)
    if page_index < 0:
        page_index = 0
    start = page_index * page_size
    items = items[start : start + page_size]

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("", status_code=status.HTTP_201_CREATED, summary="创建题单")
@alias_router.post("", status_code=status.HTTP_201_CREATED, summary="创建题单")
async def create_training(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="题单名称不能为空")
    if len(title) > 100:
        raise HTTPException(status_code=400, detail="题单名称不能超过100个字符")

    is_public = bool(payload.get("is_public", True))
    raw_codes = payload.get("problem_codes") or []
    problem_ids = await _resolve_codes(db, raw_codes) if raw_codes else []

    training = TrainingPlan(
        title=title,
        description=(payload.get("description") or "").strip() or None,
        is_public=is_public,
        is_featured=False,
        # 官方/用户题单归属在创建时一次性落库，之后不再随作者权限变化漂移
        is_official=bool(
            current_user.is_admin or current_user.is_super_admin
            or current_user.can_manage_problems
        ),
        owner_id=current_user.id,
    )
    db.add(training)
    await db.flush()

    for order, pid in enumerate(problem_ids):
        db.add(TrainingProblem(training_id=training.id, problem_id=pid, sort_order=order))

    await db.commit()
    await db.refresh(training)

    # 重新加载关联
    loaded = await _get_training(db, training.id)
    return _training_dict(
        loaded or training, current_user,
        with_problems=True,
        problem_count=len(problem_ids),
        solved_count=0,
        status_map={},
    )


@router.get("/{training_id}", summary="题单详情")
@alias_router.get("/{training_id}", summary="题单详情")
async def training_detail(
    training_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> dict:
    training = await _get_training(db, training_id)
    if training is None:
        raise HTTPException(status_code=404, detail="题单不存在")

    if not training.is_public and not _can_manage(training, current_user):
        raise HTTPException(status_code=403, detail="无权访问私有题单")

    problems = [tp.problem for tp in training.problems if tp.problem]
    status_map = await ProblemService.attach_user_status(db, problems, current_user.id) if current_user else {}
    solved_count = sum(1 for p in problems if status_map.get(p.id) == "accepted")

    return _training_dict(
        training, current_user,
        with_problems=True,
        problem_count=len(problems),
        solved_count=solved_count,
        status_map=status_map,
    )


@router.put("/{training_id}", summary="编辑题单")
@alias_router.put("/{training_id}", summary="编辑题单")
async def update_training(
    training_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    training = await _get_training(db, training_id)
    if training is None:
        raise HTTPException(status_code=404, detail="题单不存在")

    if not _can_manage(training, current_user):
        raise HTTPException(status_code=403, detail="无权编辑该题单")

    if "title" in payload:
        title = (payload.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="题单名称不能为空")
        training.title = title

    if "description" in payload:
        training.description = (payload.get("description") or "").strip() or None

    if "is_public" in payload:
        training.is_public = bool(payload["is_public"])

    if "problem_codes" in payload and payload["problem_codes"] is not None:
        problem_ids = await _resolve_codes(db, payload.get("problem_codes") or [])
        await db.execute(delete(TrainingProblem).where(TrainingProblem.training_id == training.id))
        await db.flush()
        for order, pid in enumerate(problem_ids):
            db.add(TrainingProblem(training_id=training.id, problem_id=pid, sort_order=order))

    await db.commit()
    await db.refresh(training)

    loaded = await _get_training(db, training.id)
    problems = [tp.problem for tp in (loaded or training).problems if tp.problem]
    status_map = await ProblemService.attach_user_status(db, problems, current_user.id) if current_user else {}
    solved_count = sum(1 for p in problems if status_map.get(p.id) == "accepted")

    return _training_dict(
        loaded or training, current_user,
        with_problems=True,
        problem_count=len(problems),
        solved_count=solved_count,
        status_map=status_map,
    )


@router.delete("/{training_id}", summary="删除题单")
@alias_router.delete("/{training_id}", summary="删除题单")
async def delete_training(
    training_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    training = await _get_training(db, training_id)
    if training is None:
        raise HTTPException(status_code=404, detail="题单不存在")

    if not _can_manage(training, current_user):
        raise HTTPException(status_code=403, detail="无权删除该题单")

    await db.delete(training)
    await db.commit()
    return {"success": True}


@router.post("/{training_id}/problems", summary="向题单添加题目")
@alias_router.post("/{training_id}/problems", summary="向题单添加题目")
async def add_problem_to_training(
    training_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    training = await _get_training(db, training_id)
    if training is None:
        raise HTTPException(status_code=404, detail="题单不存在")

    if not _can_manage(training, current_user):
        raise HTTPException(status_code=403, detail="无权操作该题单")

    raw_code = payload.get("problem_code") or payload.get("code") or payload.get("problem_id")
    if not raw_code:
        raise HTTPException(status_code=400, detail="请输入题号")

    problem = await _resolve_problem_by_code(db, str(raw_code))
    if (problem is None or problem.team_id is not None
            or not problem.is_public or problem.review_status != REVIEW_APPROVED):
        raise HTTPException(status_code=400, detail=f"题目 {raw_code} 不存在或不可用")

    # 查重
    existing = (await db.execute(
        select(TrainingProblem).where(
            TrainingProblem.training_id == training_id,
            TrainingProblem.problem_id == problem.id,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="该题目已在题单中")

    # 获取当前最大 sort_order
    max_order = (await db.execute(
        select(sa_func.coalesce(sa_func.max(TrainingProblem.sort_order), -1))
        .where(TrainingProblem.training_id == training_id)
    )).scalar_one()

    tp = TrainingProblem(
        training_id=training_id,
        problem_id=problem.id,
        sort_order=max_order + 1,
    )
    db.add(tp)
    await db.commit()

    return {
        "success": True,
        "problem_id": problem.id,
        "problem_number": problem.problem_number,
        "title": problem.title,
    }


@router.delete("/{training_id}/problems/{problem_id}", summary="从题单移除题目")
@alias_router.delete("/{training_id}/problems/{problem_id}", summary="从题单移除题目")
async def remove_problem_from_training(
    training_id: int,
    problem_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    training = await _get_training(db, training_id)
    if training is None:
        raise HTTPException(status_code=404, detail="题单不存在")

    if not _can_manage(training, current_user):
        raise HTTPException(status_code=403, detail="无权操作该题单")

    res = await db.execute(
        delete(TrainingProblem).where(
            TrainingProblem.training_id == training_id,
            TrainingProblem.problem_id == problem_id,
        )
    )
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail="题单中无此题目")

    await db.commit()
    return {"success": True}


@router.put("/{training_id}/feature", summary="管理员设置/取消推荐题单")
@router.patch("/{training_id}/feature", summary="管理员设置/取消推荐题单")
@alias_router.put("/{training_id}/feature", summary="管理员设置/取消推荐题单")
@alias_router.patch("/{training_id}/feature", summary="管理员设置/取消推荐题单")
async def feature_training(
    training_id: int,
    payload: Optional[dict] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="只有管理员可以推荐题单")

    training = await _get_training(db, training_id)
    if training is None:
        raise HTTPException(status_code=404, detail="题单不存在")

    if payload is not None and "is_featured" in payload:
        training.is_featured = bool(payload["is_featured"])
    else:
        training.is_featured = not training.is_featured

    await db.commit()
    await db.refresh(training)
    return {"success": True, "is_featured": training.is_featured}


@router.put("/{training_id}/problems/reorder", summary="调整题单题目顺序")
@alias_router.put("/{training_id}/problems/reorder", summary="调整题单题目顺序")
async def reorder_problems(
    training_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """按给定 problem_id 顺序重置 sort_order。

    payload: {"problem_ids": [1, 3, 2]} 表示题目 1 在前、3 居中、2 在后。
    必须传入题单内的全部题目 id，否则报错。
    """
    training = await _get_training(db, training_id)
    if training is None:
        raise HTTPException(status_code=404, detail="题单不存在")

    if not _can_manage(training, current_user):
        raise HTTPException(status_code=403, detail="无权操作该题单")

    raw_ids = payload.get("problem_ids") or []
    if not isinstance(raw_ids, list) or not raw_ids:
        raise HTTPException(status_code=400, detail="problem_ids 不能为空")

    # 当前题单题目 id 集合
    existing = {tp.problem_id: tp for tp in training.problems}
    if len(raw_ids) != len(existing):
        raise HTTPException(
            status_code=400,
            detail="problem_ids 必须包含题单内全部题目，且不能重复",
        )
    seen: set[int] = set()
    for pid in raw_ids:
        pid_int = int(pid)
        if pid_int not in existing:
            raise HTTPException(status_code=400, detail=f"题目 {pid} 不在题单中")
        if pid_int in seen:
            raise HTTPException(status_code=400, detail="problem_ids 不能重复")
        seen.add(pid_int)

    for order, pid in enumerate(raw_ids):
        tp = existing[int(pid)]
        tp.sort_order = order

    await db.commit()

    # 重新加载并返回完整题单（含题目与做题状态）
    loaded = await _get_training(db, training_id)
    problems = [tp.problem for tp in (loaded or training).problems if tp.problem]
    status_map = await ProblemService.attach_user_status(db, problems, current_user.id) if current_user else {}
    solved_count = sum(1 for p in problems if status_map.get(p.id) == "accepted")

    return _training_dict(
        loaded or training, current_user,
        with_problems=True,
        problem_count=len(problems),
        solved_count=solved_count,
        status_map=status_map,
    )
