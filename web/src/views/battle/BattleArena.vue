<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { battleApi, type BattleProfile, type BattleHistoryItem } from '@/api/battle'
import { difficultyColor } from '@/utils/difficulty'
import { userNameColor } from '@/utils/userColor'
import { staticUrl, withBase } from '@/utils/base'

const router = useRouter()
const authStore = useAuthStore()

const profile = ref<BattleProfile | null>(null)
const leaderboard = ref<BattleProfile[]>([])
const historyList = ref<BattleHistoryItem[]>([])
const ongoingBattle = ref<{
  has_ongoing: boolean
  battle_id?: number
  mode?: 'casual' | 'ranked'
  remaining_seconds?: number
  problem?: { id: number; title: string; difficulty: string; code: string }
  opponent?: { id: number; username: string; avatar_url: string | null }
} | null>(null)

const loading = ref(true)
const activeTab = ref<'leaderboard' | 'history'>('leaderboard')

// Matchmaking state
const isMatching = ref(false)
const matchMode = ref<'casual' | 'ranked'>('ranked')
const matchTimer = ref(0)
let timerInterval: ReturnType<typeof setInterval> | undefined
let pollInterval: ReturnType<typeof setInterval> | undefined

// Tier color maps
const tierColorMap: Record<string, string> = {
  bronze: '#cd7f32',
  silver: '#a0aec0',
  gold: '#d69e2e',
  platinum: '#38b2ac',
  diamond: '#3182ce',
}

const tierIconMap: Record<string, string> = {
  bronze: 'fa-shield',
  silver: 'fa-shield-halved',
  gold: 'fa-award',
  platinum: 'fa-medal',
  diamond: 'fa-gem',
}

const currentTierColor = computed(() => {
  return tierColorMap[profile.value?.tier || 'bronze'] || '#cd7f32'
})

const currentTierIcon = computed(() => {
  return tierIconMap[profile.value?.tier || 'bronze'] || 'fa-shield'
})

const loadProfile = async () => {
  try {
    profile.value = await battleApi.getProfile()
  } catch (err) {
    console.error('Failed to load profile:', err)
  }
}

const loadLeaderboard = async () => {
  try {
    const res = await battleApi.getLeaderboard(50)
    leaderboard.value = res.items
  } catch (err) {
    console.error('Failed to load leaderboard:', err)
  }
}

const loadHistory = async () => {
  try {
    const res = await battleApi.getHistory(20)
    historyList.value = res.items
  } catch (err) {
    console.error('Failed to load history:', err)
  }
}

const loadCurrentBattle = async () => {
  try {
    const res = await battleApi.getCurrentBattle()
    ongoingBattle.value = res.has_ongoing ? res : null
  } catch (err) {
    console.error('Failed to load current battle:', err)
  }
}

const loadAllData = async () => {
  loading.value = true
  await Promise.all([loadProfile(), loadLeaderboard(), loadHistory(), loadCurrentBattle()])
  loading.value = false
}

const handleSurrenderOngoing = async (battleId: number) => {
  if (!confirm('确定放弃并认输当前对战吗？结算后将可以立即开始新匹配。')) return
  try {
    await battleApi.surrender(battleId)
    ongoingBattle.value = null
    await loadAllData()
  } catch (err: any) {
    alert(err?.response?.data?.detail || '操作失败')
  }
}

