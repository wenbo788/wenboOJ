import apiClient from './client'

export interface ContestProblemItem {
  alias: string
  problem_id: number
  sort_order: number
  title: string
  difficulty: string
  problem_number: string
}

export interface ContestRatingItem {
  user_id: number
  user_number: number
  username: string
  rank: number
  participants: number
  rating_before: number
  rating_after: number
  delta: number
}

export interface VirtualContestState {
  active: boolean
  virtual: {
    id: number
    source_contest_id: number
    started_at: string | null
    ends_at: string | null
    finished_at: string | null
    active: boolean
    remaining_seconds: number
  } | null
  results: {
    problem_id: number
    solved: boolean
    best_score: number
    attempts: number
    first_ac_at: string | null
  }[]
}

export interface ContestTeamMember {
  user_id?: number
  id?: number
  user_number: number | null
  username: string
  display_tag?: string | null
  username_color?: string | null
  color_tier?: string | null
  is_cheater?: boolean
  is_banned?: boolean
  is_super_admin?: boolean
  is_big_admin?: boolean
  can_manage_problems?: boolean
  is_leader?: boolean
}

export interface ContestTeamInfo {
  id: number
  name: string
  leader_id: number
  leader?: { id: number; username: string; user_number: number | null }
  is_leader?: boolean
  invite_code?: string
  member_count?: number
  members: ContestTeamMember[]
  created_at?: string | null
}

export interface ContestItem {
  id: number
  title: string
  description: string
  visibility: 'public' | 'private' | 'team' | 'team_private' | 'team_public'
  type_label: string
  team_id: number | null
  team_name: string | null
  invite_code?: string | null
  rule_type: 'xcpc' | 'acm' | 'ioi' | 'oi'
  rule_type_label?: string
  start_time: string | null
  end_time: string | null
  status: 'pending' | 'running' | 'ended'
  owner: { user_id: number; username: string; user_number: number | null }
  participant_count: number
  problem_count: number
  is_owner: boolean
  can_manage: boolean
  can_edit?: boolean
  is_participant: boolean
  can_view_problems?: boolean
  hide_submissions_from_admin?: boolean
  is_team_contest?: boolean
  // 是否计入比赛等级分（只有个人赛能开；结算见 rating 接口）
  is_rated?: boolean
  max_team_members?: number
  team_count?: number
  my_team?: ContestTeamInfo | null
  problems?: ContestProblemItem[]
}

export interface RankDetail {
  tries: number
  solved: boolean
  score: number
  minutes?: number
  penalty?: number
  first_solved?: boolean
}

export interface RankRow {
  rank: number
  user?: Record<string, any>
  team?: {
    id: number
    name: string
    leader_id: number
    members: ContestTeamMember[]
  }
  solved: number
  penalty: number
  total_score: number
  last_time?: string | null
  detail: Record<string, RankDetail>
}

export interface RankResponse {
  rule_type: string
  rule_type_label?: string
  is_team_contest?: boolean
  is_frozen?: boolean
  message?: string
  aliases: string[]
  rows: RankRow[]
}

