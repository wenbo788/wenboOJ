"""管理员API - 支持原管理后台的所有功能"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from typing import Optional, List, Dict, Any

from app.core.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.models.judgement import JudgementLog
from app.services.auth import revoke_user_tokens
from app import permissions as perm

router = APIRouter(prefix="/admin", tags=["admin"])


async def check_admin_permission(current_user: User) -> User:
    """检查管理员权限（任意管理角色）"""
    if not perm.is_any_admin(current_user):
        raise HTTPException(
            status_code=403,
            detail="你没有权限"
        )
    return current_user


def format_user_for_original(user: User) -> Dict[str, Any]:
    """格式化用户数据为原系统期望的格式"""
    return {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "user_number": user.user_number,
        "phone": user.phone,
        "is_active": user.is_active,
        "is_banned": user.is_banned,
        "is_cheater": user.is_cheater,
        "is_super_admin": user.is_super_admin,
        "is_big_admin": getattr(user, "is_big_admin", False),
        "is_admin": user.is_admin,
        "can_speak": user.can_speak,
        "can_manage_users": user.can_manage_users,
        "can_manage_posts": user.can_manage_posts,
        "can_manage_problems": getattr(user, 'can_manage_problems', False),
        "can_assign_admin": getattr(user, 'can_assign_admin', False),
        "experience": getattr(user, 'experience', 0),
        "avatar_url": user.avatar_url,
        "user_tag": user.user_tag,
        "display_tag": user.display_tag,
        "username_color": user.username_color,
        "color_tier": getattr(user, 'color_tier', 'gray'),
        "name_color": getattr(user, "name_color", ""),
        "bio": user.bio,
        "speak_until": user.speak_until.isoformat() if getattr(user, 'speak_until', None) else None,
        "malicious_report_count": getattr(user, 'malicious_report_count', 0),
        "content_violation_count": getattr(user, 'content_violation_count', 0),
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        "last_online": getattr(user, 'last_online', None)
    }


@router.get("/users/online")
async def get_online_users(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取活跃用户列表（近似值，非真实在线状态）。

    ⚠️ 系统目前没有在线状态跟踪（无心跳/最后活跃时间列），
    这里返回的是「未封禁且已激活的前 100 个用户」，仅供运营粗略参考，
    ``approximate=True`` 明确告知调用方这不是精确在线数，
    避免有人把被 limit(100) 截断的 online_count 当成真实在线人数做决策。
    """
    await check_admin_permission(current_user)

    # 由于系统没有在线状态跟踪，这里返回所有未封禁的活跃用户
    # （selectinload 是给 display_tag 用的：它要读 tag_cards，
    #   不预加载就会触发同步懒加载，async 下直接 500）
    result = await db.execute(
        select(User)
        .options(selectinload(User.tag_cards))
        .where(
            User.is_active == True,
            User.is_banned == False
        ).limit(100)
    )
    users = result.scalars().all()

    return {
        "online_users": [format_user_for_original(user) for user in users],
        "online_count": len(users),
        "approximate": True,
        "note": "近似活跃用户列表（上限 100），非真实在线状态",
    }


