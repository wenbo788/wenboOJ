"""User persistence operations."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.security import hash_password
from app.models.tag_card import UserTagCard
from app.models.user import User
from app.schemas.user import UserCreate

# 下发用户资料时必须带上的 eager load（唯一口径，别再各写一份）。
#
# 为什么：UserOut / SelfUserOut / PublicUserOut / UserAdminResponse 都含
# ``tag_cards``，而 ``UserTagCardOut.granter_name`` 要读 ``UserTagCard.granter``，
# 后者是 ``lazy="raise"``（见 models/tag_card.py 的说明）。所以**任何**把带卡用户
# 丢给这些响应模型的查询都必须显式带出授予人：漏了不会退化成一次懒加载，而是
# 序列化时直接抛 ``InvalidRequestError: 'UserTagCard.granter' is not available
# due to lazy='raise'`` → 整个请求 500（列表接口里只要有一个戴卡用户，
# 整页就出不来）。注意 lazy="raise" 对 granter_id 为空的卡（商店购买）同样会抛，
# 所以不是「只有管理员授予的卡」才触发。
#
# ⚠️ 只能在「用完就序列化返回」的查询上用，别放进 get_current_user 那种
# 每个请求都走的入口：joinedload 出来的授予人 User 进身份映射时**自己的
# tag_cards 没被加载**（自引用急切链会被递归守卫截断）。此后同一请求里任何
# db.get(User, 授予人) 都会命中这个半成品实例，再读 display_tag 就是同步懒加载
# → async 下 MissingGreenlet 500。这正是 #90 修私信 500 时踩过的坑。
USER_TAG_CARD_OPTIONS = (
    selectinload(User.tag_cards).joinedload(UserTagCard.granter),
)


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_id_for_payload(db: AsyncSession, user_id: int) -> User | None:
    """按 id 取用户，并保证 ``tag_cards.granter`` 已加载（响应要 granter_name）。

    用 ``populate_existing`` 是必须的：``get_current_user`` 往往已经把同一个 User
    加载进身份映射了（那份没带授予人），不覆盖的话这条查询会原样返回旧实例，
    granter 依旧缺失、序列化照样 500。
    """
    result = await db.execute(
        select(User)
        .options(*USER_TAG_CARD_OPTIONS)
        .where(User.id == user_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_identifier(db: AsyncSession, identifier: str) -> User | None:
    """Look up by username OR email in a single query (used at login)."""
    result = await db.execute(
        select(User).where(
            (User.username == identifier) | (User.email == identifier)
        )
    )
    return result.scalar_one_or_none()


async def allocate_user_number(db: AsyncSession) -> int:
    """顺序分配：取最小未占用的用户编号 UID（从 1 开始递增）。"""
    result = await db.execute(
        select(User.user_number).order_by(User.user_number)
    )
    used_numbers = set(result.scalars().all())
    user_number = 1
    while user_number in used_numbers:
        user_number += 1
    return user_number


async def create_user(db: AsyncSession, data: UserCreate) -> User:
    """Create a user, raising 409 on a username/email conflict.

    The pre-check is a courtesy for nicer messages; the ``IntegrityError``
    handler is the real guarantee against concurrent-registration races.
    """
    existing = (
        await db.execute(
            select(User).where(
                (User.username == data.username) | (User.email == data.email)
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already registered",
        )

    user = User(
        username=data.username,
        email=data.email,
        hashed_password=hash_password(data.password),
        # user_number 为 NOT NULL UNIQUE，缺省插入会触发 IntegrityError
        # 并被下方 except 误报为「用户名或邮箱已注册」
        user_number=await allocate_user_number(db),
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        # Unique-violation race: the only unique constraints here are
        # username/email, so any conflict -> 409. DB-agnostic (works on both
        # PostgreSQL pgcode 23505 and SQLite, which has no such code).
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already registered",
        ) from exc
    await db.commit()
    await db.refresh(user)
    return user
