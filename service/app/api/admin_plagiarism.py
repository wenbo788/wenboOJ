"""管理后台：提交查重（疑似抄袭）榜单。

只出**提示**，不做任何自动判罚：管理员看完两边代码，再走既有的
「标记作弊者 / 取消成绩」流程。

权限统一走 ``perm.can_manage_problems``（白名单/超管/大管/题管）——
反作弊是题目/比赛侧的事，对应「管理名单」的题目管理列。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app import permissions as perm
from app.core.database import get_db
from app.deps import get_current_user
from app.models.plagiarism import SimilarSubmissionPair
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.user import User
from app.services import plagiarism as detector

router = APIRouter(prefix="/admin/plagiarism", tags=["admin"])


def _require_reviewer(user: User) -> None:
    if not perm.can_manage_problems(user):
        raise HTTPException(status_code=403, detail="需要题目管理权限")


def _brief_submission(sub: Submission | None) -> dict[str, Any] | None:
    if sub is None:
        return None
    return {
        "id": sub.id,
        "user_id": sub.user_id,
        "user_number": sub.user.user_number if sub.user else None,
        "username": sub.user.username if sub.user else None,
        "language": sub.language,
        "status": sub.status,
        "score": sub.score,
        "judged_at": sub.judged_at.isoformat() if sub.judged_at else None,
    }


@router.post("/scan", summary="扫描一个比赛/题目的提交查重（覆盖该范围的旧结果）")
async def scan(
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """跑一次查重。

    请求体：``{"contest_id": 12}`` 或 ``{"problem_id": 34}``，可选
    ``threshold``（默认 0.8，0.1~1.0）。同一范围重复扫描会覆盖旧结果
    —— 调小阈值后不会残留过期命中。
    """
    _require_reviewer(current_user)

    contest_id = payload.get("contest_id")
    problem_id = payload.get("problem_id")
    threshold = payload.get("threshold", detector.DEFAULT_THRESHOLD)
    if contest_id is None and problem_id is None:
        raise HTTPException(status_code=400, detail="请指定 contest_id 或 problem_id")
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="threshold 需为数字")

    try:
        result = await detector.scan_and_store(
            db,
            contest_id=int(contest_id) if contest_id is not None else None,
            problem_id=int(problem_id) if problem_id is not None else None,
            threshold=threshold,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"success": True, **result}


@router.get("", summary="疑似抄袭榜单（读缓存结果）")
async def list_pairs(
    contest_id: int | None = Query(None, description="按比赛过滤"),
    problem_id: int | None = Query(None, description="按题目过滤"),
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """列出已扫描出的疑似抄袭对（按相似度倒序）。

    只是提示：**没有任何处罚状态**，确认后请走题目/比赛后台的
    「标记作弊者」或成绩处理流程。
    """
    _require_reviewer(current_user)

    stmt = (
        select(SimilarSubmissionPair)
        .options(
            joinedload(SimilarSubmissionPair.submission_a).joinedload(Submission.user),
            joinedload(SimilarSubmissionPair.submission_b).joinedload(Submission.user),
            joinedload(SimilarSubmissionPair.problem),
        )
        .where(SimilarSubmissionPair.score >= min_score)
    )
    if contest_id is not None:
        stmt = stmt.where(SimilarSubmissionPair.contest_id == contest_id)
    if problem_id is not None:
        stmt = stmt.where(SimilarSubmissionPair.problem_id == problem_id)
    stmt = stmt.order_by(SimilarSubmissionPair.score.desc(), SimilarSubmissionPair.id)

    rows = (await db.execute(stmt.limit(limit))).scalars().all()

    items = []
    for row in rows:
        problem: Problem | None = row.problem
        items.append({
            "id": row.id,
            "score": round(row.score, 4),
            "contest_id": row.contest_id,
            "problem_id": row.problem_id,
            "problem_title": problem.title if problem else None,
            "a": _brief_submission(row.submission_a),
            "b": _brief_submission(row.submission_b),
            "detail": row.detail,
        })

    return {"items": items, "total": len(items)}


@router.get("/{pair_id}", summary="一对疑似抄袭的双方代码（人工确认用）")
async def pair_detail(
    pair_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """返回两边源码，供并排人工比对。

    刻意允许查看完整代码：反作弊必须看得见代码（比赛进行中也是 —— 否则只能
    赛后追认）。权限与扫描一致（题目管理），不额外放开给其它角色。
    """
    _require_reviewer(current_user)

    row = (await db.execute(
        select(SimilarSubmissionPair)
        .options(
            joinedload(SimilarSubmissionPair.submission_a).joinedload(Submission.user),
            joinedload(SimilarSubmissionPair.submission_b).joinedload(Submission.user),
            joinedload(SimilarSubmissionPair.problem),
        )
        .where(SimilarSubmissionPair.id == pair_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在")

    a, b = row.submission_a, row.submission_b
    return {
        "id": row.id,
        "score": round(row.score, 4),
        "problem_id": row.problem_id,
        "problem_title": row.problem.title if row.problem else None,
        "contest_id": row.contest_id,
        "detail": row.detail,
        "a": {**_brief_submission(a), "code": a.code if a else None},
        "b": {**_brief_submission(b), "code": b.code if b else None},
    }
