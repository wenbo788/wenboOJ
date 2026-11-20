"""云剪贴板接口。

能力：
  - 列表（分页 + kind 筛选 + 关键字搜索）
  - 创建（超限自动挤掉最旧的 text / code 条目）
  - 修改 / 删除 / 单条查看
所有条目严格隔离：仅所属用户可见可改。
"""

from __future__ import annotations

import zlib

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db, _IS_SQLITE
from app.deps import get_current_user
from app.models.clipboard import UserClipboard
from app.models.user import User
from app.schemas.clipboard import (
    ClipboardCreate,
    ClipboardItem,
    ClipboardListResponse,
    ClipboardUpdate,
)

router = APIRouter(prefix="/clipboards", tags=["clipboards"])

_MAX_LEN = settings.CLIPBOARD_MAX_TEXT_LEN
_MAX_ITEMS = settings.CLIPBOARD_MAX_ITEMS
_MAX_CODE_ITEMS = settings.CLIPBOARD_CODE_MAX_ITEMS
_ALLOWED_KINDS = {"text", "code"}


async def _get_own(db: AsyncSession, item_id: int, user: User) -> UserClipboard:
    row = await db.get(UserClipboard, item_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="条目不存在")
    return row


async def _evict_if_needed(db: AsyncSession, user_id: int, kind: str) -> None:
    """若超限则删除最旧的条目。

    ⚠️ 调用方不变量（重构时务必保留，否则并发保护会静默失效）：
      1. PostgreSQL 用 advisory lock 串行化同一 (user_id, kind) 的 eviction，
         避免并发写都绕过 count 检查后各自插入、短暂超出配额。
      2. ``pg_advisory_xact_lock`` 的生命周期**绑定当前事务**，因此调用方必须在
         同一事务内完成「本函数 → INSERT/UPDATE → COMMIT」，一旦把本函数抽成
         独立 service 方法并在外层提前 commit，锁会在 count 之前释放，保护失效。
         （create / update_item 两条路径目前都满足这一约束。）
      3. SQLite 下连接本身是文件级锁、单连接串行，跳过 advisory lock；
         这是开发环境的已知边界，不提供跨进程并发保护。
    注意：不在聚合查询上用 FOR UPDATE —— PostgreSQL 禁止这种写法。
    advisory lock key 用 zlib.crc32 确定性哈希，跨 worker 进程一致。
    """
    if kind == "text":
        limit = _MAX_ITEMS
    else:
        limit = _MAX_CODE_ITEMS

    if not _IS_SQLITE:
        raw = f"clipboard:{user_id}:{kind}".encode()
        key = (zlib.crc32(raw) & 0x7FFFFFFF) + 1_000_000
        await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})

    total = await db.scalar(
        select(func.count())
        .select_from(UserClipboard)
        .where(UserClipboard.user_id == user_id, UserClipboard.kind == kind)
    )
    total = total or 0
    if total < limit:
        return
    # 本次 create 会新增 1 条：删到 limit-1 条最旧记录，
    # 再加上即将插入的 1 条恰好收敛到 limit（修复 off-by-one 超限额）。
    excess = total - (limit - 1)
    oldest_ids = (await db.execute(
        select(UserClipboard.id)
        .where(UserClipboard.user_id == user_id, UserClipboard.kind == kind)
        .order_by(UserClipboard.id.asc())
        .limit(excess)
    )).scalars().all()
    if oldest_ids:
        await db.execute(delete(UserClipboard).where(UserClipboard.id.in_(oldest_ids)))