// Start matching
const startMatch = async (mode: 'casual' | 'ranked', simulate = false) => {
  if (ongoingBattle.value && ongoingBattle.value.battle_id) {
    const confirmForfeit = confirm(
      `您当前有一场尚未结束的对战（剩余约 ${Math.ceil((ongoingBattle.value.remaining_seconds || 0) / 60)} 分钟）。\n\n点击【确定】认输放弃当前对战并开始新匹配，点击【取消】返回继续当前对决。`
    )
    if (!confirmForfeit) {
      router.push(`/arena/room/${ongoingBattle.value.battle_id}`)
      return
    }
    // User chose to forfeit and start fresh match
    try {
      await battleApi.surrender(ongoingBattle.value.battle_id)
      ongoingBattle.value = null
    } catch {
      // Ignore surrender error
    }
  }

  matchMode.value = mode
  isMatching.value = true
  matchTimer.value = 0

  clearInterval(timerInterval)
  timerInterval = setInterval(() => {
    matchTimer.value += 1
  }, 1000)

  const actualSimulate = mode === 'casual' ? simulate : false

  try {
    const res = await battleApi.startMatch(mode, actualSimulate, true)
    if (res.status === 'matched' && res.battle_id) {
      stopMatchPolling()
      router.push(`/arena/room/${res.battle_id}`)
      return
    }
  } catch (err: any) {
    alert(err?.response?.data?.detail || '匹配发起失败，请稍后重试')
    cancelMatch()
    return
  }

  // Start polling match status
  clearInterval(pollInterval)
  pollInterval = setInterval(async () => {
    try {
      const statusRes = await battleApi.getMatchStatus()
      if (statusRes.status === 'matched' && statusRes.battle_id) {
        stopMatchPolling()
        router.push(`/arena/room/${statusRes.battle_id}`)
      }
    } catch {
      // Ignore transient polling errors
    }
  }, 1500)
}

const cancelMatch = async () => {
  stopMatchPolling()
  try {
    await battleApi.cancelMatch()
  } catch {
    // Ignore cancel errors
  }
}

const stopMatchPolling = () => {
  isMatching.value = false
  clearInterval(timerInterval)
  clearInterval(pollInterval)
}

const formatSeconds = (sec: number) => {
  const m = Math.floor(sec / 60).toString().padStart(2, '0')
  const s = (sec % 60).toString().padStart(2, '0')
  return `${m}:${s}`
}

onMounted(() => {
  loadAllData()
})

onBeforeUnmount(() => {
  stopMatchPolling()
})
</script>

