<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  getTrainingLists,
  createTrainingList,
  deleteTrainingList,
  toggleFeatureTraining,
  type TrainingListItem
} from '@/api/training'
import { userNameColor } from '@/utils/userColor'
import { fmtDateTime } from '@/utils/datetime'
import Swal from 'sweetalert2'
import { isSuperAdmin } from '@/utils/permissions'

const router = useRouter()
const authStore = useAuthStore()

const isLoggedIn = computed(() => authStore.isAuthenticated)
const currentUser = computed(() => authStore.currentUser)
// 权限判定走真源工具（!72 重构），tab 契约与本文件/后端 scope=official|user 对齐
const isAdmin = computed(() => isSuperAdmin(currentUser.value))

// Tabs: 'official' | 'user' | 'my'
const currentTab = ref<'official' | 'user' | 'my'>('official')
const keyword = ref('')
const page = ref(1)
const pageSize = ref(12)
const total = ref(0)
const lists = ref<TrainingListItem[]>([])
const loading = ref(false)

// 新建弹窗状态
const showCreateModal = ref(false)
const createLoading = ref(false)
const newForm = ref({
  title: '',
  description: '',
  is_public: true
})

const letterAvatar = (name: string) => {
  const ch = (name || 'U').trim().charAt(0).toUpperCase() || 'U'
  return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Crect width='40' height='40' fill='%23e74c3c'/%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' dy='.3em' fill='white' font-size='16' font-family='Arial'%3E${encodeURIComponent(ch)}%3C/text%3E%3C/svg%3E`
}

const loadData = async () => {
  loading.value = true
  try {
    const params: any = {
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value.trim() || undefined
    }

    if (currentTab.value === 'official') {
      params.scope = 'official'
    } else if (currentTab.value === 'user') {
      params.scope = 'user'
    } else if (currentTab.value === 'my') {
      if (!currentUser.value?.id) {
        lists.value = []
        total.value = 0
        loading.value = false
        return
      }
      params.author_id = currentUser.value.id
    }

    const res = await getTrainingLists(params)
    lists.value = res.items
    total.value = res.total
  } catch (err: any) {
    console.error(err)
    Swal.fire({
      icon: 'error',
      title: '加载失败',
      text: err.response?.data?.detail || err.message || '请稍后再试'
    })
  } finally {
    loading.value = false
  }
}

const switchTab = (tab: 'official' | 'user' | 'my') => {
  if (tab === 'my' && !isLoggedIn.value) {
    router.push('/login')
    return
  }
  currentTab.value = tab
  page.value = 1
  loadData()
}

const handleSearch = () => {
  page.value = 1
  loadData()
}

const openCreateModal = () => {
  if (!isLoggedIn.value) {
    router.push('/login')
    return
  }
  newForm.value = {
    title: '',
    description: '',
    is_public: true
  }
  showCreateModal.value = true
}

const handleCreate = async () => {
  if (!newForm.value.title.trim()) {
    Swal.fire({ icon: 'warning', text: '请输入题单标题' })
    return
  }
  createLoading.value = true
  try {
    const created = await createTrainingList(newForm.value)
    showCreateModal.value = false
    Swal.fire({
      icon: 'success',
      title: '创建成功',
      timer: 1500,
      showConfirmButton: false
    })
    router.push(`/training/${created.id}`)
  } catch (err: any) {
    Swal.fire({
      icon: 'error',
      title: '创建失败',
      text: err.response?.data?.detail || err.message || '未知错误'
    })
  } finally {
    createLoading.value = false
  }
}

const handleToggleFeature = async (e: Event, item: TrainingListItem) => {
  e.stopPropagation()
  if (!isAdmin.value) return
  const nextStatus = !item.is_featured
  try {
    await toggleFeatureTraining(item.id, nextStatus)
    item.is_featured = nextStatus
    Swal.fire({
      icon: 'success',
      title: nextStatus ? '已推荐此题单' : '已取消推荐',
      timer: 1200,
      showConfirmButton: false
    })
    // 在官方/用户题单 tab 下，取消推荐后题单仍会留在列表里（is_featured 只是排序权重），
    // 但如果将来想做"仅精选"筛选分支再对应处理即可。此处顺手刷新一次。
    loadData()
  } catch (err: any) {
    Swal.fire({
      icon: 'error',
      title: '操作失败',
      text: err.response?.data?.detail || err.message
    })
  }
}

