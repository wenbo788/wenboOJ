<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { problemsApi } from '@/api/problems'
import { articlesApi, type ColumnArticleItem } from '@/api/columns'
import type { Problem } from '@/types'
import { useAuthStore } from '@/stores/auth'
import { difficultyColor } from '@/utils/difficulty'
import { userNameColor } from '@/utils/userColor'
import { fmtDateTime } from '@/utils/datetime'
import UserAvatarStatus from '@/components/UserAvatarStatus.vue'

import { isSuperAdmin } from '@/utils/permissions'
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const problemCodeParam = computed(() => (route.params.code ? String(route.params.code) : ''))
const problemIdParam = computed(() => (route.params.id ? Number(route.params.id) : null))

const problem = ref<Problem | null>(null)
const loadingProblem = ref(true)
const problemError = ref('')

const solutions = ref<ColumnArticleItem[]>([])
const loadingSolutions = ref(true)
const page = ref(1)
const pageSize = ref(12)
const total = ref(0)

const currentUser = computed(() => authStore.currentUser)
const isLoggedIn = computed(() => authStore.isAuthenticated)
const isAdmin = computed(() => isSuperAdmin(currentUser.value))
const canManage = computed(() => {
  const u = currentUser.value
  return !!u && (isAdmin.value || u.can_manage_problems === true)
})

const togglingSubmission = ref(false)
const handleToggleSubmission = async () => {
  if (!problem.value || togglingSubmission.value) return
  const currentAllowed = problem.value.allow_solution_submission !== false
  const actionText = currentAllowed ? '关闭' : '开启'
  if (!confirm(`确定要${actionText}本题的题解提交通道吗？`)) {
    return
  }
  togglingSubmission.value = true
  try {
    const updated = await problemsApi.toggleSolutionSubmission(problem.value.id, !currentAllowed)
    problem.value = { ...problem.value, ...updated }
  } catch (err: any) {
    alert(err.response?.data?.detail || err.message || `${actionText}题解通道失败`)
  } finally {
    togglingSubmission.value = false
  }
}

const canonicalCode = computed(() => {
  if (!problem.value) return problemCodeParam.value || ''
  return problem.value.problem_number || (problem.value.team_id ? `T${problem.value.t_no || problem.value.id}` : `P${1000 + problem.value.id}`)
})

const letterAvatar = (name: string) => {
  const ch = (name || 'U').trim().charAt(0).toUpperCase() || 'U'
  return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Crect width='40' height='40' fill='%23e74c3c'/%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' dy='.3em' fill='white' font-size='16' font-family='Arial'%3E${encodeURIComponent(ch)}%3C/text%3E%3C/svg%3E`
}

const loadProblem = async () => {
  loadingProblem.value = true
  problemError.value = ''
  try {
    if (problemCodeParam.value) {
      problem.value = await problemsApi.getByCode(problemCodeParam.value)
    } else if (problemIdParam.value) {
      problem.value = await problemsApi.get(problemIdParam.value)
    }
    if (problem.value) {
      document.title = `${canonicalCode.value} ${problem.value.title} 题解 - NLNOJ`
    }
  } catch (err: any) {
    problemError.value = err.response?.data?.detail || err.message || '题目加载失败'
    problem.value = null
  } finally {
    loadingProblem.value = false
  }
}

const loadSolutions = async () => {
  if (!problem.value) return
  loadingSolutions.value = true
  try {
    const res = await articlesApi.list({
      problem_id: problem.value.id,
      category: '题解',
      page: page.value,
      page_size: pageSize.value,
    })
    solutions.value = res.items
    total.value = res.total
  } catch (err: any) {
    console.error('加载题解列表失败:', err)
  } finally {
    loadingSolutions.value = false
  }
}

const goBackToProblem = () => {
  if (problem.value) {
    const code = canonicalCode.value
    router.push(`/problem/${code}`)
  } else {
    router.push('/problems')
  }
}

