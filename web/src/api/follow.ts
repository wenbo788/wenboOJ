// 关注/粉丝 API 客户端

import apiClient from './client'

export interface FollowUser {
  id: number
  user_number: number
  username: string
  avatar_url: string
  user_tag: string
  is_admin: boolean
  is_following: boolean
  followed_at: string | null
}

export interface FollowStats {
  followers_count: number
  following_count: number
  is_following: boolean
}

export interface FollowListResponse {
  total: number
  page: number
  page_size: number
  followers?: FollowUser[]
  following?: FollowUser[]
}

export const followApi = {
  /** 关注用户 */
  async follow(userId: number): Promise<{ success: boolean; message: string }> {
    return apiClient.post(`/users/${userId}/follow`)
  },

  /** 取消关注 */
  async unfollow(userId: number): Promise<{ success: boolean; message: string }> {
    return apiClient.delete(`/users/${userId}/follow`)
  },

  /** 获取粉丝列表 */
  async getFollowers(
    userId: number,
    page = 0,
    pageSize = 20,
  ): Promise<FollowListResponse> {
    return apiClient.get(`/users/${userId}/followers?page=${page}&page_size=${pageSize}`)
  },

  /** 获取关注列表 */
  async getFollowing(
    userId: number,
    page = 0,
    pageSize = 20,
  ): Promise<FollowListResponse> {
    return apiClient.get(`/users/${userId}/following?page=${page}&page_size=${pageSize}`)
  },

  /** 获取关注统计 */
  async getStats(userId: number): Promise<FollowStats> {
    return apiClient.get(`/users/${userId}/follow-stats`)
  },
}
