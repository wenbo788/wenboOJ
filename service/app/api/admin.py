"""管理后台API"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, desc, or_, func as sa_func

from app.core.database import get_db
from app.deps import get_current_user, get_current_user_optional
from app.models.user import User
from app.models.judgement import JudgementLog
from app.models.team import Team, TeamMember
from app.models.user_history import UsernameHistory, UserTagHistory
from app.schemas.user import UserAdminUpdate, UserAdminResponse
from app.services.auth import revoke_user_tokens
from app.services.user import USER_TAG_CARD_OPTIONS
from app import permissions as perm

router = APIRouter(prefix="/admin", tags=["admin"])

# ================================================================
# 权限变更分类（与参考项目 analyzePermissionChanges 逻辑一致）
# ================================================================
NORMAL_PERMS = ["can_speak"]
# 管理类权限字段（用于陶片放逐日志分类，不用于权限判断本身）
ADMIN_PERMS = [
    "is_super_admin", "is_big_admin", "is_admin",
    "can_manage_users", "can_manage_posts",
    "can_manage_problems", "can_manage_tags",
]


def analyze_permission_changes(changes: dict) -> dict:
    """把权限变更分类为普通/管理的授予与撤销."""
    normal_grants: list = []
    normal_revokes: list = []
    admin_grants: list = []
    admin_revokes: list = []

    for field, value in changes.items():
        change_info = {"permission": field, "new_value": value}

        if field == "is_banned":
            # is_banned 逻辑是反的：false = 授予进入主站
            if value is False:
                normal_grants.append(change_info)
            else:
                normal_revokes.append(change_info)
        elif field in NORMAL_PERMS:
            if value is True:
                normal_grants.append(change_info)
            else:
                normal_revokes.append(change_info)
        elif field in ADMIN_PERMS:
            if value is True:
                admin_grants.append(change_info)
            else:
                admin_revokes.append(change_info)

    return {
        "normal_grants": normal_grants,
        "normal_revokes": normal_revokes,
        "admin_grants": admin_grants,
        "admin_revokes": admin_revokes,
    }


def determine_action_type(changes: dict) -> tuple[str, dict]:
    """根据变更内容确定日志 action_type 与 action_detail.

    返回 (action_type, action_detail)；普通与管理权限混合时抛出 ValueError。
    """
    only_cheater_change = len(changes) == 1 and "is_cheater" in changes
    only_banned_change = len(changes) == 1 and "is_banned" in changes

    analyzed = analyze_permission_changes(changes)
    has_normal = bool(analyzed["normal_grants"] or analyzed["normal_revokes"])
    has_admin = bool(analyzed["admin_grants"] or analyzed["admin_revokes"])

    if has_normal and has_admin:
        raise ValueError("不能同时修改普通权限和管理权限，请分别操作")

    if only_cheater_change:
        action_type = "brown_penalty" if changes["is_cheater"] else "unbrown"
        detail = {
            "changes": [{"permission": "is_cheater", "new_value": changes["is_cheater"]}],
            "category": "cheater",
        }
    elif only_banned_change:
        if changes["is_banned"] is False:
            action_type, detail = "unban", {
                "changes": [{"permission": "is_banned", "new_value": False}],
                "category": "normal",
            }
        else:
            action_type, detail = "ban", {
                "changes": [{"permission": "is_banned", "new_value": True}],
                "category": "normal",
            }
    elif has_normal:
        if analyzed["normal_grants"] and not analyzed["normal_revokes"]:
            action_type, detail = "grant_normal", {
                "changes": analyzed["normal_grants"], "category": "normal"}
        elif analyzed["normal_revokes"] and not analyzed["normal_grants"]:
            action_type, detail = "revoke_normal", {
                "changes": analyzed["normal_revokes"], "category": "normal"}
        else:
            action_type, detail = "ostracism", {
                "changes": analyzed["normal_grants"] + analyzed["normal_revokes"],
                "category": "normal",
            }
    elif has_admin:
        action_type, detail = "admin_rotation", {
            "changes": analyzed["admin_grants"] + analyzed["admin_revokes"],
            "category": "admin",
        }
    else:
        # 没有可记录的权限变更（例如只改了备注等字段），不写日志
        action_type, detail = "", {}

    return action_type, detail


async def insert_judgement_log(
    db: AsyncSession,
    admin_id: int,
    target_user_id: int,
    action_type: str,
    action_detail: dict,
    reason: Optional[str],
) -> None:
    """写入一条陶片放逐日志（reason 为空时不记录，与参考项目一致）."""
    if not reason or not str(reason).strip():
        return
    db.add(JudgementLog(
        admin_id=admin_id,
        target_user_id=target_user_id,
        action_type=action_type,
        action_detail=action_detail,
        reason=str(reason).strip(),
    ))


@router.post("/users/id/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """重置指定用户密码。请求体：{password: "新密码"}"""
    if not perm.can_reset_password(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="你没有权限"
        )

    new_password = payload.get("password") or ""
    if not new_password or not (6 <= len(new_password) <= 72):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密码长度需为 6-72 位"
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    # 0/1/68 号为受保护账号：任何人都不可修改
    if user.user_number in perm.PROTECTED_UIDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="0/1/68 号账号受保护，不可修改"
        )

    from app.core.security import hash_password
    user.hashed_password = hash_password(new_password)

    # 清除该用户全部刷新令牌：现有登录态到期（≤30分钟）后无法续期，强制下线
    from app.models.refresh_token import RefreshToken
    await db.execute(delete(RefreshToken).where(RefreshToken.user_id == user.id))

    await db.commit()

    return {"message": "密码重置成功，该用户的登录状态已失效"}


@router.get("/users", response_model=List[UserAdminResponse])
async def get_users(
    limit: int = Query(20, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> List[UserAdminResponse]:
    """获取用户列表（需要管理员权限）"""

    # 权限检查：用户列表，任意管理员可访问
    if not perm.is_any_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="你没有权限"
        )

    # 响应含 tag_cards（卡上要 granter_name），必须显式带出授予人：
    # UserTagCard.granter 是 lazy="raise"，漏了整页 500（列表里一个戴卡用户就够）
    query = select(User).options(*USER_TAG_CARD_OPTIONS)

    # 搜索功能
    if search:
        search_pattern = f"%{search}%"
        query = query.where(
            or_(
                User.username.ilike(search_pattern),
                User.email.ilike(search_pattern),
                User.user_number == int(search) if search.isdigit() else False
            )
        )

    query = query.order_by(User.user_number).offset(offset).limit(limit)
    result = await db.execute(query)
    users = result.scalars().all()

    return [UserAdminResponse.model_validate(user) for user in users]


@router.get("/users/{user_number}", response_model=UserAdminResponse)
async def get_user_by_number(
    user_number: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> UserAdminResponse:
    """获取单个用户信息（含 PII，任意管理员可访问）"""
    if not perm.is_any_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="你没有权限"
        )

    result = await db.execute(
        select(User).options(*USER_TAG_CARD_OPTIONS)
        .where(User.user_number == user_number)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )

    return UserAdminResponse.model_validate(user)


@router.put("/users/{user_number}", response_model=UserAdminResponse)
async def update_user(
    user_number: int,
    user_update: UserAdminUpdate,
    reason: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> UserAdminResponse:
    """更新用户信息（需要管理员权限）"""

    # 查询目标用户。这里的实例最后要直接喂给 UserAdminResponse（响应含
    # tag_cards[].granter_name），所以同样得带上授予人 eager load：
    # 否则「保存一个戴卡用户的资料」会 500，而库里的改动其实已经提交了。
    result = await db.execute(
        select(User).options(*USER_TAG_CARD_OPTIONS)
        .where(User.user_number == user_number)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )

    # 权限检查：使用真源 can_modify_user（白名单/大管可改普通用户，超管不可改）
    if not perm.can_modify_user(current_user, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="你没有权限"
        )

    # 0/1/68 号为受保护账号：任何人都不可修改
    if user.user_number in perm.PROTECTED_UIDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="0/1/68 号账号受保护，不可修改"
        )

    # 不能修改自己
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能修改自己"
        )

    # 超级管理员只有白名单能改（UID=2 历史例外：其普通资料仍可由管理权限修改）
    if (
        perm.is_super_admin(user)
        and user.user_number != 2
        and not perm.is_super_admin(current_user)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="你没有权限"
        )

    # 超级管理是固定身份：仅白名单可任命/撤销超管
    if user_update.is_super_admin is not None:
        if not perm.is_white_list(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="你没有权限"
            )

    # 更新用户信息
    update_data = user_update.model_dump(exclude_unset=True)

    # 理由强制：涉及权限/封禁类字段的更新必须填写理由（保证可追溯）
    perm_like = {
        "is_admin", "is_banned", "is_cheater", "can_speak",
        "can_manage_users", "can_manage_posts", "can_manage_problems", "can_manage_tags",
    }
    if set(update_data) & perm_like and not str(reason or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="权限操作必须填写理由"
        )

    old_username = user.username
    for field, value in update_data.items():
        if field == "user_tag":
            continue
        if hasattr(user, field):
            setattr(user, field, value)

    old_tag = user.user_tag
    # 管理员在后台直接设置头衔时，摘下原佩戴的 Tag 卡，使新头衔即刻生效
    if "user_tag" in update_data:
        raw_tag = update_data["user_tag"]
        cleaned_tag = raw_tag.strip() if (raw_tag and str(raw_tag).strip()) else None
        if cleaned_tag != old_tag:
            user.user_tag = cleaned_tag
            if cleaned_tag:
                for c in (user.tag_cards or []):
                    c.enabled = False
            db.add(UserTagHistory(
                user_id=user.id,
                operator_id=current_user.id,
                action="custom_tag",
                tag_name=cleaned_tag or "(清除头衔)",
            ))

    # 管理员改名也重置 30 天冷却并留痕
    if update_data.get("username") and update_data["username"] != old_username:
        from datetime import datetime, timezone
        user.last_username_change = datetime.now(timezone.utc)
        db.add(UsernameHistory(
            user_id=user.id,
            operator_id=current_user.id,
            old_username=old_username,
            new_username=update_data["username"],
        ))

    await db.commit()
    await db.refresh(user)

    return UserAdminResponse.model_validate(user)


@router.post("/users/{user_number}/permissions")
async def update_user_permissions(
    user_number: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """更新用户权限（需要管理员权限）。

    请求体两种格式：
      - {changes: {field: value, ...}, reason: "原因"}   （推荐，会记录陶片放逐日志）
      - {field: value, ...}                               （兼容旧格式，不记录日志）
    """
    # 兼容两种请求格式
    if "changes" in payload and isinstance(payload["changes"], dict):
        changes = dict(payload["changes"])
        reason = payload.get("reason")
    else:
        changes = {k: v for k, v in payload.items() if k != "reason"}
        reason = None

    # 限时禁言参数单独取出：它是 can_speak 的附属参数，不是独立权限字段。
    # 必须在 determine_action_type 之前取出，避免干扰普通/管理权限分类。
    mute_days = changes.pop("mute_days", None)
    if mute_days is not None and mute_days not in (1, 7, 14):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="禁言天数只支持 1 / 7 / 14，不带天数为永久禁言",
        )

    # 超级管理是固定身份：任命/撤销超管仅白名单可做；
    # UID=2 是历史遗留例外目标，其 is_super_admin 字段本身不可改（400）。
    # 该判定需要目标用户上下文，放在下方查询之后。

    # 权限检查：白名单/超管/旧版用户管理权限均可修改用户权限。
    # 过渡期兼容：can_manage_users 是旧后台字段，迁移完成前放行。
    if not (
        perm.is_white_list(current_user)
        or perm.is_super_admin(current_user)
        or getattr(current_user, "can_manage_users", False)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="你没有权限"
        )

    # 查询目标用户
    result = await db.execute(select(User).where(User.user_number == user_number))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )

    # 0/1/68 号为受保护账号：任何人都不可修改
    if user_number in perm.PROTECTED_UIDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="0/1/68 号账号受保护，不可修改"
        )

    # 不能修改自己的权限
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能修改自己的权限"
        )

    # 超级管理员目标（UID=2 除外）：非超管不可修改其权限
    if (
        perm.is_super_admin(user)
        and user.user_number != 2
        and not perm.is_super_admin(current_user)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="不能修改超级管理员权限"
        )

    # is_super_admin 字段本身：UID=2 固定身份不可改（400）；
    # 其余目标仅白名单可任命/撤销
    if "is_super_admin" in changes:
        if user.user_number == 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="超级管理员权限不可修改"
            )
        if not perm.is_white_list(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="只有白名单可以任命/撤销超级管理员"
            )

    # 分类校验（普通权限与管理权限不能同时修改）
    try:
        action_type, action_detail = determine_action_type(changes)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    # 理由强制：不填理由的权限操作直接拒绝（保证陶片放逐日志可追溯）
    if not (reason and str(reason).strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="权限操作必须填写理由",
        )

    # 更新权限（授予用户/秩序管理不再自动附带进入后台 is_admin，
    # 紫名与后台身份严格以 is_admin 为准）
    apply_changes = dict(changes)

    # 非角色字段（普通权限）：函数入口已校验"白名单/超管"，可自由修改
    NORMAL_PERMISSIONS = {
        'can_speak', 'is_banned', 'is_cheater',
    }

    # 角色字段 → 角色名映射（用于 perm.can_grant_role 字段级校验）
    #   - can_manage_problems / can_manage_posts：白名单 + 超管 都可授予
    #   - is_admin / can_manage_users / can_manage_tags：仅白名单可授予
    ROLE_FIELD_MAP = {
        'can_manage_problems': 'problem_admin',
        'can_manage_posts': 'community_admin',
        'is_big_admin': 'big_admin',
        'is_admin': 'admin',
        'can_manage_users': 'admin',
        'can_manage_tags': 'admin',
    }

    for perm_key, value in apply_changes.items():
        # is_super_admin：仅白名单可修改
        if perm_key == 'is_super_admin':
            if not perm.is_white_list(current_user):
                raise HTTPException(status_code=403, detail="你没有权限")
            if hasattr(user, perm_key):
                setattr(user, perm_key, value)
            continue

        # 普通权限
        if perm_key in NORMAL_PERMISSIONS:
            if hasattr(user, perm_key):
                setattr(user, perm_key, value)
            continue

        # 角色字段：授予走 can_grant_role，撤销走 can_revoke_role
        if perm_key in ROLE_FIELD_MAP:
            target_role = ROLE_FIELD_MAP[perm_key]
            if value is False:
                # 撤销：统一走 can_revoke_role（白名单任意；超管可撤非超管目标）
                # 撤销操作比授予宽松，超管可清理 legacy 字段
                if not perm.can_revoke_role(current_user, user):
                    raise HTTPException(status_code=403, detail="你没有权限")
            else:
                if not perm.can_grant_role(current_user, target_role):
                    raise HTTPException(status_code=403, detail="你没有权限")
            if hasattr(user, perm_key):
                setattr(user, perm_key, value)
            continue

        # 其他字段静默忽略
    # 自由发言变更必须同步 speak_until（否则会残留上一次禁言的到期时间）：
    #   恢复发言 → 清空到期时间
    #   撤销发言 + mute_days∈{1,7,14} → 限时禁言
    #   撤销发言且不带 mute_days → 永久禁言（speak_until=None）
    new_speak_until = None
    if apply_changes.get("can_speak") is False and mute_days in (1, 7, 14):
        new_speak_until = datetime.now(timezone.utc) + timedelta(days=int(mute_days))
    if "can_speak" in apply_changes:
        user.speak_until = new_speak_until
        if action_detail is not None:
            action_detail["changes"].append({
                "permission": "speak_until",
                "new_value": new_speak_until.isoformat() if new_speak_until else None,
            })

    # 封禁即踢下线：吊销其全部刷新令牌，现有会话下一请求即失效
    if apply_changes.get("is_banned") is True:
        await revoke_user_tokens(db, user.id)

    if action_type:
        await insert_judgement_log(
            db, current_user.id, user.id, action_type, action_detail, reason
        )

    # is_admin 聚合同步
    if not (perm.is_white_list(user) or user.is_super_admin or user.is_big_admin):
        user.is_admin = (
            user.can_manage_problems
            or user.can_manage_posts
            or user.can_manage_users
        )

    await db.commit()

    return {"message": "权限更新成功"}


@router.get("/award-certifications", summary="待审核奖项认证列表")
async def list_award_certifications(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if not perm.is_super_admin(current_user):
        raise HTTPException(status_code=403, detail="你没有权限")
    rows = (await db.execute(
        select(User).where(User.award_cert_status == "pending")
        .order_by(User.id)
    )).scalars().all()
    return {"items": [{
        "user_number": u.user_number,
        "username": u.username,
        "real_name": u.real_name,
        "oierdb_uid": u.oierdb_uid,
        "oi_awards": u.oi_awards,
    } for u in rows]}


@router.post("/users/{user_number}/award-certification/review",
             summary="审核奖项认证")
async def review_award_certification(
    user_number: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if not perm.is_super_admin(current_user):
        raise HTTPException(status_code=403, detail="你没有权限")
    user = (await db.execute(
        select(User).where(User.user_number == user_number)
    )).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.award_cert_status != "pending":
        raise HTTPException(status_code=400, detail="该用户没有待审核的认证")
    action = (payload.get("action") or "").strip()
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action 需为 approve 或 reject")
    if action == "approve":
        oi_level = (payload.get("oi_level") or "").strip()
        if not oi_level:
            raise HTTPException(status_code=400, detail="通过时需填写 OI 等级")
        user.oi_level = oi_level
        user.award_cert_status = "approved"
    else:
        user.award_cert_status = "rejected"
        user.oi_level = None
    await db.commit()
    return {"success": True, "status": user.award_cert_status}


@router.get("/teams", summary="团队列表（含封禁状态）")
async def list_admin_teams(
    limit: int = Query(20, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """获取团队列表（需要用户管理权限），包含 is_banned 状态与成员数。"""
    if not perm.can_manage_teams(current_user):
        raise HTTPException(status_code=403, detail="你没有权限")

    query = select(Team)
    if search:
        pattern = f"%{search}%"
        query = query.where(Team.name.ilike(pattern))

    total = (await db.execute(
        select(sa_func.count()).select_from(query.subquery())
    )).scalar() or 0

    teams = (await db.execute(
        query.order_by(Team.id.desc()).offset(offset).limit(limit)
    )).scalars().all()

    items = []
    for t in teams:
        mc = (await db.execute(
            select(sa_func.count()).select_from(TeamMember)
            .where(TeamMember.team_id == t.id)
        )).scalar() or 0
        owner = await db.get(User, t.owner_id)
        items.append({
            "id": t.id,
            "name": t.name,
            "description": t.description or "",
            "owner_id": t.owner_id,
            "owner_username": owner.username if owner else "已删除用户",
            "owner_user_number": owner.user_number if owner else None,
            "member_count": mc + 1,  # +1 计入 owner
            "is_banned": bool(t.is_banned),
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.patch("/teams/{team_id}/ban", summary="封禁/解封团队")
async def toggle_team_ban(
    team_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """设置团队封禁状态。请求体：{is_banned: true/false}（需要用户管理权限）。"""
    if not perm.can_manage_teams(current_user):
        raise HTTPException(status_code=403, detail="你没有权限")

    team = (await db.execute(
        select(Team).where(Team.id == team_id)
    )).scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")

    is_banned = payload.get("is_banned")
    if not isinstance(is_banned, bool):
        raise HTTPException(status_code=400, detail="is_banned 需为布尔值")

    team.is_banned = is_banned
    await db.commit()
    return {"id": team.id, "name": team.name, "is_banned": team.is_banned}
