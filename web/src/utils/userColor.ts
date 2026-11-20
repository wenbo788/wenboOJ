// 用户名配色（全站统一）。身份颜色优先于自定义/购买颜色：
// 优先级与后端 service/app/permissions.py 的 user_name_color **严格一致**：
//   白名单/超管/大管（同紫）→ 题管（青）→ 社管（深蓝）→ 作弊者 → 封禁
//   → 自定义色 → 购买档位
//
// 优先用后端算好的 name_color：公开资料等接口刻意不下发 can_manage_* 管理标志
// （隐私），这里只靠 payload 推不出题管/社管色，个人主页的名字颜色就会和
// 犇犇/私信/管理名单对不上。本地这份链只作为「payload 没带 name_color」时的兜底。
//
// - UID 白名单 / 超管（is_super_admin）/ 大管（is_big_admin）→ 紫 #9C3DCF
//   （这三档在界面上是同一层，统一紫色；金色是后来加的，已回退）
// - 题管（can_manage_problems）→ 青 #13C2C2
// - 社管（can_manage_posts）→ 深蓝 #0D47A1
// - 作弊者 → 棕 #AD8B00
// - 封禁 → 黑 #000000
// - 其他用户 → 按购买档位 color_tier：灰 / 蓝 / 绿 / 橙 / 红

import { SUPER_ADMIN_UIDS } from '@/utils/permissions'
export const COLOR_WHITE_LIST = '#9C3DCF'
export const COLOR_SUPER_ADMIN = '#9C3DCF'
export const COLOR_BIG_ADMIN = '#9C3DCF'
export const COLOR_PROBLEM_ADMIN = '#13C2C2'
export const COLOR_COMMUNITY_ADMIN = '#0D47A1'
export const COLOR_CHEATER = '#AD8B00'
export const COLOR_BANNED = '#000000'

export const COLOR_TIER_MAP: Record<string, string> = {
  gray: '#95a5a6',
  blue: '#1890ff',
  green: '#52c41a',
  orange: '#fa8c16',
  red: '#e74c3c',
}
export const COLOR_DEFAULT = COLOR_TIER_MAP.gray

const colorCache = new Map<string, string>()

export function userNameColor(user: any): string {
  if (!user) return COLOR_DEFAULT
  // 后端算好的权威身份色优先（个人主页、私信等接口都会带上）
  if (typeof user.name_color === 'string' && user.name_color) return user.name_color
  const cacheKey = String(user.id || user.user_number || '')

  const hasColorInfo = user.name_color || user.color_tier || user.username_color
    || user.is_banned || user.is_cheater
    || user.is_super_admin || user.is_big_admin
    || user.can_manage_problems || user.can_manage_posts

  if (cacheKey && !hasColorInfo && colorCache.has(cacheKey)) {
    return colorCache.get(cacheKey)!
  }

  // 优先级与后端 user_color 严格对齐：身份 > 作弊/封禁 > 购买档位
  let color: string
  if (SUPER_ADMIN_UIDS.includes(user.user_number)) {
    color = COLOR_WHITE_LIST
  } else if (user.is_super_admin) {
    color = COLOR_SUPER_ADMIN
  } else if (user.is_big_admin) {
    color = COLOR_BIG_ADMIN
  } else if (user.can_manage_problems) {
    color = COLOR_PROBLEM_ADMIN
  } else if (user.can_manage_posts) {
    color = COLOR_COMMUNITY_ADMIN
  } else if (user.is_cheater) {
    color = COLOR_CHEATER
  } else if (user.is_banned) {
    color = COLOR_BANNED
  } else {
    // 管理后台设置的自定义色优先于购买的档位色（与后端 user_name_color 同序）
    const custom = typeof user.username_color === 'string' ? user.username_color.trim() : ''
    color = custom || COLOR_TIER_MAP[user.color_tier] || COLOR_DEFAULT
  }

  if (cacheKey) colorCache.set(cacheKey, color)
  return color
}