"""题库 API。"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status,
)
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger("oj.problems")
from app import permissions as perm
from app.core.database import get_db
from app.deps import get_current_user
from app.models.contest import Contest, ContestParticipant, ContestProblem
from app.models.problem import (
    Problem,
    ProblemAttachment,
    REVIEW_APPROVED,
    REVIEW_DRAFT,
    REVIEW_PENDING,
    REVIEW_REJECTED,
    REVIEW_STATUSES,
)
from app.models.submission import TestCase
from app.models.team import Team, TeamMember
from app.models.user import User
from app.schemas.problem import (
    ProblemCreate,
    ProblemMarkdownParseRequest,
    ProblemMigrateRequest,
    ProblemReviewRequest,
    ProblemToggleSolutionRequest,
    ProblemTryRunRequest,
    ProblemUpdate,
)
from app.services.judge import (
    JudgeError,
    LANGUAGES,
    adjust_experience_on_difficulty_change,
    adjust_contribution_on_author_change,
    adjust_contribution_on_difficulty_change,
    try_run as sandbox_try_run,
)
from app.services.contest import (
    is_contest_organizer,
    get_shielded_contest_for_problem,
    is_team_organizing_shielded_contest,
)
from app.services.problem import ProblemService, attachment_dict
from app.services.problem_markdown import parse_problem_markdown
from app.services.problem_zip import parse_problem_zip
from app.utils.ratelimit import check
from sqlalchemy import delete, func as sa_func, select
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/problems", tags=["problems"])

# 题目附件：单文件上限 16MB；扩展名黑名单拦可执行文件，其余放行
# 落盘在 /storage/private/problem_attachments（不暴露在 /static），
# 必须走 GET /problems/{id}/attachments/{aid}/download 带可见性鉴权才能取。
_MAX_ATTACHMENT_SIZE = 16 * 1024 * 1024
_FORBIDDEN_ATTACHMENT_EXT = {
    ".exe", ".bat", ".cmd", ".sh", ".msi", ".dll", ".so", ".jar", ".apk", ".ps1",
}


def _sanitize_filename(name: str) -> str:
    """清洗用户上传的文件名，保证 Content-Disposition 安全。

    去掉引号/换行/回车（header 注入与解析错误源）及控制字符，
    再掐头去尾空白，兜底为「附件」。
    """
    cleaned = re.sub(r'["\r\n\\\x00-\x1f\x7f]', "_", name)
    cleaned = cleaned.strip().strip(".")
    return cleaned or "附件"


# 可在浏览器中直接执行脚本的 MIME 类型，一律禁止作为下载响应类型
_UNSAFE_MIME_PREFIXES = ("text/", "image/svg", "application/xhtml")
_UNSAFE_MIME_TYPES = {
    "text/html", "text/plain", "text/xml",
    "image/svg+xml", "application/xhtml+xml", "application/xml",
}


def _safe_download_media_type(content_type: str | None) -> str:
    """下载出口的 MIME 兜底：非白名单式安全类型降级为 octet-stream。

    上传时 content_type 来自客户端请求头，可被伪造为可执行脚本的类型。
    统一降级强制浏览器按二进制下载处理，消除 XSS 向量。
    """
    ct = (content_type or "").split(";")[0].strip().lower()
    if not ct or ct in _UNSAFE_MIME_TYPES or ct.startswith(_UNSAFE_MIME_PREFIXES):
        return "application/octet-stream"
    return ct


def _resolve_attachment_root() -> Path:
    """附件落盘根目录。

    以 settings.ATTACHMENT_STORAGE_ROOT 为准：绝对路径直接使用；
    相对路径按「仓库根 / 该路径」解析（与仓库内storage/ 的既有布局一致），
    不再依赖 __file__ 层级推算，避免容器 working_dir 变化时静默漂移。
    """
    raw = Path(settings.ATTACHMENT_STORAGE_ROOT).expanduser()
    if raw.is_absolute():
        return raw
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    return repo_root / raw


_PRIVATE_ATTACH_DIR = _resolve_attachment_root()


def _unlink_attachment_file(problem_id: int, stored_path: str) -> None:
    """删除单个附件的磁盘文件（不存在即忽略）。

    只取``Path(stored_path).name``，绝不接受调用方传入的路径片段，
    防止 ../ 穿越到 attachments 根目录之外。
    """
    try:
        (_PRIVATE_ATTACH_DIR / str(problem_id) / Path(stored_path).name).unlink(
            missing_ok=True
        )
    except OSError:
        # 磁盘清理失败不应阻断DB 已提交的操作；残留文件由对账任务兜底
        pass


def _purge_problem_attachment_dir(problem_id: int) -> None:
    """清理某题的全部附件目录（题目被删除时调用）。

    SQLAlchemy 的 cascade / 外键 ON DELETE CASCADE 只删DB 行，不会unlink，
    因此题目一旦删除就必须显式清目录，否则 storage 下孤儿文件会无限累积。
    """
    import shutil

    target = _PRIVATE_ATTACH_DIR / str(problem_id)
    # 双重保险：确认目标确实位于附件根目录内再动手
    try:
        target.resolve().relative_to(_PRIVATE_ATTACH_DIR.resolve())
    except ValueError:
        return
    shutil.rmtree(target, ignore_errors=True)


def find_orphan_attachment_files(known_stored: set[tuple[int, str]]) -> list[str]:
    """对账：列出磁盘上存在但 DB 无对应记录的孤儿附件文件。

    供定期任务/运维脚本调用。``known_stored`` 为 DB 中的 (problem_id, stored_path) 集合。
    """
    orphans: list[str] = []
    if not _PRIVATE_ATTACH_DIR.exists():
        return orphans
    for problem_dir in _PRIVATE_ATTACH_DIR.iterdir():
        if not problem_dir.is_dir():
            continue
        try:
            pid = int(problem_dir.name)
        except ValueError:
            continue
        for f in problem_dir.iterdir():
            if f.is_file() and (pid, f.name) not in known_stored:
                orphans.append(str(f))
    return orphans


def _can_edit_problem(db_problem: Problem, user: User, team_admin: bool) -> bool:
    """题目编辑权限：题目管理员 / 出题人本人 / 团队管理员。"""
    if _can_manage_problems(user):
        return True
    if db_problem.author_id is not None and db_problem.author_id == user.id:
        return True
    return team_admin


async def _ensure_can_edit_problem(
    db: AsyncSession, problem: Problem, user: User
) -> None:
    """校验附件管理权限：无权限时按题不存在处理 404 / 403。"""
    if problem.team_id is None:
        if not _can_edit_problem(problem, user, False):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在"
            )
        return
    if _can_manage_problems(user):
        return
    if await _is_team_admin(db, problem.team_id, user):
        return
    if not await _is_team_member(db, problem.team_id, user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在"
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="需要团队管理权限"
    )


def _can_manage_problems(user: User) -> bool:
    """题目管理口径 =「管理名单 → 题目管理」那一列（白名单/超管/大管/题管）。

    以前这里只认裸字段 `can_manage_problems`，于是名单把白名单/超管/大管勾在
    题目管理列上、他们进来却处处 403 —— 又是「名单上有、活干不了」。
    `is_admin`（泛管理员）仍不放行：它不在名单任何一列里，能力上位也不该外溢。
    """
    return perm.can_manage_problems(user)


def _require_problem_manage(user: User) -> None:
    if not _can_manage_problems(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="需要题目管理权限"
        )


def _is_publicly_visible(problem: Problem) -> bool:
    """主题库题真正对外公开：作者想公开 且 审核已通过。"""
    return bool(problem.is_public and problem.review_status == REVIEW_APPROVED)


def _can_view_main_problem(problem: Problem, user: User) -> bool:
    """主题库题可读：题目管理员 / 出题人本人 / 已通过审核的公开题。"""
    if _can_manage_problems(user):
        return True
    if problem.author_id is not None and problem.author_id == user.id:
        return True
    return _is_publicly_visible(problem)


async def _ensure_can_view_problem(
    db: AsyncSession, problem: Problem, user: User
) -> None:
    """统一题目可见性校验（附件下载/详情都复用）。无权限按 404 处理。

    口径必须与题面详情接口 ``_resolve_team_problem_access`` 一致，
    否则会出现「能打开题面却拿不到附件 / 下载 404」的两套判定。
    """
    if problem.team_id is not None:
        # 团队公开题全站可见；私有题需成员身份或可访问比赛挂载
        if problem.is_public:
            return
        if await _is_team_member(db, problem.team_id, user):
            return
        if await _is_problem_in_accessible_contest(db, problem.id, user):
            return
        raise HTTPException(status_code=404, detail="题目不存在")
    if _can_view_main_problem(problem, user):
        return
    if await _is_problem_in_accessible_contest(db, problem.id, user):
        return
    raise HTTPException(status_code=404, detail="题目不存在")


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
    row = (await db.execute(
        select(TeamMember.id).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == user.id,
            TeamMember.role == "admin",
        )
    )).scalar_one_or_none()
    return row is not None


async def _is_team_member(db: AsyncSession, team_id: int, user: User) -> bool:
    """当前用户是否可见该团队私有题（成员 / 团队管理员 / 题目管理权限）。"""
    if _can_manage_problems(user) or user.is_super_admin:
        if not await is_team_organizing_shielded_contest(db, team_id, user):
            return True
    return await _is_team_admin(db, team_id, user) or bool((await db.execute(
        select(TeamMember.id).where(
            TeamMember.team_id == team_id, TeamMember.user_id == user.id)
    )).scalar_one_or_none())


async def _is_problem_in_accessible_contest(
    db: AsyncSession, problem_id: int, user: User
) -> bool:
    """检查题目是否挂在当前用户有权访问的比赛中（已报名的比赛、已结束的公开赛等）。"""
    now = datetime.now(timezone.utc)
    rows = (await db.execute(
        select(Contest.id, Contest.visibility, Contest.start_time, Contest.end_time)
        .join(ContestProblem, ContestProblem.contest_id == Contest.id)
        .where(ContestProblem.problem_id == problem_id)
    )).all()
    if not rows:
        return False
    for cid, vis, st, en in rows:
        en_aware = _aware(en) if en else None
        st_aware = _aware(st) if st else None
        # 1. 比赛已结束：公开赛（全站公开/团队公开）赛后向全站所有人公开题目
        if en_aware and now >= en_aware and vis in ("public", "team_public"):
            return True
        # 2. 比赛进行中：如果用户已报名该比赛，允许通过比赛访问题目
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


async def _resolve_team_problem_access(
    db: AsyncSession, problem: Problem, user: User
) -> None:
    """团队题的可见性：
    1. 团队公开题（is_public 为 True）对全站所有人开放；
    2. 作为比赛题目挂在某场比赛中，且该比赛处于进行中（已报名）/已结束（公开赛）时对用户开放；
    3. 团队成员 / 团队管理员 / 站方管理员可见；
    其余按不存在处理（404 防探测）。
    """
    if problem.team_id is None:
        return
    # 团队公开题：全站所有人可见
    if problem.is_public:
        return
    if await _is_team_member(db, problem.team_id, user):
        return
    if await _is_problem_in_accessible_contest(db, problem.id, user):
        return
    # 区分 404（非成员）/403（成员但被下架等），当前仅成员可见
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在"
    )


def _aware(dt: datetime) -> datetime:
    """SQLite 读回 naive datetime，统一按 UTC 处理（Postgres 返回 aware）。"""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _can_view_contest_problems(user: User) -> bool:
    """能看比赛题：与「题目管理」列同口径（见 _can_manage_problems）。"""
    return perm.can_manage_problems(user)


async def _resolve_contest_problem_access(
    db: AsyncSession, problem: Problem, user: User
) -> None:
    """比赛期间的题目：未报名者不可读题面；报名了也要等开赛。

    只约束「未开始 / 进行中」的比赛；已结束的比赛题目回归普通题库内容。
    举办方（创建者及举办团队全员）始终可见；若开启管理员参赛保护，非举办方的管理员亦受开赛时间与报名限制。
    """
    now = datetime.now(timezone.utc)
    rows = (await db.execute(
        select(Contest)
        .join(ContestProblem, ContestProblem.contest_id == Contest.id)
        .where(ContestProblem.problem_id == problem.id)
    )).scalars().all()
    # 未结束（end_time 还没到）的比赛才算「比赛期间」
    live = [c for c in rows if _aware(c.end_time) is not None and _aware(c.end_time) >= now]
    if not live:
        return

    # 举办方始终可见（创建者及举办团队全员）
    for c in live:
        if await is_contest_organizer(db, c, user):
            return

    # 若未开启管理员参赛保护，题目管理员/站内管理员直接放行
    has_shield = any(getattr(c, "hide_submissions_from_admin", False) for c in live)
    if _can_view_contest_problems(user) and not has_shield:
        return

    # 报名了其中任意一场才进下一道门（报名时就已校验过团队资格）
    registered = (await db.execute(
        select(ContestParticipant.contest_id).where(
            ContestParticipant.user_id == user.id,
            ContestParticipant.contest_id.in_([c.id for c in live]),
        )
    )).scalars().all()
    if not registered:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该题属于未结束的比赛，报名后才能查看题目内容",
        )
    # 报名了也要等开赛：报名的比赛全都还没开始 → 开赛后才放行
    reg = set(registered)
    if any(
        c.id in reg and _aware(c.start_time) is not None and _aware(c.start_time) <= now
        for c in live
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="该题所在比赛尚未开始，比赛开始后才能查看题目内容",
    )


@router.get("", summary="题目列表")
async def list_problems(
    difficulty: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None, max_length=100),
    all: bool = Query(False, description="含未公开题目（兼容旧参数，已被默认行为取代）"),
    scope: str = Query(
        "public",
        pattern="^(public|mine|review)$",
        description="public 题库 / mine 我出的题 / review 审核后台（需题目管理权限）",
    ),
    review_status: Optional[str] = Query(None, description="按审核状态过滤"),
    page: int = Query(0, ge=0),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """题库列表，支持难度 / 来源 / 标签 / 关键词筛选。

    - public（默认）：普通人只看到审核通过的公开题；有题目管理权限者可见全部。
    - mine：当前用户自己出的题（任意审核状态）。
    - review：审核后台，需题目管理权限，可叠加 review_status=pending/rejected。
    """
    if review_status is not None and review_status not in REVIEW_STATUSES:
        raise HTTPException(status_code=400, detail="非法审核状态")

    mine = False
    if scope == "mine":
        mine = True
        include_private = False
    elif scope == "review":
        _require_problem_manage(current_user)
        include_private = True
    else:
        include_private = bool(all) or _can_manage_problems(current_user)

    return await ProblemService.list_problems(
        db,
        difficulty=difficulty,
        source=source,
        tag=tag,
        keyword=keyword,
        include_private=include_private,
        user_id=current_user.id,
        page=page,
        page_size=page_size,
        mine=mine,
        review_status=review_status,
        review_scope=(scope == "review"),
    )


@router.get("/sources", summary="来源列表")
async def list_sources(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[str]:
    """去重后的题目来源（筛选下拉用）。"""
    return await ProblemService.list_sources(db)


async def resolve_problem_by_code(
    db: AsyncSession, code: str, current_user: User
) -> Problem | None:
    """按题号解析题目并做与网页题面完全一致的可见性/访问校验。

    题号形态：主题库 P{n} / 用户题库 U{n}（id = n-1000）/ 团队题 T{n} /
    纯数字（优先按 n-1000 解析，兜底按裸 id）。返回 ``None`` 表示题目
    不存在或当前用户不可见（调用方统一回 404，防 id 探测）；团队/比赛
    访问冲突直接抛 ``HTTPException``（调用方透传，或在 otk 通道转换为
    ``{"error"}`` 格式）。

    by-code 端点与 otk-remote 拉题端点共用本函数——两条通道一个口径。
    """
    code = code.strip().upper()
    problem: Problem | None
    if code.startswith("T") and code[1:].isdigit():
        problem = (await db.execute(
            select(Problem).where(Problem.t_no == int(code[1:]))
        )).scalar_one_or_none()
    elif code[:1] in ("P", "U") and code[1:].isdigit():
        problem = await ProblemService.get_by_id(db, int(code[1:]) - 1000)
        # 编号字母必须与题目实际归属一致，防止 P/U 串号探测
        if problem is not None and problem.team_id is None:
            expect_official = code.startswith("P")
            if bool(problem.is_official) != expect_official:
                problem = None
    elif code.isdigit():
        num = int(code)
        problem = None
        if num >= 1000:
            problem = await ProblemService.get_by_id(db, num - 1000)
        if problem is None:
            problem = await ProblemService.get_by_id(db, num)
    else:
        problem = None
    if problem is None or (
        problem.team_id is None
        and not _can_view_main_problem(problem, current_user)
    ):
        return None
    await _resolve_team_problem_access(db, problem, current_user)
    await _resolve_contest_problem_access(db, problem, current_user)
    return problem


@router.get("/by-code/{code}", summary="按题号访问题目（P1001 / T10）")
async def get_problem_by_code(
    code: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """统一题目入口：主题库 P{n} / 用户题库 U{n}（id = n-1000），团队题 T{n}。"""
    problem = await resolve_problem_by_code(db, code, current_user)
    if problem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在"
        )
    return ProblemService._dict(problem, with_description=True)


@router.get("/submit-eligibility", summary="获取投题审核门槛与完成状态")
async def get_problem_submit_eligibility(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """查询当前用户各难度的投题审核门槛达成情况（>=15道）。"""
    return await ProblemService.get_problem_submit_eligibility(db, current_user)


@router.post("/parse-markdown", summary="解析题目 Markdown 题面")
async def parse_problem_markdown_api(
    req: ProblemMarkdownParseRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    """解析题目 Markdown 文本，自动提取标题、难度、时空限制、分节与样例组。"""
    return parse_problem_markdown(req.content)


async def _import_single_problem_zip(
    db: AsyncSession,
    current_user: User,
    content: bytes,
    filename: str,
    problem_id: Optional[int] = None,
    team_id: Optional[int] = None,
    is_public: Optional[bool] = None,
    clear_existing_cases: bool = True,
) -> dict:
    """解析单个 ZIP 压缩包并创建或更新题目及其测试点。"""
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="仅支持 zip 压缩包格式")

    try:
        parsed_data = await run_in_threadpool(parse_problem_zip, content, filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    meta = parsed_data["problem_meta"]
    subtask_cfg = parsed_data.get("subtask_config")

    # 1. 更新已有题目
    if problem_id is not None:
        problem = await ProblemService.get_by_id(db, problem_id)
        if problem is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")

        is_staff = _can_manage_problems(current_user)
        if problem.team_id is not None:
            if not is_staff and not await _is_team_admin(db, problem.team_id, current_user):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要团队管理权限")
        else:
            if not is_staff and problem.author_id != current_user.id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有权限修改该题目")

        for k in ("title", "difficulty", "source", "tags", "description", "background",
                  "input_format", "output_format", "hint", "samples", "time_limit", "memory_limit"):
            val = meta.get(k)
            if val is not None:
                setattr(problem, k, val)

        if is_public is not None:
            problem.is_public = is_public

        if subtask_cfg:
            problem.subtask_config = subtask_cfg

        if clear_existing_cases:
            await db.execute(delete(TestCase).where(TestCase.problem_id == problem.id))
            base_order = 0
        else:
            max_order = (await db.execute(
                select(sa_func.max(TestCase.sort_order)).where(TestCase.problem_id == problem.id)
            )).scalar()
            base_order = 0 if max_order is None else max_order + 1

        created_cases = []
        for offset, tc_data in enumerate(parsed_data["test_cases"]):
            tc = TestCase(
                problem_id=problem.id,
                input_data=tc_data["input"],
                expected_output=tc_data["output"],
                subtask_id=tc_data.get("subtask_id"),
                subtask_score=tc_data.get("subtask_score"),
                sort_order=base_order + offset,
            )
            db.add(tc)
            created_cases.append(tc)

        await db.commit()
        await db.refresh(problem)
        return {
            "success": True,
            "filename": filename,
            "problem": ProblemService._dict(problem, with_description=True),
            "imported_test_cases": len(created_cases),
            "detected_subtasks": parsed_data["detected_subtasks"],
            "subtask_config": problem.subtask_config,
        }

    # 2. 创建新题目
    default_title = meta.get("title") or Path(filename).stem or "未命名题目"
    problem_data = {
        "title": default_title[:100],
        "difficulty": meta.get("difficulty") or "暂无评定",
        "source": (meta.get("source") or "")[:100] if meta.get("source") else None,
        "tags": meta.get("tags") or [],
        "description": meta.get("description") or "",
        "background": meta.get("background") or "",
        "input_format": meta.get("input_format") or "",
        "output_format": meta.get("output_format") or "",
        "hint": meta.get("hint") or "",
        "samples": meta.get("samples") or [],
        "time_limit": meta.get("time_limit") or 1000,
        "memory_limit": meta.get("memory_limit") or 128,
        "author_id": current_user.id,
        "subtask_config": subtask_cfg,
    }

    from sqlalchemy.exc import IntegrityError

    problem = None
    try:
        if team_id is not None:
            if not await _is_team_admin(db, team_id, current_user):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要团队管理权限")
            team = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none()
            if team is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="团队不存在")
            if team.is_banned:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该团队已被封禁，无法创建题目")
            problem_data["team_id"] = team_id
            problem_data["is_public"] = is_public if is_public is not None else False

            for _ in range(50):
                max_no = (await db.execute(select(sa_func.max(Problem.t_no)))).scalar() or 0
                problem_data["t_no"] = max_no + 1
                try:
                    async with db.begin_nested():
                        problem = Problem(**problem_data)
                        db.add(problem)
                        await db.flush()
                        await db.refresh(problem)
                    break
                except IntegrityError:
                    problem = None
                    continue
            if problem is None:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="创建失败（编号冲突），请重试")
        else:
            is_staff = _can_manage_problems(current_user)
            wants_public = bool(is_public) if is_public is not None else False
            problem_data["is_public"] = wants_public
            problem_data["is_official"] = bool(is_staff and wants_public)
            if wants_public:
                if is_staff:
                    problem_data["review_status"] = REVIEW_APPROVED
                    problem_data["reviewer_id"] = current_user.id
                    problem_data["reviewed_at"] = datetime.now(timezone.utc)
                else:
                    diff = problem_data.get("difficulty", "入门")
                    try:
                        await ProblemService.check_submit_eligibility(db, current_user, diff)
                    except PermissionError as e:
                        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
                    problem_data["review_status"] = REVIEW_PENDING
            else:
                problem_data["review_status"] = REVIEW_DRAFT

            problem = await ProblemService.create_without_commit(db, problem_data)

        created_cases = []
        for offset, tc_data in enumerate(parsed_data["test_cases"]):
            tc = TestCase(
                problem_id=problem.id,
                input_data=tc_data["input"],
                expected_output=tc_data["output"],
                subtask_id=tc_data.get("subtask_id"),
                subtask_score=tc_data.get("subtask_score"),
                sort_order=offset,
            )
            db.add(tc)
            created_cases.append(tc)

        if problem.team_id is None and problem.review_status == REVIEW_APPROVED:
            await adjust_contribution_on_author_change(
                db, None, current_user.id, "暂无评定", problem.difficulty
            )

        await db.commit()
        await db.refresh(problem)
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        prob_id = getattr(problem, "id", None) if problem else None
        logger.exception("保存测试点或题目失败 (problem %s): %s", prob_id, e)
        raise HTTPException(status_code=500, detail="保存测试点失败，请稍后重试")

    return {
        "success": True,
        "filename": filename,
        "problem": ProblemService._dict(problem, with_description=True),
        "imported_test_cases": len(created_cases),
        "detected_subtasks": parsed_data["detected_subtasks"],
        "subtask_config": problem.subtask_config,
    }


@router.post("/import-zip", summary="上传 ZIP 压缩包导入题目（支持单文件或多文件）")
async def import_problem_zip(
    file: Optional[UploadFile] = File(None),
    files: Optional[List[UploadFile]] = File(None),
    problem_id: Optional[int] = Form(None),
    team_id: Optional[int] = Form(None),
    is_public: Optional[bool] = Form(None),
    clear_existing_cases: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """上传包含题面 Markdown 和测试数据文件夹的 ZIP 压缩包，自动创建或更新题目。
    支持单文件上传或多文件批量上传。
    """
    ok, wait = check(f"import-zip:{current_user.id}", 30, 60)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"ZIP 导入操作过于频繁，请等待 {wait} 秒后再试",
        )

    upload_files: List[UploadFile] = []
    if files:
        upload_files.extend(files)
    if file:
        upload_files.append(file)

    if not upload_files:
        raise HTTPException(status_code=400, detail="未提供任何 zip 压缩包")

    if len(upload_files) > 1:
        if problem_id is not None:
            raise HTTPException(status_code=400, detail="更新已有题目时仅支持上传单个 ZIP 压缩包")
        return await import_problems_batch_zip(
            files=upload_files,
            team_id=team_id,
            is_public=is_public,
            db=db,
            current_user=current_user,
        )

    target_file = upload_files[0]
    filename = target_file.filename or "problem.zip"
    content = await target_file.read()
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="单个压缩包大小不能超过 100MB")
    return await _import_single_problem_zip(
        db=db,
        current_user=current_user,
        content=content,
        filename=filename,
        problem_id=problem_id,
        team_id=team_id,
        is_public=is_public,
        clear_existing_cases=clear_existing_cases,
    )


@router.post("/import-batch-zip", summary="批量上传多个 ZIP 压缩包导入多个题目与测试点")
async def import_problems_batch_zip(
    files: List[UploadFile] = File(...),
    team_id: Optional[int] = Form(None),
    is_public: Optional[bool] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """批量上传多个 ZIP 压缩包，自动创建多个题目并导入对应测试数据。"""
    ok, wait = check(f"import-batch-zip:{current_user.id}", 10, 60)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"批量导入操作过于频繁，请等待 {wait} 秒后再试",
        )

    if not files:
        raise HTTPException(status_code=400, detail="未选择任何压缩包文件")

    if len(files) > 50:
        raise HTTPException(status_code=400, detail="单次最多支持批量上传 50 个题目压缩包")

    MAX_BATCH_TOTAL_BYTES = 500 * 1024 * 1024  # 500MB
    total_size = sum(getattr(f, "size", None) or 0 for f in files)
    if total_size > MAX_BATCH_TOTAL_BYTES:
        raise HTTPException(status_code=400, detail="批量上传总大小不能超过 500MB")

    results = []
    succeeded = 0
    failed = 0
    accumulated_bytes = 0

    for f in files:
        filename = f.filename or "unknown.zip"
        if not filename.lower().endswith(".zip"):
            results.append({
                "filename": filename,
                "success": False,
                "error": "仅支持 .zip 格式压缩包",
            })
            failed += 1
            continue

        try:
            content = await f.read()
            accumulated_bytes += len(content)
            if accumulated_bytes > MAX_BATCH_TOTAL_BYTES:
                results.append({
                    "filename": filename,
                    "success": False,
                    "error": "批量上传总大小已超过 500MB 限制",
                })
                failed += 1
                break

            if len(content) > 50 * 1024 * 1024:
                results.append({
                    "filename": filename,
                    "success": False,
                    "error": "文件超过 50 MB 限制",
                })
                failed += 1
                continue

            item_res = await _import_single_problem_zip(
                db=db,
                current_user=current_user,
                content=content,
                filename=filename,
                problem_id=None,
                team_id=team_id,
                is_public=is_public,
                clear_existing_cases=True,
            )
            results.append(item_res)
            succeeded += 1
        except Exception as e:
            await db.rollback()
            err_msg = e.detail if isinstance(e, HTTPException) else str(e)
            results.append({
                "filename": filename,
                "success": False,
                "error": err_msg,
            })
            failed += 1

    return {
        "total": len(files),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }


@router.get("/{problem_id}", summary="题目详情")
async def get_problem(
    problem_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    problem = await ProblemService.get_by_id(db, problem_id)
    # 待审核/未公开题：出题人本人与题目管理员可见，其余人按不存在处理（404 防探测）
    if problem is None or (
        problem.team_id is None
        and not _can_view_main_problem(problem, current_user)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在"
        )
    await _resolve_team_problem_access(db, problem, current_user)
    await _resolve_contest_problem_access(db, problem, current_user)
    return ProblemService._dict(problem, with_description=True)


@router.post("/{problem_id}/try-run", summary="自测运行（编译 + 执行一次）")
async def try_run_problem(
    problem_id: int,
    payload: ProblemTryRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """题目页「自测环境」：走评测同款沙箱跑一次，返回 stdout/stderr。"""
    ok, wait = check(f"try-run:{current_user.id}", 20, 60)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"运行太频繁，请 {wait} 秒后再试",
        )
    problem = await ProblemService.get_by_id(db, problem_id)
    # 与题目详情同口径的可见性校验（未公开题 404 防探测）
    if problem is None or (
        problem.team_id is None
        and not _can_view_main_problem(problem, current_user)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在"
        )
    await _resolve_team_problem_access(db, problem, current_user)
    await _resolve_contest_problem_access(db, problem, current_user)

    if payload.language not in LANGUAGES:
        raise HTTPException(status_code=400, detail="不支持的语言")
    if not payload.code.strip():
        raise HTTPException(status_code=400, detail="代码不能为空")
    if len(payload.code) > 64_000:
        raise HTTPException(status_code=400, detail="代码过长（上限 64KB）")
    if len(payload.input) > 200_000:
        raise HTTPException(status_code=400, detail="输入数据过长（上限 200KB）")

    try:
        return await sandbox_try_run(
            language=payload.language,
            code=payload.code,
            input_data=payload.input,
            time_limit_ms=problem.time_limit,
            memory_mb=problem.memory_limit,
        )
    except JudgeError as e:
        raise HTTPException(status_code=502, detail=f"评测沙箱不可用：{e}")


@router.post("", summary="创建题目")
async def create_problem(
    payload: ProblemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    data = payload.model_dump(exclude_unset=True)
    team_id = data.pop("team_id", None)
    if team_id is not None:
        # 团队私有题：团队管理员即可创建（无需题目管理权限），编号走全局 T 序列
        if not await _is_team_admin(db, team_id, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="需要团队管理权限",
            )
        team = (await db.execute(
            select(Team).where(Team.id == team_id)
        )).scalar_one_or_none()
        if team is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="团队不存在"
            )
        if team.is_banned:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="该团队已被封禁，无法创建题目",
            )
        data["team_id"] = team_id
        data.setdefault("is_public", False)
        data["author_id"] = current_user.id
        # T 编号跨团队全局递增：max+1，并发撞号由 unique 约束兜底后重试
        from sqlalchemy.exc import IntegrityError
        problem = None
        for _ in range(3):
            max_no = (await db.execute(
                select(sa_func.max(Problem.t_no))
            )).scalar() or 0
            data["t_no"] = max_no + 1
            try:
                problem = await ProblemService.create(db, data)
                break
            except IntegrityError:
                await db.rollback()
        if problem is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="创建失败（编号冲突），请重试",
            )
        return ProblemService._dict(problem, with_description=True)

    # 非团队题：所有人均可创建；作者即出题人。
    # 普通用户置为公开 → pending（此时是 U 题），审核通过后才转 P；
    # 题目管理员公开 → 直接 approved，进入主题库 P；草稿一律 U。
    is_staff = _can_manage_problems(current_user)
    if not is_staff and "allow_solution_submission" in data:
        data["allow_solution_submission"] = True
    wants_public = bool(data.get("is_public", True))
    data["author_id"] = current_user.id
    data["is_official"] = bool(is_staff and wants_public)
    if wants_public:
        if is_staff:
            data["review_status"] = REVIEW_APPROVED
            data["reviewer_id"] = current_user.id
            data["reviewed_at"] = datetime.now(timezone.utc)
        else:
            diff = data.get("difficulty", "入门")
            try:
                await ProblemService.check_submit_eligibility(db, current_user, diff)
            except PermissionError as e:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
            data["review_status"] = REVIEW_PENDING
    else:
        data["review_status"] = REVIEW_DRAFT
    problem = await ProblemService.create(db, data)
    # 主题库题：出题人按难度获得贡献值。仅审核通过（直接公开）时发放，
    # 待审核题通过后由审核接口补发，防止建草稿刷贡献。
    if problem.review_status == REVIEW_APPROVED:
        await adjust_contribution_on_author_change(
            db, None, current_user.id, "暂无评定", problem.difficulty
        )
    return ProblemService._dict(problem, with_description=True)


@router.put("/{problem_id}", summary="更新题目")
async def update_problem(
    problem_id: int,
    payload: ProblemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    problem = await ProblemService.get_by_id(db, problem_id)
    if problem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在"
        )
    shielded = await get_shielded_contest_for_problem(db, problem_id, current_user)
    if shielded is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该题属于未结束的比赛，比赛结束前非举办方不可修改题目",
        )
    # 主题库题：题目管理员可改任意题；普通用户只能改自己出的题
    # 团队私有题：团队管理员即可编辑
    # （非成员按不存在处理 404；成员但非管理员 403）
    is_main = problem.team_id is None
    is_staff = _can_manage_problems(current_user)
    if is_main:
        if not is_staff and problem.author_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在"
            )
    elif not is_staff:
        if await _is_team_admin(db, problem.team_id, current_user):
            pass
        elif not await _is_team_member(db, problem.team_id, current_user):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="需要团队管理权限"
            )
        team = (await db.execute(
            select(Team).where(Team.id == problem.team_id)
        )).scalar_one_or_none()
        if team is not None and team.is_banned:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="该团队已被封禁，无法修改题目",
            )
    old_difficulty = problem.difficulty
    old_author_id = problem.author_id
    old_review_status = problem.review_status
    data = payload.model_dump(exclude_unset=True)

    # 指派出题人：仅题目管理员可用（普通作者不能把题转给别人）
    author_identifier = data.pop("author", None)
    if author_identifier is not None:
        if not is_staff:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="只有题目管理员可以指派出题人",
            )
        ident = str(author_identifier).strip()
        author_user: User | None = None
        if ident:
            author_user = (await db.execute(
                select(User).where(User.username == ident)
            )).scalar_one_or_none()
            if author_user is None and ident.isdigit():
                author_user = (await db.execute(
                    select(User).where(User.user_number == int(ident))
                )).scalar_one_or_none()
            if author_user is None:
                raise HTTPException(
                    status_code=400, detail=f"用户「{ident}」不存在"
                )
        data["author_id"] = author_user.id if author_user else None

    # 题解通道开关：仅管理员/题目管理员可配置
    if "allow_solution_submission" in data:
        can_toggle = is_staff or current_user.is_admin or current_user.is_super_admin
        if not can_toggle:
            data.pop("allow_solution_submission", None)

    # 非团队题公开审核状态机（团队题不走审核）：
    # 想公开 → 管理员直接 approved（转 P）；普通作者 pending（仍 U）
    # 改回隐藏 → draft（退回 U）
    if is_main and "is_public" in data:
        wants_public = bool(data["is_public"])
        if wants_public:
            if is_staff:
                data["review_status"] = REVIEW_APPROVED
                data["reviewer_id"] = current_user.id
                data["reviewed_at"] = datetime.now(timezone.utc)
                data["review_reason"] = None
                data["is_official"] = True
            else:
                diff = data.get("difficulty", problem.difficulty)
                try:
                    await ProblemService.check_submit_eligibility(db, current_user, diff)
                except PermissionError as e:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
                data["review_status"] = REVIEW_PENDING
                data["reviewer_id"] = None
                data["reviewed_at"] = None
                data["review_reason"] = None
                data["is_official"] = False
        else:
            data["review_status"] = REVIEW_DRAFT
            data["is_official"] = False
    elif is_main and not is_staff and "difficulty" in data:
        if problem.is_public or problem.review_status == REVIEW_PENDING:
            diff = data["difficulty"]
            try:
                await ProblemService.check_submit_eligibility(db, current_user, diff)
            except PermissionError as e:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    problem = await ProblemService.update(
        db, problem, data
    )
    # 主题库题：难度变更重算所有首次 AC 该题用户的经验（团队私有题不计经验）
    if (problem.team_id is None
            and payload.difficulty is not None
            and payload.difficulty != old_difficulty):
        await adjust_experience_on_difficulty_change(
            db, problem.id, old_difficulty, payload.difficulty
        )
    # 主题库题贡献值结算：只在「已通过审核」状态下账面上存在出题贡献
    if is_main:
        was_approved = old_review_status == REVIEW_APPROVED
        now_approved = problem.review_status == REVIEW_APPROVED
        if not was_approved and now_approved:
            # 首次通过审核（管理员直接公开 / 审核接口之外的发布途径）：补发贡献
            await adjust_contribution_on_author_change(
                db, None, problem.author_id, "暂无评定", problem.difficulty
            )
        elif was_approved and not now_approved:
            # 已公开的题被下架/驳回：扣回出题贡献；再次通过时按新难度补发
            await adjust_contribution_on_author_change(
                db, old_author_id, None, old_difficulty, problem.difficulty
            )
        elif now_approved and problem.author_id != old_author_id:
            await adjust_contribution_on_author_change(
                db, old_author_id, problem.author_id,
                old_difficulty, problem.difficulty,
            )
        elif (now_approved
                and payload.difficulty is not None
                and payload.difficulty != old_difficulty):
            await adjust_contribution_on_difficulty_change(
                db, problem.author_id, old_difficulty, problem.difficulty
            )
    return ProblemService._dict(problem, with_description=True)


@router.post(
    "/{problem_id}/submit-to-library",
    summary="提交题目进主题库（草稿/被驳回 → 待审核）",
)
async def submit_problem_to_library(
    problem_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """把「我的题库」里的题一键提交进主题库。

    草稿（未公开）或被驳回的题 → ``is_public=True`` + ``review_status=pending``，
    进入管理员审核队列；**审核通过后才正式进主题库**（转 P 编号）。
    题目管理权限者提交时免投题门槛（与创建题目时的口径一致）。
    """
    problem = await ProblemService.get_by_id(db, problem_id)
    if problem is None or problem.team_id is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")
    if problem.author_id != current_user.id and not _can_manage_problems(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="只能提交自己出的题目"
        )
    if problem.is_official or problem.review_status == REVIEW_APPROVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="该题已在主题库中"
        )
    if problem.review_status == REVIEW_PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="该题正在审核中，请等待审核结果"
        )

    # 投题门槛（与创建题目同一套校验；题目管理权限者免检）
    if not _can_manage_problems(current_user):
        try:
            await ProblemService.check_submit_eligibility(db, current_user, problem.difficulty)
        except PermissionError as e:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    # 条件 UPDATE 保证状态流转原子：上面读取到的状态到写入之间，管理员可能刚好
    # 审核通过（is_official=True）。若直接赋值再 commit，就会把已入库的题覆写成
    # pending，产生「已进主题库却显示待审核」的脏数据。
    from sqlalchemy import update as sa_update

    result = await db.execute(
        sa_update(Problem)
        .where(
            Problem.id == problem_id,
            Problem.is_official.is_(False),
            Problem.review_status.in_([REVIEW_DRAFT, REVIEW_REJECTED]),
        )
        .values(is_public=True, review_status=REVIEW_PENDING)
    )
    if result.rowcount == 0:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该题状态已变更（可能已进主题库或正在审核中），请刷新后重试",
        )
    await db.commit()
    await db.refresh(problem)
    return {
        "success": True,
        "problem_id": problem.id,
        "problem_number": problem.problem_number,
        "review_status": problem.review_status,
    }


@router.post("/{problem_id}/review", summary="审核题目（通过/驳回）")
async def review_problem(
    problem_id: int,
    payload: ProblemReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """题目审核：通过后题目立即公开；驳回需填写原因，作者修改后可重新提交。"""
    _require_problem_manage(current_user)
    problem = await ProblemService.get_by_id(db, problem_id)
    if problem is None or problem.team_id is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在"
        )

    was_approved = problem.review_status == REVIEW_APPROVED
    old_difficulty = problem.difficulty
    old_author_id = problem.author_id

    if payload.action == "approve":
        # 审核通过检测：出题人通过的主题库 >= 该题难度的题目必须 >= 15 道（出题人具备管理权限者免检）
        if problem.author_id:
            author = (await db.execute(
                select(User).where(User.id == problem.author_id)
            )).scalar_one_or_none()
            if author and not _can_manage_problems(author):
                count, _ = await ProblemService.get_user_ac_count_ge_difficulty(
                    db, author.id, problem.difficulty
                )
                if count < ProblemService.PROBLEM_SUBMIT_THRESHOLD:
                    diff_label = (
                        problem.difficulty
                        if problem.difficulty in ProblemService.DIFFICULTY_RANKS
                        else "入门"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"投递者未达到投题门槛（通过「{diff_label}」及以上题目 {count}/{ProblemService.PROBLEM_SUBMIT_THRESHOLD} 道），暂不允许审核通过",
                    )

        problem.is_public = True
        problem.review_status = REVIEW_APPROVED
        problem.review_reason = None
        problem.reviewer_id = current_user.id
        problem.reviewed_at = datetime.now(timezone.utc)
        # 审核通过：从用户题 U 转入主题库 P
        problem.is_official = True
    else:
        if not payload.reason:
            raise HTTPException(status_code=400, detail="驳回时必须填写驳回原因")
        problem.review_status = REVIEW_REJECTED
        problem.review_reason = payload.reason
        problem.reviewer_id = current_user.id
        problem.reviewed_at = datetime.now(timezone.utc)
        # 驳回：仍是作者自己的 U 题
        problem.is_official = False

    await db.commit()
    await db.refresh(problem)

    # 贡献值随审核状态走：通过补发（仅首次），驳回已公开题则扣回
    if payload.action == "approve" and not was_approved:
        await adjust_contribution_on_author_change(
            db, None, problem.author_id, "暂无评定", problem.difficulty
        )
    elif payload.action == "reject" and was_approved:
        await adjust_contribution_on_author_change(
            db, old_author_id, None, old_difficulty, problem.difficulty
        )
    return ProblemService._dict(problem, with_description=True)


@router.post("/{problem_id}/toggle-solution-submission", summary="管理员切换题解提交通道开关")
async def toggle_problem_solution_submission(
    problem_id: int,
    body: Optional[ProblemToggleSolutionRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    problem = await ProblemService.get_by_id(db, problem_id)
    if problem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在"
        )
    shielded = await get_shielded_contest_for_problem(db, problem_id, current_user)
    if shielded is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该题属于未结束的比赛，比赛结束前非举办方不可操作",
        )
    can_toggle = _can_manage_problems(current_user) or current_user.is_admin or current_user.is_super_admin
    if not can_toggle:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员或题目管理权限"
        )

    if body and body.allow is not None:
        problem.allow_solution_submission = bool(body.allow)
    else:
        problem.allow_solution_submission = not bool(problem.allow_solution_submission)

    await db.commit()
    await db.refresh(problem)
    return ProblemService._dict(problem, with_description=True)


async def _assert_team_manage_for_migrate(
    db: AsyncSession, team: Team, user: User
) -> None:
    """迁移到团队时校验：团主 / 团队管理员 才能接收题目。"""
    if team.owner_id == user.id:
        return
    row = (await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team.id,
            TeamMember.user_id == user.id,
            TeamMember.role == "admin",
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=403, detail="需要该团队的管理权限")


async def _next_team_problem_no(db: AsyncSession) -> int:
    """下一个团队题编号（t_no 是跨团队全局序列，unique 约束）。"""
    return ((await db.execute(select(sa_func.max(Problem.t_no)))).scalar() or 0) + 1


async def _assert_contest_manage_for_migrate(
    db: AsyncSession, contest: Contest, user: User
) -> None:
    """逐比赛校验管理权（与 contests 模块的 ``_can_edit_contest`` 同一口径）。

    直接复用 contests 的实现，避免两处口径漂移：站长 / 题目管理、比赛 owner、
    以及团队赛的团队管理员都算——此前只做**全局**权限判断，会把「比赛 owner /
    团主」挡在外面，等于他们无法把题迁进自己办的比赛。
    """
    from app.api.contests import _can_edit_contest

    if not await _can_edit_contest(db, contest, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="需要该比赛的管理权限"
        )


def _may_enter_library(problem: Problem, is_prob_admin: bool) -> bool:
    """题能否被放回主题库（公开可见）。

    主题库列表只收 ``is_public`` 且 ``review_status=approved`` 的题；非题管
    必须「原本就在主题库（is_official）」或「已审核通过」，否则等于借迁移
    绕过「提交进主题库」的审核流程。
    """
    return bool(
        is_prob_admin
        or problem.is_official
        or problem.review_status == REVIEW_APPROVED
    )


def _put_into_library(problem: Problem) -> None:
    """把题置为「正式在主题库」状态（脱离团队、清团队编号、公开且过审）。

    三个字段要一起对齐：只设 is_official 而不设 is_public/approved，会出现
    「编号是 P 但列表里看不到」的状态错位。
    """
    problem.team_id = None
    problem.t_no = None
    problem.is_official = True
    problem.is_public = True
    if problem.review_status != REVIEW_APPROVED:
        problem.review_status = REVIEW_APPROVED


@router.post(
    "/{problem_id}/migrate",
    summary="题目迁移（主题库 / 团队题 / 比赛赛题互搬）",
)
async def migrate_problem(
    problem_id: int,
    body: ProblemMigrateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """把题目在三种归属之间搬迁（不是复制，题目 id 与其提交记录/题解都保留）。

    - ``target=library``：进入主题库 —— 脱离团队、置为正式公开（P 编号）
    - ``target=team``：转为团队私有题 —— 挂到指定团队、分配 T 编号、不进主题库
    - ``target=contest``：挂到指定比赛；默认同时**从主题库撤下**（成为比赛独占题，
      用 ``keep_in_library=true`` 可保留在主题库）

    权限：需要「题目作者」或题目管理权限；转入团队另需该团队管理权，
    转入比赛另需该比赛的管理权。
    """
    # with_for_update：整个迁移过程（校验 -> 改归属 -> commit）期间锁住该行，
    # 避免 shielded 检查与写入之间其他事务改动题目归属造成 TOCTOU。
    # （SQLite 方言会忽略该子句，生产 PostgreSQL 生效）
    problem = (await db.execute(
        select(Problem).where(Problem.id == problem_id).with_for_update()
    )).scalar_one_or_none()
    if not problem:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")

    # 权限口径与本文件其余端点一致：严格只认 can_manage_problems 字段，
    # 不走 permissions.can_manage_problems（后者含硬编码 UID 白名单，放行面更宽，
    # 会让白名单/超管绕过下面逐团队、逐比赛的归属校验）。
    is_prob_admin = _can_manage_problems(current_user)
    if not (is_prob_admin or problem.author_id == current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="需要题目作者或题目管理权限"
        )

    # 未结束且开启参赛保护的比赛里的题：迁移会把它移出比赛（或提前公开进主题库），
    # 等于绕过赛前保护。与 update_problem / toggle-solution-submission 同一处理。
    shielded = await get_shielded_contest_for_problem(db, problem_id, current_user)
    if shielded is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"该题属于未结束的比赛《{shielded.title}》，不允许迁移",
        )

    # 归属变更前统一校验「源团队」管理权：避免作者把别人团队里的题单方面搬走
    # （target=library / team / contest 三个分支都适用，不再只护其中一个）
    if problem.team_id is not None and not is_prob_admin:
        src_team = (await db.execute(
            select(Team).where(Team.id == problem.team_id)
        )).scalar_one_or_none()
        if src_team is not None:
            await _assert_team_manage_for_migrate(db, src_team, current_user)

    moved_from = (
        "团队题" if problem.team_id is not None
        else ("主题库" if problem.is_official else "未公开题")
    )

    if body.target == "library":
        # 进主题库 = 公开可见，不能让未过审的题借迁移绕过审核流程。
        # 要求：题管 / 原本就在主题库（is_official）/ 已审核通过（approved），
        # 否则走「提交进主题库」（submit-to-library）走正规审核与投题门槛。
        if not _may_enter_library(problem, is_prob_admin):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该题尚未通过审核，不能直接迁入主题库，请先提交主题库审核",
            )
        _put_into_library(problem)

    elif body.target == "team":
        if not body.team_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="转团队题必须指定 team_id"
            )
        team = (await db.execute(
            select(Team).where(Team.id == body.team_id)
        )).scalar_one_or_none()
        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="目标团队不存在")
        if team.is_banned:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="目标团队已被封禁，无法接收题目"
            )
        if not is_prob_admin:
            await _assert_team_manage_for_migrate(db, team, current_user)
        problem.team_id = team.id
        if problem.t_no is None:
            # t_no 是跨团队全局 unique 序列：并发迁移可能算出同一个 max+1，
            # 按 create_problem 的模式用 savepoint 重试，避免 commit 时 500
            from sqlalchemy.exc import IntegrityError

            for _ in range(50):
                problem.t_no = await _next_team_problem_no(db)
                try:
                    async with db.begin_nested():
                        await db.flush()
                    break
                except IntegrityError:
                    problem.t_no = None
                    continue
            else:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="团队题编号分配冲突，请重试",
                )
        # 团队私有题不进主题库
        problem.is_official = False

    else:  # contest
        if not body.contest_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="转比赛赛题必须指定 contest_id"
            )
        contest = (await db.execute(
            select(Contest).where(Contest.id == body.contest_id)
        )).scalar_one_or_none()
        if not contest:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="目标比赛不存在")
        if not is_prob_admin:
            await _assert_contest_manage_for_migrate(db, contest, current_user)
        linked = (await db.execute(
            select(ContestProblem).where(
                ContestProblem.contest_id == contest.id,
                ContestProblem.problem_id == problem.id,
            )
        )).scalar_one_or_none()
        if linked is None:
            max_order = (await db.execute(
                select(sa_func.max(ContestProblem.sort_order)).where(
                    ContestProblem.contest_id == contest.id)
            )).scalar() or 0
            db.add(ContestProblem(
                contest_id=contest.id, problem_id=problem.id, sort_order=max_order + 1,
            ))
        problem.team_id = None
        problem.t_no = None
        if body.keep_in_library:
            # 「保留在主题库」不等于「新公开」：只有迁移前本来就已公开
            # （is_official 且 approved）的题才允许保留，否则等于借比赛迁移
            # 把未过审的题塞进主题库（还可能是刚挂上的比赛题，造成赛前泄露）。
            already_public = bool(
                problem.is_official and problem.review_status == REVIEW_APPROVED
            )
            if not (is_prob_admin or already_public):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="该题原本不在主题库（未过审），不能选择保留在主题库",
                )
            _put_into_library(problem)
        else:
            problem.is_official = False

    await db.commit()
    await db.refresh(problem)
    return {
        "success": True,
        "problem_id": problem.id,
        "moved_from": moved_from,
        "target": body.target,
        "problem_number": problem.problem_number,
        "team_id": problem.team_id,
        "is_official": bool(problem.is_official),
    }


@router.post("/{problem_id}/attachments", summary="上传题目附件")
async def upload_problem_attachment(
    problem_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """上传附件（multipart，字段名 file），单文件最大 16MB。

    出题人本人 / 题目管理员 / 团队题的团队管理员可上传。
    流式边读边写磁盘：每读 1MB 即落盘，超限立即中止并清理已写入的半截文件，
    单个附件最多常驻 1MB 于内存，避免大文件全量读入内存。
    """
    problem = await ProblemService.get_by_id(db, problem_id)
    if problem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在"
        )
    await _ensure_can_edit_problem(db, problem, current_user)

    # 限流：上传落盘属重操作，防止高频上传耗尽磁盘（与 import-zip 同口径）
    ok, wait = check(f"attach-upload:{current_user.id}", 20, 60)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"附件上传过于频繁，请等待 {wait} 秒后再试",
        )

    orig_name = _sanitize_filename((file.filename or "附件").strip()[:255])
    ext = Path(orig_name).suffix.lower()
    if ext in _FORBIDDEN_ATTACHMENT_EXT:
        raise HTTPException(status_code=400, detail=f"不允许上传 {ext} 类型的文件")

    upload_dir = _PRIVATE_ATTACH_DIR / str(problem_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    disk_path = upload_dir / stored_name

    # 流式边读边写：超过 16MB 立即中止并删除已写入的半截文件，避免全量占内存
    total = 0
    write_ok = False
    try:
        with disk_path.open("wb") as fh:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_ATTACHMENT_SIZE:
                    raise HTTPException(status_code=400, detail="附件不能超过 16MB")
                fh.write(chunk)
        write_ok = True
    finally:
        if not write_ok:
            disk_path.unlink(missing_ok=True)
    if total == 0:
        disk_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="文件为空")

    # stored_path 存磁盘 uuid 文件名，对外下载走 GET /download 接口带鉴权
    att = ProblemAttachment(
        problem_id=problem_id,
        uploader_id=current_user.id,
        orig_name=orig_name,
        stored_path=stored_name,
        size_bytes=total,
        content_type=file.content_type,
    )
    db.add(att)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        disk_path.unlink(missing_ok=True)
        raise
    await db.refresh(att)
    return {"success": True, "attachment": attachment_dict(att, problem_id=problem_id)}


@router.get(
    "/{problem_id}/attachments/{attachment_id}/download",
    summary="下载题目附件（带题目可见性鉴权）",
)
async def download_problem_attachment(
    problem_id: int,
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """附件不走 /static 直链，统一走该接口校验题目可见性后返回文件。"""
    problem = await ProblemService.get_by_id(db, problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    await _ensure_can_view_problem(db, problem, current_user)

    att = (await db.execute(
        select(ProblemAttachment).where(
            ProblemAttachment.id == attachment_id,
            ProblemAttachment.problem_id == problem_id,
        )
    )).scalar_one_or_none()
    if att is None:
        raise HTTPException(status_code=404, detail="附件不存在")

    disk = _PRIVATE_ATTACH_DIR / str(problem_id) / Path(att.stored_path).name
    if not disk.is_file():
        raise HTTPException(status_code=404, detail="附件已损坏")
    # content_type 来自客户端上传请求头，可被伪造为 text/html、image/svg+xml
    # 等可执行脚本的类型。虽然 FileResponse(filename=...) 会强制
    # Content-Disposition: attachment，但在旧版浏览器 / 企业代理 / 被
    # iframe 引用等场景下仍可能被渲染。下载出口对不安全类型统一降级。
    media_type = _safe_download_media_type(att.content_type)
    # 历史数据可能存有未清洗的文件名，下载出口再清洗一次（双保险）
    return FileResponse(
        path=disk,
        filename=_sanitize_filename(att.orig_name),
        media_type=media_type,
    )


@router.delete("/{problem_id}/attachments/{attachment_id}", summary="删除题目附件")
async def delete_problem_attachment(
    problem_id: int,
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """删除附件（上传者本人 / 出题人 / 题目管理员 / 团队管理员）。"""
    problem = await ProblemService.get_by_id(db, problem_id)
    if problem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在"
        )
    await _ensure_can_edit_problem(db, problem, current_user)

    att = (await db.execute(
        select(ProblemAttachment).where(
            ProblemAttachment.id == attachment_id,
            ProblemAttachment.problem_id == problem_id,
        )
    )).scalar_one_or_none()
    if att is None:
        raise HTTPException(status_code=404, detail="附件不存在")

    # 即使 expire_on_commit=False（AsyncSessionLocal 的实际配置），
    # 行被删除后访问其属性也不可靠，且为避免潜在的关系加载问题，
    # 在 delete/commit 之前先把磁盘路径缓存下来。
    stored = att.stored_path

    # 先 DB 后磁盘：commit 成功再 unlink，避免悬空记录
    try:
        await db.delete(att)
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    _unlink_attachment_file(problem_id, stored)
    return {"success": True}