export const contestsApi = {
  async list(page = 0): Promise<{ items: ContestItem[]; total: number }> {
    return apiClient.get('/api/contests', { params: { page, page_size: 50 } })
  },

  async get(id: number): Promise<ContestItem> {
    return apiClient.get(`/api/contests/${id}`)
  },

  async create(data: {
    title: string
    description?: string
    start_time: string
    end_time: string
    problem_codes: string[]
    team_id?: number
    visibility?: 'public' | 'private' | 'team' | 'team_private' | 'team_public'
    invite_code?: string
    rule_type?: 'xcpc' | 'acm' | 'ioi' | 'oi'
    hide_submissions_from_admin?: boolean
    is_team_contest?: boolean
    max_team_members?: number
  }): Promise<ContestItem> {
    return apiClient.post('/api/contests', data)
  },

  async update(id: number, data: {
    title?: string
    description?: string
    start_time?: string
    end_time?: string
    problem_codes?: string[]
    team_id?: number | null
    visibility?: 'public' | 'private' | 'team' | 'team_private' | 'team_public'
    invite_code?: string
    rule_type?: 'xcpc' | 'acm' | 'ioi' | 'oi'
    hide_submissions_from_admin?: boolean
    is_team_contest?: boolean
    max_team_members?: number
  }): Promise<ContestItem> {
    return apiClient.put(`/api/contests/${id}`, data)
  },

  async remove(id: number): Promise<{ success: boolean }> {
    return apiClient.delete(`/api/contests/${id}`)
  },

  async register(id: number, inviteCode?: string, teamInfo?: { team_name?: string; team_invite_code?: string }): Promise<{ success: boolean; team_id?: number; team_name?: string; invite_code?: string; message?: string }> {
    const payload: Record<string, any> = {}
    if (inviteCode) payload.invite_code = inviteCode
    if (teamInfo?.team_name) payload.team_name = teamInfo.team_name
    if (teamInfo?.team_invite_code) payload.team_invite_code = teamInfo.team_invite_code
    return apiClient.post(`/api/contests/${id}/register`, Object.keys(payload).length > 0 ? payload : undefined)
  },

  async rank(id: number): Promise<RankResponse> {
    return apiClient.get(`/api/contests/${id}/rank`)
  },

  // 虚拟参赛：镜像一场已结束的比赛，个人计时
  async getVirtualMe(id: number): Promise<VirtualContestState> {
    return apiClient.get(`/api/contests/${id}/virtual/me`)
  },

  async startVirtual(id: number): Promise<{ success: boolean; virtual: VirtualContestState['virtual'] }> {
    return apiClient.post(`/api/contests/${id}/virtual/start`)
  },

  async finishVirtual(id: number): Promise<{ success: boolean; virtual: VirtualContestState['virtual']; results: VirtualContestState['results'] }> {
    return apiClient.post(`/api/contests/${id}/virtual/finish`)
  },

  // 等级分：is_rated 的比赛才有；结算后 items 非空
  async getRating(id: number): Promise<{ is_rated: boolean; settled: boolean; items: ContestRatingItem[] }> {
    return apiClient.get(`/api/contests/${id}/rating`)
  },

  async settleRating(id: number): Promise<{ success: boolean; already_settled: boolean; settled: number; items: ContestRatingItem[] }> {
    return apiClient.post(`/api/contests/${id}/rating/settle`)
  },

  async getTeams(id: number): Promise<ContestTeamInfo[]> {
    return apiClient.get(`/api/contests/${id}/teams`)
  },

  async getMyTeam(id: number): Promise<ContestTeamInfo | null> {
    return apiClient.get(`/api/contests/${id}/my-team`)
  },

  async createTeam(id: number, data: { name: string; team_invite_code?: string; contest_invite_code?: string }): Promise<{ success: boolean; team_id: number; name: string; invite_code: string }> {
    return apiClient.post(`/api/contests/${id}/teams`, data)
  },

  async joinTeam(id: number, data: { invite_code?: string; team_id?: number; contest_invite_code?: string }): Promise<{ success: boolean; team_id: number; name: string }> {
    return apiClient.post(`/api/contests/${id}/teams/join`, data)
  },

  async addTeamMember(contestId: number, teamId: number, usernameOrUid: string): Promise<{ success: boolean; added_user: string }> {
    return apiClient.post(`/api/contests/${contestId}/teams/${teamId}/add_member`, { username_or_uid: usernameOrUid })
  },

  async kickTeamMember(contestId: number, teamId: number, userId: number): Promise<{ success: boolean }> {
    return apiClient.post(`/api/contests/${contestId}/teams/${teamId}/kick`, { user_id: userId })
  },

  async leaveTeam(contestId: number): Promise<{ success: boolean }> {
    return apiClient.post(`/api/contests/${contestId}/teams/leave`)
  },
}
