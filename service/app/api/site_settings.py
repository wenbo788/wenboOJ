"""站点级配置接口：顶栏公告（announcement）与首页云图栏目（home_cloud）。

存储用 site_settings 键值表（key 唯一，value 为 JSON）。

- GET  /site-settings/announcement  公开读（顶栏要给游客也展示）
- PUT  /site-settings/announcement  管理员写
- GET  /site-settings/home-cloud    管理员读原始配置（站点管理编辑页）
- PUT  /site-settings/home-cloud    管理员写
- GET  /home/cloud  公开读：固定随机卡（友情链接 / 随机题目 / 随机讨论，
  每次请求随机抽 3~4 条）+ 两张可修改卡（精选题目 / 置顶讨论）
"""

from __future__ import annotations

import random
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.deps import get_current_user
from app.models.forum import ForumComment, ForumPost
from app.models.friend_link import FriendLink
from app.models.problem import Problem
from app.models.site_setting import SiteSetting
from app.models.user import User
from app.services.forum import FORUM_NAMES, ForumService

router = APIRouter(tags=["site-settings"])

ANNOUNCEMENT_KEY = "announcement"
HOME_CLOUD_KEY = "home_cloud"

# 云图可修改卡（精选题目 / 置顶讨论）各最多选 4 条；
# 三张固定随机卡每次请求随机抽 RANDOM_CARD_MIN~MAX 条
MAX_POST_IDS = 4
MAX_PROBLEM_IDS = 4
RANDOM_CARD_MIN = 3
RANDOM_CARD_MAX = 4


# ---------------------------------------------------------------- 公告


