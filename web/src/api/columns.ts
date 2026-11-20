import apiClient from './client'

export interface ColumnAuthor {
  id: number
  username: string
  user_number?: number
  avatar_url?: string
  user_tag?: string
  username_color?: string
  rating?: number
  role?: string
  is_admin?: boolean
  is_super_admin?: boolean
  last_seen?: string | null
}

export interface ColumnArticleItem {
  id: number
  column_id?: number | null
  title: string
  summary?: string
  cover_url?: string
  category?: string
  is_recommended?: boolean
  /** 草稿标记：仅作者本人可见，未发布 */
  is_draft?: boolean
  problem_id?: number | null
  problem_code?: string | null
  problem_title?: string | null
  recommend_status?: string
  recommend_reason?: string | null
  view_count: number
  like_count?: number
  star_count?: number
  comment_count?: number
  created_at: string
  updated_at: string
  author?: ColumnAuthor
  column_title?: string
}

export interface ColumnArticleDetail extends ColumnArticleItem {
  content: string
  column_title?: string
  reviewed_at?: string | null
  reviewer_username?: string | null
  like_count: number
  star_count: number
  comment_count: number
  is_liked: boolean
  is_starred: boolean
}

export const COLUMN_CATEGORIES = ['算法理论', '科技工程', '娱乐', '题解'] as const
export type ColumnCategory = (typeof COLUMN_CATEGORIES)[number]

export interface ColumnItem {
  id: number
  title: string
  description?: string
  cover_url?: string
  category?: string
  author_id: number
  is_recommended: boolean
  article_count: number
  like_count?: number
  star_count?: number
  comment_count?: number
  created_at: string
  updated_at: string
  author?: ColumnAuthor
}

export interface ColumnDetail extends ColumnItem {
  articles: ColumnArticleItem[]
  like_count: number
  star_count: number
  comment_count: number
  is_liked: boolean
  is_starred: boolean
}

export interface ColumnCommentItem {
  id: number
  column_id: number
  content: string
  created_at: string
  updated_at: string
  author?: ColumnAuthor
  is_author: boolean
  can_delete: boolean
}

export interface ColumnLikeResponse {
  liked: boolean
  like_count: number
}

export interface ColumnStarResponse {
  starred: boolean
  star_count: number
}

export interface ArticleLikeResponse {
  liked: boolean
  like_count: number
}

export interface ArticleStarResponse {
  starred: boolean
  star_count: number
}

export interface ArticleCommentItem {
  id: number
  article_id: number
  content: string
  created_at: string
  updated_at: string
  author?: ColumnAuthor
  is_author: boolean
  can_delete: boolean
}

export interface ColumnListParams {
  page?: number
  page_size?: number
  category?: string
  author_id?: number
  starred_by?: number
  is_recommended?: boolean
  keyword?: string
}

export interface ColumnListResponse {
  items: ColumnItem[]
  total: number
  page: number
  page_size: number
}

export interface ColumnCreateParams {
  title: string
  description?: string
  cover_url?: string
  category?: string
}

export interface ColumnUpdateParams {
  title?: string
  description?: string
  cover_url?: string
  category?: string
}

export interface ArticleListParams {
  page?: number
  page_size?: number
  category?: string
  is_recommended?: boolean
  author_id?: number
  column_id?: number
  keyword?: string
  problem_id?: number
  problem_code?: string
  recommend_status?: string
}

export interface ArticleListResponse {
  items: ColumnArticleItem[]
  total: number
  page: number
  page_size: number
}

export interface ArticleCreateParams {
  title: string
  content: string
  summary?: string
  category?: string
  cover_url?: string
  column_id?: number | null
  problem_id?: number | null
  problem_code?: string | null
  apply_recommend?: boolean
  recommend_reason?: string | null
  /** 保存为草稿：仅作者本人可见，可稍后继续编辑并发布 */
  is_draft?: boolean
}

export interface ArticleUpdateParams {
  title?: string
  content?: string
  summary?: string
  category?: string
  cover_url?: string
  column_id?: number | null
  detach_column?: boolean
  problem_id?: number | null
  problem_code?: string | null
  clear_problem?: boolean
  apply_recommend?: boolean
  recommend_reason?: string | null
}

export interface ArticleRecommendApplyParams {
  reason?: string
}

export interface ArticleRecommendReviewParams {
  action: 'approve' | 'reject'
  reason?: string
}

export interface ColumnInclusionArticleBrief {
  id: number
  title: string
  summary?: string
  category?: string
  created_at: string
  column_id?: number | null
  author?: ColumnAuthor
}

export interface ColumnInclusionColumnBrief {
  id: number
  title: string
  author_id: number
}

export interface ColumnInclusionRequestItem {
  id: number
  column_id: number
  article_id: number
  applicant_id: number
  status: 'pending' | 'approved' | 'rejected' | 'cancelled'
  message?: string | null
  reply?: string | null
  created_at: string
  updated_at: string
  article?: ColumnInclusionArticleBrief
  column?: ColumnInclusionColumnBrief
  applicant?: ColumnAuthor
}

export interface ColumnInclusionRequestCreateParams {
  article_id: number
  message?: string
}

