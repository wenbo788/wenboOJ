<script setup lang="ts">
/**
 * NLNOC 私信面板 —— 顶栏信封点开的「浮动伪弹窗」。
 *
 * 外观刻意做成一台小手机：状态栏（时间 / 信号 / Wi-Fi / 电量）+ 刘海药丸 +
 * Home Indicator，屏内视图滑动切换：
 *   home    标题 NLNOC + 会话列表（置顶「全服犇犇」，数据与首页犇犇同源）
 *   search  右上角「+」进来，按 UID / 用户名搜索开聊
 *   chat    私信聊天（NLNOCChat）/ 群聊（NLNOCGroup）/ 犇犇（NLNOCBenben）
 *
 * 犇犇回归手机面板（曾拆成顶栏独立大浮窗，用户反馈后合并回来）：
 * 首页列表置顶入口 + 独立视图，返回键回首页。
 *
 * 面板由 TopBar 挂载（顶栏跨路由常驻），开关状态在 stores/nlnoc：
 * 用户主页「发消息」通过 startChat 写 pendingPeer，本组件挂载时消费它，
 * 实现「点按钮 → 直达聊天页」。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import apiClient from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useNlnocStore, type NLNOCUser } from '@/stores/nlnoc'
import { useAcademicMode } from '@/utils/academicMode'
import { letterAvatar } from '@/utils/avatar'
import { userNameColor } from '@/utils/userColor'
import UserAvatarStatus from '@/components/UserAvatarStatus.vue'
import NLNOCChat from './NLNOCChat.vue'
import NLNOCGroup from './NLNOCGroup.vue'
import NLNOCBenben from './NLNOCBenben.vue'

type View = 'home' | 'search' | 'chat' | 'benben' | 'group' | 'group-new' | 'group-manage'

interface Conversation {
  peer: NLNOCUser
  last_message: {
    id: number
    sender_id: number
    content: string
    created_at: string
    is_recalled?: boolean
  }
  unread: number
}

/** 群聊会话（GET /api/conversations 的 item） */
interface GroupConvBrief {
  id: number
  type: string
  title: string | null
  avatar_url?: string | null
  member_count: number
  last_message_at: string | null
  last_message_content: string | null
  unread: number
}

const authStore = useAuthStore()
const nlnoc = useNlnocStore()
// 学术模式：隐藏犇犇（与首页/顶栏同一口径，入口不藏就是半吊子状态）
const { academicMode } = useAcademicMode()

const view = ref<View>('home')
/** 视图切换方向：前进从右滑入，返回从左滑入（手机 App 的老套路） */
const slideDir = ref<'fwd' | 'back'>('fwd')
const slideName = computed(() =>
  slideDir.value === 'fwd' ? 'nlnoc-slide-fwd' : 'nlnoc-slide-back',
)

const peer = ref<NLNOCUser | null>(null)
const convs = ref<Conversation[]>([])
const convsLoading = ref(false)

/* ---------------- 状态栏：时间 / 网络 / 电量 ---------------- */

const clock = ref('')
const online = ref(typeof navigator === 'undefined' ? true : navigator.onLine)
const batteryPct = ref<number | null>(null)
const batteryCharging = ref(false)

const pad = (n: number) => String(n).padStart(2, '0')
const tickClock = () => {
  const d = new Date()
  clock.value = `${d.getHours()}:${pad(d.getMinutes())}`
}

const batteryIcon = computed(() => {
  if (batteryCharging.value) return 'fa-battery-full'
  const p = batteryPct.value
  if (p === null) return 'fa-battery-three-quarters'
  if (p <= 0.1) return 'fa-battery-empty'
  if (p <= 0.25) return 'fa-battery-quarter'
  if (p <= 0.5) return 'fa-battery-half'
  if (p <= 0.75) return 'fa-battery-three-quarters'
  return 'fa-battery-full'
})
const batteryLow = computed(
  () => batteryPct.value !== null && batteryPct.value <= 0.2 && !batteryCharging.value,
)

let clockTimer = 0
let batteryCleanup: (() => void) | null = null

const initBattery = async () => {
  const nav = navigator as Navigator & { getBattery?: () => Promise<any> }
  if (typeof nav.getBattery !== 'function') return
  try {
    const bat = await nav.getBattery()
    const update = () => {
      batteryPct.value = bat.level
      batteryCharging.value = bat.charging
    }
    update()
    bat.addEventListener('levelchange', update)
    bat.addEventListener('chargingchange', update)
    batteryCleanup = () => {
      bat.removeEventListener('levelchange', update)
      bat.removeEventListener('chargingchange', update)
    }
  } catch {
    /* 浏览器不给电量就只显示图标 */
  }
}

const onOnline = () => (online.value = true)
const onOffline = () => (online.value = false)

/* ---------------- 会话列表 ---------------- */

const myId = computed(() => authStore.currentUser?.id ?? -1)

const convsError = ref('')

const loadConversations = async () => {
  convsLoading.value = true
  try {
    const data: any = await apiClient.get('/api/messages/conversations')
    convs.value = data?.conversations || []
    convsError.value = ''
  } catch (err: any) {
    // 失败不再静默：静默的表现就是「会话无声从列表消失」且无从定位。
    // 保留本地已合成的会话（如刚发出的），只展示错误 + 重试入口。
    convsError.value = err?.response?.data?.detail || err?.message || '会话列表加载失败'
  } finally {
    convsLoading.value = false
  }
  // 群聊列表跟私信一起首载/重试（失败静默：错误态归私信侧主控）
  void loadGroupConvs(true)
}

/**
 * 静默刷新会话列表（10s 一轮）：只为在线状态点、最新预览、未读跟上，
 * 不显示 loading、失败保留现有列表（错误态由手动进入时的 loadConversations 负责）。
 */
let convTimer = 0

const silentRefreshConvs = async () => {
  try {
    const data: any = await apiClient.get('/api/messages/conversations')
    convs.value = data?.conversations || []
    convsError.value = ''
  } catch {
    /* 静默失败：宁可旧一点也不闪错误、不清空 */
  }
  await loadGroupConvs(true)
}

/** 切回标签页立即刷一轮列表 */
const onPanelVisible = () => {
  if (document.visibilityState === 'visible') void silentRefreshConvs()
}

/**
 * 聊天页发送成功后本地合成/更新会话（服务端已落库，这里只是不等下一次拉取）：
 * 保证「发过的人一定在列表里」，即使随后的列表请求失败也不会看起来凭空消失。
 */
const onChatSent = (payload: { peer: NLNOCUser; message: any }) => {
  const { peer: p, message } = payload
  if (!p?.id || !message?.id) return
  const idx = convs.value.findIndex((c) => c.peer.id === p.id)
  if (idx !== -1) {
    const [old] = convs.value.splice(idx, 1)
    convs.value.unshift({ ...old, peer: p, last_message: message, unread: 0 })
  } else {
    convs.value.unshift({ peer: p, last_message: message, unread: 0 })
  }
}

/**
 * 聊天轮询顺带带回的最新对方资料：更新在线状态点（列表行 + 当前会话对象），
 * 在线/离线切换不用等下一次全量拉取。
 */
const onPeerUpdated = (p: NLNOCUser) => {
  if (!p?.id) return
  const idx = convs.value.findIndex((c) => c.peer.id === p.id)
  if (idx !== -1) {
    convs.value[idx] = { ...convs.value[idx], peer: { ...convs.value[idx].peer, ...p } }
  }
  const cur = peer.value
  if (cur && cur.id === p.id) peer.value = { ...cur, ...p }
}

const avatarOf = (u: NLNOCUser) => u.avatar_url || letterAvatar(u.username)

/** 头像 URL 加载失败：隐藏叠放的 img，露出底层的占位图标 */
const onAvaError = (e: Event) => {
  const t = e.currentTarget as HTMLImageElement | null
  if (t) t.style.display = 'none'
}

/** 会话列表里加载失败的群头像（按会话 id 记录）：失败时回退默认占位图标 */
const brokenGroupAva = ref<Set<number>>(new Set())
const onGroupAvaError = (id: number) => {
  const next = new Set(brokenGroupAva.value)
  next.add(id)
  brokenGroupAva.value = next
}

