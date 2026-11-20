<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, nextTick, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import apiClient from '@/api/client'
import Swal from 'sweetalert2'
import { userNameColor } from '@/utils/userColor'
import { isUserOnline } from '@/utils/presence'
import {
  isWhiteList,
  isSuperAdmin,
  isBigAdmin,
  isProblemAdmin,
  isCommunityAdmin,
  isTopAdmin,
  isAnyAdmin,
  isProtected,
  canModifyUser as canModifyUserFn,
  canResetPassword,
  canManageTags,
  canManageUsers,
} from '@/utils/permissions'

const authStore = useAuthStore()

// ===== 常量定义 =====
const COLOR_RED = 'var(--primary)'
const COLOR_PURPLE = '#9C3DCF'
const COLOR_BROWN = '#AD8B00'

// ===== 状态管理 =====
const users = ref<any[]>([])
const loading = ref(false)
const searchQuery = ref('')
const currentUser = ref<any>(null)
const currentProfile = ref<any>(null)
const pendingChanges = ref<Record<number, any>>({})

// ===== 筛选状态 =====
interface FilterStates {
  super_admin: 'off' | 'has' | 'no'
  big_admin: 'off' | 'has' | 'no'
  problem_mgmt: 'off' | 'has' | 'no'
  post_mgmt: 'off' | 'has' | 'no'
  enter_site: 'off' | 'has' | 'no'
  cheater: 'off' | 'has' | 'no'
  speak: 'off' | 'has' | 'no'
  status: 'off' | 'online' | 'offline'
}

const filterStates = ref<FilterStates>({
  super_admin: 'off',
  big_admin: 'off',
  problem_mgmt: 'off',
  post_mgmt: 'off',
  enter_site: 'off',
  cheater: 'off',
  speak: 'off',
  status: 'off'
})

// ===== 计算属性 =====
// 能否进入管理后台：任意管理角色（白名单/超管/大管/题管/社管）
const canAccessAdmin = computed(() => isAnyAdmin(authStore.currentUser))

// 当前操作者是否白名单（用于表格显示「操作」列、超管权限 toggle）
const isCurrentWhiteList = computed(() => isWhiteList(currentProfile.value))

// 当前操作者是否超管（含白名单）
const isCurrentSuper = computed(() => isSuperAdmin(currentProfile.value))

const filteredUsers = computed(() => {
  const keyword = searchQuery.value.trim().toLowerCase()
  return users.value.filter(user => {
    let match = true
    if (keyword) {
      const username = (user.username || '').toLowerCase()
      const remark = (user.remark || '').toLowerCase()
      const tag = (user.user_tag || '').toLowerCase()
      // 复用表格里那一列的口径，免得搜索和显示对不上
      const matchedRoleLabel = roleLabel(user)
      // 用户编号用前缀匹配：数字若也走「包含」，搜个 1 会把 1/10/210… 全捞上来
      const userNumber = String(user.user_number)

      // 文本字段一律「包含」匹配 —— 管理后台搜人基本都是凭半截名字，
      // 以前这里写的是 === 全字段精确匹配，等于搜索框只能输入完整用户名才有效。
      match =
        username.includes(keyword) ||
        remark.includes(keyword) ||
        tag.includes(keyword) ||
        matchedRoleLabel.includes(keyword) ||
        userNumber.startsWith(keyword)
    }

    if (match) {
      for (const key in filterStates.value) {
        const state = filterStates.value[key as keyof FilterStates]
        if (state === 'off') continue

        let hasPermission = false
        if (key === 'status') {
          if (state === 'online') hasPermission = isUserOnline(user)
          else if (state === 'offline') hasPermission = !isUserOnline(user)
        } else {
          switch (key) {
            case 'super_admin':
              hasPermission = isSuperAdmin(user)
              break
            case 'big_admin':
              hasPermission = isBigAdmin(user)
              break
            case 'problem_mgmt':
              hasPermission = !!user.can_manage_problems
              break
            case 'post_mgmt':
              hasPermission = !!user.can_manage_posts
              break
            case 'enter_site':
              hasPermission = !user.is_banned
              break
            case 'cheater':
              hasPermission = !!user.is_cheater
              break
            case 'speak':
              hasPermission = user.can_speak !== false
              break
          }

          if (state === 'has' && !hasPermission) { match = false; break }
          if (state === 'no' && hasPermission) { match = false; break }
        }

        if (key === 'status') {
          if (state === 'online' && !hasPermission) { match = false; break }
          if (state === 'offline' && !hasPermission) { match = false; break }
        }
      }
    }

    return match
  })
})

// ===== 分页 =====
const currentPage = ref(1)
const pageSize = 20

const totalPages = computed(() => Math.max(1, Math.ceil(filteredUsers.value.length / pageSize)))

const pagedUsers = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return filteredUsers.value.slice(start, start + pageSize)
})

const pageNumbers = computed<(number | '...')[]>(() => {
  const total = totalPages.value
  const cur = currentPage.value
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
  const pages: (number | '...')[] = [1]
  if (cur > 3) pages.push('...')
  for (let p = Math.max(2, cur - 1); p <= Math.min(total - 1, cur + 1); p++) pages.push(p)
  if (cur < total - 2) pages.push('...')
  pages.push(total)
  return pages
})

function goToPage(p: number) {
  if (p < 1 || p > totalPages.value || p === currentPage.value) return
  currentPage.value = p
}

watch(searchQuery, () => { currentPage.value = 1 })
watch(filterStates, () => { currentPage.value = 1 }, { deep: true })
watch(totalPages, (t) => { if (currentPage.value > t) currentPage.value = t })

// ===== 工具函数 =====
function formatTime(iso: string): string {
  if (!iso) return '未知'
  try {
    return new Date(iso).toLocaleString('zh-CN')
  } catch {
    return iso
  }
}

function letterAvatar(name: string): string {
  const ch = (name || 'U').trim().charAt(0).toUpperCase() || 'U'
  return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Crect width='40' height='40' fill='%23e74c3c'/%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' dy='.3em' fill='white' font-size='16' font-family='Arial'%3E${encodeURIComponent(ch)}%3C/text%3E%3C/svg%3E`
}

function getUserDisplayColor(user: any): string {
  return userNameColor(user)
}

// 在线判定统一走 @/utils/presence 的 isUserOnline（60 秒阈值 + 时区归一化），
// 这里原先自己实现了一份，两边容易改跑偏。

// 能否修改目标用户的资料：只有白名单可以（包装工具函数）
function canModifyUser(targetUser: any): boolean {
  return canModifyUserFn(currentProfile.value, targetUser)
}

// 能否修改目标用户的权限：白名单 / 超管
function canModifyPermissions(targetUser: any): boolean {
  if (!currentProfile.value) return false
  if (isProtected(targetUser)) return false
  if (targetUser.user_number === currentProfile.value.user_number) return false
  // 超管/白名单不能互相修改（与后端对齐）
  if (isTopAdmin(targetUser) && !isWhiteList(currentProfile.value)) return false
  return isWhiteList(currentProfile.value) || isSuperAdmin(currentProfile.value)
}

