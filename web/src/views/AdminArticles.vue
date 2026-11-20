<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Swal from 'sweetalert2'
import {
  articlesApi,
  type ColumnArticleItem,
} from '@/api/columns'
import { userNameColor } from '@/utils/userColor'
import { fmtDateTime } from '@/utils/datetime'
import UserAvatarStatus from '@/components/UserAvatarStatus.vue'

const router = useRouter()

const PAGE_SIZE = 20

// 筛选标签：待审核推荐（默认） / 全部精选推荐
type FilterKey = 'pending' | 'approved'
const FILTER_TABS: { key: FilterKey; text: string }[] = [
  { key: 'pending', text: '待审核推荐' },
  { key: 'approved', text: '全站精选库' },
]

const activeFilter = ref<FilterKey>('pending')
const items = ref<ColumnArticleItem[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(true)
const error = ref('')
const actingId = ref<number | null>(null)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

const letterAvatar = (name: string) => {
  const ch = (name || 'U').trim().charAt(0).toUpperCase() || 'U'
  return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Crect width='40' height='40' fill='%23e74c3c'/%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' dy='.3em' fill='white' font-size='16' font-family='Arial'%3E${encodeURIComponent(ch)}%3C/text%3E%3C/svg%3E`
}

const fetchData = async () => {
  loading.value = true
  error.value = ''
  try {
    if (activeFilter.value === 'pending') {
      const res = await articlesApi.getPendingRecommendations({
        page: page.value,
        page_size: PAGE_SIZE,
      })
      items.value = res.items || []
      total.value = res.total || 0
    } else {
      const res = await articlesApi.list({
        page: page.value,
        page_size: PAGE_SIZE,
        is_recommended: true,
      })
      items.value = res.items || []
      total.value = res.total || 0
    }
  } catch (err: any) {
    error.value = err?.response?.data?.detail || '加载推荐审核列表失败'
  } finally {
    loading.value = false
  }
}

const switchFilter = (key: FilterKey) => {
  if (key === activeFilter.value) return
  activeFilter.value = key
  page.value = 1
}

// 审核通过
const approve = async (item: ColumnArticleItem) => {
  actingId.value = item.id
  try {
    await articlesApi.reviewRecommend(item.id, { action: 'approve' })
    await Swal.fire({
      icon: 'success',
      title: `已通过《${item.title}》的全站推荐`,
      text: '已自动为作者发放 20 点社区贡献值',
      timer: 1500,
      showConfirmButton: false,
    })
    await afterAction()
  } catch (err: any) {
    Swal.fire('审核操作失败', err?.response?.data?.detail || err.message, 'error')
  } finally {
    actingId.value = null
  }
}

// 审核驳回：必须填写原因
const reject = async (item: ColumnArticleItem) => {
  const result = await Swal.fire({
    title: `驳回《${item.title}》推荐`,
    input: 'textarea',
    inputLabel: '驳回原因（必填，将展示给作者）',
    inputValue: item.recommend_reason || '',
    inputPlaceholder: '例如：思路解析需更详尽、LaTeX 公式或代码排版需调整等',
    inputAttributes: { maxlength: '500' },
    showCancelButton: true,
    confirmButtonText: '确认驳回',
    cancelButtonText: '取消',
    inputValidator: (v) => {
      if (!v || !String(v).trim()) return '请填写驳回原因'
      return undefined
    },
  })
  if (!result.isConfirmed) return

  actingId.value = item.id
  try {
    await articlesApi.reviewRecommend(item.id, {
      action: 'reject',
      reason: String(result.value).trim(),
    })
    await Swal.fire({
      icon: 'info',
      title: '已驳回全站推荐申请',
      timer: 1200,
      showConfirmButton: false,
    })
    await afterAction()
  } catch (err: any) {
    Swal.fire('驳回失败', err?.response?.data?.detail || err.message, 'error')
  } finally {
    actingId.value = null
  }
}

// 取消推荐（对于已精选库）
const cancelRecommend = async (item: ColumnArticleItem) => {
  const res = await Swal.fire({
    title: `取消《${item.title}》全站推荐？`,
    text: '取消后将不再在广场精选流与题解区默认高亮展示。',
    icon: 'question',
    showCancelButton: true,
    confirmButtonText: '确认取消',
    cancelButtonText: '暂不操作',
  })
  if (!res.isConfirmed) return

  actingId.value = item.id
  try {
    await articlesApi.toggleRecommend(item.id, false)
    await afterAction()
  } catch (err: any) {
    Swal.fire('操作失败', err?.response?.data?.detail || err.message, 'error')
  } finally {
    actingId.value = null
  }
}

const afterAction = async () => {
  if (items.value.length === 1 && page.value > 1) page.value -= 1
  else await fetchData()
}

const goPrev = () => { if (page.value > 1) { page.value -= 1 } }
const goNext = () => { if (page.value < totalPages.value) { page.value += 1 } }

watch(activeFilter, fetchData)
watch(page, fetchData)
onMounted(fetchData)
</script>

<template>
  <div class="admin-articles-page">
    <div class="admin-container">
      <div class="page-head">
        <div>
          <h2 class="page-title"><i class="fa-solid fa-newspaper"></i> 题解与文章推荐审核</h2>
          <p class="page-sub">
            审核作者申请的全站推荐文章与题目题解；通过后将公开展示在文章广场精选流与对应题目的题解专区，并为作者发放 20 点社区贡献值。
          </p>
        </div>
      </div>

      <div class="card">
        <div class="filter-tabs">
          <button
            v-for="t in FILTER_TABS"
            :key="t.key"
            class="filter-tab-btn"
            :class="{ active: activeFilter === t.key }"
            @click="switchFilter(t.key)"
          >
            {{ t.text }}
          </button>
        </div>

        <div v-if="loading" class="empty-state">
          <i class="fa-solid fa-spinner fa-spin"></i> 正在加载审核列表...
        </div>
        <div v-else-if="error" class="empty-state error">
          <i class="fa-solid fa-circle-exclamation"></i> {{ error }}
        </div>
        <div v-else-if="items.length === 0" class="empty-state">
          <i class="fa-regular fa-folder-open"></i>
          {{ activeFilter === 'pending' ? '当前暂无待审核的推荐申请' : '暂无精选推荐文章' }}
        </div>

        <div v-else class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th style="width: 60px;">ID</th>
                <th>文章标题</th>
                <th style="width: 100px;">分类</th>
                <th style="width: 160px;">关联题目</th>
                <th style="width: 140px;">作者</th>
                <th>申请理由 / 摘要</th>
                <th style="width: 140px;">提交时间</th>
                <th style="width: 180px; text-align: right;">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in items" :key="item.id">
                <td class="id-cell">#{{ item.id }}</td>
                <td>
                  <router-link :to="`/article/${item.id}`" class="title-link" target="_blank">
                    {{ item.title }}
                    <i class="fa-solid fa-arrow-up-right-from-square title-ext-icon"></i>
                  </router-link>
                </td>
                <td>
                  <span class="cat-pill" :class="{ 'cat-sol': item.category === '题解' }">
                    {{ item.category || '算法理论' }}
                  </span>
                </td>
                <td>
                  <router-link
                    v-if="item.problem_code || item.problem_id"
                    :to="`/problem/${item.problem_code || (item.problem_id ? 'P' + (1000 + item.problem_id) : '')}/solutions`"
                    class="prob-link"
                    target="_blank"
                  >
                    <i class="fa-solid fa-lightbulb"></i>
                    {{ item.problem_code || (item.problem_id ? 'P' + (1000 + item.problem_id) : '') }}
                    <span v-if="item.problem_title" class="prob-title-sub">({{ item.problem_title }})</span>
                  </router-link>
                  <span v-else class="text-muted">-</span>
                </td>
                <td>
                  <div class="author-cell" v-if="item.author">
                    <UserAvatarStatus :user="item.author" :size="6">
                      <img
                        :src="item.author.avatar_url || letterAvatar(item.author.username)"
                        :alt="item.author.username"
                      />
                    </UserAvatarStatus>
                    <router-link
                      :to="`/user/${item.author.user_number}`"
                      class="author-name"
                      :style="{ color: userNameColor(item.author) }"
                      target="_blank"
                    >
                      {{ item.author.username }}
                    </router-link>
                  </div>
                  <span v-else class="text-muted">-</span>
                </td>
                <td>
                  <div class="reason-cell">
                    <span v-if="item.recommend_reason" class="reason-text">
                      <i class="fa-solid fa-quote-left quote-icon"></i> {{ item.recommend_reason }}
                    </span>
                    <span v-else-if="item.summary" class="summary-text">{{ item.summary }}</span>
                    <span v-else class="text-muted">（未填写）</span>
                  </div>
                </td>
                <td class="time-cell">{{ fmtDateTime(item.created_at) }}</td>
                <td class="action-cell">
                  <template v-if="activeFilter === 'pending'">
                    <button
                      class="btn-act btn-approve"
                      :disabled="actingId === item.id"
                      @click="approve(item)"
                    >
                      <i class="fa-solid fa-check"></i> 通过
                    </button>
                    <button
                      class="btn-act btn-reject"
                      :disabled="actingId === item.id"
                      @click="reject(item)"
                    >
                      <i class="fa-solid fa-xmark"></i> 驳回
                    </button>
                  </template>
                  <template v-else>
                    <button
                      class="btn-act btn-cancel-rec"
                      :disabled="actingId === item.id"
                      @click="cancelRecommend(item)"
                    >
                      <i class="fa-solid fa-star-half-stroke"></i> 取消精选
                    </button>
                  </template>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 分页 -->
        <div v-if="total > PAGE_SIZE" class="pagination-bar">
          <button class="page-btn" :disabled="page <= 1" @click="goPrev">上一页</button>
          <span class="page-info">第 {{ page }} / {{ totalPages }} 页（共 {{ total }} 条）</span>
          <button class="page-btn" :disabled="page >= totalPages" @click="goNext">下一页</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.admin-articles-page {
  min-height: 100vh;
  padding: 24px 20px 60px;
  line-height: 1.5;
}

.admin-container {
  max-width: 1400px;
  margin: 0 auto;
}

.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-title {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 700;
  color: var(--text-strong);
  display: flex;
  align-items: center;
  gap: 10px;
}

.page-sub {
  margin: 0;
  font-size: 13px;
  color: var(--text-sub);
}

.card {
  background: var(--surface);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: 20px 24px;
}

.filter-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 18px;
  border-bottom: 1px solid var(--border-color);
  padding-bottom: 12px;
}