const previewOf = (c: Conversation) => {
  if (c.last_message.is_recalled) return '消息已撤回'
  const text = (c.last_message.content || '').replace(/\s+/g, ' ').trim()
  const mine = c.last_message.sender_id === myId.value
  const prefix = mine ? '我: ' : ''
  return prefix + (text.length > 24 ? text.slice(0, 24) + '…' : text)
}

/** 会话行时间：今天 → HH:mm，昨天 → 昨天，更早 → MM-DD */
const shortTime = (iso: string) => {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const t = d.getTime()
  if (t >= startOfToday) return `${d.getHours()}:${pad(d.getMinutes())}`
  if (t >= startOfToday - 86400_000) return '昨天'
  return `${d.getMonth() + 1}-${pad(d.getDate())}`
}

/* ---------------- 视图切换 ---------------- */

const goHome = () => {
  slideDir.value = 'back'
  view.value = 'home'
  peer.value = null
  loadConversations()
}

const goSearch = () => {
  plusMenu.value = false
  slideDir.value = 'fwd'
  view.value = 'search'
}

const openBenben = () => {
  slideDir.value = 'fwd'
  view.value = 'benben'
}

// 学术模式中途打开时正看着犇犇：直接回首页，不留空屏
watch(academicMode, (v) => {
  if (v && view.value === 'benben') goHome()
})

const openChat = (u: NLNOCUser) => {
  peer.value = u
  slideDir.value = 'fwd'
  view.value = 'chat'
}

/* ---------------- 「+」下拉：发起私信 / 创建群聊 ---------------- */

const plusMenu = ref(false)

const togglePlus = () => {
  plusMenu.value = !plusMenu.value
}

/** 点 + 菜单外面任意处关闭（+ 按钮 click.stop，不冒泡到这里） */
const onPlusOutside = (e: MouseEvent) => {
  const t = e.target as HTMLElement | null
  if (!t?.closest?.('.nlnoc-plus-wrap')) plusMenu.value = false
}

watch(plusMenu, (open) => {
  if (open) document.addEventListener('click', onPlusOutside, true)
  else document.removeEventListener('click', onPlusOutside, true)
})

/* ---------------- 群聊会话（列表混排 + 打开） ---------------- */

const groupConvs = ref<GroupConvBrief[]>([])
const activeGroupId = ref(0)

const loadGroupConvs = async (silent = false) => {
  try {
    const data: any = await apiClient.get('/api/conversations')
    groupConvs.value = Array.isArray(data?.items) ? data.items : []
  } catch {
    if (!silent) groupConvs.value = groupConvs.value
    /* 非静默也不闪整页错误：群聊列表失败保留旧数据，下一轮轮询兜底 */
  }
}

/** home 混排：私信 + 群聊按各自最新消息时间倒序，没有消息的沉底 */
const homeItems = computed(() => {
  const dm = convs.value.map((c) => ({
    kind: 'dm' as const,
    time: new Date(c.last_message?.created_at || 0).getTime() || 0,
    item: c,
  }))
  const gp = groupConvs.value.map((g) => ({
    kind: 'group' as const,
    time: g.last_message_at ? new Date(g.last_message_at).getTime() : 0,
    item: g,
  }))
  return [...dm, ...gp].sort((a, b) => b.time - a.time)
})

/** 打开群聊即视为已读：清掉列表角标并让顶栏未读数跟上 */
const markGroupRead = async (id: number) => {
  try {
    await apiClient.post(`/api/conversations/${id}/read`)
  } catch {
    /* 静默：清零失败不影响阅读 */
  }
  const g = groupConvs.value.find((x) => x.id === id)
  if (g) g.unread = 0
  void nlnoc.refreshUnread()
}

const openGroup = (id: number) => {
  activeGroupId.value = id
  slideDir.value = 'fwd'
  view.value = 'group'
  void markGroupRead(id)
}

const onGroupSent = () => {
  void loadGroupConvs(true)
}

/* ---------------- 创建群聊（+ 菜单第二项，搜索选人） ---------------- */

const cgTitle = ref('')
const cgQuery = ref('')
const cgResults = ref<NLNOCUser[]>([])
const cgSearching = ref(false)
const cgPicked = ref<NLNOCUser[]>([])
const cgCreating = ref(false)
const cgError = ref('')
let cgTimer = 0
let cgSeq = 0

const runCgSearch = async () => {
  const q = cgQuery.value.trim()
  const seq = ++cgSeq
  if (!q) {
    cgResults.value = []
    cgSearching.value = false
    return
  }
  cgSearching.value = true
  try {
    const data: any = await apiClient.get('/api/users/search', { params: { q } })
    if (seq === cgSeq) cgResults.value = data?.items || []
  } catch {
    if (seq === cgSeq) cgResults.value = []
  } finally {
    if (seq === cgSeq) cgSearching.value = false
  }
}

watch(cgQuery, () => {
  window.clearTimeout(cgTimer)
  cgTimer = window.setTimeout(() => void runCgSearch(), 250)
})

const cgTogglePick = (u: NLNOCUser) => {
  const i = cgPicked.value.findIndex((x) => x.id === u.id)
  if (i === -1) cgPicked.value.push(u)
  else cgPicked.value.splice(i, 1)
}

const goCreateGroup = () => {
  plusMenu.value = false
  cgTitle.value = ''
  cgQuery.value = ''
  cgResults.value = []
  cgPicked.value = []
  cgError.value = ''
  slideDir.value = 'fwd'
  view.value = 'group-new'
}

const submitCreateGroup = async () => {
  if (!cgTitle.value.trim() || cgCreating.value) return
  cgCreating.value = true
  cgError.value = ''
  try {
    const data: any = await apiClient.post('/api/conversations', {
      type: 'group',
      title: cgTitle.value.trim(),
      // 后端 member_ids 语义是用户编号（user_number/UID），与邀请输入框一致；
      // 之前误传主键 id，导致建群时混入 user_number 恰好等于该 id 的无关用户
      member_ids: cgPicked.value.map((u) => u.user_number),
    })
    cgTitle.value = ''
    cgQuery.value = ''
    cgPicked.value = []
    await loadGroupConvs(true)
    openGroup(data.id)
  } catch (err: any) {
    cgError.value = err?.response?.data?.detail || '创建失败'
  } finally {
    cgCreating.value = false
  }
}

/* ---------------- 群聊管理（群会话页右上角「管理」进入） ---------------- */

interface GMemberBrief {
  user_id: number
  username: string
  role: string
}

const mgDetail = ref<{
  id: number
  title: string | null
  avatar_url?: string | null
  owner_id: number | null
  dissolved?: boolean
  member_count: number
  members: GMemberBrief[]
} | null>(null)
const mgTitle = ref('')
const mgAvatar = ref('')
const mgInvite = ref('')
const mgError = ref('')
const mgNotice = ref('')
const mgBusy = ref(false)

const mgIsOwner = computed(() => !!mgDetail.value && mgDetail.value.owner_id === myId.value)
const mgCanManage = computed(() => {
  const r = mgDetail.value?.members.find((m) => m.user_id === myId.value)?.role
  return r === 'owner' || r === 'admin'
})
const roleLabel = (r: string) => (r === 'owner' ? '群主' : r === 'admin' ? '管理' : '成员')

const flashMg = (msg: string) => {
  mgNotice.value = msg
  window.setTimeout(() => {
    if (mgNotice.value === msg) mgNotice.value = ''
  }, 2500)
}

const loadManage = async () => {
  mgError.value = ''
  try {
    const data: any = await apiClient.get(`/api/conversations/${activeGroupId.value}`)
    mgDetail.value = data
    mgTitle.value = data?.title || ''
    mgAvatar.value = data?.avatar_url || ''
  } catch (err: any) {
    mgError.value = err?.response?.data?.detail || '加载群信息失败'
    mgDetail.value = null
  }
}

const openManage = () => {
  slideDir.value = 'fwd'
  view.value = 'group-manage'
  void loadManage()
}

const manageBack = () => {
  slideDir.value = 'back'
  view.value = 'group'
}

const saveGroupSettings = async () => {
  if (!mgTitle.value.trim() || mgBusy.value) return
  mgBusy.value = true
  try {
    await apiClient.put(`/api/conversations/${activeGroupId.value}`, {
      title: mgTitle.value.trim(),
      avatar_url: mgAvatar.value.trim(),
    })
    await Promise.all([loadManage(), loadGroupConvs(true)])
    flashMg('群设置已更新')
  } catch (err: any) {
    mgError.value = err?.response?.data?.detail || '更新失败'
  } finally {
    mgBusy.value = false
  }
}