<template>
  <div class="arena-container">
    <!-- 顶部段位与战绩名片 -->
    <div class="arena-header-card" :style="{ borderColor: currentTierColor }">
      <div class="rank-badge-wrap" :style="{ color: currentTierColor }">
        <i :class="['fa-solid', currentTierIcon, 'badge-icon']"></i>
        <div class="rank-name">{{ profile?.rank_name || '青铜 III' }}</div>
      </div>

      <div class="rank-info-wrap">
        <div class="rank-progress-row">
          <div class="lp-label">
            <span class="lp-value">{{ profile?.points || 0 }}</span>
            <span class="lp-max"> / 100 LP</span>
          </div>
        </div>
        <div class="progress-bar-bg">
          <div
            class="progress-bar-fill"
            :style="{ width: `${Math.min(100, profile?.points || 0)}%`, backgroundColor: currentTierColor }"
          ></div>
        </div>

        <div class="stats-grid">
          <div class="stat-item">
            <div class="stat-num">{{ profile?.total_matches || 0 }}</div>
            <div class="stat-name">总场次</div>
          </div>
          <div class="stat-item">
            <div class="stat-num stat-win">{{ profile?.wins || 0 }}</div>
            <div class="stat-name">胜场</div>
          </div>
          <div class="stat-item">
            <div class="stat-num">{{ profile?.win_rate || 0 }}%</div>
            <div class="stat-name">胜率</div>
          </div>
          <div class="stat-item">
            <div class="stat-num stat-streak">{{ profile?.win_streak || 0 }}</div>
            <div class="stat-name">当前连胜</div>
          </div>
          <div class="stat-item">
            <div class="stat-num stat-exp">{{ (profile?.experience || 0).toLocaleString() }}</div>
            <div class="stat-name">我的经验</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 进行中对战提醒横幅 -->
    <div v-if="ongoingBattle && ongoingBattle.has_ongoing" class="ongoing-battle-alert">
      <div class="ongoing-alert-content">
        <div class="alert-icon-pulse">
          <i class="fa-solid fa-gamepad"></i>
        </div>
        <div class="alert-texts">
          <div class="alert-title">
            <span>您当前有一场正在进行中的 1v1 对决</span>
            <span class="mode-tag" :class="ongoingBattle.mode">{{ ongoingBattle.mode === 'ranked' ? '排位模式' : '普通模式' }}</span>
          </div>
          <div class="alert-desc">
            题目：<strong>{{ ongoingBattle.problem?.code }} {{ ongoingBattle.problem?.title }}</strong>
            <span class="dot-sep">•</span>
            对手：<strong>{{ ongoingBattle.opponent?.username }}</strong>
            <span class="dot-sep">•</span>
            剩余倒计时：<strong class="time-remain">{{ formatSeconds(ongoingBattle.remaining_seconds || 0) }}</strong>
          </div>
        </div>
      </div>
      <div class="ongoing-alert-actions">
        <button
          type="button"
          class="btn-alert-resume"
          @click="router.push(`/arena/room/${ongoingBattle.battle_id}`)"
        >
          <i class="fa-solid fa-arrow-right-to-bracket"></i> 继续对战
        </button>
        <button
          type="button"
          class="btn-alert-surrender"
          @click="handleSurrenderOngoing(ongoingBattle.battle_id!)"
        >
          <i class="fa-solid fa-flag"></i> 认输并结束
        </button>
      </div>
    </div>

    <!-- 模式对战选择卡片 -->
    <div class="mode-selection-grid">
      <!-- 排位对战 -->
      <div class="mode-card mode-ranked" @click="startMatch('ranked')">
        <div class="mode-icon-wrap ranked-icon">
          <i class="fa-solid fa-trophy"></i>
        </div>
        <div class="mode-content">
          <div class="mode-title">排位对战</div>
          <div class="mode-desc">
            1v1 实时对抗，计入天梯段位与胜点。
          </div>
          <button type="button" class="mode-btn btn-ranked">
            <i class="fa-solid fa-play"></i> 开始排位匹配
          </button>
        </div>
      </div>

      <!-- 普通对战 -->
      <div class="mode-card mode-casual" @click="startMatch('casual')">
        <div class="mode-icon-wrap casual-icon">
          <i class="fa-solid fa-gamepad"></i>
        </div>
        <div class="mode-content">
          <div class="mode-title">普通对战</div>
          <div class="mode-desc">
            自由对抗练习，不计入天梯段位。
          </div>
          <button type="button" class="mode-btn btn-casual">
            <i class="fa-solid fa-fire"></i> 开始普通匹配
          </button>
        </div>
      </div>
    </div>

    <!-- 下半部分功能 Tabs -->
    <div class="arena-tabs-card">
      <div class="arena-tabs-header">
        <button
          type="button"
          class="tab-btn"
          :class="{ active: activeTab === 'leaderboard' }"
          @click="activeTab = 'leaderboard'"
        >
          <i class="fa-solid fa-ranking-star"></i> 天梯排行榜
        </button>
        <button
          type="button"
          class="tab-btn"
          :class="{ active: activeTab === 'history' }"
          @click="activeTab = 'history'"
        >
          <i class="fa-solid fa-clock-rotate-left"></i> 最近对战
        </button>
      </div>

      <div class="arena-tabs-body">
        <!-- 排行榜面板 -->
        <div v-if="activeTab === 'leaderboard'" class="tab-pane">
          <div style="display: flex; justify-content: flex-end; align-items: center; margin-bottom: 12px;">
            <a :href="withBase('/ranking?type=battle')" class="go-full-rank-link" @click.prevent="router.push('/ranking?type=battle')">
              前往全站对战排行榜 <i class="fa-solid fa-arrow-right"></i>
            </a>
          </div>

          <div v-if="loading" class="empty-state">加载中...</div>
          <div v-else-if="leaderboard.length === 0" class="empty-state">暂无排位天梯数据，快来打第一把吧！</div>
          <div v-else class="table-wrap">
            <table class="arena-table">
              <thead>
                <tr>
                  <th style="width: 70px;">排名</th>
                  <th>选手</th>
                  <th>当前段位</th>
                  <th>胜点</th>
                  <th>胜场次</th>
                  <th>总场次 / 胜率</th>
                  <th>当前连胜</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="user in leaderboard" :key="user.user_id" :class="{ 'is-me': user.user_id === authStore.currentUser?.id }">
                  <td>
                    <span v-if="user.rank === 1" class="rank-badge rank-1"><i class="fa-solid fa-crown"></i> 1</span>
                    <span v-else-if="user.rank === 2" class="rank-badge rank-2">2</span>
                    <span v-else-if="user.rank === 3" class="rank-badge rank-3">3</span>
                    <span v-else class="rank-badge">{{ user.rank }}</span>
                  </td>
                  <td>
                    <div class="player-cell">
                      <img :src="user.avatar_url || staticUrl('/static/uploads/avatars/default.png')" class="player-avatar" alt="avatar" />
                      <router-link
                        v-if="user.user_number"
                        :to="`/user/${user.user_number}`"
                        class="player-name"
                        :style="{ color: userNameColor(user) }"
                      >{{ user.username }}</router-link>
                      <span v-else class="player-name" :style="{ color: userNameColor(user) }">{{ user.username }}</span>
                      <span v-if="user.user_tag" class="user-tag" :style="{ backgroundColor: userNameColor(user) }">{{ user.user_tag }}</span>
                    </div>
                  </td>
                  <td>
                    <span class="tier-pill" :style="{ backgroundColor: `${tierColorMap[user.tier] || '#999'}22`, color: tierColorMap[user.tier] || '#999' }">
                      <i :class="['fa-solid', tierIconMap[user.tier] || 'fa-shield']"></i>
                      {{ user.rank_name }}
                    </span>
                  </td>
                  <td>
                    <strong>{{ user.points }}</strong> LP
                  </td>
                  <td>
                    <strong style="color: #38a169; font-size: 15px;">{{ user.wins }} 胜</strong>
                  </td>
                  <td>
                    {{ user.total_matches }} 场 ({{ user.win_rate }}%)
                  </td>
                  <td>
                    <span v-if="user.win_streak > 0" class="streak-tag">
                      <i class="fa-solid fa-fire"></i> {{ user.win_streak }} 连胜
                    </span>
                    <span v-else>-</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- 历史战绩面板 -->
        <div v-if="activeTab === 'history'" class="tab-pane">
          <div v-if="loading" class="empty-state">加载中...</div>
          <div v-else-if="historyList.length === 0" class="empty-state">你还没有任何对战记录，快去匹配一局吧！</div>
          <div v-else class="history-grid">
            <div
              v-for="item in historyList"
              :key="item.id"
              class="history-card"
              :class="[`result-${item.result}`]"
            >
              <div class="history-header">
                <span class="mode-tag" :class="item.mode">
                  {{ item.mode === 'ranked' ? '天梯排位' : '普通对战' }}
                </span>
                <span class="result-text">
                  <span v-if="item.result === 'win'">胜利 VICTORY</span>
                  <span v-else-if="item.result === 'loss'">战败 DEFEAT</span>
                  <span v-else-if="item.result === 'draw'">平局 DRAW</span>
                  <span v-else>对局中 ONGOING</span>
                </span>
                <span class="history-time">{{ new Date(item.started_at).toLocaleString() }}</span>
              </div>

              <div class="history-body">
                <div class="history-problem">
                  <span class="prob-title">题目：{{ item.problem.code }} {{ item.problem.title }}</span>
                  <span
                    class="diff-badge"
                    :style="{ color: difficultyColor(item.problem.difficulty) }"
                  >
                    {{ item.problem.difficulty }}
                  </span>
                </div>
                <div class="history-opponent">
                  对手：
                  <router-link
                    v-if="item.opponent.user_number"
                    :to="`/user/${item.opponent.user_number}`"
                    class="opp-link"
                    :style="{ color: userNameColor(item.opponent) }"
                  ><strong>{{ item.opponent.username }}</strong></router-link>
                  <strong v-else :style="{ color: userNameColor(item.opponent) }">{{ item.opponent.username }}</strong>
                </div>
                <div v-if="item.settlement" class="history-settlement">
                  <span class="gain-item">+{{ item.settlement.xp_gain }} 经验</span>
                  <span v-if="item.settlement.rank?.points_delta" class="gain-item">
                    {{ item.settlement.rank.points_delta > 0 ? `+${item.settlement.rank.points_delta}` : item.settlement.rank.points_delta }} LP
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 匹配遮罩弹窗 -->
    <div v-if="isMatching" class="match-overlay">
      <div class="match-modal">
        <div class="radar-pulse"></div>
        <div class="match-mode-label">
          {{ matchMode === 'ranked' ? '排位天梯匹配中' : '普通对战匹配中' }}
        </div>
        <div class="match-timer">{{ formatSeconds(matchTimer) }}</div>
        <p class="match-tip">正在寻找实力相当的对手...</p>

        <div class="match-actions">
          <!-- 仅普通对战模式在等待超时后允许匹配练习模拟对手（排位天梯必须与真人对决） -->
          <button
            v-if="matchTimer >= 5 && matchMode === 'casual'"
            type="button"
            class="btn-simulate"
            @click="startMatch('casual', true)"
          >
            <i class="fa-solid fa-robot"></i> 匹配练习模拟对手
          </button>
          <button type="button" class="btn-cancel" @click="cancelMatch">
            <i class="fa-solid fa-xmark"></i> 取消匹配
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.arena-container {
  max-width: 1100px;
  margin: 0 auto;
  padding: 24px 16px;
}

