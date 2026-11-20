<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { problemsApi } from '@/api/problems'
import type { ProblemListItem } from '@/types'
import { DIFFICULTY_LIST, difficultyColor } from '@/utils/difficulty'
import { useDifficultyReveal } from '@/utils/academicMode'
import { problemUserStatusMeta } from '@/utils/submissionStatus'
import { problemReviewMeta } from '@/utils/problemReview'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

// 严格只认题目管理权限
const canManage = computed(() => !!authStore.currentUser?.can_manage_problems)

// 学术模式：难度默认收起，想看得一道一道点开（刷新即恢复隐藏）
const { isDifficultyVisible, revealDifficulty } = useDifficultyReveal()
// 登录用户均可提交新题
const canCreate = computed(() => !!authStore.currentUser)

// 视图范围：public 题库（默认） / mine 我的题目
const scope = computed<'public' | 'mine'>(() =>
  route.query.scope === 'mine' ? 'mine' : 'public'
)
const setScope = (s: 'public' | 'mine') =>
  updateQuery({ scope: s === 'public' ? undefined : s, page: undefined })

const PAGE_SIZE = 20

// 筛选条件放入 URL query（刷新 / 后退均保持），与 Tickets.vue 同一套路
const difficultyFilter = computed({
  get: () => (route.query.difficulty as string) || '',
  set: (v: string) => updateQuery({ difficulty: v || undefined, page: undefined }),
})
const sourceFilter = computed({
  get: () => (route.query.source as string) || '',
  set: (v: string) => updateQuery({ source: v || undefined, page: undefined }),
})
// 有题目管理权限的人默认可见未公开题（后端行为），列表中以「未公开」徽章标注

// 关键词是「应用后」才进 URL：输入框是本地态，点搜索 / 回车才生效
const keywordInput = ref((route.query.keyword as string) || '')

// 页码（0-based，与后端一致）
const page = computed({
  get: () => {
    const p = parseInt(route.query.page as string, 10)
    return Number.isFinite(p) && p > 0 ? p : 0
  },
  set: (v: number) => updateQuery({ page: v > 0 ? String(v) : undefined }),
})

// 统一更新 URL query（空值移除，避免脏参数）
const updateQuery = (patch: Record<string, string | undefined>) => {
  const merged: Record<string, string> = {}
  for (const [k, v] of Object.entries({ ...route.query, ...patch })) {
    if (v) merged[k] = String(v)
  }
  router.replace({ query: merged })
}

const applyFilters = () => {
  // 搜索视为回到第一页
  const merged: Record<string, string> = {}
  for (const [k, v] of Object.entries({
    difficulty: difficultyFilter.value,
    source: sourceFilter.value,
    keyword: keywordInput.value.trim(),
  })) {
    if (v) merged[k] = String(v)
  }
  router.replace({ query: merged })
}

const resetFilters = () => {
  keywordInput.value = ''
  router.replace({ query: {} })
}