const inviteGroup = async () => {
  const ids = mgInvite.value
    .split(/[\s,，]+/)
    .map(Number)
    .filter((n) => Number.isInteger(n) && n > 0)
  if (!ids.length) {
    mgError.value = '请输入要邀请的 UID'
    return
  }
  mgBusy.value = true
  try {
    await apiClient.post(`/api/conversations/${activeGroupId.value}/members`, {
      member_ids: ids,
    })
    mgInvite.value = ''
    await loadManage()
    flashMg('邀请成功')
  } catch (err: any) {
    mgError.value = err?.response?.data?.detail || '邀请失败'
  } finally {
    mgBusy.value = false
  }
}

/** 移除成员 / 自己退团：后端按 target 是否等于操作者写不同系统消息 */
const removeOrLeave = async (m: GMemberBrief) => {
  const self = m.user_id === myId.value
  const tip = self
    ? '确定退出该群聊？退出后如需再加入须由群成员邀请。'
    : `确认将 ${m.username} 移出群聊？`
  if (!window.confirm(tip)) return
  mgBusy.value = true
  try {
    await apiClient.delete(`/api/conversations/${activeGroupId.value}/members/${m.user_id}`)
    await loadManage()
    flashMg(self ? '已退出群聊' : '已移除')
  } catch (err: any) {
    mgError.value = err?.response?.data?.detail || (self ? '退出失败' : '移除失败')
  } finally {
    mgBusy.value = false
  }
}

const toggleAdmin = async (m: GMemberBrief) => {
  const role = m.role === 'admin' ? 'member' : 'admin'
  mgBusy.value = true
  try {
    await apiClient.put(`/api/conversations/${activeGroupId.value}/members/${m.user_id}/role`, {
      role,
    })
    await loadManage()
    flashMg(role === 'admin' ? '已设为管理员' : '已取消管理员')
  } catch (err: any) {
    mgError.value = err?.response?.data?.detail || '操作失败'
  } finally {
    mgBusy.value = false
  }
}

/** 解散群聊：仅群主可见，不可逆——历史消息保留、全员禁止再发送 */
const dissolveGroup = async () => {
  if (!window.confirm('确定解散该群聊？解散后不可恢复，所有成员只能查看历史消息！')) return
  mgBusy.value = true
  try {
    await apiClient.post(`/api/conversations/${activeGroupId.value}/dissolve`)
    flashMg('群聊已解散')
    await loadManage()
    await loadGroupConvs(true)
  } catch (err: any) {
    mgError.value = err?.response?.data?.detail || '解散失败'
  } finally {
    mgBusy.value = false
  }
}

/* ---------------- 用户搜索（防抖） ---------------- */

const searchQ = ref('')
const searchResults = ref<NLNOCUser[]>([])
const searching = ref(false)
let searchTimer = 0
let searchSeq = 0

const runSearch = async () => {
  const q = searchQ.value.trim()
  if (!q) return
  const seq = ++searchSeq
  searching.value = true
  try {
    const data: any = await apiClient.get('/api/users/search', { params: { q } })
    if (seq === searchSeq) searchResults.value = data?.items || []
  } catch {
    if (seq === searchSeq) searchResults.value = []
  } finally {
    if (seq === searchSeq) searching.value = false
  }
}

watch(searchQ, () => {
  window.clearTimeout(searchTimer)
  if (!searchQ.value.trim()) {
    searchResults.value = []
    searching.value = false
    return
  }
  searchTimer = window.setTimeout(runSearch, 280)
})

/* ---------------- 视口跟踪（手机端准全屏适配） ---------------- */

/**
 * ≤640px 手机端把机身铺成准全屏：宽度贴视口、高度撑到底，拖动与
 * 缩放停用（把手隐藏、onDragStart 早退）。锚点垂直方向仍走 CSS 的
 * calc(100% + 14px)——锚在吸顶的顶栏里，滚动自动跟随；横向 left 与
 * 机身宽高由 JS 按信封按钮的实时位置算：窄屏顶栏会换行，写死数值
 * 早晚对不上。onMounted 里先于首帧 sync 一次，不会闪错位。
 */
const anchorRef = ref<HTMLElement | null>(null)
const compact = ref(window.matchMedia('(max-width: 640px)').matches)
const viewport = ref({ w: window.innerWidth, h: window.innerHeight })
const wrapBox = ref({ left: 0, bottom: 0 })

const syncViewport = () => {
  viewport.value = { w: window.innerWidth, h: window.innerHeight }
  compact.value = window.matchMedia('(max-width: 640px)').matches
  const parent = anchorRef.value?.parentElement
  if (compact.value && parent) {
    const pr = parent.getBoundingClientRect()
    wrapBox.value = { left: pr.left, bottom: pr.bottom }
  }
}

/* ---------------- 拖动机身 ---------------- */

/**
 * 按住机身非交互区域（状态栏、页头、气泡间空白）即可拖动；
 * 列表/输入框/按钮被排除，滚动与点击不受影响。
 * 位移写在 anchor 层的 transform 上——phone 自身的开合动画也用 transform，
 * 两层分开，互不覆盖。
 */
const phoneRef = ref<HTMLElement | null>(null)
const dragging = ref(false)
const offset = ref({ x: 0, y: 0 })
const anchorStyle = computed(() => {
  if (compact.value) {
    // 手机端：机身左缘贴视口 8px（wrapBox.left 是信封按钮的视口横坐标，
    // anchor 的 left 相对它），宽高交给 phoneStyle；transform 不用
    return { left: `${8 - wrapBox.value.left}px`, right: 'auto' }
  }
  return { transform: `translate(${offset.value.x}px, ${offset.value.y}px)` }
})

const DRAG_EXCLUDE =
  'button, a, input, textarea, select, label, .nlnoc-list, .nlnoc-msgs, .nlnoc-composer'
/** 拖出视口时至少保留的可见宽度/高度，防止拖丢 */
const EDGE_W = 120
const EDGE_H = 64

let grab = { px: 0, py: 0, ox: 0, oy: 0 }
let base = { left: 0, right: 0, top: 0, bottom: 0, w: 0, h: 0, vw: 0, vh: 0 }

const clamp = (v: number, min: number, max: number) => Math.min(Math.max(v, min), max)

const onDragStart = (e: PointerEvent) => {
  if (e.button !== 0 || compact.value) return // 手机端准全屏，没有可拖的位移
  const target = e.target as HTMLElement
  if (target.closest(DRAG_EXCLUDE)) return
  const el = e.currentTarget as HTMLElement
  const r = el.getBoundingClientRect()
  base = {
    left: r.left,
    right: r.right,
    top: r.top,
    bottom: r.bottom,
    w: r.width,
    h: r.height,
    vw: window.innerWidth,
    vh: window.innerHeight,
  }
  grab = { px: e.clientX, py: e.clientY, ox: offset.value.x, oy: offset.value.y }
  dragging.value = true
  el.setPointerCapture(e.pointerId)
}

const onDragMove = (e: PointerEvent) => {
  if (!dragging.value) return
  // 无位移基准 = 拖动开始时的 rect 减去当时的偏移
  const bLeft = base.left - grab.ox
  const bTop = base.top - grab.oy
  let nx = grab.ox + (e.clientX - grab.px)
  let ny = grab.oy + (e.clientY - grab.py)
  // 约束「机身在视口内至少露出 EDGE_W×EDGE_H」等价于：
  //   机身左/上边 ∈ [EDGE − 边长, 视口边长 − EDGE]
  // 两端必须以同一条基准边（left/top）表达。旧版右/下界误用了
  // right/bottom 基准——上界整整小了一个机身宽度（vw−EDGE−w 而非
  // vw−EDGE），起手即被向内拽、右/底部永远到不了边，初始位置
  // （right: −6px 贴边）甚至落在禁区里。
  nx = clamp(nx, EDGE_W - base.w - bLeft, base.vw - EDGE_W - bLeft)
  ny = clamp(ny, EDGE_H - base.h - bTop, base.vh - EDGE_H - bTop)
  offset.value = { x: nx, y: ny }
}

const onDragEnd = (e: PointerEvent) => {
  if (!dragging.value) return
  dragging.value = false
  try {
    ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
  } catch {
    /* 浏览器可能已自动释放 */
  }
}

