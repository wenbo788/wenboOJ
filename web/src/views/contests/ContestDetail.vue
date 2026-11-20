<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { contestsApi, type ContestItem, type RankRow, type ContestTeamInfo, type ContestRatingItem, type VirtualContestState } from '@/api/contests'
import { difficultyColor } from '@/utils/difficulty'
import { userNameColor } from '@/utils/userColor'
import { renderRichText } from '@/utils/markdown'
import { fmtDateTime } from '@/utils/datetime'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const isLoggedIn = computed(() => authStore.isAuthenticated)
const currentUser = computed(() => authStore.currentUser)

const contestId = computed(() => parseInt(route.params.id as string, 10))
const contest = ref<ContestItem | null>(null)
const loading = ref(true)
const error = ref('')
const acting = ref(false)
const actionMsg = ref('')

// 队伍相关状态
const myTeam = ref<ContestTeamInfo | null>(null)
const teamsList = ref<ContestTeamInfo[]>([])
const loadingTeams = ref(false)

// 组队报名/建队弹窗
const showTeamModal = ref(false)
const teamModalTab = ref<'create' | 'join' | 'direct'>('create')
const newTeamName = ref('')
const newTeamInviteCode = ref('')
const joinInviteCode = ref('')
const teamActionLoading = ref(false)
const teamActionError = ref('')

// 队长直接添加队员
const addMemberInput = ref('')
const addingMember = ref(false)
const addMemberMsg = ref('')

// 选项卡由 hash 驱动：默认说明，#problem 题目列表，#scoreboard 排行榜，#team 参赛队伍
const TABS = computed(() => {
  const list = [
    { key: 'statement', label: '比赛说明' },
    { key: 'problem', label: '题目列表' },
    { key: 'scoreboard', label: '排行榜' },
  ]
  if (contest.value?.is_team_contest) {
    list.push({ key: 'team', label: '参赛队伍' })
  }
  return list
})
type TabKey = 'statement' | 'problem' | 'scoreboard' | 'team'

const activeTab = ref<TabKey>('statement')
const rankAliases = ref<string[]>([])
const rankRows = ref<RankRow[]>([])
const rankRuleType = ref<'xcpc' | 'acm' | 'ioi' | 'oi'>('xcpc')
const rankLoading = ref(false)
const rankDenied = ref(false)
const rankFrozen = ref(false)
const rankFrozenMsg = ref('')

// 等级分（is_rated 的比赛才有）
const ratingItems = ref<ContestRatingItem[]>([])

// ===== 虚拟参赛（镜像一场已结束的比赛，个人计时）=====
const virtualState = ref<VirtualContestState>({ active: false, virtual: null, results: [] })
const virtualRemaining = ref(0)
const virtualLoading = ref(false)
const virtualError = ref('')
let virtualTimer: ReturnType<typeof setInterval> | undefined

const virtualRemainingText = computed(() => {
  const t = Math.max(0, virtualRemaining.value)
  const h = Math.floor(t / 3600)
  const m = Math.floor((t % 3600) / 60)
  const sec = t % 60
  return [h, m, sec].map(v => String(v).padStart(2, '0')).join(':')
})

// 只有「已结束的个人赛」能开虚拟赛，且必须登录
const canStartVirtual = computed(() => {
  const c = contest.value
  if (!c || !isLoggedIn.value) return false
  return !c.is_team_contest && c.status === 'ended' && (c.visibility || 'public') === 'public'
})

async function loadVirtual() {
  if (!isLoggedIn.value || !contest.value) return
  try {
    const data = await contestsApi.getVirtualMe(contestId.value)
    virtualState.value = data
    virtualRemaining.value = data.virtual?.remaining_seconds ?? 0
    startVirtualTicking()
  } catch {
    // 未开始过 / 无权限都按「没有虚拟赛」处理
    virtualState.value = { active: false, virtual: null, results: [] }
    virtualRemaining.value = 0
  }
}

function startVirtualTicking() {
  if (virtualTimer) clearInterval(virtualTimer)
  if (!virtualState.value.active) return
  // 用服务端给的 ends_at 现算剩余秒数：本地 `-1` 会随标签页节流/卡顿累积漂移
  const deadline = Date.parse(virtualState.value.virtual?.ends_at || '')
  virtualTimer = setInterval(() => {
    if (Number.isFinite(deadline)) {
      virtualRemaining.value = Math.max(0, Math.round((deadline - Date.now()) / 1000))
    } else if (virtualRemaining.value > 0) {
      virtualRemaining.value -= 1
    }
    if (virtualRemaining.value <= 0) {
      if (virtualTimer) {
        clearInterval(virtualTimer)
        virtualTimer = undefined
        loadVirtual()   // 到点了：刷新成「已结束」
      }
    }
  }, 1000)
}

async function startVirtual() {
  virtualLoading.value = true
  virtualError.value = ''
  try {
    await contestsApi.startVirtual(contestId.value)
    await loadVirtual()
  } catch (e: any) {
    virtualError.value = e?.response?.data?.detail || '开始虚拟参赛失败'
  } finally {
    virtualLoading.value = false
  }
}

async function finishVirtual() {
  if (!window.confirm('提前结束虚拟参赛？结束后这场比赛就不能再按虚拟赛提交了。')) return
  virtualLoading.value = true
  virtualError.value = ''
  try {
    await contestsApi.finishVirtual(contestId.value)
    await loadVirtual()
  } catch (e: any) {
    virtualError.value = e?.response?.data?.detail || '结束虚拟参赛失败'
  } finally {
    virtualLoading.value = false
  }
}
const ratingSettled = ref(false)
const ratingLoading = ref(false)
const ratingError = ref('')

async function loadRating() {
  if (!contest.value?.is_rated) return
  try {
    const data = await contestsApi.getRating(Number(contestId.value))
    ratingItems.value = data?.items ?? []
    ratingSettled.value = !!data?.settled
  } catch {
    // 未结算/无权查看都按「空」处理，不打扰用户
    ratingItems.value = []
    ratingSettled.value = false
  }
}

async function settleRating() {
  ratingLoading.value = true
  ratingError.value = ''
  try {
    const data = await contestsApi.settleRating(Number(contestId.value))
    ratingItems.value = data?.items ?? []
    ratingSettled.value = true
  } catch (e: any) {
    ratingError.value = e?.response?.data?.detail || '结算失败'
  } finally {
    ratingLoading.value = false
  }
}

const RULE_TYPE_LABEL: Record<string, string> = {
  xcpc: 'XCPC 赛制',
  acm: 'XCPC 赛制',
  ioi: 'IOI 赛制',
  oi: 'OI 赛制',
}

const descriptionHtml = computed(() =>
  contest.value ? renderRichText(contest.value.description || '') : '')

const syncTabFromHash = () => {
  const h = (route.hash || '').replace('#', '')
  activeTab.value = (TABS.value.some(t => t.key === h) ? h : 'statement') as TabKey
  if (activeTab.value === 'scoreboard' && rankRows.value.length === 0 && !rankLoading.value) {
    loadRank()
    loadRating()
    loadVirtual()
  }
  if (activeTab.value === 'team') {
    loadTeams()
  }
}

const switchTab = (key: TabKey) => {
  if (route.hash === `#${key}`) { syncTabFromHash(); return }
  router.push({ hash: `#${key}` })
}

