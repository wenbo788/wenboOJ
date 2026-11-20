import apiClient from './client'

export interface TrainingProblemItem {
  problem_id: number
  id?: number
  sort_order: number
  problem_number: string
  title: string
  difficulty: string
  accepted_count?: number
  submission_count?: number
  solved_count?: number
  submit_count?: number
  // accepted / attempted / null（未提交）
  my_status?: string | null
  status?: string | null
}

export interface TrainingOwner {
  id?: number
  user_id: number
  username: string
  user_number?: number
  avatar_url?: string
  display_tag?: string
  user_tag?: string
  username_color?: string
  is_admin?: boolean
  is_super_admin?: boolean
}

export interface TrainingItem {
  id: number
  title: string
  description: string
  is_featured: boolean
  is_public: boolean
  owner: TrainingOwner
  author?: TrainingOwner
  created_at: string | null
  updated_at?: string | null
  problem_count: number
  solved_count: number
  user_solved_count?: number
  can_edit?: boolean
  can_feature?: boolean
  is_super_admin?: boolean
  is_admin?: boolean
  problems?: TrainingProblemItem[]
}

export type TrainingListItem = TrainingItem
export type TrainingDetail = TrainingItem

export interface TrainingListParams {
  page?: number
  page_size?: number
  hide_completed?: boolean
  featured_only?: boolean
  /** official = 官方题单(P), user = 用户题单(U) */
  scope?: 'official' | 'user'
  owner_id?: number
  author_id?: number
  keyword?: string
  search?: string
}

export const trainingsApi = {
  async list(
    paramsOrPage: TrainingListParams | number = 0,
    hideCompleted = false,
    featuredOnly = false
  ): Promise<{ items: TrainingItem[]; total: number }> {
    let params: any
    if (typeof paramsOrPage === 'number') {
      params = {
        page: paramsOrPage,
        page_size: 50,
        hide_completed: hideCompleted || undefined,
        featured_only: featuredOnly || undefined,
      }
    } else {
      params = { ...paramsOrPage }
      if (!params.page_size) params.page_size = 50
    }
    return apiClient.get('/api/trainings', { params })
  },

  async get(id: number): Promise<TrainingItem> {
    return apiClient.get(`/api/trainings/${id}`)
  },

  async create(data: {
    title: string
    description?: string
    is_public?: boolean
    problem_codes?: string[]
  }): Promise<TrainingItem> {
    return apiClient.post('/api/trainings', data)
  },

  async update(
    id: number,
    data: {
      title?: string
      description?: string
      is_public?: boolean
      problem_codes?: string[]
    }
  ): Promise<TrainingItem> {
    return apiClient.put(`/api/trainings/${id}`, data)
  },

  async remove(id: number): Promise<{ success: boolean }> {
    return apiClient.delete(`/api/trainings/${id}`)
  },

  async addProblem(
    id: number,
    problem_code: string
  ): Promise<{ success: boolean; problem_id: number; problem_number: string; title: string }> {
    return apiClient.post(`/api/trainings/${id}/problems`, { problem_code })
  },

  async removeProblem(id: number, problem_id: number): Promise<{ success: boolean }> {
    return apiClient.delete(`/api/trainings/${id}/problems/${problem_id}`)
  },

  async toggleFeature(
    id: number,
    is_featured?: boolean
  ): Promise<{ success: boolean; is_featured: boolean }> {
    return apiClient.put(`/api/trainings/${id}/feature`, is_featured !== undefined ? { is_featured } : {})
  },

  async reorderProblems(
    id: number,
    problem_ids: number[]
  ): Promise<TrainingItem> {
    return apiClient.put(`/api/trainings/${id}/problems/reorder`, { problem_ids })
  },
}

// Named function exports for flexible imports
export const getTrainingLists = (params?: TrainingListParams) => trainingsApi.list(params)
export const getTrainingDetail = (id: number) => trainingsApi.get(id)
export const createTrainingList = (data: Parameters<typeof trainingsApi.create>[0]) => trainingsApi.create(data)
export const updateTrainingList = (id: number, data: Parameters<typeof trainingsApi.update>[1]) => trainingsApi.update(id, data)
export const deleteTrainingList = (id: number) => trainingsApi.remove(id)
export const addProblemToTraining = (id: number, code: string) => trainingsApi.addProblem(id, code)
export const removeProblemFromTraining = (id: number, pid: number) => trainingsApi.removeProblem(id, pid)
export const toggleFeatureTraining = (id: number, is_featured?: boolean) => trainingsApi.toggleFeature(id, is_featured)
export const reorderTrainingProblems = (id: number, problem_ids: number[]) => trainingsApi.reorderProblems(id, problem_ids)