/** 双击机身空白处归位（手机端无位移，一并停用） */
const onDragDouble = (e: MouseEvent) => {
  if (compact.value) return
  const target = e.target as HTMLElement
  if (target.closest(DRAG_EXCLUDE)) return
  offset.value = { x: 0, y: 0 }
}

/* ---------------- 右下角把手：调整机身大小 ---------------- */

/**
 * 桌面端拖右下角改宽高，写在 phone 内联样式（size 为 null 时走 CSS 的
 * min(348px, …) 响应式默认值）；尺寸存本机 localStorage，双击把手恢复
 * 默认。手机端由 syncViewport 锁成准全屏：phoneStyle 的 compact 分支
 * 忽略 size，把手同时被 v-if 摘掉。
 */
const size = ref<{ w: number; h: number } | null>(null)
const resizing = ref(false)
let resizeGrab = { px: 0, py: 0, w: 0, h: 0 }

const RESIZE_MIN_W = 300
const RESIZE_MIN_H = 420
const RESIZE_MAX_W = 760
const RESIZE_MAX_H = 940
const SIZE_KEY = 'nlnoc-phone-size'

try {
  const raw = window.localStorage.getItem(SIZE_KEY)
  if (raw) {
    const v = JSON.parse(raw)
    if (v && Number.isFinite(v.w) && Number.isFinite(v.h)) size.value = { w: v.w, h: v.h }
  }
} catch {
  /* 隐私模式 / 坏 JSON：当没存过 */
}

watch(size, (v) => {
  try {
    if (v) window.localStorage.setItem(SIZE_KEY, JSON.stringify(v))
    else window.localStorage.removeItem(SIZE_KEY)
  } catch {
    /* 存失败不致命，下次拖动再试 */
  }
})

const phoneStyle = computed(() => {
  if (compact.value) {
    // 手机端：顶到锚点（wrapBox.bottom + 14）以下铺满视口，底部留 8
    const top = wrapBox.value.bottom + 14
    return {
      width: `${Math.max(240, viewport.value.w - 16)}px`,
      height: `${Math.max(320, viewport.value.h - top - 8)}px`,
    }
  }
  if (!size.value) return undefined
  // 视口变小也钳得回去（显示器切换 / 窗口缩小不至于拖爆出屏）
  const maxW = Math.max(RESIZE_MIN_W, Math.min(RESIZE_MAX_W, viewport.value.w - 40))
  const maxH = Math.max(RESIZE_MIN_H, Math.min(RESIZE_MAX_H, viewport.value.h - 90))
  return {
    width: `${clamp(size.value.w, RESIZE_MIN_W, maxW)}px`,
    height: `${clamp(size.value.h, RESIZE_MIN_H, maxH)}px`,
  }
})

const onResizeStart = (e: PointerEvent) => {
  if (e.button !== 0 || compact.value) return
  const r = phoneRef.value?.getBoundingClientRect()
  resizeGrab = { px: e.clientX, py: e.clientY, w: r?.width ?? 348, h: r?.height ?? 640 }
  resizing.value = true
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
}

const onResizeMove = (e: PointerEvent) => {
  if (!resizing.value) return
  const maxW = Math.max(RESIZE_MIN_W, Math.min(RESIZE_MAX_W, viewport.value.w - 40))
  const maxH = Math.max(RESIZE_MIN_H, Math.min(RESIZE_MAX_H, viewport.value.h - 90))
  size.value = {
    w: clamp(resizeGrab.w + (e.clientX - resizeGrab.px), RESIZE_MIN_W, maxW),
    h: clamp(resizeGrab.h + (e.clientY - resizeGrab.py), RESIZE_MIN_H, maxH),
  }
}

const onResizeEnd = (e: PointerEvent) => {
  if (!resizing.value) return
  resizing.value = false
  try {
    ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
  } catch {
    /* 浏览器可能已自动释放 */
  }
}

const onResizeReset = () => {
  size.value = null
}

/* ---------------- 生命周期 ---------------- */

onMounted(() => {
  syncViewport() // 先于首帧对齐手机端准全屏几何
  window.addEventListener('resize', syncViewport)
  tickClock()
  clockTimer = window.setInterval(tickClock, 15000)
  window.addEventListener('online', onOnline)
  window.addEventListener('offline', onOffline)
  void initBattery()

  // 用户主页「发消息」进来的：直接落到聊天页
  if (nlnoc.pendingPeer) {
    peer.value = nlnoc.pendingPeer
    nlnoc.pendingPeer = null
    view.value = 'chat'
  } else {
    view.value = 'home'
  }
  loadConversations()
  // 列表静默轮询：在线状态点 / 最新预览 / 未读跟上节奏，不转圈
  convTimer = window.setInterval(silentRefreshConvs, 10000)
  document.addEventListener('visibilitychange', onPanelVisible)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', syncViewport)
  window.clearInterval(clockTimer)
  window.clearInterval(convTimer)
  window.clearTimeout(searchTimer)
  document.removeEventListener('visibilitychange', onPanelVisible)
  document.removeEventListener('click', onPlusOutside, true)
  window.removeEventListener('online', onOnline)
  window.removeEventListener('offline', onOffline)
  batteryCleanup?.()
})
</script>