const loadTeams = async () => {
  if (!contest.value?.is_team_contest) return
  loadingTeams.value = true
  try {
    teamsList.value = await contestsApi.getTeams(contestId.value)
  } catch {
    teamsList.value = []
  } finally {
    loadingTeams.value = false
  }
}

const load = async () => {
  if (!Number.isFinite(contestId.value)) {
    error.value = '无效的比赛 ID'
    loading.value = false
    return
  }
  loading.value = true
  let success = false
  try {
    const data = await contestsApi.get(contestId.value)
    contest.value = data
    myTeam.value = data.my_team || null
    error.value = ''
    if (data.is_team_contest) {
      if (data.is_participant && !myTeam.value) {
        try {
          myTeam.value = await contestsApi.getMyTeam(contestId.value)
        } catch {
          myTeam.value = null
        }
      }
      loadTeams()
    }
    syncTabFromHash()
    success = true
  } catch (err: any) {
    error.value = err.response?.data?.detail || err.message || '加载失败'
    contest.value = null
    scheduleRetry()
  } finally {
    loading.value = false
    if (success) scheduleStatusRefresh()
  }
}

const RETRY_DELAY_MS = 5000
watch(contestId, load)
watch(() => route.hash, syncTabFromHash)
onMounted(() => { load() })
onUnmounted(() => { if (virtualTimer) clearInterval(virtualTimer) })

let statusTimer: ReturnType<typeof setTimeout> | undefined
const clearStatusTimer = () => {
  if (statusTimer !== undefined) {
    clearTimeout(statusTimer)
    statusTimer = undefined
  }
}
const MIN_REFRESH_GAP_MS = 5000
let lastStatusRefreshAt = 0

const scheduleStatusRefresh = () => {
  clearStatusTimer()
  const c = contest.value
  if (!c || c.status === 'ended') return
  const targetIso = c.status === 'pending' ? c.start_time : c.end_time
  if (!targetIso) return
  const delay = new Date(targetIso).getTime() - Date.now()
  if (delay <= 0) {
    const elapsed = Date.now() - lastStatusRefreshAt
    const wait = Math.max(0, delay + 1500, MIN_REFRESH_GAP_MS - elapsed)
    lastStatusRefreshAt = Date.now()
    statusTimer = setTimeout(() => load(), wait)
    return
  }
  lastStatusRefreshAt = Date.now()
  statusTimer = setTimeout(() => load(), delay + 1500)
}

function scheduleRetry() {
  clearStatusTimer()
  statusTimer = setTimeout(() => load(), RETRY_DELAY_MS)
}
onUnmounted(clearStatusTimer)

const loadRank = async () => {
  rankLoading.value = true
  rankDenied.value = false
  rankFrozen.value = false
  try {
    const data = await contestsApi.rank(contestId.value)
    rankAliases.value = data.aliases
    rankRows.value = data.rows
    rankRuleType.value = (data.rule_type as any) || 'xcpc'
    rankFrozen.value = !!data.is_frozen
    rankFrozenMsg.value = data.message || 'OI 赛制比赛进行中，排行榜暂不公开，比赛结束后统一揭晓'
  } catch (err: any) {
    rankDenied.value = true
  } finally {
    rankLoading.value = false
  }
}

const STATUS: Record<string, { text: string; cls: string }> = {
  running: { text: '进行中', cls: 'running' },
  pending: { text: '未开始', cls: 'pending' },
  ended: { text: '已结束', cls: 'ended' },
}
const fmt = (iso: string | null) => fmtDateTime(iso, '—')

// 个人赛报名
const doRegister = async () => {
  let inviteCode: string | undefined
  if (contest.value?.visibility === 'private' || contest.value?.visibility === 'team_private') {
    inviteCode = window.prompt('这是一场邀请赛，请输入邀请码：') || ''
    if (!inviteCode) return
  }
  acting.value = true
  actionMsg.value = ''
  try {
    await contestsApi.register(contestId.value, inviteCode)
    actionMsg.value = '报名成功'
    await load()
  } catch (err: any) {
    actionMsg.value = err.response?.data?.detail || '报名失败'
  } finally {
    acting.value = false
  }
}

// 组队赛：打开报名/组队弹窗
const openTeamModal = (tab: 'create' | 'join' | 'direct' = 'create') => {
  teamModalTab.value = tab
  teamActionError.value = ''
  showTeamModal.value = true
}

// 组队赛：创建队伍
const handleCreateTeam = async () => {
  const name = newTeamName.value.trim()
  if (!name) {
    teamActionError.value = '请输入队伍名称'
    return
  }
  let contestCode: string | undefined
  if (contest.value?.visibility === 'private' || contest.value?.visibility === 'team_private') {
    contestCode = window.prompt('这是一场邀请赛，请输入比赛邀请码：') || ''
    if (!contestCode) return
  }
  teamActionLoading.value = true
  teamActionError.value = ''
  try {
    await contestsApi.createTeam(contestId.value, {
      name,
      team_invite_code: newTeamInviteCode.value.trim() || undefined,
      contest_invite_code: contestCode,
    })
    showTeamModal.value = false
    newTeamName.value = ''
    newTeamInviteCode.value = ''
    actionMsg.value = `队伍「${name}」创建成功！`
    await load()
  } catch (err: any) {
    teamActionError.value = err.response?.data?.detail || err.message || '创建队伍失败'
  } finally {
    teamActionLoading.value = false
  }
}

// 组队赛：凭口令加入队伍
const handleJoinTeam = async (codeOverride?: string) => {
  const code = (codeOverride || joinInviteCode.value).trim()
  if (!code) {
    teamActionError.value = '请输入队伍邀请口令'
    return
  }
  let contestCode: string | undefined
  if (contest.value?.visibility === 'private' || contest.value?.visibility === 'team_private') {
    contestCode = window.prompt('这是一场邀请赛，请输入比赛邀请码：') || ''
    if (!contestCode) return
  }
  teamActionLoading.value = true
  teamActionError.value = ''
  try {
    const res = await contestsApi.joinTeam(contestId.value, {
      invite_code: code,
      contest_invite_code: contestCode,
    })
    showTeamModal.value = false
    joinInviteCode.value = ''
    actionMsg.value = `成功加入队伍「${res.name}」！`
    await load()
  } catch (err: any) {
    teamActionError.value = err.response?.data?.detail || err.message || '加入队伍失败'
  } finally {
    teamActionLoading.value = false
  }
}

// 组队赛：直接报名（稍后组队）
const handleDirectRegister = async () => {
  let contestCode: string | undefined
  if (contest.value?.visibility === 'private' || contest.value?.visibility === 'team_private') {
    contestCode = window.prompt('这是一场邀请赛，请输入比赛邀请码：') || ''
    if (!contestCode) return
  }
  teamActionLoading.value = true
  teamActionError.value = ''
  try {
    await contestsApi.register(contestId.value, contestCode)
    showTeamModal.value = false
    actionMsg.value = '报名成功，请创建或加入一支队伍开始比赛！'
    await load()
  } catch (err: any) {
    teamActionError.value = err.response?.data?.detail || err.message || '报名失败'
  } finally {
    teamActionLoading.value = false
  }
}