export interface ColumnInclusionRequestReviewParams {
  action: 'approve' | 'reject'
  reply?: string
}

export const columnsApi = {
  // 获取专栏列表
  async list(params: ColumnListParams = {}): Promise<ColumnListResponse> {
    const q = new URLSearchParams()
    if (params.page) q.append('page', String(params.page))
    if (params.page_size) q.append('page_size', String(params.page_size))
    if (params.category) q.append('category', params.category)
    if (params.author_id !== undefined && params.author_id !== null) {
      q.append('author_id', String(params.author_id))
    }
    if (params.starred_by !== undefined && params.starred_by !== null) {
      q.append('starred_by', String(params.starred_by))
    }
    if (params.is_recommended !== undefined && params.is_recommended !== null) {
      q.append('is_recommended', String(params.is_recommended))
    }
    if (params.keyword) q.append('keyword', params.keyword)

    const queryStr = q.toString()
    return apiClient.get(queryStr ? `/api/columns?${queryStr}` : '/api/columns')
  },

  // 获取专栏详情
  async get(columnId: number): Promise<ColumnDetail> {
    return apiClient.get(`/api/columns/${columnId}`)
  },

  // 创建专栏
  async create(data: ColumnCreateParams): Promise<ColumnItem> {
    return apiClient.post('/api/columns', data)
  },

  // 更新专栏
  async update(columnId: number, data: ColumnUpdateParams): Promise<ColumnItem> {
    return apiClient.put(`/api/columns/${columnId}`, data)
  },

  // 删除专栏
  async delete(columnId: number): Promise<{ message: string; id: number }> {
    return apiClient.delete(`/api/columns/${columnId}`)
  },

  // 管理员推荐/取消推荐专栏
  async toggleRecommend(columnId: number, is_recommended: boolean): Promise<ColumnItem> {
    return apiClient.put(`/api/columns/${columnId}/recommend`, { is_recommended })
  },

  // 点赞/取消点赞
  async toggleLike(columnId: number): Promise<ColumnLikeResponse> {
    return apiClient.post(`/api/columns/${columnId}/like`)
  },

  // 收藏/取消收藏
  async toggleStar(columnId: number): Promise<ColumnStarResponse> {
    return apiClient.post(`/api/columns/${columnId}/star`)
  },

  // 获取专栏评论
  async getComments(columnId: number): Promise<ColumnCommentItem[]> {
    return apiClient.get(`/api/columns/${columnId}/comments`)
  },

  // 发布评论
  async createComment(columnId: number, content: string): Promise<ColumnCommentItem> {
    return apiClient.post(`/api/columns/${columnId}/comments`, { content })
  },

  // 删除评论
  async deleteComment(columnId: number, commentId: number): Promise<{ message: string; id: number }> {
    return apiClient.delete(`/api/columns/${columnId}/comments/${commentId}`)
  },

  // 发布文章
  async createArticle(columnId: number, data: ArticleCreateParams): Promise<ColumnArticleItem> {
    return apiClient.post(`/api/columns/${columnId}/articles`, data)
  },

  // 获取文章详情
  async getArticle(columnId: number, articleId: number): Promise<ColumnArticleDetail> {
    return apiClient.get(`/api/columns/${columnId}/articles/${articleId}`)
  },

  // 更新文章
  async updateArticle(columnId: number, articleId: number, data: ArticleUpdateParams): Promise<ColumnArticleItem> {
    return apiClient.put(`/api/columns/${columnId}/articles/${articleId}`, data)
  },

  // 删除文章
  async deleteArticle(columnId: number, articleId: number): Promise<{ message: string; id: number }> {
    return apiClient.delete(`/api/columns/${columnId}/articles/${articleId}`)
  },

  // 获取当前登录用户拥有的专栏列表
  async getMyColumns(): Promise<ColumnItem[]> {
    return apiClient.get('/api/columns/my')
  },

  // 提交文章收录申请
  async applyInclusion(columnId: number, data: ColumnInclusionRequestCreateParams): Promise<ColumnInclusionRequestItem> {
    return apiClient.post(`/api/columns/${columnId}/inclusion-requests`, data)
  },

  // 获取专栏的收录申请列表
  async getInclusionRequests(columnId: number): Promise<ColumnInclusionRequestItem[]> {
    return apiClient.get(`/api/columns/${columnId}/inclusion-requests`)
  },

  // 审核专栏收录申请
  async reviewInclusionRequest(columnId: number, requestId: number, data: ColumnInclusionRequestReviewParams): Promise<ColumnInclusionRequestItem> {
    return apiClient.post(`/api/columns/${columnId}/inclusion-requests/${requestId}/review`, data)
  },

  // 撤回专栏收录申请
  async cancelInclusionRequest(columnId: number, requestId: number): Promise<{ message: string; id: number }> {
    return apiClient.delete(`/api/columns/${columnId}/inclusion-requests/${requestId}`)
  },

  // 将文章移出专栏（保留文章）
  async detachArticle(columnId: number, articleId: number): Promise<{ message: string; article_id: number; column_id: number }> {
    return apiClient.post(`/api/columns/${columnId}/articles/${articleId}/detach`)
  },
}

