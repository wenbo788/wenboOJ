"""Homepage friend links API."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps import get_current_user
from app.models.friend_link import FriendLink
from app.models.user import User

router = APIRouter(prefix="/friend-links", tags=["friend-links"])


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


class FriendLinkInput(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    icon: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=500)

    @field_validator("title", "icon", "url")
    @classmethod
    def trim_value(cls, value: str) -> str:
        return value.strip()

    @field_validator("icon")
    @classmethod
    def validate_icon(cls, value: str) -> str:
        if not (_is_http_url(value) or (value.startswith("/") and not value.startswith("//"))):
            raise ValueError("图标地址须为 http(s) 地址或站内路径")
        return value

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if not _is_http_url(value):
            raise ValueError("友情链接地址必须是 http(s) 地址")
        return value


@router.get("", summary="获取首页友情链接")
async def list_friend_links(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    rows = await db.execute(
        select(FriendLink)
        .where(FriendLink.is_active.is_(True))
        .order_by(FriendLink.sort_order.asc(), FriendLink.id.asc())
    )
    return {
        "links": [
            {"id": item.id, "title": item.title, "icon": item.icon, "url": item.url}
            for item in rows.scalars().all()
        ]
    }


@router.put("", summary="管理员更新首页友情链接")
async def replace_friend_links(
    payload: list[FriendLinkInput],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    if not current_user.is_admin and not current_user.is_super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    if len(payload) > 40:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="最多只能添加 40 个友情链接")
    if any(not item.title or not item.icon or not item.url for item in payload):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="名称、图标和链接均不能为空")

    await db.execute(delete(FriendLink))
    db.add_all([
        FriendLink(title=item.title, icon=item.icon, url=item.url, sort_order=index, is_active=True)
        for index, item in enumerate(payload)
    ])
    await db.commit()
    return {"success": True}
