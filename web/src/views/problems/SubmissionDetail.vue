<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import CodeEditor from '@/components/CodeEditor.vue'
import { submissionsApi } from '@/api/submissions'
import {
  submissionStatusText,
  submissionStatusColor,
  caseStatusText,
} from '@/utils/submissionStatus'
import { fmtDateTime } from '@/utils/datetime'
import type { Submission } from '@/types'

const route = useRoute()
const router = useRouter()

const sub = ref<Submission | null>(null)
const loading = ref(true)
const error = ref('')
let pollTimer: number | null = null
let pollCount = 0

const expandedSubtasks = ref<Record<number, boolean>>({})
const isSubtaskExpanded = (id: number) => {
  return expandedSubtasks.value[id] !== false
}
const toggleSubtask = (id: number) => {
  expandedSubtasks.value[id] = !isSubtaskExpanded(id)
}

const contestId = computed(() => {
  const fromSubmission = Number(sub.value?.contest_id)
  if (Number.isFinite(fromSubmission) && fromSubmission > 0) return fromSubmission
  const fromQuery = parseInt(route.query.contest as string, 10)
  return Number.isFinite(fromQuery) && fromQuery > 0 ? fromQuery : null
})

const isJudging = computed(() =>
  !!sub.value && !sub.value.result_hidden && (sub.value.status === 'pending' || sub.value.status === 'judging')
)

const editorLang = computed(() => {
  const l = sub.value?.language
  return l === 'python3' ? 'python' : l ?? 'cpp'
})

const load = async () => {
  const id = parseInt(route.params.id as string, 10)
  if (!Number.isFinite(id)) return
  try {
    sub.value = await submissionsApi.get(id)
    error.value = ''
    schedulePoll()
  } catch (err: any) {
    error.value = err.response?.data?.detail || '加载失败'
    sub.value = null
    loading.value = false
  }
}

// 评测中每 1.5s 轮询，最多 120 次（3 分钟）
const schedulePoll = () => {
  loading.value = false
  if (!isJudging.value || pollCount >= 120) return
  pollCount++
  pollTimer = window.setTimeout(async () => {
    try {
      const id = parseInt(route.params.id as string, 10)
      sub.value = await submissionsApi.get(id)
    } catch { /* 忽略单次轮询失败 */ }
    schedulePoll()
  }, 1500)
}

onMounted(load)
onBeforeUnmount(() => {
  if (pollTimer) window.clearTimeout(pollTimer)
})
</script>

