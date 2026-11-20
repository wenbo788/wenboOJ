"""用户资料管理服务。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_history import UsernameHistory
from app.schemas.user import UserProfileUpdate
from app.core.security import verify_password, hash_password
from app.services.user import get_user_by_id_for_payload

# 改名冷却：30 天
USERNAME_CHANGE_COOLDOWN = timedelta(days=30)


async def get_user_by_id(
    db: AsyncSession, user_id: int, *, options: Sequence[Any] | None = None
) -> User | None:
    """根据用户ID获取用户。

    Args:
        db: 数据库会话
        user_id: 用户ID
        options: 额外的 eager load 选项

    Returns:
        用户对象或 None
    """
    stmt = select(User)
    if options:
        stmt = stmt.options(*options)
    result = await db.execute(stmt.where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_number(
    db: AsyncSession, user_number: int, *, options: Sequence[Any] | None = None
) -> User | None:
    """根据用户编号获取用户。

    Args:
        db: 数据库会话
        user_number: 用户编号
        options: 额外的 eager load 选项

    Returns:
        用户对象或 None
    """
    stmt = select(User)
    if options:
        stmt = stmt.options(*options)
    result = await db.execute(stmt.where(User.user_number == user_number))
    return result.scalar_one_or_none()


async def get_user_by_username(
    db: AsyncSession, username: str, *, options: Sequence[Any] | None = None
) -> User | None:
    """根据用户名获取用户。

    @提及 渲染出的主页链接只有用户名（没有用户编号），靠这个入口查。

    ``options`` 用来补 eager load：公开资料接口要下发 Tag 卡上的「授予人名字」，
    而 ``UserTagCard.granter`` 是 lazy="raise"（见该模型注释），不显式带出来
    就会在序列化时才炸。

    Args:
        db: 数据库会话
        username: 用户名
        options: 额外的 eager load 选项

    Returns:
        用户对象或 None
    """
    stmt = select(User)
    if options:
        stmt = stmt.options(*options)
    result = await db.execute(stmt.where(User.username == username))
    return result.scalar_one_or_none()


async def update_user_profile(
    db: AsyncSession,
    user_id: int,
    payload: UserProfileUpdate
) -> User:
    """更新用户资料。

    Args:
        db: 数据库会话
        user_id: 用户ID
        payload: 更新数据

    Returns:
        更新后的用户对象

    Raises:
        ValueError: 用户不存在或数据无效
    """
    # 返回值最终喂给 SelfUserOut（含 tag_cards[].granter_name），且必须用
    # populate_existing 覆盖 get_current_user 已经放进身份映射的那份实例
    user = await get_user_by_id_for_payload(db, user_id)
    if not user:
        raise ValueError("用户不存在")

    # 改名冷却：30 天内只能改一次
    if payload.username and payload.username != user.username:
        if user.last_username_change is not None:
            now = datetime.now(timezone.utc)
            last = user.last_username_change
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            remaining = (last + USERNAME_CHANGE_COOLDOWN) - now
            if remaining.total_seconds() > 0:
                days = int(remaining.total_seconds() // 86400)
                hours = int((remaining.total_seconds() % 86400) // 3600)
                raise ValueError(
                    f"用户名每 30 天只能修改一次，还需等待 {days} 天 {hours} 小时"
                )

        # 检查用户名是否重复
        existing_user = await db.execute(
            select(User).where(User.username == payload.username)
        )
        if existing_user.scalar_one_or_none():
            raise ValueError("用户名已被使用")

    old_username = user.username
    is_renamed = bool(payload.username and payload.username != old_username)

    # 更新字段
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if hasattr(user, field):
            setattr(user, field, value)

    # 改名成功后记录时间与历史
    if is_renamed:
        user.last_username_change = datetime.now(timezone.utc)
        db.add(UsernameHistory(
            user_id=user.id,
            operator_id=user.id,
            old_username=old_username,
            new_username=payload.username,
        ))

    await db.commit()
    await db.refresh(user)

    return user


async def update_user_password(
    db: AsyncSession,
    user_id: int,
    old_password: str,
    new_password: str
) -> None:
    """更新用户密码。

    Args:
        db: 数据库会话
        user_id: 用户ID
        old_password: 旧密码
        new_password: 新密码

    Raises:
        ValueError: 用户不存在或旧密码错误
    """
    user = await get_user_by_id(db, user_id)
    if not user:
        raise ValueError("用户不存在")

    # 验证旧密码
    if not verify_password(old_password, user.hashed_password):
        raise ValueError("旧密码错误")

    # 更新密码
    user.hashed_password = hash_password(new_password)
    await db.commit()


async def check_username_available(db: AsyncSession, username: str) -> bool:
    """检查用户名是否可用。

    Args:
        db: 数据库会话
        username: 用户名

    Returns:
        是否可用
    """
    result = await db.execute(
        select(User).where(User.username == username)
    )
    return result.scalar_one_or_none() is None


async def check_email_available(db: AsyncSession, email: str) -> bool:
    """检查邮箱是否可用。

    Args:
        db: 数据库会话
        email: 邮箱

    Returns:
        是否可用
    """
    result = await db.execute(
        select(User).where(User.email == email)
    )
    return result.scalar_one_or_none() is None


async def check_phone_available(db: AsyncSession, phone: str) -> bool:
    """检查手机号是否可用。

    Args:
        db: 数据库会话
        phone: 手机号

    Returns:
        是否可用
    """
    result = await db.execute(
        select(User).where(User.phone == phone)
    )
    return result.scalar_one_or_none() is None
