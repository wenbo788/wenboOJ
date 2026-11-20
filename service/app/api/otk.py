"""otk-remote 协议服务端（协议规范：otk-remote 协议 v1）。

otk（OierToolKit）是纯客户端：拉题 / 提交 / 轮询结果，三个端点挂
``/otk/v1`` 命名空间，与 OJ 自身 ``/api`` / ``/problems`` 路由隔离；
错误统一 ``{"error": "..."}`` 格式（客户端优先展示该字段，由 main.py
注册的 ``OTKError`` handler 负责打包）。

安全口径（与网页端一致或更严）：

- **认证**：三个端点都要求 ``Authorization: Bearer <access token>``
  （客户端用 ``OTK_TOKEN`` 环境变量或 ``otk config remote_token`` 提供）；
- **题目可见性 / 可提交性**与网页题面、网页提交完全同一套判断（复用
  ``problems.resolve_problem_by_code`` 与 submissions 的守卫——比赛题
  在未结束比赛里一律拒绝，防止 otk 成为绕过比赛守卫的旁路）；
- **提交查询只允许本人**（防枚举他人提交，也防把编译输出当测试数据
  oracle）；
- **detail 泄露面**：协议的 ``detail`` / ``test_points[].detail`` 只在
  CE 时返回编译器输出（协议明文允许——编译错误不涉及测试数据），
  WA / TLE / RE 等一律返回空串——逐点对比信息（期望输出等）不出站，
  防止用远端接口逆推测试数据；
- 提交与网页端落同一张 submissions 表、同一条评测管线，**otk 提交在
  网页提交列表/详情天然可见**（协议响应不带 code，测试数据同样不经过
  远端通道）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.problems import resolve_problem_by_code
from app.api.submissions import (
    _aware,
    _can_manage,
    _require_team_member_for_problem,
    _unended_contests_for_problem,
)
from app.core.database import get_db
from app.core.security import decode_token
from app.models.problem import Problem, REVIEW_APPROVED
from app.models.submission import Submission, TestCase
from app.models.user import User
from app.services.contest import is_contest_organizer
from app.services.judge import LANGUAGES, judge_submission
from app.services.user import get_user_by_id
from app.utils.ratelimit import check

router = APIRouter(prefix="/otk/v1", tags=["otk"])

# 协议建议的源码上限
MAX_SOURCE_BYTES = 256 * 1024

# 本站状态 -> 协议 verdict。客户端按字符串比较（AC/WA/...），拿到的必须是
# 明确的两个进行态（Pending/Judging）或终态，未知状态一律归 SE——保证
# 客户端永远不会死轮询。
_VERDICT_MAP = {
    "pending": "Pending",
    "judging": "Judging",
    "accepted": "AC",
    "wrong_answer": "WA",
    "time_limit_exceeded": "TLE",
    "memory_limit_exceeded": "MLE",
    "runtime_error": "RE",
    "compile_error": "CE",
    "system_error": "SE",
    # 协议没有的站点状态：
    "cancelled": "SE",      # 成绩取消 = 终态，SE 让客户端停轮询
    "skipped": "Pending",   # 子任务剪枝没跑的点 = 未出结果（仅逐点出现）
}


class OTKError(Exception):
    """协议层错误：main.py 注册 handler，打包成 ``{"error": ...}`` JSON。

    FastAPI 的 HTTPException 统一回 ``{"detail": ...}``，而协议客户端优先
    读顶层 ``error`` 字段，所以 otk 通道的错误全部走这个异常。
    """

    def __init__(self, status_code: int, error: str):
        super().__init__(error)
        self.status_code = status_code
        self.error = error


async def _authenticate(request: Request, db: AsyncSession) -> User:
    """Bearer access token 认证（otk 端点专用：错误必须是 ``{"error"}`` 格式）。"""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer ") or not header[7:].strip():
        raise OTKError(
            401,
            "缺少访问令牌：OTK_TOKEN=<token> 或 otk config remote_token <token>",
        )
    try:
        payload = decode_token(header[7:].strip(), expected_type="access")
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        raise OTKError(401, "访问令牌无效或已过期，请重新登录获取")
    user = await get_user_by_id(db, user_id)
    if user is None:
        raise OTKError(401, "访问令牌无效或已过期，请重新登录获取")
    return user


async def _resolve_or_404(problem_id: str, db: AsyncSession, user: User) -> Problem:
    """复用网页题面的题号解析；不可见/不存在统一 404（防探测）。"""
    try:
        problem = await resolve_problem_by_code(db, problem_id, user)
    except HTTPException as exc:
        raise OTKError(exc.status_code, str(exc.detail))
    if problem is None:
        raise OTKError(404, "题目不存在")
    return problem


@router.get("/problems/{problem_id}", summary="获取题目（otk-remote）")
async def otk_get_problem(
    problem_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """拉题：题号（P1001 / U1001 / T10 / 数字 id）换题面基础信息。"""
    user = await _authenticate(request, db)
    problem = await _resolve_or_404(problem_id, db, user)
    samples = problem.samples or []
    return {
        "id": problem.problem_number,
        "title": problem.title or "",
        "time_limit_ms": int(problem.time_limit or 0),
        "memory_limit_mb": float(problem.memory_limit or 0),
        "samples": [
            {"input": str(s.get("input", "")), "output": str(s.get("output", ""))}
            for s in samples
            if isinstance(s, dict)
        ],
    }


class OtkSubmissionIn(BaseModel):
    problem: str = Field(min_length=1, max_length=64)
    language: str = Field(min_length=1, max_length=20)
    source: str = Field(min_length=1)


@router.post(
    "/submissions",
    status_code=status.HTTP_201_CREATED,
    summary="提交代码（otk-remote）",
)
async def otk_create_submission(
    payload: OtkSubmissionIn,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """提交代码：与网页提交同一张表、同一条评测管线（网页端天然可见）。

    校验口径与网页提交端点一致（可见性、团队成员、比赛题守卫、banned、
    限流共享同一桶）——otk 不能成为绕过比赛保护的旁路。otk 协议没有比赛
    上下文，等价于网页的 contest_id=None 通道。
    """
    user = await _authenticate(request, db)

    problem = await _resolve_or_404(payload.problem, db, user)

    # 语言白名单与评测器一致（协议示例 "cpp" 直接命中本站 C++）
    if payload.language not in LANGUAGES:
        raise OTKError(
            400,
            f"不支持的语言：{payload.language}（可选：{'/'.join(LANGUAGES)}）",
        )
    # 源码上限（协议建议 256KB）
    if len(payload.source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise OTKError(400, f"源码超过 {MAX_SOURCE_BYTES // 1024}KB 上限")

    # ---- 可提交校验（与网页提交端点同口径）----
    if problem.team_id is None:
        # 主题库题：公开 + 已审核才对所有人开放，否则仅出题人 / 题目管理员
        if not (problem.is_public and problem.review_status == REVIEW_APPROVED) \
                and not _can_manage(user) \
                and problem.author_id != user.id:
            raise OTKError(404, "题目不存在")
    else:
        # 团队私有题仅成员可提交（otk 通道不带 contest_id）
        try:
            await _require_team_member_for_problem(db, problem, user, contest_id=None)
        except HTTPException as exc:
            raise OTKError(exc.status_code, str(exc.detail))

    # 比赛题守卫：未结束比赛里的题一律拒绝（豁免口径同网页——出题人 /
    # 题目管理员 / 比赛创建者），防止赛前赛中借 otk 反复提交探测测试数据
    unended = await _unended_contests_for_problem(db, problem.id)
    if unended:
        is_shielded = any(
            getattr(c, "hide_submissions_from_admin", False)
            and not await is_contest_organizer(db, c, user)
            for c in unended
        )
        exempt = not is_shielded and (
            _can_manage(user)
            or (problem.author_id is not None and problem.author_id == user.id)
            or any(c.owner_id == user.id for c in unended)
        )
        if not exempt:
            # 文案与网页 contest_id=None 通道一致（进行中 / 未开始区分）
            now = datetime.now(timezone.utc)
            running = False
            for c in unended:
                st, en = _aware(c.start_time), _aware(c.end_time)
                if st and en and st <= now <= en:
                    running = True
                    break
            raise OTKError(
                400,
                "该题正在进行比赛，请从比赛页面提交"
                if running else "该题为比赛题目，比赛开始后才能提交",
            )

    if user.is_banned:
        raise OTKError(403, "被封禁用户不能提交评测")

    case_count = (await db.execute(
        select(sa_func.count()).select_from(TestCase).where(
            TestCase.problem_id == problem.id
        )
    )).scalar() or 0
    if case_count == 0:
        raise OTKError(400, "该题目暂无测试数据，无法提交评测")

    # 与网页端共享同一限流桶（同 user_number）：5 分钟 6 次
    ok, wait = check(f"submit:{user.user_number}", 6, 300)
    if not ok:
        raise OTKError(429, f"提交太频繁，请 {wait} 秒后再试")

    sub = Submission(
        problem_id=problem.id,
        user_id=user.id,
        code=payload.source,
        language=payload.language,
        status="pending",
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)

    background_tasks.add_task(judge_submission, sub.id)
    return {"id": str(sub.id)}


@router.get("/submissions/{submission_id}", summary="查询提交（otk-remote）")
async def otk_get_submission(
    submission_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """轮询提交结果：verdict / 逐点结果；只允许查询本人的提交。"""
    user = await _authenticate(request, db)

    if not submission_id.isdigit():
        raise OTKError(404, "提交不存在")
    sub = (await db.execute(
        select(Submission).where(Submission.id == int(submission_id))
    )).scalar_one_or_none()
    if sub is None or sub.user_id != user.id:
        raise OTKError(404, "提交不存在")

    verdict = _VERDICT_MAP.get(sub.status, "SE")
    if sub.status in ("pending", "judging"):
        # 协议：Pending / Judging 时其余字段可省略——客户端只认 verdict
        return {"id": str(sub.id), "verdict": verdict}

    # detail 政策：仅 CE 返回编译器输出（协议明文；编译错误不涉及测试数据）；
    # WA / TLE / RE 等一律空——逐点对比与错误信息不走远端通道，防止用提交
    # 接口当测试数据 oracle。
    detail = (sub.error_message or "") if sub.status == "compile_error" else ""

    points: list[dict[str, Any]] = []
    for r in (sub.test_results or []):
        if not isinstance(r, dict):
            continue
        try:
            idx = int(r.get("case"))
        except (TypeError, ValueError):
            continue
        points.append({
            "index": idx,
            "verdict": _VERDICT_MAP.get(str(r.get("status", "")), "SE"),
            # 本站二值判题没有逐点分（协议：非计分 OJ 填 0）——不伪造分数
            "score": 0,
            "time_ms": int(r.get("time") or 0),
            "memory_kb": int(r.get("memory") or 0),
            "detail": "",
        })
    points.sort(key=lambda p: p["index"])

    return {
        "id": str(sub.id),
        "verdict": verdict,
        # 二值判题（AC=100 其余=0）按协议「非计分 OJ」处理：分数不下发，
        # 客户端不显示 x/y 分与逐点分，AC 与否看 verdict 即可
        "score": 0,
        "max_score": 0,
        "time_ms": int(sub.time_used or 0),
        "memory_kb": int(sub.memory_used or 0),
        "detail": detail,
        "test_points": points,
    }