// 队长直接添加队员
const handleAddMember = async () => {
  if (!addMemberInput.value.trim() || !myTeam.value) return
  addingMember.value = true
  addMemberMsg.value = ''
  try {
    const res = await contestsApi.addTeamMember(contestId.value, myTeam.value.id, addMemberInput.value.trim())
    addMemberMsg.value = `已添加队员「${res.added_user}」`
    addMemberInput.value = ''
    await load()
  } catch (err: any) {
    addMemberMsg.value = err.response?.data?.detail || err.message || '添加失败'
  } finally {
    addingMember.value = false
  }
}

// 队长移出队员
const handleKickMember = async (memberId: number, memberName: string) => {
  if (!myTeam.value) return
  if (!confirm(`确定将队员「${memberName}」移出队伍吗？`)) return
  try {
    await contestsApi.kickTeamMember(contestId.value, myTeam.value.id, memberId)
    actionMsg.value = `已移出队员「${memberName}」`
    await load()
  } catch (err: any) {
    alert(err.response?.data?.detail || err.message || '操作失败')
  }
}

// 退出或解散队伍
const handleLeaveTeam = async () => {
  if (!myTeam.value) return
  const isLeader = myTeam.value.is_leader
  const hasOthers = myTeam.value.members.length > 1
  const tip = isLeader
    ? (hasOthers ? '确定退出队伍吗？队长将自动移交给下一位队员。' : '确定解散队伍并退出比赛报名吗？')
    : '确定退出该队伍吗？'
  if (!confirm(tip)) return
  try {
    await contestsApi.leaveTeam(contestId.value)
    actionMsg.value = isLeader && !hasOthers ? '队伍已解散' : '已退出队伍'
    await load()
  } catch (err: any) {
    alert(err.response?.data?.detail || err.message || '退出失败')
  }
}

// 复制口令
const copyInviteCode = (code: string) => {
  navigator.clipboard.writeText(code)
  alert(`口令 ${code} 已复制到剪贴板！`)
}

const doDelete = async () => {
  if (!contest.value) return
  if (!confirm(`确定删除比赛「${contest.value.title}」吗？此操作不可恢复。`)) return
  acting.value = true
  try {
    await contestsApi.remove(contestId.value)
    router.push('/contests')
  } catch (err: any) {
    actionMsg.value = err.response?.data?.detail || '删除失败'
    acting.value = false
  }
}

const openProblem = (pid: number) => {
  if (!contest.value) return
  router.push(`/problems/${pid}?contest=${contest.value.id}`)
}

const canViewProblems = computed(() => {
  if (!contest.value) return false
  if (contest.value.status === 'pending') return false
  if (contest.value.status === 'ended') return true
  return !!contest.value.can_view_problems
})
const denied = computed(() =>
  (activeTab.value === 'problem' || activeTab.value === 'scoreboard')
  && !!contest.value && !canViewProblems.value)

const userColor = (u: Record<string, any>) => userNameColor(u)
</script>

