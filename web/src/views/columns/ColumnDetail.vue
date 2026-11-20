<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  columnsApi,
  articlesApi,
  COLUMN_CATEGORIES,
  type ColumnDetail,
  type ColumnArticleItem,
  type ColumnInclusionRequestItem,
} from '@/api/columns'
import { userNameColor } from '@/utils/userColor'
import { fmtDateTime } from '@/utils/datetime'
import { renderRichText as renderMarkdown } from '@/utils/markdown'
import MarkdownSplitEditor from '@/components/MarkdownSplitEditor.vue'
import UserAvatarStatus from '@/components/UserAvatarStatus.vue'
import Swal from 'sweetalert2'

import { isSuperAdmin } from '@/utils/permissions'
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const columnId = computed(() => Number(route.params.id))
const detail = ref<ColumnDetail | null>(null)
const loading = ref(true)
const error = ref('')

const currentUser = computed(() => authStore.currentUser)
const isLoggedIn = computed(() => authStore.isAuthenticated)
const isAdmin = computed(() => isSuperAdmin(currentUser.value))
const isAuthor = computed(() => {
  if (!currentUser.value || !detail.value) return false
  return currentUser.value.id === detail.value.author_id
})
const canManage = computed(() => isAuthor.value || isAdmin.value)

const letterAvatar = (name: string) => {
  const ch = (name || 'U').trim().charAt(0).toUpperCase() || 'U'
  return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Crect width='40' height='40' fill='%23e74c3c'/%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' dy='.3em' fill='white' font-size='16' font-family='Arial'%3E${encodeURIComponent(ch)}%3C/text%3E%3C/svg%3E`
}

const getCategoryClass = (category?: string) => {
  switch (category) {
    case '算法理论':
      return 'cat-algo'
    case '科技工程':
      return 'cat-tech'
    case '题解':
      return 'cat-sol'
    case '娱乐':
      return 'cat-fun'
    default:
      return 'cat-default'
  }
}

const loadDetail = async () => {
  loading.value = true
  error.value = ''
  try {
    const res = await columnsApi.get(columnId.value)
    detail.value = res
    if (canManage.value) {
      loadInclusionRequests()
    }
  } catch (err: any) {
    console.error(err)
    error.value = err.response?.data?.detail || err.message || '加载专栏失败'
  } finally {
    loading.value = false
  }
}

watch(canManage, (val) => {
  if (val && detail.value) {
    loadInclusionRequests()
  }
})

// ==================== 管理员全站推荐 ====================
const togglingRecommend = ref(false)
const handleToggleRecommend = async () => {
  if (!detail.value || !isAdmin.value) return
  const nextStatus = !detail.value.is_recommended
  const actionText = nextStatus ? '设为全站推荐' : '取消全站推荐'

  const confirmRes = await Swal.fire({
    title: `确认${actionText}？`,
    text: nextStatus ? '推荐后，该专栏将展示在文章广场的推荐专栏中。' : '取消后，该专栏将从推荐中移除。',
    icon: 'question',
    showCancelButton: true,
    confirmButtonText: '确认',
    cancelButtonText: '取消',
    confirmButtonColor: 'var(--primary)',
  })
  if (!confirmRes.isConfirmed) return

  togglingRecommend.value = true
  try {
    const updated = await columnsApi.toggleRecommend(columnId.value, nextStatus)
    detail.value.is_recommended = updated.is_recommended
    Swal.fire({
      icon: 'success',
      title: `${actionText}成功`,
      timer: 1500,
      showConfirmButton: false,
    })
  } catch (err: any) {
    Swal.fire({
      icon: 'error',
      title: `${actionText}失败`,
      text: err.response?.data?.detail || err.message,
    })
  } finally {
    togglingRecommend.value = false
  }
}

// ==================== 专栏编辑与删除 ====================
const showEditColumnModal = ref(false)
const editColumnLoading = ref(false)
const editColumnForm = ref({
  title: '',
  description: '',
  cover_url: '',
  category: '算法理论',
})

const openEditColumn = () => {
  if (!detail.value) return
  editColumnForm.value = {
    title: detail.value.title,
    description: detail.value.description || '',
    cover_url: detail.value.cover_url || '',
    category: detail.value.category || '算法理论',
  }
  showEditColumnModal.value = true
}

const handleUpdateColumn = async () => {
  if (!editColumnForm.value.title.trim()) {
    Swal.fire({ icon: 'warning', text: '专栏标题不能为空' })
    return
  }
  editColumnLoading.value = true
  try {
    const updated = await columnsApi.update(columnId.value, {
      title: editColumnForm.value.title.trim(),
      description: editColumnForm.value.description.trim() || undefined,
      cover_url: editColumnForm.value.cover_url.trim() || undefined,
      category: editColumnForm.value.category,
    })
    if (detail.value) {
      detail.value.title = updated.title
      detail.value.description = updated.description
      detail.value.cover_url = updated.cover_url
      detail.value.category = updated.category
    }
    showEditColumnModal.value = false
    Swal.fire({ icon: 'success', title: '专栏更新成功', timer: 1200, showConfirmButton: false })
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '更新失败', text: err.response?.data?.detail || err.message })
  } finally {
    editColumnLoading.value = false
  }
}

const handleDeleteColumn = async () => {
  const confirmRes = await Swal.fire({
    title: '确认删除该专栏？',
    text: '专栏删除后，其包含的文章将保留并转为独立文章，专栏合集本身将被永久删除。',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonText: '删除',
    cancelButtonText: '取消',
    confirmButtonColor: '#e74c3c',
  })
  if (!confirmRes.isConfirmed) return

  try {
    await columnsApi.delete(columnId.value)
    await Swal.fire({ icon: 'success', title: '专栏已删除', timer: 1500, showConfirmButton: false })
    router.push('/columns')
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '删除失败', text: err.response?.data?.detail || err.message })
  }
}

// ==================== 文章创建与编辑 ====================
const showArticleModal = ref(false)
const articleModalMode = ref<'create' | 'edit'>('create')
const editingArticleId = ref<number | null>(null)
const articleModalLoading = ref(false)

const articleForm = ref({
  title: '',
  content: '',
  summary: '',
})

const openCreateArticle = () => {
  articleModalMode.value = 'create'
  editingArticleId.value = null
  articleForm.value = { title: '', content: '', summary: '' }
  showArticleModal.value = true
}

