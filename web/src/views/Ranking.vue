<script setup lang="ts">
/**
 * 全站排行榜页面。
 * 支持「经验排行榜」与「对战段位榜」双模式切换：
 * - 经验排行榜：总经验 = 经验余额 + 经验商店 Tag 卡花费 + 用经验购买颜色的花费
 * - 对战段位榜：按段位由高到低排行；相同段位按胜场次降序排行
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import apiClient from '@/api/client'
import { userNameColor } from '@/utils/userColor'

interface RankItem {
  rank: number
  user_number: number
  username: string
  avatar_url: string
  display_tag: string
  color_tier: string
  is_banned: boolean
  is_cheater: boolean
  is_admin: boolean
  is_super_admin: boolean
  can_manage_users: boolean
  can_manage_posts: boolean
  can_manage_problems: boolean
  can_manage_tags: boolean
  // 经验榜字段
  experience?: number
  tag_experience?: number
  color_experience?: number
  total_experience?: number
  // 等级分榜字段
  rating?: number
  max_rating?: number
  rated_contests?: number
  // 对战榜字段
  tier?: string
  tier_name?: string
  sub_tier?: number
  sub_tier_roman?: string
  points?: number
  rank_name?: string
  rank_score?: number
  total_matches?: number
  wins?: number
  losses?: number
  draws?: number
  win_rate?: number
  win_streak?: number
}

interface MyRank {
  rank: number
  user_number: number
  username: string
  total_experience?: number
  experience?: number
  tag_experience?: number
  color_experience?: number
  rank_name?: string
  tier?: string
  points?: number
  wins?: number
  total_matches?: number
  // 等级分榜字段
  rating?: number
  max_rating?: number
  rated_contests?: number
  win_rate?: number
}

const router = useRouter()
const route = useRoute()

const activeTab = ref<'exp' | 'battle' | 'rating'>(
  (route.query.type as string) === 'battle'
    ? 'battle'
    : (route.query.type as string) === 'rating'
      ? 'rating'
      : 'exp')

const items = ref<RankItem[]>([])
const myRank = ref<MyRank | null>(null)
const loading = ref(true)
const errorMsg = ref('')
const page = ref(1)
const pageSize = 10
const total = ref(0)
const totalPages = ref(1)

const tierColorMap: Record<string, string> = {
  bronze: '#cd7f32',
  silver: '#718096',
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

function formatExp(n?: number): string {
  return (n || 0).toLocaleString('zh-CN')
}

function rowColor(p: RankItem): string {
  return userNameColor(p)
}

function goUser(un: number) {
  router.push(`/user/${un}`)
}

function podiumIcon(rank: number): string {
  if (rank === 1) return 'fa-solid fa-crown'
  if (rank === 2) return 'fa-solid fa-2'
  return 'fa-solid fa-3'
}

// 领奖台展示顺序：第2名、第1名、第3名（中间最高），仅第 1 页展示
const podiumOrder = computed<RankItem[]>(() => {
  if (page.value !== 1) return []
  const top3 = items.value.slice(0, 3)
  if (top3.length === 1) return [top3[0]]
  if (top3.length === 2) return [top3[1], top3[0]]
  return [top3[1], top3[0], top3[2]]
})

// 第 1 页跳过前 3 名，其余页全部展示
const restItems = computed<RankItem[]>(() =>
  page.value === 1 ? items.value.slice(3) : items.value,
)

const canPrev = computed(() => page.value > 1)
const canNext = computed(() => page.value < totalPages.value)

function goPage(p: number) {
  if (p < 1 || p > totalPages.value || p === page.value) return
  page.value = p
  void load()
}

function switchTab(tab: 'exp' | 'battle' | 'rating') {
  if (activeTab.value === tab) return
  activeTab.value = tab
  page.value = 1
  router.replace({ query: { ...route.query, type: tab } })
  void load()
}

async function load() {
  loading.value = true
  errorMsg.value = ''
  const start = performance.now()
  const endpoint = activeTab.value === 'battle'
    ? '/api/ranking/battle'
    : activeTab.value === 'rating'
      ? '/api/ranking/rating'
      : '/api/ranking'

  try {
    const data: any = await apiClient.get(endpoint, {
      params: { page: page.value, page_size: pageSize },
    })
    items.value = data.items || []
    myRank.value = data.my_rank || null
    total.value = data.total || 0
    totalPages.value = data.total_pages || 1
  } catch (err: any) {
    errorMsg.value = err.response?.data?.detail || '排行榜加载失败'
  } finally {
    const elapsed = performance.now() - start
    const minDelay = 250
    if (elapsed < minDelay) {
      await new Promise((r) => setTimeout(r, minDelay - elapsed))
    }
    loading.value = false
  }
}

watch(
  () => route.query.type,
  (newType) => {
    const target = newType === 'battle' ? 'battle' : 'exp'
    if (activeTab.value !== target) {
      activeTab.value = target
      page.value = 1
      void load()
    }
  },
)

onMounted(() => load())
</script>

<template>
  <div class="ranking-page">
    <div class="ranking-container">
      <!-- 头部卡片 -->
      <div class="card head-card">
        <div class="head-row">
          <div>
            <h2 class="page-title">
              <i :class="['head-icon', activeTab === 'battle' ? 'fa-solid fa-gamepad' : (activeTab === 'rating' ? 'fa-solid fa-chart-line' : 'fa-solid fa-trophy')]"></i>
              {{ activeTab === 'battle' ? '对战段位排行榜' : (activeTab === 'rating' ? '等级分排行榜' : '经验排行榜') }}
            </h2>
            <div class="head-sub">
              <span v-if="activeTab === 'battle'">
                实时更新
              </span>
              <span v-else-if="activeTab === 'rating'">
                来自计入等级分的个人赛（初始 1500，参赛越多 K 越小）
              </span>
              <span v-else>
                总经验 = 经验余额 + 经验商店 Tag 花费 + 经验购买颜色花费 · 实时更新
              </span>
            </div>
          </div>

          <!-- 双榜 Tab 切换按钮 -->
          <div class="tab-group">
            <button
              type="button"
              class="tab-btn"
              :class="{ active: activeTab === 'exp' }"
              @click="switchTab('exp')"
            >
              <i class="fa-solid fa-bolt"></i> 经验榜
            </button>
            <button
              type="button"
              class="tab-btn"
              :class="{ active: activeTab === 'battle' }"
              @click="switchTab('battle')"
            >
              <i class="fa-solid fa-ranking-star"></i> 段位天梯榜
            </button>
            <button
              type="button"
              class="tab-btn"
              :class="{ active: activeTab === 'rating' }"
              @click="switchTab('rating')"
            >
              <i class="fa-solid fa-chart-line"></i> 等级分榜
            </button>
          </div>
        </div>
      </div>

      <div v-if="loading && items.length === 0" class="card state-card">
        <span class="loading-spinner"></span> 正在加载排行榜…
      </div>

      <div v-else-if="errorMsg && items.length === 0" class="card error-card">
        <i class="fa-solid fa-circle-exclamation"></i> {{ errorMsg }}
      </div>

      <div v-else-if="activeTab === 'rating'" class="card rating-board">
        <table class="rank-table">
          <thead>
            <tr>
              <th>排名</th>
              <th>选手</th>
              <th>等级分</th>
              <th>最高</th>
              <th>场次</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in items" :key="r.user_number" @click="goUser(r.user_number)">
              <td>#{{ r.rank }}</td>
              <td :style="{ color: rowColor(r) }">
                {{ r.username }}
                <span v-if="r.display_tag" class="rating-tag">{{ r.display_tag }}</span>
              </td>
              <td class="rating-score">{{ r.rating }}</td>
              <td>{{ r.max_rating }}</td>
              <td>{{ r.rated_contests }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="myRank" class="rating-my">
          我的排名 #{{ myRank.rank }} · {{ myRank.username }} · {{ myRank.rating }} 分
        </div>
      </div>

      <div v-else class="rank-content" :class="{ 'is-loading': loading }">
        <!-- Top 3 领奖台 -->
        <div v-if="items.length > 0" class="podium">
          <template v-for="p in podiumOrder" :key="p.user_number">
            <div
              class="podium-item"
              :class="`podium-${p.rank}`"
              @click="goUser(p.user_number)"
            >
              <div class="podium-crown">
                <i :class="podiumIcon(p.rank)"></i>
              </div>
              <img
                v-if="p.avatar_url"
                :src="p.avatar_url"
                class="podium-avatar"
                :style="{ borderColor: rowColor(p) }"
              />
              <div v-else class="podium-avatar podium-avatar-placeholder">
                <i class="fa-solid fa-user"></i>
              </div>
              <div class="podium-name" :style="{ color: rowColor(p) }">
                {{ p.username }}
              </div>
              <div v-if="p.display_tag" class="podium-tag">{{ p.display_tag }}</div>

              <!-- 对战榜显示段位与胜场 -->
              <template v-if="activeTab === 'battle'">
                <div
                  class="podium-tier-tag"
                  :style="{ color: tierColorMap[p.tier || 'bronze'], backgroundColor: `${tierColorMap[p.tier || 'bronze']}22` }"
                >
                  <i :class="['fa-solid', tierIconMap[p.tier || 'bronze'] || 'fa-shield']"></i>
                  {{ p.rank_name }} ({{ p.points }} LP)
                </div>
                <div class="podium-wins">
                  <span class="win-count">{{ p.wins }} 胜</span>
                  <span class="win-rate">({{ p.win_rate }}%)</span>
                </div>
                <div class="podium-exp-label">天梯胜场</div>
              </template>

              <!-- 经验榜显示经验 -->
              <template v-else>
                <div class="podium-exp">{{ formatExp(p.total_experience) }}</div>
                <div class="podium-exp-label">总经验</div>
              </template>
            </div>
          </template>
        </div>

        <!-- 我的排名卡片 -->
        <div v-if="myRank" class="my-rank-card" @click="goUser(myRank.user_number)">
          <div class="my-rank-left">
            <i class="fa-solid fa-user-graduate my-rank-icon"></i>
            <span class="my-rank-label">我的排名</span>
          </div>
          <div class="my-rank-num">
            <span class="my-rank-rank">#{{ myRank.rank }}</span>
            <span class="my-rank-sep">·</span>
            <span class="my-rank-username">{{ myRank.username }}</span>
          </div>

          <div v-if="activeTab === 'battle'" class="my-rank-exp">
            <span class="my-rank-total" :style="{ color: tierColorMap[myRank.tier || 'bronze'] }">
              {{ myRank.rank_name }} ({{ myRank.points }} LP)
            </span>
            <span class="my-rank-detail">
              <strong>{{ myRank.wins }}</strong> 胜 · 共 {{ myRank.total_matches }} 场 (胜率 {{ myRank.win_rate }}%)
            </span>
          </div>

          <div v-else class="my-rank-exp">
            <span class="my-rank-total">{{ formatExp(myRank.total_experience) }}</span>
            <span class="my-rank-detail">
              余额 {{ formatExp(myRank.experience) }} · Tag {{ formatExp(myRank.tag_experience) }} · 颜色 {{ formatExp(myRank.color_experience) }}
            </span>
          </div>
        </div>

        <!-- 4 名及以后列表 -->
        <div v-if="restItems.length > 0" class="card">
          <div class="rank-list">
            <div
              v-for="item in restItems"
              :key="item.user_number"
              class="rank-row"
              :class="{ 'is-me': myRank && item.user_number === myRank.user_number }"
              @click="goUser(item.user_number)"
            >
              <div class="rank-num">{{ item.rank }}</div>
              <img
                v-if="item.avatar_url"
                :src="item.avatar_url"
                class="rank-avatar"
                :style="{ borderColor: rowColor(item) }"
              />
              <div v-else class="rank-avatar rank-avatar-placeholder">
                <i class="fa-solid fa-user"></i>
              </div>
              <div class="rank-user">
                <div
                  class="rank-username"
                  :style="(myRank && item.user_number === myRank.user_number) ? { color: '#4f46e5' } : { color: rowColor(item) }"
                >
                  {{ item.username }}
                </div>
                <div v-if="item.display_tag" class="rank-tag">{{ item.display_tag }}</div>
              </div>

              <!-- 对战榜行右侧 -->
              <div v-if="activeTab === 'battle'" class="rank-battle-info">
                <div class="rank-tier-pill" :style="{ color: tierColorMap[item.tier || 'bronze'], backgroundColor: `${tierColorMap[item.tier || 'bronze']}22` }">
                  <i :class="['fa-solid', tierIconMap[item.tier || 'bronze'] || 'fa-shield']"></i>
                  {{ item.rank_name }}
                  <span class="lp-tag">{{ item.points }} LP</span>
                </div>
                <div class="rank-wins-detail">
                  <span class="win-bold">{{ item.wins }} 胜</span>
                  <span class="sub-matches">/ {{ item.total_matches }} 场 ({{ item.win_rate }}%)</span>
                  <span v-if="item.win_streak && item.win_streak > 0" class="streak-badge">
                    <i class="fa-solid fa-fire"></i> {{ item.win_streak }} 连胜
                  </span>
                </div>
              </div>

              <!-- 经验榜行右侧 -->
              <div v-else class="rank-exp">
                <div class="rank-total">{{ formatExp(item.total_experience) }}</div>
                <div class="rank-detail">
                  余额 {{ formatExp(item.experience) }} · Tag {{ formatExp(item.tag_experience) }} · 颜色 {{ formatExp(item.color_experience) }}
                </div>
              </div>
            </div>
          </div>
        </div>

        <div v-if="items.length === 0" class="card state-card">
          <i class="fa-solid fa-chart-column" style="font-size:32px;color:#cbd5e1;margin-bottom:8px"></i>
          <span v-if="activeTab === 'battle'">暂无对战天梯排名，去打一场 1v1 对战吧！</span>
          <span v-else>暂无用户上榜，快去 AC 题目积累经验吧！</span>
        </div>

        <!-- 分页 -->
        <div v-if="totalPages > 1" class="pagination">
          <button
            type="button"
            class="page-btn"
            :disabled="!canPrev"
            @click="goPage(page - 1)"
          >
            上一页
          </button>
          <span class="page-info">第 {{ page }} / {{ totalPages }} 页（共 {{ total }} 人）</span>
          <button
            type="button"
            class="page-btn"
            :disabled="!canNext"
            @click="goPage(page + 1)"
          >
            下一页
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rating-board { padding: 12px 16px; }
.rating-board .rank-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.rating-board .rank-table th, .rating-board .rank-table td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border-color, #eee); }
.rating-board .rank-table tbody tr { cursor: pointer; }
.rating-score { font-weight: 600; color: #0d47a1; }
.rating-tag { margin-left: 6px; font-size: 12px; opacity: .7; }
.rating-my { margin-top: 10px; font-size: 13px; opacity: .8; }
.ranking-page {
  padding: 32px 16px;
  min-height: calc(100vh - 60px);
}

.ranking-container {
  max-width: 960px;
  margin: 0 auto;
}

.card {
  background: var(--surface-plain);
  border-radius: 12px;
  border: 1px solid var(--border-color);
  box-shadow: var(--shadow-card);
  padding: 24px;
  margin-bottom: 20px;
}

.head-card {
  padding: 24px 32px;
}

.head-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
}

.page-title {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text-main);
}

.head-icon {
  color: #f59e0b;
}

.head-sub {
  margin-top: 6px;
  font-size: 13px;
  color: var(--text-sub);
}

/* Tab 切换 */
.tab-group {
  display: flex;
  gap: 6px;
  background: var(--bg-subtle);
  padding: 4px;
  border-radius: 8px;
}