// 超级管理是固定身份：任何人都不可修改。
// 「用户管理 / Tag 管理」在后端对应 can_grant_role 的 admin 角色：
// 白名单全权，超管也能授予/撤销（与前端 canGrantRole 同一套规则），
// 大管及以下只能看状态、不能点。
function canToggleField(field: string): boolean {
  if (field === 'is_super_admin') return false
  if (field === 'can_manage_users' || field === 'can_manage_tags') {
    return isCurrentWhiteList.value || isCurrentSuper.value
  }
  return true
}

// 用户类型显示
function roleLabel(user: any): string {
  if (isWhiteList(user)) return '白名单'
  if (isSuperAdmin(user)) return '超管'
  if (isBigAdmin(user)) return '大管'
  if (isProblemAdmin(user)) return '题管'
  if (isCommunityAdmin(user)) return '社管'
  // 这两项也在「管理名单」里公示，后台的「权限」列必须跟着显示，
  // 否则会出现「名单公示了他，后台却写着普通用户」
  if (canManageUsers(user)) return '用户管理'
  if (canManageTags(user)) return 'Tag 管理'
  return '普通用户'
}

// ===== OI/XCPC等级徽章 =====
function getCcfBadgeHtml(ccfLevel: number, user: any): string {
  if (user && user.show_ccf_badge === false) return ''
  if (!ccfLevel) return ''
  if (ccfLevel >= 11) {
    return `<svg class="svg-inline--fa fa-badge-check rainbow-badge" style="width: 16px; height: 16px; vertical-align: middle;">
      <path fill="currentColor" d="M0 256C0 292.8 20.7 324.8 51.1 340.9 41 373.8 49 411 75 437s63.3 34 96.1 23.9C187.2 491.3 219.2 512 256 512s68.8-20.7 84.9-51.1C373.8 471 411 463 437 437s34-63.3 23.9-96.1C491.3 324.8 512 292.8 512 256s-20.7-68.8-51.1-84.9C471 138.2 463 101 437 75s-63.3-34-96.1-23.9C324.8 20.7 292.8 0 256 0s-68.8 20.7-84.9 51.1C138.2 41 101 49 75 75s-34 63.3-23.9 96.1C20.7 187.2 0 219.2 0 256z"/>
    </svg>`
  }
  if (!ccfLevel || ccfLevel < 1 || ccfLevel > 10) return ''

  let color = ''
  if (ccfLevel >= 1 && ccfLevel <= 5) color = '#52C41A'
  else if (ccfLevel >= 6 && ccfLevel <= 7) color = '#3498DB'
  else if (ccfLevel >= 8 && ccfLevel <= 10) color = '#FFC116'

  return `<svg class="svg-inline--fa fa-badge-check" style="width: 16px; height: 16px; vertical-align: middle;">
    <path class="fa-secondary" fill="${color}" d="M0 256C0 292.8 20.7 324.8 51.1 340.9 41 373.8 49 411 75 437s63.3 34 96.1 23.9C187.2 491.3 219.2 512 256 512s68.8-20.7 84.9-51.1C373.8 471 411 463 437 437s34-63.3 23.9-96.1C491.3 324.8 512 292.8 512 256s-20.7-68.8-51.1-84.9C471 138.2 463 101 437 75s-63.3-34-96.1-23.9C324.8 20.7 292.8 0 256 0s-68.8 20.7-84.9 51.1C138.2 41 101 49 75 75s-34 63.3-23.9 96.1C20.7 187.2 0 219.2 0 256z"/>
    <path class="fa-primary" fill="#ffffff" d="M328.7 155.5c7.8-10.7 22.8-13.1 33.5-5.3 10.7 7.8 13.1 22.8 5.3 33.5L244.7 352.7c-4.2 5.7-10.7 9.4-17.8 9.8-7.1 .5-14-2.2-18.9-7.3l-55.7-57.6c-9.2-9.5-9-24.7 .6-33.9 9.5-9.2 24.7-8.9 33.9 .6l35.8 37 106.1-145.8z"/>
  </svg>`
}

function getXcpcBalloonHtml(level: number, user: any): string {
  if (user && user.show_xcpc_badge === false) return ''
  if (!level) return ''
  let color = ''
  if (level >= 1 && level <= 5) {
    color = '#52C41A'
  } else if (level >= 6 && level <= 7) {
    color = '#3498DB'
  } else if (level >= 8 && level <= 10) {
    color = '#FFC116'
  }
  if (level >= 11) {
    return `<svg class="svg-inline--fa fa-balloon rainbow-badge" style="width: 16px; height: 16px; vertical-align: middle; margin-left: 2px;">
      <path class="fa-primary" fill="currentColor" d="M56 176c0 13.3 10.7 24 24 24s24-10.7 24-24c0-39.8 32.2-72 72-72 13.3 0 24-10.7 24-24s-10.7-24-24-24C109.7 56 56 109.7 56 176z"></path>
      <path class="fa-secondary" fill="currentColor" d="M0 192C0 86 86 0 192 0S384 86 384 192c0 128-160 240-160 240l27.9 41.8c2.7 4 4.1 8.8 4.1 13.6 0 13.6-11 24.6-24.6 24.6l-78.9 0c-13.6 0-24.6-11-24.6-24.6 0-4.8 1.4-9.6 4.1-13.6L160 432S0 320 0 192z"></path>
    </svg>`
  }
  return `<svg class="svg-inline--fa fa-balloon" style="width: 16px; height: 16px; vertical-align: middle; margin-left: 2px;">
    <path class="fa-secondary" fill="#ffffff" d="M56 176c0 13.3 10.7 24 24 24s24-10.7 24-24c0-39.8 32.2-72 72-72 13.3 0 24-10.7 24-24s-10.7-24-24-24C109.7 56 56 109.7 56 176z"></path>
    <path class="fa-primary" fill="${color}" d="M0 192C0 86 86 0 192 0S384 86 384 192c0 128-160 240-160 240l27.9 41.8c2.7 4 4.1 8.8 4.1 13.6 0 13.6-11 24.6-24.6 24.6l-78.9 0c-13.6 0-24.6-11-24.6-24.6 0-4.8 1.4-9.6 4.1-13.6L160 432S0 320 0 192z"></path>
  </svg>`
}

// ===== 筛选功能 =====
function toggleFilterTag(key: keyof FilterStates) {
  if (key === 'status') {
    const current = filterStates.value[key] || 'off'
    if (current === 'off') filterStates.value[key] = 'online'
    else if (current === 'online') filterStates.value[key] = 'offline'
    else if (current === 'offline') filterStates.value[key] = 'off'
  } else {
    const current = filterStates.value[key] || 'off'
    if (current === 'off') filterStates.value[key] = 'has'
    else if (current === 'has') filterStates.value[key] = 'no'
    else if (current === 'no') filterStates.value[key] = 'off'
  }
}

function getFilterLabel(key: keyof FilterStates): string {
  const labels: Record<string, string> = {
    super_admin: '超管',
    big_admin: '大管',
    problem_mgmt: '题管',
    post_mgmt: '社管',
    enter_site: '进入主站',
    cheater: '学术不端',
    speak: '自由发言',
    status: '状态'
  }
  return labels[key] || key
}