const openEditArticle = (art: ColumnArticleItem) => {
  articleModalMode.value = 'edit'
  editingArticleId.value = art.id
  articleForm.value = {
    title: art.title,
    content: '', // 会加载或者暂存
    summary: art.summary || '',
  }
  showArticleModal.value = true

  // 加载全文
  columnsApi.getArticle(columnId.value, art.id).then((fullArt) => {
    articleForm.value.content = fullArt.content
  })
}

const handleSubmitArticle = async () => {
  if (!articleForm.value.title.trim()) {
    Swal.fire({ icon: 'warning', text: '文章标题不能为空' })
    return
  }
  if (!articleForm.value.content.trim()) {
    Swal.fire({ icon: 'warning', text: '文章正文不能为空' })
    return
  }

  articleModalLoading.value = true
  try {
    if (articleModalMode.value === 'create') {
      const newArt = await columnsApi.createArticle(columnId.value, {
        title: articleForm.value.title.trim(),
        content: articleForm.value.content,
        summary: articleForm.value.summary.trim() || undefined,
      })
      if (detail.value) {
        detail.value.articles.unshift(newArt)
        detail.value.article_count += 1
      }
      Swal.fire({ icon: 'success', title: '文章发布成功', timer: 1200, showConfirmButton: false })
    } else if (editingArticleId.value) {
      const updated = await columnsApi.updateArticle(columnId.value, editingArticleId.value, {
        title: articleForm.value.title.trim(),
        content: articleForm.value.content,
        summary: articleForm.value.summary.trim() || undefined,
      })
      if (detail.value) {
        const idx = detail.value.articles.findIndex((a) => a.id === editingArticleId.value)
        if (idx !== -1) {
          detail.value.articles[idx] = { ...detail.value.articles[idx], ...updated }
        }
      }
      Swal.fire({ icon: 'success', title: '文章修改成功', timer: 1200, showConfirmButton: false })
    }
    showArticleModal.value = false
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '提交失败', text: err.response?.data?.detail || err.message })
  } finally {
    articleModalLoading.value = false
  }
}

const handleDeleteArticle = async (art: ColumnArticleItem) => {
  const confirmRes = await Swal.fire({
    title: '确认删除这篇文章？',
    text: `《${art.title}》将被永久删除。`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonText: '删除',
    cancelButtonText: '取消',
    confirmButtonColor: '#e74c3c',
  })
  if (!confirmRes.isConfirmed) return

  try {
    await columnsApi.deleteArticle(columnId.value, art.id)
    if (detail.value) {
      detail.value.articles = detail.value.articles.filter((a) => a.id !== art.id)
      detail.value.article_count = Math.max(0, detail.value.article_count - 1)
    }
    Swal.fire({ icon: 'success', title: '文章已删除', timer: 1200, showConfirmButton: false })
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '删除失败', text: err.response?.data?.detail || err.message })
  }
}

// ==================== 移出专栏 ====================
const handleDetachArticle = async (art: ColumnArticleItem) => {
  const isArtAuthor = currentUser.value && art.author && currentUser.value.id === art.author.id
  const title = isArtAuthor ? '确认将你的文章移出本专栏？' : '确认将该文章移出专栏？'
  const text = '移出后文章仍将完整保留为独立文章，仅解除该专栏收录归属。'

  const confirmRes = await Swal.fire({
    title,
    text,
    icon: 'question',
    showCancelButton: true,
    confirmButtonText: '确认移出',
    cancelButtonText: '取消',
    confirmButtonColor: '#f59e0b',
  })
  if (!confirmRes.isConfirmed) return

  try {
    await columnsApi.detachArticle(columnId.value, art.id)
    if (detail.value) {
      detail.value.articles = detail.value.articles.filter((a) => a.id !== art.id)
      detail.value.article_count = Math.max(0, detail.value.article_count - 1)
    }
    Swal.fire({ icon: 'success', title: '文章已从专栏移出', timer: 1200, showConfirmButton: false })
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '移出失败', text: err.response?.data?.detail || err.message })
  }
}

// ==================== 收录申请（专栏管理端） ====================
const inclusionRequests = ref<ColumnInclusionRequestItem[]>([])
const requestsLoading = ref(false)
const showRequestsModal = ref(false)
const requestFilter = ref<'all' | 'pending' | 'reviewed'>('pending')
const reviewingRequestId = ref<number | null>(null)
const rejectReplyMap = ref<Record<number, string>>({})
const showRejectInputMap = ref<Record<number, boolean>>({})

const pendingRequestsCount = computed(() => {
  return inclusionRequests.value.filter((r) => r.status === 'pending').length
})

const filteredRequests = computed(() => {
  if (requestFilter.value === 'pending') {
    return inclusionRequests.value.filter((r) => r.status === 'pending')
  }
  if (requestFilter.value === 'reviewed') {
    return inclusionRequests.value.filter((r) => r.status !== 'pending')
  }
  return inclusionRequests.value
})

const loadInclusionRequests = async () => {
  if (!columnId.value) return
  requestsLoading.value = true
  try {
    const list = await columnsApi.getInclusionRequests(columnId.value)
    inclusionRequests.value = list
  } catch (err: any) {
    console.error('加载收录申请失败:', err)
  } finally {
    requestsLoading.value = false
  }
}

const openRequestsModal = () => {
  showRequestsModal.value = true
  loadInclusionRequests()
}

const handleReviewRequest = async (req: ColumnInclusionRequestItem, action: 'approve' | 'reject') => {
  const reply = rejectReplyMap.value[req.id]?.trim() || undefined
  if (action === 'reject' && !showRejectInputMap.value[req.id]) {
    showRejectInputMap.value[req.id] = true
    return
  }

  reviewingRequestId.value = req.id
  try {
    await columnsApi.reviewInclusionRequest(columnId.value, req.id, {
      action,
      reply,
    })
    Swal.fire({
      icon: 'success',
      title: action === 'approve' ? '已同意收录该文章' : '已驳回收录申请',
      timer: 1500,
      showConfirmButton: false,
    })
    showRejectInputMap.value[req.id] = false
    await loadInclusionRequests()
    await loadDetail()
  } catch (err: any) {
    Swal.fire({
      icon: 'error',
      title: '审核操作失败',
      text: err.response?.data?.detail || err.message,
    })
  } finally {
    reviewingRequestId.value = null
  }
}

