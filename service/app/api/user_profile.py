"""用户资料管理API。"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.database import get_db
from app.deps import get_current_user, get_current_user_optional
from app import permissions as perm
from app.models.follow import Follow
from app.models.tag_card import UserTagCard
from app.models.user import User
from app.models.user_history import UsernameHistory, UserTagHistory
from app.schemas.user import (
    PasswordUpdate,
    PublicUserOut,
    SelfUserOut,
    UserProfileUpdate,
    UsernameHistoryOut,
    UserTagHistoryOut,
)
from app.services import user_profile as user_service
from app.services.user import (
    USER_TAG_CARD_OPTIONS,
    get_user_by_id_for_payload,
)

router = APIRouter(prefix="/users", tags=["user-profile"])

_OIERDB_API_BASE = "https://oier.api.baoshuo.dev"
_OIERDB_CDN_BASE = "https://cos-1.cdn.baoshuo.xyz/oier"
_OIERDB_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_OIERDB_CACHE_TTL = 3600
_OIERDB_AWARD_LEVELS = [
    "金牌", "银牌", "铜牌",
    "一等奖", "二等奖", "三等奖",
    "国际金牌", "国际银牌", "国际铜牌",
    "前5%", "前15%", "前25%",
]

_oierdb_cache: dict[str, Any] = {
    "ts": 0.0,
    "index": None,
    "contests": None,
    "schools": None,
}
_oierdb_lock = asyncio.Lock()

_ALLOWED_AVATAR_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_MAX_AVATAR_SIZE = 5 * 1024 * 1024  # 5MB

# 主题商店：内置渐变预设（前端按 key 渲染对应 CSS 渐变）
_ALLOWED_THEME_PRESETS = {"dawn", "ocean", "dusk", "sakura"}


async def _require_tag_manager(user: User) -> None:
    # 统一走权限真源：白名单/超管/大管，或明确授予了 can_manage_tags 的人。
    # 这里原先只认「超管 或 字段」，白名单和大管反而会被挡在外面。
    if not perm.can_manage_tags(user):
        raise HTTPException(status_code=403, detail="需要 Tag 管理权限")


def _card_dict(card: UserTagCard) -> dict:
    return {
        "id": card.id,
        "name": card.name,
        "enabled": card.enabled,
        "granter_id": card.granter_id,
        "granter_name": card.granter.username if card.granter else None,
        "created_at": card.created_at.isoformat() if card.created_at else None,
    }



async def _get_follow_stats(
    db: AsyncSession,
    user_id: int,
    current_user: User | None = None,
) -> dict[str, Any]:
    """获取用户的关注统计信息。失败时优雅降级为默认值，不阻塞主接口。"""
    try:
        from sqlalchemy import func

        followers_count = (
            await db.execute(
                select(func.count()).where(Follow.followee_id == user_id)
            )
        ).scalar() or 0

        following_count = (
            await db.execute(
                select(func.count()).where(Follow.follower_id == user_id)
            )
        ).scalar() or 0

        is_following = False
        if current_user and current_user.id != user_id:
            result = await db.execute(
                select(Follow.id).where(
                    Follow.follower_id == current_user.id,
                    Follow.followee_id == user_id,
                )
            )
            is_following = result.scalar_one_or_none() is not None

        return {
            "followers_count": followers_count,
            "following_count": following_count,
            "is_following": is_following,
        }
    except Exception:
        return {
            "followers_count": 0,
            "following_count": 0,
            "is_following": False,
        }



@router.get("/me/tag-cards", summary="我的 Tag 卡列表")
async def list_my_tag_cards(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    cards = (await db.execute(
        select(UserTagCard)
        .options(joinedload(UserTagCard.granter))
        .where(UserTagCard.user_id == current_user.id)
        .order_by(UserTagCard.id)
    )).scalars().all()
    return {"items": [_card_dict(c) for c in cards]}


@router.put("/me/tag-cards/{card_id}/toggle", summary="佩戴/摘下 Tag 卡（佩戴制：同时仅一张）")
async def toggle_my_tag_card(
    card_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    card = (await db.execute(
        select(UserTagCard)
        .options(joinedload(UserTagCard.granter))
        .where(
            UserTagCard.id == card_id, UserTagCard.user_id == current_user.id)
    )).scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="Tag 卡不存在")
    if not card.enabled:
        # 佩戴制：先摘下其他卡
        others = (await db.execute(
            select(UserTagCard).where(
                UserTagCard.user_id == current_user.id,
                UserTagCard.enabled.is_(True))
        )).scalars().all()
        for c in others:
            c.enabled = False
        card.enabled = True
    else:
        card.enabled = False
    await db.commit()
    return _card_dict(card)


@router.post("/{user_id}/tag-cards", status_code=201,
             summary="授予 Tag 卡（需 Tag 管理权限）")
async def grant_tag_card(
    user_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    await _require_tag_manager(current_user)
    target = (await db.execute(
        select(User).where(User.id == user_id)
    )).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Tag 名称不能为空")
    if len(name) > 50:
        raise HTTPException(status_code=400, detail="Tag 名称过长（≤50 字）")
    exists = (await db.execute(
        select(UserTagCard.id).where(
            UserTagCard.user_id == user_id, UserTagCard.name == name)
    )).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=400, detail="该用户已有同名 Tag 卡")
    should_enable = bool(payload.get("enabled", True))
    if should_enable:
        others = (await db.execute(
            select(UserTagCard).where(
                UserTagCard.user_id == user_id,
                UserTagCard.enabled.is_(True))
        )).scalars().all()
        for c in others:
            c.enabled = False
    card = UserTagCard(
        user_id=user_id,
        name=name,
        enabled=should_enable,
        granter_id=current_user.id,
    )
    db.add(card)
    db.add(UserTagHistory(
        user_id=user_id,
        operator_id=current_user.id,
        action="grant",
        tag_name=name,
    ))
    await db.commit()
    card_with_granter = (await db.execute(
        select(UserTagCard)
        .options(joinedload(UserTagCard.granter))
        .where(UserTagCard.id == card.id)
    )).scalar_one()
    return _card_dict(card_with_granter)


@router.delete("/{user_id}/tag-cards/{card_id}", status_code=204,
               summary="删除 Tag 卡（需 Tag 管理权限）")
async def delete_tag_card(
    user_id: int,
    card_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    await _require_tag_manager(current_user)
    card = (await db.execute(
        select(UserTagCard).where(
            UserTagCard.id == card_id, UserTagCard.user_id == user_id)
    )).scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="Tag 卡不存在")
    db.add(UserTagHistory(
        user_id=user_id,
        operator_id=current_user.id,
        action="revoke",
        tag_name=card.name,
    ))
    await db.delete(card)
    await db.commit()


@router.get("/{user_id}/username-history", summary="获取用户改名历史")
async def get_username_history(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    target = (await db.execute(
        select(User).where(User.id == user_id)
    )).scalar_one_or_none()
    if not target:
        target = (await db.execute(
            select(User).where(User.user_number == user_id)
        )).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")

    result = await db.execute(
        select(UsernameHistory)
        .options(joinedload(UsernameHistory.operator))
        .where(UsernameHistory.user_id == target.id)
        .order_by(UsernameHistory.created_at.desc(), UsernameHistory.id.desc())
    )
    records = result.scalars().all()
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "operator_id": r.operator_id,
            "operator_name": r.operator.username if r.operator else "系统",
            "is_self": r.operator_id == r.user_id,
            "old_username": r.old_username,
            "new_username": r.new_username,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]


@router.get("/{user_id}/tag-history", summary="获取用户 Tag 变动历史")
async def get_tag_history(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    target = (await db.execute(
        select(User).where(User.id == user_id)
    )).scalar_one_or_none()
    if not target:
        target = (await db.execute(
            select(User).where(User.user_number == user_id)
        )).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")

    action_map = {
        "grant": "授予 Tag 卡",
        "revoke": "删除 Tag 卡",
        "custom_tag": "修改自定义头衔",
        "shop_redeem": "商店兑换",
    }

    result = await db.execute(
        select(UserTagHistory)
        .options(joinedload(UserTagHistory.operator))
        .where(UserTagHistory.user_id == target.id)
        .order_by(UserTagHistory.created_at.desc(), UserTagHistory.id.desc())
    )
    records = result.scalars().all()
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "operator_id": r.operator_id,
            "operator_name": r.operator.username if r.operator else ("商店/系统" if r.action == "shop_redeem" else "系统"),
            "action": r.action,
            "action_label": action_map.get(r.action, r.action),
            "tag_name": r.tag_name,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]



@router.get("/me", response_model=SelfUserOut, summary="获取当前用户信息")
async def get_user_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """获取当前登录用户的详细资料信息。

    重新查一次而不是直接返回 current_user：响应含 ``tag_cards[].granter_name``，
    get_current_user 那份实例没带授予人（理由见 services/user.py 的
    USER_TAG_CARD_OPTIONS），戴卡用户会因此 500。
    """
    return await get_user_by_id_for_payload(db, current_user.id)


@router.put("/me/profile", response_model=SelfUserOut, summary="更新用户资料")
async def update_user_profile(
    payload: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """更新当前用户的资料信息。

    Args:
        payload: 更新的用户资料数据
        current_user: 当前用户
        db: 数据库会话

    Returns:
        更新后的用户信息
    """
    try:
        updated_user = await user_service.update_user_profile(
            db, current_user.id, payload
        )
        return updated_user
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.put("/me/password", summary="更新用户密码")
async def update_user_password(
    payload: PasswordUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """更新当前用户的密码。

    Args:
        payload: 包含旧密码和新密码的数据
        current_user: 当前用户
        db: 数据库会话

    Returns:
        成功消息
    """
    try:
        await user_service.update_user_password(
            db, current_user.id, payload.old_password, payload.new_password
        )
        return {"message": "密码更新成功"}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/me/cover", summary="上传个人主页封面")
async def upload_cover(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """上传当前用户的个人主页封面图（multipart/form-data，字段名 file）。"""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_AVATAR_EXT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅支持 jpg/jpeg/png/gif/webp 图片",
        )

    content = await file.read()
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="图片不能超过 8MB",
        )

    upload_dir = Path(__file__).resolve().parent.parent.parent / "static" / "uploads" / "covers"
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{current_user.user_number}_cover_{int(time.time() * 1000)}{ext}"
    (upload_dir / filename).write_bytes(content)

    cover_url = f"/static/uploads/covers/{filename}"
    current_user.cover_url = cover_url
    await db.commit()

    return {"success": True, "cover_url": cover_url}


@router.post("/me/avatar", summary="上传用户头像")
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """上传当前用户的头像文件（multipart/form-data，字段名 file）。

    保存到服务端 static/uploads/avatars/，并将 avatar_url 更新为对应路径。
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_AVATAR_EXT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅支持 jpg/jpeg/png/gif/webp 图片",
        )

    content = await file.read()
    if len(content) > _MAX_AVATAR_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="图片不能超过 5MB",
        )

    upload_dir = Path(__file__).resolve().parent.parent.parent / "static" / "uploads" / "avatars"
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{current_user.user_number}_avatar_{int(time.time() * 1000)}{ext}"
    (upload_dir / filename).write_bytes(content)

    avatar_url = f"/static/uploads/avatars/{filename}"
    current_user.avatar_url = avatar_url
    await db.commit()

    return {"success": True, "avatar_url": avatar_url}


