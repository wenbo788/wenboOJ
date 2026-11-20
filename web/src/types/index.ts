// 认证相关类型
export interface User {
  id: number
  username: string
  email: string
  user_number: number
  phone?: string | null
  is_active: boolean
  is_banned: boolean
  is_admin: boolean
  is_super_admin: boolean
  is_big_admin?: boolean
  is_cheater: boolean
  can_speak: boolean
  can_manage_users: boolean
  can_manage_posts: boolean
  can_manage_problems: boolean
  can_assign_admin: boolean
  experience?: number
  contribution?: number
  // 比赛等级分（只在 is_rated 的个人赛结算；未参加 = 1500）
  rating?: number
  max_rating?: number
  rated_contests?: number
  theme_background?: string | null
  theme_enabled?: boolean
  theme_hue?: number
  theme_mode?: 'light' | 'dark'
  home_style?: 'cloud' | 'luogu'
  /** 学术模式：隐藏犇犇/灌水区，题目难度默认隐藏（个人设置里开） */
  academic_mode?: boolean
  code_template?: Record<string, string> | null
  code_font?: string | null
  avatar_url?: string | null
  user_tag?: string | null
  username_color?: string | null
  bio?: string | null
  last_seen?: string | null
  last_username_change?: string | null
  followers_count?: number
  following_count?: number
  is_following?: boolean
  real_name?: string | null
  oierdb_uid?: string | null
  oi_awards?: any[] | null
  oi_level?: string | null
  award_cert_status?: string
  created_at: string
  updated_at?: string
}

export interface LoginCredentials {
  username: string
  password: string
}

/* ===== 图床 ===== */
/** 水印模式：none = 无水印（占高级空间）；text = 站点文字水印（占普通空间） */
export type WatermarkMode = 'none' | 'text'

export interface HostedImage {
  id: number
  url: string
  original_name: string | null
  size_bytes: number
  content_type: string | null
  /** none / text */
  watermark: string
  /** 是否占用「高级空间」 */
  is_premium: boolean
  is_locked: boolean
  created_at: string
}

export interface ImageListResponse {
  items: HostedImage[]
  total: number
  page: number
  page_size: number
}

export interface ImageQuota {
  total_count: number
  premium_used: number
  premium_quota: number
  basic_used: number
  basic_quota: number
  /** 超过该体积的图片强制占用高级空间 */
  premium_threshold: number
}

/* ===== 云剪贴板 ===== */
export type ClipboardKind = 'text' | 'code'

export interface ClipboardItem {
  id: number
  kind: ClipboardKind
  title: string | null
  language: string | null
  content: string
  created_at: string
  updated_at: string
}

export interface ClipboardListResponse {
  items: ClipboardItem[]
  total: number
  page: number
  page_size: number
}