<template>
  <div class="submission-detail-page">
    <div class="submission-detail-container">
      <div v-if="loading" class="empty">加载中...</div>
      <div v-else-if="error" class="empty">{{ error }}</div>

      <template v-else-if="sub">
        <div class="submission-detail-layout">
        <div class="submission-detail-main">
        <div class="card">
          <div class="d-head">
            <span class="d-title">提交 #{{ sub.id }}</span>
            <span class="status-badge" :style="{ color: submissionStatusColor(sub.status) }">
              {{ submissionStatusText(sub.status) }}
            </span>
            <span v-if="sub.result_hidden" class="oi-tip">OI 赛制进行中，评测结果与分数将在赛后公布</span>
            <span v-if="isJudging" class="judging-tip">评测中，结果稍后自动刷新…</span>
          </div>
          <div class="d-meta">
            <span>题目：<a class="p-link" @click="router.push(`/problems/${sub.problem_id}`)">
              {{ sub.problem_number }} {{ sub.problem_title }}
            </a></span>
            <span>提交者：<b>{{ sub.user?.username }}</b></span>
            <span>语言：<b>{{ sub.language }}</b></span>
            <span>提交时间：<b>{{ fmtDateTime(sub.created_at) }}</b></span>
          </div>
        </div>

        <!-- 评测结果 -->
        <div class="card">
          <div class="section-title">评测结果</div>
          <div v-if="sub.result_hidden" class="empty small">
            OI 赛制比赛进行中，代码已成功提交。评测结果、测试点详情及得分将在比赛结束后统一公布。
          </div>
          <div v-else-if="isJudging" class="empty small">等待评测结果…</div>
          <template v-else>
            <div class="result-summary">
              <div class="result-item">
                <span class="result-label">得分</span>
                <span class="result-value">{{ sub.score }}</span>
              </div>
              <div class="result-item">
                <span class="result-label">耗时</span>
                <span class="result-value">{{ sub.time_used === null || sub.time_used === undefined ? '—' : sub.time_used + ' ms' }}</span>
              </div>
              <div class="result-item">
                <span class="result-label">内存</span>
                <span class="result-value">{{ sub.memory_used === null || sub.memory_used === undefined ? '—' : (sub.memory_used / 1024).toFixed(1) + ' MB' }}</span>
              </div>
            </div>

            <div v-if="sub.error_message" class="error-box">
              <div class="error-title">
                <span>错误信息</span>
                <button type="button" class="code-copy code-copy-light" data-copy>
                  <i class="fa-solid fa-copy" /><span data-copy-label>复制</span>
                </button>
              </div>
              <pre>{{ sub.error_message }}</pre>
            </div>

            <!-- 子任务评测结果（如果有 subtask_results） -->
            <div v-if="sub.subtask_results && sub.subtask_results.length" class="subtask-container">
              <div
                v-for="st in sub.subtask_results"
                :key="st.subtask_id"
                class="subtask-card"
              >
                <div class="subtask-header" @click="toggleSubtask(st.subtask_id)">
                  <div class="subtask-title-group">
                    <i class="fa-solid" :class="isSubtaskExpanded(st.subtask_id) ? 'fa-chevron-down' : 'fa-chevron-right'"></i>
                    <span class="subtask-title">{{ st.name || ('Subtask #' + st.subtask_id) }}</span>
                    <span
                      class="subtask-score-pill"
                      :class="{
                        'pill-pass': st.score > 0 && st.score === st.total_score,
                        'pill-partial': st.score > 0 && st.score < st.total_score,
                        'pill-fail': st.score === 0,
                      }"
                    >
                      {{ st.score }} / {{ st.total_score }} 分
                    </span>
                  </div>
                  <div class="subtask-meta-group">
                    <span class="subtask-status" :style="{ color: submissionStatusColor(st.status) }">
                      {{ submissionStatusText(st.status) }}
                    </span>
                    <span class="subtask-usage">{{ st.time }} ms · {{ (st.memory / 1024).toFixed(1) }} MB</span>
                  </div>
                </div>

                <div v-show="isSubtaskExpanded(st.subtask_id)" class="subtask-body">
                  <table class="case-table">
                    <thead>
                      <tr><th>测试点</th><th>状态</th><th>耗时</th><th>内存</th></tr>
                    </thead>
                    <tbody>
                      <tr v-for="r in st.cases" :key="r.case">
                        <td>#{{ r.case }}</td>
                        <td :style="{ color: r.status === 'accepted' ? '#52c41a' : (r.status === 'skipped' ? '#95a5a6' : 'var(--primary)'), fontWeight: 600 }">
                          {{ caseStatusText(r.status) }}
                        </td>
                        <td>{{ r.status === 'skipped' ? '—' : r.time + ' ms' }}</td>
                        <td>{{ r.status === 'skipped' ? '—' : (r.memory / 1024).toFixed(1) + ' MB' }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <!-- 常规非子任务测试点表格 -->
            <table v-else-if="sub.test_results && sub.test_results.length" class="case-table">
              <thead>
                <tr><th>测试点</th><th>状态</th><th>耗时</th><th>内存</th></tr>
              </thead>
              <tbody>
                <tr v-for="r in sub.test_results" :key="r.case">
                  <td>#{{ r.case }}</td>
                  <td :style="{ color: r.status === 'accepted' ? '#52c41a' : (r.status === 'skipped' ? '#95a5a6' : 'var(--primary)'), fontWeight: 600 }">
                    {{ caseStatusText(r.status) }}
                  </td>
                  <td>{{ r.status === 'skipped' ? '—' : r.time + ' ms' }}</td>
                  <td>{{ r.status === 'skipped' ? '—' : (r.memory / 1024).toFixed(1) + ' MB' }}</td>
                </tr>
              </tbody>
            </table>
          </template>
        </div>

        <!-- 源代码 -->
        <div class="card" v-if="sub.code_visible && sub.code !== undefined">
          <div class="section-title">源代码</div>
          <CodeEditor :model-value="sub.code" :language="editorLang" readonly height="360px" />
        </div>
        <div class="card" v-else-if="!sub.code_visible">
          <div class="section-title">源代码</div>
          <div class="empty small">
            {{ sub.code_hidden_reason || '无权查看他人提交的代码' }}
          </div>
        </div>

        </div>
        <aside class="submission-actions-card">
          <div class="actions-card-title">快速导航</div>
          <button class="action-button" @click="router.push({ path: `/problems/${sub.problem_id}`, ...(contestId ? { query: { contest: String(contestId) } } : {}) })">
            <i class="fa-solid fa-book-open"></i> 返回题目
          </button>
          <button class="action-button" @click="router.push({ path: '/submissions', query: { problem_id: String(sub.problem_id), ...(contestId ? { contest: String(contestId) } : {}) } })">
            <i class="fa-solid fa-list"></i> 提交记录
          </button>
          <button class="action-button" @click="router.push('/problems')">
            <i class="fa-solid fa-arrow-left"></i> 返回题库
          </button>
          <button v-if="contestId" class="action-button action-contest" @click="router.push(`/contest/${contestId}`)">
            <i class="fa-solid fa-trophy"></i> 返回比赛
          </button>
        </aside>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.submission-detail-page {
  min-height: 100vh;
  line-height: 1.5;
}

.submission-detail-container {
  max-width: 1280px;
  margin: 0 auto;
}

.submission-detail-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 210px;
  align-items: start;
  gap: 18px;
}

