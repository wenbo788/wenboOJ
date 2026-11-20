"""站内投票接口。

- 阅读：登录即可（`GET /polls`、`GET /polls/{id}`）
- 发起/关闭：任意管理员（`permissions.is_any_admin`）
- 投票：登录用户，一人一票（多选为一份多选，可改票）
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions as perm
from app.core.database import get_db
from app.deps import get_current_user
from app.models.poll import Poll
from app.models.user import User
from app.services import poll as poll_service

router = APIRouter(prefix="/polls", tags=["polls"])


def _require_admin(user: User) -> None:
    if not perm.is_any_admin(user):
        raise HTTPException(status_code=403, detail="需要管理员权限")


async def _load_poll(db: AsyncSession, poll_id: int) -> Poll:
    poll = (await db.execute(select(Poll).where(Poll.id == poll_id))).scalar_one_or_none()
    if poll is None:
        raise HTTPException(status_code=404, detail="投票不存在")
    return poll


@router.get("", summary="投票列表")
async def list_polls(
    status: str = Query("all", pattern="^(all|open|closed)$"),
    page: int = Query(0, ge=0),
    page_size: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """分页与状态过滤都下推到 SQL —— 不能把整张表捞进内存再切片。

    分页用**页码从 0 开始**（与站内其它列表一致）。
    """
    now = datetime.now(timezone.utc)
    query = select(Poll)
    if status == "open":
        query = query.where(
            Poll.closed_at.is_(None),
            or_(Poll.ends_at.is_(None), Poll.ends_at > now),
        )
    elif status == "closed":
        query = query.where(
            or_(
                Poll.closed_at.is_not(None),
                and_(Poll.ends_at.is_not(None), Poll.ends_at <= now),
            )
        )

    total = int((await db.execute(
        select(func.count()).select_from(query.subquery())
    )).scalar() or 0)

    rows = (await db.execute(
        query.order_by(Poll.id.desc())
        .offset(page * page_size)
        .limit(page_size)
    )).scalars().unique().all()

    items = await poll_service.list_payloads(db, list(rows), current_user)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{poll_id}", summary="投票详情")
async def get_poll(
    poll_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    poll = await _load_poll(db, poll_id)
    return await poll_service.poll_payload(db, poll, current_user)


@router.post("", status_code=201, summary="发起投票（管理员）")
async def create_poll(
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_admin(current_user)
    try:
        poll = await poll_service.create_poll(db, current_user, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await poll_service.poll_payload(db, poll, current_user)


@router.post("/{poll_id}/vote", summary="投票 / 改票")
async def vote(
    poll_id: int,
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    poll = await _load_poll(db, poll_id)
    option_ids = payload.get("option_ids")
    if not isinstance(option_ids, list) or not option_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个选项")
    try:
        await poll_service.cast_vote(db, poll, current_user, option_ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await poll_service.poll_payload(db, poll, current_user)


@router.post("/{poll_id}/close", summary="结束投票（发起者或管理员）")
async def close_poll(
    poll_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    poll = await _load_poll(db, poll_id)
    if current_user.id != poll.created_by and not perm.is_any_admin(current_user):
        raise HTTPException(status_code=403, detail="只有发起者或管理员能结束投票")
    await poll_service.close_poll(db, poll)
    return await poll_service.poll_payload(db, poll, current_user)
