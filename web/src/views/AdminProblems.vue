<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Swal from 'sweetalert2'
import { problemsApi } from '@/api/problems'
import type { ProblemListItem, ProblemReviewStatus } from '@/types'
import { difficultyColor } from '@/utils/difficulty'
import { userNameColor } from '@/utils/userColor'
import { problemReviewMeta } from '@/utils/problemReview'

const router = useRouter()

const PAGE_SIZE = 20

// 状态筛选：待审核（默认）/ 已驳回 / 已通过 / 全部（主题库所有题）
type FilterKey = 'pending' | 'rejected' | 'approved' | 'all'
const FILTER_TABS: { key: FilterKey; text: string }[] = [
  { key: 'pending', text: '待审核' },
  { key: 'rejected', text: '已驳回' },
  { key: 'approved', text: '已通过' },
  { key: 'all', text: '全部' },
]

const activeFilter = ref<FilterKey>('pending')
const items = ref<ProblemListItem[]>([])
const total = ref(0)
const page = ref(0)  // 与后端一致：0 基（offset = page * page_size）
const loading = ref(true)
const error = ref('')
// 正在操作的题目 id（通过/驳回进行中按钮置灰）
const actingId = ref<number | null>(null)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

const fetchData = async () => {
  loading.value = true
  error.value = ''
  try {
    const data = await problemsApi.list({
      page: page.value,
      page_size: PAGE_SIZE,
      scope: 'review',
      review_status:
        activeFilter.value === 'all' ? undefined : (activeFilter.value as ProblemReviewStatus),
    })
    items.value = data.items || []
    total.value = data.total || 0
  } catch (err: any) {
    error.value = err?.response?.data?.detail || '加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

const switchFilter = (key: FilterKey) => {
  if (key === activeFilter.value) return
  activeFilter.value = key
  page.value = 0
}

// 审核通过：题目立即公开并发放出题人贡献
const approve = async (p: ProblemListItem) => {
  actingId.value = p.id
  try {
    await problemsApi.review(p.id, 'approve')
    await Swal.fire({
      icon: 'success',
      title: `已通过《${p.title}》`,
      timer: 1200,
      showConfirmButton: false,
      allowOutsideClick: false,
    })
    await afterAction()
  } catch (err: any) {
    Swal.fire('操作失败', err?.response?.data?.detail || '请重试', 'error')
  } finally {
    actingId.value = null
  }
}

// 驳回：必须填写原因（作者会在题目页看到）
const reject = async (p: ProblemListItem) => {
  const result = await Swal.fire({
    title: `驳回《${p.title}》`,
    input: 'textarea',
    inputLabel: '驳回原因（必填，将展示给出题人）',
    inputValue: p.review_reason || '',
    inputAttributes: { maxlength: '500' },
    showCancelButton: true,
    confirmButtonText: '确认驳回',
    cancelButtonText: '取消',
    width: '90%',
    allowOutsideClick: false,
    inputValidator: (v) => {
      if (!v || !String(v).trim()) return '请填写驳回原因'
      return undefined
    },
  })
  if (!result.isConfirmed) return

  actingId.value = p.id
  try {
    Swal.showLoading()
    await problemsApi.review(p.id, 'reject', String(result.value).trim())
    Swal.close()
    await afterAction()
  } catch (err: any) {
    Swal.fire('操作失败', err?.response?.data?.detail || '请重试', 'error')
  } finally {
    actingId.value = null
  }
}

// 操作后刷新；当前页空了就回退一页
const afterAction = async () => {
  if (items.value.length === 1 && page.value > 0) page.value -= 1
  else await fetchData()
}

const goPrev = () => { if (page.value > 0) { page.value -= 1 } }
const goNext = () => { if (page.value < totalPages.value - 1) { page.value += 1 } }

watch(activeFilter, fetchData)
watch(page, fetchData)
onMounted(fetchData)
</script>

<template>
  <div class="admin-problem-page">
    <div class="admin-container">
      <div class="page-head">
        <div>
          <h2 class="page-title"><i class="fa-solid fa-gavel"></i> 题目审核</h2>
          <p class="page-sub">
            用户公开的题目会先进入待审核队列，通过后才在题库公开；驳回需填写原因。
          </p>
        </div>
        <div class="page-head-actions">
          <button class="btn-ghost" @click="router.push('/admin/plagiarism')">
            <i class="fa-solid fa-magnifying-glass-chart"></i> 提交查重
          </button>
        </div>
      </div>

      <div class="card">
        <!-- 状态筛选 -->
        <div class="filter-tabs">
          <button
            v-for="t in FILTER_TABS"
            :key="t.key"
            class="filter-tab"
            :class="{ active: activeFilter === t.key }"
            @click="switchFilter(t.key)"
          >{{ t.text }}</button>
        </div>

        <div v-if="loading" class="state-tip">加载中...</div>
        <div v-else-if="error" class="state-tip error">{{ error }}</div>
        <div v-else-if="items.length === 0" class="state-tip">
          <i class="fa-regular fa-circle-check empty-icon"></i>
          <div>暂无{{ FILTER_TABS.find(t => t.key === activeFilter)?.text }}题目</div>
        </div>

        <div v-else class="table-wrap">
          <table class="review-table">
            <thead>
              <tr>
                <th class="col-code">题号</th>
                <th>标题</th>
                <th class="col-author">出题人</th>
                <th class="col-diff">难度</th>
                <th class="col-status">状态</th>
                <th class="col-time">提交时间</th>
                <th class="col-ops">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in items" :key="p.id">
                <td class="col-code">
                  <a class="p-link" @click="router.push(`/problems/${p.id}`)">{{ p.problem_number }}</a>
                </td>
                <td>
                  <a class="p-link p-title" @click="router.push(`/problems/${p.id}`)">{{ p.title }}</a>
                  <div v-if="p.review_status === 'rejected' && p.review_reason" class="reason-line">
                    驳回原因：{{ p.review_reason }}
                  </div>
                </td>
                <td class="col-author">
                  <span v-if="p.author" :style="{ color: userNameColor(p.author) }">{{ p.author.username }}</span>
                  <span v-else class="muted">—</span>
                </td>
                <td class="col-diff">
                  <span class="diff-badge" :style="{ background: difficultyColor(p.difficulty) }">
                    {{ p.difficulty }}
                  </span>
                </td>
                <td class="col-status">
                  <span
                    class="status-badge"
                    :style="{
                      background: problemReviewMeta(p.review_status).bg,
                      color: problemReviewMeta(p.review_status).color,
                    }"
                  >{{ problemReviewMeta(p.review_status).text }}</span>
                </td>
                <td class="col-time">{{ new Date(p.created_at).toLocaleString() }}</td>
                <td class="col-ops">
                  <button
                    v-if="p.review_status !== 'approved'"
                    class="btn-approve"
                    :disabled="actingId === p.id"
                    @click="approve(p)"
                  >通过</button>
                  <button
                    class="btn-reject"
                    :disabled="actingId === p.id"
                    @click="reject(p)"
                  >{{ p.review_status === 'approved' ? '驳回下架' : '驳回' }}</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 分页 -->
        <div v-if="!loading && !error && items.length" class="pagination">
          <button class="page-btn" :disabled="page <= 0" @click="goPrev">上一页</button>
          <span class="page-info">{{ page + 1 }} / {{ totalPages }}（共 {{ total }} 题）</span>
          <button class="page-btn" :disabled="page >= totalPages - 1" @click="goNext">下一页</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-head-actions { display: flex; align-items: center; gap: 8px; }
.btn-ghost { padding: 6px 12px; border: 1px solid var(--border-color, #ddd); background: transparent; border-radius: 6px; cursor: pointer; }
.admin-problem-page {
  padding: 20px 16px 40px;
}

.admin-container {
  max-width: 1100px;
  margin: 0 auto;
}

.page-head {
  margin-bottom: 16px;
}

.page-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-strong);
  margin: 0 0 4px;
}

.page-title i {
  color: var(--primary);
  margin-right: 8px;
}

.page-sub {
  font-size: 13px;
  color: var(--text-sub);
  margin: 0;
}

.card {
  background: var(--surface-plain);
  border-radius: 10px;
  padding: 16px 20px;
  box-shadow: 0 1px 4px rgba(31, 45, 61, 0.06);
}

.filter-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.filter-tab {
  padding: 6px 18px;
  border: 1px solid #e2e8f0;
  background: var(--surface-plain);
  color: var(--text-sub);
  border-radius: 20px;
  font-size: 13px;
  cursor: pointer;
}

.filter-tab.active {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
  font-weight: 600;
}

.state-tip {
  padding: 60px 20px;
  text-align: center;
  color: var(--text-sub);
  font-size: 14px;
}

.state-tip.error {
  color: #e74c3c;
}

.empty-icon {
  font-size: 36px;
  color: #67c23a;
  margin-bottom: 10px;
}

.table-wrap {
  overflow-x: auto;
}

.review-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.review-table th,
.review-table td {
  padding: 12px 10px;
  text-align: left;
  border-bottom: 1px solid #f0f2f5;
  vertical-align: middle;
}

.review-table th {
  color: var(--text-sub);
  font-weight: 600;
  font-size: 12px;
  white-space: nowrap;
}

.col-code { width: 70px; }
.col-author { width: 110px; }
.col-diff { width: 90px; }
.col-status { width: 80px; }
.col-time { width: 170px; white-space: nowrap; color: var(--text-sub); font-size: 12px; }
.col-ops { width: 140px; white-space: nowrap; }

.p-link {
  color: #3498db;
  cursor: pointer;
  text-decoration: none;
}

.p-link:hover {
  text-decoration: underline;
}

.p-title {
  font-weight: 600;
}

.reason-line {
  margin-top: 4px;
  font-size: 12px;
  color: #c0392b;
  line-height: 1.5;
}

.muted {
  color: #b0b7c3;
}

.diff-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  color: #fff;
  font-size: 12px;
  white-space: nowrap;
}

.status-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 12px;
  white-space: nowrap;
}

.btn-approve,
.btn-reject {
  padding: 5px 14px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  border: 1px solid transparent;
  margin-right: 6px;
}

.btn-approve {
  background: var(--bg-subtle);
  color: #67c23a;
  border-color: #c2e7b0;
}

.btn-approve:hover:not(:disabled) {
  background: #67c23a;
  color: #fff;
}

.btn-reject {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  color: #f56c6c;
  border-color: #fbc4c4;
}

.btn-reject:hover:not(:disabled) {
  background: #f56c6c;
  color: #fff;
}

.btn-approve:disabled,
.btn-reject:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 14px;
  margin-top: 18px;
}

.page-btn {
  padding: 6px 16px;
  border: 1px solid #e2e8f0;
  background: var(--surface-plain);
  color: var(--text-sub);
  border-radius: 6px;
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

@media (max-width: 600px) {
  .card {
    padding: 12px;
  }
}
</style>