const items = ref<ProblemListItem[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const sources = ref<string[]>([])

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

// 数字分页：首尾 + 当前页邻域，超过窗口画省略号（-1 哨兵）
const pagesToShow = computed<number[]>(() => {
  const n = pageCount.value
  const cur = page.value
  if (n <= 7) return Array.from({ length: n }, (_, i) => i)
  const wanted = new Set<number>([0, n - 1, cur - 1, cur, cur + 1])
  const arr = [...wanted].filter((p) => p >= 0 && p < n).sort((a, b) => a - b)
  const out: number[] = []
  let prev = -2
  for (const p of arr) {
    if (prev !== -2 && p - prev > 1) out.push(-1)
    out.push(p)
    prev = p
  }
  return out
})

const fetchData = async () => {
  loading.value = true
  error.value = ''
  try {
    const data = await problemsApi.list({
      page: page.value,
      page_size: PAGE_SIZE,
      difficulty: difficultyFilter.value || undefined,
      source: sourceFilter.value || undefined,
      keyword: (route.query.keyword as string) || undefined,
      scope: scope.value,
    })
    items.value = data.items || []
    total.value = data.total || 0
  } catch (err: any) {
    error.value = err.response?.data?.detail || err.message || '加载失败'
  } finally {
    loading.value = false
  }
}

// ==================== 我的题库：提交进主题库 ====================
const submittingId = ref<number | null>(null)

/** 我的题库里，还没进主题库、也不在审核中的题，可以提交 */
const canSubmitToLibrary = (p: any) =>
  scope.value === 'mine' && !p.is_official && p.review_status !== 'pending'

const handleSubmitToLibrary = async (p: any) => {
  const confirmRes = await Swal.fire({
    title: '提交进主题库？',
    text: '提交后进入管理员审核队列，通过后题目正式进入主题库（编号由 U 转 P）。',
    icon: 'question',
    showCancelButton: true,
    confirmButtonText: '提交审核',
    cancelButtonText: '取消',
    confirmButtonColor: 'var(--primary)',
    cancelButtonColor: '#909399',
  })
  if (!confirmRes.isConfirmed) return
  submittingId.value = p.id
  try {
    await problemsApi.submitToLibrary(p.id)
    Swal.fire({ icon: 'success', title: '已提交，等待审核', timer: 1400, showConfirmButton: false })
    await fetchData()
  } catch (err: any) {
    Swal.fire({
      icon: 'error',
      title: '提交失败',
      text: err.response?.data?.detail || err.message || '未知错误',
    })
  } finally {
    submittingId.value = null
  }
}

const loadSources = async () => {
  try {
    sources.value = await problemsApi.sources()
  } catch {
    sources.value = []
  }
}

import Swal from 'sweetalert2'

const zipListInputRef = ref<HTMLInputElement | null>(null)
const importingZip = ref(false)

function escapeHtml(str: any): string {
  if (str === null || str === undefined) return ''
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

const handleZipListImport = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const fileList = input.files ? Array.from(input.files) : []
  input.value = ''
  if (!fileList.length) return

  const nonZip = fileList.filter((f) => !f.name.toLowerCase().endsWith('.zip'))
  if (nonZip.length > 0) {
    Swal.fire({
      icon: 'warning',
      title: '格式错误',
      text: `仅支持 .zip 格式压缩包，以下文件不符合要求：\n${nonZip.map((f) => f.name).join(', ')}`,
    })
    return
  }

  const oversize = fileList.filter((f) => f.size > 50 * 1024 * 1024)
  if (oversize.length > 0) {
    Swal.fire({
      icon: 'warning',
      title: '压缩包过大',
      text: `单个 ZIP 压缩包最多支持 50 MB，以下文件超出限制：\n${oversize.map((f) => `${f.name} (${(f.size / (1024 * 1024)).toFixed(1)} MB)`).join(', ')}`,
    })
    return
  }

  importingZip.value = true
  try {
    const res = await problemsApi.importBatchZip(fileList, { is_public: false })

    if (fileList.length === 1 && res.results[0]?.success && res.results[0].problem) {
      const p = res.results[0].problem
      const tcCount = res.results[0].imported_test_cases || 0
      const result = await Swal.fire({
        icon: 'success',
        title: '题目导入成功！',
        html: `题目<strong>《${escapeHtml(p.title)}》</strong>(${escapeHtml(p.problem_number)}) 已成功导入，包含 <strong>${tcCount}</strong> 个测试点。`,
        showCancelButton: true,
        confirmButtonText: '进入编辑',
        cancelButtonText: '留在此页',
      })
      if (result.isConfirmed) {
        router.push(`/problems/${p.id}/edit`)
      } else {
        fetchData()
      }
    } else {
      const successItems = res.results.filter((r) => r.success && r.problem)
      const failedItems = res.results.filter((r) => !r.success)

      let html = `<div style="text-align: left; max-height: 360px; overflow-y: auto; font-size: 14px; line-height: 1.6;">`
      html += `<p style="margin-bottom: 10px;">共处理 <strong>${res.total}</strong> 个文件：<span style="color: #10b981; font-weight: bold;">成功 ${res.succeeded} 个</span>，<span style="color: ${res.failed > 0 ? '#ef4444' : '#6b7280'}; font-weight: bold;">失败 ${res.failed} 个</span></p>`

      if (successItems.length > 0) {
        html += `<div style="margin-bottom: 12px; padding: 8px 12px; background: #ecfdf5; border-radius: 6px; border: 1px solid #a7f3d0;">`
        html += `<strong style="color: #065f46;">成功导入题目：</strong><ul style="padding-left: 20px; margin: 6px 0 0 0;">`
        for (const item of successItems) {
          html += `<li><strong>《${escapeHtml(item.problem!.title)}》</strong> (${escapeHtml(item.problem!.problem_number)}) - 测试点: ${item.imported_test_cases} 个</li>`
        }
        html += `</ul></div>`
      }

      if (failedItems.length > 0) {
        html += `<div style="padding: 8px 12px; background: #fef2f2; border-radius: 6px; border: 1px solid #fecaca;">`
        html += `<strong style="color: #991b1b;">失败文件：</strong><ul style="padding-left: 20px; margin: 6px 0 0 0;">`
        for (const item of failedItems) {
          html += `<li><strong>${escapeHtml(item.filename)}</strong>: <span style="color: #dc2626;">${escapeHtml(item.error || '未知错误')}</span></li>`
        }
        html += `</ul></div>`
      }
      html += `</div>`

      await Swal.fire({
        icon: res.failed === 0 ? 'success' : res.succeeded === 0 ? 'error' : 'warning',
        title: res.failed === 0 ? '全部题目批量导入成功！' : '批量导入完成',
        html,
        confirmButtonText: '确定',
      })
      fetchData()
    }
  } catch (err: any) {
    const detail = err?.response?.data?.detail || err?.message || '批量导入失败，请检查网络或压缩包内容'
    Swal.fire('导入失败', detail, 'error')
  } finally {
    importingZip.value = false
  }
}

watch(
  () => route.fullPath,
  () => {
    // URL 变化（含前进后退）→ 同步输入框并重新拉取
    keywordInput.value = (route.query.keyword as string) || ''
    fetchData()
  }
)

onMounted(() => {
  fetchData()
  loadSources()
})
</script>

<template>
  <div class="problem-list-page">
    <div class="problem-list-container">
      <!-- 头部 -->
      <div class="page-head">
        <div>
          <h2 class="page-title">题库</h2>
          <p class="page-sub">
            {{ scope === 'mine'
              ? '我的题库：你出的题都在这里（草稿 / 待审核 / 已驳回 / 已进主题库）。还没进主题库的题可以随时提交审核。'
              : '按难度、来源或关键词查找题目，点击题名查看题面。' }}
          </p>
        </div>
        <div class="head-actions">
          <div class="scope-tabs">
            <button
              class="scope-tab"
              :class="{ active: scope === 'public' }"
              @click="setScope('public')"
            >题库</button>
            <button
              v-if="canCreate"
              class="scope-tab"
              :class="{ active: scope === 'mine' }"
              @click="setScope('mine')"
            >我的题库</button>
          </div>
          <button v-if="canManage" class="btn-ghost-admin" @click="router.push('/admin/problems')">
            <i class="fa-solid fa-gavel"></i> 题目审核
          </button>
          <button v-if="canCreate" class="btn-zip-import" :disabled="importingZip" @click="zipListInputRef?.click()">
            <i class="fa-solid" :class="importingZip ? 'fa-spinner fa-spin' : 'fa-file-zipper'"></i>
            {{ importingZip ? '正在导入...' : 'ZIP 导入题目 (支持多选)' }}
          </button>
          <input
            ref="zipListInputRef"
            type="file"
            accept=".zip"
            multiple
            style="display: none"
            @change="handleZipListImport"
          />
          <button v-if="canCreate" class="btn-new" @click="router.push('/problems/new')">
            <i class="fa-solid fa-plus"></i> 新建题目
          </button>
        </div>
      </div>

      <div class="card">
        <!-- 筛选栏 -->
        <div class="filter-bar">
          <select v-model="difficultyFilter" class="filter-select">
            <option value="">全部难度</option>
            <option v-for="d in DIFFICULTY_LIST" :key="d" :value="d">{{ d }}</option>
          </select>
          <select v-model="sourceFilter" class="filter-select">
            <option value="">全部来源</option>
            <option v-for="s in sources" :key="s" :value="s">{{ s }}</option>
          </select>
          <input
            v-model="keywordInput"
            class="filter-input"
            placeholder="搜索题号或题目名称"
            @keyup.enter="applyFilters"
          />
          <button class="btn-search" @click="applyFilters">搜索</button>
          <button class="btn-reset" @click="resetFilters">重置</button>
        </div>

        <div class="result-count">共 {{ total }} 条记录</div>

        <!-- 列表 -->
        <div v-if="loading" class="loading-state">
          <span class="loading-spinner"></span>
          <span>题目加载中…</span>
        </div>
        <div v-else-if="error" class="empty">{{ error }}</div>
        <div v-else-if="items.length === 0" class="empty">暂无题目</div>

        <div v-else class="table-wrap">
          <table class="problem-table">
            <thead>
              <tr>
                <th class="col-status">状态</th>
                <th class="col-pid">题号</th>
                <th>题目名称</th>
                <th class="col-tags">算法标签</th>
                <th class="col-diff">难度</th>
                <th class="col-rate">通过率</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in items" :key="p.id">
                <td class="col-status">
                  <i
                    class="status-icon"
                    :class="problemUserStatusMeta(p.my_status).icon"
                    :style="{ color: problemUserStatusMeta(p.my_status).color }"
                    :title="problemUserStatusMeta(p.my_status).text"
                    :aria-label="problemUserStatusMeta(p.my_status).text"
                  ></i>
                </td>
                <td class="col-pid">
                  <RouterLink class="p-link" :to="`/problems/${p.id}`">{{ p.problem_number }}</RouterLink>
                </td>
                <td>
                  <RouterLink class="p-link p-title" :to="`/problems/${p.id}`">{{ p.title }}</RouterLink>
                  <span
                    v-if="p.review_status && p.review_status !== 'approved'"
                    class="review-badge"
                    :style="{
                      background: problemReviewMeta(p.review_status).bg,
                      color: problemReviewMeta(p.review_status).color,
                    }"
                  >{{ p.is_public ? problemReviewMeta(p.review_status).text : '草稿' }}</span>
                  <RouterLink
                    v-if="scope === 'mine'"
                    class="edit-link"
                    :to="`/problems/${p.id}/edit`"
                  >编辑</RouterLink>
                  <!-- 我的题库：把还没进主题库的题一键提交审核 -->
                  <button
                    v-if="canSubmitToLibrary(p)"
                    class="submit-lib-btn"
                    :disabled="submittingId === p.id"
                    title="提交后进入管理员审核队列，通过即进入主题库"
                    @click="handleSubmitToLibrary(p)"
                  >{{ submittingId === p.id ? '提交中...' : '提交进主题库' }}</button>
                </td>
                <td class="col-tags">
                  <template v-if="p.tags && p.tags.length">
                    <RouterLink
                      v-for="t in p.tags"
                      :key="t"
                      class="tag-badge"
                      :to="{ path: '/problems', query: { tag: t } }"
                    >{{ t }}</RouterLink>
                  </template>
                  <span v-else class="muted">-</span>
                </td>
                <td class="col-diff">
                  <span
                    v-if="isDifficultyVisible(p.id)"
                    class="diff-badge"
                    :style="{ background: difficultyColor(p.difficulty) }"
                  >
                    {{ p.difficulty }}
                  </span>
                  <!-- 学术模式下只有已点开的那一道题显示难度 -->
                  <button
                    v-else
                    type="button"
                    class="diff-reveal-btn"
                    title="学术模式：难度默认隐藏，点一下只看这道题"
                    @click="revealDifficulty(p.id)"
                  >显示难度</button>
                </td>
                <td class="col-rate">
                  <template v-if="p.pass_rate !== null">
                    <div class="rate-line">
                      <div class="rate-bar">
                        <div class="rate-fill" :style="{ width: p.pass_rate + '%' }"></div>
                      </div>
                      <span class="rate-text">{{ p.pass_rate }}%</span>
                    </div>
                  </template>
                  <span v-else class="muted">暂无</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 数字分页 -->
        <div class="pagination" v-if="pageCount > 1">
          <button class="page-btn" :disabled="page === 0" @click="page = page - 1">&laquo;</button>
          <template v-for="(n, i) in pagesToShow" :key="i">
            <span v-if="n === -1" class="page-ellipsis">…</span>
            <button v-else class="page-btn" :class="{ active: n === page }" @click="page = n">
              {{ n + 1 }}
            </button>
          </template>
          <button class="page-btn" :disabled="page >= pageCount - 1" @click="page = page + 1">&raquo;</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.problem-list-page {
  min-height: 100vh;
  line-height: 1.5;
}

