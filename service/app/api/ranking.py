"""经验排行榜 API。

总经验 = 当前经验余额 + 已兑换「经验商店」Tag 卡所消耗的经验。
- 经验商店（SHOP_ITEMS）使用经验兑换，其花费要加回，反映用户累计获得的总经验；
- 贡献商店（CONTRIBUTION_SHOP_ITEMS）使用贡献兑换，不计入经验排名。

实时查询：每次请求直接计算，不做缓存，确保排名与当前数据一致。
"""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func as sa_func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.deps import get_current_user_optional
from app.models.tag_card import UserTagCard
from app.models.user import User
from app.models.battle import UserBattleStats, TIER_NAMES, TIER_ORDER
from app.api.shop import SHOP_ITEMS

router = APIRouter(tags=["ranking"])

# 经验商店 Tag 名 → 价格（贡献商店不计入经验排名）
_EXP_TAG_PRICE: dict[str, int] = {item["name"]: int(item["price"]) for item in SHOP_ITEMS}


def _total_experience(user: User) -> tuple[int, int, int]:
    """返回 (总经验, 经验商店 Tag 卡花费, 用经验购买用户名颜色的花费)。

    用贡献购买颜色的花费不计入总经验（仅经验货币部分加回）。
    """
    spent = sum(
        _EXP_TAG_PRICE.get(c.name, 0)
        for c in (user.tag_cards or [])
    )
    color_spent = user.color_exp_spent or 0
    return (user.experience or 0) + spent + color_spent, spent, color_spent