/* 顶部段位卡片 */
.arena-header-card {
  display: flex;
  align-items: center;
  gap: 32px;
  background: var(--surface-plain);
  border: 2px solid;
  border-radius: 12px;
  padding: 24px 32px;
  box-shadow: var(--shadow-card);
  margin-bottom: 24px;
}

.rank-badge-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-width: 140px;
}

.badge-icon {
  font-size: 64px;
  margin-bottom: 8px;
  filter: drop-shadow(0 4px 8px rgba(0,0,0,0.15));
}

.rank-name {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 0.5px;
}

.rank-info-wrap {
  flex: 1;
}

.rank-progress-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 8px;
}

.lp-value {
  font-size: 24px;
  font-weight: 800;
}

.lp-max {
  color: var(--text-sub);
  font-size: 14px;
}

.rank-desc {
  font-size: 13px;
  color: var(--text-sub);
}

.progress-bar-bg {
  width: 100%;
  height: 10px;
  background: var(--bg-subtle);
  border-radius: 5px;
  overflow: hidden;
  margin-bottom: 20px;
}

.progress-bar-fill {
  height: 100%;
  border-radius: 5px;
  transition: width 0.4s ease;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
  background: var(--surface-plain);
  padding: 12px 16px;
  border-radius: 8px;
  text-align: center;
}

