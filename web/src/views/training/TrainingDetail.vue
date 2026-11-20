<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  getTrainingDetail,
  updateTrainingList,
  deleteTrainingList,
  addProblemToTraining,
  removeProblemFromTraining,
  toggleFeatureTraining,
  reorderTrainingProblems,
  type TrainingDetail
} from '@/api/training'
import { difficultyColor } from '@/utils/difficulty'
import { useDifficultyReveal } from '@/utils/academicMode'
import { userNameColor } from '@/utils/userColor'
import { fmtDateTime } from '@/utils/datetime'
import { renderRichText as renderMarkdown } from '@/utils/markdown'
import { problemUserStatusMeta } from '@/utils/submissionStatus'
import Swal from 'sweetalert2'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

// 学术模式：题单里的难度默认收起，点一下只看这道题（刷新即恢复隐藏）
const { isDifficultyVisible, revealDifficulty } = useDifficultyReveal()

const trainingId = Number(route.params.id)
const detail = ref<TrainingDetail | null>(null)
const loading = ref(true)
const error = ref('')

// 添加题目
const problemCodeInput = ref('')
const addingProblem = ref(false)

// 调整题目顺序
const reordering = ref(false)

// 编辑题单弹窗
const showEditModal = ref(false)
const editLoading = ref(false)
const editForm = ref({
  title: '',
  description: '',
  is_public: true
})

const letterAvatar = (name: string) => {
  const ch = (name || 'U').trim().charAt(0).toUpperCase() || 'U'
  return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Crect width='40' height='40' fill='%23e74c3c'/%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' dy='.3em' fill='white' font-size='16' font-family='Arial'%3E${encodeURIComponent(ch)}%3C/text%3E%3C/svg%3E`
}

const loadDetail = async () => {
  loading.value = true
  error.value = ''
  try {
    const res = await getTrainingDetail(trainingId)
    detail.value = res
  } catch (err: any) {
    console.error(err)
    error.value = err.response?.data?.detail || err.message || '加载题单失败'
  } finally {
    loading.value = false
  }
}

// 添加题目
const handleAddProblem = async () => {
  const code = problemCodeInput.value.trim()
  if (!code) {
    Swal.fire({ icon: 'warning', text: '请输入题号，如 P1001、U1001、T1001 或 1001' })
    return
  }

  addingProblem.value = true
  try {
    await addProblemToTraining(trainingId, code)
    problemCodeInput.value = ''
    Swal.fire({
      icon: 'success',
      title: '题目添加成功',
      timer: 1200,
      showConfirmButton: false
    })
    await loadDetail()
  } catch (err: any) {
    Swal.fire({
      icon: 'error',
      title: '添加失败',
      text: err.response?.data?.detail || err.message || '未找到该题目或已在题单中'
    })
  } finally {
    addingProblem.value = false
  }
}

// 移除题目
const handleRemoveProblem = async (problemId: number, title: string) => {
  const res = await Swal.fire({
    title: '确认移除题目？',
    text: `确定将「${title}」从题单中移除？`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#d33',
    confirmButtonText: '确定移除',
    cancelButtonText: '取消'
  })
  if (!res.isConfirmed) return

  try {
    await removeProblemFromTraining(trainingId, problemId)
    Swal.fire({ icon: 'success', title: '已移除', timer: 1000, showConfirmButton: false })
    await loadDetail()
  } catch (err: any) {
    Swal.fire({
      icon: 'error',
      title: '移除失败',
      text: err.response?.data?.detail || err.message
    })
  }
}

// 管理员推荐/取消推荐
const handleToggleFeature = async () => {
  if (!detail.value || !detail.value.can_feature) return
  const nextStatus = !detail.value.is_featured
  try {
    const res = await toggleFeatureTraining(trainingId, nextStatus)
    detail.value.is_featured = res.is_featured
    Swal.fire({
      icon: 'success',
      title: res.is_featured ? '已设置为推荐题单' : '已取消推荐',
      timer: 1500,
      showConfirmButton: false
    })
  } catch (err: any) {
    Swal.fire({
      icon: 'error',
      title: '操作失败',
      text: err.response?.data?.detail || err.message
    })
  }
}