@router.post("/me/theme/background", summary="上传主题背景图")
async def upload_theme_background(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """上传自定义背景图（multipart/form-data，字段名 file），上传后自动启用。

    存到 static/uploads/themes/；图片类型与大小限制与头像一致。
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_AVATAR_EXT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅支持 jpg/jpeg/png/gif/webp 图片",
        )

    content = await file.read()
    if len(content) > _MAX_AVATAR_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="图片不能超过 5MB",
        )

    upload_dir = Path(__file__).resolve().parent.parent.parent / "static" / "uploads" / "themes"
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{current_user.user_number}_theme_{int(time.time() * 1000)}{ext}"
    (upload_dir / filename).write_bytes(content)

    # 覆盖旧的自定义图，保留/启用状态由用户后续 PUT 控制
    current_user.theme_background = f"/static/uploads/themes/{filename}"
    current_user.theme_enabled = True
    await db.commit()

    return {
        "success": True,
        "theme_background": current_user.theme_background,
        "theme_enabled": current_user.theme_enabled,
        "theme_hue": current_user.theme_hue,
    }


# ===== 个人偏好（偏好设置页：代码模板 / 编辑器等宽字体）=====
# 与前端 constants/codeFonts.ts 的字体列表保持一致
_ALLOWED_PREF_FONTS = {
    "jetbrains-mono",
    "roboto-mono",
    "source-code-pro",
    "ibm-plex-mono",
    "space-mono",
    "courier-prime",
}
_ALLOWED_TEMPLATE_LANGS = ("cpp", "c", "python3")
_TEMPLATE_MAX_LEN = 50_000  # 单语言模板上限（与提交代码体量同级，防滥用）


def _decode_template(raw: str | None) -> dict[str, str] | None:
    """code_template 列（JSON 字符串）→ 字典；空或脏数据回 None（前端用内置默认）。"""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


@router.put("/me/prefs", summary="保存个人偏好（代码模板/等宽字体）")
async def update_my_prefs(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """``code_template`` 传各语言模板字典（未包含的语言恢复内置默认）或
    null（全部恢复默认）；``code_font`` 传字体 key 或 null（恢复默认）。
    二者均可选，只更新传入的键。"""
    if "code_template" in payload:
        tpl = payload["code_template"]
        if tpl is None:
            current_user.code_template = None
        else:
            if not isinstance(tpl, dict):
                raise HTTPException(status_code=400, detail="code_template 需为对象")
            cleaned: dict[str, str] = {}
            for lang, code in tpl.items():
                if lang not in _ALLOWED_TEMPLATE_LANGS:
                    raise HTTPException(status_code=400, detail=f"不支持的语言：{lang}")
                if not isinstance(code, str):
                    raise HTTPException(
                        status_code=400, detail=f"{lang} 模板需为字符串"
                    )
                if len(code) > _TEMPLATE_MAX_LEN:
                    raise HTTPException(
                        status_code=400,
                        detail=f"{lang} 模板过长（上限 {_TEMPLATE_MAX_LEN} 字符）",
                    )
                cleaned[lang] = code
            current_user.code_template = json.dumps(cleaned, ensure_ascii=False)

    if "code_font" in payload:
        font = payload["code_font"]
        if font is not None and font not in _ALLOWED_PREF_FONTS:
            raise HTTPException(status_code=400, detail=f"未知字体：{font}")
        current_user.code_font = font

    # 学术模式开关（个人设置里切）：自律偏好，服务端不据此拒绝任何请求，
    # 只由前端据此隐藏犇犇/灌水区、默认收起题目难度
    if "academic_mode" in payload:
        mode = payload["academic_mode"]
        if not isinstance(mode, bool):
            raise HTTPException(status_code=400, detail="academic_mode 需为布尔值")
        current_user.academic_mode = mode

    await db.commit()
    return {
        "success": True,
        "code_template": _decode_template(current_user.code_template),
        "code_font": current_user.code_font,
        "academic_mode": current_user.academic_mode,
    }


@router.put("/me/theme", summary="设置主题背景（选择/清除/开关）")
async def update_theme(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """更新主题：``background`` 传图片 URL、``preset:xxx``（内置渐变）或
    null（恢复默认）；``enabled`` 控制是否应用。二者均可选。"""
    if "background" in payload:
        bg = payload.get("background")
        if bg is None or bg == "":
            current_user.theme_background = None
            current_user.theme_enabled = False
        elif str(bg).startswith("preset:"):
            preset = str(bg).split(":", 1)[1]
            if preset not in _ALLOWED_THEME_PRESETS:
                raise HTTPException(
                    status_code=400, detail=f"未知主题预设：{preset}"
                )
            current_user.theme_background = str(bg)
            current_user.theme_enabled = True
        elif str(bg).startswith("/static/uploads/themes/"):
            current_user.theme_background = str(bg)
            current_user.theme_enabled = True
        elif str(bg).startswith(("http://", "https://")):
            current_user.theme_background = str(bg)
            current_user.theme_enabled = True
        else:
            raise HTTPException(
                status_code=400, detail="非法路径"
            )

    if "enabled" in payload:
        if not isinstance(payload["enabled"], bool):
            raise HTTPException(status_code=400, detail="enabled 需为布尔值")
        if payload["enabled"] and current_user.theme_background is None:
            raise HTTPException(
                status_code=400, detail="还没有可选用的主题背景，请先上传或选择预设"
            )
        current_user.theme_enabled = payload["enabled"]

    # 色相调整：-180..180 的整数偏移，独立于背景开关
    if "hue" in payload:
        hue = payload.get("hue")
        if isinstance(hue, bool) or not isinstance(hue, int):
            raise HTTPException(status_code=400, detail="hue 需为整数")
        if not -180 <= hue <= 180:
            raise HTTPException(status_code=400, detail="hue 需在 -180 ~ 180 之间")
        current_user.theme_hue = hue

    # 深色主题开关：light / dark，独立于背景开关
    if "mode" in payload:
        mode = payload.get("mode")
        if mode not in ("light", "dark"):
            raise HTTPException(status_code=400, detail="mode 需为 light 或 dark")
        current_user.theme_mode = mode

    # 主页风格开关：cloud（新版云图首页）/ luogu（经典洛谷式首页），
    # 主题商店里切，只影响自己的首页观感
    if "home_style" in payload:
        style = payload.get("home_style")
        if style not in ("cloud", "luogu"):
            raise HTTPException(status_code=400, detail="home_style 需为 cloud 或 luogu")
        current_user.home_style = style

    await db.commit()
    return {
        "success": True,
        "theme_background": current_user.theme_background,
        "theme_enabled": current_user.theme_enabled,
        "theme_hue": current_user.theme_hue,
        "theme_mode": current_user.theme_mode,
        "home_style": current_user.home_style,
    }


# 公开资料要下发卡片上的「授予人名字」，而 granter 是 lazy="raise"，
# 必须显式带出来（见 models/tag_card.py 的说明），否则序列化时会触发 500。
# 口径复用 services/user.py 的常量：别再各写一份，漏一处就是一整页 500。
_PUBLIC_USER_OPTIONS = list(USER_TAG_CARD_OPTIONS)


@router.get("/{user_id}", response_model=PublicUserOut, summary="获取指定用户信息")
async def get_user_by_id(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
) -> User:
    """根据用户ID获取用户信息。

    Args:
        user_id: 用户ID
        db: 数据库会话

    Returns:
        用户信息
    """
    user = await user_service.get_user_by_id(db, user_id, options=_PUBLIC_USER_OPTIONS)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    # 附加关注统计（优雅降级，避免统计失败导致主接口 500）
    try:
        stats = await _get_follow_stats(db, user_id, current_user)
        for key, value in stats.items():
            setattr(user, key, value)
    except Exception:
        pass
    return user


@router.get("/number/{user_number}", response_model=PublicUserOut, summary="根据用户编号获取用户信息")
async def get_user_by_number(
    user_number: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
) -> User:
    """根据用户编号获取用户信息。

    Args:
        user_number: 用户编号
        db: 数据库会话

    Returns:
        用户信息
    """
    user = await user_service.get_user_by_number(db, user_number, options=_PUBLIC_USER_OPTIONS)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    # 附加关注统计（优雅降级，避免统计失败导致主接口 500）
    try:
        stats = await _get_follow_stats(db, user.id, current_user)
        for key, value in stats.items():
            setattr(user, key, value)
    except Exception:
        pass
    return user


# 用户名 3-50 位：ASCII 字母/数字/下划线，另兼容 CJK 汉字
# （管理员/资料更新不限制字符集，站内可能有中文用户名）
USERNAME_RE = re.compile(
    r"^[A-Za-z0-9_\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]{3,50}$"
)


@router.get("/by-username/{username}", response_model=PublicUserOut, summary="根据用户名获取用户信息")
async def get_user_by_username(
    username: str,
    db: AsyncSession = Depends(get_db),
) -> User:
    """根据用户名获取用户信息。

    讨论区/犇犇里的 @提及 需要指向用户主页，而主页路由用的是用户编号，
    提到的人只给了用户名，所以补上这个入口，避免前端再发一次批量解析请求。
    """
    if not USERNAME_RE.match(username):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    user = await user_service.get_user_by_username(
        db,
        username,
        options=_PUBLIC_USER_OPTIONS,
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    return user


def _oierdb_parse_records(
    records: str, contests: list, schools: list
) -> tuple[str, list[dict]]:
    """解析选手的压缩记录串，返回（最近学校名, 获奖列表）。"""
    awards: list[dict] = []
    school = ""
    latest = -1
    for rec in records.split("/"):
        fields = rec.split(":")
        if len(fields) < 6:
            continue
        try:
            cid = int(fields[0])
            sid = int(fields[1])
            lv = int(fields[5])
        except ValueError:
            continue
        if not (0 <= cid < len(contests)) or not (0 <= lv < len(_OIERDB_AWARD_LEVELS)):
            continue
        contest = contests[cid] if isinstance(contests[cid], dict) else {}
        cname = contest.get("name") or ""
        year = contest.get("year") or 0
        level = _OIERDB_AWARD_LEVELS[lv]
        awards.append({
            "contest": cname,
            "name": cname,
            "year": year,
            "award": level,
            "prize": level,
        })
        if year >= latest:
            latest = year
            if 0 <= sid < len(schools):
                entry = schools[sid]
                if isinstance(entry, list) and entry:
                    school = entry[0] or ""
    return school, awards


async def _oierdb_download() -> tuple[dict, str]:
    """下载 OIerDB 官方静态数据与选手数据集，返回（静态数据, 原始文本）。"""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        last_err: Exception | None = None
        for base in (_OIERDB_API_BASE, _OIERDB_CDN_BASE):
            try:
                s_info = await client.get(
                    base + "/static.info.json", headers={"User-Agent": _OIERDB_UA}
                )
                r_info = await client.get(
                    base + "/result.info.json", headers={"User-Agent": _OIERDB_UA}
                )
                s_info.raise_for_status()
                r_info.raise_for_status()
                s_suf = str(s_info.json().get("sha512") or "")[:7]
                r_suf = str(r_info.json().get("sha512") or "")[:7]
                if not s_suf or not r_suf:
                    raise ValueError("OIerDB 元信息缺少 sha512")
                static_resp = await client.get(
                    f"{base}/static.{s_suf}.json", headers={"User-Agent": _OIERDB_UA}
                )
                result_resp = await client.get(
                    f"{base}/result.{r_suf}.txt", headers={"User-Agent": _OIERDB_UA}
                )
                static_resp.raise_for_status()
                result_resp.raise_for_status()
                static = static_resp.json()
                text = result_resp.content.decode("utf-8", errors="replace")
                return static, text
            except Exception as exc:
                last_err = exc
        raise last_err or RuntimeError("OIerDB 下载失败")


def _oierdb_build(static: dict, text: str) -> dict:
    """把静态数据与选手文本构建成按姓名索引的检索表。"""
    contests = static.get("contests") or []
    schools = static.get("schools") or []
    index: dict[str, list[tuple[str, str]]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",", 8)
        if len(parts) < 9:
            continue
        uid, _initials, person, _gender, _em, _s1, _s2, _cl, records = parts
        if not person:
            continue
        index.setdefault(person, []).append((uid, records))
    return {"contests": contests, "schools": schools, "index": index}


async def _oierdb_get_index() -> dict:
    """获取（带缓存的）OIerDB 检索表。"""
    cache = _oierdb_cache
    if cache["index"] is not None and time.monotonic() - cache["ts"] < _OIERDB_CACHE_TTL:
        return cache
    async with _oierdb_lock:
        if cache["index"] is not None and time.monotonic() - cache["ts"] < _OIERDB_CACHE_TTL:
            return cache
        static, text = await _oierdb_download()
        cache.update(_oierdb_build(static, text))
        cache["ts"] = time.monotonic()
        return cache


@router.get("/oierdb/search", summary="搜索 OIerDB（按真实姓名）")
async def search_oierdb(
    name: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    """基于 OIerDB 官方数据集在服务端检索选手，避免前端跨域与死链。"""
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="姓名不能为空")
    if len(name) > 50:
        raise HTTPException(status_code=400, detail="姓名过长")
    try:
        data = await _oierdb_get_index()
    except Exception:
        return {"items": [], "error": "OIerDB 请求失败，请稍后重试"}
    index: dict = data["index"] or {}
    contests = data["contests"] or []
    schools = data["schools"] or []
    matched: list[tuple[str, str, str]] = []
    exact = index.get(name)
    if exact:
        for uid, records in exact:
            matched.append((name, uid, records))
    else:
        for person, entries in index.items():
            if name in person:
                for uid, records in entries:
                    matched.append((person, uid, records))
            if len(matched) >= 50:
                break
    items: list[dict] = []
    for person, uid, records in matched[:20]:
        school, awards = _oierdb_parse_records(records, contests, schools)
        items.append({
            "id": uid,
            "uid": uid,
            "name": person,
            "school": school,
            "awards": awards,
        })
    return {"items": items}


@router.post("/me/award-certification", summary="提交奖项认证申请")
async def submit_award_certification(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """用户提交奖项认证：需提供 real_name、oierdb_uid、oi_awards。"""
    real_name = (payload.get("real_name") or "").strip()
    oierdb_uid = (payload.get("oierdb_uid") or "").strip()
    oi_awards = payload.get("oi_awards")
    if not real_name:
        raise HTTPException(status_code=400, detail="请填写真实姓名")
    if not oierdb_uid:
        raise HTTPException(status_code=400, detail="请选择 OIerDB 条目")
    if not isinstance(oi_awards, list) or not oi_awards:
        raise HTTPException(status_code=400, detail="请选择至少一项奖项")
    current_user.real_name = real_name
    current_user.oierdb_uid = oierdb_uid
    current_user.oi_awards = oi_awards
    current_user.award_cert_status = "pending"
    current_user.oi_level = None
    await db.commit()
    return {"success": True, "status": "pending"}


@router.delete("/me/award-certification", summary="撤回奖项认证申请")
async def cancel_award_certification(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if current_user.award_cert_status == "approved":
        raise HTTPException(status_code=400, detail="已通过的认证不可撤回")
    current_user.award_cert_status = "none"
    current_user.oierdb_uid = None
    current_user.oi_awards = None
    current_user.oi_level = None
    await db.commit()
    return {"success": True}
