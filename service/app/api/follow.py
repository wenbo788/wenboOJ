"""关注/粉丝 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps import get_current_user, get_current_user_optional
from app.models.follow import Follow
from app.models.user import User

router = APIRouter(prefix="/users", tags=["follow"])


def _follow_user_dict(user: User, created_at, is_following: bool) -> dict:
    """粉丝/关注列表项：字段齐全，可供前端 userNameColor() 复算配色。"""
    return {
        "id": user.id,
        "user_number": user.user_number,
        "username": user.username,
        "avatar_url": user.avatar_url or "",
        "user_tag": user.display_tag,
        "color_tier": user.color_tier or "gray",
        "name_color": user.name_color,
        "is_admin": bool(user.is_admin),
        "is_super_admin": bool(user.is_super_admin),
        "is_banned": bool(user.is_banned),
        "is_cheater": bool(user.is_cheater),
        "can_manage_users": bool(user.can_manage_users),
        "can_manage_posts": bool(user.can_manage_posts),
        "can_manage_problems": bool(user.can_manage_problems),
        "can_manage_tags": bool(user.can_manage_tags),
        "is_following": is_following,
        "followed_at": created_at.isoformat() if created_at else None,
    }


@router.post("/{user_id}/follow", summary="关注用户")
async def follow_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """关注指定用户。"""
    if current_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能关注自己",
        )

    # 检查目标用户是否存在
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    # 检查是否已关注
    existing = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.followee_id == user_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="已关注该用户",
        )

    follow = Follow(follower_id=current_user.id, followee_id=user_id)
    db.add(follow)
    await db.commit()
    return {"success": True, "message": f"已关注 {target.username}"}


@router.delete("/{user_id}/follow", summary="取消关注")
async def unfollow_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """取消关注指定用户。"""
    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.followee_id == user_id,
        )
    )
    follow = result.scalar_one_or_none()
    if not follow:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="未关注该用户",
        )

    await db.delete(follow)
    await db.commit()
    return {"success": True, "message": "已取消关注"}


@router.get("/{user_id}/followers", summary="获取粉丝列表")
async def get_followers(
    user_id: int,
    page: int = 0,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """获取指定用户的粉丝列表。"""
    # 检查用户是否存在
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    # 查询粉丝
    query = (
        select(User, Follow.created_at)
        .join(Follow, Follow.follower_id == User.id)
        .where(Follow.followee_id == user_id)
        .order_by(Follow.created_at.desc())
        .offset(page * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    rows = result.all()

    # 统计总数
    count_query = select(func.count()).where(Follow.followee_id == user_id)
    total = (await db.execute(count_query)).scalar() or 0

    followers = []
    for user, created_at in rows:
        is_following = False
        if current_user:
            is_following = await _check_following(db, current_user.id, user.id)
        followers.append(
            _follow_user_dict(user, created_at, is_following))

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "followers": followers,
    }


@router.get("/{user_id}/following", summary="获取关注列表")
async def get_following(
    user_id: int,
    page: int = 0,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """获取指定用户关注的人。"""
    # 检查用户是否存在
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    # 查询关注的人
    query = (
        select(User, Follow.created_at)
        .join(Follow, Follow.followee_id == User.id)
        .where(Follow.follower_id == user_id)
        .order_by(Follow.created_at.desc())
        .offset(page * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    rows = result.all()

    # 统计总数
    count_query = select(func.count()).where(Follow.follower_id == user_id)
    total = (await db.execute(count_query)).scalar() or 0

    following = []
    for user, created_at in rows:
        is_following = False
        if current_user:
            is_following = await _check_following(db, current_user.id, user.id)
        following.append(
            _follow_user_dict(user, created_at, is_following))

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "following": following,
    }


@router.get("/{user_id}/follow-stats", summary="获取关注统计")
async def get_follow_stats(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """获取指定用户的关注/粉丝统计。"""
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    # 粉丝数
    followers_count = (
        await db.execute(
            select(func.count()).where(Follow.followee_id == user_id)
        )
    ).scalar() or 0

    # 关注数
    following_count = (
        await db.execute(
            select(func.count()).where(Follow.follower_id == user_id)
        )
    ).scalar() or 0

    # 当前用户是否关注了该用户
    is_following = False
    if current_user and current_user.id != user_id:
        is_following = await _check_following(db, current_user.id, user_id)

    return {
        "followers_count": followers_count,
        "following_count": following_count,
        "is_following": is_following,
    }


async def _check_following(db: AsyncSession, follower_id: int, followee_id: int) -> bool:
    """检查是否已关注。"""
    result = await db.execute(
        select(Follow.id).where(
            Follow.follower_id == follower_id,
            Follow.followee_id == followee_id,
        )
    )
    return result.scalar_one_or_none() is not None