@router.get("", response_model=ClipboardListResponse, summary="我的剪贴板列表")
async def list_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    kind: str | None = Query(None, description="text / code"),
    q: str | None = Query(None, max_length=100, description="按标题 / 正文搜索"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ClipboardListResponse:
    conds = [UserClipboard.user_id == current_user.id]
    if kind:
        if kind not in _ALLOWED_KINDS:
            raise HTTPException(status_code=400, detail="kind 仅支持 text / code")
        conds.append(UserClipboard.kind == kind)
    if q:
        escaped_q = (
            q.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        like = f"%{escaped_q}%"
        conds.append(
            (UserClipboard.title.ilike(like, escape="\\"))
            | (UserClipboard.content.ilike(like, escape="\\"))
        )

    total = await db.scalar(select(func.count()).select_from(UserClipboard).where(*conds))
    rows = (
        await db.execute(
            select(UserClipboard)
            .where(*conds)
            .order_by(UserClipboard.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return ClipboardListResponse(
        items=[ClipboardItem.model_validate(r) for r in rows],
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


@router.get("/limits", summary="获取剪贴板配额（前端展示用）")
async def get_limits(
    current_user: User = Depends(get_current_user),
) -> dict:
    """轻量接口，前端展示文案/校验从这里读，避免与后端配置漂移。"""
    return {
        "max_content_len": settings.CLIPBOARD_MAX_TEXT_LEN,
        "max_items": settings.CLIPBOARD_MAX_ITEMS,
        "max_code_items": settings.CLIPBOARD_CODE_MAX_ITEMS,
    }


@router.get("/{item_id}", response_model=ClipboardItem, summary="单条查看")
async def get_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserClipboard:
    return await _get_own(db, item_id, current_user)


@router.post(
    "",
    response_model=ClipboardItem,
    status_code=status.HTTP_201_CREATED,
    summary="新建条目",
)
async def create_item(
    payload: ClipboardCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserClipboard:
    if payload.kind not in _ALLOWED_KINDS:
        raise HTTPException(status_code=400, detail="kind 仅支持 text / code")

    content = payload.content
    # Schema 的 min_length=1 只拦空字符串，纯空白 " " 能过。
    # 前端已用 trim() 拒绝，后端必须对齐，否则 API 直连可造出脏数据。
    if not content.strip():
        raise HTTPException(status_code=400, detail="内容不能为空或纯空白")
    if len(content) > _MAX_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"正文不能超过 {_MAX_LEN} 字符（当前 {len(content)}）",
        )
    if payload.language and payload.kind != "code":
        raise HTTPException(status_code=400, detail="非代码条目不能指定 language")

    await _evict_if_needed(db, current_user.id, payload.kind)

    row = UserClipboard(
        user_id=current_user.id,
        kind=payload.kind,
        title=(payload.title or "").strip()[:120] or None,
        language=(payload.language or "").strip()[:32] or None,
        content=content,
    )
    db.add(row)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(row)
    return row


@router.patch("/{item_id}", response_model=ClipboardItem, summary="修改条目")
async def update_item(
    item_id: int,
    payload: ClipboardUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserClipboard:
    row = await _get_own(db, item_id, current_user)

    # 所有校验必须前置到状态赋值之前：否则一次失败的请求会留下半改状态，
    # 且校验顺序与 create 路径不一致。
    new_kind = payload.kind if payload.kind is not None else row.kind
    if payload.kind is not None and payload.kind not in _ALLOWED_KINDS:
        raise HTTPException(status_code=400, detail="kind 仅支持 text / code")
    if payload.language and new_kind != "code":
        raise HTTPException(status_code=400, detail="非代码条目不能指定 language")
    if payload.content is not None and not payload.content.strip():
        raise HTTPException(status_code=400, detail="内容不能为空或纯空白")
    if payload.content is not None and len(payload.content) > _MAX_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"正文不能超过 {_MAX_LEN} 字符（当前 {len(payload.content)}）",
        )

    # kind 变更会改变条目所属配额分组，必须走与 create 同一个挤兑入口，
    # 否则可把多条 text 批量改成 code 绕过 CLIPBOARD_CODE_MAX_ITEMS。
    # 注意：这里必须与后续的 UPDATE 在同一事务内 commit（见 _evict_if_needed 文档）。
    if new_kind != row.kind:
        await _evict_if_needed(db, current_user.id, new_kind)

    row.kind = new_kind
    # kind 切到 text 时，若客户端未显式指定 language，主动清空，
    # 保持与 create 路径一致的不变量（text 条目不带 language）。
    if payload.kind is not None and payload.kind != "code" and payload.language is None:
        row.language = None
    if payload.title is not None:
        row.title = (payload.title or "").strip()[:120] or None
    if payload.language is not None:
        row.language = (payload.language or "").strip()[:32] or None
    if payload.content is not None:
        row.content = payload.content

    # kind 切换可能已触发 _evict_if_needed（advisory lock + DELETE），
    # commit 失败时显式回滚，避免会话停留在半改状态。
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(row)
    return row


@router.delete("/{item_id}", summary="删除条目")
async def delete_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    row = await _get_own(db, item_id, current_user)
    await db.delete(row)
    # 与 create/update 保持一致：commit 失败显式回滚，保证事务状态确定性
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return {"success": True}
