<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import Swal from 'sweetalert2'
import { useAuthStore } from '@/stores/auth'
import { isSuperAdmin } from '@/utils/permissions'
import { submissionsApi } from '@/api/submissions'
import { submissionStatusText, submissionStatusColor } from '@/utils/submissionStatus'
import { fmtDateTime } from '@/utils/datetime'
import type { Submission } from '@/types'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const PAGE_SIZE = 20

const problemFilter = computed(() => {
  const p = parseInt(route.query.problem_id as string, 10)
  return Number.isFinite(p) && p > 0 ? p : null
})
// 能否批量重测/取消成绩：超管/题管
const canRejudge = computed(() => {
  const u = authStore.currentUser
  if (!u || !problemFilter.value) return false
  return isSuperAdmin(u) || u.can_manage_problems === true
})

const page = computed({
  get: () => {
    const p = parseInt(route.query.page as string, 10)
    return Number.isFinite(p) && p > 0 ? p : 0
  },
  set: (v: number) => updateQuery({ page: v > 0 ? String(v) : undefined }),
})

const updateQuery = (patch: Record<string, string | undefined>) => {
  const merged: Record<string, string> = {}
  for (const [k, v] of Object.entries({ ...route.query, ...patch })) {
    if (v) merged[k] = String(v)
  }
  router.replace({ query: merged })
}