function getFilterTagClass(key: keyof FilterStates): string {
  const state = filterStates.value[key] || 'off'
  let classes = 'filter-tag'
  if (state === 'has') classes += ' active-green'
  else if (state === 'no') classes += ' active-red'
  else if (key === 'status') {
    if (state === 'online') classes += ' active-online'
    else if (state === 'offline') classes += ' active-offline'
  }
  return classes
}

/** 自由发言徽章的悬停说明：禁言时长/到期时间 */
function muteTitle(user: any): string {
  const pending = pendingChanges.value[user.user_number]
  if (pending?.can_speak === false) {
    return pending.mute_days ? `待确认：禁言 ${pending.mute_days} 天` : '待确认：永久禁言'
  }
  if (pending?.can_speak === true) return '待确认：恢复自由发言'
  if (user.can_speak === false) {
    return user.speak_until
      ? `禁言至 ${new Date(user.speak_until).toLocaleString('zh-CN')}（到期自动恢复）`
      : '永久禁言'
  }
  return '自由发言'
}

// ===== 权限修改（本地待确认 + SweetAlert2 输入原因）=====

/**
 * 选择禁言时长（撤销自由发言前）。
 * 返回天数 1/7/14，永久为 null；取消返回 undefined。
 */
async function promptMuteDuration(): Promise<number | null | undefined> {
  const result = await Swal.fire({
    title: '选择禁言时长',
    html: `
      <style>
        .mute-tip{color:var(--text-sub);font-size:13px;line-height:1.8;margin-bottom:12px}
        .mute-pills{display:flex;gap:10px;justify-content:center;flex-wrap:wrap}
        .mp-pill{display:inline-flex;align-items:center;gap:7px;padding:8px 18px;
          border:1px solid #e2e8f0;border-radius:999px;font-size:14px;color:var(--text-sub);
          cursor:pointer;background:var(--surface-plain);transition:all .15s}
        .mp-pill:hover{border-color:#b8c4d0}
        .mp-pill input{accent-color:var(--primary,#e74c3c);width:14px;height:14px;margin:0}
        .mp-pill:has(input:checked){border-color:var(--primary,#e74c3c);
          background:color-mix(in srgb, var(--danger) 10%, transparent);color: var(--danger-text);font-weight:700}
      </style>
      <div class="mute-tip">限时禁言到期后用户访问时自动恢复自由发言</div>
      <div class="mute-pills">
        <label class="mp-pill"><input type="radio" name="mute_pick" value="1" checked><span>1 天</span></label>
        <label class="mp-pill"><input type="radio" name="mute_pick" value="7"><span>7 天</span></label>
        <label class="mp-pill"><input type="radio" name="mute_pick" value="14"><span>14 天</span></label>
        <label class="mp-pill"><input type="radio" name="mute_pick" value="0"><span>永久</span></label>
      </div>`,
    showCancelButton: true,
    confirmButtonText: '确认禁言',
    cancelButtonText: '取消',
    preConfirm: () => {
      const el = document.querySelector(
        '.swal2-popup input[name="mute_pick"]:checked',
      ) as HTMLInputElement | null
      if (!el) {
        Swal.showValidationMessage('请选择禁言时长')
        return false
      }
      return Number(el.value)
    },
  })
  if (!result.isConfirmed) return undefined
  return result.value === 0 ? null : (result.value as number)
}

async function toggleLocalPermission(userNumber: number, field: string, currentValue: boolean) {
  if (!canToggleField(field)) return
  if (!pendingChanges.value[userNumber]) pendingChanges.value[userNumber] = {}

  if (field === 'can_speak' && currentValue === true
      && pendingChanges.value[userNumber][field] === undefined) {
    const days = await promptMuteDuration()
    if (days === undefined) return
    pendingChanges.value[userNumber].can_speak = false
    if (days !== null) pendingChanges.value[userNumber].mute_days = days
  } else if (pendingChanges.value[userNumber][field] !== undefined) {
    delete pendingChanges.value[userNumber][field]
    if (field === 'can_speak') delete pendingChanges.value[userNumber].mute_days
  } else {
    pendingChanges.value[userNumber][field] = !currentValue
  }
  if (Object.keys(pendingChanges.value[userNumber]).length === 0) {
    delete pendingChanges.value[userNumber]
  }
}

// 分析权限变更类型
function analyzePermissionChanges(changes: any) {
  const normalPerms = ['can_speak']
  const adminPerms = [
    'is_super_admin',
    'is_big_admin',
    'is_admin',
    'can_manage_users',
    'can_manage_problems',
    'can_manage_posts',
    'can_manage_tags',
  ]

  const normalGrants: any[] = []
  const normalRevokes: any[] = []
  const adminGrants: any[] = []
  const adminRevokes: any[] = []

  for (const [field, value] of Object.entries(changes)) {
    const changeInfo = { permission: field, new_value: value }

    if (field === 'is_banned') {
      if (value === false) { normalGrants.push(changeInfo) } else { normalRevokes.push(changeInfo) }
    } else if (normalPerms.includes(field)) {
      if (value === true) { normalGrants.push(changeInfo) } else { normalRevokes.push(changeInfo) }
    } else if (adminPerms.includes(field)) {
      if (value === true) { adminGrants.push(changeInfo) } else { adminRevokes.push(changeInfo) }
    }
  }

  return { normalGrants, normalRevokes, adminGrants, adminRevokes }
}

// SweetAlert2 输入原因
async function promptReason(operationName: string): Promise<string | undefined> {
  const { value: reason } = await Swal.fire({
    title: `请输入 ${operationName} 的原因`,
    html: `<textarea id="swal-textarea" class="swal2-textarea" rows="3" style="width:100%;max-width:460px;text-align:left;margin:0 auto;display:block;"></textarea>`,
    showCancelButton: true,
    confirmButtonText: '操作',
    cancelButtonText: '取消',
    focusConfirm: false,
    preConfirm: () => {
      const textarea = document.getElementById('swal-textarea') as HTMLTextAreaElement | null
      const value = textarea ? textarea.value.trim() : ''
      if (!value) { Swal.showValidationMessage('原因不能为空！'); return false }
      return value
    }
  })
  return reason
}

// 更新用户权限（记录陶片放逐日志）
async function updateUserField(userNumber: number, changes: any, reason?: string) {
  await apiClient.post(`/api/admin/users/${userNumber}/permissions`, {
    changes,
    reason
  })
}

// 更新用户资料
async function updateUserProfile(userNumber: number, updateData: any) {
  const data: any = await apiClient.put(`/api/admin/users/${userNumber}`, updateData)
  const target = users.value.find(u => u.user_number === userNumber)
  if (target && data) Object.assign(target, data)
  // 若修改的是当前登录用户的资料，立即同步 authStore
  if (currentUser.value?.user_number === userNumber) {
    await authStore.syncCurrentUser()
  }
}

