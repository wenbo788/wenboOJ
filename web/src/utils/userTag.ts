import { SUPER_ADMIN_UIDS } from '@/utils/permissions'

/**
 * 全站统一获取用户称号/Tag文本（与后端 User.display_tag 逻辑严格对齐）
 *
 * 优先级：
 * 1. 作弊者（非管理员）：强制显示「作弊者」，不被 Tag 卡掩盖
 * 2. 佩戴中的 Tag 卡（优先取 tag_cards 中 enabled: true 的项）
 * 3. 自定义头衔（user_tag）
 * 4. 各接口预先计算好的 display_tag（若非空且与高级角色无冲突）
 * 5. 角色默认称号（UID 白名单 / 超级管理员 / 大管 / 题管 / 社管 / 管理员）
 * 6. 默认返回空字符串
 */
export function getUserTagDisplay(user: any): string {
  if (!user) return ''

  const isAnyAdmin = Boolean(
    SUPER_ADMIN_UIDS.includes(user.user_number) ||
    user.is_super_admin ||
    user.is_big_admin ||
    user.can_manage_problems ||
    user.can_manage_posts ||
    user.is_admin
  )

  // 1. 作弊者优先判定（非管理员强制显示作弊者）
  if (user.is_cheater && !isAnyAdmin) {
    return '作弊者'
  }

  // 2. 检查佩戴中的 Tag 卡（优先查 tag_cards 中 enabled: true 的项）
  if (Array.isArray(user.tag_cards)) {
    const enabledCard = user.tag_cards.find((c: any) => c && c.enabled)
    if (enabledCard?.name) {
      return enabledCard.name
    }
  }

  // 3. 用户在后台设置的自定义 user_tag（若显式设置，优先于默认角色头衔）
  if (user.user_tag && typeof user.user_tag === 'string' && user.user_tag.trim()) {
    return user.user_tag.trim()
  }

  // 4. 检查已序列化的 display_tag（各业务接口返回的佩戴称号）
  if (user.display_tag && typeof user.display_tag === 'string' && user.display_tag.trim()) {
    const dt = user.display_tag.trim()
    // 若后端曾降级默认回退成普通「管理员」，但当前用户其实是更高级角色（超管/大管/题管/社管/白名单/用户管理/Tag 管理），重新按真源解析
    const isHigherRole = (
      SUPER_ADMIN_UIDS.includes(user.user_number) ||
      user.is_super_admin ||
      user.is_big_admin ||
      user.can_manage_problems ||
      user.can_manage_posts ||
      user.can_manage_users ||
      user.can_manage_tags
    )
    if (dt !== '管理员' || !isHigherRole) {
      return dt
    }
  }

  // 5. 角色身份兜底（当未佩戴 Tag 卡且无自定义头衔时）
  if (SUPER_ADMIN_UIDS.includes(user.user_number)) {
    return 'UID 白名单'
  }
  if (user.is_super_admin) {
    return '超级管理员'
  }
  if (user.is_big_admin) {
    return '大管'
  }
  if (user.can_manage_problems) {
    return '题管'
  }
  if (user.can_manage_posts) {
    return '社管'
  }
  // 这两项同样在「管理名单」里公示，称号链不能漏，否则名单上「有位置、没称号」
  if (user.can_manage_users) {
    return '用户管理'
  }
  if (user.can_manage_tags) {
    return 'Tag 管理'
  }
  if (user.is_admin) {
    return '管理员'
  }

  return ''
}

/**
 * 获取用户的角色/身份类型文本（用于主页等位置展示「用户类型」）
 */
export function getUserRoleText(user: any): string {
  if (!user) return ''
  if (SUPER_ADMIN_UIDS.includes(user.user_number)) {
    return 'UID 白名单'
  }
  if (user.is_super_admin) {
    return '超级管理员'
  }
  if (user.is_big_admin) {
    return '大管'
  }
  if (user.can_manage_problems) {
    return '题管'
  }
  if (user.can_manage_posts) {
    return '社管'
  }
  if (user.can_manage_users) {
    return '用户管理'
  }
  if (user.can_manage_tags) {
    return 'Tag 管理'
  }
  if (user.is_admin) {
    return '管理员'
  }
  if (user.is_cheater) {
    return '作弊者'
  }
  return '普通用户'
}