const items = ref<Submission[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const rejudgeScore = ref<0 | 100 | null>(100)
const rejudging = ref(false)

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

const fetchData = async () => {
  loading.value = true
  error.value = ''
  try {
    const data = problemFilter.value
      ? await submissionsApi.listByProblem(problemFilter.value, {
          page: page.value,
          page_size: PAGE_SIZE,
        })
      : await submissionsApi.listMine({ page: page.value, page_size: PAGE_SIZE })
    items.value = data.items || []
    total.value = data.total || 0
  } catch (err: any) {
    error.value = err.response?.data?.detail || err.message || '加载失败'
  } finally {
    loading.value = false
  }
}

const rejudgeSubmissions = async () => {
  if (!problemFilter.value || rejudging.value) return
  const txt = rejudgeScore.value === null ? '全部' : `${rejudgeScore.value} 分`
  const res = await Swal.fire({
    title: '确认批量重测？',
    text: `将重测该题${txt}的历史提交。`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonText: '确认重测',
    cancelButtonText: '取消',
  })
  if (!res.isConfirmed) return

  rejudging.value = true
  try {
    const r = await submissionsApi.rejudge(problemFilter.value, rejudgeScore.value)
    await Swal.fire(
      '已加入重测队列',
      `已排队 ${r.queued} 条，${r.skipped} 条正在评测或已跳过。`,
      'success',
    )
    fetchData()
  } catch (err: any) {
    Swal.fire('重测失败', err.response?.data?.detail || err.message || '请重试', 'error')
  } finally {
    rejudging.value = false
  }
}

const cancelScore = ref<0 | 100 | null>(100)
const cancelling = ref(false)

const rejudgeOne = async (id: number) => {
  const res = await Swal.fire({
    title: '确认重测该提交？',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonText: '确认重测',
    cancelButtonText: '取消',
  })
  if (!res.isConfirmed) return
  try {
    await submissionsApi.rejudgeOne(id)
    Swal.fire('已加入重测队列', '', 'success')
    fetchData()
  } catch (err: any) {
    Swal.fire('重测失败', err.response?.data?.detail || err.message || '请重试', 'error')
  }
}

const cancelScoreOne = async (id: number) => {
  const res = await Swal.fire({
    title: '确认取消该提交成绩？',
    text: '此操作不可撤销，提交数与通过数会回滚，首次 AC 经验会扣回。',
    icon: 'error',
    showCancelButton: true,
    confirmButtonText: '确认取消',
    cancelButtonText: '取消',
  })
  if (!res.isConfirmed) return
  try {
    await submissionsApi.cancelScoreOne(id)
    Swal.fire('已取消成绩', '', 'success')
    fetchData()
  } catch (err: any) {
    Swal.fire('取消失败', err.response?.data?.detail || err.message || '请重试', 'error')
  }
}

const cancelSubmissionsScore = async () => {
  if (!problemFilter.value || cancelling.value) return
  const txt = cancelScore.value === null ? '全部' : `${cancelScore.value} 分`
  const res = await Swal.fire({
    title: '确认批量取消成绩？',
    text: `将取消该题${txt}的历史提交成绩（提交数与通过数会回滚，首次 AC 经验会扣回）。此操作不可撤销。`,
    icon: 'error',
    showCancelButton: true,
    confirmButtonText: '确认取消',
    cancelButtonText: '取消',
  })
  if (!res.isConfirmed) return

  cancelling.value = true
  try {
    const r = await submissionsApi.cancelScore(problemFilter.value, cancelScore.value)
    await Swal.fire('已取消成绩', `已取消 ${r.cancelled} 条，${r.skipped} 条已跳过。`, 'success')
    fetchData()
  } catch (err: any) {
    Swal.fire('取消失败', err.response?.data?.detail || err.message || '请重试', 'error')
  } finally {
    cancelling.value = false
  }
}

watch(() => route.fullPath, fetchData)
onMounted(fetchData)
</script>

<template>
  <div class="submission-list-page">
    <div class="submission-list-container">
      <div class="page-head">
        <div>
          <h2 class="page-title">评测记录</h2>
          <p class="page-sub">
            {{ problemFilter ? `查看题目的全部提交记录` : '我的全部提交记录' }}
          </p>
        </div>
      </div>

      <div v-if="canRejudge" class="card rejudge-card">
        <div class="rejudge-copy">
          <strong>批量重测</strong>
        </div>
        <div class="rejudge-actions">
          <label>
            重测范围
            <select v-model="rejudgeScore" :disabled="rejudging">
              <option :value="100">100 分提交</option>
              <option :value="0">0 分提交</option>
              <option :value="null">全部提交</option>
            </select>
          </label>
          <button class="btn-rejudge" :disabled="rejudging" @click="rejudgeSubmissions">
            {{ rejudging ? '排队中…' : '批量重测' }}
          </button>
        </div>
      </div>

      <div v-if="canRejudge" class="card cancel-card">
        <div class="rejudge-copy">
          <strong>取消成绩</strong>
        </div>
        <div class="rejudge-actions">
          <label>
            取消范围
            <select v-model="cancelScore" :disabled="cancelling">
              <option :value="100">100 分提交</option>
              <option :value="0">0 分提交</option>
              <option :value="null">全部提交</option>
            </select>
          </label>
          <button class="btn-cancel-score" :disabled="cancelling" @click="cancelSubmissionsScore">
            {{ cancelling ? '处理中…' : '批量取消成绩' }}
          </button>
        </div>
      </div>

      <div class="card">
        <div class="result-count">共 {{ total }} 条记录</div>

        <div v-if="loading" class="loading-state">
          <span class="loading-spinner"></span>
          <span>评测记录加载中…</span>
        </div>
        <div v-else-if="error" class="empty">{{ error }}</div>
        <div v-else-if="items.length === 0" class="empty">暂无提交记录</div>

        <div v-else class="table-wrap">
          <table class="sub-table">
            <thead>
              <tr>
                <th>提交编号</th>
                <th>题目</th>
                <th v-if="problemFilter">提交者</th>
                <th>得分</th>
                <th>状态</th>
                <th>耗时</th>
                <th>内存</th>
                <th>语言</th>
                <th>提交时间</th>
                <th v-if="canRejudge">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in items" :key="s.id" class="row-click" @click="router.push(`/submissions/${s.id}`)">
                <td class="col-no">#{{ s.id }}</td>
                <td>
                  <span class="p-link" @click.stop="router.push(`/problems/${s.problem_id}`)">
                    {{ s.problem_number }} {{ s.problem_title }}
                  </span>
                </td>
                <td v-if="problemFilter" class="col-user">{{ s.user?.username }}</td>
                <td class="col-num">{{ s.score }}</td>
                <td>
                  <span class="status-text" :style="{ color: submissionStatusColor(s.status) }">
                    {{ submissionStatusText(s.status) }}
                  </span>
                </td>
                <td class="col-num">{{ s.time_used === null || s.time_used === undefined ? '—' : s.time_used + ' ms' }}</td>
                <td class="col-num">{{ s.memory_used === null || s.memory_used === undefined ? '—' : (s.memory_used / 1024).toFixed(1) + ' MB' }}</td>
                <td>{{ s.language }}</td>
                <td class="col-time">{{ fmtDateTime(s.created_at) }}</td>
                <td v-if="canRejudge" class="col-actions" @click.stop>
                  <button
                    class="btn-row-rejudge"
                    :disabled="s.status === 'pending' || s.status === 'judging'"
                    @click="rejudgeOne(s.id)"
                  >重测</button>
                  <button
                    class="btn-row-cancel"
                    :disabled="s.status === 'pending' || s.status === 'judging' || s.status === 'cancelled'"
                    @click="cancelScoreOne(s.id)"
                  >取消成绩</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="pagination" v-if="pageCount > 1">
          <button class="page-btn" :disabled="page === 0" @click="page = page - 1">&laquo;</button>
          <span class="page-info">第 {{ page + 1 }} / {{ pageCount }} 页</span>
          <button class="page-btn" :disabled="page >= pageCount - 1" @click="page = page + 1">&raquo;</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.submission-list-page {
  min-height: 100vh;
  line-height: 1.5;
}

.submission-list-container {
  max-width: 1100px;
  margin: 0 auto;
}

.page-head {
  margin-bottom: 16px;
}

.page-title {
  font-size: 1.3rem;
  font-weight: 700;
  color: var(--text-strong);
}

.page-sub {
  color: var(--text-sub);
  font-size: 13px;
  margin-top: 4px;
}

.rejudge-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 18px;
  margin-bottom: 16px;
}