// 调整题目顺序：上移/下移
const moveProblem = async (idx: number, direction: -1 | 1) => {
  if (!detail.value || !detail.value.problems) return
  const arr = detail.value.problems
  const target = idx + direction
  if (target < 0 || target >= arr.length) {
    return
  }
  // 交换位置
  const tmp = arr[idx]
  arr[idx] = arr[target]
  arr[target] = tmp
  // 调后端持久化
  reordering.value = true
  try {
    const res = await reorderTrainingProblems(
      trainingId,
      arr.map((p) => p.problem_id)
    )
    detail.value = res
  } catch (err: any) {
    Swal.fire({
      icon: 'error',
      title: '排序保存失败',
      text: err.response?.data?.detail || err.message
    })
    // 失败回滚：重新加载
    await loadDetail()
  } finally {
    reordering.value = false
  }
}

// 编辑题单
const openEditModal = () => {
  if (!detail.value) return
  editForm.value = {
    title: detail.value.title,
    description: detail.value.description,
    is_public: detail.value.is_public
  }
  showEditModal.value = true
}

const handleUpdate = async () => {
  if (!editForm.value.title.trim()) {
    Swal.fire({ icon: 'warning', text: '请输入题单标题' })
    return
  }
  editLoading.value = true
  try {
    await updateTrainingList(trainingId, editForm.value)
    showEditModal.value = false
    Swal.fire({ icon: 'success', title: '更新成功', timer: 1200, showConfirmButton: false })
    await loadDetail()
  } catch (err: any) {
    Swal.fire({
      icon: 'error',
      title: '更新失败',
      text: err.response?.data?.detail || err.message
    })
  } finally {
    editLoading.value = false
  }
}

// 删除题单
const handleDelete = async () => {
  if (!detail.value) return
  const res = await Swal.fire({
    title: '确认删除题单？',
    text: `删除题单「${detail.value.title}」后不可恢复！`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#d33',
    confirmButtonText: '确定删除',
    cancelButtonText: '取消'
  })
  if (!res.isConfirmed) return

  try {
    await deleteTrainingList(trainingId)
    Swal.fire({ icon: 'success', title: '题单已删除', timer: 1500, showConfirmButton: false })
    router.push('/training')
  } catch (err: any) {
    Swal.fire({
      icon: 'error',
      title: '删除失败',
      text: err.response?.data?.detail || err.message
    })
  }
}

onMounted(loadDetail)
</script>