.tab-btn {
  padding: 8px 18px;
  border: none;
  background: transparent;
  color: var(--text-sub);
  font-weight: 600;
  font-size: 14px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s;
}

.tab-btn.active {
  background: var(--surface-plain);
  color: #3b82f6;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
}

/* 领奖台 */
.podium {
  display: flex;
  justify-content: center;
  align-items: flex-end;
  gap: 16px;
  margin-bottom: 28px;
  padding: 20px 0;
}

.podium-item {
  flex: 1;
  max-width: 220px;
  background: var(--surface-plain);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  padding: 24px 16px 20px;
  text-align: center;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
  box-shadow: var(--shadow-card);
  position: relative;
}

.podium-item:hover {
  transform: translateY(-4px);
  box-shadow: var(--shadow-card-hover);
}

.podium-1 {
  order: 2;
  transform: translateY(-16px);
  border: 2px solid #fbbf24;
}

.podium-1:hover {
  transform: translateY(-20px);
}

.podium-2 {
  order: 1;
  border: 2px solid #94a3b8;
}

.podium-3 {
  order: 3;
  border: 2px solid #d97706;
}

.podium-crown {
  font-size: 26px;
  margin-bottom: 8px;
}

.podium-1 .podium-crown { color: #f59e0b; }
.podium-2 .podium-crown { color: #94a3b8; }
.podium-3 .podium-crown { color: #d97706; }

.podium-avatar {
  width: 58px;
  height: 58px;
  border-radius: 50%;
  object-fit: cover;
  border: 3px solid;
  margin: 0 auto 10px;
}

.podium-avatar-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-subtle);
  color: var(--text-sub);
  font-size: 24px;
}

.podium-name {
  font-size: 15px;
  font-weight: 700;
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.podium-tag {
  display: inline-block;
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 4px;
  background: var(--bg-subtle);
  color: var(--text-main);
  margin-bottom: 6px;
}

.podium-tier-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 12px;
  margin-bottom: 4px;
}

.podium-wins {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 4px;
}

.win-count {
  font-size: 18px;
  font-weight: 800;
  color: #10b981;
}

.win-rate {
  font-size: 12px;
  color: var(--text-sub);
}

.podium-exp {
  font-size: 18px;
  font-weight: 800;
  color: #4f46e5;
}

.podium-exp-label {
  font-size: 11px;
  color: var(--text-sub);
  margin-top: 2px;
}

/* 我的排名卡片 */
.my-rank-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--surface-plain);
  border: 2px dashed #93c5fd;
  border-radius: 12px;
  padding: 14px 24px;
  margin-bottom: 20px;
  cursor: pointer;
}