<template>
  <div class="contest-detail-page">
    <div class="contest-detail-container">
      <div class="back-link">
        <a @click.prevent="router.push('/contests')" href="#">← 返回比赛列表</a>
      </div>

      <div v-if="loading" class="empty">加载中...</div>
      <div v-else-if="error" class="empty">{{ error }}</div>

      <template v-else-if="contest">
        <!-- 头部卡：标题 + 统计 + 选项卡 -->
        <div class="card head-card">
          <div class="head-top">
            <div class="title-row">
              <h1>{{ contest.title }}</h1>
              <span class="status-badge" :class="STATUS[contest.status].cls">{{ STATUS[contest.status].text }}</span>
              <span v-if="contest.is_team_contest" class="team-contest-badge">
                <i class="fa-solid fa-users"></i> 组队赛 ({{ contest.max_team_members || 3 }}人)
              </span>
              <span
                v-if="contest.hide_submissions_from_admin"
                class="shield-badge"
                title="已开启管理员参赛保护：赛中对非举办方管理员隐藏他人提交与代码，管理员可公平参赛"
              >
                <i class="fa-solid fa-shield-halved" /> 管理员参赛保护
              </span>
            </div>
            <div class="head-stats">
              <div class="stat">
                <div class="stat-label">题数</div>
                <div class="stat-value">{{ contest.problem_count }}</div>
              </div>
              <div class="stat">
                <div class="stat-label">参赛人数</div>
                <div class="stat-value">{{ contest.participant_count }}</div>
              </div>
              <div v-if="contest.is_team_contest" class="stat">
                <div class="stat-label">参赛队伍</div>
                <div class="stat-value">{{ contest.team_count ?? teamsList.length }}</div>
              </div>
            </div>
          </div>
          <div class="tab-row">
            <div class="setting-nav">
              <span
                v-for="t in TABS"
                :key="t.key"
                class="nav-btn"
                :class="{
                  active: activeTab === t.key,
                  locked: t.key !== 'statement' && !canViewProblems
                }"
                @click="switchTab(t.key as TabKey)"
              >
                {{ t.label }}
                <i
                  v-if="t.key !== 'statement' && !canViewProblems"
                  class="fa-solid fa-lock lock-ico"
                />
              </span>
            </div>
            <div class="head-actions">
              <button
                v-if="contest.can_edit || contest.is_owner || contest.can_manage"
                class="btn-secondary"
                @click="router.push(`/contest/${contest.id}/edit`)"
              >编辑比赛</button>
              <button
                v-if="contest.can_edit || contest.is_owner || contest.can_manage"
                class="btn-danger"
                :disabled="acting"
                @click="doDelete"
              >删除比赛</button>
              <template v-if="isLoggedIn">
                <!-- 非组队赛报名 -->
                <template v-if="!contest.is_team_contest">
                  <button
                    v-if="!contest.is_participant && contest.status !== 'ended'"
                    class="btn-primary"
                    :disabled="acting"
                    @click="doRegister"
                  >{{ acting ? '处理中...' : '报名比赛' }}</button>
                  <span v-else-if="contest.is_participant" class="joined-tag"><i class="fa-solid fa-circle-check"></i> 已报名</span>
                </template>

                <!-- 组队赛：报名与队伍状态 -->
                <template v-else>
                  <template v-if="!contest.is_participant && contest.status !== 'ended'">
                    <button class="btn-primary" @click="openTeamModal('create')">
                      <i class="fa-solid fa-users"></i> 组队报名
                    </button>
                  </template>
                  <template v-else-if="contest.is_participant">
                    <span v-if="myTeam" class="joined-tag team-tag">
                      <i class="fa-solid fa-users"></i> 我的队伍：<b>{{ myTeam.name }}</b>
                    </span>
                    <button v-else-if="contest.status !== 'ended'" class="btn-primary btn-sm" @click="openTeamModal('create')">
                      <i class="fa-solid fa-plus"></i> 创建/加入队伍
                    </button>
                  </template>
                </template>
              </template>
            </div>
          </div>
        </div>

        <div v-if="actionMsg" class="action-msg">{{ actionMsg }}</div>

        <!-- 无权访问题目/排行榜 -->
        <div v-if="denied" class="card body-card denied-card">
          <i class="fa-solid fa-lock denied-ico"></i>
          <div class="denied-text">你无权进行此操作</div>
          <div class="denied-sub">
            {{ contest.status === 'pending'
              ? '比赛尚未开始，开始并报名后即可查看题目与排行榜'
              : '报名比赛后即可查看题目与排行榜' }}
          </div>
        </div>

        <!-- 比赛说明 -->
        <div v-else-if="activeTab === 'statement'" class="detail-grid">
          <div class="statement-main">
            <!-- 组队赛且用户在队伍中：置顶展示我的队伍卡片 -->
            <div v-if="contest.is_team_contest && myTeam" class="card my-team-card">
              <div class="team-card-head">
                <div class="team-title-row">
                  <span class="team-badge-icon"><i class="fa-solid fa-users"></i></span>
                  <h3 class="team-title">{{ myTeam.name }}</h3>
                  <span v-if="myTeam.is_leader" class="leader-pill"><i class="fa-solid fa-crown"></i> 队长</span>
                  <span class="team-capacity">{{ myTeam.members.length }} / {{ contest.max_team_members || 3 }} 人</span>
                </div>
                <div class="team-card-actions">
                  <button v-if="myTeam.invite_code" class="btn-code" @click="copyInviteCode(myTeam.invite_code)">
                    <i class="fa-solid fa-key"></i> 口令：<b>{{ myTeam.invite_code }}</b> <i class="fa-regular fa-copy"></i>
                  </button>
                  <button class="btn-text-danger" @click="handleLeaveTeam">
                    {{ myTeam.is_leader && myTeam.members.length === 1 ? '解散队伍' : '退出队伍' }}
                  </button>
                </div>
              </div>

              <!-- 队员列表 -->
              <div class="team-members-grid">
                <div v-for="m in myTeam.members" :key="m.user_id" class="member-chip">
                  <span v-if="m.user_id === myTeam.leader_id" class="chip-crown">👑</span>
                  <router-link :to="`/user/${m.user_number}`" class="member-name" :style="{ color: userColor(m) }">
                    {{ m.username }}
                  </router-link>
                  <span v-if="m.user_number" class="member-uid">#{{ m.user_number }}</span>
                  <button
                    v-if="myTeam.is_leader && m.user_id !== myTeam.leader_id && contest.status !== 'ended'"
                    class="kick-btn"
                    title="移出队员"
                    @click="handleKickMember(m.user_id!, m.username)"
                  >
                    <i class="fa-solid fa-xmark"></i>
                  </button>
                </div>
              </div>

              <!-- 队长快捷添加队友 -->
              <div
                v-if="myTeam.is_leader && myTeam.members.length < (contest.max_team_members || 3) && contest.status !== 'ended'"
                class="add-member-bar"
              >
                <input
                  v-model="addMemberInput"
                  class="form-input form-input-sm"
                  placeholder="输入队友的用户名或 UID 直拉入队..."
                  @keydown.enter.prevent="handleAddMember"
                />
                <button
                  class="btn-secondary btn-sm"
                  :disabled="addingMember || !addMemberInput.trim()"
                  @click="handleAddMember"
                >
                  {{ addingMember ? '添加中...' : '添加队员' }}
                </button>
                <span v-if="addMemberMsg" class="member-add-tip">{{ addMemberMsg }}</span>
              </div>
            </div>

            <!-- 组队赛且用户报名但尚未入队：温馨提示卡片 -->
            <div v-else-if="contest.is_team_contest && contest.is_participant && !myTeam && contest.status !== 'ended'" class="card my-team-card pending-team-card">
              <div class="pending-team-inner">
                <i class="fa-solid fa-triangle-exclamation warn-ico"></i>
                <div class="pending-team-text">
                  <b>你已报名本场比赛，但尚未加入任何队伍！</b>
                  <p>组队赛必须以队伍身份提交代码；请立即创建新队伍或凭口令加入队伍。</p>
                </div>
                <div class="pending-team-btns">
                  <button class="btn-primary btn-sm" @click="openTeamModal('create')">创建队伍</button>
                  <button class="btn-secondary btn-sm" @click="openTeamModal('join')">加入队伍</button>
                </div>
              </div>
            </div>

            <div class="card body-card statement-card">
              <h4 class="section-title">比赛介绍</h4>
              <div v-if="contest.description" class="prose statement-body" v-html="descriptionHtml" />
              <div v-else class="empty small">主办方没有填写比赛说明</div>
            </div>
          </div>

          <div class="side-col">
            <div class="card side-card">
              <div v-if="contest.status === 'running'" class="side-tip running-tip">比赛正在进行中</div>
              <div v-else-if="contest.status === 'ended'" class="side-tip ended-tip">比赛已经结束了</div>
              <div v-else class="side-tip pending-tip">比赛尚未开始</div>
              <div class="side-rows">
                <div class="side-row"><span>比赛编号</span><b>{{ contest.id }}</b></div>
                <div class="side-row"><span>举办者</span>
                  <router-link
                    v-if="contest.owner.user_number"
                    :to="`/user/${contest.owner.user_number}`"
                    class="owner-link"
                  >{{ contest.owner.username }}</router-link>
                  <span v-else class="owner-link">{{ contest.owner.username }}</span>
                </div>
                <div class="side-row"><span>比赛类型</span>
                  <b>{{ contest.type_label }} · {{ RULE_TYPE_LABEL[contest.rule_type] || 'XCPC 赛制' }}</b>
                </div>
                <div v-if="contest.team_name" class="side-row"><span>举办团队</span>
                  <b>{{ contest.team_name }}</b>
                </div>
                <div v-if="contest.is_team_contest" class="side-row"><span>赛制模式</span>
                  <b style="color: #722ed1;"><i class="fa-solid fa-users"></i> 组队赛 (≤{{ contest.max_team_members || 3 }}人)</b>
                </div>
                <div class="side-row"><span>开始时间</span><b>{{ fmt(contest.start_time) }}</b></div>
                <div class="side-row"><span>结束时间</span><b>{{ fmt(contest.end_time) }}</b></div>
                <div v-if="contest.hide_submissions_from_admin" class="side-row"><span>管理员参赛</span>
                  <b style="color: var(--primary);">已开启保护</b>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 题目列表 -->
        <div v-else-if="activeTab === 'problem'" class="card body-card">
          <h4 class="section-title">题目列表 <span class="member-count">（{{ contest.problems?.length || 0 }} 道）</span></h4>
          <div v-if="contest.status === 'running' && contest.is_participant" class="hint-bar">
            比赛进行中——从比赛页进入题目并提交，提交会计入比赛成绩{{ contest.is_team_contest ? '（组队成绩全队共享）' : '' }}
          </div>
          <div v-if="contest.problems && contest.problems.length" class="cp-list">
            <div
              v-for="p in contest.problems"
              :key="p.problem_id"
              class="cp-item"
              @click="openProblem(p.problem_id)"
            >
              <span class="cp-alias">{{ p.alias }}</span>
              <span class="cp-title">{{ p.title }}</span>
              <span class="diff-badge" :style="{ background: difficultyColor(p.difficulty) }">{{ p.difficulty }}</span>
            </div>
          </div>
          <div v-else class="empty small">比赛暂未配置题目</div>
          <div v-if="contest.status === 'running' && !contest.is_participant" class="hint-bar warn">
            你尚未报名，报名后提交才会计入比赛成绩
          </div>
        </div>

        <!-- 排行榜 -->
        <div v-else-if="activeTab === 'scoreboard'" class="card body-card">
          <div class="rank-header-row">
            <h4 class="section-title">
              排行榜
              <span class="member-count">（{{ rankRows.length }} {{ contest.is_team_contest ? '支队伍' : '人' }}）</span>
            </h4>
            <div class="rank-badges">
              <span v-if="contest.is_team_contest" class="team-contest-badge"><i class="fa-solid fa-users"></i> 组队榜</span>
              <span class="rule-hint-pill">{{ RULE_TYPE_LABEL[rankRuleType] || 'XCPC 赛制' }}</span>
            </div>
          </div>

          <div v-if="rankLoading" class="empty small">加载中...</div>
          <div v-else-if="rankFrozen" class="frozen-card">
            <div class="frozen-icon"><i class="fa-solid fa-lock"></i></div>
            <div class="frozen-title">OI 赛制进行中</div>
            <div class="frozen-desc">{{ rankFrozenMsg }}</div>
          </div>
          <div v-else-if="rankDenied" class="empty small">你无权查看排行榜</div>
          <div v-else-if="rankRows.length === 0" class="empty small">还没有人报名或暂无有效成绩</div>
          <div v-else class="rank-wrap">
            <table class="rank-table">
              <thead>
                <tr>
                  <th class="col-rank">排名</th>
                  <th class="col-user">{{ contest.is_team_contest ? '队伍 / 成员' : '选手' }}</th>
                  <template v-if="rankRuleType === 'xcpc' || rankRuleType === 'acm'">
                    <th class="col-solved">通过数</th>
                    <th class="col-penalty">总罚时</th>
                  </template>
                  <template v-else>
                    <th class="col-solved">总分</th>
                    <th class="col-penalty">通过题数</th>
                  </template>
                  <th v-for="a in rankAliases" :key="a" class="col-prob">{{ a }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in rankRows" :key="r.team ? `t-${r.team.id}` : `u-${r.user?.user_id}`">
                  <td class="col-rank">{{ r.rank }}</td>
                  <td class="col-user">
                    <!-- 组队赛：队伍名称与成员名单 -->
                    <template v-if="r.team">
                      <div class="rank-team-cell">
                        <div class="rank-team-name">
                          <i class="fa-solid fa-users"></i>
                          <span>{{ r.team.name }}</span>
                        </div>
                        <div class="rank-team-members">
                          <span v-for="m in r.team.members" :key="m.user_id" class="rank-member-tag">
                            <span v-if="m.user_id === r.team.leader_id" class="crown">👑</span>
                            <router-link :to="`/user/${m.user_number}`" class="u-link" :style="{ color: userColor(m) }">
                              {{ m.username }}
                            </router-link>
                          </span>
                        </div>
                      </div>
                    </template>
                    <!-- 个人赛：单一选手 -->
                    <template v-else-if="r.user">
                      <router-link :to="`/user/${r.user.user_number}`" class="u-link" :style="{ color: userColor(r.user) }">
                        {{ r.user.username }}
                      </router-link>
                    </template>
                  </td>
                  <template v-if="rankRuleType === 'xcpc' || rankRuleType === 'acm'">
                    <td class="col-solved font-bold">{{ r.solved }}</td>
                    <td class="col-penalty">{{ r.penalty }}</td>
                  </template>
                  <template v-else>
                    <td class="col-solved font-bold">{{ r.total_score }}</td>
                    <td class="col-penalty">{{ r.solved }}</td>
                  </template>
                  <td v-for="a in rankAliases" :key="a" class="col-prob">
                    <template v-if="rankRuleType === 'xcpc' || rankRuleType === 'acm'">
                      <template v-if="r.detail[a]?.solved">
                        <span class="cell solved" :class="{ fb: r.detail[a]?.first_solved }">
                          {{ r.detail[a].minutes }}′
                          <em v-if="r.detail[a].tries">({{ r.detail[a].tries }})</em>
                        </span>
                      </template>
                      <span v-else-if="r.detail[a]?.tries" class="cell tried">-{{ r.detail[a].tries }}</span>
                      <span v-else class="cell none">·</span>
                    </template>
                    <template v-else>
                      <span v-if="r.detail[a]?.score === 100" class="cell solved">100</span>
                      <span v-else-if="r.detail[a]?.score > 0" class="cell partial">{{ r.detail[a].score }}</span>
                      <span v-else-if="r.detail[a]?.tries" class="cell tried">0</span>
                      <span v-else class="cell none">·</span>
                    </template>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 虚拟参赛：镜像一场已结束的比赛，个人计时 -->
          <div v-if="isLoggedIn && canStartVirtual" class="virtual-panel">
            <div v-if="virtualState.active" class="virtual-active">
              <div class="virtual-timer">
                <i class="fa-solid fa-stopwatch"></i>
                虚拟参赛进行中，剩余 <b>{{ virtualRemainingText }}</b>
              </div>
              <button class="btn-settle" :disabled="virtualLoading" @click="finishVirtual">提前结束</button>
            </div>
            <div v-else class="virtual-idle">
              <span class="hint">把这场比赛镜像出来自己再打一遍：题目与时长照抄原赛，成绩只算你自己的，不进原赛榜。</span>
              <button class="btn-settle" :disabled="virtualLoading || !canStartVirtual" @click="startVirtual">
                {{ virtualLoading ? '处理中…' : '开始虚拟参赛' }}
              </button>
            </div>
            <p v-if="virtualError" class="rating-error">{{ virtualError }}</p>

            <table v-if="virtualState.active && virtualState.results.length" class="rank-table rating-table">
              <thead>
                <tr>
                  <th>题目</th>
                  <th>状态</th>
                  <th>最高分</th>
                  <th>提交次数</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(r, i) in virtualState.results" :key="r.problem_id">
                  <td>{{ rankAliases[i] || `#${r.problem_id}` }}</td>
                  <td :class="r.solved ? 'delta-up' : ''">{{ r.solved ? '已通过' : '未通过' }}</td>
                  <td>{{ r.best_score }}</td>
                  <td>{{ r.attempts }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 等级分变化（仅 is_rated 的个人赛；结算后可见） -->
          <div v-if="contest.is_rated" class="rating-panel">
            <div class="rating-head">
              <h4 class="section-title">
                等级分变化
                <span class="member-count">（{{ ratingSettled ? `${ratingItems.length} 人已结算` : '待结算' }}）</span>
              </h4>
              <button
                v-if="contest.can_edit && !ratingSettled"
                class="btn-settle"
                :disabled="ratingLoading"
                @click="settleRating"
              >{{ ratingLoading ? '结算中…' : '结算等级分' }}</button>
            </div>
            <p v-if="ratingError" class="rating-error">{{ ratingError }}</p>
            <table v-if="ratingItems.length" class="rank-table rating-table">
              <thead>
                <tr>
                  <th class="col-rank">名次</th>
                  <th class="col-user">选手</th>
                  <th>赛前</th>
                  <th>赛后</th>
                  <th>变化</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in ratingItems" :key="r.user_id">
                  <td class="col-rank">{{ r.rank }}</td>
                  <td class="col-user">{{ r.username }}<span class="member-count"> #{{ r.user_number }}</span></td>
                  <td>{{ r.rating_before }}</td>
                  <td>{{ r.rating_after }}</td>
                  <td :class="r.delta >= 0 ? 'delta-up' : 'delta-down'">
                    {{ r.delta > 0 ? '+' : '' }}{{ r.delta }}
                  </td>
                </tr>
              </tbody>
            </table>
            <p v-else-if="!ratingSettled" class="empty small">
              比赛结束后由管理员结算；只结算「至少提交过一次」的参赛者。
            </p>
          </div>
        </div>

        <!-- 参赛队伍列表（仅组队赛） -->
        <div v-else-if="activeTab === 'team'" class="card body-card">
          <div class="team-tab-head">
            <h4 class="section-title">参赛队伍 <span class="member-count">（{{ teamsList.length }} 支队伍）</span></h4>
            <div v-if="isLoggedIn && !myTeam && contest.status !== 'ended'" class="team-tab-btns">
              <button class="btn-primary btn-sm" @click="openTeamModal('create')"><i class="fa-solid fa-plus"></i> 创建队伍</button>
              <button class="btn-secondary btn-sm" @click="openTeamModal('join')"><i class="fa-solid fa-key"></i> 口令加入</button>
            </div>
          </div>

          <div v-if="loadingTeams" class="empty small">加载队伍中...</div>
          <div v-else-if="teamsList.length === 0" class="empty small">本比赛暂无已创建的队伍</div>
          <div v-else class="teams-list-grid">
            <div v-for="t in teamsList" :key="t.id" class="team-overview-card" :class="{ 'is-my': myTeam?.id === t.id }">
              <div class="toc-head">
                <div class="toc-name">
                  <i class="fa-solid fa-users"></i>
                  <b>{{ t.name }}</b>
                  <span v-if="myTeam?.id === t.id" class="toc-my-tag">我的队伍</span>
                </div>
                <div class="toc-meta">
                  <span>{{ t.members.length }} / {{ contest.max_team_members || 3 }} 人</span>
                </div>
              </div>

              <div class="toc-members">
                <div v-for="m in t.members" :key="m.user_id" class="toc-member-chip">
                  <span v-if="m.user_id === t.leader_id" class="toc-crown" title="队长">👑</span>
                  <router-link :to="`/user/${m.user_number}`" class="u-link" :style="{ color: userColor(m) }">
                    {{ m.username }}
                  </router-link>
                </div>
              </div>

              <!-- 未加入队伍的用户可点击加入该队伍 -->
              <div v-if="isLoggedIn && !myTeam && t.members.length < (contest.max_team_members || 3) && contest.status !== 'ended'" class="toc-foot">
                <button class="btn-secondary btn-xs" @click="openTeamModal('join')">
                  <i class="fa-solid fa-arrow-right-to-bracket"></i> 凭口令加入
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 组队赛：报名与组队弹窗 -->
        <div v-if="showTeamModal" class="modal-overlay" @click.self="showTeamModal = false">
          <div class="modal-box">
            <div class="modal-header">
              <h3>组队参赛</h3>
              <button class="modal-close" @click="showTeamModal = false">&times;</button>
            </div>

            <!-- 弹窗模式切换 -->
            <div class="modal-tabs">
              <button
                type="button"
                class="modal-tab-btn"
                :class="{ active: teamModalTab === 'create' }"
                @click="teamModalTab = 'create'; teamActionError = ''"
              >
                <i class="fa-solid fa-plus"></i> 创建新队伍
              </button>
              <button
                type="button"
                class="modal-tab-btn"
                :class="{ active: teamModalTab === 'join' }"
                @click="teamModalTab = 'join'; teamActionError = ''"
              >
                <i class="fa-solid fa-key"></i> 加入已有队伍
              </button>
              <button
                v-if="!contest.is_participant"
                type="button"
                class="modal-tab-btn"
                :class="{ active: teamModalTab === 'direct' }"
                @click="teamModalTab = 'direct'; teamActionError = ''"
              >
                <i class="fa-solid fa-user"></i> 仅先报名
              </button>
            </div>

            <!-- 创建新队伍 -->
            <div v-if="teamModalTab === 'create'" class="modal-body">
              <label class="form-item">
                <span class="form-label">队伍名称 *</span>
                <input
                  v-model="newTeamName"
                  class="form-input"
                  placeholder="例如：ACM三剑客 / 银河战舰"
                  maxlength="50"
                  @keydown.enter.prevent="handleCreateTeam"
                />
              </label>
              <label class="form-item">
                <span class="form-label">队伍邀请口令（选填）</span>
                <input
                  v-model="newTeamInviteCode"
                  class="form-input"
                  placeholder="留空则系统自动随机生成 6 位口令"
                  maxlength="32"
                />
                <span class="hint">队友凭此口令加入队伍，可在队内随时查看或分享</span>
              </label>
              <div v-if="teamActionError" class="form-error">{{ teamActionError }}</div>
              <div class="modal-footer">
                <button class="btn-secondary" @click="showTeamModal = false">取消</button>
                <button
                  class="btn-primary"
                  :disabled="teamActionLoading || !newTeamName.trim()"
                  @click="handleCreateTeam"
                >
                  {{ teamActionLoading ? '创建中...' : '立即创建并参赛' }}
                </button>
              </div>
            </div>

            <!-- 加入已有队伍 -->
            <div v-else-if="teamModalTab === 'join'" class="modal-body">
              <label class="form-item">
                <span class="form-label">队伍邀请口令 *</span>
                <input
                  v-model="joinInviteCode"
                  class="form-input"
                  placeholder="请输入队长分享的队伍邀请口令"
                  maxlength="32"
                  @keydown.enter.prevent="() => handleJoinTeam()"
                />
                <span class="hint">请向队长索取 6 位队伍邀请口令</span>
              </label>
              <div v-if="teamActionError" class="form-error">{{ teamActionError }}</div>
              <div class="modal-footer">
                <button class="btn-secondary" @click="showTeamModal = false">取消</button>
                <button
                  class="btn-primary"
                  :disabled="teamActionLoading || !joinInviteCode.trim()"
                  @click="() => handleJoinTeam()"
                >
                  {{ teamActionLoading ? '加入中...' : '加入队伍' }}
                </button>
              </div>
            </div>

            <!-- 仅先报名 -->
            <div v-else class="modal-body">
              <div class="direct-reg-tip">
                <p>先完成比赛报名，你可以稍后再创建队伍或等待队长将你拉入队伍。</p>
                <p class="sub-tip">注：组队赛中必须加入一支队伍后才能提交比赛题目代码。</p>
              </div>
              <div v-if="teamActionError" class="form-error">{{ teamActionError }}</div>
              <div class="modal-footer">
                <button class="btn-secondary" @click="showTeamModal = false">取消</button>
                <button
                  class="btn-primary"
                  :disabled="teamActionLoading"
                  @click="handleDirectRegister"
                >
                  {{ teamActionLoading ? '报名中...' : '确认报名' }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.virtual-panel { margin-top: 14px; padding: 10px 12px; border: 1px dashed var(--border-color, #ddd); border-radius: 8px; }
.virtual-active, .virtual-idle { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.virtual-timer { font-size: 14px; }
.virtual-timer b { font-family: ui-monospace, monospace; font-size: 16px; color: #0d47a1; }
.rating-panel { margin-top: 18px; border-top: 1px solid var(--border-color, #eee); padding-top: 12px; }
.rating-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.btn-settle { padding: 5px 12px; border-radius: 6px; border: 1px solid #0d47a1; background: #0d47a1; color: #fff; cursor: pointer; }
.btn-settle:disabled { opacity: .6; cursor: not-allowed; }
.rating-error { color: #c0392b; font-size: 13px; margin: 6px 0; }
.rating-table { margin-top: 8px; }
.delta-up { color: #2e7d32; font-weight: 600; }
.delta-down { color: #c62828; font-weight: 600; }
.contest-detail-page { min-height: calc(100vh - 60px); }
.contest-detail-container { max-width: 1100px; margin: 0 auto; padding: 20px; }
.back-link { margin-bottom: 12px; }
.back-link a { color: var(--primary); font-size: 14px; cursor: pointer; text-decoration: none; }

.card { padding: 20px 26px; margin-bottom: 16px; }

.head-top { display: flex; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; gap: 14px; }
.title-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.title-row h1 { color: var(--primary); font-size: 26px; margin: 0; }
.status-badge { font-size: 13px; padding: 3px 14px; border-radius: 20px; font-weight: 600; }
.status-badge.running { color: #fff; background: #52c41a; }
.status-badge.pending { color: #fff; background: #f39c11; }
.status-badge.ended { color: #8e9aaf; background: var(--bg-subtle); }
.shield-badge { font-size: 12px; padding: 3px 10px; border-radius: 20px; font-weight: 500; background: color-mix(in srgb, var(--primary) 12%, transparent); color: var(--primary); display: inline-flex; align-items: center; gap: 4px; }
.team-contest-badge { font-size: 12px; padding: 3px 12px; border-radius: 20px; font-weight: 600; color: #722ed1; background: color-mix(in srgb, #722ed1 10%, transparent); display: inline-flex; align-items: center; gap: 6px; }

.head-stats { display: flex; gap: 26px; }
.stat { text-align: center; }
.stat-label { font-size: 13px; color: var(--text-sub); }
.stat-value { font-size: 20px; font-weight: 700; color: var(--text-strong); }

.tab-row { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-top: 20px; border-top: 1px solid var(--border-color); padding-top: 14px; }
.setting-nav { display: flex; gap: 8px; }
.nav-btn { padding: 6px 16px; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; color: var(--text-sub); display: inline-flex; align-items: center; gap: 6px; }
.nav-btn:hover:not(.locked) { color: var(--text-strong); background: var(--bg-subtle); }
.nav-btn.active { color: #fff; background: var(--primary); }
.nav-btn.locked { opacity: .6; cursor: not-allowed; }
.lock-ico { font-size: 12px; }

.head-actions { display: flex; align-items: center; gap: 10px; }
.joined-tag { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; padding: 6px 14px; border-radius: 8px; font-weight: 600; background: color-mix(in srgb, var(--success) 12%, transparent); color: var(--success); }
.joined-tag.team-tag { background: color-mix(in srgb, #722ed1 12%, transparent); color: #722ed1; }
.action-msg { background: color-mix(in srgb, var(--primary) 10%, transparent); color: var(--primary); padding: 10px 16px; border-radius: 8px; font-size: 13px; font-weight: 600; margin-bottom: 14px; }

.detail-grid { display: grid; grid-template-columns: 1fr 300px; gap: 16px; }
.statement-main { display: flex; flex-direction: column; gap: 16px; }

/* 我的队伍卡片 */
.my-team-card { background: color-mix(in srgb, #722ed1 4%, var(--surface)); border-left: 4px solid #722ed1; }
.team-card-head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; }
.team-title-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.team-badge-icon { color: #722ed1; font-size: 18px; }
.team-title { margin: 0; font-size: 18px; color: var(--text-strong); font-weight: 700; }
.leader-pill { font-size: 11px; padding: 2px 8px; border-radius: 10px; background: #f39c11; color: #fff; font-weight: 600; }
.team-capacity { font-size: 12px; color: var(--text-sub); }
.team-card-actions { display: flex; align-items: center; gap: 10px; }
.btn-code { background: color-mix(in srgb, #722ed1 10%, transparent); color: #722ed1; border: 1px dashed #722ed1; border-radius: 6px; padding: 4px 10px; font-size: 12px; cursor: pointer; font-weight: 600; }
.btn-code:hover { background: color-mix(in srgb, #722ed1 20%, transparent); }
.btn-text-danger { background: none; border: none; color: #e74c3c; font-size: 12px; cursor: pointer; text-decoration: underline; padding: 0; }

.team-members-grid { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.member-chip { display: inline-flex; align-items: center; gap: 6px; background: var(--surface-strong); border: 1px solid var(--border-color); padding: 4px 10px; border-radius: 6px; font-size: 13px; }
.chip-crown { font-size: 13px; }
.member-name { font-weight: 600; text-decoration: none; }
.member-uid { font-size: 11px; color: var(--text-sub); }
.kick-btn { background: none; border: none; color: #8e9aaf; cursor: pointer; padding: 0 2px; font-size: 12px; }
.kick-btn:hover { color: #e74c3c; }

.add-member-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding-top: 10px; border-top: 1px dashed var(--border-color); }
.form-input-sm { width: 260px; padding: 5px 10px; font-size: 13px; }
.btn-xs { padding: 4px 10px; font-size: 12px; }
.member-add-tip { font-size: 12px; color: var(--primary); }

.pending-team-card { border-left-color: #f39c11; background: color-mix(in srgb, #f39c11 4%, var(--surface)); }
.pending-team-inner { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.warn-ico { font-size: 26px; color: #f39c11; }
.pending-team-text { flex: 1; font-size: 13px; color: var(--text-strong); }
.pending-team-text p { margin: 4px 0 0; color: var(--text-sub); }
.pending-team-btns { display: flex; gap: 8px; }

.side-card { padding: 18px 20px; }
.side-tip { font-size: 14px; font-weight: 700; margin-bottom: 12px; }
.running-tip { color: light-dark(#52c41a, #34d399); }
.pending-tip { color: #f39c11; }
.ended-tip { color: #e74c3c; }
.side-rows { display: flex; flex-direction: column; gap: 10px; }
.side-row { display: flex; justify-content: space-between; align-items: center; font-size: 13px; color: var(--text-sub); }
.side-row b { color: var(--text-strong); font-weight: 600; }
.owner-link { color: var(--primary); font-weight: 600; text-decoration: none; }

.section-title { margin: 4px 0 14px; color: var(--text-strong); }
.member-count { color: var(--text-sub); font-weight: 400; font-size: 13px; }
.statement-body { min-height: 60px; }
.hint-bar { background: color-mix(in srgb, var(--primary) 8%, transparent); color: var(--primary-text); border-radius: 8px; padding: 10px 14px; font-size: 13px; margin-bottom: 12px; }
.hint-bar.warn { background: color-mix(in srgb, var(--warning) 12%, transparent); color: var(--warning-text); }

.denied-card { text-align: center; padding: 46px 20px; }
.denied-ico { font-size: 34px; color: #c2c9d4; margin-bottom: 12px; }
.denied-text { font-size: 17px; font-weight: 700; color: var(--text-strong); }
.denied-sub { margin-top: 8px; color: #8e9aaf; font-size: 13px; }

.cp-list { display: flex; flex-direction: column; gap: 8px; }
.cp-item { display: flex; align-items: center; gap: 12px; background: var(--surface-strong); border: var(--border-width) solid var(--border-color); border-radius: 8px; padding: 10px 14px; cursor: pointer; }
.cp-item:hover { border-color: rgba(231, 76, 60, 0.4); background: rgba(231, 76, 60, 0.06); }
.cp-alias { font-weight: 700; color: var(--primary); min-width: 28px; }
.cp-title { flex: 1; color: var(--text-strong); font-size: 14px; }
.diff-badge { color: #fff; font-size: 12px; padding: 2px 10px; border-radius: 4px; font-weight: 600; }

/* 排行榜 */
.rank-wrap { overflow-x: auto; }
.rank-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.rank-table th, .rank-table td { padding: 9px 10px; border-bottom: 1px solid #f0f2f5; text-align: center; }
.rank-table th { color: var(--text-sub); font-weight: 600; background: rgba(148, 163, 184, 0.14); }
.col-user { text-align: left !important; min-width: 160px; }
.u-link { font-weight: 700; text-decoration: none; }
.rank-header-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.rank-badges { display: flex; align-items: center; gap: 8px; }
.rule-hint-pill { font-size: 12px; padding: 2px 10px; border-radius: 4px; background: rgba(22, 119, 255, 0.08); color: #1677ff; font-weight: 600; }
.font-bold { font-weight: 700; }
.cell { display: inline-block; min-width: 44px; padding: 2px 8px; border-radius: 6px; }
.cell.solved { background: color-mix(in srgb, var(--success) 10%, transparent); color: var(--success-text); font-weight: 700; }
.cell.solved.fb { background: #27ae60; color: #fff; }
.cell.solved.fb em { color: #fff; opacity: 0.9; }
.cell.solved em { font-style: normal; color: #e67e22; font-size: 12px; }
.cell.partial { background: color-mix(in srgb, var(--warning) 12%, transparent); color: var(--warning-text); font-weight: 700; }
.cell.tried { background: color-mix(in srgb, var(--danger) 10%, transparent); color: #e74c3c; }
.cell.none { color: #ccc; }

.rank-team-cell { display: flex; flex-direction: column; gap: 3px; }
.rank-team-name { font-weight: 700; color: var(--text-strong); display: flex; align-items: center; gap: 6px; }
.rank-team-name i { color: #722ed1; }
.rank-team-members { display: flex; flex-wrap: wrap; gap: 6px; }
.rank-member-tag { font-size: 12px; display: inline-flex; align-items: center; gap: 3px; }
.rank-member-tag .crown { font-size: 11px; }

.frozen-card { text-align: center; padding: 48px 20px; }
.frozen-icon { font-size: 38px; color: #fa8c16; margin-bottom: 12px; }
.frozen-title { font-size: 17px; font-weight: 700; color: var(--text-strong); }
.frozen-desc { margin-top: 8px; color: #8e9aaf; font-size: 13px; max-width: 460px; margin-left: auto; margin-right: auto; line-height: 1.6; }

/* 参赛队伍选项卡 */
.team-tab-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; flex-wrap: wrap; gap: 10px; }
.team-tab-btns { display: flex; gap: 8px; }
.teams-list-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.team-overview-card { background: var(--surface-strong); border: 1px solid var(--border-color); border-radius: 10px; padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
.team-overview-card.is-my { border-color: #722ed1; background: color-mix(in srgb, #722ed1 4%, var(--surface-strong)); }
.toc-head { display: flex; align-items: center; justify-content: space-between; }
.toc-name { display: flex; align-items: center; gap: 6px; font-size: 15px; color: var(--text-strong); }
.toc-name i { color: #722ed1; }
.toc-my-tag { font-size: 11px; background: #722ed1; color: #fff; padding: 1px 6px; border-radius: 4px; font-weight: 600; }
.toc-meta { font-size: 12px; color: var(--text-sub); }
.toc-members { display: flex; flex-wrap: wrap; gap: 6px; }
.toc-member-chip { font-size: 12px; background: var(--surface); border: 1px solid var(--border-color); border-radius: 4px; padding: 2px 6px; display: inline-flex; align-items: center; gap: 4px; }
.toc-crown { font-size: 11px; }
.toc-foot { margin-top: 4px; display: flex; justify-content: flex-end; }

/* 弹窗 */
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 999; display: flex; justify-content: center; align-items: center; }
.modal-box { background: var(--surface-plain); border-radius: 14px; width: 92%; max-width: 480px; max-height: 88vh; overflow-y: auto; padding: 22px 26px; }
.modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.modal-header h3 { margin: 0; font-size: 18px; color: var(--text-strong); }
.modal-close { background: none; border: none; font-size: 20px; color: #8e9aaf; cursor: pointer; }
.modal-tabs { display: flex; gap: 8px; margin-bottom: 16px; border-bottom: 1px solid var(--border-color); padding-bottom: 10px; }
.modal-tab-btn { flex: 1; padding: 8px; border: none; background: var(--bg-subtle); border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; color: var(--text-sub); display: inline-flex; justify-content: center; align-items: center; gap: 6px; }
.modal-tab-btn.active { background: #722ed1; color: #fff; }
.form-item { display: block; margin-bottom: 14px; }
.form-label { display: block; font-size: 13px; font-weight: 600; color: var(--text-strong); margin-bottom: 6px; }
.form-input { width: 100%; box-sizing: border-box; padding: 8px 12px; border: 1px solid #dce0e6; border-radius: 8px; font-size: 14px; outline: none; }
.form-input:focus { border-color: #722ed1; }
.hint { font-size: 12px; color: #8e9aaf; margin-top: 4px; display: block; }
.form-error { color: #e74c3c; font-size: 13px; margin: 8px 0; }
.modal-footer { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
.direct-reg-tip { font-size: 13px; color: var(--text-strong); line-height: 1.6; }
.sub-tip { color: #e67e22; font-size: 12px; }

.btn-primary { background: var(--primary); color: #fff; border: none; border-radius: 8px; padding: 8px 20px; font-weight: 600; cursor: pointer; font-size: 14px; }
.btn-primary.btn-sm { padding: 6px 14px; font-size: 13px; }
.btn-secondary { background: var(--bg-subtle); color: var(--text-strong); border: none; border-radius: 8px; padding: 8px 20px; font-weight: 600; cursor: pointer; font-size: 14px; }
.btn-secondary.btn-sm { padding: 6px 14px; font-size: 13px; }
.btn-secondary:hover:not(:disabled) { background: #e2e8f0; }
.btn-danger { background: transparent; color: #e74c3c; border: 1px solid #e74c3c; border-radius: 8px; padding: 8px 20px; font-weight: 600; cursor: pointer; font-size: 14px; }
button:disabled { opacity: .6; cursor: not-allowed; }
.empty { text-align: center; color: var(--text-sub); padding: 30px 0; }
.empty.small { padding: 14px 0; font-size: 13px; }

@media (max-width: 860px) {
  .detail-grid { grid-template-columns: 1fr; }
}

@media (max-width: 600px) {
  .contest-detail-container {
    padding: 16px 0;
  }
  .card,
  .body-card {
    padding: 14px;
  }
  .side-card {
    padding: 14px;
  }
}
</style>