.stat-num {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-strong);
}

.stat-win {
  color: #38a169;
}

.stat-streak {
  color: #dd6b20;
}

.stat-exp {
  color: #805ad5;
}

.stat-name {
  font-size: 12px;
  color: var(--text-sub);
  margin-top: 2px;
}

/* 对战模式选择卡片 */
.mode-selection-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 28px;
}

.mode-card {
  display: flex;
  gap: 20px;
  background: var(--surface-plain);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 24px;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
  position: relative;
  overflow: hidden;
}

.mode-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-card-hover);
}

.mode-icon-wrap {
  width: 64px;
  height: 64px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  flex-shrink: 0;
}

.ranked-icon {
  background: #fefcbf;
  color: #b7791f;
}

.casual-icon {
  background: var(--bg-subtle);
  color: var(--text-main);
}

.mode-content {
  flex: 1;
}

.mode-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-strong);
  margin-bottom: 6px;
}

.mode-desc {
  font-size: 13px;
  color: var(--text-sub);
  line-height: 1.5;
  margin-bottom: 16px;
}

.mode-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 20px;
  border-radius: 6px;
  font-weight: 600;
  font-size: 14px;
  border: none;
  cursor: pointer;
}

.btn-ranked {
  background: #d69e2e;
  color: #ffffff;
}