.rejudge-copy {
  display: flex;
  flex-direction: column;
  gap: 3px;
  color: var(--text-sub);
  font-size: 12px;
}

.rejudge-copy strong {
  color: var(--text-strong);
  font-size: 14px;
}

.rejudge-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
  color: var(--text-sub);
  font-size: 13px;
}

.rejudge-actions label {
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.rejudge-actions select {
  padding: 6px 8px;
  border: 1px solid #d9e2ec;
  border-radius: 6px;
  color: var(--text-strong);
  background: var(--surface-plain);
}

.btn-rejudge {
  padding: 7px 14px;
  border: 1px solid #e67e22;
  border-radius: 7px;
  color: #fff;
  background: #e67e22;
  cursor: pointer;
}

.btn-rejudge:hover:not(:disabled) {
  background: #d35400;
  border-color: #d35400;
}

.btn-rejudge:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.cancel-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 18px;
  margin-bottom: 16px;
}

.btn-cancel-score {
  padding: 7px 14px;
  border: 1px solid #e74c3c;
  border-radius: 7px;
  color: #fff;
  background: #e74c3c;
  cursor: pointer;
}
.btn-cancel-score:hover:not(:disabled) {
  background: #c0392b;
  border-color: #c0392b;
}
.btn-cancel-score:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.col-actions {
  white-space: nowrap;
}
.btn-row-rejudge,
.btn-row-cancel {
  padding: 3px 10px;
  margin-right: 6px;
  border-radius: 5px;
  font-size: 12px;
  cursor: pointer;
  border: 1px solid transparent;
}
.btn-row-rejudge {
  background: #e67e22;
  color: #fff;
  border-color: #e67e22;
}
.btn-row-rejudge:hover:not(:disabled) {
  background: #d35400;
}
.btn-row-cancel {
  background: var(--surface-plain);
  color: #e74c3c;
  border-color: #e74c3c;
}
.btn-row-cancel:hover:not(:disabled) {
  background: #e74c3c;
  color: #fff;
}
.btn-row-rejudge:disabled,
.btn-row-cancel:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* 背景/圆角/边框/阴影由全局 .card 基类统一提供（亚克力），这里只管布局 */
.card {
  padding: 20px 24px;
}

.result-count {
  color: var(--text-sub);
  font-size: 13px;
  margin-bottom: 8px;
}

.table-wrap {
  overflow-x: auto;
}

.sub-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.sub-table th {
  text-align: left;
  padding: 11px 12px;
  color: var(--text-sub);
  font-size: 13px;
  border-bottom: 2px solid #edf2f7;
  white-space: nowrap;
}

.sub-table td {
  padding: 13px 12px;
  border-bottom: 1px solid #f0f2f5;
}

.row-click {
  cursor: pointer;
  transition: background 0.15s;
}

.row-click:hover {
  background: color-mix(in srgb, var(--primary) 6%, transparent);
}

.col-no {
  color: var(--text-sub);
  white-space: nowrap;
}

.col-user {
  font-weight: 600;
  white-space: nowrap;
}

.col-num,
.col-time {
  color: var(--text-sub);
  white-space: nowrap;
  font-size: 13px;
}

.p-link {
  color: #3498db;
  cursor: pointer;
}

.p-link:hover {
  text-decoration: underline;
}

.status-text {
  font-weight: 600;
  white-space: nowrap;
}

.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 10px;
  padding: 18px 0 4px;
}

.page-btn {
  padding: 6px 12px;
  border: 1px solid #e2e8f0;
  background: var(--surface-plain);
  border-radius: 8px;
  font-size: 13px;
  color: var(--text-sub);
  cursor: pointer;
}

.page-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.page-info {
  font-size: 13px;
  color: var(--text-sub);
}

.empty {
  text-align: center;
  padding: 60px 20px;
  color: var(--text-sub);
}

/* ===== 手机端：原本无任何媒体查询 ===== */
@media (max-width: 600px) {
  .card {
    padding: 16px 14px;
  }

  .rejudge-card {
    align-items: stretch;
    flex-direction: column;
  }

  .cancel-card {
    align-items: stretch;
    flex-direction: column;
  }

  .rejudge-actions {
    flex-wrap: wrap;
  }
}
</style>