<template>
  <div ref="anchorRef" class="nlnoc-anchor" :class="{ dragging }" :style="anchorStyle">
    <Transition name="nlnoc-pop" appear>
      <div
        ref="phoneRef"
        class="nlnoc-phone"
        role="dialog"
        aria-label="NLNOC 私信"
        :style="phoneStyle"
        @pointerdown="onDragStart"
        @pointermove="onDragMove"
        @pointerup="onDragEnd"
        @pointercancel="onDragEnd"
        @dblclick="onDragDouble"
      >
      <!-- 状态栏：刘海药丸 + 时间 + 信号/Wi-Fi/电量 -->
      <div class="nlnoc-statusbar">
        <span class="nlnoc-clock">{{ clock }}</span>
        <span class="nlnoc-island" aria-hidden="true"></span>
        <span class="nlnoc-indicators">
          <i class="fa-solid fa-signal" aria-hidden="true"></i>
          <i
            class="fa-solid"
            :class="online ? 'fa-wifi' : 'fa-plane'"
            :title="online ? '已联网' : '当前离线'"
          ></i>
          <span class="nlnoc-batt" :class="{ low: batteryLow }">
            <i class="fa-solid" :class="batteryIcon" aria-hidden="true"></i>
            <span v-if="batteryPct !== null" class="nlnoc-batt-pct">
              {{ Math.round(batteryPct * 100) }}%
            </span>
          </span>
        </span>
      </div>

      <!-- 屏幕 -->
      <div class="nlnoc-screen">
        <Transition :name="slideName" mode="out-in">
          <!-- ===== 首页：标题 + 会话列表 ===== -->
          <div v-if="view === 'home'" key="home" class="nlnoc-page">
            <div class="nlnoc-head">
              <div class="nlnoc-brand">
                <span class="nlnoc-logo">NLNOC</span>
                <span class="nlnoc-slogan">online chat</span>
              </div>
              <!-- 「+」下拉：发起私信 / 创建群聊 -->
              <div class="nlnoc-plus-wrap">
                <button
                  type="button"
                  class="nlnoc-round-btn"
                  title="添加"
                  @click.stop="togglePlus"
                >
                  <i class="fa-solid fa-plus" :class="{ 'nlnoc-plus-open': plusMenu }"></i>
                </button>
                <div v-if="plusMenu" class="nlnoc-plus-menu">
                  <button type="button" @click="goSearch">
                    <i class="fa-regular fa-comment-dots"></i> 发起私信
                  </button>
                  <button type="button" @click="goCreateGroup">
                    <i class="fa-solid fa-user-group"></i> 创建群聊
                  </button>
                </div>
              </div>
            </div>

            <div class="nlnoc-list">
              <!-- 全服犇犇：固定第一位，内容就是首页那条犇犇流（学术模式隐藏） -->
              <button
                v-if="!academicMode"
                type="button"
                class="nlnoc-conv nlnoc-conv--broadcast"
                @click="openBenben"
              >
                <span class="nlnoc-conv-avatar benben">
                  <i class="fa-solid fa-bullhorn"></i>
                </span>
                <span class="nlnoc-conv-main">
                  <span class="nlnoc-conv-row1">
                    <span class="nlnoc-conv-name broadcast">全服犇犇</span>
                    <span class="nlnoc-conv-time">实时</span>
                  </span>
                  <span class="nlnoc-conv-row2">
                    <span class="nlnoc-conv-preview">全站公开动态 · 与首页同源</span>
                  </span>
                </span>
              </button>

              <div v-if="convsLoading && convs.length === 0" class="nlnoc-empty">
                <i class="fa-solid fa-spinner fa-spin"></i>
              </div>
              <div v-else-if="convsError && convs.length === 0" class="nlnoc-empty">
                <i class="fa-solid fa-triangle-exclamation"></i>
                <p>{{ convsError }}</p>
                <button type="button" class="nlnoc-retry" @click="loadConversations">重试</button>
              </div>
              <div v-else-if="homeItems.length === 0" class="nlnoc-empty">
                <i class="fa-regular fa-comment-dots"></i>
                <p>还没有会话</p>
                <p class="nlnoc-empty-sub">点右上角「+」发私信或创建群聊</p>
              </div>

              <!-- 私信 + 群聊混排（按各自最新消息时间倒序） -->
              <template v-for="it in homeItems" :key="it.kind === 'dm' ? 'dm-' + it.item.peer.id : 'gp-' + it.item.id">
                <button
                  v-if="it.kind === 'dm'"
                  type="button"
                  class="nlnoc-conv"
                  @click="openChat(it.item.peer)"
                >
                  <UserAvatarStatus :user="it.item.peer" :size="9" class="nlnoc-conv-avatar-wrap">
                    <img :src="avatarOf(it.item.peer)" class="nlnoc-avatar-img" alt="" />
                  </UserAvatarStatus>
                  <span class="nlnoc-conv-main">
                    <span class="nlnoc-conv-row1">
                      <span class="nlnoc-conv-name" :style="{ color: userNameColor(it.item.peer) }">
                        {{ it.item.peer.username }}
                      </span>
                      <span class="nlnoc-conv-time">{{ shortTime(it.item.last_message.created_at) }}</span>
                    </span>
                    <span class="nlnoc-conv-row2">
                      <span class="nlnoc-conv-preview">{{ previewOf(it.item) }}</span>
                      <span v-if="it.item.unread > 0" class="nlnoc-conv-badge">
                        {{ it.item.unread > 99 ? '99+' : it.item.unread }}
                      </span>
                    </span>
                  </span>
                </button>

                <button
                  v-else
                  type="button"
                  class="nlnoc-conv"
                  @click="openGroup(it.item.id)"
                >
                  <span class="nlnoc-conv-avatar nlnoc-conv-avatar--group">
                    <i v-if="!it.item.avatar_url || brokenGroupAva.has(it.item.id)" class="fa-solid fa-user-group"></i>
                    <img
                      v-if="it.item.avatar_url && !brokenGroupAva.has(it.item.id)"
                      :src="it.item.avatar_url"
                      class="nlnoc-conv-avatar-img"
                      alt=""
                      @error="onGroupAvaError(it.item.id)"
                    />
                  </span>
                  <span class="nlnoc-conv-main">
                    <span class="nlnoc-conv-row1">
                      <span class="nlnoc-conv-name">{{ it.item.title || '未命名群组' }}</span>
                      <span class="nlnoc-conv-time">
                        {{ it.item.last_message_at ? shortTime(it.item.last_message_at) : '' }}
                      </span>
                    </span>
                    <span class="nlnoc-conv-row2">
                      <span class="nlnoc-conv-preview">
                        {{ it.item.last_message_content || `${it.item.member_count} 名成员` }}
                      </span>
                      <span v-if="it.item.unread > 0" class="nlnoc-conv-badge">
                        {{ it.item.unread > 99 ? '99+' : it.item.unread }}
                      </span>
                    </span>
                  </span>
                </button>
              </template>
            </div>
          </div>

          <!-- ===== 搜索页 ===== -->
          <div v-else-if="view === 'search'" key="search" class="nlnoc-page">
            <div class="nlnoc-subhead">
              <button type="button" class="nlnoc-back" title="返回" @click="goHome">
                <i class="fa-solid fa-chevron-left"></i>
              </button>
              <div class="nlnoc-searchbox">
                <i class="fa-solid fa-magnifying-glass"></i>
                <input
                  v-model="searchQ"
                  type="text"
                  placeholder="搜索 UID / 用户名"
                  maxlength="50"
                  @keydown.esc="goHome"
                />
                <button
                  v-if="searchQ"
                  type="button"
                  class="nlnoc-clear"
                  title="清空"
                  @click="searchQ = ''"
                >
                  <i class="fa-solid fa-circle-xmark"></i>
                </button>
              </div>
            </div>

            <div class="nlnoc-list">
              <div v-if="searching" class="nlnoc-empty">
                <i class="fa-solid fa-spinner fa-spin"></i>
              </div>
              <div v-else-if="!searchQ.trim()" class="nlnoc-empty">
                <i class="fa-solid fa-user-group"></i>
                <p>输入 UID 或用户名</p>
                <p class="nlnoc-empty-sub">找到人 → 回车开聊</p>
              </div>
              <div v-else-if="searchResults.length === 0" class="nlnoc-empty">
                <i class="fa-regular fa-face-frown"></i>
                <p>没有找到「{{ searchQ.trim() }}」</p>
              </div>
              <button
                v-for="u in searchResults"
                :key="u.id"
                type="button"
                class="nlnoc-conv"
                @click="openChat(u)"
              >
                <UserAvatarStatus :user="u" :size="9" class="nlnoc-conv-avatar-wrap">
                  <img :src="avatarOf(u)" class="nlnoc-avatar-img" alt="" />
                </UserAvatarStatus>
                <span class="nlnoc-conv-main">
                  <span class="nlnoc-conv-row1">
                    <span class="nlnoc-conv-name" :style="{ color: userNameColor(u) }">
                      {{ u.username }}
                    </span>
                    <span class="nlnoc-conv-time" v-if="u.user_tag">{{ u.user_tag }}</span>
                  </span>
                  <span class="nlnoc-conv-row2">
                    <span class="nlnoc-conv-preview">UID {{ u.user_number }}</span>
                  </span>
                </span>
                <i class="fa-solid fa-chevron-right nlnoc-conv-go"></i>
              </button>
            </div>
          </div>

          <!-- ===== 私信聊天页 ===== -->
          <NLNOCChat
            v-else-if="view === 'chat' && peer"
            key="chat"
            :peer="peer"
            @back="goHome"
            @sent="onChatSent"
            @peer-updated="onPeerUpdated"
          />

          <!-- ===== 群聊会话页 ===== -->
          <NLNOCGroup
            v-else-if="view === 'group' && activeGroupId"
            key="group"
            :conversation-id="activeGroupId"
            @back="goHome"
            @manage="openManage"
            @sent="onGroupSent"
          />

          <!-- ===== 创建群聊页 ===== -->
          <div v-else-if="view === 'group-new'" key="group-new" class="nlnoc-page">
            <div class="nlnoc-subhead">
              <button type="button" class="nlnoc-back" title="返回" @click="goHome">
                <i class="fa-solid fa-chevron-left"></i>
              </button>
              <div class="nlnoc-subtitle">创建群聊</div>
            </div>

            <div class="nlnoc-list nlnoc-form">
              <label class="nlnoc-form-label">群名称</label>
              <input
                v-model="cgTitle"
                class="nlnoc-form-input"
                type="text"
                maxlength="100"
                placeholder="给群组起个名字"
              />

              <label class="nlnoc-form-label">
                初始成员 <span class="nlnoc-form-hint">（可选，已选 {{ cgPicked.length }} 人）</span>
              </label>
              <div v-if="cgPicked.length" class="nlnoc-chips">
                <button
                  v-for="u in cgPicked"
                  :key="u.id"
                  type="button"
                  class="nlnoc-chip"
                  title="点击移除"
                  @click="cgTogglePick(u)"
                >
                  {{ u.username }} <i class="fa-solid fa-xmark"></i>
                </button>
              </div>

              <div class="nlnoc-searchbox nlnoc-form-search">
                <i class="fa-solid fa-magnifying-glass"></i>
                <input
                  v-model="cgQuery"
                  type="text"
                  placeholder="搜索 UID / 用户名"
                  maxlength="50"
                />
                <button
                  v-if="cgQuery"
                  type="button"
                  class="nlnoc-clear"
                  title="清空"
                  @click="cgQuery = ''"
                >
                  <i class="fa-solid fa-circle-xmark"></i>
                </button>
              </div>

              <div v-if="cgSearching" class="nlnoc-form-tip">
                <i class="fa-solid fa-spinner fa-spin"></i>
              </div>
              <div
                v-else-if="cgQuery.trim() && cgResults.length === 0"
                class="nlnoc-form-tip"
              >
                没有找到「{{ cgQuery.trim() }}」
              </div>
              <div v-else-if="!cgQuery.trim()" class="nlnoc-form-tip">
                搜索用户加入群聊
              </div>
              <button
                v-for="u in cgResults"
                :key="u.id"
                type="button"
                class="nlnoc-conv nlnoc-pick"
                :class="{ picked: cgPicked.some((x) => x.id === u.id) }"
                @click="cgTogglePick(u)"
              >
                <img :src="avatarOf(u)" class="nlnoc-avatar-img" alt="" />
                <span class="nlnoc-conv-main">
                  <span class="nlnoc-conv-row1">
                    <span class="nlnoc-conv-name" :style="{ color: userNameColor(u) }">
                      {{ u.username }}
                    </span>
                    <span class="nlnoc-conv-time" v-if="u.user_tag">{{ u.user_tag }}</span>
                  </span>
                  <span class="nlnoc-conv-row2">
                    <span class="nlnoc-conv-preview">UID {{ u.user_number }}</span>
                  </span>
                </span>
                <i
                  class="fa-solid nlnoc-pick-mark"
                  :class="cgPicked.some((x) => x.id === u.id) ? 'fa-circle-check' : 'fa-circle-plus'"
                ></i>
              </button>

              <div v-if="cgError" class="nlnoc-form-err">
                <i class="fa-solid fa-circle-exclamation"></i> {{ cgError }}
              </div>

              <button
                type="button"
                class="nlnoc-form-submit"
                :disabled="!cgTitle.trim() || cgCreating"
                @click="submitCreateGroup"
              >
                <i v-if="cgCreating" class="fa-solid fa-spinner fa-spin"></i>
                <i v-else class="fa-solid fa-user-group"></i>
                {{ cgCreating ? '创建中…' : '创建群聊' }}
              </button>
            </div>
          </div>

          <!-- ===== 群聊管理页（群会话页右上角进入） ===== -->
          <div v-else-if="view === 'group-manage'" key="group-manage" class="nlnoc-page">
            <div class="nlnoc-subhead">
              <button type="button" class="nlnoc-back" title="返回" @click="manageBack">
                <i class="fa-solid fa-chevron-left"></i>
              </button>
              <div class="nlnoc-subtitle">群聊管理</div>
            </div>

            <div class="nlnoc-list nlnoc-manage">
              <div v-if="mgError" class="nlnoc-form-err">
                <i class="fa-solid fa-circle-exclamation"></i> {{ mgError }}
              </div>
              <div v-if="mgNotice" class="nlnoc-form-ok">
                <i class="fa-solid fa-circle-check"></i> {{ mgNotice }}
              </div>
              <div v-if="!mgDetail && !mgError" class="nlnoc-empty">
                <i class="fa-solid fa-spinner fa-spin"></i>
              </div>

              <template v-if="mgDetail">
                <!-- 群设置（管理及以上）：群名 + 头像 URL -->
                <div v-if="mgCanManage" class="nlnoc-manage-card">
                  <div class="nlnoc-manage-label">群设置</div>
                  <div class="nlnoc-manage-row">
                    <input
                      v-model="mgTitle"
                      class="nlnoc-form-input"
                      type="text"
                      maxlength="100"
                      placeholder="未命名群组"
                    />
                    <button
                      type="button"
                      class="nlnoc-manage-btn"
                      :disabled="mgBusy || !mgTitle.trim() || (mgTitle.trim() === (mgDetail.title || '') && mgAvatar.trim() === (mgDetail.avatar_url || ''))"
                      @click="saveGroupSettings"
                    >
                      保存
                    </button>
                  </div>
                  <div class="nlnoc-manage-sublabel">群头像 URL</div>
                  <div class="nlnoc-manage-row">
                    <input
                      v-model="mgAvatar"
                      class="nlnoc-form-input"
                      type="url"
                      maxlength="500"
                      placeholder="https://example.com/avatar.png"
                    />
                    <span class="nlnoc-manage-ava">
                      <i class="fa-solid fa-user-group"></i>
                      <img
                        v-if="mgAvatar.trim()"
                        :src="mgAvatar.trim()"
                        class="nlnoc-ava-img"
                        alt=""
                        @error="onAvaError"
                      />
                    </span>
                  </div>
                  <div class="nlnoc-manage-hint">填图片链接，保存后群头像生效；留空恢复默认图标</div>
                </div>

                <!-- 邀请成员（管理及以上） -->
                <div v-if="mgCanManage" class="nlnoc-manage-card">
                  <div class="nlnoc-manage-label">邀请成员</div>
                  <div class="nlnoc-manage-row">
                    <input
                      v-model="mgInvite"
                      class="nlnoc-form-input"
                      type="text"
                      placeholder="UID，逗号 / 空格分隔"
                      @keydown.enter="inviteGroup"
                    />
                    <button
                      type="button"
                      class="nlnoc-manage-btn"
                      :disabled="mgBusy || !mgInvite.trim()"
                      @click="inviteGroup"
                    >
                      邀请
                    </button>
                  </div>
                </div>

                <!-- 成员列表 -->
                <div class="nlnoc-manage-card">
                  <div class="nlnoc-manage-label">
                    成员 <span class="nlnoc-form-hint">（{{ mgDetail.member_count }}）</span>
                  </div>
                  <div
                    v-for="m in mgDetail.members"
                    :key="m.user_id"
                    class="nlnoc-member"
                  >
                    <img :src="letterAvatar(m.username)" class="nlnoc-avatar-img" alt="" />
                    <span class="nlnoc-member-name">{{ m.username }}</span>
                    <span class="nlnoc-member-role" :class="'role-' + m.role">
                      {{ roleLabel(m.role) }}
                    </span>
                    <span class="nlnoc-member-acts">
                      <button
                        v-if="mgIsOwner && m.role !== 'owner'"
                        type="button"
                        class="nlnoc-manage-btn sm"
                        :disabled="mgBusy"
                        @click="toggleAdmin(m)"
                      >
                        {{ m.role === 'admin' ? '取消管理' : '设管理' }}
                      </button>
                      <!-- 自己且非群主：退出群聊；他人：移除 -->
                      <button
                        v-if="m.role !== 'owner' && (m.user_id === myId || mgCanManage)"
                        type="button"
                        class="nlnoc-manage-btn sm danger"
                        :disabled="mgBusy"
                        @click="removeOrLeave(m)"
                      >
                        {{ m.user_id === myId ? '退出群聊' : '移除' }}
                      </button>
                    </span>
                  </div>
                </div>

                <!-- 解散群聊（仅群主，不可逆） -->
                <div v-if="mgIsOwner && !mgDetail.dissolved" class="nlnoc-manage-card">
                  <div class="nlnoc-manage-label">危险操作</div>
                  <button
                    type="button"
                    class="nlnoc-manage-btn danger wide"
                    :disabled="mgBusy"
                    @click="dissolveGroup"
                  >
                    解散群聊
                  </button>
                  <div class="nlnoc-manage-hint">解散后不可恢复，历史消息保留，全员无法再发送</div>
                </div>
              </template>
            </div>
          </div>

          <!-- ===== 犇犇页（顶栏独立浮窗合并回来的入口） ===== -->
          <NLNOCBenben v-else key="benben" @back="goHome" />
        </Transition>
      </div>

      <!-- Home Indicator -->
      <div class="nlnoc-homebar" aria-hidden="true"><span></span></div>

      <!-- 右下角调整大小把手：拖动改宽高，双击恢复默认（手机端隐藏）。
           是 button，天然落在 DRAG_EXCLUDE 里，不会被当成拖机身 -->
      <button
        v-if="!compact"
        type="button"
        class="nlnoc-resize"
        :class="{ resizing }"
        title="拖动调整大小 · 双击恢复默认"
        aria-label="调整面板大小"
        @pointerdown="onResizeStart"
        @pointermove="onResizeMove"
        @pointerup="onResizeEnd"
        @pointercancel="onResizeEnd"
        @dblclick="onResizeReset"
      >
        <i class="fa-solid fa-expand"></i>
      </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