// 确认修改
async function applyUserChanges(userNumber: number) {
  const targetUser = users.value.find(u => u.user_number === userNumber)
  if (targetUser && !canModifyPermissions(targetUser)) {
    Swal.fire({ icon: 'warning', title: '无效操作', text: '你没有权限' })
    return
  }
  const changes = pendingChanges.value[userNumber]
  if (!changes || Object.keys(changes).length === 0) {
    Swal.fire({ icon: 'info', title: '没有待修改的权限', timer: 1200 })
    return
  }
  const reason = await promptReason('确认修改权限')
  if (!reason) return

  const onlyCheaterChange = Object.keys(changes).length === 1 && changes.is_cheater !== undefined
  const onlyBannedChange = Object.keys(changes).length === 1 && changes.is_banned !== undefined

  const { normalGrants, normalRevokes, adminGrants, adminRevokes } = analyzePermissionChanges(changes)

  const hasNormalChanges = normalGrants.length > 0 || normalRevokes.length > 0
  const hasAdminChanges = adminGrants.length > 0 || adminRevokes.length > 0

  if (hasNormalChanges && hasAdminChanges) {
    Swal.fire({
      icon: 'warning',
      title: '无效操作',
      text: '不能同时修改普通权限和管理权限，请分别操作'
    })
    return
  }

  let actionLabel = ''

  if (onlyCheaterChange) {
    actionLabel = changes.is_cheater ? '棕名惩罚' : '解除棕名'
  } else if (onlyBannedChange) {
    actionLabel = changes.is_banned === false ? '授予权限' : '用户封禁'
  } else if (hasNormalChanges) {
    if (normalGrants.length > 0 && normalRevokes.length === 0) {
      actionLabel = '授予权限'
    } else if (normalRevokes.length > 0 && normalGrants.length === 0) {
      actionLabel = '撤销权限'
    } else {
      actionLabel = '陶片放逐'
    }
  } else if (hasAdminChanges) {
    actionLabel = '管理轮换'
  }

  try {
    const submitChanges = { ...changes }
    // is_super_admin 只有白名单能提交（超管不能授/撤超管）
    if (!isWhiteList(currentProfile.value)) {
      delete submitChanges.is_super_admin
    }
    if (Object.keys(submitChanges).length === 0) {
      delete pendingChanges.value[userNumber]
      await loadUsers()
      return
    }
    await updateUserField(userNumber, submitChanges, reason)
    delete pendingChanges.value[userNumber]
    await loadUsers()

    Swal.fire({
      icon: 'success',
      title: '修改成功',
      text: `${actionLabel}操作已完成`,
      timer: 1500
    })
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '更新失败', text: err.response?.data?.detail || err.message || '未知错误' })
  }
}

// ===== 行内编辑 =====
const editing = ref<null | { field: 'username' | 'user_tag' | 'remark'; userNumber: number }>(null)
const editingValue = ref('')

function startEdit(field: 'username' | 'user_tag' | 'remark', user: any) {
  if (!canModifyUser(user)) return
  if (field === 'user_tag' && user.is_cheater) return
  if (field === 'user_tag' && !canManageTags(currentUser.value)) {
    Swal.fire({ icon: 'info', title: '修改 Tag 需要管理员权限' })
    return
  }
  editing.value = { field, userNumber: user.user_number }
  editingValue.value = field === 'username'
    ? (user.username || '未命名')
    : field === 'user_tag'
      ? (user.user_tag || '')
      : (user.remark || '')
  nextTick(() => {
    const input = document.querySelector('.editable-field-input') as HTMLInputElement | null
    if (input) { input.focus(); input.select() }
  })
}

function cancelEdit() {
  editing.value = null
  editingValue.value = ''
}

async function saveEdit(user: any) {
  if (!editing.value) return
  const field = editing.value.field
  const val = editingValue.value.trim()
  const original = field === 'username'
    ? (user.username || '未命名')
    : field === 'user_tag'
      ? (user.user_tag || '')
      : (user.remark || '')
  cancelEdit()
  if (val === original) return
  try {
    await updateUserProfile(user.user_number, { [field]: val || null })
    await loadUsers()
    if (field === 'user_tag') {
      Swal.fire({
        icon: 'success',
        title: val ? `已更新 Tag 为「${val}」` : '已清除 Tag',
        timer: 1200,
        showConfirmButton: false
      })
    } else if (field === 'username') {
      Swal.fire({
        icon: 'success',
        title: '已更新用户名',
        timer: 1200,
        showConfirmButton: false
      })
    }
  } catch (err: any) {
    Swal.fire({
      icon: 'error',
      title: '修改失败',
      text: err.response?.data?.detail || err.message || '未知错误'
    })
  }
}

// ===== 改名与 Tag 变更历史 =====
async function openUsernameHistory(user: any) {
  try {
    const records: any = await apiClient.get(`/api/users/${user.id || user.user_number}/username-history`)
    if (!records || records.length === 0) {
      Swal.fire({
        icon: 'info',
        title: `${user.username} 的改名记录`,
        text: '暂无改名历史记录',
      })
      return
    }
    const html = `
      <div style="text-align: left; max-height: 350px; overflow-y: auto; font-size: 13px;">
        <table style="width: 100%; border-collapse: collapse;">
          <thead>
            <tr style="border-bottom: 2px solid #e2e8f0; color: #64748b;">
              <th style="padding: 6px 8px; text-align: left;">变更详情</th>
              <th style="padding: 6px 8px; text-align: left;">操作人</th>
              <th style="padding: 6px 8px; text-align: right;">时间</th>
            </tr>
          </thead>
          <tbody>
            ${records.map((r: any) => `
              <tr style="border-bottom: 1px solid #f1f5f9;">
                <td style="padding: 8px;">
                  <span style="color: #64748b; text-decoration: line-through;">${r.old_username}</span>
                  <span style="margin: 0 4px; color: #94a3b8;">&rarr;</span>
                  <strong style="color: #3b82f6;">${r.new_username}</strong>
                </td>
                <td style="padding: 8px;">
                  <span style="color: ${r.is_self ? '#10b981' : '#3b82f6'}; font-weight: 500;">
                    ${r.is_self ? '用户本人' : r.operator_name}
                  </span>
                </td>
                <td style="padding: 8px; text-align: right; color: #94a3b8; font-size: 12px;">
                  ${r.created_at ? new Date(r.created_at).toLocaleString('zh-CN', { dateStyle: 'short', timeStyle: 'short' }) : '-'}
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `
    Swal.fire({
      title: `${user.username} 的改名记录`,
      html,
      width: '600px',
      confirmButtonText: '关闭',
    })
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '获取记录失败', text: err.response?.data?.detail || err.message })
  }
}

async function openTagHistory(user: any) {
  try {
    const records: any = await apiClient.get(`/api/users/${user.id || user.user_number}/tag-history`)
    if (!records || records.length === 0) {
      Swal.fire({
        icon: 'info',
        title: `${user.username} 的 Tag 变动记录`,
        text: '暂无 Tag 变动历史记录',
      })
      return
    }
    const actionBadgeColors: Record<string, string> = {
      grant: 'background: #dcfce7; color: #15803d;',
      revoke: 'background: #fee2e2; color: #b91c1c;',
      custom_tag: 'background: #f3e8ff; color: #7e22ce;',
      shop_redeem: 'background: #fef3c7; color: #b45309;',
    }
    const html = `
      <div style="text-align: left; max-height: 350px; overflow-y: auto; font-size: 13px;">
        <table style="width: 100%; border-collapse: collapse;">
          <thead>
            <tr style="border-bottom: 2px solid #e2e8f0; color: #64748b;">
              <th style="padding: 6px 8px; text-align: left;">动作</th>
              <th style="padding: 6px 8px; text-align: left;">Tag 名称</th>
              <th style="padding: 6px 8px; text-align: left;">操作人</th>
              <th style="padding: 6px 8px; text-align: right;">时间</th>
            </tr>
          </thead>
          <tbody>
            ${records.map((r: any) => `
              <tr style="border-bottom: 1px solid #f1f5f9;">
                <td style="padding: 8px;">
                  <span style="display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 600; ${actionBadgeColors[r.action] || ''}">
                    ${r.action_label}
                  </span>
                </td>
                <td style="padding: 8px; font-weight: 600;">「${r.tag_name}」</td>
                <td style="padding: 8px;">
                  <span style="color: #3b82f6; font-weight: 500;">${r.operator_name}</span>
                </td>
                <td style="padding: 8px; text-align: right; color: #94a3b8; font-size: 12px;">
                  ${r.created_at ? new Date(r.created_at).toLocaleString('zh-CN', { dateStyle: 'short', timeStyle: 'short' }) : '-'}
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `
    Swal.fire({
      title: `${user.username} 的 Tag 变动记录`,
      html,
      width: '640px',
      confirmButtonText: '关闭',
    })
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '获取记录失败', text: err.response?.data?.detail || err.message })
  }
}