.submission-detail-main { min-width: 0; }

.submission-actions-card {
  position: sticky;
  top: 88px;
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 16px;
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--surface);
  box-shadow: var(--shadow-card);
}

.actions-card-title {
  margin-bottom: 3px;
  color: var(--text-sub);
  font-size: 13px;
  font-weight: 700;
}

.action-button {
  display: flex;
  min-height: 40px;
  align-items: center;
  gap: 9px;
  padding: 9px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: var(--surface-plain);
  color: var(--text-sub);
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  text-align: left;
}

.action-button:hover { border-color: var(--primary); color: var(--primary); }
.action-button.action-contest { border-color: #e6a23c; background: color-mix(in srgb, var(--warning) 12%, transparent);color: var(--warning-text); }
.action-button.action-contest:hover { border-color: #d99018; background: color-mix(in srgb, var(--warning) 12%, transparent);color: var(--warning-text); }

.card {
  background: var(--surface);
  -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: 20px 24px;
  margin-bottom: 16px;
}

.d-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.d-title {
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--text-strong);
}

.status-badge {
  font-size: 1rem;
  font-weight: 700;
}

.judging-tip {
  color: var(--text-sub);
  font-size: 12px;
}

.oi-tip {
  color: #e67e22;
  font-size: 12px;
  background: rgba(230, 126, 34, 0.1);
  padding: 2px 8px;
  border-radius: 4px;
}

.d-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  margin-top: 10px;
  color: var(--text-sub);
  font-size: 13px;
}

.d-meta b {
  color: var(--text-strong);
}

.p-link {
  color: #3498db;
  cursor: pointer;
}

.p-link:hover {
  text-decoration: underline;
}