.problem-list-container {
  max-width: 1100px;
  margin: 0 auto;
}

.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.scope-tabs {
  display: inline-flex;
  border: 1px solid #e2e8f0;
  border-radius: 24px;
  overflow: hidden;
  background: var(--surface-plain);
}

.scope-tab {
  padding: 8px 18px;
  border: none;
  background: transparent;
  font-size: 13px;
  color: var(--text-sub);
  cursor: pointer;
}

.scope-tab.active {
  background: var(--primary);
  color: #fff;
  font-weight: 600;
}

.btn-ghost-admin {
  padding: 9px 18px;
  border: 1px solid #e2e8f0;
  background: var(--surface-plain);
  color: var(--text-sub);
  border-radius: 24px;
  font-size: 14px;
  cursor: pointer;
  white-space: nowrap;
}

.btn-ghost-admin:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.btn-zip-import {
  padding: 9px 18px;
  border: 1px solid #e2e8f0;
  background: var(--surface-plain);
  color: var(--text-sub);
  border-radius: 24px;
  font-size: 14px;
  cursor: pointer;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s;
}

.btn-zip-import:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
}

.btn-zip-import:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-new {
  padding: 9px 22px;
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: 24px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}

.btn-new:hover {
  background: var(--primary-hover);
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

/* 背景/圆角/边框/阴影由全局 .card 基类统一提供（亚克力），这里只管布局 */
.card {
  padding: 20px 24px;
}

.filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
}