const handleDelete = async (e: Event, item: TrainingListItem) => {
  e.stopPropagation()
  const result = await Swal.fire({
    title: '确认删除题单？',
    text: `删除题单「${item.title}」后不可恢复！`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#d33',
    confirmButtonText: '确定删除',
    cancelButtonText: '取消'
  })
  if (!result.isConfirmed) return

  try {
    await deleteTrainingList(item.id)
    Swal.fire({ icon: 'success', title: '已删除', timer: 1200, showConfirmButton: false })
    loadData()
  } catch (err: any) {
    Swal.fire({
      icon: 'error',
      title: '删除失败',
      text: err.response?.data?.detail || err.message
    })
  }
}

const totalPages = computed(() => Math.ceil(total.value / pageSize.value) || 1)

onMounted(loadData)
</script>

<template>
  <div class="training-page">
    <div class="training-container">
      <!-- 顶部 Header -->
      <div class="page-header">
        <div class="header-left">
          <h1 class="page-title">
            <i class="fa-solid fa-layer-group"></i> 训练题单
          </h1>
          <p class="page-subtitle">精选各类算法练习题单，系统化攻克知识专题</p>
        </div>
        <div class="header-right">
          <button class="btn-create" @click="openCreateModal">
            <i class="fa-solid fa-plus"></i> 新建题单
          </button>
        </div>
      </div>

      <!-- 选项卡与搜索栏 -->
      <div class="filter-bar">
        <div class="tabs">
          <button
            class="tab-btn"
            :class="{ active: currentTab === 'official' }"
            @click="switchTab('official')"
          >
            <i class="fa-solid fa-shield-halved"></i> 官方题单 <span class="tab-badge">P</span>
          </button>
          <button
            class="tab-btn"
            :class="{ active: currentTab === 'user' }"
            @click="switchTab('user')"
          >
            <i class="fa-solid fa-users"></i> 用户题单 <span class="tab-badge">U</span>
          </button>
          <button
            v-if="isLoggedIn"
            class="tab-btn"
            :class="{ active: currentTab === 'my' }"
            @click="switchTab('my')"
          >
            <i class="fa-solid fa-user"></i> 我的题单
          </button>
        </div>

        <div class="search-box">
          <input
            v-model="keyword"
            type="text"
            placeholder="搜索题单标题或简介..."
            @keyup.enter="handleSearch"
          >
          <button class="search-btn" @click="handleSearch">
            <i class="fa-solid fa-magnifying-glass"></i>
          </button>
        </div>
      </div>

      <!-- 题单列表内容 -->
      <div v-if="loading" class="empty-state">
        <i class="fa-solid fa-spinner fa-spin"></i> 正在加载题单列表...
      </div>
      <div v-else-if="lists.length === 0" class="empty-state">
        <i class="fa-solid fa-folder-open empty-icon"></i>
        <p v-if="currentTab === 'official'">暂无官方题单，管理员可创建题单或将已有题单标记为精选</p>
        <p v-else-if="currentTab === 'user'">暂无用户题单，成为第一个发布题单的用户吧</p>
        <p v-else-if="currentTab === 'my'">你还没有创建过题单，点击上方「新建题单」开始创建吧</p>
        <p v-else>暂无匹配的题单</p>
      </div>
      <div v-else class="cards-grid">
        <div
          v-for="item in lists"
          :key="item.id"
          class="training-card"
          @click="router.push(`/training/${item.id}`)"
        >
          <div class="card-main">
            <div class="card-title-row">
              <span class="card-title">{{ item.title }}</span>
              <span v-if="item.is_featured" class="badge-featured" title="官方精选推荐">
                <i class="fa-solid fa-star"></i> 精选
              </span>
              <span v-if="!item.is_public" class="badge-private">私有</span>
            </div>

            <p class="card-desc">{{ item.description || '暂无描述' }}</p>

            <!-- 做题进度（登录状态下显示） -->
            <div v-if="isLoggedIn && item.problem_count > 0" class="progress-wrap">
              <div class="progress-info">
                <span>做题进度</span>
                <span class="progress-fraction">
                  <b>{{ item.user_solved_count ?? item.solved_count }}</b> / {{ item.problem_count }}
                  ({{ Math.round(((item.user_solved_count ?? item.solved_count) / item.problem_count) * 100) }}%)
                </span>
              </div>
              <div class="progress-bar-bg">
                <div
                  class="progress-bar-fill"
                  :style="{ width: `${Math.min(100, Math.round(((item.user_solved_count ?? item.solved_count) / item.problem_count) * 100))}%` }"
                ></div>
              </div>
            </div>

            <!-- 底部 Meta 信息 -->
            <div class="card-footer">
              <div class="author-info" @click.stop>
                <router-link :to="item.author?.user_number ? `/user/${item.author.user_number}` : '#'" class="author-link">
                  <img
                    :src="item.author?.avatar_url || letterAvatar(item.author?.username || 'U')"
                    class="author-avatar"
                    alt=""
                  >
                  <span
                    class="author-name"
                    :style="{ color: userNameColor(item.author) }"
                  >{{ item.author?.username }}</span>
                </router-link>
              </div>

              <div class="meta-right">
                <span class="meta-item">
                  <i class="fa-solid fa-list-check"></i> {{ item.problem_count }} 题
                </span>
                <span class="meta-item">
                  <i class="fa-regular fa-clock"></i> {{ fmtDateTime(item.updated_at, '—') }}
                </span>

                <!-- 管理员推荐按钮 -->
                <button
                  v-if="isAdmin"
                  class="action-btn"
                  :class="{ active: item.is_featured }"
                  :title="item.is_featured ? '取消推荐' : '设为推荐'"
                  @click="(e) => handleToggleFeature(e, item)"
                >
                  <i :class="item.is_featured ? 'fa-solid fa-star' : 'fa-regular fa-star'"></i>
                </button>

                <!-- 删除按钮（作者或管理员） -->
                <button
                  v-if="isAdmin || (currentUser?.id === item.author?.id)"
                  class="action-btn text-danger"
                  title="删除题单"
                  @click="(e) => handleDelete(e, item)"
                >
                  <i class="fa-regular fa-trash-can"></i>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 分页组件 -->
      <div v-if="totalPages > 1" class="pagination">
        <button
          class="page-btn"
          :disabled="page <= 1"
          @click="page--; loadData()"
        >
          上一页
        </button>
        <span class="page-text">第 {{ page }} / {{ totalPages }} 页</span>
        <button
          class="page-btn"
          :disabled="page >= totalPages"
          @click="page++; loadData()"
        >
          下一页
        </button>
      </div>
    </div>

    <!-- 新建题单 Modal -->
    <div v-if="showCreateModal" class="modal-backdrop" @click.self="showCreateModal = false">
      <div class="modal-card">
        <div class="modal-header">
          <h3><i class="fa-solid fa-circle-plus"></i> 新建训练题单</h3>
          <button class="close-btn" @click="showCreateModal = false">
            <i class="fa-solid fa-xmark"></i>
          </button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>题单名称 <span class="req">*</span></label>
            <input
              v-model="newForm.title"
              type="text"
              maxlength="100"
              placeholder="例如：动态规划经典题单、入门百题"
              class="form-input"
            >
          </div>
          <div class="form-group">
            <label>题单描述</label>
            <textarea
              v-model="newForm.description"
              rows="4"
              placeholder="介绍题单的目标、知识点覆盖或推荐刷题顺序..."
              class="form-textarea"
            ></textarea>
          </div>
          <div class="form-group">
            <label>公开设置</label>
            <div class="radio-row">
              <label class="radio-label">
                <input v-model="newForm.is_public" type="radio" :value="true">
                <span>公开（所有人均可在题单广场中查阅与练习）</span>
              </label>
              <label class="radio-label">
                <input v-model="newForm.is_public" type="radio" :value="false">
                <span>私有（仅自己与管理员可见）</span>
              </label>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn-cancel" @click="showCreateModal = false">取消</button>
          <button class="btn-confirm" :disabled="createLoading" @click="handleCreate">
            {{ createLoading ? '创建中...' : '确认创建' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.training-page {
  min-height: calc(100vh - 60px);
  padding: 24px 20px;
}

.training-container {
  max-width: 1200px;
  margin: 0 auto;
}

/* 顶部标题栏 */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.page-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-strong);
  margin: 0 0 6px 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.page-title i {
  color: var(--primary);
}

.page-subtitle {
  margin: 0;
  font-size: 14px;
  color: var(--text-sub);
}

.btn-create {
  background: var(--primary);
  color: #fff;
  border: none;
  padding: 10px 22px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.btn-create:hover {
  filter: brightness(1.08);
  transform: translateY(-1px);
}

/* 过滤与搜索 */
.filter-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 12px;
}

.tabs {
  display: flex;
  gap: 8px;
  background: var(--bg-subtle);
  padding: 4px;
  border-radius: 10px;
}

.tab-btn {
  border: none;
  background: transparent;
  padding: 8px 18px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-sub);
  cursor: pointer;
  transition: all 0.15s;
  display: flex;
  align-items: center;
  gap: 6px;
}