// ==================== 用户投稿文章至专栏 ====================
const showContributeModal = ref(false)
const myArticles = ref<ColumnArticleItem[]>([])
const myArticlesLoading = ref(false)
const selectedArticleId = ref<number | null>(null)
const contributeMessage = ref('')
const contributeSubmitting = ref(false)

const openContributeModal = async () => {
  if (!isLoggedIn.value) {
    router.push(`/login?redirect=${route.fullPath}`)
    return
  }
  showContributeModal.value = true
  selectedArticleId.value = null
  contributeMessage.value = ''
  myArticlesLoading.value = true
  try {
    const list = await articlesApi.getMyArticles()
    myArticles.value = list
  } catch (err: any) {
    console.error('获取我的文章列表失败:', err)
  } finally {
    myArticlesLoading.value = false
  }
}

const handleSubmitContribute = async () => {
  if (!selectedArticleId.value) {
    Swal.fire({ icon: 'warning', text: '请选择要投稿的文章' })
    return
  }

  contributeSubmitting.value = true
  try {
    await columnsApi.applyInclusion(columnId.value, {
      article_id: selectedArticleId.value,
      message: contributeMessage.value.trim() || undefined,
    })
    showContributeModal.value = false
    Swal.fire({
      icon: 'success',
      title: '投稿申请已提交',
      text: isAuthor.value || isAdmin.value ? '已直接收录至专栏！' : '已发送给专栏创建者审核。',
    })
    await loadDetail()
    if (canManage.value) {
      await loadInclusionRequests()
    }
  } catch (err: any) {
    Swal.fire({
      icon: 'error',
      title: '投稿失败',
      text: err.response?.data?.detail || err.message,
    })
  } finally {
    contributeSubmitting.value = false
  }
}

const goToArticle = (artId: number) => {
  router.push(`/column/${columnId.value}/article/${artId}`)
}

// ==================== 专栏点赞与收藏 ====================
const liking = ref(false)
const starring = ref(false)

const handleToggleLike = async () => {
  if (!isLoggedIn.value) {
    Swal.fire({ icon: 'info', title: '请先登录', text: '登录后即可点赞专栏', timer: 1500, showConfirmButton: false })
    return
  }
  if (!detail.value || liking.value) return
  liking.value = true
  try {
    const res = await columnsApi.toggleLike(columnId.value)
    detail.value.is_liked = res.liked
    detail.value.like_count = res.like_count
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '操作失败', text: err.response?.data?.detail || err.message })
  } finally {
    liking.value = false
  }
}

const handleToggleStar = async () => {
  if (!isLoggedIn.value) {
    Swal.fire({ icon: 'info', title: '请先登录', text: '登录后即可收藏专栏', timer: 1500, showConfirmButton: false })
    return
  }
  if (!detail.value || starring.value) return
  starring.value = true
  try {
    const res = await columnsApi.toggleStar(columnId.value)
    detail.value.is_starred = res.starred
    detail.value.star_count = res.star_count
    Swal.fire({
      icon: 'success',
      title: res.starred ? '专栏已收藏' : '已取消收藏',
      timer: 1200,
      showConfirmButton: false,
    })
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '操作失败', text: err.response?.data?.detail || err.message })
  } finally {
    starring.value = false
  }
}

onMounted(() => {
  loadDetail()
})
</script>