@router.post("/users/batch")
async def batch_update_users(
    payload: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """批量更新用户（reason 非空时写入陶片放逐日志）"""
    # 权限检查：统一走真源 —— 白名单/超管，或持有 can_manage_users 字段的人
    # （这个字段就是「管理名单」里用户管理那一列的公示依据，认它才一致）
    if not perm.can_manage_users(current_user):
        raise HTTPException(status_code=403, detail="你没有权限")

    user_numbers = payload.get("user_numbers") or []
    updates = payload.get("updates") or {}
    reason = payload.get("reason")

    # 超级管理是固定身份：拒绝任何针对 is_super_admin 的修改
    if 'is_super_admin' in updates:
        raise HTTPException(status_code=400, detail="超级管理员权限不可修改")

    # 字段级校验：超管只能授予题管/社管，白名单才能授予其他管理角色
    _NORMAL_PERMISSIONS = {'can_speak', 'is_banned', 'is_cheater'}
    _ROLE_FIELD_MAP = {
        'can_manage_problems': 'problem_admin',
        'can_manage_posts': 'community_admin',
        'is_big_admin': 'big_admin',
        'is_admin': 'admin',
        'can_manage_users': 'admin',
        'can_manage_tags': 'admin',
    }
    # 批量可写字段白名单：普通权限 + 角色字段 + 禁言天数
    _ALLOWED_BATCH_FIELDS = _NORMAL_PERMISSIONS | set(_ROLE_FIELD_MAP) | {'mute_days'}

    # 角色字段校验：授予走 can_grant_role，撤销走「白名单/超管」上界。
    # 批量接口无法针对每个目标用户单独调用 can_revoke_role（无单 target 上下文），
    # 因此撤销侧使用「白名单/超管」作为保守上界，与单用户接口撤销侧口径一致。
    for _field, _value in updates.items():
        if _field not in _ALLOWED_BATCH_FIELDS:
            raise HTTPException(status_code=400, detail=f"不支持批量修改字段: {_field}")
        if _field in _ROLE_FIELD_MAP:
            if _value is False:
                if not (perm.is_white_list(current_user) or perm.is_super_admin(current_user)):
                    raise HTTPException(status_code=403, detail="你没有权限")
            else:
                if not perm.can_grant_role(current_user, _ROLE_FIELD_MAP[_field]):
                    raise HTTPException(status_code=403, detail="你没有权限")

    # 理由强制：批量权限操作必须填写理由（保证陶片放逐日志可追溯）
    if not str(reason or '').strip():
        raise HTTPException(status_code=400, detail="批量权限操作必须填写理由")

    # 查询用户
    result = await db.execute(
        select(User).where(User.user_number.in_(user_numbers))
    )
    users = result.scalars().all()

    if not users:
        raise HTTPException(status_code=404, detail="没有找到匹配的用户")

    # 批量操作日志分类（与参考项目 batchAction 逻辑一致）
    field = list(updates.keys())[0] if updates else ''
    new_value = updates.get(field)
    normal_perms = ['can_speak']
    admin_perms = ['is_super_admin', 'is_big_admin', 'is_admin', 'can_manage_users',
                   'can_manage_posts', 'can_manage_problems', 'can_manage_tags']

    if field == 'is_banned':
        action_type = 'unban' if new_value is False else 'ban'
        action_detail: Dict[str, Any] = {
            "changes": [{"permission": field, "new_value": new_value}],
            "category": "normal",
        }
    elif field in normal_perms:
        action_type = 'grant_normal' if new_value else 'revoke_normal'
        action_detail = {
            "changes": [{"permission": field, "new_value": new_value}],
            "category": "normal",
        }
    elif field in admin_perms:
        action_type = 'admin_rotation'
        action_detail = {
            "changes": [{"permission": field, "new_value": new_value}],
            "category": "admin",
        }
    else:
        action_type = 'grant_perm' if new_value else 'revoke_perm'
        action_detail = {"permission": field, "new_value": new_value}

    # 批量撤销自由发言时可带 mute_days ∈ {1,7,14} 限时禁言
    mute_days = updates.get('mute_days')
    batch_speak_until = None
    if updates.get('can_speak') is False and mute_days in (1, 7, 14):
        batch_speak_until = datetime.now(timezone.utc) + timedelta(days=int(mute_days))
    if batch_speak_until is not None:
        changes_list = action_detail.setdefault("changes", [])
        changes_list.append(
            {"permission": "speak_until", "new_value": batch_speak_until.isoformat()}
        )

    updated_users = []
    for user in users:
        # 受保护账号：任何人都不可修改（引用真源常量）
        if user.user_number in perm.PROTECTED_UIDS:
            continue

        # 超级管理员只有白名单能改
        if perm.is_super_admin(user) and not perm.is_white_list(current_user):
            continue

        # 撤销角色时逐用户校验 can_revoke_role（超管不能撤其他超管）
        _has_revoke = any(
            _f in _ROLE_FIELD_MAP and _v is False
            for _f, _v in updates.items()
        )
        if _has_revoke and not perm.can_revoke_role(current_user, user):
            continue

        # 不能批量修改自己
        if user.id == current_user.id:
            continue

        # 更新字段
        for field_name, value in updates.items():
            if field_name == 'mute_days':
                continue
            if hasattr(user, field_name):
                setattr(user, field_name, value)

        # is_admin 聚合同步（= 是否有任一管理能力，与权限真源的 is_any_admin 对齐；
        # can_manage_tags 也算，否则「只在名单 Tag 列里的人」is_admin 会是 False）
        if not (perm.is_white_list(user) or user.is_super_admin or user.is_big_admin):
            user.is_admin = (
                user.can_manage_problems
                or user.can_manage_posts
                or user.can_manage_users
                or user.can_manage_tags
            )

        # 自由发言变更同步 speak_until
        if updates.get('can_speak') is True:
            user.speak_until = None
        elif updates.get('can_speak') is False:
            user.speak_until = batch_speak_until

        updated_users.append(user)

        # 每个目标用户写一条日志（reason 为空时跳过）
        if reason and str(reason).strip():
            db.add(JudgementLog(
                admin_id=current_user.id,
                target_user_id=user.id,
                action_type=action_type,
                action_detail=action_detail,
                reason=str(reason).strip(),
            ))

    # 先把 id 记下来：commit 之后 ORM 实例会过期，再读 user.id / user.updated_at
    # 都会触发**同步**懒加载，在 async 会话里直接 MissingGreenlet（500）
    updated_ids = [u.id for u in updated_users]

    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"批量更新失败: {str(e)}")

    # 封禁即踢下线：吊销被禁用户的全部刷新令牌，现有会话下一请求即失效
    if updates.get('is_banned') is True:
        for uid in updated_ids:
            await revoke_user_tokens(db, uid)

    # 响应要重新查一遍（顺带 selectinload 出 tag_cards，display_tag 要用）：
    # 拿过期实例拼响应就是上面那个 500 的成因——改动其实已经提交了，
    # 前端却收到报错、列表也不刷新，看起来就变成「名单和实际权限对不上」
    fresh = (await db.execute(
        select(User)
        .options(selectinload(User.tag_cards))
        .where(User.id.in_(updated_ids))
    )).scalars().all() if updated_ids else []

    return {
        "success": True,
        "updated_count": len(fresh),
        "data": [format_user_for_original(user) for user in fresh]
    }


@router.get("/stats")
async def get_admin_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取管理后台统计数据"""
    await check_admin_permission(current_user)

    # 用户统计
    total_users_result = await db.execute(select(func.count()).select_from(User))
    total_users = total_users_result.scalar() or 0

    active_users_result = await db.execute(
        select(func.count()).select_from(User).where(User.is_active == True)
    )
    active_users = active_users_result.scalar() or 0

    banned_users_result = await db.execute(
        select(func.count()).select_from(User).where(User.is_banned == True)
    )
    banned_users = banned_users_result.scalar() or 0

    admin_users_result = await db.execute(
        select(func.count()).select_from(User).where(
            or_(User.is_super_admin == True, User.is_admin == True)
        )
    )
    admin_users = admin_users_result.scalar() or 0

    return {
        "total_users": total_users,
        "active_users": active_users,
        "banned_users": banned_users,
        "admin_users": admin_users,
        "online_users": active_users  # 简化处理
    }