.btn-ranked:hover {
  background: #b7791f;
}

.btn-casual {
  background: #4a5568;
  color: #ffffff;
}

.btn-casual:hover {
  background: #2d3748;
}

/* Tabs 区域 */
.arena-tabs-card {
  background: var(--surface-plain);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  overflow: hidden;
}

.arena-tabs-header {
  display: flex;
  border-bottom: 1px solid var(--border-color);
  background: var(--surface-plain);
}

.tab-btn {
  padding: 14px 24px;
  background: none;
  border: none;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-sub);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
}

.tab-btn.active {
  color: #3182ce;
  background: var(--surface-plain);
  border-bottom-color: #3182ce;
}

.arena-tabs-body {
  padding: 24px;
}

.go-full-rank-link {
  font-size: 13px;
  color: #3182ce;
  font-weight: 600;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.go-full-rank-link:hover {
  text-decoration: underline;
}

/* 表格 */
.arena-table {
  width: 100%;
  border-collapse: collapse;
}

.arena-table th {
  text-align: left;
  padding: 12px 14px;
  border-bottom: 2px solid var(--border-color);
  color: var(--text-sub);
  font-size: 13px;
}

.arena-table td {
  padding: 14px;
  border-bottom: 1px solid var(--border-color);
  font-size: 14px;
}

.arena-table tr.is-me {
  /* 语义 tint 跟着主题走：写死浅蓝在深色下是一条浅底浅字的亮带 */
  background: color-mix(in srgb, var(--primary) 12%, transparent);
}

.player-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.player-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  object-fit: cover;
}

.player-name {
  font-weight: 600;
  text-decoration: none;
}

a.player-name:hover {
  text-decoration: underline;
}

.opp-link {
  text-decoration: none;
}

.opp-link:hover {
  text-decoration: underline;
}

.tier-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 700;
}

.rank-badge {
  font-weight: 700;
  color: var(--text-sub);
}

.rank-1 {
  color: #d69e2e;
  font-size: 16px;
}

.rank-2 {
  color: var(--text-sub);
  font-size: 15px;
}

.rank-3 {
  color: #b7791f;
  font-size: 15px;
}

.streak-tag {
  color: #dd6b20;
  font-weight: 600;
}

.user-tag {
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
}

/* 历史卡片 */
.history-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.history-card {
  border-left: 4px solid var(--border-color);
  background: var(--surface-plain);
  border-radius: 0 8px 8px 0;
  padding: 16px;
}

.history-card.result-win {
  border-left-color: var(--success);
  background: color-mix(in srgb, var(--success) 12%, transparent);
}

.history-card.result-loss {
  border-left-color: var(--danger);
  background: color-mix(in srgb, var(--danger) 12%, transparent);
}

.history-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.mode-tag {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
}

.mode-tag.ranked {
  background: #feebc8;
  color: #b7791f;
}

.mode-tag.casual {
  background: var(--bg-subtle);
  color: var(--text-main);
}

.result-text {
  font-weight: 800;
  font-size: 14px;
}

.result-win .result-text {
  color: var(--success);
}

.result-loss .result-text {
  color: var(--danger);
}

.history-time {
  font-size: 12px;
  color: var(--text-sub);
  margin-left: auto;
}

.history-body {
  display: flex;
  align-items: center;
  gap: 24px;
  font-size: 13px;
}

.gain-item {
  background: var(--surface-plain);
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  font-weight: 600;
  color: var(--text-main);
  margin-right: 6px;
}
/* 匹配遮罩 */
.match-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.match-modal {
  background: var(--surface-plain);
  border-radius: 16px;
  padding: 40px;
  text-align: center;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.25);
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 340px;
}

.radar-pulse {
  width: 72px;
  height: 72px;
  background: #3182ce;
  border-radius: 50%;
  margin-bottom: 20px;
  animation: pulse 1.6s infinite ease-in-out;
}