/* ===== 机身 ===== */
/* 锚定在信封正下方；拖动位移写在 anchor 的 transform 上，
   与 phone 自身开合动画的 transform 分层，互不覆盖 */
.nlnoc-anchor {
  position: absolute;
  top: calc(100% + 14px);
  right: -6px;
  z-index: 400;
}

.nlnoc-anchor.dragging {
  z-index: 410;
  user-select: none;
}

/* 状态栏是主要拖动把手；非交互区域按住也能拖（pointerdown 在模板上） */
.nlnoc-anchor .nlnoc-statusbar {
  cursor: grab;
}

.nlnoc-anchor.dragging .nlnoc-statusbar {
  cursor: grabbing;
}

.nlnoc-phone {
  position: relative;
  width: min(348px, calc(100vw - 24px));
  height: min(640px, calc(100vh - 130px));
  display: flex;
  flex-direction: column;
  padding: 9px;
  background: linear-gradient(160deg, #171a2b, #0d1020 60%);
  border-radius: 46px;
  box-shadow:
    0 28px 70px rgba(10, 12, 26, 0.42),
    0 4px 14px rgba(10, 12, 26, 0.24),
    inset 0 0 0 1.5px rgba(255, 255, 255, 0.14);
}

/* ===== 状态栏 ===== */
.nlnoc-statusbar {
  position: relative;
  flex: none;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  color: #eef1fa;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.nlnoc-island {
  position: absolute;
  left: 50%;
  top: 7px;
  transform: translateX(-50%);
  width: 96px;
  height: 26px;
  background: #05060d;
  border-radius: 999px;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.05);
}