export interface RegisterData {
  username: string
  email?: string
  phone?: string
  password: string
  email_token?: string
  email_code?: string
  phone_token?: string
  phone_code?: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

// 题目相关类型（难度）
export type ProblemDifficulty =
  | '暂无评定'
  | '入门'
  | '普及-'
  | '普及'
  | '普及+/提高-'
  | '提高'
  | '提高+/省选-'
  | '省选/NOI-'
  | 'NOI/NOI+/CTSC'

export interface ProblemSample {
  input: string
  output: string
}

// 题库列表中当前用户对某题的完成状态：已通过 / 提交过但未通过 / 从未提交
export type ProblemUserStatus = 'accepted' | 'attempted' | null

// 题目审核状态：draft 草稿 / pending 待审核 / approved 已通过 / rejected 已驳回
export type ProblemReviewStatus = 'draft' | 'pending' | 'approved' | 'rejected'

// 出题人简要信息（含全站配色判定字段；存量题可能为 null）
export interface ProblemAuthor {
  user_id: number
  username: string
  user_tag: string
  is_admin: boolean
  is_super_admin: boolean
  is_banned: boolean
  is_cheater: boolean
  can_manage_users: boolean
  can_manage_posts: boolean
  can_manage_problems: boolean
  user_number: number | null
  avatar_url: string
}

export interface SubtaskConfigItem {
  id: number
  score: number
  name?: string
}

// 题目附件（PDF 题面、数据表、素材等；单文件上限 16MB）
// download_url 指向带题目可见性鉴权的下载接口，不再暴露可直链下载的路径
export interface ProblemAttachment {
  id: number
  orig_name: string
  download_url: string | null
  size_bytes: number
  content_type: string | null
  uploader_name: string | null
  created_at: string | null
}

export interface Problem {
  id: number
  problem_number: string
  title: string
  difficulty: ProblemDifficulty
  source: string | null
  tags: string[]
  author?: ProblemAuthor | null
  description: string
  background: string
  input_format: string
  output_format: string
  hint: string
  samples: ProblemSample[]
  time_limit: number
  memory_limit: number
  submit_count: number
  solved_count: number
  pass_rate: number | null
  is_public: boolean
  allow_solution_submission?: boolean
  team_id?: number | null
  t_no?: number | null
  is_spj?: boolean
  spj_language?: string | null
  spj_code?: string | null
  subtask_config?: SubtaskConfigItem[]
  attachments?: ProblemAttachment[]
  review_status: ProblemReviewStatus
  review_reason?: string | null
  reviewed_at?: string | null
  created_at: string
  updated_at: string
  // 仅题库列表接口返回（详情接口没有该字段）
  my_status?: ProblemUserStatus
}

export type ProblemListItem = Omit<Problem, 'description'>

export interface ProblemListResponse {
  total: number
  page: number
  page_size: number
  items: ProblemListItem[]
}

// 提交相关类型
export type SubmissionStatus =
  | 'pending'
  | 'judging'
  | 'accepted'
  | 'partially_correct'
  | 'wrong_answer'
  | 'time_limit_exceeded'
  | 'memory_limit_exceeded'
  | 'runtime_error'
  | 'compile_error'
  | 'system_error'
  | 'cancelled'
  | 'submitted'

export interface SubmissionCaseResult {
  case: number
  subtask_id?: number
  status: string
  time: number
  memory: number
}

export interface SubtaskResult {
  subtask_id: number
  name: string
  score: number
  total_score: number
  status: string
  time: number
  memory: number
  cases: SubmissionCaseResult[]
}

export interface SubmissionUser {
  user_id: number
  username: string
  user_number: number
  avatar_url: string
  is_admin: boolean
}

export interface Submission {
  id: number
  problem_id: number
  contest_id?: number | null
  problem_number: string
  problem_title?: string | null
  user: SubmissionUser
  language: string
  status: SubmissionStatus
  score: number
  time_used?: number | null
  memory_used?: number | null
  error_message?: string | null
  test_results: SubmissionCaseResult[]
  subtask_results?: SubtaskResult[]
  code?: string
  code_visible?: boolean
  /** 代码被隐藏的原因（比赛进行中），没有该字段时按「无权查看他人代码」处理 */
  code_hidden_reason?: string
  /** OI 赛制比赛进行中时，评测结果对非管理员隐藏 */
  result_hidden?: boolean
  judged_at?: string | null
  created_at: string
}

export interface SubmissionListResponse {
  total: number
  page: number
  page_size: number
  items: Submission[]
}

export interface TestCaseItem {
  id: number
  input_data: string
  expected_output: string
  input_preview?: string
  expected_output_preview?: string
  input_size?: number
  expected_output_size?: number
  sort_order: number
  subtask_id?: number | null
  subtask_score?: number | null
}

// 通用 API 响应类型
export interface ApiResponse<T> {
  data: T
  message?: string
}

export interface ApiError {
  detail: string
  status_code?: number
}

// ==================== 站点配置（顶栏公告 / 首页云图） ====================

/** 顶栏滚动公告的单条内容（link 可空，空则点击不跳转） */
export interface AnnouncementItem {
  text: string
  link?: string | null
}

/** 顶栏公告配置（GET/PUT /api/site-settings/announcement） */
export interface AnnouncementConfig {
  enabled: boolean
  items: AnnouncementItem[]
}

/** 首页云图可修改卡：精选题目（管理员选题，最多 4 道） */
export interface HomeCloudFeaturedConfig {
  enabled: boolean
  title?: string
  problem_ids?: number[]
}

/** 首页云图可修改卡：置顶讨论（管理员选帖，最多 4 条） */
export interface HomeCloudPinnedConfig {
  enabled: boolean
  title?: string
  post_ids?: number[]
}

/**
 * 首页云图配置（GET/PUT /api/site-settings/home-cloud）。
 * 另有三张固定随机卡（友情链接 / 随机题目 / 随机讨论）不进配置，
 * 启用板块即展示、不可修改。
 */
export interface HomeCloudConfig {
  enabled: boolean
  featured_problems: HomeCloudFeaturedConfig
  pinned_posts: HomeCloudPinnedConfig
}

/** 公开解析后的云图栏目（GET /api/home/cloud）中的一张小卡类型 */
export type HomeCloudCardType = 'posts' | 'problems' | 'friend_links'

/** 公开解析后的云图栏目（GET /api/home/cloud）：items 为后端按配置取好的内容 */
export interface HomeCloudCardResolved {
  type: HomeCloudCardType
  title: string
  items: any[]
}

// 全局类型扩展
declare global {
  interface Window {
    __AUTH_TOKENS__?: {
      accessToken: string
      refreshToken: string
      apiUrl: string
    }
    __AUTH_INFO__?: {
      accessToken: string
      refreshToken: string
      apiUrl: string
      currentUser: User | null
    }
    supabase?: any
  }
}

export {} // 确保这是模块文件
