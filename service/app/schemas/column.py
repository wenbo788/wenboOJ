"""Schemas for Columns and Column Articles (专栏系统)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class AuthorBrief(BaseModel):
    id: int
    username: str
    user_number: Optional[int] = None
    avatar_url: Optional[str] = None
    user_tag: Optional[str] = None
    username_color: Optional[str] = None
    color_tier: str = "gray"
    rating: Optional[int] = None
    role: Optional[str] = None
    is_admin: Optional[bool] = False
    is_super_admin: Optional[bool] = False
    # 在线点要用：没有这个字段时，专栏作者/评论者在头像上永远显示离线
    last_seen: Optional[datetime] = None


COLUMN_CATEGORIES = ["算法理论", "科技工程", "娱乐", "题解"]
DEFAULT_CATEGORY = "算法理论"


class ColumnCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100, description="专栏标题")
    description: Optional[str] = Field(None, max_length=2000, description="专栏简介")
    cover_url: Optional[str] = Field(None, max_length=500, description="封面图片链接")
    category: Optional[str] = Field(default="算法理论", description="专栏分类")


class ColumnUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=100, description="专栏标题")
    description: Optional[str] = Field(None, max_length=2000, description="专栏简介")
    cover_url: Optional[str] = Field(None, max_length=500, description="封面图片链接")
    category: Optional[str] = Field(None, description="专栏分类")


class ColumnRecommendUpdate(BaseModel):
    is_recommended: bool = Field(..., description="是否推荐至全站主页")


class ColumnArticleListItem(BaseModel):
    id: int
    column_id: Optional[int] = None
    title: str
    summary: Optional[str] = None
    cover_url: Optional[str] = None
    category: str = "算法理论"
    is_recommended: bool = False
    is_draft: bool = False
    problem_id: Optional[int] = None
    problem_code: Optional[str] = None
    problem_title: Optional[str] = None
    recommend_status: str = "none"
    recommend_reason: Optional[str] = None
    view_count: int = 0
    like_count: int = 0
    star_count: int = 0
    comment_count: int = 0
    created_at: datetime
    updated_at: datetime
    author: Optional[AuthorBrief] = None
    column_title: Optional[str] = None


class ColumnListItem(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    cover_url: Optional[str] = None
    category: str = "算法理论"
    author_id: int
    is_recommended: bool
    article_count: int = 0
    like_count: int = 0
    star_count: int = 0
    comment_count: int = 0
    created_at: datetime
    updated_at: datetime
    author: Optional[AuthorBrief] = None


class ColumnDetail(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    cover_url: Optional[str] = None
    category: str = "算法理论"
    author_id: int
    is_recommended: bool
    article_count: int = 0
    like_count: int = 0
    star_count: int = 0
    comment_count: int = 0
    is_liked: bool = False
    is_starred: bool = False
    created_at: datetime
    updated_at: datetime
    author: Optional[AuthorBrief] = None
    articles: list[ColumnArticleListItem] = []


class ColumnListResponse(BaseModel):
    items: list[ColumnListItem]
    total: int
    page: int
    page_size: int


class ColumnArticleCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=150, description="文章标题")
    content: str = Field(..., min_length=1, description="文章正文（Markdown）")
    summary: Optional[str] = Field(None, max_length=500, description="文章摘要，留空则自动截取")
    category: Optional[str] = Field(default="算法理论", description="文章分类")
    cover_url: Optional[str] = Field(None, max_length=500, description="文章封面图片")
    column_id: Optional[int] = Field(None, description="所属专栏ID，留空表示独立文章")
    problem_id: Optional[int] = Field(None, description="关联题目ID")
    problem_code: Optional[str] = Field(None, description="关联题号（如 P1001 / T1 / U1001）")
    apply_recommend: Optional[bool] = Field(False, description="是否同时申请全站推荐")
    recommend_reason: Optional[str] = Field(None, max_length=500, description="申请推荐理由")
    is_draft: Optional[bool] = Field(
        False, description="是否保存为草稿（草稿仅作者本人可见，可稍后继续编辑并发布）"
    )


class ColumnArticleUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=150, description="文章标题")
    content: Optional[str] = Field(None, min_length=1, description="文章正文（Markdown）")
    summary: Optional[str] = Field(None, max_length=500, description="文章摘要")
    category: Optional[str] = Field(None, description="文章分类")
    cover_url: Optional[str] = Field(None, max_length=500, description="文章封面图片")
    column_id: Optional[int] = Field(None, description="所属专栏ID")
    detach_column: Optional[bool] = Field(False, description="是否脱离专栏变为独立文章")
    problem_id: Optional[int] = Field(None, description="关联题目ID")
    problem_code: Optional[str] = Field(None, description="关联题号（如 P1001 / T1 / U1001）")
    clear_problem: Optional[bool] = Field(False, description="是否清除关联题目")
    apply_recommend: Optional[bool] = Field(None, description="是否重新申请全站推荐")
    recommend_reason: Optional[str] = Field(None, max_length=500, description="申请推荐理由")


class ColumnArticleRecommendUpdate(BaseModel):
    is_recommended: bool = Field(..., description="是否推荐至文章广场精选")


class ArticleRecommendApply(BaseModel):
    reason: Optional[str] = Field(None, max_length=500, description="申请全站推荐理由")


class ArticleRecommendReview(BaseModel):
    action: str = Field(..., description="审批动作：approve 通过 / reject 驳回 / cancel 取消推荐")
    reason: Optional[str] = Field(None, max_length=500, description="审核意见或驳回原因")


class ColumnArticleDetail(BaseModel):
    id: int
    column_id: Optional[int] = None
    title: str
    content: str
    summary: Optional[str] = None
    cover_url: Optional[str] = None
    category: str = "算法理论"
    is_recommended: bool = False
    is_draft: bool = False
    problem_id: Optional[int] = None
    problem_code: Optional[str] = None
    problem_title: Optional[str] = None
    recommend_status: str = "none"
    recommend_reason: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    reviewer_username: Optional[str] = None
    view_count: int = 0
    like_count: int = 0
    star_count: int = 0
    comment_count: int = 0
    is_liked: bool = False
    is_starred: bool = False
    created_at: datetime
    updated_at: datetime
    author: Optional[AuthorBrief] = None
    column_title: Optional[str] = None


class ArticleListResponse(BaseModel):
    items: list[ColumnArticleListItem]
    total: int
    page: int
    page_size: int


ArticleListItem = ColumnArticleListItem
ArticleDetail = ColumnArticleDetail
ArticleCreate = ColumnArticleCreate
ArticleUpdate = ColumnArticleUpdate
ArticleRecommendUpdate = ColumnArticleRecommendUpdate


# ==================== 专栏点赞/收藏（向下兼容） ====================
class ColumnLikeResponse(BaseModel):
    liked: bool
    like_count: int


class ColumnStarResponse(BaseModel):
    starred: bool
    star_count: int


class ColumnCommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000, description="评论内容（支持 Markdown / KaTeX）")


class ColumnCommentItem(BaseModel):
    id: int
    column_id: int
    content: str
    created_at: datetime
    updated_at: datetime
    author: Optional[AuthorBrief] = None
    is_author: bool = False
    can_delete: bool = False


# ==================== 文章点赞/收藏/评论（一等公民） ====================
class ArticleLikeResponse(BaseModel):
    liked: bool
    like_count: int


class ArticleStarResponse(BaseModel):
    starred: bool
    star_count: int


class ArticleCommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000, description="评论内容（支持 Markdown / KaTeX）")


class ArticleCommentItem(BaseModel):
    id: int
    article_id: int
    content: str
    created_at: datetime
    updated_at: datetime
    author: Optional[AuthorBrief] = None
    is_author: bool = False
    can_delete: bool = False


# ==================== 专栏收录申请 ====================
class ColumnInclusionRequestCreate(BaseModel):
    article_id: int = Field(..., description="申请收录的文章ID")
    message: Optional[str] = Field(None, max_length=500, description="申请说明/推荐语")


class ColumnInclusionRequestReview(BaseModel):
    action: str = Field(..., pattern="^(approve|reject)$", description="审核操作：approve 或 reject")
    reply: Optional[str] = Field(None, max_length=500, description="审核意见/理由")


class ColumnInclusionArticleBrief(BaseModel):
    id: int
    title: str
    summary: Optional[str] = None
    category: str = "算法理论"
    created_at: datetime
    column_id: Optional[int] = None
    author: Optional[AuthorBrief] = None


class ColumnInclusionColumnBrief(BaseModel):
    id: int
    title: str
    author_id: int


class ColumnInclusionRequestItem(BaseModel):
    id: int
    column_id: int
    article_id: int
    applicant_id: int
    status: str
    message: Optional[str] = None
    reply: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    article: Optional[ColumnInclusionArticleBrief] = None
    column: Optional[ColumnInclusionColumnBrief] = None
    applicant: Optional[AuthorBrief] = None