@keyframes pulse {
  0% {
    transform: scale(0.85);
    box-shadow: 0 0 0 0 rgba(49, 130, 206, 0.7);
  }
  70% {
    transform: scale(1);
    box-shadow: 0 0 0 24px rgba(49, 130, 206, 0);
  }
  100% {
    transform: scale(0.85);
    box-shadow: 0 0 0 0 rgba(49, 130, 206, 0);
  }
}

.match-mode-label {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-strong);
  margin-bottom: 8px;
}

.match-timer {
  font-size: 32px;
  font-weight: 800;
  color: #3182ce;
  font-family: monospace;
  margin-bottom: 8px;
}

.match-tip {
  font-size: 13px;
  color: var(--text-sub);
  margin-bottom: 24px;
}

.match-actions {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
}

.btn-simulate {
  padding: 10px 16px;
  background: var(--bg-subtle);
  color: var(--text-strong);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-weight: 600;
  font-size: 13px;
  cursor: pointer;
}

.btn-simulate:hover {
  background: var(--border-color);
}

.btn-cancel {
  padding: 10px 16px;
  background: #e53e3e;
  color: #ffffff;
  border: none;
  border-radius: 6px;
  font-weight: 600;
  font-size: 13px;
  cursor: pointer;
}

.btn-cancel:hover {
  background: #c53030;
}

.empty-state {
  text-align: center;
  color: var(--text-sub);
  padding: 36px 0;
  font-size: 14px;
}

/* 进行中对战提醒横幅 */
.ongoing-battle-alert {
  display: flex;
  align-items: center;
  justify-content: space-between;
  /* 语义 tint 跟着主题走：写死浅琥珀渐变在深色下会是一块刺眼的亮斑 */
  background: color-mix(in srgb, var(--warning) 14%, transparent);
  border: 1.5px solid color-mix(in srgb, var(--warning) 45%, transparent);
  border-radius: 12px;
  padding: 14px 20px;
  margin-bottom: 24px;
  box-shadow: 0 4px 12px rgba(221, 107, 32, 0.12);
  animation: slideInDown 0.3s ease-out;
}

@keyframes slideInDown {
  from {
    opacity: 0;
    transform: translateY(-8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.ongoing-alert-content {
  display: flex;
  align-items: center;
  gap: 16px;
}

.alert-icon-pulse {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: #dd6b20;
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  box-shadow: 0 0 0 0 rgba(221, 107, 32, 0.4);
  animation: iconPulse 2s infinite;
}

@keyframes iconPulse {
  0% {
    box-shadow: 0 0 0 0 rgba(221, 107, 32, 0.4);
  }
  70% {
    box-shadow: 0 0 0 8px rgba(221, 107, 32, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(221, 107, 32, 0);
  }
}

.alert-texts {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.alert-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 700;
  color: var(--warning-text);
}

.mode-tag {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 12px;
  background: #c05621;
  color: #ffffff;
}

.mode-tag.casual {
  background: #319795;
}

.alert-desc {
  font-size: 13px;
  color: var(--warning-text);
}

.alert-desc .dot-sep {
  margin: 0 6px;
  color: var(--warning-text);
}

.alert-desc .time-remain {
  color: var(--danger-text);
}

.ongoing-alert-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.btn-alert-resume {
  padding: 8px 18px;
  background: #dd6b20;
  color: #ffffff;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s;
}

.btn-alert-resume:hover {
  background: #c05621;
  transform: translateY(-1px);
}

.btn-alert-surrender {
  padding: 8px 14px;
  background: var(--surface-plain);
  color: var(--danger-text);
  border: 1px solid color-mix(in srgb, var(--danger) 35%, transparent);
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s;
}

.btn-alert-surrender:hover {
  background: color-mix(in srgb, var(--danger) 12%, transparent);
  border-color: color-mix(in srgb, var(--danger) 50%, transparent);
}

@media (max-width: 768px) {
  .arena-header-card {
    flex-direction: column;
    text-align: center;
  }
  .mode-selection-grid {
    grid-template-columns: 1fr;
  }
  .stats-grid {
    grid-template-columns: repeat(3, 1fr);
  }
  .tier-cards-row {
    grid-template-columns: 1fr;
  }
}
</style>
