// 权限判定（与后端 service/app/permissions.py 保持一致）
// B 方案：白名单 > 超管 > 大管 > 题管/社管 > 用户

export const SUPER_ADMIN_UIDS = [1, 68, 210]
export const PROTECTED_UIDS = [0, 1, 3, 4, 68, 165, 210]


export function isWhiteList(user: any): boolean {
  return !!user && SUPER_ADMIN_UIDS.includes(user.user_number)
}

export function isProtected(user: any): boolean {
  return !!user && PROTECTED_UIDS.includes(user.user_number)
}

export function isSuperAdmin(user: any): boolean {
  if (!user) return false
  if (isWhiteList(user)) return false
  return user.is_super_admin === true
}

export function isBigAdmin(user: any): boolean {
  if (!user) return false
  if (isSuperAdmin(user) || isWhiteList(user)) return false
  return user.is_big_admin === true
}

export function isProblemAdmin(user: any): boolean {
  if (!user) return false
  if (isWhiteList(user) || isSuperAdmin(user) || isBigAdmin(user)) return false
  return user.can_manage_problems === true
}

export function isCommunityAdmin(user: any): boolean {
  if (!user) return false
  if (isWhiteList(user) || isSuperAdmin(user) || isBigAdmin(user)) return false
  return user.can_manage_posts === true
}

export function isAnyAdmin(user: any): boolean {
  if (!user) return false
  return (
    isWhiteList(user) ||
    isSuperAdmin(user) ||
    isBigAdmin(user) ||
    isProblemAdmin(user) ||
    isCommunityAdmin(user) ||
    user.is_admin === true ||
    user.can_manage_users === true ||
    // 与后端 is_any_admin 对齐：只在「管理名单 → Tag 管理」列里的人也算管理员
    user.can_manage_tags === true
  )
}

export function isTopAdmin(user: any): boolean {
  return isWhiteList(user) || isSuperAdmin(user)
}

export const ROLE_RANK: Record<string, number> = {
  white_list: 5,
  super_admin: 4,
  big_admin: 3,
  problem_admin: 2,
  community_admin: 2,
}

export function roleRank(user: any): number {
  if (!user) return 0
  if (isWhiteList(user)) return ROLE_RANK.white_list
  if (isSuperAdmin(user)) return ROLE_RANK.super_admin
  if (isBigAdmin(user)) return ROLE_RANK.big_admin
  if (isProblemAdmin(user)) return ROLE_RANK.problem_admin
  if (isCommunityAdmin(user)) return ROLE_RANK.community_admin
  return 0
}


export function canModifyUser(operator: any, target: any): boolean {
  if (!operator || !target) return false
  if (isProtected(target)) return false
  if (operator.user_number === target.user_number) return false
  if (isWhiteList(target)) return false
  if (isWhiteList(operator)) return true
  if (isSuperAdmin(operator)) return !isSuperAdmin(target)
  if (isBigAdmin(operator)) return !isAnyAdmin(target)
  // 「管理名单 → 用户管理」那一列的口径就是 canManageUsers（白名单/超管/大管，
  // 或持有 can_manage_users 字段的人）。后端 permissions.can_modify_user 与
  // 单用户改权限、批量、改头像三个入口都用这个口径，前端必须一致 ——
  // 否则接口放行了，编辑按钮却不出现（还是「名单上有、活干不了」）。
  // 目标范围：受保护账号、白名单、自己上面已挡掉，剩下只有「UID 2 以外的超管」
  // 不可动（UID 2 是历史遗留例外）。
  if (canManageUsers(operator)) {
    return !(isSuperAdmin(target) && target.user_number !== 2)
  }
  return false
}

export function canResetPassword(operator: any): boolean {
  return isWhiteList(operator)
}

export function canBanUser(operator: any): boolean {
  return isWhiteList(operator) || isSuperAdmin(operator) || isBigAdmin(operator)
}
export const canBanDirectly = canBanUser