.my-rank-left {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #2563eb;
  font-weight: 700;
}

.my-rank-num {
  font-size: 15px;
  font-weight: 700;
}

.my-rank-exp {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.my-rank-total {
  font-size: 16px;
  font-weight: 800;
}

.my-rank-detail {
  font-size: 12px;
  color: var(--text-sub);
}

/* 列表展示 */
.rank-list {
  display: flex;
  flex-direction: column;
}

.rank-row {
  display: flex;
  align-items: center;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border-color);
  cursor: pointer;
  transition: background 0.15s;
}

.rank-row:last-child {
  border-bottom: none;
}

.rank-row:hover {
  background: var(--surface-plain);
}

.rank-row.is-me {
  /* 语义 tint 用 color-mix 跟着主题走：写死浅蓝在深色下会变成一条
     浅底浅字的亮带（行内文字读不出来） */
  background: color-mix(in srgb, var(--primary) 10%, transparent);
}

.rank-num {
  width: 44px;
  font-size: 16px;
  font-weight: 800;
  color: var(--text-sub);
}

.rank-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid;
  margin-right: 14px;
}

.rank-avatar-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-subtle);
  color: var(--text-sub);
  font-size: 16px;
}

.rank-user {
  flex: 1;
}

.rank-username {
  font-size: 14px;
  font-weight: 700;
}

