import apiClient from './client'

export interface PollOption {
  id: number
  text: string
  /** 看不到结果时为 null */
  votes: number | null
  percent: number | null
}

export interface Poll {
  id: number
  title: string
  description: string
  allow_multiple: boolean
  anonymous: boolean
  show_results_before_end: boolean
  created_by: number
  created_at: string | null
  ends_at: string | null
  closed_at: string | null
  open: boolean
  results_visible: boolean
  options: PollOption[]
  total_votes: number | null
  voter_count: number
  my_votes: number[]
  voters: { user_number: number; username: string; avatar_url: string }[]
}

export const pollsApi = {
  async list(status: 'all' | 'open' | 'closed' = 'all', page = 0, pageSize = 20) {
    return apiClient.get('/api/polls', { params: { status, page, page_size: pageSize } })
  },
  async get(id: number): Promise<Poll> {
    return apiClient.get(`/api/polls/${id}`)
  },
  async create(payload: {
    title: string
    description?: string
    options: string[]
    allow_multiple?: boolean
    anonymous?: boolean
    show_results_before_end?: boolean
    ends_at?: string | null
  }): Promise<Poll> {
    return apiClient.post('/api/polls', payload)
  },
  async vote(id: number, optionIds: number[]): Promise<Poll> {
    return apiClient.post(`/api/polls/${id}/vote`, { option_ids: optionIds })
  },
  async close(id: number): Promise<Poll> {
    return apiClient.post(`/api/polls/${id}/close`)
  },
}