// 双击头像上传
function uploadAvatar(user: any) {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = 'image/*'
  input.style.display = 'none'
  document.body.appendChild(input)
  input.addEventListener('change', async () => {
    const file = input.files?.[0]
    if (!file) { input.remove(); return }
    try {
      const fd = new FormData()
      fd.append('file', file)
      const data: any = await apiClient.post(`/api/admin/users/${user.user_number}/avatar`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      const target = users.value.find(u => u.user_number === user.user_number)
      if (target) target.avatar_url = data.avatar_url
    } catch { /* 静默 */ } finally { input.remove() }
  })
  input.click()
}

// ===== 用户列表加载 =====
async function loadUsers() {
  if (!canAccessAdmin.value) return

  loading.value = true
  try {
    const data = await apiClient.get('/api/admin/users?limit=1000')
    users.value = (data as any) || []
    currentUser.value = authStore.currentUser
    currentProfile.value = authStore.currentUser
    Object.keys(filterStates.value).forEach(k => {
      ;(filterStates.value as any)[k] = 'off'
    })
  } catch (error: any) {
    console.error('加载用户列表失败:', error)
    Swal.fire({ icon: 'error', title: '加载失败', text: error.response?.data?.detail || error.message })
  } finally {
    loading.value = false
  }
}

// ===== 选择功能 =====
const selectedUsers = ref<Set<number>>(new Set())

function toggleUserSelection(userNumber: number) {
  if (selectedUsers.value.has(userNumber)) {
    selectedUsers.value.delete(userNumber)
  } else {
    selectedUsers.value.add(userNumber)
  }
}

function toggleSelectAll(e: Event) {
  const checked = (e.target as HTMLInputElement).checked
  if (!checked) {
    pagedUsers.value.forEach(user => selectedUsers.value.delete(user.user_number))
  } else {
    pagedUsers.value.forEach(user => {
      if (canModifyPermissions(user)) selectedUsers.value.add(user.user_number)
    })
  }
}

// ===== 批量操作 =====
async function batchAction(actionName: string, updateObj: any) {
  const ids = Array.from(selectedUsers.value)
  if (ids.length === 0) return
  const targetUsers = ids
    .map(id => users.value.find(u => u.user_number === id))
    .filter(u => u && canModifyPermissions(u))
  if (targetUsers.length === 0) return

  let payload = updateObj
  if (updateObj.can_speak === false) {
    const days = await promptMuteDuration()
    if (days === undefined) return
    payload = days !== null ? { can_speak: false, mute_days: days } : { can_speak: false }
  }

  const reason = await promptReason(actionName)
  if (!reason) return
  try {
    const filteredIds = targetUsers.map(u => u.user_number)
    await apiClient.post('/api/admin/users/batch', {
      user_numbers: filteredIds,
      updates: payload,
      reason
    })
    selectedUsers.value.clear()
    await loadUsers()
  } catch (error: any) {
    Swal.fire({ icon: 'error', title: '批量操作失败', text: error.response?.data?.detail || error.message })
  }
}

// ===== 重置密码（仅白名单可用）=====
async function resetPassword(userId: number, username: string) {
  const result = await Swal.fire({
    title: `重置 ${username} 的密码`,
    input: 'password',
    inputAttributes: { autocomplete: 'new-password' },
    showCancelButton: true,
    confirmButtonText: '确认重置',
    cancelButtonText: '取消',
    preConfirm: (value) => {
      if (!value) {
        Swal.showValidationMessage('请填写完整')
        return false
      }
      if (value.length < 6) {
        Swal.showValidationMessage('密码长度过短或过长')
        return false
      }
      return value
    }
  })

  if (result.isConfirmed) {
    const newPassword = result.value
    try {
      await apiClient.post(`/api/admin/users/id/${userId}/reset-password`, { password: newPassword })
      await Swal.fire({
        icon: 'success',
        title: '重置成功',
        text: `用户 ${username} 的密码已重置`,
        timer: 1500
      })
    } catch (err: any) {
      Swal.fire({
        icon: 'error',
        title: '重置失败',
        text: err.response?.data?.detail || err.message || '未知错误'
      })
    }
  }
}

// ===== 心跳上报 =====
let heartbeatTimer: number | undefined

async function updateLastSeen() {
  if (!authStore.isAuthenticated) return
  try {
    await apiClient.post('/api/users/me/seen')
  } catch { /* 静默 */ }
}

// ===== 生命周期 =====
onMounted(async () => {
  if (!authStore.currentUser && authStore.accessToken) {
    try {
      await authStore.fetchCurrentUser()
    } catch { /* 失败时由路由守卫处理 */ }
  }
  if (canAccessAdmin.value) {
    await loadUsers()
    await updateLastSeen()
    heartbeatTimer = window.setInterval(updateLastSeen, 30000)
  }
})

onUnmounted(() => {
  if (heartbeatTimer) clearInterval(heartbeatTimer)
})
</script>

<template>
  <div class="admin-page">
    <div class="main-layout">
      <div class="content-wrapper">
        <div class="main-content">
          <div class="card">
            <div class="card-header">用户管理</div>
            <div class="search-bar">
              <input
                v-model="searchQuery"
                type="text"
                placeholder="用户名 / 备注 / 头衔 / 身份 / 用户编号（支持部分匹配）"
              >
              <span class="result-count">共 {{ filteredUsers.length }} 位用户 · 第 {{ currentPage }}/{{ totalPages }} 页</span>
            </div>
            <div class="filter-tags">
              <span
                v-for="(state, key) in filterStates"
                :key="key"
                :class="getFilterTagClass(key as keyof FilterStates)"
                @click="toggleFilterTag(key as keyof FilterStates)"
              >
                {{ getFilterLabel(key as keyof FilterStates) }}
              </span>
            </div>
            <div class="table-wrap">
              <div v-if="loading" class="loading-text">
                加载中...
              </div>

              <div v-else-if="filteredUsers.length === 0" class="loading-text">
                没有找到匹配的用户
              </div>

              <table v-else>
                <thead>
                  <tr>
                    <th class="check-col"><input type="checkbox" title="全选" @change="toggleSelectAll"></th>
                    <th>注册时间</th>
                    <th>用户编号</th>
                    <th>头像</th>
                    <th>用户名</th>
                    <th>标签</th>
                    <th>OI</th>
                    <th>XCPC</th>
                    <th>备注名</th>
                    <th>用户类型</th>
                    <th>权限</th>
                    <th v-if="isCurrentWhiteList">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="user in pagedUsers" :key="user.user_number">
                    <td class="check-col">
                      <input
                        type="checkbox"
                        class="row-checkbox"
                        :class="isUserOnline(user) ? 'online' : 'offline'"
                        :disabled="!canModifyPermissions(user)"
                        :checked="selectedUsers.has(user.user_number)"
                        @change="toggleUserSelection(user.user_number)"
                      >
                    </td>

                    <td>{{ formatTime(user.created_at) }}</td>

                    <td>
                      <router-link
                        :to="`/user/${user.user_number}`"
                        style="color:var(--text-strong);text-decoration:none;"
                      >
                        {{ user.user_number }}
                      </router-link>
                    </td>

                    <td>
                      <img
                        class="avatar-image"
                        :src="user.avatar_url || letterAvatar(user.username)"
                        :alt="user.username"
                        style="width:32px;height:32px;border-radius:50%;object-fit:cover;background:var(--bg-subtle);display:block;cursor:pointer;"
                        @error="(e) => (e.target as HTMLImageElement).src = letterAvatar(user.username)"
                        @dblclick="canModifyUser(user) && uploadAvatar(user)"
                      >
                    </td>

                    <td>
                      <input
                        v-if="editing && editing.field === 'username' && editing.userNumber === user.user_number"
                        v-model="editingValue"
                        class="editable-field-input"
                        @blur="saveEdit(user)"
                        @keydown.enter.prevent="($event.target as HTMLInputElement).blur()"
                        @keydown.esc.prevent="cancelEdit"
                      >
                      <div v-else class="username-cell">
                        <span
                          class="username-display"
                          :style="{ color: getUserDisplayColor(user) }"
                          @dblclick="startEdit('username', user)"
                        >{{ user.username || '未命名' }}</span>
                        <button
                          type="button"
                          class="cell-history-btn"
                          title="查看改名记录"
                          @click.stop="openUsernameHistory(user)"
                        >
                          <i class="fa-solid fa-clock-rotate-left"></i>
                        </button>
                      </div>
                    </td>

                    <td>
                      <input
                        v-if="editing && editing.field === 'user_tag' && editing.userNumber === user.user_number"
                        v-model="editingValue"
                        placeholder="输入 Tag（留空清除）"
                        class="editable-field-input"
                        @blur="saveEdit(user)"
                        @keydown.enter.prevent="($event.target as HTMLInputElement).blur()"
                        @keydown.esc.prevent="cancelEdit"
                      >
                      <div v-else class="tag-cell">
                        <span @dblclick="startEdit('user_tag', user)">
                          <span
                            v-if="user.display_tag"
                            class="user-tag-display"
                            :style="{ backgroundColor: getUserDisplayColor(user) }"
                          >{{ user.display_tag }}</span>
                          <span v-else class="editable-field">-</span>
                        </span>
                        <button
                          type="button"
                          class="cell-history-btn"
                          title="查看 Tag 变动记录"
                          @click.stop="openTagHistory(user)"
                        >
                          <i class="fa-solid fa-clock-rotate-left"></i>
                        </button>
                      </div>
                    </td>

                    <td>
                      <span v-if="user.ccf_level && user.ccf_level >= 1" class="level-badge-svg">{{ user.ccf_level }} 级 <span v-html="getCcfBadgeHtml(user.ccf_level, user)"></span></span>
                      <span v-else>-</span>
                    </td>

                    <td>
                      <span v-if="user.xcpc_level && user.xcpc_level >= 1" class="level-badge-svg">{{ user.xcpc_level }} 级 <span v-html="getXcpcBalloonHtml(user.xcpc_level, user)"></span></span>
                      <span v-else>-</span>
                    </td>

                    <td>
                      <input
                        v-if="editing && editing.field === 'remark' && editing.userNumber === user.user_number"
                        v-model="editingValue"
                        class="editable-field-input"
                        @blur="saveEdit(user)"
                        @keydown.enter.prevent="($event.target as HTMLInputElement).blur()"
                        @keydown.esc.prevent="cancelEdit"
                      >
                      <span
                        v-else
                        class="editable-field"
                        @dblclick="startEdit('remark', user)"
                      >{{ user.remark || '-' }}</span>
                    </td>

                    <td>{{ roleLabel(user) }}</td>

                    <td>
                      <div class="perm-group-line">
                        <span class="perm-cat">普通权限</span>
                        <span
                          v-if="canModifyPermissions(user)"
                          class="action-link"
                          :class="[(pendingChanges[user.user_number]?.is_banned !== undefined ? (pendingChanges[user.user_number].is_banned ? 'red' : 'green') : (user.is_banned ? 'red' : 'green')), (pendingChanges[user.user_number]?.is_banned !== undefined ? 'pending' : '')]"
                          style="cursor:pointer;"
                          @click="toggleLocalPermission(user.user_number, 'is_banned', user.is_banned || false)"
                        >进入主站</span>
                        <span v-else class="action-link" :class="user.is_banned ? 'red' : 'green'" style="cursor:default;">进入主站</span>
                        |
                        <span
                          v-if="canModifyPermissions(user)"
                          class="action-link"
                          :class="[(pendingChanges[user.user_number]?.is_cheater !== undefined ? (pendingChanges[user.user_number].is_cheater ? 'green' : 'red') : (user.is_cheater ? 'green' : 'red')), (pendingChanges[user.user_number]?.is_cheater !== undefined ? 'pending' : '')]"
                          style="cursor:pointer;"
                          @click="toggleLocalPermission(user.user_number, 'is_cheater', user.is_cheater || false)"
                        >学术不端</span>
                        <span v-else class="action-link" :class="user.is_cheater ? 'green' : 'red'" style="cursor:default;">学术不端</span>
                        |
                        <span
                          v-if="canModifyPermissions(user)"
                          class="action-link"
                          :class="[(pendingChanges[user.user_number]?.can_speak !== undefined ? (pendingChanges[user.user_number].can_speak ? 'green' : 'red') : (user.can_speak !== false ? 'green' : 'red')), (pendingChanges[user.user_number]?.can_speak !== undefined ? 'pending' : '')]"
                          style="cursor:pointer;"
                          :title="muteTitle(user)"
                          @click="toggleLocalPermission(user.user_number, 'can_speak', user.can_speak !== false)"
                        >自由发言</span>
                        <span v-else class="action-link" :class="user.can_speak !== false ? 'green' : 'red'" style="cursor:default;" :title="muteTitle(user)">自由发言</span>
                      </div>
                      <div class="perm-group-line">
                        <span class="perm-cat">管理权限</span>
                        <template v-for="(perm, idx) in [
                          ...(isCurrentWhiteList ? [{ name: '超管', field: 'is_super_admin', on: !!user.is_super_admin }] : []),
                          ...(isCurrentWhiteList ? [{ name: '大管', field: 'is_big_admin', on: !!user.is_big_admin }] : []),
                          { name: '题管', field: 'can_manage_problems', on: !!user.can_manage_problems },
                          { name: '社管', field: 'can_manage_posts', on: !!user.can_manage_posts },
                          // 这两项同样是「管理名单」公示的内容，后台必须能看见、能改
                          { name: '用户管理', field: 'can_manage_users', on: !!user.can_manage_users },
                          { name: 'Tag 管理', field: 'can_manage_tags', on: !!user.can_manage_tags }
                        ]" :key="perm.field">
                          <span v-if="idx > 0"> | </span>
                          <span
                            v-if="canModifyPermissions(user) && canToggleField(perm.field)"
                            class="action-link"
                            :class="[(pendingChanges[user.user_number]?.[perm.field] !== undefined ? (pendingChanges[user.user_number][perm.field] ? 'green' : 'red') : (perm.on ? 'green' : 'red')), (pendingChanges[user.user_number]?.[perm.field] !== undefined ? 'pending' : '')]"
                            style="cursor:pointer;"
                            @click="toggleLocalPermission(user.user_number, perm.field, perm.on)"
                          >{{ perm.name }}</span>
                          <span v-else class="action-link" :class="perm.on ? 'green' : 'red'" style="cursor:default;">{{ perm.name }}</span>
                        </template>
                      </div>
                      <div class="perm-group-line" style="margin-top:4px;">
                        <button
                          class="btn-sm confirm"
                          :disabled="!(pendingChanges[user.user_number] && Object.keys(pendingChanges[user.user_number]).length > 0)"
                          @click="applyUserChanges(user.user_number)"
                        >确认修改</button>
                      </div>
                    </td>

                    <!-- 重置密码按钮：仅白名单可见 -->
                    <td v-if="canResetPassword(authStore.currentUser)">
                      <button class="btn-reset-password" @click="resetPassword(user.id, user.username)">重置密码</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div v-if="!loading && totalPages > 1" class="pagination-bar">
              <button class="page-btn" :disabled="currentPage <= 1" @click="goToPage(currentPage - 1)">上一页</button>
              <template v-for="(p, i) in pageNumbers" :key="`${p}-${i}`">
                <span v-if="p === '...'" class="page-ellipsis">…</span>
                <button
                  v-else
                  class="page-btn"
                  :class="{ active: p === currentPage }"
                  @click="goToPage(p)"
                >{{ p }}</button>
              </template>
              <button class="page-btn" :disabled="currentPage >= totalPages" @click="goToPage(currentPage + 1)">下一页</button>
            </div>

            <div class="batch-bar" :class="{ show: selectedUsers.size > 0 }">
              <span class="info">已选 {{ selectedUsers.size }} 位用户</span>
              <template v-if="isCurrentWhiteList || isCurrentSuper">
                <button class="btn-sm grant" @click="batchAction('批量授予进入主站权限', { is_banned: false })">授予进入主站权限</button>
                <button class="btn-sm revoke" @click="batchAction('批量撤销进入主站权限', { is_banned: true })">撤销进入主站权限</button>
                <button class="btn-sm grant" @click="batchAction('批量授予自由发言权限', { can_speak: true })">授予自由发言权限</button>
                <button class="btn-sm revoke" @click="batchAction('批量撤销自由发言权限', { can_speak: false })">撤销自由发言权限</button>
              </template>
              <button v-if="isCurrentSuper" class="btn-sm grant" @click="batchAction('批量授予题目管理权限', { can_manage_problems: true })">授予题目管理权限</button>
              <button v-if="isCurrentSuper" class="btn-sm revoke" @click="batchAction('批量撤销题目管理权限', { can_manage_problems: false })">撤销题目管理权限</button>
              <button v-if="isCurrentSuper" class="btn-sm grant" @click="batchAction('批量授予社区管理权限', { can_manage_posts: true })">授予社区管理权限</button>
              <button v-if="isCurrentSuper" class="btn-sm revoke" @click="batchAction('批量撤销社区管理权限', { can_manage_posts: false })">撤销社区管理权限</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ========== 基础样式 ========== */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

