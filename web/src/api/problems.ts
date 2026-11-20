import apiClient from './client'
import type {
  Problem,
  ProblemAttachment,
  ProblemListItem,
  ProblemListResponse,
  ProblemReviewStatus,
} from '@/types'

export interface ProblemFilterParams {
  page?: number
  page_size?: number
  difficulty?: string
  source?: string
  tag?: string
  keyword?: string
  all?: boolean
  // public 题库（默认）/ mine 我出的题 / review 审核后台
  scope?: 'public' | 'mine' | 'review'
  review_status?: ProblemReviewStatus
}

export const problemsApi = {
  // 题目列表（支持难度 / 来源 / 标签 / 关键词筛选）
  async list(
    params: ProblemFilterParams = {}
  ): Promise<ProblemListResponse> {
    return apiClient.get('/api/problems', { params })
  },

  // 题目详情（含题面）
  async get(id: number): Promise<Problem> {
    return apiClient.get(`/api/problems/${id}`)
  },

  // 按统一题号访问（P1001 / U1001 / T10）
  async getByCode(code: string): Promise<Problem> {
    return apiClient.get(`/api/problems/by-code/${encodeURIComponent(code)}`)
  },

  // 去重后的来源列表（筛选下拉用）
  async sources(): Promise<string[]> {
    return apiClient.get('/api/problems/sources')
  },

  // 创建题目（所有人可创建主题库题；普通用户公开需审核）
  async create(data: Partial<Problem>): Promise<Problem> {
    return apiClient.post('/api/problems', data)
  },

  async update(
    id: number,
    data: Partial<Problem> & { author?: string }
  ): Promise<Problem> {
    return apiClient.put(`/api/problems/${id}`, data)
  },

  // 后台审核：通过 / 驳回（驳回需填写原因）
  async review(
    id: number,
    action: 'approve' | 'reject',
    reason?: string
  ): Promise<Problem> {
    return apiClient.post(`/api/problems/${id}/review`, { action, reason })
  },

  // 获取投题审核门槛与各难度完成状态
  async getSubmitEligibility(): Promise<{
    can_bypass: boolean
    threshold: number
    stats: Record<
      string,
      { exact_count: number; ge_count: number; threshold: number; qualified: boolean }
    >
  }> {
    return apiClient.get('/api/problems/submit-eligibility')
  },

  // 解析题目 Markdown 题面
  async parseMarkdown(content: string) {
    return apiClient.post('/api/problems/parse-markdown', { content })
  },

  // 上传题目附件（单文件最大 16MB）
  async uploadAttachment(
    id: number,
    file: File
  ): Promise<{ success: boolean; attachment: ProblemAttachment }> {
    const form = new FormData()
    form.append('file', file)
    return apiClient.post(`/api/problems/${id}/attachments`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  // 删除题目附件
  async deleteAttachment(
    id: number,
    attachmentId: number
  ): Promise<{ success: boolean }> {
    return apiClient.delete(`/api/problems/${id}/attachments/${attachmentId}`)
  },

  // 管理员切换题解提交通道开关
  async toggleSolutionSubmission(id: number, allow?: boolean): Promise<Problem> {
    return apiClient.post(
      `/api/problems/${id}/toggle-solution-submission`,
      allow !== undefined ? { allow } : {}
    )
  },

  // 提交题目进主题库（我的题库里的草稿 / 被驳回题 → 待审核）
  // 注意：与 migrate(target='library') 语义不同 —— 这个走审核队列（转 pending），
  // 而 migrate 要求已过审才能进主题库。勿互相委托。
  async submitToLibrary(id: number): Promise<{
    success: boolean
    problem_id: number
    problem_number: string
    review_status: string
  }> {
    return apiClient.post(`/api/problems/${id}/submit-to-library`)
  },

  // 题目迁移：主题库 / 团队题 / 比赛赛题之间互搬
  async migrate(
    id: number,
    data: {
      target: 'library' | 'team' | 'contest'
      team_id?: number
      contest_id?: number
      keep_in_library?: boolean
    }
  ): Promise<{
    success: boolean
    problem_id: number
    moved_from: string
    target: string
    problem_number: string
    team_id: number | null
    is_official: boolean
  }> {
    return apiClient.post(`/api/problems/${id}/migrate`, data)
  },

  // 上传 ZIP 压缩包批量导入题目（包含 Markdown 题面和测试点文件夹）
  async importZip(
    file: File,
    options?: {
      problem_id?: number
      team_id?: number
      is_public?: boolean
      clear_existing_cases?: boolean
    }
  ): Promise<{
    success: boolean
    problem: Problem
    imported_test_cases: number
    detected_subtasks: number[]
    subtask_config?: any[]
  }> {
    const formData = new FormData()
    formData.append('file', file)
    if (options?.problem_id !== undefined && options.problem_id !== null) {
      formData.append('problem_id', String(options.problem_id))
    }
    if (options?.team_id !== undefined && options.team_id !== null) {
      formData.append('team_id', String(options.team_id))
    }
    if (options?.is_public !== undefined && options.is_public !== null) {
      formData.append('is_public', String(options.is_public))
    }
    if (options?.clear_existing_cases !== undefined) {
      formData.append('clear_existing_cases', String(options.clear_existing_cases))
    }
    return apiClient.post('/api/problems/import-zip', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  // 批量上传多个 ZIP 压缩包导入多个题目与数据点
  async importBatchZip(
    files: File[],
    options?: {
      team_id?: number
      is_public?: boolean
    }
  ): Promise<ImportBatchZipResponse> {
    const formData = new FormData()
    for (const file of files) {
      formData.append('files', file)
    }
    if (options?.team_id !== undefined && options.team_id !== null) {
      formData.append('team_id', String(options.team_id))
    }
    if (options?.is_public !== undefined && options.is_public !== null) {
      formData.append('is_public', String(options.is_public))
    }
    return apiClient.post('/api/problems/import-batch-zip', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
}

export interface ImportBatchZipItemResult {
  filename: string
  success: boolean
  error?: string
  problem?: Problem
  imported_test_cases?: number
  detected_subtasks?: number[]
  subtask_config?: any[]
}

export interface ImportBatchZipResponse {
  total: number
  succeeded: number
  failed: number
  results: ImportBatchZipItemResult[]
}

export type { Problem, ProblemListItem }