<template>
  <div class="column-detail-page">
    <div class="column-container">
      <!-- 顶部面包屑与操作 -->
      <div class="nav-breadcrumbs">
        <router-link to="/" class="crumb-link"><i class="fa-solid fa-house"></i> 首页</router-link>
        <span class="crumb-sep">/</span>
        <span class="crumb-current">专栏详情</span>
      </div>

      <!-- 加载中 / 错误 -->
      <div v-if="loading" class="state-card loading-card">
        <i class="fa-solid fa-spinner fa-spin"></i> 加载专栏中...
      </div>

      <div v-else-if="error" class="state-card error-card">
        <i class="fa-solid fa-circle-exclamation"></i> {{ error }}
        <button class="btn-retry" @click="loadDetail">重试</button>
      </div>

      <template v-else-if="detail">
        <!-- 专栏头部主卡片 -->
        <div class="card column-header-card">
          <div class="column-header-body">
            <div class="column-cover-wrap">
              <img
                v-if="detail.cover_url"
                :src="detail.cover_url"
                alt="专栏封面"
                class="column-cover-img"
              />
              <div v-else class="column-cover-placeholder">
                <i class="fa-solid fa-book-bookmark"></i>
              </div>
            </div>

            <div class="column-main-info">
              <div class="title-row">
                <h1 class="column-title">{{ detail.title }}</h1>
                <span class="badge-cat" :class="getCategoryClass(detail.category)">
                  {{ detail.category || '算法理论' }}
                </span>
                <span v-if="detail.is_recommended" class="badge-recommended">
                  <i class="fa-solid fa-star"></i> 全站推荐
                </span>
              </div>

              <p class="column-desc">
                {{ detail.description || '作者很懒，还没有填写专栏简介~' }}
              </p>

              <div class="column-meta-row">
                <div class="author-info" v-if="detail.author">
                  <UserAvatarStatus :user="detail.author" :size="7">
                    <img
                      :src="detail.author.avatar_url || letterAvatar(detail.author.username)"
                      :alt="detail.author.username"
                    />
                  </UserAvatarStatus>
                  <router-link
                    :to="detail.author.user_number ? `/user/${detail.author.user_number}` : '#'"
                    class="author-name"
                    :style="{ color: userNameColor(detail.author) }"
                  >
                    {{ detail.author.username }}
                  </router-link>
                  <span
                    v-if="detail.author.user_tag"
                    class="user-tag"
                    :style="{ backgroundColor: userNameColor(detail.author) }"
                  >
                    {{ detail.author.user_tag }}
                  </span>
                </div>

                <div class="stat-items">
                  <span class="stat-item">
                    <i class="fa-solid fa-file-lines"></i> {{ detail.article_count }} 篇文章
                  </span>
                  <span class="stat-item">
                    <i class="fa-regular fa-thumbs-up"></i> {{ detail.like_count || 0 }} 点赞
                  </span>
                  <span class="stat-item">
                    <i class="fa-regular fa-bookmark"></i> {{ detail.star_count || 0 }} 收藏
                  </span>
                  <span class="stat-item">
                    <i class="fa-regular fa-clock"></i> 创建于 {{ fmtDateTime(detail.created_at) }}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <!-- 动作栏 -->
          <div class="column-action-bar">
            <!-- 点赞按钮 -->
            <button
              class="btn-action btn-like"
              :class="{ 'is-liked': detail.is_liked }"
              :disabled="liking"
              @click="handleToggleLike"
              title="点赞专栏"
            >
              <i :class="detail.is_liked ? 'fa-solid fa-thumbs-up' : 'fa-regular fa-thumbs-up'"></i>
              {{ detail.is_liked ? '已点赞' : '点赞' }} ({{ detail.like_count || 0 }})
            </button>

            <!-- 收藏按钮 -->
            <button
              class="btn-action btn-star"
              :class="{ 'is-starred': detail.is_starred }"
              :disabled="starring"
              @click="handleToggleStar"
              title="收藏专栏"
            >
              <i :class="detail.is_starred ? 'fa-solid fa-bookmark' : 'fa-regular fa-bookmark'"></i>
              {{ detail.is_starred ? '已收藏' : '收藏' }} ({{ detail.star_count || 0 }})
            </button>

            <!-- 管理员推荐按钮 -->
            <button
              v-if="isAdmin"
              class="btn-action btn-recommend"
              :class="{ 'is-active': detail.is_recommended }"
              :disabled="togglingRecommend"
              @click="handleToggleRecommend"
            >
              <i class="fa-solid fa-star"></i>
              {{ detail.is_recommended ? '取消全站推荐' : '设为全站推荐' }}
            </button>

            <!-- 投稿文章按钮 -->
            <button
              v-if="isLoggedIn"
              class="btn-action btn-contribute"
              @click="openContributeModal"
              title="投稿我的文章至该专栏"
            >
              <i class="fa-solid fa-paper-plane"></i> 投稿文章
            </button>

            <!-- 收录申请管理（专栏作者或管理员） -->
            <button
              v-if="canManage"
              class="btn-action btn-requests"
              @click="openRequestsModal"
              title="查看与处理收录申请"
            >
              <i class="fa-solid fa-inbox"></i> 收录申请
              <span v-if="pendingRequestsCount > 0" class="badge-pending-count">{{ pendingRequestsCount }}</span>
            </button>

            <!-- 作者操作 -->
            <template v-if="canManage">
              <button class="btn-action btn-primary" @click="openCreateArticle">
                <i class="fa-solid fa-pen-nib"></i> 写文章
              </button>
              <button class="btn-action btn-secondary" @click="openEditColumn">
                <i class="fa-solid fa-gear"></i> 编辑专栏
              </button>
              <button class="btn-action btn-danger" @click="handleDeleteColumn">
                <i class="fa-solid fa-trash-can"></i> 删除
              </button>
            </template>
          </div>
        </div>

        <!-- 专栏文章列表卡片 -->
        <div class="card articles-card">
          <div class="articles-header">
            <h2 class="section-title">
              <i class="fa-solid fa-list-ul"></i> 专栏目录
              <span class="count-pill">{{ detail.articles.length }}</span>
            </h2>
            <button v-if="canManage" class="btn-link-action" @click="openCreateArticle">
              <i class="fa-solid fa-plus"></i> 新增文章
            </button>
          </div>

          <div v-if="detail.articles.length === 0" class="empty-articles">
            <div class="empty-icon"><i class="fa-solid fa-feather-pointed"></i></div>
            <p>本专栏暂无发布的文章</p>
            <button v-if="canManage" class="btn-action btn-primary" @click="openCreateArticle">
              立即发布第一篇
            </button>
          </div>

          <div v-else class="article-list">
            <div
              v-for="(art, idx) in detail.articles"
              :key="art.id"
              class="article-item"
              @click="goToArticle(art.id)"
            >
              <div class="article-num">{{ idx + 1 }}</div>
              <div class="article-main">
                <div class="article-title-row">
                  <h3 class="article-title">{{ art.title }}</h3>
                  <span
                    v-if="art.author && art.author.id !== detail.author_id"
                    class="badge-guest-author"
                    title="非专栏创建者投稿文章"
                  >
                    <i class="fa-solid fa-user-pen"></i> 作者: {{ art.author.username }}
                  </span>
                </div>
                <p v-if="art.summary" class="article-summary">{{ art.summary }}</p>
                <div class="article-footer">
                  <span class="meta-field">
                    <i class="fa-regular fa-calendar"></i> {{ fmtDateTime(art.created_at) }}
                  </span>
                  <span class="meta-field">
                    <i class="fa-regular fa-eye"></i> {{ art.view_count }} 阅读
                  </span>
                </div>
              </div>

              <!-- 操作区 -->
              <div
                v-if="canManage || (currentUser && art.author && currentUser.id === art.author.id)"
                class="article-actions"
                @click.stop
              >
                <!-- 原作者或管理员可编辑文章 -->
                <button
                  v-if="(art.author && currentUser && art.author.id === currentUser.id) || isAdmin"
                  class="btn-icon"
                  title="编辑文章"
                  @click="openEditArticle(art)"
                >
                  <i class="fa-solid fa-pen"></i>
                </button>

                <!-- 原作者或管理员可彻底删除文章 -->
                <button
                  v-if="(art.author && currentUser && art.author.id === currentUser.id) || isAdmin"
                  class="btn-icon danger"
                  title="删除文章"
                  @click="handleDeleteArticle(art)"
                >
                  <i class="fa-solid fa-trash"></i>
                </button>

                <!-- 移出专栏：若当前是专栏作者但不是该文章原作者，或者文章原作者想单独将该文章从专栏移出 -->
                <button
                  v-if="(canManage && art.author && art.author.id !== detail.author_id) || (currentUser && art.author && currentUser.id === art.author.id)"
                  class="btn-icon warning"
                  title="将文章移出专栏（保留文章本体）"
                  @click="handleDetachArticle(art)"
                >
                  <i class="fa-solid fa-arrow-right-from-bracket"></i>
                </button>
              </div>
            </div>
          </div>
        </div>

      </template>
    </div>

    <!-- 弹窗：编辑专栏 -->
    <div v-if="showEditColumnModal" class="modal-backdrop" @click.self="showEditColumnModal = false">
      <div class="modal-card">
        <div class="modal-head">
          <h3>编辑专栏</h3>
          <button class="close-btn" @click="showEditColumnModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>专栏名称 <span class="req">*</span></label>
            <input v-model="editColumnForm.title" type="text" maxlength="100" class="form-input" placeholder="输入专栏标题" />
          </div>
          <div class="form-group">
            <label>专栏分类 <span class="req">*</span></label>
            <div class="category-select-group">
              <label
                v-for="cat in COLUMN_CATEGORIES"
                :key="cat"
                class="cat-radio-label"
                :class="{ active: editColumnForm.category === cat }"
              >
                <input
                  v-model="editColumnForm.category"
                  type="radio"
                  :value="cat"
                  style="display: none;"
                />
                {{ cat }}
              </label>
            </div>
          </div>
          <div class="form-group">
            <label>专栏简介</label>
            <textarea v-model="editColumnForm.description" rows="3" maxlength="2000" class="form-textarea" placeholder="介绍一下这个专栏的内容与面向读者"></textarea>
          </div>
          <div class="form-group">
            <label>封面图片链接（可选）</label>
            <input v-model="editColumnForm.cover_url" type="url" maxlength="500" class="form-input" placeholder="https://..." />
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn-secondary" @click="showEditColumnModal = false">取消</button>
          <button class="btn-primary" :disabled="editColumnLoading" @click="handleUpdateColumn">
            {{ editColumnLoading ? '保存中...' : '保存更改' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 弹窗：写文章 / 编辑文章 -->
    <div v-if="showArticleModal" class="modal-backdrop" @click.self="showArticleModal = false">
      <div class="modal-card modal-article-editor">
        <div class="modal-head">
          <h3>{{ articleModalMode === 'create' ? '撰写专栏文章' : '编辑专栏文章' }}</h3>
          <button class="close-btn" @click="showArticleModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>文章标题 <span class="req">*</span></label>
            <input v-model="articleForm.title" type="text" maxlength="150" class="form-input" placeholder="输入文章标题" />
          </div>

          <div class="form-group">
            <label>文章摘要（可选，留空将自动从正文截取）</label>
            <input v-model="articleForm.summary" type="text" maxlength="500" class="form-input" placeholder="简短的一两句话概括文章核心" />
          </div>

          <div class="form-group">
            <label class="field-label-bold">
              文章正文 (支持 Markdown / LaTeX 公式，实时分栏渲染) <span class="req">*</span>
            </label>
            <MarkdownSplitEditor
              v-model="articleForm.content"
              height="480px"
              placeholder="编写 Markdown 正文... 支持 KaTeX 公式（如 $O(n \log n)$ 与 $$\sum_{i=1}^n i$$）及代码高亮"
            />
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn-secondary" @click="showArticleModal = false">取消</button>
          <button class="btn-primary" :disabled="articleModalLoading" @click="handleSubmitArticle">
            {{ articleModalLoading ? '发布中...' : (articleModalMode === 'create' ? '发布文章' : '保存修改') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 弹窗：收录申请管理 -->
    <div v-if="showRequestsModal" class="modal-backdrop" @click.self="showRequestsModal = false">
      <div class="modal-card modal-inclusion">
        <div class="modal-head">
          <div class="modal-head-title">
            <h3>专栏收录申请</h3>
            <span v-if="pendingRequestsCount > 0" class="badge-pending-count">{{ pendingRequestsCount }} 待审核</span>
          </div>
          <button class="close-btn" @click="showRequestsModal = false">&times;</button>
        </div>

        <div class="modal-tabs">
          <button
            class="tab-btn"
            :class="{ active: requestFilter === 'pending' }"
            @click="requestFilter = 'pending'"
          >
            待审核 ({{ pendingRequestsCount }})
          </button>
          <button
            class="tab-btn"
            :class="{ active: requestFilter === 'reviewed' }"
            @click="requestFilter = 'reviewed'"
          >
            已处理 ({{ inclusionRequests.length - pendingRequestsCount }})
          </button>
          <button
            class="tab-btn"
            :class="{ active: requestFilter === 'all' }"
            @click="requestFilter = 'all'"
          >
            全部 ({{ inclusionRequests.length }})
          </button>
        </div>

        <div class="modal-body request-list-body">
          <div v-if="requestsLoading" class="loading-state">
            <i class="fa-solid fa-spinner fa-spin"></i> 加载申请中...
          </div>
          <div v-else-if="filteredRequests.length === 0" class="empty-state">
            <i class="fa-regular fa-folder-open empty-icon"></i>
            <p>暂无相关收录申请</p>
          </div>
          <div v-else class="request-items-list">
            <div
              v-for="req in filteredRequests"
              :key="req.id"
              class="request-card"
              :class="`status-${req.status}`"
            >
              <div class="request-card-head">
                <div class="req-author" v-if="req.applicant">
                  <UserAvatarStatus :user="req.applicant" :size="6">
                    <img
                      :src="req.applicant.avatar_url || letterAvatar(req.applicant.username)"
                      :alt="req.applicant.username"
                    />
                  </UserAvatarStatus>
                  <router-link
                    :to="req.applicant.user_number ? `/user/${req.applicant.user_number}` : '#'"
                    class="req-author-name"
                    :style="{ color: userNameColor(req.applicant) }"
                    target="_blank"
                  >
                    @{{ req.applicant.username }}
                  </router-link>
                  <span class="req-time">{{ fmtDateTime(req.created_at) }}</span>
                </div>

                <div class="req-status-tag" :class="`tag-${req.status}`">
                  <span v-if="req.status === 'pending'"><i class="fa-solid fa-hourglass-half"></i> 待审核</span>
                  <span v-else-if="req.status === 'approved'"><i class="fa-solid fa-check"></i> 已收录</span>
                  <span v-else-if="req.status === 'rejected'"><i class="fa-solid fa-xmark"></i> 已拒绝</span>
                  <span v-else-if="req.status === 'cancelled'"><i class="fa-solid fa-ban"></i> 申请人已撤回</span>
                </div>
              </div>

              <div class="req-article-info" v-if="req.article">
                <router-link
                  :to="`/article/${req.article.id}`"
                  target="_blank"
                  class="req-article-title"
                >
                  <i class="fa-solid fa-file-lines"></i> 《{{ req.article.title }}》
                  <i class="fa-solid fa-arrow-up-right-from-square title-ext-icon"></i>
                </router-link>
                <p v-if="req.article.summary" class="req-article-summary">
                  {{ req.article.summary }}
                </p>
              </div>

              <div v-if="req.message" class="req-message-box">
                <span class="message-label">申请理由：</span>
                <span class="message-text">{{ req.message }}</span>
              </div>

              <!-- 审核回复理由 -->
              <div v-if="req.reply" class="req-reply-box">
                <span class="reply-label">审核意见：</span>
                <span class="reply-text">{{ req.reply }}</span>
              </div>

              <!-- 待处理操作栏 -->
              <div v-if="req.status === 'pending'" class="req-actions-bar">
                <div v-if="showRejectInputMap[req.id]" class="reject-inline-input">
                  <input
                    v-model="rejectReplyMap[req.id]"
                    type="text"
                    class="form-input"
                    placeholder="输入拒绝理由（可选）"
                    maxlength="500"
                    @keyup.enter="handleReviewRequest(req, 'reject')"
                  />
                  <button
                    class="btn-sm btn-confirm-reject"
                    :disabled="reviewingRequestId === req.id"
                    @click="handleReviewRequest(req, 'reject')"
                  >
                    确认拒绝
                  </button>
                  <button
                    class="btn-sm btn-cancel-reject"
                    @click="showRejectInputMap[req.id] = false"
                  >
                    取消
                  </button>
                </div>
                <template v-else>
                  <button
                    class="btn-sm btn-approve"
                    :disabled="reviewingRequestId === req.id"
                    @click="handleReviewRequest(req, 'approve')"
                  >
                    <i class="fa-solid fa-check"></i> 同意收录
                  </button>
                  <button
                    class="btn-sm btn-reject"
                    :disabled="reviewingRequestId === req.id"
                    @click="handleReviewRequest(req, 'reject')"
                  >
                    <i class="fa-solid fa-xmark"></i> 拒绝
                  </button>
                </template>
              </div>
            </div>
          </div>
        </div>

        <div class="modal-foot">
          <button class="btn-secondary" @click="showRequestsModal = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- 弹窗：投稿文章至专栏 -->
    <div v-if="showContributeModal" class="modal-backdrop" @click.self="showContributeModal = false">
      <div class="modal-card">
        <div class="modal-head">
          <h3>投稿文章至「{{ detail?.title || '专栏' }}」</h3>
          <button class="close-btn" @click="showContributeModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <p class="modal-tip-desc">
            选择你已发表的文章申请收录至此专栏。专栏创建者审核通过后即可加入该专栏合集。
          </p>

          <div v-if="myArticlesLoading" class="loading-state">
            <i class="fa-solid fa-spinner fa-spin"></i> 正在加载我的文章列表...
          </div>
          <div v-else-if="myArticles.length === 0" class="empty-state">
            <p>你还没有发表任何文章，快去写一篇吧！</p>
            <router-link to="/articles" class="btn-primary" style="display:inline-block; padding: 6px 14px; text-decoration: none; border-radius: 6px; margin-top: 8px;">
              前往文章广场
            </router-link>
          </div>
          <template v-else>
            <div class="form-group">
              <label>选择要投稿的文章 <span class="req">*</span></label>
              <select v-model="selectedArticleId" class="form-select">
                <option :value="null" disabled>请选择一篇文章...</option>
                <option
                  v-for="art in myArticles"
                  :key="art.id"
                  :value="art.id"
                  :disabled="art.column_id === columnId"
                >
                  {{ art.title }} {{ art.column_id === columnId ? '（已在该专栏中）' : '' }}
                </option>
              </select>
            </div>

            <div class="form-group">
              <label>申请留言 / 推荐语（可选）</label>
              <textarea
                v-model="contributeMessage"
                rows="3"
                maxlength="500"
                class="form-textarea"
                placeholder="简单介绍一下文章内容以及为何适合收录至该专栏..."
              ></textarea>
            </div>
          </template>
        </div>
        <div class="modal-foot">
          <button class="btn-secondary" @click="showContributeModal = false">取消</button>
          <button
            class="btn-primary"
            :disabled="contributeSubmitting || !selectedArticleId"
            @click="handleSubmitContribute"
          >
            {{ contributeSubmitting ? '提交中...' : '提交申请' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.column-detail-page {
  padding: 24px 16px 60px;
  background-color: var(--color-background-soft, #f8fafc);
  min-height: calc(100vh - 60px);
}

.column-container {
  max-width: 1000px;
  margin: 0 auto;
}

.nav-breadcrumbs {
  margin-bottom: 16px;
  font-size: 13px;
  color: var(--text-sub);
  display: flex;
  align-items: center;
  gap: 8px;
}

.crumb-link {
  color: var(--text-sub);
  text-decoration: none;
  transition: color 0.2s;
}

.crumb-link:hover {
  color: var(--primary, #3b82f6);
}

.crumb-sep {
  color: #cbd5e1;
}

.crumb-current {
  color: var(--text-strong);
  font-weight: 500;
}

/* 通用卡片与状态 */
.card {
  background: var(--surface-plain);
  border-radius: 12px;
  border: 1px solid rgba(226, 232, 240, 0.8);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  margin-bottom: 24px;
}

.state-card {
  padding: 48px;
  text-align: center;
  border-radius: 12px;
  background: var(--surface-plain);
  border: 1px solid #e2e8f0;
  color: var(--text-sub);
}

.error-card {
  color: #ef4444;
}

.btn-retry {
  margin-left: 12px;
  padding: 4px 12px;
  border-radius: 6px;
  border: 1px solid #cbd5e1;
  background: var(--surface-plain);
  cursor: pointer;
}

/* 专栏头部主卡片 */
.column-header-card {
  padding: 24px;
}

.column-header-body {
  display: flex;
  gap: 24px;
}

.column-cover-wrap {
  width: 160px;
  height: 120px;
  border-radius: 10px;
  overflow: hidden;
  flex-shrink: 0;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.column-cover-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.column-cover-placeholder {
  width: 100%;
  height: 100%;
  background: linear-gradient(135deg, #6366f1, #a855f7);
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(255, 255, 255, 0.9);
  font-size: 40px;
}

.column-main-info {
  flex: 1;
  min-width: 0;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.column-title {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
color: light-dark(#0f172a, #d5dae2);
}

.badge-recommended {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: linear-gradient(135deg, #f59e0b, #d97706);
  color: #ffffff;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
  box-shadow: 0 2px 6px rgba(245, 158, 11, 0.3);
}

.badge-cat {
  font-size: 12px;
  padding: 2px 9px;
  border-radius: 6px;
  font-weight: 600;
}

.cat-algo {
  background: color-mix(in srgb, var(--primary) 8%, transparent);
color: var(--primary-text);
  border: 1px solid #91caff;
}

.cat-tech {
  background: color-mix(in srgb, var(--accent) 8%, transparent);
color: var(--accent-text);
  border: 1px solid #d3adf7;
}

.cat-sol {
  background: color-mix(in srgb, var(--success) 10%, transparent);
color: var(--success-text);
  border: 1px solid #b7eb8f;
}

.cat-fun {
  background: color-mix(in srgb, var(--warning) 12%, transparent);
color: var(--warning-text);
  border: 1px solid #ffd591;
}

.cat-default {
  background: var(--bg-subtle);
  color: var(--text-sub);
  border: 1px solid #d9d9d9;
}

.category-select-group {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.cat-radio-label {
  border: 1px solid var(--border-color);
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
  color: var(--text-muted);
}

.cat-radio-label:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.cat-radio-label.active {
  background: var(--primary);
  color: #fff;
  border-color: var(--primary);
}

.column-desc {
  margin: 0 0 16px;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-sub);
}

.column-meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
  padding-top: 12px;
  border-top: 1px solid #f1f5f9;
}

.author-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.author-info img {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  object-fit: cover;
}

.author-name {
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
}

.user-tag {
  color: #fff;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 500;
}

.stat-items {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: var(--text-sub);
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.column-action-bar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #f1f5f9;
}

.btn-action {
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  transition: all 0.2s;
}

.btn-recommend {
  background: color-mix(in srgb, var(--warning) 12%, transparent);
color: var(--warning-text);
  border: 1px solid #fde68a;
}

.btn-recommend:hover {
  background: #fde68a;
}

.btn-recommend.is-active {
  background: #f59e0b;
  color: #fff;
}

.btn-primary {
  background: var(--primary, #3b82f6);
  color: #fff;
}

.btn-primary:hover {
  filter: brightness(1.08);
}

.btn-secondary {
  background: var(--bg-subtle);
  color: var(--text-sub);
}

.btn-secondary:hover {
  background: #e2e8f0;
}

.btn-danger {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  color: #ef4444;
}

.btn-danger:hover {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
}

/* 文章列表卡片 */
.articles-card {
  padding: 24px;
}

.articles-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.section-title {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
color: light-dark(#0f172a, #d5dae2);
  display: flex;
  align-items: center;
  gap: 8px;
}

.count-pill {
  font-size: 12px;
  background: var(--bg-subtle);
  color: var(--text-sub);
  padding: 2px 8px;
  border-radius: 10px;
}

.btn-link-action {
  background: none;
  border: none;
  color: var(--primary, #3b82f6);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}

.empty-articles {
  padding: 48px 0;
  text-align: center;
  color: #94a3b8;
}

.empty-icon {
  font-size: 40px;
  margin-bottom: 12px;
  color: #cbd5e1;
}

.empty-articles p {
  margin: 0 0 16px;
  font-size: 14px;
}

.article-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.article-item {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  padding: 16px;
  border-radius: 10px;
  border: 1px solid #f1f5f9;
  background: var(--surface-plain);
  cursor: pointer;
  transition: all 0.2s;
}

.article-item:hover {
  background: var(--surface-plain);
  border-color: #cbd5e1;
  transform: translateY(-1px);
}

.article-num {
  font-size: 16px;
  font-weight: 700;
  color: #94a3b8;
  width: 28px;
  text-align: center;
  line-height: 1.5;
}

.article-main {
  flex: 1;
  min-width: 0;
}

.article-title {
  margin: 0 0 6px;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-strong);
}

.article-summary {
  margin: 0 0 10px;
  font-size: 13px;
  color: var(--text-sub);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.article-footer {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: #94a3b8;
}

.meta-field {
  display: flex;
  align-items: center;
  gap: 4px;
}

.article-actions {
  display: flex;
  gap: 6px;
}

.btn-icon {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
  background: var(--surface-plain);
  color: var(--text-sub);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}

.btn-icon:hover {
  background: var(--bg-subtle);
  color: var(--text-strong);
}

.btn-icon.danger:hover {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  color: #ef4444;
  border-color: #fca5a5;
}

/* 模态弹窗 */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(4px);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}

.modal-card {
  background: var(--surface-plain);
  border-radius: 14px;
  width: 100%;
  max-width: 520px;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.2);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.modal-lg {
  max-width: 820px;
}

.modal-article-editor {
  max-width: 1120px;
  width: 95vw;
  max-height: 94vh;
}

.modal-article-editor .modal-body {
  max-height: calc(94vh - 130px);
}

.field-label-bold {
  display: block;
  font-weight: 600;
  font-size: 13px;
  color: var(--text-strong);
  margin-bottom: 8px;
}

.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #f1f5f9;
}

.modal-head h3 {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
color: light-dark(#0f172a, #d5dae2);
}

.close-btn {
  background: none;
  border: none;
  font-size: 24px;
  color: #94a3b8;
  cursor: pointer;
}

.modal-body {
  padding: 20px;
  overflow-y: auto;
  max-height: 75vh;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-strong);
  margin-bottom: 6px;
}

.req {
  color: #ef4444;
}

.form-input,
.form-textarea {
  width: 100%;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid #cbd5e1;
  font-size: 14px;
  outline: none;
  transition: border-color 0.2s;
  box-sizing: border-box;
}

.form-input:focus,
.form-textarea:focus {
  border-color: var(--primary, #3b82f6);
}

.code-editor {
  font-family: Menlo, Monaco, Consolas, 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.5;
}

.editor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.tab-toggle {
  display: flex;
  background: var(--bg-subtle);
  border-radius: 6px;
  padding: 2px;
}

.toggle-btn {
  border: none;
  background: none;
  padding: 3px 10px;
  font-size: 12px;
  border-radius: 4px;
  cursor: pointer;
  color: var(--text-sub);
}

.toggle-btn.active {
  background: var(--surface-plain);
color: light-dark(#0f172a, #d5dae2);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.markdown-preview {
  min-height: 240px;
  max-height: 380px;
  overflow-y: auto;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: var(--surface-plain);
}

.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 20px;
  border-top: 1px solid #f1f5f9;
  background: var(--surface-plain);
}

.modal-foot button {
  padding: 8px 18px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border: none;
}

/* 点赞与收藏按钮 */
.btn-like {
  background: var(--surface-plain);
  color: var(--text-sub);
  border: 1px solid #e2e8f0;
}
.btn-like:hover {
  background: var(--bg-subtle);
  color: #2563eb;
  border-color: #bfdbfe;
}
.btn-like.is-liked {
  background: color-mix(in srgb, var(--primary) 8%, transparent);
color: var(--primary-text);
  border-color: #93c5fd;
  font-weight: 600;
}

.btn-star {
  background: var(--surface-plain);
  color: var(--text-sub);
  border: 1px solid #e2e8f0;
}
.btn-star:hover {
  background: color-mix(in srgb, var(--warning) 12%, transparent);
color: var(--warning-text);
  border-color: #fef08a;
}
.btn-star.is-starred {
  background: color-mix(in srgb, var(--warning) 12%, transparent);
color: var(--warning-text);
  border-color: #fde047;
  font-weight: 600;
}

/* 收录与投稿样式 */
.article-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.article-title-row .article-title {
  margin: 0;
}

.badge-guest-author {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  background: color-mix(in srgb, var(--primary) 8%, transparent);
color: var(--primary-text);
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 500;
}

.btn-requests {
  background: color-mix(in srgb, var(--accent) 8%, transparent);
color: var(--accent-text);
  border: 1px solid #f5d0fe;
  position: relative;
}
.btn-requests:hover {
  background: color-mix(in srgb, var(--accent) 8%, transparent);
  border-color: #f0abfc;
}

.btn-contribute {
  background: color-mix(in srgb, var(--success) 10%, transparent);
color: var(--success-text);
  border: 1px solid #bbf7d0;
}
.btn-contribute:hover {
  background: color-mix(in srgb, var(--success) 10%, transparent);
  border-color: #86efac;
}

.badge-pending-count {
  background: #ef4444;
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 10px;
  margin-left: 4px;
}

.btn-icon.warning:hover {
  background: color-mix(in srgb, var(--warning) 12%, transparent);
color: var(--warning-text);
  border-color: #fde68a;
}

.modal-inclusion {
  max-width: 680px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
}

.modal-head-title {
  display: flex;
  align-items: center;
  gap: 10px;
}

.modal-tabs {
  display: flex;
  gap: 8px;
  padding: 10px 20px;
  border-bottom: 1px solid #f1f5f9;
  background: var(--surface-plain);
}

.tab-btn {
  background: none;
  border: none;
  font-size: 13px;
  color: var(--text-sub);
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 500;
  transition: all 0.2s;
}

.tab-btn:hover {
  background: var(--bg-subtle);
  color: var(--text-strong);
}

.tab-btn.active {
  background: #3b82f6;
  color: #fff;
}

.request-list-body {
  max-height: calc(85vh - 180px);
  overflow-y: auto;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.request-items-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.request-card {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px 16px;
  background: var(--surface-plain);
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: all 0.2s;
}

.request-card:hover {
  border-color: #cbd5e1;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
}

.request-card.status-pending {
  border-left: 4px solid #3b82f6;
}

.request-card.status-approved {
  border-left: 4px solid #10b981;
}

.request-card.status-rejected {
  border-left: 4px solid #ef4444;
}

.request-card.status-cancelled {
  border-left: 4px solid #94a3b8;
}

.request-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.req-author {
  display: flex;
  align-items: center;
  gap: 8px;
}

.req-author img {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  object-fit: cover;
}

.req-author-name {
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
}

.req-time {
  font-size: 12px;
  color: #94a3b8;
  margin-left: 4px;
}

.req-status-tag {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 6px;
  font-weight: 500;
}

.tag-pending {
  background: color-mix(in srgb, var(--primary) 8%, transparent);
color: var(--primary-text);
}

.tag-approved {
  background: color-mix(in srgb, var(--success) 10%, transparent);
color: var(--success-text);
}

.tag-rejected {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
color: var(--danger-text);
}

.tag-cancelled {
  background: var(--bg-subtle);
  color: var(--text-sub);
}

.req-article-info {
  background: var(--surface-plain);
  border-radius: 8px;
  padding: 10px 12px;
}

.req-article-title {
  font-size: 14px;
  font-weight: 600;
color: light-dark(#0f172a, #d5dae2);
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.req-article-title:hover {
  color: #2563eb;
}

.title-ext-icon {
  font-size: 11px;
  opacity: 0.6;
}

.req-article-summary {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--text-sub);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.req-message-box,
.req-reply-box {
  font-size: 13px;
  line-height: 1.5;
  padding: 6px 10px;
  border-radius: 6px;
}

.req-message-box {
  background: color-mix(in srgb, var(--warning) 12%, transparent);
color: var(--warning-text);
}

.req-reply-box {
  background: var(--bg-subtle);
  color: var(--text-strong);
}

.message-label,
.reply-label {
  font-weight: 600;
  margin-right: 4px;
}

.req-actions-bar {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 4px;
}

.btn-approve {
  background: #10b981;
  color: #fff;
  border: none;
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}

.btn-approve:hover {
  background: #059669;
}

.btn-reject {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
color: var(--danger-text);
  border: 1px solid #fca5a5;
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}

.btn-reject:hover {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
}

.reject-inline-input {
  display: flex;
  gap: 6px;
  width: 100%;
  align-items: center;
}

.btn-confirm-reject {
  background: #dc2626;
  color: #fff;
  border: none;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
}

.btn-cancel-reject {
  background: var(--bg-subtle);
  color: var(--text-sub);
  border: none;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}

.modal-tip-desc {
  font-size: 13px;
  color: var(--text-sub);
  margin: 0 0 16px;
  line-height: 1.5;
}

.form-select {
  width: 100%;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid #cbd5e1;
  font-size: 14px;
  outline: none;
  background: var(--surface-plain);
}

@media (max-width: 640px) {
  .column-header-body {
    flex-direction: column;
    align-items: center;
    text-align: center;
  }
  .column-meta-row {
    flex-direction: column;
    align-items: center;
  }
  .column-action-bar {
    justify-content: center;
  }
}
</style>