.admin-page {
  font-family: inherit;
  line-height: 1.5;
}

.main-layout {
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 20px 20px 20px;
  position: relative;
  min-height: 100vh;
}

.card {
  background: var(--surface);
  -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: 20px 24px;
  margin-bottom: 24px;
}

.card-header {
  font-size: 1.25rem;
  font-weight: 600;
  border-left: 4px solid var(--primary);
  padding-left: 12px;
  margin-bottom: 20px;
}

.search-bar {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.search-bar input {
  flex: 1;
  min-width: 200px;
  padding: 8px 14px;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  transition: border .2s;
}

.search-bar input:focus {
  border-color: var(--primary);
}

.search-bar .result-count {
  font-size: 13px;
  color: var(--text-sub);
  white-space: nowrap;
}

.filter-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 8px 0 12px 0;
}

.filter-tag {
  padding: 4px 16px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  user-select: none;
  transition: background .2s, color .2s, border-color .2s, transform .1s;
  border: 2px solid transparent;
  background: var(--bg-subtle);
  color: var(--text-sub);
  white-space: nowrap;
}

.filter-tag:hover {
  background: #e0e0e0;
  transform: scale(1.02);
}

.filter-tag.active-green {
  background: color-mix(in srgb, var(--success) 10%, transparent);
  color: var(--success-text);
  border-color: #52C41A;
}

