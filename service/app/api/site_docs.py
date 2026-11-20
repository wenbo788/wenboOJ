"""站点文档（帮助中心 / 社区规则）接口。

读取公开；写入仅限秩序管理（can_manage_posts，管理员/超管默认具备）。
每次保存写入修改日志（site_doc_logs），日志仅秩序管理可查看。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps import get_current_user
from app.models.site_document import SiteDocLog, SiteDocument
from app.models.user import User
from app.services.moderation import is_order_admin

router = APIRouter(prefix="/site-docs", tags=["site-docs"])

# 白名单：只允许这些站点文档 key，避免随意建记录
ALLOWED_KEYS = {"help", "rules"}
MAX_CONTENT = 100_000


class SiteDocUpdate(BaseModel):
    title: str = Field("", max_length=100)
    content: str = Field("", max_length=MAX_CONTENT)


def _doc_out(doc: SiteDocument | None, key: str) -> dict[str, Any]:
    if doc is None:
        return {"key": key, "title": "", "content": "", "updated_at": None}
    return {
        "key": doc.key,
        "title": doc.title,
        "content": doc.content,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }


async def _get(db: AsyncSession, key: str) -> SiteDocument | None:
    return (await db.execute(
        select(SiteDocument).where(SiteDocument.key == key)
    )).scalar_one_or_none()


@router.get("/{key}", summary="获取站点文档（公开）")
async def get_site_doc(
    key: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if key not in ALLOWED_KEYS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    return _doc_out(await _get(db, key), key)


@router.put("/{key}", summary="更新站点文档（仅秩序管理）")
async def update_site_doc(
    key: str,
    payload: SiteDocUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if not is_order_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="需要秩序管理权限"
        )
    if key not in ALLOWED_KEYS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")

    doc = await _get(db, key)
    old_title = doc.title if doc else ""
    old_content = doc.content if doc else ""
    if doc is None:
        doc = SiteDocument(
            key=key,
            title=payload.title.strip(),
            content=payload.content,
            updated_by_id=current_user.id,
        )
        db.add(doc)
    else:
        doc.title = payload.title.strip()
        doc.content = payload.content
        doc.updated_by_id = current_user.id

    # 修改日志：记录前后快照（仅秩序管理可见）
    db.add(SiteDocLog(
        key=key,
        editor_id=current_user.id,
        old_title=old_title,
        new_title=payload.title.strip(),
        old_content=old_content,
        new_content=payload.content,
    ))
    await db.commit()
    await db.refresh(doc)
    return _doc_out(doc, key)


@router.get("/{key}/logs", summary="站点文档修改日志（仅秩序管理）")
async def get_site_doc_logs(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if not is_order_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="需要秩序管理权限"
        )
    if key not in ALLOWED_KEYS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")

    rows = (await db.execute(
        select(SiteDocLog)
        .where(SiteDocLog.key == key)
        .order_by(SiteDocLog.created_at.desc(), SiteDocLog.id.desc())
    )).scalars().unique().all()

    def _brief(u: User | None) -> dict[str, Any]:
        if u is None:
            return {"id": None, "username": "已删除", "user_number": None, "avatar_url": ""}
        return {
            "id": u.id,
            "username": u.username,
            "user_number": u.user_number,
            "avatar_url": u.avatar_url or "",
        }

    return {"logs": [{
        "id": log.id,
        "editor": _brief(log.editor),
        "old_title": log.old_title,
        "new_title": log.new_title,
        "old_content": log.old_content,
        "new_content": log.new_content,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    } for log in rows]}
