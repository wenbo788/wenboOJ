import apiClient from './client'

export interface TeamUserBrief {
  user_id: number | null
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

export interface TeamMemberItem {
  user_id: number
  role: 'owner' | 'admin' | 'member'
  note: string
  joined_at: string | null
  user: TeamUserBrief
}

export interface TeamItem {
  id: number
  name: string
  description: string
  owner: TeamUserBrief
  owner_id: number
  member_count: number
  is_banned: boolean
  created_at: string | null
  is_owner: boolean
  is_member: boolean
  is_team_admin: boolean
}

export interface TeamJoinedItem extends TeamItem {
  user_role: 'owner' | 'admin' | 'member'
  joined_at: string | null
}

export interface TeamJoinRequestItem {
  user_id: number
  created_at: string | null
  user: TeamUserBrief
}

export interface TeamProblemItem {
  id: number
  problem_number: string
  title: string
  difficulty: string
  submit_count: number
  solved_count: number
  is_public?: boolean
  team_id?: number | null
}

export interface TeamDetailItem extends TeamItem {
  members: TeamMemberItem[]
  is_pending: boolean
  pending_count: number
}

export interface TeamPostCommentItem {
  id: number
  post_id: number
  author: TeamUserBrief
  content: string
  created_at: string | null
  updated_at: string | null
}

export interface TeamPostItem {
  id: number
  team_id: number
  title: string
  content: string
  author: TeamUserBrief
  is_pinned: boolean
  is_locked: boolean
  reply_count: number
  created_at: string | null
  updated_at: string | null
}

export interface TeamPostDetailItem extends TeamPostItem {
  comments: TeamPostCommentItem[]
}

export const teamsApi = {
  async list(page = 0, pageSize = 20): Promise<{ items: TeamItem[]; total: number }> {
    return apiClient.get('/api/teams', { params: { page, page_size: pageSize } })
  },

  async get(id: number): Promise<TeamDetailItem> {
    return apiClient.get(`/api/teams/${id}`)
  },

  async create(data: { name: string; description?: string }): Promise<TeamItem> {
    return apiClient.post('/api/teams', data)
  },

  // 更新团队概览（名称 / 简介）：团主与团队管理员可编辑
  async update(
    id: number,
    data: { name?: string; description?: string }
  ): Promise<TeamItem> {
    return apiClient.put(`/api/teams/${id}`, data)
  },

  async join(id: number): Promise<{ pending: boolean }> {
    return apiClient.post(`/api/teams/${id}/join`)
  },

  async requests(id: number): Promise<{ items: TeamJoinRequestItem[] }> {
    return apiClient.get(`/api/teams/${id}/requests`)
  },

  // 我加入/创建的团队列表
  async myJoined(): Promise<{ items: TeamJoinedItem[]; total: number }> {
    return apiClient.get('/api/teams/my')
  },

  // 指定用户加入/创建的团队列表
  async userTeams(userId: number): Promise<{ items: TeamJoinedItem[]; total: number }> {
    return apiClient.get(`/api/teams/user/${userId}`)
  },

  // 我可管理的团队（团主/管理员，办赛下拉用）
  async myManageable(): Promise<{ items: { id: number; name: string; is_owner: boolean }[] }> {
    return apiClient.get('/api/teams/my/manageable')
  },

  // 团队私有题库（成员可见；题目为 T 编号系列）
  async problems(id: number): Promise<TeamProblemItem[]> {
    return apiClient.get(`/api/teams/${id}/problems`)
  },

  // 我所在团队的全部题目（T 编号倒序，带团队名）
  async myProblems(): Promise<{ items: (TeamProblemItem & { team_name: string })[] }> {
    return apiClient.get('/api/teams/my/problems')
  },

  async approveRequest(teamId: number, userId: number): Promise<{ success: boolean }> {
    return apiClient.post(`/api/teams/${teamId}/requests/${userId}/approve`)
  },

  async rejectRequest(teamId: number, userId: number): Promise<{ success: boolean }> {
    return apiClient.post(`/api/teams/${teamId}/requests/${userId}/reject`)
  },

  async leave(id: number): Promise<{ success: boolean }> {
    return apiClient.post(`/api/teams/${id}/leave`)
  },

  async dissolve(id: number): Promise<{ success: boolean }> {
    return apiClient.delete(`/api/teams/${id}`)
  },

  async transfer(teamId: number, userId: number): Promise<{ success: boolean }> {
    return apiClient.post(`/api/teams/${teamId}/transfer/${userId}`)
  },

  async updateMember(
    teamId: number,
    userId: number,
    data: { role?: 'member' | 'admin'; note?: string }
  ): Promise<TeamMemberItem> {
    return apiClient.put(`/api/teams/${teamId}/members/${userId}`, data)
  },

  async removeMember(teamId: number, userId: number): Promise<{ success: boolean }> {
    return apiClient.delete(`/api/teams/${teamId}/members/${userId}`)
  },

  async posts(teamId: number, page = 0, pageSize = 20): Promise<{ items: TeamPostItem[]; total: number }> {
    return apiClient.get(`/api/teams/${teamId}/posts`, { params: { page, page_size: pageSize } })
  },

  async getPost(teamId: number, postId: number): Promise<TeamPostDetailItem> {
    return apiClient.get(`/api/teams/${teamId}/posts/${postId}`)
  },

  async createPost(teamId: number, data: { title: string; content: string }): Promise<TeamPostItem> {
    return apiClient.post(`/api/teams/${teamId}/posts`, data)
  },

  async updatePost(teamId: number, postId: number, data: { title: string; content: string }): Promise<TeamPostItem> {
    return apiClient.put(`/api/teams/${teamId}/posts/${postId}`, data)
  },

  async deletePost(teamId: number, postId: number): Promise<{ success: boolean }> {
    return apiClient.delete(`/api/teams/${teamId}/posts/${postId}`)
  },

  async addPostComment(teamId: number, postId: number, data: { content: string }): Promise<TeamPostCommentItem> {
    return apiClient.post(`/api/teams/${teamId}/posts/${postId}/comments`, data)
  },

  async deletePostComment(teamId: number, postId: number, commentId: number): Promise<{ success: boolean }> {
    return apiClient.delete(`/api/teams/${teamId}/posts/${postId}/comments/${commentId}`)
  },

  async togglePostPin(teamId: number, postId: number): Promise<{ is_pinned: boolean }> {
    return apiClient.post(`/api/teams/${teamId}/posts/${postId}/pin`)
  },

  async togglePostLock(teamId: number, postId: number): Promise<{ is_locked: boolean }> {
    return apiClient.post(`/api/teams/${teamId}/posts/${postId}/lock`)
  },
}