class AnnouncementItem(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    link: str | None = Field(default=None, max_length=500)

    @field_validator("link")
    @classmethod
    def _no_js_scheme(cls, v: str | None) -> str | None:
        if v is not None and v.strip().lower().startswith("javascript:"):
            raise ValueError("链接协议不允许")
        return v


class AnnouncementConfig(BaseModel):
    enabled: bool = False
    items: list[AnnouncementItem] = Field(default_factory=list, max_length=10)


def _default_announcement() -> dict[str, Any]:
    return {"enabled": False, "items": []}


async def _get_setting(db: AsyncSession, key: str) -> SiteSetting | None:
    row = await db.execute(select(SiteSetting).where(SiteSetting.key == key))
    return row.scalar_one_or_none()


def _require_admin(current_user: User) -> None:
    if not current_user.is_admin and not current_user.is_super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")


@router.get("/site-settings/announcement", summary="读取顶栏公告配置（公开）")
async def get_announcement(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = await _get_setting(db, ANNOUNCEMENT_KEY)
    if row is None or not isinstance(row.value, dict):
        return _default_announcement()
    value = AnnouncementConfig(**row.value)
    return {"enabled": value.enabled, "items": [item.model_dump() for item in value.items]}


@router.put("/site-settings/announcement", summary="保存顶栏公告配置（管理员）")
async def put_announcement(
    payload: AnnouncementConfig,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_admin(current_user)
    normalized = {
        "enabled": payload.enabled,
        "items": [
            {"text": item.text.strip(), "link": (item.link or "").strip() or None}
            for item in payload.items
        ],
    }
    if normalized["enabled"] and not normalized["items"]:
        raise HTTPException(status_code=400, detail="启用公告时至少要有一条内容")

    row = await _get_setting(db, ANNOUNCEMENT_KEY)
    if row is None:
        row = SiteSetting(key=ANNOUNCEMENT_KEY, value=normalized, updated_by_id=current_user.id)
        db.add(row)
    else:
        row.value = normalized
        row.updated_by_id = current_user.id
    await db.commit()
    return {"success": True, **normalized}


# ---------------------------------------------------------------- 首页云图栏目


class CloudFeaturedConfig(BaseModel):
    """可修改卡：精选题目（管理员指定题 id，最多 4 道）"""

    enabled: bool = False
    title: str = Field(default="", max_length=30)
    problem_ids: list[int] = Field(default_factory=list, max_length=MAX_PROBLEM_IDS)


class CloudPinnedConfig(BaseModel):
    """可修改卡：置顶讨论（管理员指定帖子 id，最多 4 条）"""

    enabled: bool = False
    title: str = Field(default="", max_length=30)
    post_ids: list[int] = Field(default_factory=list, max_length=MAX_POST_IDS)


class HomeCloudConfig(BaseModel):
    """首页云图配置 = 板块开关 + 两张可修改卡。

    三张固定卡（友情链接随机 / 随机题目 / 随机讨论）不进配置：
    启用板块就展示，管理员不可修改、不可关闭。
    """

    enabled: bool = False
    featured_problems: CloudFeaturedConfig = Field(default_factory=CloudFeaturedConfig)
    pinned_posts: CloudPinnedConfig = Field(default_factory=CloudPinnedConfig)


def _home_cloud_to_value(cfg: HomeCloudConfig) -> dict[str, Any]:
    return {
        "enabled": cfg.enabled,
        "featured_problems": {
            "enabled": cfg.featured_problems.enabled,
            "title": cfg.featured_problems.title.strip(),
            "problem_ids": list(cfg.featured_problems.problem_ids),
        },
        "pinned_posts": {
            "enabled": cfg.pinned_posts.enabled,
            "title": cfg.pinned_posts.title.strip(),
            "post_ids": list(cfg.pinned_posts.post_ids),
        },
    }


def _default_home_cloud() -> dict[str, Any]:
    return _home_cloud_to_value(HomeCloudConfig())


# 旧版自由卡片的默认标题 → 新版可修改卡的默认叫法（管理员自定义标题原样保留）
_LEGACY_TITLE_MAP = {"热门讨论": "置顶讨论", "推荐题目": "精选题目"}


def _coerce_home_cloud(raw: Any) -> HomeCloudConfig:
    """读库值 → 新结构。

    老版本落库的是 {"cards": [...]} 自由卡片列表，迁移成两张可修改卡
    （posts → 置顶讨论，problems → 精选题目，友链卡由固定随机卡接管），
    管理端下次保存后即转正；解析失败退回默认值。
    """
    if not isinstance(raw, dict):
        return HomeCloudConfig()
    if "pinned_posts" not in raw and "cards" in raw:
        cfg = HomeCloudConfig(enabled=bool(raw.get("enabled")))
        pinned_ids: list[int] = []
        featured_ids: list[int] = []
        pinned_title = ""
        featured_title = ""
        for card in raw.get("cards") or []:
            if not isinstance(card, dict):
                continue
            title = str(card.get("title") or "").strip()
            if card.get("type") == "posts":
                for pid in card.get("post_ids") or []:
                    if (
                        isinstance(pid, int)
                        and pid not in pinned_ids
                        and len(pinned_ids) < MAX_POST_IDS
                    ):
                        pinned_ids.append(pid)
                if title and not pinned_title:
                    pinned_title = _LEGACY_TITLE_MAP.get(title, title)
            elif card.get("type") == "problems":
                for pid in card.get("problem_ids") or []:
                    if (
                        isinstance(pid, int)
                        and pid not in featured_ids
                        and len(featured_ids) < MAX_PROBLEM_IDS
                    ):
                        featured_ids.append(pid)
                if title and not featured_title:
                    featured_title = _LEGACY_TITLE_MAP.get(title, title)
        cfg.pinned_posts = CloudPinnedConfig(
            enabled=bool(pinned_ids), title=pinned_title, post_ids=pinned_ids
        )
        cfg.featured_problems = CloudFeaturedConfig(
            enabled=bool(featured_ids), title=featured_title, problem_ids=featured_ids
        )
        return cfg
    try:
        return HomeCloudConfig(**raw)
    except Exception:
        return HomeCloudConfig(enabled=bool(raw.get("enabled")))


@router.get("/site-settings/home-cloud", summary="读取首页云图栏目配置（管理员）")
async def get_home_cloud(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_admin(current_user)
    row = await _get_setting(db, HOME_CLOUD_KEY)
    return _home_cloud_to_value(_coerce_home_cloud(row.value if row else None))


@router.put("/site-settings/home-cloud", summary="保存首页云图栏目配置（管理员）")
async def put_home_cloud(
    payload: HomeCloudConfig,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_admin(current_user)
    if payload.featured_problems.enabled and not payload.featured_problems.problem_ids:
        raise HTTPException(status_code=400, detail="启用精选题目时至少要选 1 道题")
    if payload.pinned_posts.enabled and not payload.pinned_posts.post_ids:
        raise HTTPException(status_code=400, detail="启用置顶讨论时至少要选 1 个帖子")
    normalized = _home_cloud_to_value(payload)
    row = await _get_setting(db, HOME_CLOUD_KEY)
    if row is None:
        row = SiteSetting(key=HOME_CLOUD_KEY, value=normalized, updated_by_id=current_user.id)
        db.add(row)
    else:
        row.value = normalized
        row.updated_by_id = current_user.id
    await db.commit()
    return {"success": True, **normalized}


# ---------------------------------------------------------------- 公开解析


def _post_brief(post: ForumPost, reply_count: int) -> dict[str, Any]:
    return {
        "id": post.id,
        "title": post.title,
        "forum": post.forum,
        "forum_name": FORUM_NAMES.get(post.forum, post.forum),
        "created_at": post.created_at.isoformat() if post.created_at else None,
        "reply_count": reply_count,
        # 字段口径对齐 ForumService._user_brief，前端展示可直接复用
        "author": ForumService._user_brief(post.author),
    }


async def _posts_briefs(db: AsyncSession, posts: list[ForumPost]) -> list[dict[str, Any]]:
    """给一批帖子补回复数，保持入参顺序。"""
    if not posts:
        return []
    counts_rows = await db.execute(
        select(ForumComment.post_id, func.count())
        .where(
            ForumComment.post_id.in_([p.id for p in posts]),
            ForumComment.is_deleted.is_(False),
        )
        .group_by(ForumComment.post_id)
    )
    counts = {pid: n for pid, n in counts_rows.all()}
    return [_post_brief(post, counts.get(post.id, 0)) for post in posts]


async def _resolve_posts(db: AsyncSession, post_ids: list[int]) -> list[dict[str, Any]]:
    if not post_ids:
        return []
    result = await db.execute(
        select(ForumPost)
        .options(selectinload(ForumPost.author))
        .where(ForumPost.id.in_(post_ids), ForumPost.is_deleted.is_(False))
    )
    posts = {p.id: p for p in result.scalars().unique().all()}
    # 按配置顺序输出
    return await _posts_briefs(db, [posts[pid] for pid in post_ids if pid in posts])


def _problem_brief(p: Problem) -> dict[str, Any]:
    return {
        "id": p.id,
        "problem_number": p.problem_number,
        "title": p.title,
        "difficulty": p.difficulty,
        "tags": p.tags or [],
        "solved_count": p.solved_count,
        "submit_count": p.submit_count,
    }


async def _resolve_problems(db: AsyncSession, problem_ids: list[int]) -> list[dict[str, Any]]:
    if not problem_ids:
        return []
    result = await db.execute(
        select(Problem).where(
            Problem.id.in_(problem_ids),
            Problem.is_public.is_(True),
            Problem.review_status == "approved",
        )
    )
    problems = {p.id: p for p in result.scalars().all()}
    return [
        _problem_brief(p) for pid in problem_ids if (p := problems.get(pid)) is not None
    ]


# ---------------- 固定随机卡：每次请求随机抽 RANDOM_CARD_MIN~MAX 条 ----------------


async def _sample_posts(db: AsyncSession, k: int) -> list[dict[str, Any]]:
    result = await db.execute(
        select(ForumPost)
        .options(selectinload(ForumPost.author))
        .where(ForumPost.is_deleted.is_(False))
        .order_by(func.random())
        .limit(k)
    )
    return await _posts_briefs(db, list(result.scalars().unique().all()))


async def _sample_problems(db: AsyncSession, k: int) -> list[dict[str, Any]]:
    result = await db.execute(
        select(Problem)
        .where(Problem.is_public.is_(True), Problem.review_status == "approved")
        .order_by(func.random())
        .limit(k)
    )
    return [_problem_brief(p) for p in result.scalars().all()]


async def _sample_friend_links(db: AsyncSession, k: int) -> list[dict[str, Any]]:
    result = await db.execute(
        select(FriendLink)
        .where(FriendLink.is_active.is_(True))
        .order_by(FriendLink.sort_order.asc(), FriendLink.id.asc())
    )
    links = list(result.scalars().all())
    # 随机挑「哪几个」，展示顺序仍按 sort_order 排
    picked = random.sample(links, min(k, len(links)))
    picked.sort(key=lambda l: (l.sort_order or 0, l.id))
    return [
        {"id": link.id, "title": link.title, "icon": link.icon, "url": link.url}
        for link in picked
    ]


def _random_card_count() -> int:
    return random.randint(RANDOM_CARD_MIN, RANDOM_CARD_MAX)


@router.get("/home/cloud", summary="首页云图内容（公开：固定随机卡 + 可修改卡）")
async def get_home_cloud_content(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = await _get_setting(db, HOME_CLOUD_KEY)
    config = _coerce_home_cloud(row.value if row else None)
    if not config.enabled:
        return {"enabled": False, "cards": []}

    cards: list[dict[str, Any]] = []

    # 固定卡（不可修改）：友情链接（随机）、随机题目、随机讨论
    links = await _sample_friend_links(db, _random_card_count())
    if links:
        cards.append({"type": "friend_links", "title": "友情链接", "items": links})
    problems = await _sample_problems(db, _random_card_count())
    if problems:
        cards.append({"type": "problems", "title": "随机题目", "items": problems})
    posts = await _sample_posts(db, _random_card_count())
    if posts:
        cards.append({"type": "posts", "title": "随机讨论", "items": posts})

    # 可修改卡：管理员配置的精选题目 / 置顶讨论，未启用或没内容自动隐藏
    featured = config.featured_problems
    if featured.enabled and featured.problem_ids:
        items = await _resolve_problems(db, featured.problem_ids)
        if items:
            cards.append(
                {
                    "type": "problems",
                    "title": featured.title or "精选题目",
                    "items": items,
                }
            )
    pinned = config.pinned_posts
    if pinned.enabled and pinned.post_ids:
        items = await _resolve_posts(db, pinned.post_ids)
        if items:
            cards.append(
                {
                    "type": "posts",
                    "title": pinned.title or "置顶讨论",
                    "items": items,
                }
            )

    return {"enabled": True, "cards": cards}