.filter-tab-btn {
  padding: 6px 16px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-sub);
  cursor: pointer;
  transition: all 0.2s;
}

.filter-tab-btn.active {
  background: var(--primary);
  color: #fff;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 60px 20px;
  color: var(--text-sub);
  font-size: 14px;
}

.empty-state.error {
  color: var(--danger, #ef4444);
}

.table-wrap {
  overflow-x: auto;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.data-table th {
  text-align: left;
  padding: 10px 12px;
  color: var(--text-sub);
  font-weight: 600;
  border-bottom: 1px solid var(--border-color);
  background: var(--surface-plain);
}

.data-table td {
  padding: 12px;
  border-bottom: 1px solid var(--border-color);
  color: var(--text-main);
  vertical-align: middle;
}

.id-cell {
  font-family: monospace;
  color: var(--text-sub);
}

.title-link {
  font-weight: 600;
  color: var(--text-strong);
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  line-height: 1.4;
}

.title-link:hover {
  color: var(--primary);
  text-decoration: underline;
}

.title-ext-icon {
  font-size: 10px;
  color: var(--text-sub);
}

.cat-pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  background: var(--surface-plain);
  border: 1px solid var(--border-color);
  color: var(--text-sub);
}

.cat-pill.cat-sol {
  background: rgba(245, 158, 11, 0.12);
  border-color: rgba(245, 158, 11, 0.3);
  color: #b45309;
}

.prob-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 600;
  color: #d97706;
  text-decoration: none;
}