const goToWriteSolution = () => {
  if (problem.value?.allow_solution_submission === false && !canManage.value) {
    alert('因为题目做法足够充分或题目过于简单已关闭题解通道。')
    return
  }
  const code = canonicalCode.value
  router.push({
    path: '/articles',
    query: {
      write: 'solution',
      problem: code,
    },
  })
}

const changePage = (p: number) => {
  page.value = p
  loadSolutions()
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

watch(
  () => [problemCodeParam.value, problemIdParam.value],
  async () => {
    await loadProblem()
    await loadSolutions()
  }
)

onMounted(async () => {
  await loadProblem()
  await loadSolutions()
})
</script>

<template>
  <div class="problem-solutions-page">
    <div class="solutions-container">
      <!-- 顶部加载或报错 -->
      <div v-if="loadingProblem" class="card loading-card">
        <i class="fa-solid fa-spinner fa-spin"></i> 正在加载题目信息...
      </div>
      <div v-else-if="problemError" class="card error-card">
        <i class="fa-solid fa-triangle-exclamation"></i>
        <span>{{ problemError }}</span>
        <button class="btn-back" @click="router.push('/problems')">返回题库</button>
      </div>

      <template v-else-if="problem">
        <!-- 题目基础信息横幅 -->
        <div class="card problem-header-card">
          <div class="ph-top">
            <div class="ph-info">
              <span class="p-number">{{ canonicalCode }}</span>
              <h1 class="p-title">{{ problem.title }}</h1>
              <span
                class="diff-badge"
                :style="{ background: difficultyColor(problem.difficulty) }"
              >
                {{ problem.difficulty }}
              </span>
              <span v-if="problem.is_spj" class="spj-badge">Special Judge</span>
            </div>
            <div class="ph-actions">
              <button class="btn-action btn-back" @click="goBackToProblem">
                <i class="fa-solid fa-arrow-left"></i> 返回题目
              </button>
              <button
                v-if="canManage"
                class="btn-action"
                :class="problem.allow_solution_submission === false ? 'btn-toggle-open' : 'btn-toggle-close'"
                :disabled="togglingSubmission"
                @click="handleToggleSubmission"
              >
                <i class="fa-solid" :class="problem.allow_solution_submission === false ? 'fa-lock-open' : 'fa-lock'"></i>
                {{ togglingSubmission ? '处理中...' : (problem.allow_solution_submission === false ? '开启题解通道' : '关闭题解通道') }}
              </button>
              <button
                class="btn-action btn-write"
                :class="{ disabled: problem.allow_solution_submission === false && !canManage }"
                :disabled="problem.allow_solution_submission === false && !canManage"
                :title="problem.allow_solution_submission === false && !canManage ? '因为题目做法足够充分或题目过于简单已关闭题解通道。' : ''"
                @click="goToWriteSolution"
              >
                <i class="fa-solid" :class="problem.allow_solution_submission === false && !canManage ? 'fa-lock' : 'fa-pen-nib'"></i>
                {{ problem.allow_solution_submission === false && !canManage ? '通道已关闭' : '写题解' }}
              </button>
            </div>
          </div>
          <div class="ph-meta">
            <span>时间限制：<b>{{ problem.time_limit }} ms</b></span>
            <span>内存限制：<b>{{ problem.memory_limit }} MB</b></span>
            <span>通过率：<b>{{ problem.pass_rate === null ? '暂无' : problem.pass_rate + '%' }}</b></span>
            <span>通过人数：<b>{{ problem.solved_count }}</b></span>
          </div>
        </div>

        <!-- 题解通道关闭提示横幅 -->
        <div v-if="problem.allow_solution_submission === false" class="solutions-closed-banner">
          <div class="closed-icon">
            <i class="fa-solid fa-lock"></i>
          </div>
          <div class="closed-text">
            <h4>题解提交通道已关闭</h4>
            <p>
              因为题目做法足够充分或题目过于简单已关闭题解通道。
            </p>
          </div>
        </div>

        <!-- 题解规范提示框（通道开放时显示） -->
        <div v-else class="solutions-guide-banner">
          <div class="guide-icon">
            <i class="fa-solid fa-lightbulb"></i>
          </div>
          <div class="guide-text">
            <h4>题解发布与审核说明</h4>
            <p>
              欢迎撰写清晰、严谨的原创题解！发布“题解”分类文章并填上本题题号后，可申请全站推荐；管理员审核通过后，该题解将同时展示在<b>文章广场</b>与<b>本题题解区</b>中，并奖励 <b>20 点社区贡献值</b>。
            </p>
          </div>
          <div class="guide-action">
            <button class="btn-guide-write" @click="goToWriteSolution">
              <i class="fa-solid fa-plus"></i> 发布我的题解
            </button>
          </div>
        </div>

        <!-- 题解列表区域 -->
        <div class="solutions-section">
          <div class="section-title-bar">
            <h2 class="section-title">
              <i class="fa-solid fa-file-lines"></i> 本题精选题解
              <span class="count-tag">{{ total }} 篇</span>
            </h2>
          </div>

          <!-- 加载中 -->
          <div v-if="loadingSolutions" class="card loading-card">
            <i class="fa-solid fa-spinner fa-spin"></i> 正在加载题解...
          </div>

          <!-- 空状态 -->
          <div v-else-if="solutions.length === 0" class="card empty-card">
            <div class="empty-icon">
              <i v-if="problem.allow_solution_submission === false" class="fa-solid fa-lock"></i>
              <i v-else class="fa-regular fa-folder-open"></i>
            </div>
            <p class="empty-title">
              {{ problem.allow_solution_submission === false ? '题解提交通道已关闭' : '本题暂无公开精选题解' }}
            </p>
            <p class="empty-sub">
              {{ problem.allow_solution_submission === false ? '因为题目做法足够充分或题目过于简单已关闭题解通道。' : '欢迎提交本题的第一篇题解，审核通过后即可获得全站推荐与 20 点贡献值奖励！' }}
            </p>
            <button
              v-if="problem.allow_solution_submission !== false || canManage"
              class="btn-action btn-write mt-3"
              @click="goToWriteSolution"
            >
              <i class="fa-solid fa-pen-nib"></i> {{ canManage && problem.allow_solution_submission === false ? '管理员写题解' : '抢先写题解' }}
            </button>
          </div>

          <!-- 列表卡片 -->
          <div v-else class="solution-grid">
            <div
              v-for="sol in solutions"
              :key="sol.id"
              class="solution-card"
              @click="router.push(`/article/${sol.id}`)"
            >
              <div class="card-header-line">
                <div class="author-cell">
                  <UserAvatarStatus v-if="sol.author" :user="sol.author" :size="7">
                    <img
                      :src="sol.author.avatar_url || letterAvatar(sol.author.username)"
                      :alt="sol.author.username"
                    />
                  </UserAvatarStatus>
                  <div class="author-info-text">
                    <router-link
                      v-if="sol.author"
                      :to="sol.author.user_number ? `/user/${sol.author.user_number}` : '#'"
                      class="author-name"
                      :style="{ color: userNameColor(sol.author) }"
                      @click.stop
                    >
                      {{ sol.author.username }}
                    </router-link>
                    <span
                      v-if="sol.author?.user_tag"
                      class="user-tag"
                      :style="{ backgroundColor: userNameColor(sol.author) }"
                    >
                      {{ sol.author.user_tag }}
                    </span>
                  </div>
                </div>

                <!-- 审核状态标记 -->
                <div class="status-tags">
                  <span
                    v-if="sol.recommend_status === 'pending'"
                    class="tag-badge status-pending"
                    title="待管理员审核全站推荐"
                  >
                    <i class="fa-solid fa-clock"></i> 审核中
                  </span>
                  <span
                    v-else-if="sol.recommend_status === 'rejected'"
                    class="tag-badge status-rejected"
                    :title="sol.recommend_reason ? `未通过：${sol.recommend_reason}` : '未通过全站推荐审核'"
                  >
                    <i class="fa-solid fa-circle-xmark"></i> 未通过
                  </span>
                  <span
                    v-else-if="sol.is_recommended"
                    class="tag-badge status-approved"
                    title="全站推荐精选题解"
                  >
                    <i class="fa-solid fa-check"></i> 精选推荐
                  </span>
                </div>
              </div>

              <h3 class="sol-title">
                {{ sol.title }}
              </h3>

              <p class="sol-summary">
                {{ sol.summary || '作者暂未提供摘要，点击卡片阅读详细题解内容...' }}
              </p>

              <div class="card-footer-line">
                <div class="meta-left">
                  <span><i class="fa-regular fa-clock"></i> {{ fmtDateTime(sol.created_at) }}</span>
                </div>
                <div class="meta-right">
                  <span><i class="fa-regular fa-eye"></i> {{ sol.view_count }}</span>
                  <span v-if="sol.like_count !== undefined"><i class="fa-regular fa-thumbs-up"></i> {{ sol.like_count }}</span>
                  <span v-if="sol.comment_count !== undefined"><i class="fa-regular fa-comment-dots"></i> {{ sol.comment_count }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 分页 -->
          <div v-if="total > pageSize" class="solutions-pagination">
            <button :disabled="page <= 1" class="page-btn" @click="changePage(page - 1)">上一页</button>
            <span class="page-info">第 {{ page }} 页 / 共 {{ Math.ceil(total / pageSize) }} 页</span>
            <button :disabled="page * pageSize >= total" class="page-btn" @click="changePage(page + 1)">下一页</button>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.problem-solutions-page {
  min-height: 100vh;
  padding: 24px 16px;
  line-height: 1.5;
}

.solutions-container {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.card {
  background: var(--surface);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: 20px 24px;
}

.loading-card,
.error-card {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  font-size: 15px;
  color: var(--text-sub);
  min-height: 160px;
}

.error-card {
  color: var(--danger, #ef4444);
}

.btn-back {
  padding: 8px 16px;
  background: var(--surface-plain);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-sub);
  transition: all 0.2s;
}

.btn-back:hover {
  border-color: var(--primary);
  color: var(--primary);
}

/* 题头卡片 */
.problem-header-card {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.ph-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.ph-info {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.p-number {
  font-size: 20px;
  font-weight: 800;
  color: var(--primary);
  letter-spacing: -0.5px;
}

.p-title {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  color: var(--text-strong);
}

.diff-badge {
  padding: 3px 10px;
  border-radius: 999px;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}

.spj-badge {
  padding: 3px 8px;
  border-radius: 6px;
  background: #f1f5f9;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
}

.ph-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.btn-action {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 8px 18px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  border: 1px solid transparent;
}

.btn-write {
  background: var(--primary);
  color: #fff;
}

.btn-write:hover {
  background: var(--primary-hover);
}

.btn-write.disabled,
.btn-write:disabled {
  opacity: 0.65;
  cursor: not-allowed;
  background: #94a3b8;
  border-color: #94a3b8;
}

.btn-toggle-close {
  background: #fef2f2;
  color: #dc2626;
  border: 1px solid #fecaca;
}

.btn-toggle-close:hover:not(:disabled) {
  background: #fee2e2;
  border-color: #fca5a5;
}

.btn-toggle-open {
  background: #ecfdf5;
  color: #059669;
  border: 1px solid #a7f3d0;
}

.btn-toggle-open:hover:not(:disabled) {
  background: #d1fae5;
  border-color: #6ee7b7;
}

.ph-meta {
  display: flex;
  align-items: center;
  gap: 20px;
  font-size: 13px;
  color: var(--text-sub);
  border-top: 1px solid var(--border-color);
  padding-top: 14px;
  flex-wrap: wrap;
}

.ph-meta span b {
  color: var(--text-strong);
}

/* 规范提示横幅 */
.solutions-guide-banner {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.08) 0%, rgba(217, 119, 6, 0.03) 100%);
  border: 1px solid rgba(245, 158, 11, 0.28);
  border-radius: var(--radius-md);
}

.guide-icon {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  background: rgba(245, 158, 11, 0.15);
  color: #d97706;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  flex-shrink: 0;
}

.guide-text {
  flex: 1;
  min-width: 0;
}

.guide-text h4 {
  margin: 0 0 4px 0;
  font-size: 15px;
  font-weight: 700;
  color: #b45309;
}

.guide-text p {
  margin: 0;
  font-size: 13px;
  color: var(--text-sub);
  line-height: 1.5;
}

.guide-action {
  flex-shrink: 0;
}

.btn-guide-write {
  padding: 7px 14px;
  border-radius: 8px;
  background: #d97706;
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  border: none;
  cursor: pointer;
  transition: all 0.2s;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.btn-guide-write:hover {
  background: #b45309;
}

/* 题解关闭提示横幅 */
.solutions-closed-banner {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  background: linear-gradient(135deg, rgba(239, 68, 68, 0.08) 0%, rgba(220, 38, 38, 0.03) 100%);
  border: 1px solid rgba(239, 68, 68, 0.28);
  border-radius: var(--radius-md);
}

.closed-icon {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  background: rgba(239, 68, 68, 0.15);
  color: #dc2626;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  flex-shrink: 0;
}

.closed-text {
  flex: 1;
  min-width: 0;
}

.closed-text h4 {
  margin: 0 0 4px 0;
  font-size: 15px;
  font-weight: 700;
  color: #b91c1c;
}

.closed-text p {
  margin: 0;
  font-size: 13px;
  color: var(--text-sub);
  line-height: 1.5;
}

/* 题解列表区域 */
.solutions-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.section-title-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section-title {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--text-strong);
  display: flex;
  align-items: center;
  gap: 10px;
}

.count-tag {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-sub);
  background: var(--surface-plain);
  border: 1px solid var(--border-color);
  padding: 2px 8px;
  border-radius: 999px;
}

/* 空状态卡片 */
.empty-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 48px 24px;
}

.empty-icon {
  font-size: 42px;
  color: #94a3b8;
  margin-bottom: 12px;
}

.empty-title {
  margin: 0 0 6px 0;
  font-size: 17px;
  font-weight: 700;
  color: var(--text-strong);
}

.empty-sub {
  margin: 0;
  font-size: 13px;
  color: var(--text-sub);
}

.mt-3 {
  margin-top: 14px;
}

/* 题解卡片网格 */
.solution-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 16px;
}