<template>
  <div class="training-detail-page">
    <div class="detail-container">
      <!-- 错误状态 -->
      <div v-if="error" class="error-card">
        <i class="fa-solid fa-circle-exclamation error-icon"></i>
        <h2>{{ error }}</h2>
        <button class="btn-back" @click="router.push('/training')">返回题单广场</button>
      </div>

      <!-- 加载状态 -->
      <div v-else-if="loading" class="loading-state">
        <i class="fa-solid fa-spinner fa-spin"></i> 正在加载题单内容...
      </div>

      <!-- 详情主视图 -->
      <template v-else-if="detail">
        <!-- 顶部面包屑与导航 -->
        <div class="breadcrumb">
          <router-link to="/training" class="bread-link">
            <i class="fa-solid fa-layer-group"></i> 训练题单
          </router-link>
          <span class="bread-sep">/</span>
          <span class="bread-cur">{{ detail.title }}</span>
        </div>

        <!-- 题单信息卡片 -->
        <div class="card header-card">
          <div class="header-main">
            <div class="title-row">
              <h1 class="training-title">{{ detail.title }}</h1>
              <span v-if="detail.is_featured" class="badge-featured">
                <i class="fa-solid fa-star"></i> 推荐题单
              </span>
              <span v-if="!detail.is_public" class="badge-private">私有题单</span>
            </div>

            <!-- 描述 Markdown 渲染 -->
            <div
              v-if="detail.description"
              class="desc-content prose"
              v-html="renderMarkdown(detail.description)"
            ></div>
            <div v-else class="desc-content text-muted">暂无详细描述</div>

            <!-- 元数据与作者 -->
            <div class="header-meta">
              <div class="author-block">
                <router-link :to="detail.author?.user_number ? `/user/${detail.author.user_number}` : '#'" class="author-link">
                  <img
                    :src="detail.author?.avatar_url || letterAvatar(detail.author?.username || 'U')"
                    class="author-avatar"
                    alt=""
                  >
                  <span
                    class="author-name"
                    :style="{ color: userNameColor(detail.author) }"
                  >{{ detail.author?.username }}</span>
                </router-link>
                <span
                  v-if="detail.author?.user_tag"
                  class="user-tag"
                  :style="{ backgroundColor: userNameColor(detail.author) }"
                >{{ detail.author.user_tag }}</span>
              </div>

              <div class="meta-stats">
                <span><i class="fa-solid fa-list-check"></i> 共 {{ detail.problem_count }} 题</span>
                <span><i class="fa-regular fa-clock"></i> 更新于 {{ fmtDateTime(detail.updated_at, '—') }}</span>
              </div>
            </div>
          </div>

          <!-- 右侧操作栏 -->
          <div class="header-actions">
            <!-- 管理员推荐按钮 -->
            <button
              v-if="detail.can_feature"
              class="btn-action"
              :class="{ 'btn-star-active': detail.is_featured }"
              @click="handleToggleFeature"
            >
              <i :class="detail.is_featured ? 'fa-solid fa-star' : 'fa-regular fa-star'"></i>
              {{ detail.is_featured ? '取消推荐' : '设为推荐' }}
            </button>

            <!-- 作者/管理员编辑与删除 -->
            <template v-if="detail.can_edit">
              <button class="btn-action" @click="openEditModal">
                <i class="fa-solid fa-pen-to-square"></i> 编辑题单
              </button>
              <button class="btn-action text-danger" @click="handleDelete">
                <i class="fa-regular fa-trash-can"></i> 删除题单
              </button>
            </template>
          </div>
        </div>

        <!-- 做题进度卡片 -->
        <div v-if="authStore.isAuthenticated && detail.problem_count > 0" class="card progress-card">
          <div class="progress-left">
            <span class="prog-title"><i class="fa-solid fa-chart-pie"></i> 练习进度</span>
            <span class="prog-score">
              已完成 <b>{{ detail.user_solved_count ?? detail.solved_count }}</b> / {{ detail.problem_count }} 题
            </span>
          </div>
          <div class="progress-right">
            <div class="prog-bar-bg">
              <div
                class="prog-bar-fill"
                :style="{ width: `${Math.min(100, Math.round(((detail.user_solved_count ?? detail.solved_count) / detail.problem_count) * 100))}%` }"
              ></div>
            </div>
            <span class="prog-pct">
              {{ Math.round(((detail.user_solved_count ?? detail.solved_count) / detail.problem_count) * 100) }}%
            </span>
          </div>
        </div>

        <!-- 快速添加题目输入框（作者与管理员可见） -->
        <div v-if="detail.can_edit" class="card add-problem-card">
          <div class="card-subtitle">
            <i class="fa-solid fa-plus-circle"></i> 添加题目到题单
          </div>
          <div class="add-form">
            <div class="input-wrapper">
              <i class="fa-solid fa-hashtag input-icon"></i>
              <input
                v-model="problemCodeInput"
                type="text"
                placeholder="输入题号，例如 P1001、U1001、T1001 或 1001"
                class="problem-code-input"
                :disabled="addingProblem"
                @keyup.enter="handleAddProblem"
              >
            </div>
            <button
              class="btn-add-problem"
              :disabled="addingProblem || !problemCodeInput.trim()"
              @click="handleAddProblem"
            >
              <i v-if="addingProblem" class="fa-solid fa-spinner fa-spin"></i>
              <i v-else class="fa-solid fa-plus"></i>
              {{ addingProblem ? '添加中...' : '添加题目' }}
            </button>
          </div>
          <div class="add-hint">
            <i class="fa-solid fa-circle-info"></i> 支持输入主题库题号（如 <code>P1001</code>）、用户题库题号（如 <code>U1001</code>）、纯数字（如 <code>1001</code>）或团队题号（如 <code>T1001</code>）。
          </div>
        </div>

        <!-- 题目列表表格 -->
        <div class="card problems-card">
          <div class="table-header">
            <h3><i class="fa-solid fa-list-ol"></i> 题目列表 ({{ detail.problems?.length || 0 }})</h3>
          </div>

          <div v-if="!detail.problems || detail.problems.length === 0" class="no-problems">
            <i class="fa-solid fa-folder-open empty-icon"></i>
            <p>题单中暂无题目</p>
            <p v-if="detail.can_edit" class="sub-hint">可在上方输入框中输入题号快速添加题目</p>
          </div>

          <div v-else class="table-responsive">
            <table class="problem-table">
              <thead>
                <tr>
                  <th style="width: 60px;">状态</th>
                  <th style="width: 120px;">题号</th>
                  <th>题目名称</th>
                  <th style="width: 110px;">难度</th>
                  <th style="width: 140px;">通过 / 提交</th>
                  <th v-if="detail.can_edit" style="width: 150px; text-align: center;">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(p, idx) in detail.problems" :key="p.problem_id">
                  <!-- 状态 -->
                  <td class="status-cell">
                    <span
                      class="status-icon"
                      :title="problemUserStatusMeta(p.my_status).text"
                      :style="{ color: problemUserStatusMeta(p.my_status).color }"
                    >
                      <i :class="problemUserStatusMeta(p.my_status).icon"></i>
                    </span>
                  </td>

                  <!-- 题号 -->
                  <td>
                    <router-link :to="`/problem/${p.problem_number}`" class="problem-number-link">
                      {{ p.problem_number }}
                    </router-link>
                  </td>

                  <!-- 题目名称 -->
                  <td>
                    <router-link :to="`/problem/${p.problem_number}`" class="problem-title-link">
                      {{ p.title }}
                    </router-link>
                  </td>

                  <!-- 难度（学术模式下默认收起，点一下只看这道题） -->
                  <td>
                    <span
                      v-if="isDifficultyVisible(p.problem_id)"
                      class="diff-badge"
                      :style="{ background: difficultyColor(p.difficulty) }"
                    >
                      {{ p.difficulty }}
                    </span>
                    <button
                      v-else
                      type="button"
                      class="diff-reveal-btn"
                      title="学术模式：难度默认隐藏，点一下只看这道题"
                      @click="revealDifficulty(p.problem_id)"
                    >显示难度</button>
                  </td>

                  <!-- 通过率 -->
                  <td class="rate-cell">
                    <span class="rate-nums">{{ (p.solved_count ?? p.accepted_count) || 0 }} / {{ (p.submit_count ?? p.submission_count) || 0 }}</span>
                    <span class="rate-pct">
                      ({{ ((p.submit_count ?? p.submission_count) || 0) > 0 ? Math.round((((p.solved_count ?? p.accepted_count) || 0) / ((p.submit_count ?? p.submission_count) || 1)) * 100) : 0 }}%)
                    </span>
                  </td>

                  <!-- 操作 -->
                  <td v-if="detail.can_edit" class="action-cell">
                    <button
                      class="btn-move"
                      title="上移"
                      :disabled="reordering || idx === 0"
                      @click="moveProblem(idx, -1)"
                    >
                      <i class="fa-solid fa-arrow-up"></i>
                    </button>
                    <button
                      class="btn-move"
                      title="下移"
                      :disabled="reordering || idx === (detail.problems!.length - 1)"
                      @click="moveProblem(idx, 1)"
                    >
                      <i class="fa-solid fa-arrow-down"></i>
                    </button>
                    <button
                      class="btn-remove"
                      title="从题单移除"
                      :disabled="reordering"
                      @click="handleRemoveProblem(p.problem_id, p.title)"
                    >
                      <i class="fa-regular fa-trash-can"></i>
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </div>

    <!-- 编辑题单 Modal -->
    <div v-if="showEditModal" class="modal-backdrop" @click.self="showEditModal = false">
      <div class="modal-card">
        <div class="modal-header">
          <h3><i class="fa-solid fa-pen-to-square"></i> 编辑题单</h3>
          <button class="close-btn" @click="showEditModal = false">
            <i class="fa-solid fa-xmark"></i>
          </button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>题单名称 <span class="req">*</span></label>
            <input
              v-model="editForm.title"
              type="text"
              maxlength="100"
              class="form-input"
            >
          </div>
          <div class="form-group">
            <label>题单描述</label>
            <textarea
              v-model="editForm.description"
              rows="5"
              class="form-textarea"
            ></textarea>
          </div>
          <div class="form-group">
            <label>公开设置</label>
            <div class="radio-row">
              <label class="radio-label">
                <input v-model="editForm.is_public" type="radio" :value="true">
                <span>公开（所有人均可在题单广场中查阅与练习）</span>
              </label>
              <label class="radio-label">
                <input v-model="editForm.is_public" type="radio" :value="false">
                <span>私有（仅自己与管理员可见）</span>
              </label>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn-cancel" @click="showEditModal = false">取消</button>
          <button class="btn-confirm" :disabled="editLoading" @click="handleUpdate">
            {{ editLoading ? '保存中...' : '保存更改' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.training-detail-page {
  min-height: calc(100vh - 60px);
  padding: 24px 20px;
}

.detail-container {
  max-width: 1100px;
  margin: 0 auto;
}

/* 面包屑 */
.breadcrumb {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  margin-bottom: 16px;
  color: var(--text-sub);
}

.bread-link {
  color: var(--primary);
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.bread-link:hover {
  text-decoration: underline;
}

.bread-sep {
  color: #cbd5e1;
}

.bread-cur {
  color: var(--text-strong);
  font-weight: 600;
}

/* 卡片基类 */
.card {
  padding: 24px;
  margin-bottom: 20px;
}

/* 头部卡片 */
.header-card {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 24px;
}

.header-main {
  flex: 1;
  min-width: 0;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.training-title {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  color: var(--text-strong);
}

.badge-featured {
  background: color-mix(in srgb, var(--warning) 12%, transparent);
color: var(--warning-text);
  border: 1px solid #ffd591;
  font-size: 13px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.badge-private {
  background: var(--bg-subtle);
  color: var(--text-sub);
  font-size: 13px;
  padding: 3px 8px;
  border-radius: 6px;
}

.desc-content {
  font-size: 14px;
  color: var(--text-sub);
  line-height: 1.6;
  margin-bottom: 18px;
}

.text-muted {
  color: #94a3b8;
  font-style: italic;
}

.header-meta {
  display: flex;
  align-items: center;
  gap: 24px;
  flex-wrap: wrap;
  padding-top: 14px;
  border-top: 1px solid #f1f5f9;
}

.author-block {
  display: flex;
  align-items: center;
  gap: 8px;
}

.author-link {
  display: flex;
  align-items: center;
  gap: 8px;
  text-decoration: none;
}

.author-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  object-fit: cover;
}

.author-name {
  font-weight: 600;
  font-size: 14px;
}

.user-tag {
  font-size: 11px;
  color: #fff;
  padding: 1px 6px;
  border-radius: 4px;
}

.meta-stats {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: var(--text-sub);
}

.meta-stats span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.header-actions {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 130px;
}

.btn-action {
  background: var(--surface-plain);
  border: 1px solid #e2e8f0;
  color: var(--text-strong);
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  transition: all 0.15s;
}

.btn-action:hover {
  background: var(--bg-subtle);
  border-color: #cbd5e1;
}

.btn-star-active {
  background: color-mix(in srgb, var(--warning) 12%, transparent);
  border-color: #ffd591;
color: var(--warning-text);
}

.btn-action.text-danger {
  color: #ef4444;
}

.btn-action.text-danger:hover {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border-color: #fca5a5;
}

/* 进度卡片 */
.progress-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  padding: 16px 24px;
}

.progress-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.prog-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-main, #1e293b);
  display: flex;
  align-items: center;
  gap: 6px;
}

.prog-title i {
color: light-dark(#10b981, #34d399);
}

.prog-score {
  font-size: 13px;
  color: var(--text-muted, #64748b);
}

.prog-score b {
color: light-dark(#10b981, #34d399);
  font-size: 15px;
}

.progress-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  max-width: 400px;
}

.prog-bar-bg {
  flex: 1;
  height: 8px;
  background: var(--border-color, #e2e8f0);
  border-radius: 4px;
  overflow: hidden;
}

.prog-bar-fill {
  height: 100%;
  background: #10b981;
  border-radius: 4px;
  transition: width 0.3s;
}

.prog-pct {
  font-size: 13px;
  font-weight: 700;
color: light-dark(#10b981, #34d399);
  min-width: 42px;
  text-align: right;
}

/* 添加题目卡片 */
.add-problem-card {
  border: 1px dashed var(--primary);
  padding: 18px 24px;
}

.card-subtitle {
  font-size: 14px;
  font-weight: 700;
  color: var(--primary);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.add-form {
  display: flex;
  gap: 12px;
  align-items: center;
}

.input-wrapper {
  position: relative;
  flex: 1;
}

.input-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: #94a3b8;
  font-size: 14px;
}

.problem-code-input {
  width: 100%;
  box-sizing: border-box;
  padding: 9px 12px 9px 36px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  transition: border-color 0.2s;
}

.problem-code-input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.btn-add-problem {
  background: var(--primary);
  color: #fff;
  border: none;
  padding: 9px 20px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 14px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.btn-add-problem:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.add-hint {
  font-size: 12px;
  color: var(--text-sub);
  margin-top: 8px;
}

.add-hint code {
  background: #e2e8f0;
  padding: 2px 5px;
  border-radius: 4px;
  font-family: monospace;
}

/* 题目列表卡片 */
.table-header {
  margin-bottom: 16px;
}

.table-header h3 {
  margin: 0;
  font-size: 17px;
  color: var(--text-strong);
  display: flex;
  align-items: center;
  gap: 8px;
}

.table-responsive {
  overflow-x: auto;
}

.problem-table {
  width: 100%;
  border-collapse: collapse;
}

.problem-table th {
  text-align: left;
  padding: 12px 14px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-sub);
  border-bottom: 2px solid #e2e8f0;
}

.problem-table td {
  padding: 14px;
  font-size: 14px;
  color: var(--text-strong);
  border-bottom: 1px solid #f1f5f9;
}

.problem-table tr:hover {
  background: var(--surface-plain);
}

.status-cell {
  text-align: center;
  font-size: 16px;
}

.status-ac {
color: light-dark(#10b981, #34d399);
}

.status-wa {
  color: #f59e0b;
}

.status-none {
  color: #cbd5e1;
}

.problem-number-link {
  color: var(--primary);
  font-weight: 700;
  text-decoration: none;
}

.problem-number-link:hover {
  text-decoration: underline;
}

.problem-title-link {
  color: var(--text-strong);
  text-decoration: none;
  font-weight: 500;
}

.problem-title-link:hover {
  color: var(--primary);
}

.diff-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  color: #fff;
  font-size: 12px;
  font-weight: 600;
}

.rate-cell {
  font-size: 13px;
  color: var(--text-sub);
}

.rate-pct {
  font-size: 12px;
  color: #94a3b8;
  margin-left: 4px;
}

.btn-remove {
  background: transparent;
  border: none;
  color: #94a3b8;
  font-size: 15px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
}

.btn-remove:hover:not(:disabled) {
  color: #ef4444;
  background: color-mix(in srgb, var(--danger) 10%, transparent);
}

.btn-remove:disabled,
.btn-move:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.action-cell {
  text-align: center;
  white-space: nowrap;
}

.btn-move {
  background: transparent;
  border: 1px solid #e2e8f0;
  color: var(--text-sub);
  font-size: 13px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  margin-right: 4px;
  transition: all 0.15s;
}

.btn-move:hover:not(:disabled) {
  background: var(--bg-subtle);
  border-color: #cbd5e1;
  color: var(--text-strong);
}

.no-problems {
  text-align: center;
  padding: 48px 20px;
  color: #94a3b8;
}

.empty-icon {
  font-size: 44px;
  margin-bottom: 12px;
  color: #cbd5e1;
}

.sub-hint {
  font-size: 13px;
  color: var(--text-sub);
}

/* 错误与加载状态 */
.error-card {
  text-align: center;
  padding: 60px 20px;
  background: var(--surface-plain);
  border-radius: 14px;
}

.error-icon {
  font-size: 48px;
  color: #ef4444;
  margin-bottom: 16px;
}

.btn-back {
  margin-top: 16px;
  background: var(--primary);
  color: #fff;
  border: none;
  padding: 8px 20px;
  border-radius: 8px;
  cursor: pointer;
}

.loading-state {
  text-align: center;
  padding: 60px 20px;
  color: #94a3b8;
}

/* Modal 弹窗 */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
}

.modal-card {
  background: var(--surface-plain);
  border-radius: 14px;
  width: 90%;
  max-width: 520px;
  padding: 24px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.15);
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 18px;
}

.modal-header h3 {
  margin: 0;
  font-size: 18px;
  color: var(--text-strong);
  display: flex;
  align-items: center;
  gap: 8px;
}

.close-btn {
  background: none;
  border: none;
  font-size: 18px;
  color: #94a3b8;
  cursor: pointer;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-strong);
  margin-bottom: 6px;
}

.form-group .req {
  color: #ef4444;
}

.form-input,
.form-textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 9px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 14px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.15s;
}

.form-input:focus,
.form-textarea:focus {
  border-color: var(--primary);
}

.radio-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.radio-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-sub);
  cursor: pointer;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 24px;
}

.btn-cancel {
  background: var(--bg-subtle);
  color: var(--text-sub);
  border: none;
  padding: 8px 18px;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
}

.btn-confirm {
  background: var(--primary);
  color: #fff;
  border: none;
  padding: 8px 22px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.btn-confirm:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

@media (max-width: 600px) {
  .header-card {
    flex-direction: column;
  }
  .header-actions {
    width: 100%;
    flex-direction: row;
  }
  .add-form {
    flex-direction: column;
  }
  .btn-add-problem {
    width: 100%;
    justify-content: center;
  }
}
</style>