.rank-tag {
  font-size: 11px;
  color: var(--text-sub);
  margin-top: 2px;
}

.rank-battle-info {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}

.rank-tier-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 700;
}

.lp-tag {
  font-size: 11px;
  opacity: 0.85;
}

.rank-wins-detail {
  font-size: 12px;
  color: var(--text-sub);
  display: flex;
  align-items: center;
  gap: 6px;
}

.win-bold {
  color: #10b981;
  font-weight: 800;
  font-size: 14px;
}

.streak-badge {
  color: var(--warning-text);
  font-weight: 700;
  background: color-mix(in srgb, var(--warning) 14%, transparent);
  padding: 1px 6px;
  border-radius: 4px;
}

.rank-exp {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.rank-total {
  font-size: 15px;
  font-weight: 800;
  color: var(--text-strong);
}

.rank-detail {
  font-size: 12px;
  color: var(--text-sub);
}

/* 分页 */
.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16px;
  padding: 16px 0;
}

.page-btn {
  padding: 8px 16px;
  background: var(--surface-plain);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-main);
  cursor: pointer;
}

.page-btn:hover:not(:disabled) {
  background: var(--bg-subtle);
}

.page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.page-info {
  font-size: 13px;
  color: var(--text-sub);
}

.state-card, .error-card {
  text-align: center;
  color: var(--text-sub);
  padding: 48px;
}

.error-card {
  color: #ef4444;
}

.loading-spinner {
  display: inline-block;
  width: 16px;
  height: 16px;
  border: 2px solid var(--border-color);
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-right: 8px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 640px) {
  .podium {
    flex-direction: column;
    align-items: center;
  }
  .podium-item {
    width: 100%;
    max-width: 100%;
    transform: none !important;
  }
  .my-rank-card {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  .my-rank-exp {
    align-items: flex-start;
  }
}
</style>