.filter-select {
  padding: 8px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 13px;
  color: var(--text-sub);
  background: var(--surface-plain);
}

.filter-input {
  flex: 1;
  min-width: 180px;
  padding: 8px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 13px;
  color: var(--text-sub);
  outline: none;
}

.filter-input:focus {
  border-color: var(--primary);
}

.btn-search {
  padding: 8px 22px;
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.btn-search:hover {
  background: var(--primary-hover);
}

.btn-reset {
  padding: 8px 18px;
  border: 1px solid #e2e8f0;
  background: var(--surface-plain);
  border-radius: 8px;
  font-size: 13px;
  color: var(--text-sub);
  cursor: pointer;
}

.btn-reset:hover {
  
}

.result-count {
  color: var(--text-sub);
  font-size: 13px;
  margin-bottom: 8px;
}

.table-wrap {
  overflow-x: auto;
}

.problem-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.problem-table th {
  text-align: left;
  padding: 11px 12px;
  color: var(--text-sub);
  font-size: 13px;
  border-bottom: 2px solid #edf2f7;
  white-space: nowrap;
}

.problem-table td {
  padding: 13px 12px;
  border-bottom: 1px solid #f0f2f5;
}

.problem-table tbody tr {
  transition: background 0.15s;
}

.problem-table tbody tr:hover {
  background: color-mix(in srgb, var(--primary) 6%, transparent);
}

.col-pid {
  white-space: nowrap;
}

.col-status {
  width: 44px;
  white-space: nowrap;
}

/* 特异性需盖过 .problem-table th { text-align: left }，否则表头左对齐 */
.problem-table .col-status {
  text-align: center;
}

.status-icon {
  font-size: 15px;
  vertical-align: middle;
  cursor: help;
}

.col-tags {
  max-width: 320px;
}

.col-diff,
.col-rate {
  white-space: nowrap;
}

.p-link {
  color: #3498db;
  text-decoration: none;
}

.p-link:hover {
  text-decoration: underline;
}

.p-title {
  font-weight: 600;
  color: var(--text-strong);
}

.p-title:hover {
  color: var(--primary);
}

.tag-badge {
  display: inline-block;
  margin: 1px 4px 1px 0;
  padding: 2px 10px;
  border-radius: 20px;
  background: var(--bg-subtle);
  color: var(--text-sub);
  font-size: 12px;
  text-decoration: none;
  white-space: nowrap;
}

.tag-badge:hover {
  background: #e2e8f0;
}

.diff-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.rate-line {
  display: flex;
  align-items: center;
  gap: 8px;
}

.rate-bar {
  width: 70px;
  height: 8px;
  background: var(--bg-subtle);
  border-radius: 4px;
  overflow: hidden;
}

.rate-fill {
  height: 100%;
  background: #52c41a;
  border-radius: 4px;
}

.rate-text {
  font-size: 12px;
  color: var(--text-sub);
}

.muted {
  color: #b6c2cf;
}

.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 6px;
  padding: 18px 0 4px;
}