.solution-card {
  background: var(--surface);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 18px 20px;
  cursor: pointer;
  transition: all 0.22s ease;
  display: flex;
  flex-direction: column;
  gap: 12px;
  box-shadow: var(--shadow-card);
}

.solution-card:hover {
  transform: translateY(-2px);
  border-color: var(--primary);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.08);
}

.card-header-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.author-cell {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
}

.author-info-text {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.author-name {
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.author-name:hover {
  text-decoration: underline;
}

.user-tag {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  color: #fff;
  font-weight: 600;
}

.status-tags {
  flex-shrink: 0;
}

.tag-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}

.status-pending {
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.status-rejected {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
  border: 1px solid rgba(239, 68, 68, 0.3);
}

.status-approved {
  background: rgba(16, 185, 129, 0.12);
  color: #10b981;
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.sol-title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-strong);
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.sol-summary {
  margin: 0;
  font-size: 13px;
  color: var(--text-sub);
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  flex: 1;
}

.card-footer-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-top: 1px solid var(--border-color);
  padding-top: 10px;
  font-size: 12px;
  color: var(--text-sub);
}

.meta-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* 分页 */
.solutions-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  margin-top: 12px;
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

@media (max-width: 640px) {
  .solution-grid {
    grid-template-columns: 1fr;
  }
  .solutions-guide-banner {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