@router.get("/ranking", summary="经验排行榜（总经验 = 经验 + 经验商店 Tag 花费 + 经验购买颜色花费）")
async def experience_ranking(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(10, ge=1, le=100, description="每页人数"),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> dict:
    users = (await db.execute(
        select(User)
        .where(User.is_active.is_(True))
        .options(selectinload(User.tag_cards))
    )).scalars().all()

    rows: list[dict] = []
    for u in users:
        total, spent, color_spent = _total_experience(u)
        if total <= 0:
            continue  # 没有经验的用户不参与排名
        rows.append({
            "user_id": u.id,
            "user_number": u.user_number,
            "username": u.username,
            "avatar_url": u.avatar_url or "",
            "display_tag": u.display_tag,
            "color_tier": u.color_tier or "gray",
            "name_color": u.name_color,
            # 身份标志位：前端 userNameColor 据此判定黑/棕/紫/青/档位色
            "is_banned": u.is_banned,
            "is_cheater": u.is_cheater,
            "is_admin": u.is_admin,
            "is_super_admin": u.is_super_admin,
            "can_manage_users": u.can_manage_users,
            "can_manage_posts": u.can_manage_posts,
            "can_manage_problems": u.can_manage_problems,
            "can_manage_tags": u.can_manage_tags,
            "experience": u.experience or 0,        # 当前余额
            "tag_experience": spent,                 # 经验商店已兑换花费
            "color_experience": color_spent,         # 用经验购买颜色的花费
            "total_experience": total,               # 排名依据
        })

    # 按总经验降序；同经验按 user_number 升序，保证顺序稳定
    rows.sort(key=lambda r: (-r["total_experience"], r["user_number"]))

    # 计算当前登录用户的排名（未登录或总经验为 0 则返回 null）
    my_rank = None
    if current_user is not None:
        for i, r in enumerate(rows):
            if r["user_id"] == current_user.id:
                my_rank = {
                    "rank": i + 1,
                    "user_number": r["user_number"],
                    "username": r["username"],
                    "total_experience": r["total_experience"],
                    "experience": r["experience"],
                    "tag_experience": r["tag_experience"],
                    "color_experience": r["color_experience"],
                }
                break

    total = len(rows)
    total_pages = max(1, math.ceil(total / page_size))
    # 页码越界兜底：超出最后一页则返回最后一页
    page = min(page, total_pages)
    start = (page - 1) * page_size
    end = start + page_size
    page_rows = rows[start:end]

    # 排名是全局的，不是当前页内的
    for i, r in enumerate(page_rows):
        r["rank"] = start + i + 1
        r.pop("user_id", None)  # 内部字段不返回

    return {
        "items": page_rows,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "my_rank": my_rank,
    }


_ROMAN = {1: "I", 2: "II", 3: "III"}


@router.get("/ranking/battle", summary="对战段位排行榜（按段位排行，相同段位按胜场次排行）")
async def battle_ranking(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(10, ge=1, le=100, description="每页人数"),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = (
        select(User, UserBattleStats)
        .outerjoin(UserBattleStats, User.id == UserBattleStats.user_id)
        .where(User.is_active.is_(True))
    )
    res = await db.execute(stmt)
    records = res.all()

    rows: list[dict] = []
    for user, stats in records:
        tier = stats.tier if stats else "bronze"
        sub_tier = stats.sub_tier if stats else 3
        points = stats.points if stats else 0
        wins = stats.wins if stats else 0
        total_matches = stats.total_matches if stats else 0
        win_streak = stats.win_streak if stats else 0

        # Global rank rating score for tier comparison
        tier_idx = TIER_ORDER.index(tier) if tier in TIER_ORDER else 0
        sub_idx = max(0, 3 - sub_tier)
        rank_score = tier_idx * 300 + sub_idx * 100 + points

        win_rate = round((wins / total_matches * 100), 1) if total_matches > 0 else 0.0
        tier_name = TIER_NAMES.get(tier, "青铜")
        sub_roman = _ROMAN.get(sub_tier, "III")

        rows.append({
            "user_id": user.id,
            "user_number": user.user_number,
            "username": user.username,
            "avatar_url": user.avatar_url or "",
            "display_tag": user.display_tag,
            "color_tier": user.color_tier or "gray",
            "name_color": user.name_color,
            "is_banned": user.is_banned,
            "is_cheater": user.is_cheater,
            "is_admin": user.is_admin,
            "is_super_admin": user.is_super_admin,
            "can_manage_users": user.can_manage_users,
            "can_manage_posts": user.can_manage_posts,
            "can_manage_problems": user.can_manage_problems,
            "can_manage_tags": user.can_manage_tags,
            "tier": tier,
            "tier_name": tier_name,
            "sub_tier": sub_tier,
            "sub_tier_roman": sub_roman,
            "points": points,
            "rank_name": f"{tier_name} {sub_roman}",
            "rank_score": rank_score,
            "total_matches": total_matches,
            "wins": wins,
            "losses": stats.losses if stats else 0,
            "draws": stats.draws if stats else 0,
            "win_rate": win_rate,
            "win_streak": win_streak,
        })

    # 排序规则：先按段位(rank_score)降序；段位相同的按胜场次(wins)降序；再按胜率、连胜降序
    rows.sort(
        key=lambda r: (
            -r["rank_score"],
            -r["wins"],
            -r["win_rate"],
            -r["win_streak"],
            r["user_number"],
        )
    )

    my_rank = None
    if current_user is not None:
        for i, r in enumerate(rows):
            if r["user_id"] == current_user.id:
                my_rank = {
                    "rank": i + 1,
                    "user_number": r["user_number"],
                    "username": r["username"],
                    "rank_name": r["rank_name"],
                    "tier": r["tier"],
                    "points": r["points"],
                    "wins": r["wins"],
                    "total_matches": r["total_matches"],
                    "win_rate": r["win_rate"],
                }
                break

    total = len(rows)
    total_pages = max(1, math.ceil(total / page_size))
    page = min(page, total_pages)
    start = (page - 1) * page_size
    end = start + page_size
    page_rows = rows[start:end]

    for i, r in enumerate(page_rows):
        r["rank"] = start + i + 1
        r.pop("user_id", None)

    return {
        "items": page_rows,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "my_rank": my_rank,
    }



@router.get("/ranking/rating", summary="等级分排行榜（比赛 rated 场次结算后的分）")
async def rating_ranking(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(10, ge=1, le=100, description="每页人数"),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """按 ``users.rating`` 降序；只统计打过至少一场结算赛的人。

    分页**下推到 SQL**（order_by + offset/limit + count）：排行榜不能把全站用户
    拉进内存再排序，人一多就是内存/响应时间放大器。
    """
    base_where = (User.is_active.is_(True), User.rated_contests > 0)

    total = int((await db.execute(
        select(sa_func.count()).select_from(User).where(*base_where)
    )).scalar() or 0)
    total_pages = max(1, math.ceil(total / page_size))
    page = min(page, total_pages)
    offset = (page - 1) * page_size

    users = (await db.execute(
        select(User)
        .where(*base_where)
        # 同分按编号升序，保证顺序稳定、分页不抖
        .order_by(User.rating.desc(), User.user_number.asc())
        .offset(offset)
        .limit(page_size)
        .options(selectinload(User.tag_cards))
    )).scalars().all()

    rows = [{
        "rank": offset + i + 1,
        "user_number": u.user_number,
        "username": u.username,
        "avatar_url": u.avatar_url or "",
        "display_tag": u.display_tag,
        "color_tier": u.color_tier or "gray",
        "name_color": u.name_color,
        "is_banned": u.is_banned,
        "is_cheater": u.is_cheater,
        "is_admin": u.is_admin,
        "is_super_admin": u.is_super_admin,
        "can_manage_users": u.can_manage_users,
        "can_manage_posts": u.can_manage_posts,
        "can_manage_problems": u.can_manage_problems,
        "can_manage_tags": getattr(u, "can_manage_tags", False),
        "rating": u.rating,
        "max_rating": u.max_rating,
        "rated_contests": u.rated_contests,
    } for i, u in enumerate(users)]

    # 我的排名：只查一条 count，不把全站拉进来
    my_rank = None
    if current_user is not None and current_user.rated_contests > 0:
        ahead = int((await db.execute(
            select(sa_func.count()).select_from(User).where(
                User.is_active.is_(True),
                User.rated_contests > 0,
                or_(
                    User.rating > current_user.rating,
                    and_(User.rating == current_user.rating,
                         User.user_number < current_user.user_number),
                ),
            )
        )).scalar() or 0)
        my_rank = {
            "rank": ahead + 1,
            "user_number": current_user.user_number,
            "username": current_user.username,
            "rating": current_user.rating,
            "max_rating": current_user.max_rating,
            "rated_contests": current_user.rated_contests,
        }

    return {
        "items": rows,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "my_rank": my_rank,
    }
