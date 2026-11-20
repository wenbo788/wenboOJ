"""管理员上传接口 —— 用户头像."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app import permissions as perm

router = APIRouter(prefix="/admin", tags=["admin"])

_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


@router.post("/users/{user_number}/avatar")
async def upload_user_avatar(
    user_number: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传指定用户的头像（需要用户管理权限）。"""
    # 真源口径：白名单/超管/大管天然具备，或持有 can_manage_users 字段。
    # 原来读的是裸字段，白名单/超管/大管反而被挡在外面 —— 而「管理名单」
    # 的用户管理那一列把他们勾上了（正是「名单上有、活干不了」）。
    if not perm.can_manage_users(current_user):
        raise HTTPException(status_code=403, detail="需要用户管理权限")

    result = await db.execute(select(User).where(User.user_number == user_number))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 0/1/68 号为受保护账号：任何人都不可修改
    if user_number in perm.PROTECTED_UIDS:
        raise HTTPException(status_code=400, detail="0/1/68 号账号受保护，不可修改")

    # 不能修改自己
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能修改自己")

    # 超级管理员（UID=2 除外）：目标是不是超管同样按真源判（白名单也是更高层级，
    # 用裸 is_super_admin 判会把白名单目标漏成「普通用户」）
    if (
        perm.is_super_admin(user)
        and user.user_number != 2
        and not (perm.is_white_list(current_user) or perm.is_super_admin(current_user))
    ):
        raise HTTPException(
            status_code=403,
            detail="修改超级管理员（UID=2 除外）需要超级管理员权限"
        )

    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(status_code=400, detail="仅支持 jpg/jpeg/png/gif/webp 图片")

    upload_dir = Path(__file__).resolve().parent.parent.parent / "static" / "uploads" / "avatars"
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{user_number}_avatar_{int(time.time() * 1000)}{ext}"
    path = upload_dir / filename
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片不能超过 5MB")
    path.write_bytes(content)

    avatar_url = f"/static/uploads/avatars/{filename}"
    user.avatar_url = avatar_url
    await db.commit()

    return {"success": True, "avatar_url": avatar_url}
