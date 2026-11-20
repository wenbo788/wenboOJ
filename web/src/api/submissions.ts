import apiClient from './client'
import type {
  Submission,
  SubmissionListResponse,
  TestCaseItem,
} from '@/types'

export interface SubmissionListParams {
  page?: number
  page_size?: number
  problem_id?: number
}

export const submissionsApi = {
  // 提交代码（后台评测，返回的 status 短暂为 pending/judging）
  async create(
    problemId: number,
    data: { code: string; language: string; contest_id?: number }
  ): Promise<Submission> {
    return apiClient.post(`/api/problems/${problemId}/submissions`, data)
  },

  // 某题的提交记录（全站可见）
  async listByProblem(
    problemId: number,
    params: { page?: number; page_size?: number } = {}
  ): Promise<SubmissionListResponse> {
    return apiClient.get(`/api/problems/${problemId}/submissions`, { params })
  },

  async rejudge(
    problemId: number,
    score: 0 | 100 | null = null,
  ): Promise<{ queued: number; skipped: number; score: 0 | 100 | null }> {
    return apiClient.post(`/api/problems/${problemId}/submissions/rejudge`, { score })
  },

  // 单条重测
  async rejudgeOne(id: number): Promise<{ queued: number; skipped: number }> {
    return apiClient.post(`/api/submissions/${id}/rejudge`)
  },

  // 单条取消成绩
  async cancelScoreOne(id: number): Promise<{ cancelled: number; skipped: number }> {
    return apiClient.post(`/api/submissions/${id}/cancel-score`)
  },

  // 批量取消成绩
  async cancelScore(
    problemId: number,
    score: 0 | 100 | null = null,
  ): Promise<{ cancelled: number; skipped: number; score: 0 | 100 | null }> {
    return apiClient.post(`/api/problems/${problemId}/submissions/cancel-score`, { score })
  },

  // 我的提交记录（可按题目过滤）
  async listMine(
    params: SubmissionListParams = {}
  ): Promise<SubmissionListResponse> {
    return apiClient.get('/api/submissions/mine', { params })
  },

  // 我在该题的最后一次提交（含代码，用于提交页回填）；从未提交返回 null
  async getMyLast(problemId: number): Promise<Submission | null> {
    return apiClient.get(`/api/problems/${problemId}/my-last-submission`)
  },

  // 提交详情
  async get(id: number): Promise<Submission> {
    return apiClient.get(`/api/submissions/${id}`)
  },
}

export const testCasesApi = {
  async uploadZip(problemId: number, file: File, clearExisting = false): Promise<{ success: boolean; imported: number }> {
    const fd = new FormData()
    fd.append('file', file)
    return apiClient.post(`/api/problems/${problemId}/test-cases/upload-zip`, fd, {
      params: { clear_existing: clearExisting },
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },
  async clearAll(problemId: number): Promise<{ success: boolean; deleted_count?: number }> {
    return apiClient.delete(`/api/problems/${problemId}/test-cases`)
  },
  async list(problemId: number): Promise<TestCaseItem[]> {
    return apiClient.get(`/api/problems/${problemId}/test-cases`)
  },
  async get(problemId: number, caseId: number): Promise<TestCaseItem> {
    return apiClient.get(`/api/problems/${problemId}/test-cases/${caseId}`)
  },
  async create(problemId: number, data: { input_data: string; expected_output: string }): Promise<TestCaseItem> {
    return apiClient.post(`/api/problems/${problemId}/test-cases`, data)
  },
  async remove(problemId: number, caseId: number): Promise<{ success: boolean }> {
    return apiClient.delete(`/api/problems/${problemId}/test-cases/${caseId}`)
  },
  async batchDelete(problemId: number, caseIds: number[]): Promise<{ success: boolean; deleted_count: number }> {
    return apiClient.post(`/api/problems/${problemId}/test-cases/batch-delete`, { case_ids: caseIds })
  },
  async update(
    problemId: number,
    caseId: number,
    data: { subtask_id?: number | null; subtask_score?: number | null; input_data?: string; expected_output?: string }
  ): Promise<TestCaseItem> {
    return apiClient.patch(`/api/problems/${problemId}/test-cases/${caseId}`, data)
  },
  async updateSubtasks(
    problemId: number,
    data: {
      subtask_config: { id: number; score: number; name?: string }[]
      case_subtasks?: Record<number, number | null>
    }
  ): Promise<{ success: boolean; subtask_config: { id: number; score: number; name?: string }[] }> {
    return apiClient.put(`/api/problems/${problemId}/subtasks`, data)
  },
}