export function canRequestBan(operator: any): boolean {
  return isProblemAdmin(operator) || isCommunityAdmin(operator)
}

export function canMuteUser(operator: any): boolean {
  return (
    isWhiteList(operator) ||
    isSuperAdmin(operator) ||
    isBigAdmin(operator) ||
    isCommunityAdmin(operator)
  )
}
export const canMute = canMuteUser

export function canMarkCheater(operator: any): boolean {
  return (
    isWhiteList(operator) ||
    isSuperAdmin(operator) ||
    isBigAdmin(operator) ||
    isProblemAdmin(operator)
  )
}

export function canManageTags(operator: any): boolean {
  // 与后端 permissions.can_manage_tags 一致：高层级天然可以，
  // 被单独授予 can_manage_tags 的人也可以（这也是「管理名单」Tag 列的公示依据）
  return (
    isWhiteList(operator) ||
    isSuperAdmin(operator) ||
    isBigAdmin(operator) ||
    operator?.can_manage_tags === true
  )
}

export function canManageProblems(operator: any): boolean {
  return (
    isWhiteList(operator) ||
    isSuperAdmin(operator) ||
    isBigAdmin(operator) ||
    isProblemAdmin(operator)
  )
}

export function canManageCommunity(operator: any): boolean {
  return (
    isWhiteList(operator) ||
    isSuperAdmin(operator) ||
    isBigAdmin(operator) ||
    isCommunityAdmin(operator)
  )
}

export function canReviewArticles(operator: any): boolean {
  return (
    isWhiteList(operator) ||
    isSuperAdmin(operator) ||
    isBigAdmin(operator) ||
    isProblemAdmin(operator) ||
    isCommunityAdmin(operator)
  )
}

export function canManageTeams(operator: any): boolean {
  return (
    isWhiteList(operator) ||
    isSuperAdmin(operator) ||
    isBigAdmin(operator) ||
    isCommunityAdmin(operator) ||
    operator?.can_manage_users === true
  )
}

export function canManageUsers(operator: any): boolean {
  // 与后端 permissions.can_manage_users 一致：高层级天然可以，
  // 持有该字段的人也可以（字段就是「管理名单」用户管理列的公示依据）
  return (
    isWhiteList(operator) ||
    isSuperAdmin(operator) ||
    isBigAdmin(operator) ||
    operator?.can_manage_users === true
  )
}

export function canGrantRole(operator: any, targetRole: string): boolean {
  if (isWhiteList(operator)) return true
  if (isSuperAdmin(operator)) {
    return ['problem_admin', 'community_admin', 'big_admin', 'admin'].includes(targetRole)
  }
  return false
}

export function canRevokeRole(operator: any, target: any): boolean {
  if (!operator || !target) return false
  if (isProtected(target)) return false
  if (operator.user_number === target.user_number) return false
  if (isWhiteList(target)) return false
  if (isWhiteList(operator)) return true
  if (isSuperAdmin(operator)) return !isSuperAdmin(target)
  return false
}

export function canEditRole(operator: any, target: any): boolean {
  if (!operator || !target) return false
  if (isProtected(target)) return false
  if (operator.user_number === target.user_number) return false
  if (isWhiteList(target)) return false
  if (isWhiteList(operator)) return true
  if (isSuperAdmin(operator)) return !isSuperAdmin(target)
  return false
}

export function canViewPII(operator: any): boolean {
  return isWhiteList(operator)
}

export function canViewLastSeen(operator: any): boolean {
  return isWhiteList(operator)
}

export function maskEmail(email: string | null | undefined, whitelist: boolean): string {
  if (!email) return '-'
  if (whitelist) return email
  const at = email.indexOf('@')
  if (at <= 0) return '***'
  return email.slice(0, 2) + '***' + email.slice(at)
}

export function maskPhone(phone: string | null | undefined, whitelist: boolean): string {
  if (!phone) return '-'
  if (whitelist) return phone
  if (phone.length < 7) return '***'
  return phone.slice(0, 3) + '****' + phone.slice(-4)
}