.section-title {
  font-size: 1.02rem;
  font-weight: 700;
  color: var(--text-strong);
  border-left: 4px solid var(--primary);
  padding-left: 10px;
  margin-bottom: 14px;
}

.result-summary {
  display: flex;
  gap: 32px;
  margin-bottom: 16px;
}

.result-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.result-label {
  color: var(--text-sub);
  font-size: 12px;
}

.result-value {
  font-size: 1.3rem;
  font-weight: 700;
  color: var(--text-strong);
}

.error-box {
  border: 1px solid #f5b7b1;
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border-radius: 10px;
  padding: 12px 16px;
  margin-bottom: 16px;
}

.error-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: var(--primary);
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
}

.error-box pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 12px;
  color: var(--primary-hover);
  max-height: 300px;
  overflow-y: auto;
}

.subtask-container {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 14px;
}

.subtask-card {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
  background: var(--surface-plain);
  transition: border-color 0.2s;
}

.subtask-card:hover {
  border-color: #cbd5e1;
}

.subtask-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: var(--surface-plain);
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
}

.subtask-header:hover {
  background: var(--bg-subtle);
}

.subtask-title-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.subtask-title-group i {
  font-size: 11px;
  color: var(--text-sub);
  width: 12px;
  text-align: center;
}

.subtask-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-strong);
}

.subtask-score-pill {
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}

.pill-pass {
  background: color-mix(in srgb, var(--success) 10%, transparent);
color: var(--success-text);
  border: 1px solid #b7eb8f;
}

.pill-partial {
  background: color-mix(in srgb, var(--warning) 12%, transparent);
color: var(--warning-text);
  border: 1px solid #ffe58f;
}

.pill-fail {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  color: #ff4d4f;
  border: 1px solid #ffa39e;
}

.subtask-meta-group {
  display: flex;
  align-items: center;
  gap: 14px;
}

.subtask-status {
  font-size: 13px;
  font-weight: 600;
}

.subtask-usage {
  font-size: 12px;
  color: var(--text-sub);
}

.subtask-body {
  border-top: 1px solid #e2e8f0;
  padding: 0;
}

.subtask-body .case-table {
  margin: 0;
}

.subtask-body .case-table th {
  background: var(--surface-plain);
}

.case-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.case-table th {
  text-align: left;
  padding: 9px 12px;
  color: var(--text-sub);
  border-bottom: 2px solid #edf2f7;
}

.case-table td {
  padding: 9px 12px;
  border-bottom: 1px solid #f0f2f5;
}

.empty {
  text-align: center;
  padding: 40px 20px;
  color: var(--text-sub);
}

.empty.small {
  padding: 16px;
}

.back-row {
  text-align: center;
  padding: 4px 0 20px;
}

.btn-back {
  padding: 8px 24px;
  border: 1px solid #e2e8f0;
  background: var(--surface-plain);
  border-radius: 22px;
  font-size: 13px;
  color: var(--text-sub);
  cursor: pointer;
}

.btn-back:hover {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}

/* ===== 手机端 =====
   除了卡片内边距，还修了 .result-summary 缺 flex-wrap 的问题
   （得分/耗时/内存三个指标挤在一行会撑破容器）。===== */
@media (max-width: 600px) {
  .card {
    padding: 16px 14px;
  }

  .result-summary {
    flex-wrap: wrap;
    gap: 12px 24px;
  }
}

@media (max-width: 900px) {
  .submission-detail-layout { grid-template-columns: minmax(0, 1fr) 190px; gap: 12px; }
}

@media (max-width: 700px) {
  .submission-detail-layout { grid-template-columns: 1fr; }
  /* 单栏后 aside 会落回 DOM 末尾沉底，order 提到内容上方 */
  .submission-actions-card {
    order: -1;
    position: static;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .actions-card-title { grid-column: 1 / -1; }
}
</style>