.filter-tag.active-red {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  color: #E74C3C;
  border-color: #E74C3C;
}

.filter-tag.active-online {
  background: color-mix(in srgb, var(--success) 10%, transparent);
  color: var(--success-text);
  border-color: #2ecc71;
}

.filter-tag.active-offline {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  color: var(--primary-text);
  border-color: var(--primary);
}

.table-wrap {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

th,
td {
  padding: 10px 12px;
  text-align: left;
  border-bottom: 1px solid #edf2f7;
  vertical-align: middle;
}

th {
  background: var(--surface-plain);
  font-weight: 600;
  color: var(--text-strong);
  white-space: nowrap;
  position: sticky;
  top: 0;
  z-index: 2;
}

th:first-child,
td:first-child {
  padding-left: 8px;
}

th.check-col,
td.check-col {
  width: 40px;
  text-align: center;
}

th.check-col input,
td.check-col input {
  cursor: pointer;
  width: 16px;
  height: 16px;
}

.row-checkbox {
  -webkit-appearance: none;
  appearance: none;
  width: 16px;
  height: 16px;
  border: 2px solid #ccc;
  border-radius: 4px;
  outline: none;
  cursor: pointer;
  background: var(--surface-plain);
  position: relative;
  flex-shrink: 0;
}

.row-checkbox:checked {
  background: #3498db;
  border-color: #3498db;
}

.row-checkbox:checked::after {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 12px;
  height: 12px;
  background: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='20 6 9 17 4 12'/%3E%3C/svg%3E") no-repeat center;
  background-size: contain;
}

.row-checkbox.online {
  border-color: #2ecc71;
  background: #2ecc71;
}

.row-checkbox.offline {
  border-color: var(--primary);
  background: var(--primary);
}

.row-checkbox.online:checked {
  background: #2ecc71;
  border-color: #2ecc71;
}

.row-checkbox.offline:checked {
  background: var(--primary);
  border-color: var(--primary);
}

.row-checkbox:disabled {
  opacity: 0.5;
  cursor: default;
}

.perm-group-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin-bottom: 3px;
}