.prob-link:hover {
  text-decoration: underline;
}

.prob-title-sub {
  font-weight: 400;
  color: var(--text-sub);
  font-size: 11px;
  max-width: 90px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.author-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.author-name {
  font-weight: 600;
  text-decoration: none;
  font-size: 13px;
}

.author-name:hover {
  text-decoration: underline;
}

.reason-cell {
  max-width: 320px;
  line-height: 1.4;
}

.quote-icon {
  color: #f59e0b;
  font-size: 10px;
}

.reason-text {
  color: var(--text-strong);
  font-size: 12px;
}

.summary-text {
  color: var(--text-sub);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.text-muted {
  color: var(--text-sub);
}

.time-cell {
  font-size: 12px;
  color: var(--text-sub);
  white-space: nowrap;
}

.action-cell {
  text-align: right;
  white-space: nowrap;
}

.btn-act {
  padding: 5px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid transparent;
  cursor: pointer;
  margin-left: 6px;
  transition: all 0.2s;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.btn-approve {
  background: #10b981;
  color: #fff;
}

.btn-approve:hover:not(:disabled) {
  background: #059669;
}

.btn-reject {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
  border-color: rgba(239, 68, 68, 0.3);
}

.btn-reject:hover:not(:disabled) {
  background: #ef4444;
  color: #fff;
}

.btn-cancel-rec {
  background: rgba(245, 158, 11, 0.1);
  color: #b45309;
  border-color: rgba(245, 158, 11, 0.3);
}

.btn-cancel-rec:hover:not(:disabled) {
  background: #f59e0b;
  color: #fff;
}

.btn-act:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.pagination-bar {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16px;
  margin-top: 20px;
}

.page-btn {
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid var(--border-color);
  background: var(--surface);
  cursor: pointer;
  font-size: 13px;
}

.page-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.page-info {
  font-size: 13px;
  color: var(--text-sub);
}
</style>