.page-btn {
  min-width: 32px;
  padding: 6px 10px;
  border: 1px solid #e2e8f0;
  background: var(--surface-plain);
  border-radius: 8px;
  font-size: 13px;
  color: var(--text-sub);
  cursor: pointer;
}

.page-btn:hover:not(:disabled):not(.active) {
  border-color: var(--primary);
  color: var(--primary);
}

.page-btn.active {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
  font-weight: 600;
}

.page-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.page-ellipsis {
  color: var(--text-sub);
  padding: 0 2px;
}

.empty {
  text-align: center;
  padding: 60px 20px;
  color: var(--text-sub);
}

/* 审核状态徽章 */
.review-badge {
  margin-left: 8px;
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 12px;
  white-space: nowrap;
}

.edit-link {
  margin-left: 8px;
  font-size: 12px;
  color: #3498db;
  text-decoration: none;
  white-space: nowrap;
}

.edit-link:hover {
  text-decoration: underline;
}

/* 我的题库：提交进主题库 */
.submit-lib-btn {
  margin-left: 8px;
  padding: 2px 10px;
  font-size: 12px;
  border-radius: 6px;
  border: 1px solid color-mix(in srgb, var(--primary) 45%, transparent);
  background: transparent;
  color: var(--primary);
  cursor: pointer;
  white-space: nowrap;
}

.submit-lib-btn:hover:not(:disabled) {
  background: color-mix(in srgb, var(--primary) 10%, transparent);
}

.submit-lib-btn:disabled {
  opacity: .5;
  cursor: not-allowed;
}

/* 未公开徽章（与题目详情页 draft-badge 同款） */
.draft-badge {
  margin-left: 8px;
  padding: 2px 10px;
  border-radius: 4px;
  background: var(--bg-subtle);
  color: var(--text-sub);
  font-size: 12px;
  white-space: nowrap;
}

@media (max-width: 600px) {
  .card {
    padding: 14px;
  }
}
</style>