.perm-group-line:last-child {
  margin-bottom: 0;
}

.perm-cat {
  font-size: 11px;
  color: var(--text-sub);
  margin-right: 2px;
}

.action-link {
  text-decoration: none;
  font-size: 13px;
  padding: 2px 6px;
  border-radius: 4px;
  cursor: pointer;
}

.action-link.green {
  color: light-dark(#52C41A, #34d399);
  font-weight: 500;
}

.action-link.red {
  color: #E74C3C;
  font-weight: 500;
}

.action-link.green:hover {
  background: color-mix(in srgb, var(--success) 10%, transparent);
}

.action-link.red:hover {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
}

.action-link.pending {
  border: 2px solid #f39c12;
  background: color-mix(in srgb, var(--warning) 12%, transparent);
}

.editable-field {
  cursor: default;
  padding: 2px 4px;
  border-radius: 3px;
}

.editable-field:hover {
  background: rgba(148, 163, 184, 0.18);
}

.editable-field-input {
  border: 1px solid var(--primary);
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 14px;
  width: 100%;
  min-width: 80px;
  outline: none;
}

.username-display {
  font-weight: bold;
  cursor: pointer;
  transition: background .15s;
}

.username-display:hover {
  background: rgba(148, 163, 184, 0.18);
}

.user-tag-display {
  display: inline-block;
  border-radius: 2px;
  padding: 2px 9px;
  color: #fff;
  font-size: 11.5px;
  font-weight: 600;
  margin: 0 0 0 8px;
  cursor: default;
  transition: filter .15s;
  background-color: #9C3DCF;
}

.user-tag-display:hover {
  filter: brightness(0.9);
}

.btn-sm {
  padding: 4px 12px;
  border: none;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  margin: 2px;
}

.btn-sm.grant {
  background: #52C41A;
  color: #fff;
}

.btn-sm.revoke {
  background: #E74C3C;
  color: #fff;
}

.btn-sm:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.btn-sm.confirm {
  background: var(--primary);
  color: white;
  border: none;
  padding: 4px 10px;
  border-radius: 40px;
  font-size: 15px;
  cursor: pointer;
  transition: background 0.2s;
  width: auto;
  font-family: inherit;
  font-weight: 500;
}

.btn-sm.confirm:hover {
  background: var(--primary-hover);
}

.btn-sm.confirm:disabled {
  opacity: 0.5;
  cursor: default;
}

.btn-sm.confirm:disabled:hover {
  background: var(--primary);
}

.btn-reset-password {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  padding: 5px 12px;
  border: none;
  border-radius: 5px;
  cursor: pointer;
  text-decoration: none;
  transition: filter 0.2s, transform 0.1s;
  white-space: nowrap;
  font-family: inherit;
  line-height: 1.4;
  color: #fff;
  background: #E74C3C;
}

.btn-reset-password:hover {
  filter: brightness(1.1);
}

.btn-reset-password:active {
  transform: scale(0.96);
}

.batch-bar {
  display: none;
  margin-top: 16px;
  padding: 12px 16px;
  background: var(--surface-plain);
  border-radius: 8px;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.batch-bar.show {
  display: flex;
}

.batch-bar .info {
  font-size: 14px;
  color: var(--text-strong);
  margin-right: 8px;
}

.batch-bar .btn-sm {
  font-size: 12px;
  padding: 4px 10px;
}

@keyframes rainbow-fill {
  0% { fill: var(--primary); }
  14.28% { fill: #e67e22; }
  28.57% { fill: #f1c40f; }
  42.85% { fill: #2ecc71; }
  57.14% { fill: #3498db; }
  71.42% { fill: #9b59b6; }
  85.71% { fill: #8e44ad; }
  100% { fill: var(--primary); }
}

.rainbow-badge path,
.rainbow-badge .fa-secondary {
  animation: rainbow-fill 5s linear infinite;
}

.level-badge-svg {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-weight: 500;
  color: var(--text-strong);
  white-space: nowrap;
}

.level-badge-svg svg {
  width: 16px;
  height: 16px;
  vertical-align: middle;
  margin-left: 2px;
}

.loading-text {
  color: var(--text-sub);
  text-align: center;
  padding: 40px;
}

.pagination-bar {
  display: flex;
  gap: 6px;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  margin-top: 16px;
}

.page-btn {
  min-width: 32px;
  padding: 6px 10px;
  border: 1px solid #ddd;
  background: var(--surface-plain);
  border-radius: 6px;
  font-size: 13px;
  color: var(--text-strong);
  cursor: pointer;
  font-family: inherit;
  transition: border-color .15s, color .15s, background .15s;
}

.page-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.page-btn.active {
  background: var(--primary);
  border-color: var(--primary);
  color: white;
}

.page-btn:disabled {
  opacity: 0.4;
  cursor: default;
}

.page-btn:disabled:hover {
  border-color: #ddd;
  color: var(--text-strong);
}

.page-btn.active:disabled:hover {
  color: white;
}

.page-ellipsis {
  padding: 0 4px;
  color: var(--text-sub);
  font-size: 13px;
  user-select: none;
}

@media (max-width: 800px) {
  table,
  thead,
  tbody,
  th,
  td,
  tr {
    display: block;
  }

  thead tr {
    display: none;
  }

  tr {
    border: 1px solid #eee;
    margin-bottom: 10px;
    padding: 10px;
  }

  td {
    border: none;
    padding: 6px 0;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  td::before {
    content: attr(data-label);
    font-weight: 600;
    color: var(--text-strong);
    margin-right: 10px;
    flex-shrink: 0;
  }

  td.check-col {
    display: flex;
    justify-content: flex-start;
  }

  td.check-col::before {
    content: '';
    display: none;
  }

  .batch-bar {
    flex-direction: column;
    align-items: stretch;
  }

  .editable-field-input {
    width: auto;
  }
}

@media (max-width: 600px) {
  .card {
    padding: 16px 18px;
  }

  .batch-bar {
    flex-direction: column;
    align-items: stretch;
  }
}

@media (max-width: 600px) {
  .main-layout {
    padding: 0 0 16px 0;
  }
}

.username-cell, .tag-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.cell-history-btn {
  background: none;
  border: none;
  color: var(--text-muted, #94a3b8);
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 4px;
  font-size: 11px;
  opacity: 0.6;
  transition: all 0.2s;
}

.cell-history-btn:hover {
  opacity: 1;
  color: var(--primary, #3b82f6);
  background: var(--surface-sub, rgba(0, 0, 0, 0.05));
}
</style>
