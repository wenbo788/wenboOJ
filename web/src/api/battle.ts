import apiClient from './client'

// 用户名身份色（userNameColor）与主页跳转所需字段
export interface UserIdentityFields {
  user_number?: number
  is_banned?: boolean
  is_cheater?: boolean
  is_admin?: boolean
  is_super_admin?: boolean
  can_manage_users?: boolean
  can_manage_posts?: boolean
  can_manage_problems?: boolean
  can_manage_tags?: boolean
}

export interface BattleProfile extends UserIdentityFields {
  user_id: number
  username: string
  avatar_url: string | null
  user_tag?: string | null
  color_tier?: string
  experience: number
  tier: 'bronze' | 'silver' | 'gold' | 'platinum' | 'diamond'
  tier_name: string
  sub_tier: number
  sub_tier_roman: string
  points: number
  rank_name: string
  rank_score: number
  total_matches: number
  wins: number
  losses: number
  draws: number
  win_rate: number
  win_streak: number
  max_win_streak: number
  rank?: number
}

export interface BattleHistoryItem {
  id: number
  mode: 'casual' | 'ranked'
  status: 'ongoing' | 'finished' | 'cancelled'
  result: 'win' | 'loss' | 'draw' | 'ongoing'
  problem: {
    id: number
    title: string
    difficulty: string
    code: string
  }
  opponent: UserIdentityFields & {
    id: number
    username: string
    avatar_url: string | null
  }
  started_at: string
  finished_at: string | null
  settlement?: any
}

export interface BattlePlayer extends UserIdentityFields {
  id: number
  username: string
  avatar_url: string | null
  tier: string
  sub_tier: number
  tier_name: string
  sub_tier_roman: string
  status: 'coding' | 'submitted' | 'accepted' | 'surrendered'
  is_me: boolean
  screen_switch_count?: number
}

export interface BattleRoomDetail {
  id: number
  mode: 'casual' | 'ranked'
  status: 'ongoing' | 'finished' | 'cancelled'
  started_at: string
  finished_at: string | null
  duration_seconds: number
  remaining_seconds: number
  winner_id: number | null
  settlement?: any
  user1: BattlePlayer
  user2: BattlePlayer
  problem: {
    id: number
    code: string
    title: string
    difficulty: string
    time_limit: number
    memory_limit: number
    background: string
    description: string
    input_format: string
    output_format: string
    hint: string
    samples: Array<{ input: string; output: string }>
  }
  my_submission?: {
    id: number
    status: string
    time_used?: number | null
    memory_used?: number | null
    error_message?: string | null
  } | null
  my_screen_switch_count?: number
}

export const battleApi = {
  async getProfile(): Promise<BattleProfile> {
    return await apiClient.get('/api/battle/profile') as any
  },

  async getLeaderboard(limit = 50): Promise<{ items: BattleProfile[]; total: number }> {
    return await apiClient.get('/api/battle/leaderboard', { params: { limit } }) as any
  },

  async getBattleRanking(page = 1, pageSize = 10): Promise<{
    items: any[]
    page: number
    page_size: number
    total: number
    total_pages: number
    my_rank: any
  }> {
    return await apiClient.get('/api/ranking/battle', { params: { page, page_size: pageSize } }) as any
  },

  async getHistory(limit = 20): Promise<{ items: BattleHistoryItem[] }> {
    return await apiClient.get('/api/battle/history', { params: { limit } }) as any
  },

  async getCurrentBattle(): Promise<{
    has_ongoing: boolean
    battle_id?: number
    mode?: 'casual' | 'ranked'
    remaining_seconds?: number
    problem?: { id: number; title: string; difficulty: string; code: string }
    opponent?: { id: number; username: string; avatar_url: string | null }
  }> {
    return await apiClient.get('/api/battle/current') as any
  },

  async startMatch(
    mode: 'casual' | 'ranked',
    simulate = false,
    forfeitOngoing = false
  ): Promise<{ status: 'queued' | 'matched'; battle_id?: number }> {
    return await apiClient.post('/api/battle/match', {
      mode,
      simulate,
      forfeit_ongoing: forfeitOngoing,
    }) as any
  },

  async cancelMatch(): Promise<{ ok: boolean }> {
    return await apiClient.delete('/api/battle/match') as any
  },

  async getMatchStatus(): Promise<{ status: 'idle' | 'queued' | 'matched'; battle_id?: number; wait_time?: number }> {
    return await apiClient.get('/api/battle/match/status') as any
  },

  async getRoom(battleId: number): Promise<BattleRoomDetail> {
    return await apiClient.get(`/api/battle/rooms/${battleId}`) as any
  },

  async submitCode(battleId: number, code: string, language: string): Promise<{ submission_id: number; status: string }> {
    return await apiClient.post(`/api/battle/rooms/${battleId}/submit`, { code, language }) as any
  },

  async reportScreenSwitch(
    battleId: number,
    action: 'leave' | 'return'
  ): Promise<{ ok: boolean; leave_count?: number }> {
    return await apiClient.post(`/api/battle/rooms/${battleId}/screen-switch`, { action }) as any
  },

  async surrender(
    battleId: number,
    reason: 'surrender' | 'screen_switch_timeout' | 'screen_switch_second' = 'surrender'
  ): Promise<{ ok: boolean; winner_id: number; finish_reason?: string }> {
    return await apiClient.post(`/api/battle/rooms/${battleId}/surrender`, { reason }) as any
  },

  async tryRun(
    battleId: number,
    payload: { code: string; language: string; input?: string }
  ): Promise<BattleTryRunResult> {
    return await apiClient.post(`/api/battle/rooms/${battleId}/try-run`, payload) as any
  },
}

export interface BattleTryRunResult {
  status: 'ok' | 'compile_error' | 'runtime_error' | 'time_limit_exceeded' | 'memory_limit_exceeded' | 'output_limit_exceeded' | 'system_error'
  stdout?: string
  stderr?: string
  time_ms?: number | null
  memory_kb?: number | null
  detail?: string
}