export const articlesApi = {
  // 获取文章列表（文章广场信息流）
  async list(params: ArticleListParams = {}): Promise<ArticleListResponse> {
    const q = new URLSearchParams()
    if (params.page) q.append('page', String(params.page))
    if (params.page_size) q.append('page_size', String(params.page_size))
    if (params.category && params.category !== 'all') q.append('category', params.category)
    if (params.author_id !== undefined && params.author_id !== null) {
      q.append('author_id', String(params.author_id))
    }
    if (params.column_id !== undefined && params.column_id !== null) {
      q.append('column_id', String(params.column_id))
    }
    if (params.is_recommended !== undefined && params.is_recommended !== null) {
      q.append('is_recommended', String(params.is_recommended))
    }
    if (params.keyword) q.append('keyword', params.keyword)
    if (params.problem_id !== undefined && params.problem_id !== null) {
      q.append('problem_id', String(params.problem_id))
    }
    if (params.problem_code) q.append('problem_code', params.problem_code)
    if (params.recommend_status) q.append('recommend_status', params.recommend_status)

    const queryStr = q.toString()
    return apiClient.get(queryStr ? `/api/articles?${queryStr}` : '/api/articles')
  },

  // 获取文章详情（自动增加阅读量）
  async get(articleId: number): Promise<ColumnArticleDetail> {
    return apiClient.get(`/api/articles/${articleId}`)
  },

  // 发布新文章（独立或属于专栏）
  async create(data: ArticleCreateParams): Promise<ColumnArticleDetail> {
    return apiClient.post('/api/articles', data)
  },

  // 编辑文章
  async update(articleId: number, data: ArticleUpdateParams): Promise<ColumnArticleDetail> {
    return apiClient.put(`/api/articles/${articleId}`, data)
  },

  // 我的草稿列表（仅本人可见）
  // 我的草稿列表（仅本人可见）；后端默认 50 条/页，最多 200
  async listDrafts(page = 1, pageSize = 50): Promise<ColumnArticleItem[]> {
    return apiClient.get('/api/articles/drafts', { params: { page, page_size: pageSize } })
  },

  // 发布草稿（is_draft -> false，服务端会补做发布校验）
  async publishDraft(articleId: number): Promise<ColumnArticleDetail> {
    return apiClient.post(`/api/articles/${articleId}/publish`)
  },

  // 删除文章
  async delete(articleId: number): Promise<{ message: string; id: number }> {
    return apiClient.delete(`/api/articles/${articleId}`)
  },

  // 管理员推荐/取消推荐单篇文章
  async toggleRecommend(articleId: number, is_recommended: boolean): Promise<ColumnArticleDetail> {
    return apiClient.put(`/api/articles/${articleId}/recommend`, { is_recommended })
  },

  // 作者申请全站推荐
  async applyRecommend(articleId: number, data?: ArticleRecommendApplyParams): Promise<ColumnArticleDetail> {
    return apiClient.post(`/api/articles/${articleId}/apply-recommend`, data || {})
  },

  // 管理员审核全站推荐
  async reviewRecommend(articleId: number, data: ArticleRecommendReviewParams): Promise<ColumnArticleDetail> {
    return apiClient.post(`/api/articles/${articleId}/review-recommend`, data)
  },

  // 管理员获取待审核推荐文章列表
  async getPendingRecommendations(params: { page?: number; page_size?: number } = {}): Promise<ArticleListResponse> {
    const q = new URLSearchParams()
    if (params.page) q.append('page', String(params.page))
    if (params.page_size) q.append('page_size', String(params.page_size))
    const queryStr = q.toString()
    return apiClient.get(queryStr ? `/api/articles/recommend/pending?${queryStr}` : '/api/articles/recommend/pending')
  },

  // 点赞/取消点赞文章
  async toggleLike(articleId: number): Promise<ArticleLikeResponse> {
    return apiClient.post(`/api/articles/${articleId}/like`)
  },

  // 收藏/取消收藏文章
  async toggleStar(articleId: number): Promise<ArticleStarResponse> {
    return apiClient.post(`/api/articles/${articleId}/star`)
  },

  // 获取文章评论列表
  async getComments(articleId: number): Promise<ArticleCommentItem[]> {
    return apiClient.get(`/api/articles/${articleId}/comments`)
  },

  // 发表文章评论
  async createComment(articleId: number, content: string): Promise<ArticleCommentItem> {
    return apiClient.post(`/api/articles/${articleId}/comments`, { content })
  },

  // 删除文章评论
  async deleteComment(articleId: number, commentId: number): Promise<{ message: string; id: number }> {
    return apiClient.delete(`/api/articles/${articleId}/comments/${commentId}`)
  },

  // 获取当前登录用户发布的所有文章
  async getMyArticles(): Promise<ColumnArticleItem[]> {
    return apiClient.get('/api/articles/my')
  },

  // 获取文章相关的专栏收录申请记录
  async getInclusionRequests(articleId: number): Promise<ColumnInclusionRequestItem[]> {
    return apiClient.get(`/api/articles/${articleId}/inclusion-requests`)
  },
}