.nlnoc-indicators {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 11.5px;
}

.nlnoc-batt {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.nlnoc-batt.low {
  color: #ff6b6b;
}

.nlnoc-batt-pct {
  font-size: 10.5px;
  opacity: 0.85;
}

/* ===== 屏幕 ===== */
.nlnoc-screen {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: linear-gradient(180deg, #f7f8fc 0%, #eef1f9 100%);
  border-radius: 36px;
}

.nlnoc-page {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* ===== 首页头部 ===== */
.nlnoc-head {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 16px 10px;
}

.nlnoc-brand {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.nlnoc-logo {
  font-size: 21px;
  font-weight: 800;
  letter-spacing: 0.06em;
  background: linear-gradient(120deg, var(--primary), var(--grad-violet) 70%, var(--grad-sky));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  line-height: 1.15;
}

.nlnoc-slogan {
  font-size: 10.5px;
  color: #98a1b8;
  letter-spacing: 0.24em;
  text-transform: uppercase;
}

/* 圆形控件统一 36×36：与搜索框高度、聊天页返回键/发送键同一规格 */
.nlnoc-round-btn {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 50%;
  background: var(--primary, #4a4ae0);
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 5px 14px color-mix(in srgb, var(--primary) 35%, transparent);
  transition: transform 0.15s, box-shadow 0.15s;
}

.nlnoc-round-btn:hover {
  transform: scale(1.08);
  box-shadow: 0 7px 18px color-mix(in srgb, var(--primary) 45%, transparent);
}

/* ===== 搜索页头部 ===== */
.nlnoc-subhead {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 12px 8px;
}

.nlnoc-back {
  flex: none;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 50%;
  background: rgba(15, 18, 32, 0.06);
  color: var(--text-strong);
  font-size: 13px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s;
}

.nlnoc-back:hover {
  background: rgba(15, 18, 32, 0.12);
}

.nlnoc-searchbox {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px; /* 9×2 + 文字 + 边框 ≈ 36，与返回键同高 */
  background: var(--surface-plain);
  border: 1px solid rgba(15, 18, 32, 0.08);
  border-radius: 12px;
  color: #98a1b8;
  font-size: 13px;
  box-shadow: 0 2px 8px rgba(15, 18, 32, 0.05);
}

.nlnoc-searchbox input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  font-size: 13.5px;
  color: var(--text-strong);
  font-family: inherit;
}

.nlnoc-clear {
  flex: none;
  width: 26px;
  height: 26px; /* 给清除键一个像样的点按靶（原来裸图标 padding:0） */
  border: none;
  background: none;
  padding: 0;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #b3bacd;
  cursor: pointer;
  font-size: 14px;
}

.nlnoc-clear:hover {
  color: var(--text-sub);
}

/* ===== 会话列表 ===== */
.nlnoc-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 2px 10px 16px;
  scrollbar-width: thin;
}

.nlnoc-list::-webkit-scrollbar {
  width: 4px;
}

.nlnoc-list::-webkit-scrollbar-thumb {
  background: rgba(15, 18, 32, 0.16);
  border-radius: 2px;
}

.nlnoc-conv {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 8px;
  border: none;
  border-radius: 14px;
  background: transparent;
  cursor: pointer;
  text-align: left;
  font-family: inherit;
  transition: background 0.15s;
}

.nlnoc-conv:hover {
  background: color-mix(in srgb, var(--primary) 7%, transparent);
}

.nlnoc-conv--broadcast {
  background: color-mix(in srgb, var(--primary) 5%, transparent);
  margin-bottom: 4px;
}

.nlnoc-conv--broadcast:hover {
  background: color-mix(in srgb, var(--primary) 10%, transparent);
}

.nlnoc-conv-avatar-wrap {
  flex: none;
  line-height: 0;
}

.nlnoc-avatar-img {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  object-fit: cover;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 1px 4px rgba(15, 18, 32, 0.16);
}

.nlnoc-conv-avatar {
  position: relative; /* 群头像 URL 图片叠在占位图标上 */
  flex: none;
  width: 42px;
  height: 42px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 16px;
}

.nlnoc-conv-avatar.benben {
  background: linear-gradient(135deg, var(--primary), var(--grad-violet));
  box-shadow: 0 3px 10px color-mix(in srgb, var(--primary) 35%, transparent);
}

.nlnoc-conv-name.broadcast {
  color: var(--primary);
}

.nlnoc-conv-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.nlnoc-conv-row1 {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.nlnoc-conv-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-strong);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nlnoc-conv-time {
  flex: none;
  font-size: 10.5px;
  color: #a3aabd;
}

.nlnoc-conv-row2 {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.nlnoc-conv-preview {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  color: var(--text-sub);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nlnoc-conv-badge {
  flex: none;
  min-width: 17px;
  height: 17px;
  padding: 0 5px;
  border-radius: 999px;
  background: #f43f5e;
  color: #fff;
  font-size: 10.5px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}

.nlnoc-conv-go {
  flex: none;
  font-size: 11px;
  color: #c2c8d8;
}

/* ===== 空状态 ===== */
.nlnoc-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 40px 20px;
  color: #a3aabd;
  font-size: 13px;
  text-align: center;
}

.nlnoc-empty i {
  font-size: 26px;
  color: #c2c9dc;
}

.nlnoc-empty p {
  margin: 0;
}

.nlnoc-empty-sub {
  font-size: 11.5px;
  color: #b0b7ca;
}

/* 列表加载失败的重试按钮 */
.nlnoc-retry {
  border: none;
  background: color-mix(in srgb, var(--primary) 10%, transparent);
  color: var(--primary);
  font-size: 12px;
  padding: 6px 16px;
  border-radius: 999px;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.15s;
}

.nlnoc-retry:hover {
  background: color-mix(in srgb, var(--primary) 18%, transparent);
}

/* ===== 底部 Home Indicator ===== */
.nlnoc-homebar {
  flex: none;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.nlnoc-homebar span {
  width: 112px;
  height: 5px;
  border-radius: 3px;
  background: rgba(238, 241, 250, 0.42);
}

/* ===== 动画 ===== */
.nlnoc-pop-enter-active {
  transition: transform 0.22s cubic-bezier(0.2, 0.9, 0.3, 1.25), opacity 0.18s ease;
}

.nlnoc-pop-leave-active {
  transition: transform 0.15s ease, opacity 0.15s ease;
}

.nlnoc-pop-enter-from,
.nlnoc-pop-leave-to {
  opacity: 0;
  transform: translateY(-10px) scale(0.96);
}

.nlnoc-slide-fwd-enter-active,
.nlnoc-slide-fwd-leave-active,
.nlnoc-slide-back-enter-active,
.nlnoc-slide-back-leave-active {
  transition: transform 0.22s ease, opacity 0.22s ease;
}

.nlnoc-slide-fwd-enter-from {
  transform: translateX(36px);
  opacity: 0;
}

.nlnoc-slide-fwd-leave-to {
  transform: translateX(-26px);
  opacity: 0;
}

.nlnoc-slide-back-enter-from {
  transform: translateX(-36px);
  opacity: 0;
}

.nlnoc-slide-back-leave-to {
  transform: translateX(26px);
  opacity: 0;
}/* ===== 「+」下拉：发起私信 / 创建群聊 ===== */
.nlnoc-plus-wrap {
  position: relative;
}

.nlnoc-plus-open {
  transform: rotate(45deg);
  transition: transform 0.16s ease;
}

.nlnoc-plus-menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: 30;
  min-width: 138px;
  padding: 6px;
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid rgba(15, 18, 32, 0.08);
  border-radius: 14px;
  box-shadow: 0 14px 34px rgba(10, 12, 26, 0.18);
  animation: nlnoc-menu-pop 0.14s ease;
}

@keyframes nlnoc-menu-pop {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

.nlnoc-plus-menu button {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 9px 11px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--text-strong);
  font-size: 13.5px;
  text-align: left;
  cursor: pointer;
}

.nlnoc-plus-menu button:hover {
  background: rgba(99, 102, 241, 0.1);
  color: #4f46e5;
}

.nlnoc-plus-menu button i {
  width: 15px;
  text-align: center;
  color: #6366f1;
}

/* ===== 首页列表：群聊条目头像 ===== */
.nlnoc-conv-avatar--group {
  background: linear-gradient(135deg, #eef2ff, #e0e7ff);
  color: #6366f1;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 群头像：占位图标打底，URL 图片叠在其上（加载失败自动露出图标） */
.nlnoc-conv-avatar-img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: inherit;
  display: block;
}

.nlnoc-manage-sublabel {
  margin-top: 9px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-sub);
}

.nlnoc-manage-ava {
  position: relative;
  flex: none;
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: color-mix(in srgb, var(--primary) 8%, transparent);
  color: #6366f1;
  font-size: 13px;
}

.nlnoc-ava-img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 50%;
  display: block;
}

.nlnoc-manage-hint {
  margin-top: 7px;
  font-size: 11.5px;
  line-height: 1.5;
  color: #98a1b8;
}

/* ===== 副标题页头（创建群聊 / 群聊管理） ===== */
.nlnoc-subtitle {
  flex: 1;
  font-size: 15.5px;
  font-weight: 700;
  color: var(--text-strong);
  text-align: center;
  padding-right: 44px; /* 左侧 36 返回键 + 8 间距，减掉即视觉居中 */
}

/* ===== 表单（创建群聊） ===== */
.nlnoc-form {
  padding: 14px 14px 20px;
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.nlnoc-form-label {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-sub);
  margin-top: 5px;
}

.nlnoc-form-hint {
  font-weight: 500;
  color: #98a0b8;
}

.nlnoc-form-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid rgba(15, 18, 32, 0.12);
  border-radius: 11px;
  background: var(--surface-plain);
  font-size: 14px;
  color: var(--text-strong);
  outline: none;
}

.nlnoc-form-input:focus {
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.14);
}

.nlnoc-form-search {
  margin-top: 2px;
}

.nlnoc-form-tip {
  font-size: 12.5px;
  color: #98a0b8;
  text-align: center;
  padding: 10px 0 4px;
}

.nlnoc-form-err {
  font-size: 13px;
  color: #e5484d;
  padding: 6px 2px;
}

.nlnoc-form-ok {
  font-size: 13px;
color: light-dark(#2f9e6e, #34d399);
  padding: 6px 2px;
}

.nlnoc-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.nlnoc-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border: 0;
  border-radius: 999px;
  background: rgba(99, 102, 241, 0.12);
  color: #4f46e5;
  font-size: 12.5px;
  cursor: pointer;
}

.nlnoc-chip:hover {
  background: rgba(229, 72, 77, 0.14);
  color: #e5484d;
}

/* 选人结果行：勾选态 */
.nlnoc-pick.picked {
  background: rgba(99, 102, 241, 0.07);
}

.nlnoc-pick-mark {
  margin-left: auto;
  font-size: 16px;
  color: #c3c9dc;
}

.nlnoc-pick.picked .nlnoc-pick-mark {
  color: #6366f1;
}

.nlnoc-form-submit {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 8px;
  padding: 12px;
  border: 0;
  border-radius: 13px;
  background: linear-gradient(135deg, #6366f1, #4f46e5);
  color: #fff;
  font-size: 14.5px;
  font-weight: 700;
  cursor: pointer;
}

.nlnoc-form-submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ===== 群聊管理 ===== */
.nlnoc-manage {
  padding: 14px 14px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.nlnoc-manage-card {
  background: var(--surface-plain);
  border: 1px solid rgba(15, 18, 32, 0.08);
  border-radius: 14px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.nlnoc-manage-label {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-sub);
}

.nlnoc-manage-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.nlnoc-manage-row .nlnoc-form-input {
  flex: 1;
  min-width: 0;
}

.nlnoc-manage-btn {
  flex: none;
  padding: 9px 14px;
  border: 0;
  border-radius: 10px;
  background: rgba(99, 102, 241, 0.12);
  color: #4f46e5;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.nlnoc-manage-btn:hover:not(:disabled) {
  background: rgba(99, 102, 241, 0.2);
}

.nlnoc-manage-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.nlnoc-manage-btn.sm {
  padding: 5px 10px;
  font-size: 12px;
  border-radius: 8px;
}

.nlnoc-manage-btn.danger {
  background: rgba(229, 72, 77, 0.12);
  color: #e5484d;
}

.nlnoc-manage-btn.danger.wide {
  width: 100%;
  justify-content: center;
}

.nlnoc-manage-btn.danger:hover:not(:disabled) {
  background: rgba(229, 72, 77, 0.2);
}

.nlnoc-member {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 7px 0;
  border-top: 1px solid rgba(15, 18, 32, 0.05);
  /* 名字+徽标+双按钮一行放不下时，操作按钮整体换到第二行右对齐 */
  flex-wrap: wrap;
}

.nlnoc-member:first-of-type {
  border-top: 0;
}

.nlnoc-member-name {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-strong);
  max-width: 78px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nlnoc-member-role {
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 999px;
  background: var(--bg-subtle);
  color: var(--text-sub);
}

.nlnoc-member-role.role-owner {
  background: rgba(245, 158, 11, 0.16);
color: light-dark(#b45309, #fbbf24);
}

.nlnoc-member-role.role-admin {
  background: rgba(99, 102, 241, 0.14);
  color: #4f46e5;
}

.nlnoc-member-acts {
  margin-left: auto;
  display: inline-flex;
  gap: 6px;
  row-gap: 4px;
}

/* ===== 右下角调整大小把手（桌面端；手机端媒体查询里隐藏） ===== */
.nlnoc-resize {
  position: absolute;
  right: 26px;
  bottom: 6px; /* 落在 Home Indicator 那条暗色边框带上，让开屏幕 */
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.14);
  color: rgba(238, 241, 250, 0.78);
  font-size: 11px;
  cursor: nwse-resize;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
  touch-action: none; /* 触屏拖把手不让页面抢走手势 */
  transition: background 0.15s, color 0.15s;
}

.nlnoc-resize:hover,
.nlnoc-resize.resizing {
  background: rgba(255, 255, 255, 0.28);
  color: #fff;
}

/* ===== 手机端（≤640px）：准全屏适配 ===== */
@media (max-width: 640px) {
  /* 宽 / 高 / 横向位置由 syncViewport 写内联——窄屏顶栏会换行，
     信封按钮的横坐标写死必错；样式侧只兜把手与字号 */
  .nlnoc-resize {
    display: none;
  }

  .nlnoc-searchbox input,
  .nlnoc-form-input {
    font-size: 16px; /* <16px 时 iOS 聚焦输入框会自动放大整页 */
  }
}
</style>
