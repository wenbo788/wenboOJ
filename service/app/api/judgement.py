"""陶片放逐 API —— 管理操作日志的公开展示页."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions as perm
from app.core.database import get_db
from app.deps import get_current_user_optional
from app.models.judgement import JudgementLog
from app.models.user import User
from app.utils.ip import get_client_ip
from app.utils.ratelimit import check

router = APIRouter(prefix="/judgement", tags=["judgement"])

# 公开名单接口按 IP 限流：该接口无需登录，且会公示管理员的角色身份
# （含 is_whitelist），需防止脚本高频枚举管理员清单。阈值取得较宽松，
# 正常浏览远达不到，仅拦截抓取行为。
_IP_LIMIT_ADMIN_LIST = (30, 60)  # 30 次 / 60 秒 / IP


def _user_brief(user: User | None) -> Dict[str, Any]:
    """用户简要信息（与参考项目 fetchUsers 查询的字段一致）."""
    if user is None:
        return {
            "id": None,
            "username": "已删除",
            "avatar_url": "",
            "user_tag": "",
            "is_admin": False,
            "is_super_admin": False,
            "is_banned": False,
            "user_number": None,
            "username_color": "",
            "is_cheater": False,
            "can_manage_users": False,
            "can_manage_posts": False,
            "can_manage_problems": False,
            "color_tier": "gray",
            "name_color": "",
        }
    return {
        "id": user.id,
        "username": user.username,
        "avatar_url": user.avatar_url or "",
        "user_tag": user.display_tag,
        "is_admin": bool(user.is_admin),
        "is_super_admin": bool(user.is_super_admin),
        "is_banned": bool(user.is_banned),
        "user_number": user.user_number,
        "username_color": user.username_color or "",
        "is_cheater": bool(user.is_cheater),
        "can_manage_users": bool(user.can_manage_users),
        "can_manage_posts": bool(user.can_manage_posts),
        "can_manage_problems": bool(user.can_manage_problems),
        "color_tier": user.color_tier or "gray",
        "name_color": user.name_color,
    }


def _log_dict(log: JudgementLog) -> Dict[str, Any]:
    return {
        "id": log.id,
        "admin_id": log.admin_id,
        "target_user_id": log.target_user_id,
        "action_type": log.action_type,
        "action_detail": log.action_detail or {},
        "reason": log.reason or "",
        "created_at": log.created_at.isoformat() if log.created_at else None,
        "admin": _user_brief(log.admin),
        "target_user": _user_brief(log.target_user),
    }


@router.get("/logs")
async def get_judgement_logs(
    page: int = Query(0, ge=0),
    page_size: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> Dict[str, Any]:
    """分页获取陶片放逐日志（按时间倒序）。登录即可浏览。"""
    result = await db.execute(
        select(JudgementLog)
        .order_by(JudgementLog.created_at.desc(), JudgementLog.id.desc())
        .offset(page * page_size)
        .limit(page_size + 1)  # 多取一条判断 has_more
    )
    logs = result.scalars().unique().all()

    has_more = len(logs) > page_size
    logs = logs[:page_size]

    return {
        "logs": [_log_dict(log) for log in logs],
        "has_more": has_more,
        "page": page,
        # 是否可删除陶片（秩序管理权限，走权限真源：白名单/超管/社管）
        "can_manage": bool(current_user is not None and perm.can_manage_community(current_user)),
    }


@router.delete("/logs/{log_id}")
async def delete_judgement_log(
    log_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_optional),
) -> Dict[str, Any]:
    """删除单条陶片（需要秩序管理权限 can_manage_community）。"""
    if current_user is None:
        raise HTTPException(status_code=401, detail="未登录")
    # 走权限真源：白名单 / 超管 / 社管均可删。
    # 此前判的是裸字段 can_manage_posts，导致超管、白名单被 403，
    # 与「管理名单」页公示的权限不一致。
    if not perm.can_manage_community(current_user):
        raise HTTPException(status_code=403, detail="需要秩序管理权限")

    result = await db.execute(select(JudgementLog).where(JudgementLog.id == log_id))
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="日志不存在")

    await db.delete(log)
    await db.commit()
    return {"success": True}


@router.get("/admins", summary="管理名单（公开公示）")
async def admin_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """列出真正持有「用户 / 秩序 / 题目 / Tag」管理权限的用户，供管理名单页公示。

    无需登录；按用户编号升序；**按客户端 IP 限流**（见 ``_IP_LIMIT_ADMIN_LIST``）。

    四列的值**按权限真源算**，不是数据库里那几个原始字段：白名单/超管/大管
    天然具备这些能力，普通管理员则看各自被授予的字段。这样公示出来的名单
    和实际能不能干活是同一套口径（以前公示只看原始字段，会出现「名单里有他、
    实际干不了」或者「实际能管、名单上没有」）。

    实现上先按「字段 + 角色列」筛出候选集（否则白名单/超管/大管会因字段为
    false 而被漏掉），再用 :mod:`app.permissions` 的真源函数逐人判定；判定
    口径统一复用 :func:`app.permissions.is_any_admin`（站内「能进后台」的真源，
    含 ``is_admin`` 泛管理员）——否则仅 ``is_admin=True`` 的账号会从名单里消失，
    而它其实仍能调用后台接口，等于又制造一次「名单与实际权限不一致」。

    各列真源口径为「白名单 / 超管 / 大管，或持有对应字段」——``can_manage_tags``
    同样包含持该裸字段的用户。
    """
    # 防枚举：公开接口 + 角色身份公示，按 IP 限流（阈值宽松，不碍正常浏览）
    ok, wait = check(
        f"ip:judgement-admins:{get_client_ip(request)}", *_IP_LIMIT_ADMIN_LIST
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"请求过于频繁，请 {wait} 秒后再试",
            # RFC 6585 §1.1：429 应带 Retry-After，便于客户端/CDN 自动退避
            headers={"Retry-After": str(wait)},
        )
    rows = (await db.execute(
        select(User)
        .where(or_(
            User.can_manage_users == True,     # noqa: E712
            User.can_manage_posts == True,     # noqa: E712
            User.can_manage_problems == True,  # noqa: E712
            User.can_manage_tags == True,      # noqa: E712
            User.is_super_admin == True,       # noqa: E712
            User.is_big_admin == True,         # noqa: E712
            # 泛管理员同样能进后台，候选集必须覆盖，否则会被下面的
            # is_any_admin 过滤口径「捞不到」而静默漏人
            User.is_admin == True,             # noqa: E712
            User.user_number.in_(perm.SUPER_ADMIN_UIDS),
        ))
        .order_by(User.user_number)
        # 防御性上界：管理员数量现实里是几十量级，这里给个宽松封顶，
        # 避免数据异常（例如某字段被批量置真）时一次性把整张表拉进内存
        .limit(500)
    )).scalars().all()

    # 注意：下面 brief() 返回的 ``can_manage_*`` 是**真源解析后的有效权限**
    # （同名字段在 forum.py / 前端 permissions.ts 中仍是裸 DB 字段，语义不同），
    # 仅供管理名单页分列渲染，**不得作为后端鉴权依据**——鉴权请统一走
    # :mod:`app.permissions`。
    def brief(u: User) -> Dict[str, Any]:
        return {
            "id": u.id,
            "username": u.username,
            "avatar_url": u.avatar_url or "",
            "user_tag": u.display_tag,
            "user_number": u.user_number,
            # 与 is_big_admin 同构：统一用层级函数，避免白名单账号呈现
            # 「is_super_admin=false 但实际是更高层级」的语义混淆
            "is_super_admin": perm.is_super_admin(u),
            # 用真源层级函数（「大管（不含更高层级）」），避免白名单/超管
            # 同时被标成大管而与前端展示口径冲突
            "is_big_admin": perm.is_big_admin(u),
            # 注意：本接口无需登录，``is_whitelist`` 会向访客公开「该账号是 UID
            # 白名单成员」这一身份。管理名单页本身就是公示管理员职责的公开页面，
            # 白名单属于最高管理角色，公示其身份与技术选型一致；此字段不包含任何
            # 凭据或隐私数据，故按现有设计保留。
            # 决策依据与风险评估见 docs/security/design-decisions.md（ADR-001）。
            "is_whitelist": perm.is_white_list(u),
            # 用户名显示色：由后端统一算好，前端各处才不会各算一套
            "name_color": u.name_color,
            "is_admin": bool(u.is_admin),
            # 这四项是「能不能干」，不是原始字段（仅供展示，勿作鉴权）
            "can_manage_users": perm.can_manage_users(u),
            "can_manage_posts": perm.can_manage_community(u),
            "can_manage_problems": perm.can_manage_problems(u),
            "can_manage_tags": perm.can_manage_tags(u),
        }

    # 过滤口径与 is_any_admin 对齐：它包含 is_admin / can_manage_users 等
    # 「能进后台」的全部来源，避免出现「公示漏人但仍可调后台」的矛盾
    return {"admins": [brief(u) for u in rows if perm.is_any_admin(u)]}
