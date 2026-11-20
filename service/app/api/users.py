"""用户资源路由：注册、当前用户。"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.messages import user_brief
from app.core.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.schemas.user import SelfUserOut, UserCreate, UserOut
from app.services import auth as auth_service
from app.services import user as user_service
from app.utils.ip import get_client_ip
from app.utils.ratelimit import check

router = APIRouter(prefix="/users", tags=["users"])

# 注册按 IP 限流：防批量造小号（配合 ADR-001 的「强密码对冲喷洒」）。
# 与 extended_auth 的 /auth/register 同一思路，但此处是前端实际使用的注册入口。
_IP_LIMIT_REGISTER = (10, 60)  # 10 次 / 60 秒 / IP


@router.post(
    "",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="注册用户",
)
async def create_user(
    payload: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """注册一个新用户（创建 users 资源）。

    用户名与邮箱均需唯一；密码以 bcrypt 哈希存储。重复注册返回 409。
    按客户端 IP 限流（见 ``_IP_LIMIT_REGISTER``），防批量造小号。
    """
    ok, wait = check(f"ip:register:{get_client_ip(request)}", *_IP_LIMIT_REGISTER)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"注册过于频繁，请 {wait} 秒后再试",
            # RFC 6585 §1.1：429 应带 Retry-After，便于客户端自动退避
            headers={"Retry-After": str(wait)},
        )
    return await auth_service.register_user(db, payload)


@router.get("/me", response_model=SelfUserOut, summary="获取当前用户")
async def read_current_user(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """返回当前已登录用户的信息。

    ``/users/me`` 是「当前用户」的别名；将来若新增 ``/users/{id}``，本路由
    须声明在其之前，以免 ``me`` 被当作 id 捕获。

    这里刻意重新查一次（而不是直接返回 current_user）：响应要下发
    ``tag_cards[].granter_name``，而 get_current_user 那份实例没带授予人
    （理由见 services/user.py 的 USER_TAG_CARD_OPTIONS）。
    """
    return await user_service.get_user_by_id_for_payload(db, current_user.id)


@router.post("/me/seen", summary="心跳上报在线状态")
async def heartbeat_seen(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新当前用户的 last_seen（管理后台在线状态判断依据，60秒内视为在线）。"""
    current_user.last_seen = datetime.now(UTC)
    await db.commit()
    return {"success": True}


@router.get("/search", summary="搜索用户")
async def search_users(
    q: str = Query(..., min_length=1, max_length=50, description="UID 或用户名片段"),
    limit: int = Query(10, ge=1, le=20),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """按 UID 或用户名模糊搜索用户（NLNOC 私信「+」入口用）。

    - 返回的字段与私信会话里的 peer 完全同形，前端拿到即可直接开聊；
    - 不返回邮箱/手机号；排除自己与已停用账号；
    - 按「用户名完全匹配 > 更短用户名 > UID」排序，精确命中排最前。
    """
    term = q.strip()
    if not term:
        return {"items": []}

    ok, wait = check(f"user-search:{current_user.id}", 30, 10)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"搜索太频繁，请 {wait} 秒后再试",
            # 同上：429 附标准 Retry-After
            headers={"Retry-After": str(wait)},
        )

    conds = [User.username.ilike(f"%{term}%")]
    if term.isdigit():
        conds.append(User.user_number == int(term))

    stmt = (
        select(User)
        .where(
            User.id != current_user.id,
            User.is_active.is_(True),
            or_(*conds),
        )
        .order_by(
            case((func.lower(User.username) == term.lower(), 0), else_=1),
            func.length(User.username),
            User.user_number,
        )
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [user_brief(u) for u in rows]}