.tab-btn.active {
  background: var(--surface-plain);
  color: var(--primary);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.06);
}

.tab-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
  border-radius: 9px;
  background: #eef2f7;
  color: var(--text-sub);
}

.tab-btn.active .tab-badge {
  background: var(--primary);
  color: #fff;
}

.search-box {
  display: flex;
  align-items: center;
  background: var(--surface-plain);
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
}

.search-box input {
  border: none;
  padding: 8px 14px;
  font-size: 14px;
  outline: none;
  width: 240px;
}

.search-btn {
  background: transparent;
  border: none;
  padding: 8px 14px;
  color: var(--text-sub);
  cursor: pointer;
}

.search-btn:hover {
  color: var(--primary);
}

/* 卡片网格 */
.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 20px;
}

.training-card {
  background: var(--surface);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 20px;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;
}

.training-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-card-hover);
  border-color: var(--primary);
}

.card-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.card-title {
  font-size: 17px;
  font-weight: 700;
  color: var(--text-strong);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.badge-featured {
  background: color-mix(in srgb, var(--warning) 12%, transparent);
color: var(--warning-text);
  border: 1px solid #ffd591;
  font-size: 12px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.badge-private {
  background: var(--bg-subtle);
  color: var(--text-sub);
  font-size: 12px;
  padding: 2px 6px;
  border-radius: 4px;
}

.card-desc {
  font-size: 13px;
  color: var(--text-sub);
  margin: 0 0 16px 0;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 38px;
}

/* 进度条 */
.progress-wrap {
  margin-bottom: 16px;
  background: var(--surface-plain);
  padding: 8px 12px;
  border-radius: 8px;
}

.progress-info {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--text-sub);
  margin-bottom: 6px;
}

.progress-fraction b {
color: light-dark(#10b981, #34d399);
}

.progress-bar-bg {
  height: 6px;
  background: #e2e8f0;
  border-radius: 3px;
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  background: #10b981;
  border-radius: 3px;
  transition: width 0.3s;
}

/* 卡片底部 */
.card-footer {
  margin-top: auto;
  padding-top: 14px;
  border-top: 1px solid #f1f5f9;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.author-link {
  display: flex;
  align-items: center;
  gap: 8px;
  text-decoration: none;
}

.author-avatar {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  object-fit: cover;
}

.author-name {
  font-size: 13px;
  font-weight: 600;
}

.meta-right {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: #94a3b8;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.action-btn {
  background: transparent;
  border: none;
  color: #94a3b8;
  font-size: 14px;
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  transition: color 0.15s;
}

.action-btn:hover {
  color: var(--primary);
}

.action-btn.active {
  color: #fa8c16;
}

.action-btn.text-danger:hover {
  color: #ef4444;
}

/* 空状态 */
.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #94a3b8;
  background: var(--surface-plain);
  border-radius: 14px;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 12px;
  color: #cbd5e1;
}

/* 分页 */
.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16px;
  margin-top: 30px;
}

.page-btn {
  background: var(--surface-plain);
  border: 1px solid #cbd5e1;
  padding: 6px 16px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
}

.page-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.page-text {
  font-size: 13px;
  color: var(--text-sub);
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
  .cards-grid {
    grid-template-columns: 1fr;
  }
  .filter-bar {
    flex-direction: column;
    align-items: stretch;
  }
  .search-box input {
    width: 100%;
  }
}
</style>
