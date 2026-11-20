"""专栏与专栏文章 API。

- 专栏列表与推荐：支持按分类、推荐状态、作者、搜索筛选
- 专栏点赞与收藏：支持登录用户切换点赞、收藏状态与统计
- 专栏评论：支持 Markdown 富文本和 LaTeX 公式评论，支持 @ 提及与专栏作者通知
- 专栏创建与维护：用户可在个人中心「我的」创建和管理专栏，作者可维护文章
- 全站推荐：管理员可设置/取消全站推荐（is_recommended）
- 专栏文章阅读与管理：支持 Markdown 富文本渲染与浏览计数
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, desc, func as sa_func, or_, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.deps import get_current_user, get_current_user_optional
from app.models.column import (
    ArticleComment,
    ArticleLike,
    ArticleStar,
    Column,
    ColumnArticle,
    ColumnInclusionRequest,
    ColumnLike,
    ColumnStar,
)
from app.models.problem import Problem
from app.models.user import User
from app.schemas.column import (
    COLUMN_CATEGORIES,
    DEFAULT_CATEGORY,
    ArticleCommentCreate,
    ArticleCommentItem,
    ArticleCreate,
    ArticleLikeResponse,
    ArticleListResponse,
    ArticleRecommendApply,
    ArticleRecommendReview,
    ArticleRecommendUpdate,
    ArticleStarResponse,
    ArticleUpdate,
    AuthorBrief,
    ColumnArticleCreate,
    ColumnArticleDetail,
    ColumnArticleListItem,
    ColumnArticleRecommendUpdate,
    ColumnArticleUpdate,
    ColumnCreate,
    ColumnDetail,
    ColumnInclusionArticleBrief,
    ColumnInclusionColumnBrief,
    ColumnInclusionRequestCreate,
    ColumnInclusionRequestItem,
    ColumnInclusionRequestReview,
    ColumnLikeResponse,
    ColumnListItem,
    ColumnListResponse,
    ColumnRecommendUpdate,
    ColumnStarResponse,
    ColumnUpdate,
)
from app.services.judge import _add_contribution, RECOMMENDED_ARTICLE_CONTRIBUTION
from app.services.notification import TITLE_MAX, add_notification, clip, notify_mentions
from app.utils.ratelimit import check

router = APIRouter(prefix="/columns", tags=["专栏"])
alias_router = APIRouter(prefix="/column", tags=["专栏"])
articles_router = APIRouter(prefix="/articles", tags=["文章"])
article_alias_router = APIRouter(prefix="/article", tags=["文章"])


def _is_admin(user: User | None) -> bool:
    if not user:
        return False
    return bool(user.is_super_admin or user.is_admin)


def _can_submit_solution(problem: Problem | None, user: User | None) -> bool:
    if not problem:
        return True
    if getattr(problem, "allow_solution_submission", True):
        return True
    if not user:
        return False
    return bool(user.is_super_admin or user.is_admin or getattr(user, "can_manage_problems", False))


def _article_visible(art: ColumnArticle, user: User | None) -> bool:
    """文章对当前用户是否可见。

    - **草稿**（is_draft）：仅作者本人与管理员可见（其余人按 404 处理）
    - 审核中（recommend_status=pending，含修改后重新审核）的文章仅作者本人与管理员可见
    """
    if _is_admin(user):
        return True
    if art.is_draft:
        return user is not None and art.author_id == user.id
    if (art.recommend_status or "none") == "pending":
        return user is not None and art.author_id == user.id
    return True


def _article_pending_filter(user: User | None):
    """列表查询用：审核中文章对非作者/非管理员隐藏的 SQL 条件。"""
    cond = or_(ColumnArticle.recommend_status.is_(None), ColumnArticle.recommend_status != "pending")
    if user:
        return or_(cond, ColumnArticle.author_id == user.id)
    return cond


def _article_published_only():
    """列表查询用：把所有公开列表限制在「已发布」范围。

    草稿只在作者的「我的草稿」（``GET /articles/drafts``）里出现，
    任何公开列表（广场、专栏、题解区、用户主页等）都不应带出它——
    否则等于把未发布的正文/标题泄露出去。
    """
    return ColumnArticle.is_draft.is_(False)


def _reset_article_to_pending(art: ColumnArticle) -> None:
    """已过审文章被修改后：撤下广场推荐，重新进入审核（审核期间他人不可见）。"""
    art.is_recommended = False
    art.recommend_status = "pending"
    art.reviewed_at = None
    art.reviewer_id = None


def _author_to_brief(user: User | None) -> Optional[AuthorBrief]:
    if not user:
        return None
    return AuthorBrief(
        id=user.id,
        username=user.username,
        user_number=user.user_number,
        avatar_url=user.avatar_url,
        user_tag=user.user_tag,
        username_color=user.username_color,
        color_tier=getattr(user, "color_tier", "gray") or "gray",
        name_color=getattr(user, "name_color", "") or "",
        rating=getattr(user, "rating", None),
        role=getattr(user, "role", None),
        is_admin=user.is_admin,
        is_super_admin=user.is_super_admin,
        # 在线点（UserAvatarStatus）靠它判断；漏了作者/评论者就永远显示离线
        last_seen=user.last_seen,
    )


def _make_summary(content: str, max_len: int = 150) -> str:
    cleaned = re.sub(r"[#*`>~_\[\]()!-]", " ", content)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[:max_len] + "..."


def _req_to_item(req: ColumnInclusionRequest) -> ColumnInclusionRequestItem:
    art_brief = None
    if req.article:
        art_brief = ColumnInclusionArticleBrief(
            id=req.article.id,
            title=req.article.title,
            summary=req.article.summary,
            category=req.article.category,
            created_at=req.article.created_at,
            column_id=req.article.column_id,
            author=_author_to_brief(req.article.author),
        )
    col_brief = None
    if req.column:
        col_brief = ColumnInclusionColumnBrief(
            id=req.column.id,
            title=req.column.title,
            author_id=req.column.author_id,
        )
    return ColumnInclusionRequestItem(
        id=req.id,
        column_id=req.column_id,
        article_id=req.article_id,
        applicant_id=req.applicant_id,
        status=req.status,
        message=req.message,
        reply=req.reply,
        created_at=req.created_at,
        updated_at=req.updated_at,
        article=art_brief,
        column=col_brief,
        applicant=_author_to_brief(req.applicant),
    )


async def _resolve_problem_by_code_or_id(db: AsyncSession, code_or_id: str | int | None) -> Problem | None:
    if code_or_id is None:
        return None
    code = str(code_or_id).strip().upper()
    if not code:
        return None
    # 1. 团队题 T{t_no} 或 T{id}
    if code.startswith("T") and code[1:].isdigit():
        t_val = int(code[1:])
        p = (await db.execute(select(Problem).where(Problem.t_no == t_val))).scalar_one_or_none()
        if p:
            return p
        cand = await db.get(Problem, t_val)
        if cand and cand.team_id is not None:
            return cand
        return None
    # 2. P{1000+id} 或 U{1000+id}
    if code[:1] in ("P", "U") and code[1:].isdigit():
        pid = int(code[1:]) - 1000
        p = await db.get(Problem, pid)
        if p and p.team_id is None:
            return p
        return None
    # 3. 纯数字 ID 或 1000+id
    if code.isdigit():
        num = int(code)
        if num >= 1000:
            p = await db.get(Problem, num - 1000)
            if p:
                return p
        p = await db.get(Problem, num)
        if p:
            return p
    return None


def _article_to_list_item(
    art: ColumnArticle,
    like_count: int = 0,
    star_count: int = 0,
    comment_count: int = 0,
) -> ColumnArticleListItem:
    p_code = None
    p_title = None
    if getattr(art, "problem", None):
        p_code = art.problem.problem_number
        p_title = art.problem.title
    return ColumnArticleListItem(
        id=art.id,
        column_id=art.column_id,
        title=art.title,
        summary=art.summary,
        cover_url=art.cover_url,
        category=art.category,
        is_recommended=art.is_recommended,
        is_draft=bool(art.is_draft),
        problem_id=art.problem_id,
        problem_code=p_code,
        problem_title=p_title,
        recommend_status=getattr(art, "recommend_status", "none") or "none",
        recommend_reason=getattr(art, "recommend_reason", None),
        view_count=art.view_count,
        like_count=like_count,
        star_count=star_count,
        comment_count=comment_count,
        created_at=art.created_at,
        updated_at=art.updated_at,
        author=_author_to_brief(art.author),
        column_title=art.column.title if art.column else None,
    )


def _article_to_detail(
    art: ColumnArticle,
    like_count: int = 0,
    star_count: int = 0,
    comment_count: int = 0,
    is_liked: bool = False,
    is_starred: bool = False,
) -> ColumnArticleDetail:
    p_code = None
    p_title = None
    if getattr(art, "problem", None):
        p_code = art.problem.problem_number
        p_title = art.problem.title
    rev_name = None
    if getattr(art, "reviewer", None):
        rev_name = art.reviewer.username

    return ColumnArticleDetail(
        id=art.id,
        column_id=art.column_id,
        title=art.title,
        content=art.content,
        summary=art.summary,
        cover_url=art.cover_url,
        category=art.category,
        is_recommended=art.is_recommended,
        is_draft=bool(art.is_draft),
        problem_id=art.problem_id,
        problem_code=p_code,
        problem_title=p_title,
        recommend_status=getattr(art, "recommend_status", "none") or "none",
        recommend_reason=getattr(art, "recommend_reason", None),
        reviewed_at=getattr(art, "reviewed_at", None),
        reviewer_username=rev_name,
        view_count=art.view_count,
        like_count=like_count,
        star_count=star_count,
        comment_count=comment_count,
        is_liked=is_liked,
        is_starred=is_starred,
        created_at=art.created_at,
        updated_at=art.updated_at,
        author=_author_to_brief(art.author),
        column_title=art.column.title if art.column else None,
    )


@router.get("", response_model=ColumnListResponse, summary="获取专栏列表（支持分类、推荐、作者、收藏、搜索筛选）")
@alias_router.get("", response_model=ColumnListResponse, include_in_schema=False)
async def list_columns(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: Optional[str] = Query(None, description="专栏分类（算法理论、科技工程、娱乐、题解）"),
    author_id: Optional[int] = Query(None, description="作者用户 ID"),
    starred_by: Optional[int] = Query(None, description="收藏该专栏的用户 ID"),
    is_recommended: Optional[bool] = Query(None, description="是否全站推荐"),
    keyword: Optional[str] = Query(None, description="按专栏标题或描述搜索"),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> ColumnListResponse:
    query = select(Column).options(selectinload(Column.author))

    if starred_by is not None:
        query = query.join(ColumnStar, ColumnStar.column_id == Column.id).where(ColumnStar.user_id == starred_by)
    if category and category.strip() and category != "all":
        query = query.where(Column.category == category.strip())
    if author_id is not None:
        query = query.where(Column.author_id == author_id)

    # 针对文章广场公共列表（未指定特定作者或特定收藏）：没有被全站推荐的专栏不显示在文章广场
    if not author_id and not starred_by:
        if is_recommended is False:
            if _is_admin(current_user):
                query = query.where(Column.is_recommended.is_(False))
            else:
                query = query.where(Column.is_recommended.is_(True))
        else:
            query = query.where(Column.is_recommended.is_(True))
    else:
        if is_recommended is not None:
            query = query.where(Column.is_recommended == is_recommended)

    if keyword and keyword.strip():
        kw = f"%{keyword.strip()}%"
        query = query.where((Column.title.ilike(kw)) | (Column.description.ilike(kw)))

    total_query = select(sa_func.count()).select_from(query.subquery())
    total = (await db.execute(total_query)).scalar() or 0

    query = query.order_by(desc(Column.is_recommended), desc(Column.updated_at))
    query = query.offset((page - 1) * page_size).limit(page_size)

    columns = (await db.execute(query)).scalars().all()
    col_ids = [c.id for c in columns]

    # 批量统计文章数、点赞数、收藏数、评论数
    article_counts: dict[int, int] = {}
    like_counts: dict[int, int] = {}
    star_counts: dict[int, int] = {}
    comment_counts: dict[int, int] = {}

    if col_ids:
        # 文章统计（草稿一律不计；审核中的文章对非作者/非管理员也不可见，不计数）
        a_q = select(ColumnArticle.column_id, sa_func.count(ColumnArticle.id)).where(
            ColumnArticle.column_id.in_(col_ids),
            _article_published_only(),
        ).group_by(ColumnArticle.column_id)
        if not _is_admin(current_user):
            a_q = a_q.where(_article_pending_filter(current_user))
        for cid, cnt in (await db.execute(a_q)).all():
            article_counts[cid] = cnt

        # 点赞统计
        l_q = select(ColumnLike.column_id, sa_func.count(ColumnLike.id)).where(ColumnLike.column_id.in_(col_ids)).group_by(ColumnLike.column_id)
        for cid, cnt in (await db.execute(l_q)).all():
            like_counts[cid] = cnt

        # 收藏统计
        s_q = select(ColumnStar.column_id, sa_func.count(ColumnStar.id)).where(ColumnStar.column_id.in_(col_ids)).group_by(ColumnStar.column_id)
        for cid, cnt in (await db.execute(s_q)).all():
            star_counts[cid] = cnt

    items = [
        ColumnListItem(
            id=c.id,
            title=c.title,
            description=c.description,
            cover_url=c.cover_url,
            category=c.category,
            author_id=c.author_id,
            is_recommended=c.is_recommended,
            article_count=article_counts.get(c.id, 0),
            like_count=like_counts.get(c.id, 0),
            star_count=star_counts.get(c.id, 0),
            comment_count=0,
            created_at=c.created_at,
            updated_at=c.updated_at,
            author=_author_to_brief(c.author),
        )
        for c in columns
    ]

    return ColumnListResponse(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=ColumnListItem, status_code=status.HTTP_201_CREATED, summary="创建专栏")
@alias_router.post("", response_model=ColumnListItem, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_column(
    body: ColumnCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ColumnListItem:
    cat = (body.category or "").strip()
    if cat not in COLUMN_CATEGORIES:
        cat = DEFAULT_CATEGORY

    col = Column(
        title=body.title.strip(),
        description=body.description.strip() if body.description else None,
        cover_url=body.cover_url.strip() if body.cover_url else None,
        category=cat,
        author_id=current_user.id,
        is_recommended=False,
    )
    db.add(col)
    await db.commit()
    await db.refresh(col, ["id", "title", "description", "cover_url", "category", "author_id", "is_recommended", "created_at", "updated_at"])

    return ColumnListItem(
        id=col.id,
        title=col.title,
        description=col.description,
        cover_url=col.cover_url,
        category=col.category,
        author_id=col.author_id,
        is_recommended=col.is_recommended,
        article_count=0,
        like_count=0,
        star_count=0,
        comment_count=0,
        created_at=col.created_at,
        updated_at=col.updated_at,
        author=_author_to_brief(current_user),
    )


@router.get("/my", response_model=list[ColumnListItem], summary="获取当前登录用户的专栏列表（供发文选择）")
@alias_router.get("/my", response_model=list[ColumnListItem], include_in_schema=False)
async def list_my_columns(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ColumnListItem]:
    rows = (await db.execute(
        select(Column)
        .options(selectinload(Column.author))
        .where(Column.author_id == current_user.id)
        .order_by(desc(Column.updated_at))
    )).scalars().all()

    col_ids = [r.id for r in rows]
    art_count_map = {}
    if col_ids:
        counts = (await db.execute(
            select(ColumnArticle.column_id, sa_func.count(ColumnArticle.id))
            .where(ColumnArticle.column_id.in_(col_ids), _article_published_only())
            .group_by(ColumnArticle.column_id)
        )).all()
        art_count_map = {cid: cnt for cid, cnt in counts}

    return [
        ColumnListItem(
            id=r.id,
            title=r.title,
            description=r.description,
            cover_url=r.cover_url,
            category=r.category,
            author_id=r.author_id,
            is_recommended=r.is_recommended,
            article_count=art_count_map.get(r.id, 0),
            like_count=0,
            star_count=0,
            comment_count=0,
            created_at=r.created_at,
            updated_at=r.updated_at,
            author=_author_to_brief(r.author),
        )
        for r in rows
    ]


@router.get("/{column_id}", response_model=ColumnDetail, summary="获取专栏详情及文章列表")
@alias_router.get("/{column_id}", response_model=ColumnDetail, include_in_schema=False)
async def get_column(
    column_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> ColumnDetail:
    col = (await db.execute(
        select(Column)
        .options(
            selectinload(Column.author),
            selectinload(Column.articles).selectinload(ColumnArticle.author),
        )
        .where(Column.id == column_id)
    )).scalar_one_or_none()

    if not col:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="专栏不存在")

    # 审核中的文章仅作者本人与管理员可见；草稿一律不进专栏列表（与
    # list_columns 的 article_count 口径一致，避免同一专栏两处计数不同）
    visible_articles = [
        a for a in col.articles
        if _article_visible(a, current_user) and not a.is_draft
    ]
    articles = [
        ColumnArticleListItem(
            id=a.id,
            column_id=a.column_id,
            title=a.title,
            summary=a.summary,
            cover_url=a.cover_url,
            category=a.category,
            is_recommended=a.is_recommended,
            view_count=a.view_count,
            created_at=a.created_at,
            updated_at=a.updated_at,
            author=_author_to_brief(a.author),
            column_title=col.title,
        )
        for a in visible_articles
    ]

    like_count = (await db.execute(select(sa_func.count(ColumnLike.id)).where(ColumnLike.column_id == col.id))).scalar() or 0
    star_count = (await db.execute(select(sa_func.count(ColumnStar.id)).where(ColumnStar.column_id == col.id))).scalar() or 0
    comment_count = 0

    is_liked = False
    is_starred = False
    if current_user:
        is_liked = bool((await db.execute(
            select(ColumnLike.id).where(ColumnLike.column_id == col.id, ColumnLike.user_id == current_user.id)
        )).scalar_one_or_none())
        is_starred = bool((await db.execute(
            select(ColumnStar.id).where(ColumnStar.column_id == col.id, ColumnStar.user_id == current_user.id)
        )).scalar_one_or_none())

    return ColumnDetail(
        id=col.id,
        title=col.title,
        description=col.description,
        cover_url=col.cover_url,
        category=col.category,
        author_id=col.author_id,
        is_recommended=col.is_recommended,
        article_count=len(articles),
        like_count=like_count,
        star_count=star_count,
        comment_count=comment_count,
        is_liked=is_liked,
        is_starred=is_starred,
        created_at=col.created_at,
        updated_at=col.updated_at,
        author=_author_to_brief(col.author),
        articles=articles,
    )


@router.put("/{column_id}", response_model=ColumnListItem, summary="修改专栏信息")
@alias_router.put("/{column_id}", response_model=ColumnListItem, include_in_schema=False)
async def update_column(
    column_id: int,
    body: ColumnUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ColumnListItem:
    col = (await db.execute(
        select(Column).options(selectinload(Column.author)).where(Column.id == column_id)
    )).scalar_one_or_none()

    if not col:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="专栏不存在")
    if col.author_id != current_user.id and not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权修改此专栏")

    if body.title is not None:
        col.title = body.title.strip()
    if body.description is not None:
        col.description = body.description.strip() if body.description else None
    if body.cover_url is not None:
        col.cover_url = body.cover_url.strip() if body.cover_url else None
    if body.category is not None:
        cat = body.category.strip()
        if cat in COLUMN_CATEGORIES:
            col.category = cat

    await db.commit()
    await db.refresh(col, ["id", "title", "description", "cover_url", "category", "author_id", "is_recommended", "created_at", "updated_at"])

    art_count = (await db.execute(
        select(sa_func.count(ColumnArticle.id)).where(
            ColumnArticle.column_id == col.id, _article_published_only()
        )
    )).scalar() or 0
    like_count = (await db.execute(select(sa_func.count(ColumnLike.id)).where(ColumnLike.column_id == col.id))).scalar() or 0
    star_count = (await db.execute(select(sa_func.count(ColumnStar.id)).where(ColumnStar.column_id == col.id))).scalar() or 0
    comment_count = 0

    return ColumnListItem(
        id=col.id,
        title=col.title,
        description=col.description,
        cover_url=col.cover_url,
        category=col.category,
        author_id=col.author_id,
        is_recommended=col.is_recommended,
        article_count=art_count,
        like_count=like_count,
        star_count=star_count,
        comment_count=comment_count,
        created_at=col.created_at,
        updated_at=col.updated_at,
        author=_author_to_brief(col.author),
    )


@router.delete("/{column_id}", summary="删除专栏")
@alias_router.delete("/{column_id}", summary="删除专栏", include_in_schema=False)
async def delete_column(
    column_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    col = (await db.execute(select(Column).where(Column.id == column_id))).scalar_one_or_none()
    if not col:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="专栏不存在")
    if col.author_id != current_user.id and not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权删除此专栏")

    # 显式清理关联点赞、收藏和文章，避免外键冲突或触发 ORM 级联懒加载异常
    await db.execute(delete(ColumnLike).where(ColumnLike.column_id == column_id))
    await db.execute(delete(ColumnStar).where(ColumnStar.column_id == column_id))
    await db.execute(delete(ColumnArticle).where(ColumnArticle.column_id == column_id))
    await db.execute(delete(Column).where(Column.id == column_id))
    await db.commit()
    return {"message": "专栏已删除", "id": column_id}


@router.put("/{column_id}/recommend", response_model=ColumnListItem, summary="管理员全站推荐设置")
@alias_router.put("/{column_id}/recommend", response_model=ColumnListItem, include_in_schema=False)
async def recommend_column(
    column_id: int,
    body: ColumnRecommendUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ColumnListItem:
    if not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员可推荐专栏")

    col = (await db.execute(
        select(Column).options(selectinload(Column.author)).where(Column.id == column_id)
    )).scalar_one_or_none()

    if not col:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="专栏不存在")

    col.is_recommended = body.is_recommended
    await db.commit()
    await db.refresh(col, ["id", "title", "description", "cover_url", "category", "author_id", "is_recommended", "created_at", "updated_at"])

    art_count = (await db.execute(
        select(sa_func.count(ColumnArticle.id)).where(
            ColumnArticle.column_id == col.id, _article_published_only()
        )
    )).scalar() or 0
    like_count = (await db.execute(select(sa_func.count(ColumnLike.id)).where(ColumnLike.column_id == col.id))).scalar() or 0
    star_count = (await db.execute(select(sa_func.count(ColumnStar.id)).where(ColumnStar.column_id == col.id))).scalar() or 0
    comment_count = 0

    return ColumnListItem(
        id=col.id,
        title=col.title,
        description=col.description,
        cover_url=col.cover_url,
        category=col.category,
        author_id=col.author_id,
        is_recommended=col.is_recommended,
        article_count=art_count,
        like_count=like_count,
        star_count=star_count,
        comment_count=comment_count,
        created_at=col.created_at,
        updated_at=col.updated_at,
        author=_author_to_brief(col.author),
    )


# ==================== 专栏点赞与收藏 ====================
@router.post("/{column_id}/like", response_model=ColumnLikeResponse, summary="点赞/取消点赞专栏")
@alias_router.post("/{column_id}/like", response_model=ColumnLikeResponse, include_in_schema=False)
async def toggle_like_column(
    column_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ColumnLikeResponse:
    col = (await db.execute(select(Column).where(Column.id == column_id))).scalar_one_or_none()
    if not col:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="专栏不存在")

    existing = (await db.execute(
        select(ColumnLike).where(ColumnLike.column_id == column_id, ColumnLike.user_id == current_user.id)
    )).scalar_one_or_none()

    if existing:
        await db.delete(existing)
        liked = False
    else:
        db.add(ColumnLike(column_id=column_id, user_id=current_user.id))
        liked = True

    await db.flush()
    like_count = (await db.execute(
        select(sa_func.count(ColumnLike.id)).where(ColumnLike.column_id == column_id)
    )).scalar() or 0
    await db.commit()

    return ColumnLikeResponse(liked=liked, like_count=like_count)


@router.post("/{column_id}/star", response_model=ColumnStarResponse, summary="收藏/取消收藏专栏")
@alias_router.post("/{column_id}/star", response_model=ColumnStarResponse, include_in_schema=False)
async def toggle_star_column(
    column_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ColumnStarResponse:
    col = (await db.execute(select(Column).where(Column.id == column_id))).scalar_one_or_none()
    if not col:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="专栏不存在")

    existing = (await db.execute(
        select(ColumnStar).where(ColumnStar.column_id == column_id, ColumnStar.user_id == current_user.id)
    )).scalar_one_or_none()

    if existing:
        await db.delete(existing)
        starred = False
    else:
        db.add(ColumnStar(column_id=column_id, user_id=current_user.id))
        starred = True

    await db.flush()
    star_count = (await db.execute(
        select(sa_func.count(ColumnStar.id)).where(ColumnStar.column_id == column_id)
    )).scalar() or 0
    await db.commit()

    return ColumnStarResponse(starred=starred, star_count=star_count)


# ==================== 专栏文章 CRUD（向下兼容） ====================
@router.post("/{column_id}/articles", response_model=ColumnArticleListItem, status_code=status.HTTP_201_CREATED, summary="在专栏中发布文章")
@alias_router.post("/{column_id}/articles", response_model=ColumnArticleListItem, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_article(
    column_id: int,
    body: ColumnArticleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ColumnArticleListItem:
    col = (await db.execute(select(Column).where(Column.id == column_id))).scalar_one_or_none()
    if not col:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="专栏不存在")
    if col.author_id != current_user.id and not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权在此专栏发布文章")

    summary = body.summary.strip() if body.summary else _make_summary(body.content)
    category = body.category.strip() if body.category else col.category

    art = ColumnArticle(
        column_id=column_id,
        title=body.title.strip(),
        content=body.content,
        summary=summary,
        cover_url=body.cover_url.strip() if body.cover_url else None,
        category=category,
        is_recommended=False,
        author_id=current_user.id,
        view_count=0,
    )
    db.add(art)
    await db.commit()
    await db.refresh(art)

    return ColumnArticleListItem(
        id=art.id,
        column_id=art.column_id,
        title=art.title,
        summary=art.summary,
        cover_url=art.cover_url,
        category=art.category,
        is_recommended=art.is_recommended,
        view_count=art.view_count,
        created_at=art.created_at,
        updated_at=art.updated_at,
        author=_author_to_brief(current_user),
        column_title=col.title,
    )


@router.get("/{column_id}/articles/{article_id}", response_model=ColumnArticleDetail, summary="获取专栏文章详情（自动增加阅读量）")
@alias_router.get("/{column_id}/articles/{article_id}", response_model=ColumnArticleDetail, include_in_schema=False)
async def get_article(
    column_id: int,
    article_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> ColumnArticleDetail:
    art = (await db.execute(
        select(ColumnArticle)
        .options(selectinload(ColumnArticle.author), selectinload(ColumnArticle.column))
        .where((ColumnArticle.id == article_id) & (ColumnArticle.column_id == column_id))
    )).scalar_one_or_none()

    if not art:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文章不存在")
    if not _article_visible(art, current_user):
        # 审核中的文章仅作者本人与管理员可见
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文章不存在")

    # 草稿不计阅读量：作者从「继续编辑」反复打开详情会刷出虚高计数
    if not art.is_draft:
        # 原子自增：ORM 的 art.view_count += 1 是「读-改-写」，并发下会丢计数
        await db.execute(
            sa_update(ColumnArticle)
            .where(ColumnArticle.id == art.id)
            .values(view_count=ColumnArticle.view_count + 1)
        )
        await db.commit()
        await db.refresh(art)

    return ColumnArticleDetail(
        id=art.id,
        column_id=art.column_id,
        title=art.title,
        content=art.content,
        summary=art.summary,
        cover_url=art.cover_url,
        category=art.category,
        is_recommended=art.is_recommended,
        view_count=art.view_count,
        created_at=art.created_at,
        updated_at=art.updated_at,
        author=_author_to_brief(art.author),
        column_title=art.column.title if art.column else None,
    )


@router.put("/{column_id}/articles/{article_id}", response_model=ColumnArticleListItem, summary="编辑专栏文章")
@alias_router.put("/{column_id}/articles/{article_id}", response_model=ColumnArticleListItem, include_in_schema=False)
async def update_article(
    column_id: int,
    article_id: int,
    body: ColumnArticleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ColumnArticleListItem:
    art = (await db.execute(
        select(ColumnArticle)
        .options(selectinload(ColumnArticle.author), selectinload(ColumnArticle.column))
        .where((ColumnArticle.id == article_id) & (ColumnArticle.column_id == column_id))
    )).scalar_one_or_none()

    if not art:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文章不存在")
    if art.author_id != current_user.id and not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权修改此文章")

    if body.title is not None:
        art.title = body.title.strip()
    if body.content is not None:
        art.content = body.content
        if body.summary is None and not art.summary:
            art.summary = _make_summary(body.content)
    if body.summary is not None:
        art.summary = body.summary.strip() if body.summary else _make_summary(art.content)
    if body.category is not None:
        cat = body.category.strip()
        if cat in COLUMN_CATEGORIES:
            art.category = cat
    if body.cover_url is not None:
        art.cover_url = body.cover_url.strip() if body.cover_url else None

    # 内容被修改的已过审文章须重新审核：撤下广场推荐、回到待审核（审核期间他人不可见）
    content_changed = (
        body.title is not None or body.content is not None
        or body.summary is not None or body.category is not None or body.cover_url is not None
    )
    if content_changed and (art.is_recommended or art.recommend_status == "approved"):
        _reset_article_to_pending(art)

    author_brief = _author_to_brief(art.author)
    col_title = art.column.title if art.column else None
    await db.commit()
    await db.refresh(art)

    return ColumnArticleListItem(
        id=art.id,
        column_id=art.column_id,
        title=art.title,
        summary=art.summary,
        cover_url=art.cover_url,
        category=art.category,
        is_recommended=art.is_recommended,
        view_count=art.view_count,
        created_at=art.created_at,
        updated_at=art.updated_at,
        author=author_brief,
        column_title=col_title,
    )


@router.delete("/{column_id}/articles/{article_id}", summary="删除专栏文章")
@alias_router.delete("/{column_id}/articles/{article_id}", summary="删除专栏文章", include_in_schema=False)
async def delete_article(
    column_id: int,
    article_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    art = (await db.execute(
        select(ColumnArticle).where((ColumnArticle.id == article_id) & (ColumnArticle.column_id == column_id))
    )).scalar_one_or_none()

    if not art:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文章不存在")
    if art.author_id != current_user.id and not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权删除此文章")

    was_approved = bool(art.is_recommended or art.recommend_status == "approved")
    if was_approved and art.author_id:
        await _add_contribution(db, art.author_id, -RECOMMENDED_ARTICLE_CONTRIBUTION)

    await db.execute(
        delete(ColumnArticle).where(
            (ColumnArticle.id == article_id) & (ColumnArticle.column_id == column_id)
        )
    )
    await db.commit()
    return {"message": "文章已删除", "id": article_id}


@router.post("/{column_id}/articles/{article_id}/detach", summary="将文章从专栏中移出（不删除文章）")
@alias_router.post("/{column_id}/articles/{article_id}/detach", include_in_schema=False)
async def detach_article_from_column(
    column_id: int,
    article_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    col = (await db.execute(
        select(Column).options(selectinload(Column.author)).where(Column.id == column_id)
    )).scalar_one_or_none()
    if not col:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定专栏不存在")

    art = (await db.execute(
        select(ColumnArticle).options(selectinload(ColumnArticle.author)).where(ColumnArticle.id == article_id)
    )).scalar_one_or_none()
    if not art:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定文章不存在")

    if art.column_id != col.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该文章不在指定专栏中")

    is_col_author = (col.author_id == current_user.id)
    is_art_author = (art.author_id == current_user.id)
    if not is_col_author and not is_art_author and not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权将该文章移出专栏")

    art.column_id = None
    await db.commit()

    if is_col_author and not is_art_author and art.author_id:
        add_notification(
            db,
            user_id=art.author_id,
            ntype="column_detach",
            actor_id=current_user.id,
            link=f"/article/{art.id}",
            content=f"@{current_user.username} 已将你的文章「{clip(art.title, TITLE_MAX)}」移出专栏「{clip(col.title, TITLE_MAX)}」",
        )
        await db.commit()
    elif is_art_author and not is_col_author and col.author_id:
        add_notification(
            db,
            user_id=col.author_id,
            ntype="column_detach",
            actor_id=current_user.id,
            link=f"/column/{col.id}",
            content=f"@{current_user.username} 已将文章「{clip(art.title, TITLE_MAX)}」从你的专栏「{clip(col.title, TITLE_MAX)}」中移出",
        )
        await db.commit()

    return {"message": "文章已从专栏中移出", "article_id": article_id, "column_id": column_id}


# ==================== 专栏收录申请 API ====================
@router.post("/{column_id}/inclusion-requests", response_model=ColumnInclusionRequestItem, status_code=status.HTTP_201_CREATED, summary="申请将文章收录至他人专栏")
@alias_router.post("/{column_id}/inclusion-requests", response_model=ColumnInclusionRequestItem, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_inclusion_request(
    column_id: int,
    body: ColumnInclusionRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ColumnInclusionRequestItem:
    col = (await db.execute(
        select(Column).options(selectinload(Column.author)).where(Column.id == column_id)
    )).scalar_one_or_none()
    if not col:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定专栏不存在")

    art = (await db.execute(
        select(ColumnArticle).options(selectinload(ColumnArticle.author)).where(ColumnArticle.id == body.article_id)
    )).scalar_one_or_none()
    if not art or not _article_visible(art, current_user):
        # 草稿（及无权查看的审核中文章）按「不存在」处理：否则作者能用自己的草稿
        # 发起收录申请，并通过通知把未发布的标题泄露给第三方专栏作者
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定文章不存在")

    if art.is_draft:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="草稿需先发布后才能申请专栏收录"
        )

    if art.author_id != current_user.id and not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能申请收录自己创作的文章")

    if art.column_id == col.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该文章已在当前专栏中")

    is_direct = (col.author_id == current_user.id or _is_admin(current_user))

    existing_pending = (await db.execute(
        select(ColumnInclusionRequest).where(
            ColumnInclusionRequest.column_id == col.id,
            ColumnInclusionRequest.article_id == art.id,
            ColumnInclusionRequest.status == "pending",
        )
    )).scalar_one_or_none()
    if existing_pending:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="已提交过收录申请，请等待专栏创建者审核")

    req_status = "approved" if is_direct else "pending"
    req = ColumnInclusionRequest(
        column_id=col.id,
        article_id=art.id,
        applicant_id=current_user.id,
        status=req_status,
        message=body.message.strip() if body.message else None,
        reply="专栏作者直接收录" if is_direct else None,
    )
    db.add(req)

    if is_direct:
        art.column_id = col.id

    await db.commit()
    await db.refresh(req)

    if not is_direct and col.author_id != current_user.id:
        add_notification(
            db,
            user_id=col.author_id,
            ntype="column_request",
            actor_id=current_user.id,
            link=f"/column/{col.id}",
            content=f"@{current_user.username} 申请将文章「{clip(art.title, TITLE_MAX)}」收录至你的专栏「{clip(col.title, TITLE_MAX)}」",
        )
        await db.commit()

    req = (await db.execute(
        select(ColumnInclusionRequest)
        .options(
            selectinload(ColumnInclusionRequest.column),
            selectinload(ColumnInclusionRequest.article).selectinload(ColumnArticle.author),
            selectinload(ColumnInclusionRequest.applicant),
        )
        .where(ColumnInclusionRequest.id == req.id)
    )).scalar_one()

    return _req_to_item(req)


@router.get("/{column_id}/inclusion-requests", response_model=list[ColumnInclusionRequestItem], summary="获取专栏的收录申请列表")
@alias_router.get("/{column_id}/inclusion-requests", response_model=list[ColumnInclusionRequestItem], include_in_schema=False)
async def list_column_inclusion_requests(
    column_id: int,
    status_filter: Optional[str] = Query(None, alias="status", description="筛选状态：pending/approved/rejected/cancelled"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ColumnInclusionRequestItem]:
    col = (await db.execute(select(Column).where(Column.id == column_id))).scalar_one_or_none()
    if not col:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定专栏不存在")

    if col.author_id != current_user.id and not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅专栏创建者可查看收录申请")

    q = (
        select(ColumnInclusionRequest)
        .options(
            selectinload(ColumnInclusionRequest.column),
            selectinload(ColumnInclusionRequest.article).selectinload(ColumnArticle.author),
            selectinload(ColumnInclusionRequest.applicant),
        )
        .where(ColumnInclusionRequest.column_id == column_id)
    )
    if status_filter:
        q = q.where(ColumnInclusionRequest.status == status_filter.strip())

    q = q.order_by(desc(ColumnInclusionRequest.id))
    rows = (await db.execute(q)).scalars().all()
    return [_req_to_item(r) for r in rows]


@router.post("/{column_id}/inclusion-requests/{request_id}/review", response_model=ColumnInclusionRequestItem, summary="审核专栏收录申请（同意或拒绝）")
@alias_router.post("/{column_id}/inclusion-requests/{request_id}/review", response_model=ColumnInclusionRequestItem, include_in_schema=False)
async def review_inclusion_request(
    column_id: int,
    request_id: int,
    body: ColumnInclusionRequestReview,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ColumnInclusionRequestItem:
    col = (await db.execute(select(Column).where(Column.id == column_id))).scalar_one_or_none()
    if not col:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定专栏不存在")

    if col.author_id != current_user.id and not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅专栏创建者可审核收录申请")

    req = (await db.execute(
        select(ColumnInclusionRequest)
        .options(
            selectinload(ColumnInclusionRequest.column),
            selectinload(ColumnInclusionRequest.article).selectinload(ColumnArticle.author),
            selectinload(ColumnInclusionRequest.applicant),
        )
        .where(
            ColumnInclusionRequest.id == request_id,
            ColumnInclusionRequest.column_id == column_id,
        )
    )).scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="申请记录不存在")

    if req.status != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该申请已被处理或撤回")

    art = req.article
    if not art:
        art = (await db.execute(select(ColumnArticle).where(ColumnArticle.id == req.article_id))).scalar_one_or_none()
    if not art:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="申请关联的文章已被删除")

    reply_text = body.reply.strip() if body.reply else None

    if body.action == "approve":
        req.status = "approved"
        req.reply = reply_text
        art.column_id = col.id
        if req.applicant_id != current_user.id:
            add_notification(
                db,
                user_id=req.applicant_id,
                ntype="column_approved",
                actor_id=current_user.id,
                link=f"/column/{col.id}/article/{art.id}",
                content=f"@{current_user.username} 同意将你的文章「{clip(art.title, TITLE_MAX)}」收录进专栏「{clip(col.title, TITLE_MAX)}」",
            )
    else:
        req.status = "rejected"
        req.reply = reply_text
        reason = f"，理由：{reply_text}" if reply_text else ""
        if req.applicant_id != current_user.id:
            add_notification(
                db,
                user_id=req.applicant_id,
                ntype="column_rejected",
                actor_id=current_user.id,
                link=f"/article/{art.id}",
                content=f"@{current_user.username} 拒绝了将你的文章「{clip(art.title, TITLE_MAX)}」收录进专栏「{clip(col.title, TITLE_MAX)}」的申请{reason}",
            )

    await db.commit()
    await db.refresh(req)
    return _req_to_item(req)


@router.delete("/{column_id}/inclusion-requests/{request_id}", summary="撤回收录申请")
@alias_router.delete("/{column_id}/inclusion-requests/{request_id}", include_in_schema=False)
async def cancel_inclusion_request(
    column_id: int,
    request_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    req = (await db.execute(
        select(ColumnInclusionRequest).where(
            ColumnInclusionRequest.id == request_id,
            ColumnInclusionRequest.column_id == column_id,
        )
    )).scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="申请记录不存在")

    if req.applicant_id != current_user.id and not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权撤回此申请")

    if req.status != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="只能撤回待审核状态的申请")

    req.status = "cancelled"
    await db.commit()
    return {"message": "申请已撤回", "id": request_id}


# ==================== 独立文章 API（一等公民） ====================
@articles_router.get("/recommend/pending", response_model=ArticleListResponse, summary="待审核推荐申请列表（管理员）")
@article_alias_router.get("/recommend/pending", response_model=ArticleListResponse, include_in_schema=False)
async def list_pending_recommendations(
    page: int = Query(1, ge=1),
    page_size: int = Query(15, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ArticleListResponse:
    if not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员可查看推荐审核列表")

    query = select(ColumnArticle).options(
        selectinload(ColumnArticle.author),
        selectinload(ColumnArticle.column),
        selectinload(ColumnArticle.problem),
        selectinload(ColumnArticle.reviewer),
    ).where(ColumnArticle.recommend_status == "pending", _article_published_only())

    count_query = select(sa_func.count()).select_from(query.order_by(None).subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(desc(ColumnArticle.updated_at))
    query = query.offset((page - 1) * page_size).limit(page_size)
    articles = (await db.execute(query)).scalars().all()

    article_ids = [a.id for a in articles]
    like_counts: dict[int, int] = {}
    star_counts: dict[int, int] = {}
    comment_counts: dict[int, int] = {}
    if article_ids:
        like_rows = (await db.execute(
            select(ArticleLike.article_id, sa_func.count(ArticleLike.id))
            .where(ArticleLike.article_id.in_(article_ids))
            .group_by(ArticleLike.article_id)
        )).all()
        like_counts = dict(like_rows)

        star_rows = (await db.execute(
            select(ArticleStar.article_id, sa_func.count(ArticleStar.id))
            .where(ArticleStar.article_id.in_(article_ids))
            .group_by(ArticleStar.article_id)
        )).all()
        star_counts = dict(star_rows)

        comment_rows = (await db.execute(
            select(ArticleComment.article_id, sa_func.count(ArticleComment.id))
            .where(ArticleComment.article_id.in_(article_ids), ArticleComment.is_deleted.is_(False))
            .group_by(ArticleComment.article_id)
        )).all()
        comment_counts = dict(comment_rows)

    items = [
        _article_to_list_item(
            a,
            like_counts.get(a.id, 0),
            star_counts.get(a.id, 0),
            comment_counts.get(a.id, 0),
        )
        for a in articles
    ]
    return ArticleListResponse(items=items, total=total, page=page, page_size=page_size)


@articles_router.get("", response_model=ArticleListResponse, summary="获取文章列表（文章广场信息流或题目题解区）")
@article_alias_router.get("", response_model=ArticleListResponse, include_in_schema=False)
async def list_articles(
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=100),
    category: Optional[str] = Query(None, description="分类筛选"),
    author_id: Optional[int] = Query(None, description="作者ID"),
    column_id: Optional[int] = Query(None, description="专栏ID"),
    problem_id: Optional[int] = Query(None, description="所属题目ID"),
    problem_code: Optional[str] = Query(None, description="所属题目编号（P1001/T1/U1001）"),
    recommend_status: Optional[str] = Query(None, description="全站推荐审核状态（none/pending/approved/rejected）"),
    is_recommended: Optional[bool] = Query(None, description="是否全站推荐"),
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> ArticleListResponse:
    target_problem_id = problem_id
    if target_problem_id is None and problem_code:
        prob = await _resolve_problem_by_code_or_id(db, problem_code)
        if prob:
            target_problem_id = prob.id
        else:
            return ArticleListResponse(items=[], total=0, page=page, page_size=page_size)

    query = select(ColumnArticle).options(
        selectinload(ColumnArticle.author),
        selectinload(ColumnArticle.column),
        selectinload(ColumnArticle.problem),
        selectinload(ColumnArticle.reviewer),
    )

    if target_problem_id is not None:
        # 题目题解区：限定题目与「题解」分类
        query = query.where(ColumnArticle.problem_id == target_problem_id, ColumnArticle.category == "题解")
        if _is_admin(current_user):
            if recommend_status:
                query = query.where(ColumnArticle.recommend_status == recommend_status)
            elif is_recommended is not None:
                query = query.where(ColumnArticle.is_recommended == is_recommended)
        else:
            # 普通用户：仅展示全站推荐已通过的题解，作者本人额外可见自己的待审核/驳回稿件
            if current_user:
                query = query.where(
                    or_(
                        ColumnArticle.is_recommended.is_(True),
                        ColumnArticle.author_id == current_user.id,
                    )
                )
            else:
                query = query.where(ColumnArticle.is_recommended.is_(True))
    else:
        # 常规文章列表/文章广场
        if category and category != "all":
            query = query.where(ColumnArticle.category == category.strip())
        if author_id:
            query = query.where(ColumnArticle.author_id == author_id)
        if column_id:
            query = query.where(ColumnArticle.column_id == column_id)
        if recommend_status:
            query = query.where(ColumnArticle.recommend_status == recommend_status)

        # 针对文章广场公共列表（未指定特定作者或特定专栏）：没有被全站推荐的文章不显示在广场公开流
        if not author_id and not column_id:
            if is_recommended is False:
                if _is_admin(current_user):
                    query = query.where(ColumnArticle.is_recommended.is_(False))
                else:
                    query = query.where(ColumnArticle.is_recommended.is_(True))
            else:
                query = query.where(ColumnArticle.is_recommended.is_(True))
        else:
            if is_recommended is not None:
                query = query.where(ColumnArticle.is_recommended == is_recommended)

    if keyword and keyword.strip():
        kw = f"%{keyword.strip()}%"
        query = query.where((ColumnArticle.title.ilike(kw)) | (ColumnArticle.summary.ilike(kw)))

    # 草稿一律不出现在公开列表（作者本人的草稿走 GET /articles/drafts）
    query = query.where(_article_published_only())

    # 审核中（待审/修改后重新审核）的文章仅作者本人与管理员可见
    if not _is_admin(current_user):
        query = query.where(_article_pending_filter(current_user))

    count_query = select(sa_func.count()).select_from(query.order_by(None).subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(desc(ColumnArticle.is_recommended), desc(ColumnArticle.updated_at))
    query = query.offset((page - 1) * page_size).limit(page_size)
    articles = (await db.execute(query)).scalars().all()

    article_ids = [a.id for a in articles]
    like_counts: dict[int, int] = {}
    star_counts: dict[int, int] = {}
    comment_counts: dict[int, int] = {}
    if article_ids:
        like_rows = (await db.execute(
            select(ArticleLike.article_id, sa_func.count(ArticleLike.id))
            .where(ArticleLike.article_id.in_(article_ids))
            .group_by(ArticleLike.article_id)
        )).all()
        like_counts = dict(like_rows)

        star_rows = (await db.execute(
            select(ArticleStar.article_id, sa_func.count(ArticleStar.id))
            .where(ArticleStar.article_id.in_(article_ids))
            .group_by(ArticleStar.article_id)
        )).all()
        star_counts = dict(star_rows)

        comment_rows = (await db.execute(
            select(ArticleComment.article_id, sa_func.count(ArticleComment.id))
            .where(ArticleComment.article_id.in_(article_ids), ArticleComment.is_deleted.is_(False))
            .group_by(ArticleComment.article_id)
        )).all()
        comment_counts = dict(comment_rows)

    items = [
        _article_to_list_item(
            a,
            like_counts.get(a.id, 0),
            star_counts.get(a.id, 0),
            comment_counts.get(a.id, 0),
        )
        for a in articles
    ]
    return ArticleListResponse(items=items, total=total, page=page, page_size=page_size)


@articles_router.post("", response_model=ColumnArticleDetail, status_code=status.HTTP_201_CREATED, summary="发布新文章（支持独立或专栏文章）")
@article_alias_router.post("", response_model=ColumnArticleDetail, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_standalone_article(
    body: ArticleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ColumnArticleDetail:
    """发布新文章（支持独立或专栏文章）。

    ``is_draft=true`` 时保存为**草稿**：仅作者本人可见（公开列表/详情一律排除），
    因此放宽「题解必须关联题目」「题解通道已关闭」等发布类校验，也**不能**申请推荐——
    这些都留到草稿正式发布时（``POST /articles/{id}/publish``）再校验。
    """
    is_draft = bool(body.is_draft)

    col = None
    column_id = body.column_id if (body.column_id and body.column_id > 0) else None
    if column_id:
        col = (await db.execute(select(Column).where(Column.id == column_id))).scalar_one_or_none()
        if not col:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定专栏不存在")
        if col.author_id != current_user.id and not _is_admin(current_user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权向该专栏添加文章")

    category = body.category.strip() if body.category else (col.category if col else DEFAULT_CATEGORY)
    if category not in COLUMN_CATEGORIES:
        category = DEFAULT_CATEGORY

    # 题目关联验证（草稿放宽：允许先不关联题目，发布时再要求）
    problem_obj = None
    prob_input = body.problem_code or body.problem_id
    if prob_input:
        problem_obj = await _resolve_problem_by_code_or_id(db, prob_input)
        if not problem_obj:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="关联的题目不存在")
    elif category == "题解" and not is_draft:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="发布题解分类文章必须指定关联题号")

    if (
        category == "题解" and problem_obj and not is_draft
        and not _can_submit_solution(problem_obj, current_user)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="因为题目做法足够充分或题目过于简单已关闭题解通道。",
        )

    recommend_status = "none"
    recommend_reason = None
    # 草稿不能申请全站推荐（未发布的内容无从审核）
    if body.apply_recommend and not is_draft:
        recommend_status = "pending"
        recommend_reason = body.recommend_reason.strip() if body.recommend_reason else None

    summary = body.summary.strip() if body.summary else _make_summary(body.content)

    art = ColumnArticle(
        column_id=column_id,
        title=body.title.strip(),
        content=body.content,
        summary=summary,
        cover_url=body.cover_url.strip() if body.cover_url else None,
        category=category,
        is_recommended=False,
        is_draft=is_draft,
        problem_id=problem_obj.id if problem_obj else None,
        recommend_status=recommend_status,
        recommend_reason=recommend_reason,
        author_id=current_user.id,
        view_count=0,
    )
    db.add(art)
    await db.commit()
    await db.refresh(art)
    art.author = current_user
    art.column = col
    art.problem = problem_obj

    return _article_to_detail(art)


@articles_router.get("/my", response_model=list[ColumnArticleListItem], summary="获取当前登录用户发表的所有文章")
@article_alias_router.get("/my", response_model=list[ColumnArticleListItem], include_in_schema=False)
async def list_my_articles(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ColumnArticleListItem]:
    """我**已发布**的文章（草稿不在此列，见 ``GET /articles/drafts``）。"""
    rows = (await db.execute(
        select(ColumnArticle)
        .options(
            selectinload(ColumnArticle.author),
            selectinload(ColumnArticle.column),
            selectinload(ColumnArticle.problem),
        )
        .where(
            ColumnArticle.author_id == current_user.id,
            ColumnArticle.is_draft.is_(False),
        )
        .order_by(desc(ColumnArticle.id))
    )).scalars().all()

    return [_article_to_list_item(a) for a in rows]


# 注意：本路由必须声明在 GET /{article_id} 之前，否则 "drafts" 会被当成 article_id
@articles_router.get(
    "/drafts",
    response_model=list[ColumnArticleListItem],
    summary="我的文章草稿（仅本人可见）",
)
async def list_my_drafts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(50, ge=1, le=200, description="每页条数"),
) -> list[ColumnArticleListItem]:
    """当前用户的草稿列表（未发布），按最近修改倒序，支持分页。

    默认取最新 50 条；上限 200，避免重用户一次全量拉取。
    """
    rows = (await db.execute(
        select(ColumnArticle)
        .options(
            selectinload(ColumnArticle.author),
            selectinload(ColumnArticle.column),
            selectinload(ColumnArticle.problem),
        )
        .where(
            ColumnArticle.author_id == current_user.id,
            ColumnArticle.is_draft.is_(True),
        )
        .order_by(desc(ColumnArticle.updated_at), desc(ColumnArticle.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).scalars().all()

    return [_article_to_list_item(a) for a in rows]


@articles_router.post(
    "/{article_id}/publish",
    response_model=ColumnArticleDetail,
    summary="发布草稿（把 is_draft 置为 false，并执行发布校验）",
)
async def publish_draft(
    article_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ColumnArticleDetail:
    """把草稿正式发布。

    发布时补齐创建草稿时放宽掉的校验：题解类必须关联题目、题解通道需仍开放。
    """
    art = (await db.execute(
        select(ColumnArticle)
        .options(
            selectinload(ColumnArticle.author),
            selectinload(ColumnArticle.column),
            selectinload(ColumnArticle.problem),
            selectinload(ColumnArticle.reviewer),
        )
        # 行锁：并发的两次「发布」串行化，后来者看到 is_draft=False 直接 400，
        # 不会重复走发布校验与后续通知逻辑（SQLite 方言忽略，生产 PG 生效）
        .where(ColumnArticle.id == article_id)
        .with_for_update()
    )).scalar_one_or_none()
    if not art:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文章不存在")
    if art.author_id != current_user.id and not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权发布该文章")
    if not art.is_draft:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该文章不是草稿")

    # 发布校验（与直接发布保持一致）
    if art.category == "题解":
        if not art.problem_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="发布题解分类文章必须指定关联题号",
            )
        if not _can_submit_solution(art.problem, current_user):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="因为题目做法足够充分或题目过于简单已关闭题解通道。",
            )

    # 条件 UPDATE：只有仍是草稿才置为已发布。并发/重试的第二次请求 rowcount=0，
    # 直接返回 400 而不是把已发布文章再"发布"一遍（幂等失败而非静默重复）。
    result = await db.execute(
        sa_update(ColumnArticle)
        .where(ColumnArticle.id == article_id, ColumnArticle.is_draft.is_(True))
        .values(is_draft=False)
    )
    if result.rowcount == 0:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="该文章不是草稿（可能已被发布）"
        )
    await db.commit()
    await db.refresh(art)
    return _article_to_detail(art)


@articles_router.get("/{article_id}", response_model=ColumnArticleDetail, summary="获取独立文章详情（自动增加阅读量）")
@article_alias_router.get("/{article_id}", response_model=ColumnArticleDetail, include_in_schema=False)
async def get_standalone_article(
    article_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> ColumnArticleDetail:
    art = (await db.execute(
        select(ColumnArticle)
        .options(
            selectinload(ColumnArticle.author),
            selectinload(ColumnArticle.column),
            selectinload(ColumnArticle.problem),
            selectinload(ColumnArticle.reviewer),
        )
        .where(ColumnArticle.id == article_id)
    )).scalar_one_or_none()

    if not art:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文章不存在")
    if not _article_visible(art, current_user):
        # 审核中的文章仅作者本人与管理员可见
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文章不存在")

    # 草稿不计阅读量：作者从「继续编辑」反复打开详情会刷出虚高计数
    if not art.is_draft:
        # 原子自增：ORM 的 art.view_count += 1 是「读-改-写」，并发下会丢计数
        await db.execute(
            sa_update(ColumnArticle)
            .where(ColumnArticle.id == art.id)
            .values(view_count=ColumnArticle.view_count + 1)
        )
        await db.commit()
        await db.refresh(art)

    like_count = (await db.execute(
        select(sa_func.count(ArticleLike.id)).where(ArticleLike.article_id == art.id)
    )).scalar() or 0
    star_count = (await db.execute(
        select(sa_func.count(ArticleStar.id)).where(ArticleStar.article_id == art.id)
    )).scalar() or 0
    comment_count = (await db.execute(
        select(sa_func.count(ArticleComment.id)).where(
            ArticleComment.article_id == art.id,
            ArticleComment.is_deleted.is_(False),
        )
    )).scalar() or 0

    is_liked = False
    is_starred = False
    if current_user:
        is_liked = bool((await db.execute(
            select(ArticleLike.id).where(ArticleLike.article_id == art.id, ArticleLike.user_id == current_user.id)
        )).scalar_one_or_none())
        is_starred = bool((await db.execute(
            select(ArticleStar.id).where(ArticleStar.article_id == art.id, ArticleStar.user_id == current_user.id)
        )).scalar_one_or_none())

    return _article_to_detail(art, like_count, star_count, comment_count, is_liked, is_starred)


@articles_router.put("/{article_id}", response_model=ColumnArticleDetail, summary="编辑文章（修改内容、分类、挂载专栏、关联题目）")
@article_alias_router.put("/{article_id}", response_model=ColumnArticleDetail, include_in_schema=False)
async def update_standalone_article(
    article_id: int,
    body: ArticleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ColumnArticleDetail:
    art = (await db.execute(
        select(ColumnArticle)
        .options(
            selectinload(ColumnArticle.author),
            selectinload(ColumnArticle.column),
            selectinload(ColumnArticle.problem),
            selectinload(ColumnArticle.reviewer),
        )
        .where(ColumnArticle.id == article_id)
    )).scalar_one_or_none()

    if not art:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文章不存在")
    if art.author_id != current_user.id and not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权修改此文章")

    if body.title is not None:
        art.title = body.title.strip()
    if body.content is not None:
        art.content = body.content
        if body.summary is None and not art.summary:
            art.summary = _make_summary(body.content)
    if body.summary is not None:
        art.summary = body.summary.strip() if body.summary else _make_summary(art.content)
    if body.category is not None:
        cat = body.category.strip()
        if cat in COLUMN_CATEGORIES:
            art.category = cat
    if body.cover_url is not None:
        art.cover_url = body.cover_url.strip() if body.cover_url else None

    # 题目关联管理
    if body.clear_problem:
        art.problem_id = None
        art.problem = None
    elif body.problem_code is not None or body.problem_id is not None:
        prob_input = body.problem_code or body.problem_id
        prob = await _resolve_problem_by_code_or_id(db, prob_input)
        if not prob:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="关联的题目不存在")
        art.problem_id = prob.id
        art.problem = prob

    # 草稿阶段放宽题解类校验（与 create_standalone_article / publish_draft 一致）：
    # 否则「题解分类但还没填空题号」的草稿每次保存都必然 400，草稿闭环就断了。
    # 这两道校验在发布时（POST /articles/{id}/publish）补做。
    if art.category == "题解" and not art.problem_id and not art.is_draft:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="题解文章必须指定关联题号")

    if (
        art.category == "题解" and not art.is_draft
        and art.problem and not _can_submit_solution(art.problem, current_user)
    ):
        problem_changed = (body.problem_code is not None or body.problem_id is not None)
        category_changed = (body.category is not None and body.category.strip() == "题解")
        if body.apply_recommend is True or problem_changed or category_changed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="因为题目做法足够充分或题目过于简单已关闭题解通道。",
            )

    if body.apply_recommend is True:
        if art.is_draft:
            # 草稿不进推荐流程（与创建/申请端点一致）：否则会挂成 pending，
            # 而审核队列已排除草稿，变成谁也看不到的僵尸状态
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="草稿需先发布后才能申请全站推荐",
            )
        art.recommend_status = "pending"
        if body.recommend_reason is not None:
            art.recommend_reason = body.recommend_reason.strip() or None

    # 内容被修改的已过审文章须重新审核：撤下广场推荐、回到待审核（审核期间他人不可见）
    content_changed = (
        body.title is not None or body.content is not None or body.summary is not None
        or body.category is not None or body.cover_url is not None
        or body.clear_problem or body.problem_code is not None or body.problem_id is not None
    )
    if content_changed and (art.is_recommended or art.recommend_status == "approved"):
        _reset_article_to_pending(art)

    # 专栏归属管理
    if body.detach_column:
        art.column_id = None
        art.column = None
    elif body.column_id is not None:
        if body.column_id == 0:
            art.column_id = None
            art.column = None
        else:
            col = (await db.execute(select(Column).where(Column.id == body.column_id))).scalar_one_or_none()
            if not col:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="目标专栏不存在")
            if col.author_id != current_user.id and not _is_admin(current_user):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权将文章归入目标专栏")
            art.column_id = col.id
            art.column = col

    await db.commit()
    await db.refresh(art)

    return _article_to_detail(art)


@articles_router.delete("/{article_id}", summary="删除文章")
@article_alias_router.delete("/{article_id}", summary="删除文章", include_in_schema=False)
async def delete_standalone_article(
    article_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    art = (await db.execute(
        select(ColumnArticle).where(ColumnArticle.id == article_id)
    )).scalar_one_or_none()

    if not art:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文章不存在")
    if art.author_id != current_user.id and not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权删除此文章")

    was_approved = bool(art.is_recommended or art.recommend_status == "approved")
    if was_approved and art.author_id:
        await _add_contribution(db, art.author_id, -RECOMMENDED_ARTICLE_CONTRIBUTION)

    await db.execute(delete(ColumnArticle).where(ColumnArticle.id == article_id))
    await db.commit()
    return {"message": "文章已删除", "id": article_id}


@articles_router.get("/{article_id}/inclusion-requests", response_model=list[ColumnInclusionRequestItem], summary="获取文章的专栏收录申请记录")
@article_alias_router.get("/{article_id}/inclusion-requests", response_model=list[ColumnInclusionRequestItem], include_in_schema=False)
async def list_article_inclusion_requests(
    article_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ColumnInclusionRequestItem]:
    art = (await db.execute(select(ColumnArticle).where(ColumnArticle.id == article_id))).scalar_one_or_none()
    if not art:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定文章不存在")

    if art.author_id != current_user.id and not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅文章作者可查看该文章的收录申请")

    rows = (await db.execute(
        select(ColumnInclusionRequest)
        .options(
            selectinload(ColumnInclusionRequest.column),
            selectinload(ColumnInclusionRequest.article).selectinload(ColumnArticle.author),
            selectinload(ColumnInclusionRequest.applicant),
        )
        .where(ColumnInclusionRequest.article_id == article_id)
        .order_by(desc(ColumnInclusionRequest.id))
    )).scalars().all()

    return [_req_to_item(r) for r in rows]


@articles_router.post("/{article_id}/apply-recommend", response_model=ColumnArticleDetail, summary="作者申请全站推荐")
@article_alias_router.post("/{article_id}/apply-recommend", response_model=ColumnArticleDetail, include_in_schema=False)
async def apply_article_recommend(
    article_id: int,
    body: ArticleRecommendApply,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ColumnArticleDetail:
    art = (await db.execute(
        select(ColumnArticle)
        .options(
            selectinload(ColumnArticle.author),
            selectinload(ColumnArticle.column),
            selectinload(ColumnArticle.problem),
            selectinload(ColumnArticle.reviewer),
        )
        .where(ColumnArticle.id == article_id)
    )).scalar_one_or_none()

    if not art or not _article_visible(art, current_user):
        # 草稿 / 审核中的文章对无权者按「不存在」处理，避免对未发布内容产生互动
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文章不存在")

    if art.is_draft:
        # 草稿不进推荐流程：否则会挂成 pending（而审核队列又已排除草稿）成为僵尸状态
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="草稿需先发布后才能申请全站推荐"
        )

    if art.author_id != current_user.id and not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅作者可申请全站推荐")
    if art.category == "题解" and not art.problem_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="题解文章须先关联题号才能申请全站推荐")
    if art.category == "题解" and art.problem and not _can_submit_solution(art.problem, current_user):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="因为题目做法足够充分或题目过于简单已关闭题解通道。")
    if art.is_recommended:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该文章已被设为全站推荐，无需重复申请")

    art.recommend_status = "pending"
    if body.reason is not None:
        art.recommend_reason = body.reason.strip() or None
    await db.commit()
    await db.refresh(art)

    return _article_to_detail(art)


@articles_router.post("/{article_id}/review-recommend", response_model=ColumnArticleDetail, summary="审核文章全站推荐申请（管理员）")
@article_alias_router.post("/{article_id}/review-recommend", response_model=ColumnArticleDetail, include_in_schema=False)
async def review_article_recommend(
    article_id: int,
    body: ArticleRecommendReview,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ColumnArticleDetail:
    if not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员可审核全站推荐")

    art = (await db.execute(
        select(ColumnArticle)
        .options(
            selectinload(ColumnArticle.author),
            selectinload(ColumnArticle.column),
            selectinload(ColumnArticle.problem),
            selectinload(ColumnArticle.reviewer),
        )
        .where(ColumnArticle.id == article_id)
    )).scalar_one_or_none()

    if not art or not _article_visible(art, current_user):
        # 草稿 / 审核中的文章对无权者按「不存在」处理，避免对未发布内容产生互动
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文章不存在")

    if art.is_draft:
        # 管理员也不能把草稿推进推荐：会产生「已推荐但仍是草稿」的矛盾状态并发放贡献值
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="草稿不能参与全站推荐审核"
        )

    action = body.action.strip().lower()
    now_time = datetime.now(timezone.utc)
    was_approved = bool(art.is_recommended or art.recommend_status == "approved")

    if action == "approve":
        art.is_recommended = True
        art.recommend_status = "approved"
        art.recommend_reason = body.reason.strip() if body.reason else None
        art.reviewed_at = now_time
        art.reviewer_id = current_user.id
        if not was_approved and art.author_id:
            await _add_contribution(db, art.author_id, RECOMMENDED_ARTICLE_CONTRIBUTION)
            add_notification(
                db,
                user_id=art.author_id,
                ntype="system",
                content=f"🎉 你的文章《{clip(art.title)}》已被推荐至全站，获得 {RECOMMENDED_ARTICLE_CONTRIBUTION} 点社区贡献值！",
                actor_id=current_user.id,
                link=f"/articles/{art.id}",
            )
    elif action == "reject":
        art.is_recommended = False
        art.recommend_status = "rejected"
        art.recommend_reason = body.reason.strip() if body.reason else "不符合全站推荐标准"
        art.reviewed_at = now_time
        art.reviewer_id = current_user.id
        if was_approved and art.author_id:
            await _add_contribution(db, art.author_id, -RECOMMENDED_ARTICLE_CONTRIBUTION)
    elif action == "cancel":
        art.is_recommended = False
        art.recommend_status = "none"
        art.recommend_reason = None
        art.reviewed_at = None
        art.reviewer_id = None
        if was_approved and art.author_id:
            await _add_contribution(db, art.author_id, -RECOMMENDED_ARTICLE_CONTRIBUTION)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的审核操作")

    await db.commit()
    await db.refresh(art)

    return _article_to_detail(art)


@articles_router.put("/{article_id}/recommend", response_model=ColumnArticleDetail, summary="管理员单独推荐文章")
@article_alias_router.put("/{article_id}/recommend", response_model=ColumnArticleDetail, include_in_schema=False)
async def recommend_article(
    article_id: int,
    body: ColumnArticleRecommendUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ColumnArticleDetail:
    if not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员可推荐文章")

    art = (await db.execute(
        select(ColumnArticle)
        .options(
            selectinload(ColumnArticle.author),
            selectinload(ColumnArticle.column),
            selectinload(ColumnArticle.problem),
            selectinload(ColumnArticle.reviewer),
        )
        .where(ColumnArticle.id == article_id)
    )).scalar_one_or_none()

    if not art or not _article_visible(art, current_user):
        # 草稿 / 审核中的文章对无权者按「不存在」处理，避免对未发布内容产生互动
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文章不存在")

    if art.is_draft:
        # 同上：草稿不能被管理员直接推荐（会发放贡献值且与 is_draft 矛盾）
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="草稿不能参与全站推荐"
        )

    was_approved = bool(art.is_recommended or art.recommend_status == "approved")
    art.is_recommended = body.is_recommended
    if body.is_recommended:
        art.recommend_status = "approved"
        art.reviewed_at = datetime.now(timezone.utc)
        art.reviewer_id = current_user.id
        if not was_approved and art.author_id:
            await _add_contribution(db, art.author_id, RECOMMENDED_ARTICLE_CONTRIBUTION)
            add_notification(
                db,
                user_id=art.author_id,
                ntype="system",
                content=f"🎉 你的文章《{clip(art.title)}》已被推荐至全站，获得 {RECOMMENDED_ARTICLE_CONTRIBUTION} 点社区贡献值！",
                actor_id=current_user.id,
                link=f"/articles/{art.id}",
            )
    else:
        art.recommend_status = "none"
        art.recommend_reason = None
        art.reviewed_at = None
        art.reviewer_id = None
        if was_approved and art.author_id:
            await _add_contribution(db, art.author_id, -RECOMMENDED_ARTICLE_CONTRIBUTION)

    await db.commit()
    await db.refresh(art)

    return _article_to_detail(art)


# ==================== 文章点赞、收藏与评论 ====================
@articles_router.post("/{article_id}/like", response_model=ArticleLikeResponse, summary="点赞/取消点赞文章")
@article_alias_router.post("/{article_id}/like", response_model=ArticleLikeResponse, include_in_schema=False)
async def toggle_article_like(
    article_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ArticleLikeResponse:
    art = (await db.execute(select(ColumnArticle).where(ColumnArticle.id == article_id))).scalar_one_or_none()
    if not art or not _article_visible(art, current_user):
        # 草稿 / 审核中的文章对无权者按「不存在」处理，避免对未发布内容产生互动
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文章不存在")

    existing = (await db.execute(
        select(ArticleLike).where(ArticleLike.article_id == article_id, ArticleLike.user_id == current_user.id)
    )).scalar_one_or_none()

    if existing:
        await db.delete(existing)
        liked = False
    else:
        db.add(ArticleLike(article_id=article_id, user_id=current_user.id))
        liked = True
        if art.author_id != current_user.id:
            add_notification(
                db,
                user_id=art.author_id,
                ntype="like",
                actor_id=current_user.id,
                link=f"/article/{art.id}",
                content=f"@{current_user.username} 点赞了你的文章「{clip(art.title, TITLE_MAX)}」",
            )

    await db.commit()
    like_count = (await db.execute(
        select(sa_func.count(ArticleLike.id)).where(ArticleLike.article_id == article_id)
    )).scalar() or 0
    return ArticleLikeResponse(liked=liked, like_count=like_count)


@articles_router.post("/{article_id}/star", response_model=ArticleStarResponse, summary="收藏/取消收藏文章")
@article_alias_router.post("/{article_id}/star", response_model=ArticleStarResponse, include_in_schema=False)
async def toggle_article_star(
    article_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ArticleStarResponse:
    art = (await db.execute(select(ColumnArticle).where(ColumnArticle.id == article_id))).scalar_one_or_none()
    if not art or not _article_visible(art, current_user):
        # 草稿 / 审核中的文章对无权者按「不存在」处理，避免对未发布内容产生互动
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文章不存在")

    existing = (await db.execute(
        select(ArticleStar).where(ArticleStar.article_id == article_id, ArticleStar.user_id == current_user.id)
    )).scalar_one_or_none()

    if existing:
        await db.delete(existing)
        starred = False
    else:
        db.add(ArticleStar(article_id=article_id, user_id=current_user.id))
        starred = True
        if art.author_id != current_user.id:
            add_notification(
                db,
                user_id=art.author_id,
                ntype="star",
                actor_id=current_user.id,
                link=f"/article/{art.id}",
                content=f"@{current_user.username} 收藏了你的文章「{clip(art.title, TITLE_MAX)}」",
            )

    await db.commit()
    star_count = (await db.execute(
        select(sa_func.count(ArticleStar.id)).where(ArticleStar.article_id == article_id)
    )).scalar() or 0
    return ArticleStarResponse(starred=starred, star_count=star_count)


@articles_router.get("/{article_id}/comments", response_model=list[ArticleCommentItem], summary="获取文章评论列表")
@article_alias_router.get("/{article_id}/comments", response_model=list[ArticleCommentItem], include_in_schema=False)
async def list_article_comments(
    article_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> list[ArticleCommentItem]:
    art = (await db.execute(select(ColumnArticle).where(ColumnArticle.id == article_id))).scalar_one_or_none()
    if not art or not _article_visible(art, current_user):
        # 草稿 / 审核中的文章对无权者按「不存在」处理，避免对未发布内容产生互动
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文章不存在")

    comments = (await db.execute(
        select(ArticleComment)
        .options(selectinload(ArticleComment.author))
        .where(ArticleComment.article_id == article_id, ArticleComment.is_deleted.is_(False))
        .order_by(ArticleComment.id.asc())
    )).scalars().all()

    items: list[ArticleCommentItem] = []
    for c in comments:
        is_author = (c.author_id == art.author_id)
        can_delete = bool(
            current_user and (
                current_user.id == c.author_id
                or current_user.id == art.author_id
                or _is_admin(current_user)
            )
        )
        items.append(
            ArticleCommentItem(
                id=c.id,
                article_id=c.article_id,
                content=c.content,
                created_at=c.created_at,
                updated_at=c.updated_at,
                author=_author_to_brief(c.author),
                is_author=is_author,
                can_delete=can_delete,
            )
        )
    return items


@articles_router.post("/{article_id}/comments", response_model=ArticleCommentItem, status_code=status.HTTP_201_CREATED, summary="发表文章评论")
@article_alias_router.post("/{article_id}/comments", response_model=ArticleCommentItem, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_article_comment(
    article_id: int,
    body: ArticleCommentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ArticleCommentItem:
    if current_user.is_banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="你已被封禁，无法发表评论")
    if not current_user.can_speak:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="你已被禁言，无法发表评论")

    ok, wait = check(f"article_comment:{current_user.user_number}", 1, 5)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"评论太频繁，请 {wait} 秒后再试",
        )

    art = (await db.execute(select(ColumnArticle).where(ColumnArticle.id == article_id))).scalar_one_or_none()
    if not art or not _article_visible(art, current_user):
        # 草稿 / 审核中的文章对无权者按「不存在」处理，避免对未发布内容产生互动
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文章不存在")

    comment = ArticleComment(
        article_id=article_id,
        author_id=current_user.id,
        content=body.content.strip(),
    )
    db.add(comment)
    await db.flush()

    # 作者通知与 @提及通知
    link = f"/article/{art.id}#comments"
    title = clip(art.title, TITLE_MAX)
    if art.author_id != current_user.id:
        add_notification(
            db,
            user_id=art.author_id,
            ntype="reply",
            actor_id=current_user.id,
            link=link,
            content=f"@{current_user.username} 评论了你的文章「{title}」，快来看看吧",
        )
    await notify_mentions(
        db,
        comment.content,
        actor=current_user,
        link=link,
        where=f"文章「{title}」",
    )

    await db.commit()
    await db.refresh(comment)

    return ArticleCommentItem(
        id=comment.id,
        article_id=comment.article_id,
        content=comment.content,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
        author=_author_to_brief(current_user),
        is_author=(current_user.id == art.author_id),
        can_delete=True,
    )


@articles_router.delete("/{article_id}/comments/{comment_id}", summary="删除文章评论")
@article_alias_router.delete("/{article_id}/comments/{comment_id}", include_in_schema=False)
async def delete_article_comment(
    article_id: int,
    comment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    art = (await db.execute(select(ColumnArticle).where(ColumnArticle.id == article_id))).scalar_one_or_none()
    if not art:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文章不存在")

    comment = (await db.execute(
        select(ArticleComment).where(
            ArticleComment.id == comment_id,
            ArticleComment.article_id == article_id,
        )
    )).scalar_one_or_none()

    if not comment or comment.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评论不存在或已被删除")

    if comment.author_id != current_user.id and art.author_id != current_user.id and not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权删除此评论")

    comment.is_deleted = True
    await db.commit()
    return {"message": "评论已删除", "id": comment_id}


