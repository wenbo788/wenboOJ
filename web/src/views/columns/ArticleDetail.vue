<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  articlesApi,
  columnsApi,
  COLUMN_CATEGORIES,
  type ColumnArticleDetail,
  type ColumnItem,
  type ArticleCommentItem,
  type ColumnInclusionRequestItem,
} from '@/api/columns'
import { problemsApi } from '@/api/problems'
import { userNameColor } from '@/utils/userColor'
import { fmtDateTime } from '@/utils/datetime'
import { renderRichText as renderMarkdown } from '@/utils/markdown'
import UserAvatarStatus from '@/components/UserAvatarStatus.vue'
import MarkdownSplitEditor from '@/components/MarkdownSplitEditor.vue'
import Swal from 'sweetalert2'

import { isSuperAdmin } from '@/utils/permissions'
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const articleId = computed(() => Number(route.params.articleId))

const article = ref<ColumnArticleDetail | null>(null)
const loading = ref(true)
const error = ref('')
const myColumns = ref<ColumnItem[]>([])

const currentUser = computed(() => authStore.currentUser)
const isLoggedIn = computed(() => authStore.isAuthenticated)
const isAdmin = computed(() => isSuperAdmin(currentUser.value))
const isAuthor = computed(() => {
  if (!currentUser.value || !article.value?.author) return false
  return currentUser.value.id === article.value.author.id
})
const canManage = computed(() => isAuthor.value || isAdmin.value)

const letterAvatar = (name: string) => {
  const ch = (name || 'U').trim().charAt(0).toUpperCase() || 'U'
  return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Crect width='40' height='40' fill='%23e74c3c'/%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' dy='.3em' fill='white' font-size='16' font-family='Arial'%3E${encodeURIComponent(ch)}%3C/text%3E%3C/svg%3E`
}

const loadArticle = async () => {
  loading.value = true
  error.value = ''
  try {
    const res = await articlesApi.get(articleId.value)
    article.value = res
  } catch (err: any) {
    console.error(err)
    error.value = err.response?.data?.detail || err.message || '加载文章失败'
  } finally {
    loading.value = false
  }
}

// ==================== 文章点赞与收藏 ====================
const liking = ref(false)
const starring = ref(false)

const handleToggleLike = async () => {
  if (!isLoggedIn.value) {
    Swal.fire({ icon: 'info', title: '请先登录', text: '登录后即可点赞文章', timer: 1500, showConfirmButton: false })
    return
  }
  if (!article.value || liking.value) return
  liking.value = true
  try {
    const res = await articlesApi.toggleLike(articleId.value)
    article.value.is_liked = res.liked
    article.value.like_count = res.like_count
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '操作失败', text: err.response?.data?.detail || err.message })
  } finally {
    liking.value = false
  }
}

const handleToggleStar = async () => {
  if (!isLoggedIn.value) {
    Swal.fire({ icon: 'info', title: '请先登录', text: '登录后即可收藏文章', timer: 1500, showConfirmButton: false })
    return
  }
  if (!article.value || starring.value) return
  starring.value = true
  try {
    const res = await articlesApi.toggleStar(articleId.value)
    article.value.is_starred = res.starred
    article.value.star_count = res.star_count
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '操作失败', text: err.response?.data?.detail || err.message })
  } finally {
    starring.value = false
  }
}

// ==================== 文章评论 ====================
const comments = ref<ArticleCommentItem[]>([])
const commentsLoading = ref(false)
const commentContent = ref('')
const commentSubmitting = ref(false)
const commentBox = ref<HTMLElement | null>(null)
const commentEditor = ref<InstanceType<typeof MarkdownSplitEditor> | null>(null)

const loadComments = async () => {
  commentsLoading.value = true
  try {
    const res = await articlesApi.getComments(articleId.value)
    comments.value = res || []
    if (article.value) {
      article.value.comment_count = comments.value.length
    }
  } catch (err) {
    console.error('加载文章评论失败:', err)
  } finally {
    commentsLoading.value = false
  }
}

const submitComment = async () => {
  if (!isLoggedIn.value) {
    router.push(`/login?redirect=${route.fullPath}`)
    return
  }
  const content = commentContent.value.trim()
  if (!content) {
    Swal.fire({ icon: 'warning', text: '评论内容不能为空' })
    return
  }
  commentSubmitting.value = true
  try {
    await articlesApi.createComment(articleId.value, content)
    commentContent.value = ''
    await loadComments()
    Swal.fire({ icon: 'success', title: '评论发表成功', timer: 1200, showConfirmButton: false })
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '评论发表失败', text: err.response?.data?.detail || err.message })
  } finally {
    commentSubmitting.value = false
  }
}

const handleDeleteComment = async (cmt: ArticleCommentItem) => {
  const confirmRes = await Swal.fire({
    title: '确认删除该评论？',
    text: '删除后无法恢复！',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonText: '删除',
    cancelButtonText: '取消',
    confirmButtonColor: '#ef4444',
  })
  if (!confirmRes.isConfirmed) return

  try {
    await articlesApi.deleteComment(articleId.value, cmt.id)
    comments.value = comments.value.filter((c) => c.id !== cmt.id)
    if (article.value) {
      article.value.comment_count = Math.max(0, (article.value.comment_count || 1) - 1)
    }
    Swal.fire({ icon: 'success', title: '评论已删除', timer: 1200, showConfirmButton: false })
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '删除失败', text: err.response?.data?.detail || err.message })
  }
}

const replyTo = (cmt: ArticleCommentItem) => {
  const name = cmt.author?.username
  if (!name) return
  commentContent.value = `@${name} ` + commentContent.value.replace(
    /^@[A-Za-z0-9_\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+\s*/, ''
  )
  commentBox.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  commentEditor.value?.focus()
}

const scrollToComments = () => {
  commentBox.value?.scrollIntoView({ behavior: 'smooth' })
}

// 推荐状态切换
const recLoading = ref(false)
const handleToggleRecommend = async () => {
  if (!article.value) return
  recLoading.value = true
  try {
    const nextState = !article.value.is_recommended
    const res = await articlesApi.toggleRecommend(articleId.value, nextState)
    article.value.is_recommended = res.is_recommended
    Swal.fire({
      icon: 'success',
      title: res.is_recommended ? '已设为全站精选推荐' : '已取消推荐',
      timer: 1200,
      showConfirmButton: false,
    })
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '操作失败', text: err.response?.data?.detail || err.message })
  } finally {
    recLoading.value = false
  }
}

// 编辑文章弹窗
const showEditModal = ref(false)
const editLoading = ref(false)
const editForm = ref({
  title: '',
  content: '',
  summary: '',
  category: '算法理论',
  cover_url: '',
  column_id: null as number | null,
  problem_code: '',
  clear_problem: false,
  apply_recommend: false,
  recommend_reason: '',
})

const editResolvingProblem = ref(false)
const editResolvedProblem = ref<{ id: number; title: string; difficulty?: string } | null>(null)
const editProblemError = ref('')

const checkEditProblemCode = async () => {
  const code = editForm.value.problem_code.trim()
  if (!code) {
    editResolvedProblem.value = null
    editProblemError.value = ''
    return
  }
  editResolvingProblem.value = true
  editProblemError.value = ''
  try {
    const p = await problemsApi.getByCode(code)
    editResolvedProblem.value = {
      id: p.id,
      title: p.title,
      difficulty: p.difficulty,
    }
  } catch {
    editResolvedProblem.value = null
    editProblemError.value = '未找到该题号对应的题目'
  } finally {
    editResolvingProblem.value = false
  }
}

const openEdit = async () => {
  if (!article.value) return
  try {
    if (authStore.isAuthenticated) {
      myColumns.value = await columnsApi.getMyColumns()
    }
  } catch {
    myColumns.value = []
  }
  editResolvedProblem.value = null
  editProblemError.value = ''
  const pCode = article.value.problem_code || (article.value.problem_id ? `P${1000 + article.value.problem_id}` : '')
  editForm.value = {
    title: article.value.title,
    content: article.value.content,
    summary: article.value.summary || '',
    category: article.value.category || '算法理论',
    cover_url: article.value.cover_url || '',
    column_id: article.value.column_id ?? null,
    problem_code: pCode,
    clear_problem: false,
    apply_recommend: article.value.recommend_status === 'pending' || !!article.value.is_recommended,
    recommend_reason: article.value.recommend_reason || '',
  }
  if (pCode) {
    checkEditProblemCode()
  }
  showEditModal.value = true
}

const handleUpdate = async () => {
  if (!editForm.value.title.trim()) {
    Swal.fire({ icon: 'warning', text: '文章标题不能为空' })
    return
  }
  if (!editForm.value.content.trim()) {
    Swal.fire({ icon: 'warning', text: '文章正文不能为空' })
    return
  }

  if (editForm.value.category === '题解') {
    if (!editForm.value.problem_code.trim() && !editForm.value.clear_problem) {
      Swal.fire({ icon: 'warning', text: '发布题解分类文章必须指定关联题号' })
      return
    }
    if (editProblemError.value) {
      Swal.fire({ icon: 'warning', text: '关联题目校验未通过，请检查题号' })
      return
    }
  }

  editLoading.value = true
  try {
    const res = await articlesApi.update(articleId.value, {
      title: editForm.value.title.trim(),
      content: editForm.value.content,
      summary: editForm.value.summary.trim() || undefined,
      category: editForm.value.category,
      cover_url: editForm.value.cover_url.trim() || undefined,
      column_id: editForm.value.column_id ?? 0,
      detach_column: editForm.value.column_id === null,
      problem_code: editForm.value.clear_problem ? undefined : (editForm.value.problem_code.trim() || undefined),
      clear_problem: editForm.value.clear_problem,
      apply_recommend: editForm.value.apply_recommend,
      recommend_reason: editForm.value.recommend_reason.trim() || undefined,
    })
    if (article.value) {
      article.value = res
    }
    showEditModal.value = false
    if (res.recommend_status === 'pending') {
      Swal.fire({
        icon: 'info',
        title: '已提交重新审核',
        text: '文章修改后需要重新审核，审核通过前其他用户无法看到本文。',
        confirmButtonText: '知道了',
      })
    } else {
      Swal.fire({ icon: 'success', title: '修改成功', timer: 1200, showConfirmButton: false })
    }
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '修改失败', text: err.response?.data?.detail || err.message })
  } finally {
    editLoading.value = false
  }
}

// 作者发布草稿（草稿仅作者可见，发布后才进入公开列表）
const publishingDraft = ref(false)

const handlePublishDraft = async () => {
  if (!article.value) return
  const confirmRes = await Swal.fire({
    title: '发布这篇草稿？',
    text: '发布后文章会进入公开列表（题解类需已关联题号且题解通道开放）。',
    icon: 'question',
    showCancelButton: true,
    confirmButtonText: '确认发布',
    cancelButtonText: '再改改',
    confirmButtonColor: 'var(--primary)',
    cancelButtonColor: '#909399',
  })
  if (!confirmRes.isConfirmed) return
  publishingDraft.value = true
  try {
    await articlesApi.publishDraft(article.value.id)
    Swal.fire({ icon: 'success', title: '已发布', timer: 1200, showConfirmButton: false })
    await loadArticle()
  } catch (err: any) {
    Swal.fire({
      icon: 'error',
      title: '发布失败',
      text: err.response?.data?.detail || err.message || '未知错误',
    })
  } finally {
    publishingDraft.value = false
  }
}

// 作者申请全站推荐
const handleApplyRecommend = async () => {
  if (!article.value) return
  if (article.value.category === '题解' && !article.value.problem_id && !article.value.problem_code) {
    Swal.fire({ icon: 'warning', text: '题解文章须先关联有效题号才能申请全站推荐' })
    return
  }
  const { value: reason, isConfirmed } = await Swal.fire({
    title: '申请全站推荐',
    text: '申请推荐通过后，文章将展示在文章广场公共流及题目题解区中。',
    input: 'text',
    inputPlaceholder: '请填写推荐理由或文章亮点（选填）',
    showCancelButton: true,
    confirmButtonText: '提交申请',
    cancelButtonText: '取消',
  })
  if (!isConfirmed) return

  try {
    const res = await articlesApi.applyRecommend(article.value.id, { reason: reason?.trim() || undefined })
    article.value = res
    Swal.fire({
      icon: 'success',
      title: '推荐申请已提交',
      text: '已提交至管理员审核，请耐心等待。',
      timer: 1500,
      showConfirmButton: false
    })
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '申请失败', text: err.response?.data?.detail || err.message })
  }
}

// 管理员审核全站推荐
const handleReviewRecommend = async (action: 'approve' | 'reject') => {
  if (!article.value) return
  let reason: string | undefined = undefined

  if (action === 'reject') {
    const { value: r, isConfirmed } = await Swal.fire({
      title: '驳回全站推荐申请',
      input: 'text',
      inputPlaceholder: '请输入驳回理由（必填，如：思路欠缺解析或格式需要调整）',
      showCancelButton: true,
      confirmButtonText: '确认驳回',
      cancelButtonText: '取消',
      preConfirm: (val) => {
        if (!val || !val.trim()) {
          Swal.showValidationMessage('驳回理由不能为空')
          return false
        }
        return val.trim()
      }
    })
    if (!isConfirmed) return
    reason = r
  } else {
    const confirmRes = await Swal.fire({
      title: '确认通过全站推荐？',
      text: `审核通过后，《${article.value.title}》将展示在文章广场精选流及题目题解专区。`,
      icon: 'question',
      showCancelButton: true,
      confirmButtonText: '确认通过',
      cancelButtonText: '取消',
    })
    if (!confirmRes.isConfirmed) return
  }

  try {
    const updated = await articlesApi.reviewRecommend(article.value.id, {
      action,
      reason,
    })
    article.value = updated
    Swal.fire({
      icon: 'success',
      title: action === 'approve' ? '已通过全站推荐' : '已驳回推荐申请',
      timer: 1500,
      showConfirmButton: false,
    })
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '操作失败', text: err.response?.data?.detail || err.message })
  }
}

const handleDelete = async () => {
  const confirmRes = await Swal.fire({
    title: '确认删除这篇文章？',
    text: '删除后无法恢复！',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonText: '删除',
    cancelButtonText: '取消',
    confirmButtonColor: '#ef4444',
  })
  if (!confirmRes.isConfirmed) return

  try {
    const colId = article.value?.column_id
    await articlesApi.delete(articleId.value)
    await Swal.fire({ icon: 'success', title: '文章已删除', timer: 1200, showConfirmButton: false })
    if (colId) {
      router.push(`/column/${colId}`)
    } else {
      router.push('/articles')
    }
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '删除失败', text: err.response?.data?.detail || err.message })
  }
}

// ==================== 移出专栏 ====================
const handleDetachFromColumn = async () => {
  if (!article.value?.column_id) return
  const confirmRes = await Swal.fire({
    title: '确认将文章移出当前专栏？',
    text: `文章《${article.value.title}》仍将作为独立文章保留，仅解除专栏收录关联。`,
    icon: 'question',
    showCancelButton: true,
    confirmButtonText: '确认移出',
    cancelButtonText: '取消',
    confirmButtonColor: '#f59e0b',
  })
  if (!confirmRes.isConfirmed) return

  try {
    await columnsApi.detachArticle(article.value.column_id, articleId.value)
    article.value.column_id = null
    article.value.column_title = undefined
    Swal.fire({ icon: 'success', title: '文章已从专栏移出', timer: 1200, showConfirmButton: false })
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '移出失败', text: err.response?.data?.detail || err.message })
  }
}

// ==================== 投稿至专栏与收录申请记录 ====================
const showInclusionModal = ref(false)
const inclusionActiveTab = ref<'apply' | 'records'>('apply')
const inclusionRequests = ref<ColumnInclusionRequestItem[]>([])
const inclusionLoading = ref(false)
const availableColumns = ref<ColumnItem[]>([])
const loadingColumns = ref(false)
const selectedColumnId = ref<number | null>(null)
const customColumnId = ref('')
const columnKeyword = ref('')
const inclusionMessage = ref('')
const submittingInclusion = ref(false)
const cancellingRequestId = ref<number | null>(null)

const pendingInclusionCount = computed(() => {
  return inclusionRequests.value.filter((r) => r.status === 'pending').length
})

const loadArticleInclusionRequests = async () => {
  if (!articleId.value) return
  inclusionLoading.value = true
  try {
    const list = await articlesApi.getInclusionRequests(articleId.value)
    inclusionRequests.value = list
  } catch (err: any) {
    console.error('加载收录记录失败:', err)
  } finally {
    inclusionLoading.value = false
  }
}

const loadAvailableColumns = async () => {
  loadingColumns.value = true
  try {
    const res = await columnsApi.list({
      page: 1,
      page_size: 50,
      keyword: columnKeyword.value.trim() || undefined,
    })
    availableColumns.value = res.items
  } catch (err: any) {
    console.error('获取专栏列表失败:', err)
  } finally {
    loadingColumns.value = false
  }
}

const openArticleInclusionModal = async () => {
  showInclusionModal.value = true
  selectedColumnId.value = null
  customColumnId.value = ''
  inclusionMessage.value = ''
  columnKeyword.value = ''
  await Promise.all([loadArticleInclusionRequests(), loadAvailableColumns()])
  if (inclusionRequests.value.length > 0 && !article.value?.column_id) {
    // 若有申请记录但未归属专栏，可保持当前选中的 tab
  }
}

const handleSubmitArticleInclusion = async () => {
  const colId = customColumnId.value.trim() ? Number(customColumnId.value.trim()) : selectedColumnId.value
  if (!colId || isNaN(colId)) {
    Swal.fire({ icon: 'warning', text: '请选择或输入要投稿的目标专栏' })
    return
  }
  if (article.value?.column_id === colId) {
    Swal.fire({ icon: 'warning', text: '该文章当前已收录于该专栏中' })
    return
  }

  submittingInclusion.value = true
  try {
    await columnsApi.applyInclusion(colId, {
      article_id: articleId.value,
      message: inclusionMessage.value.trim() || undefined,
    })
    Swal.fire({
      icon: 'success',
      title: '投稿申请已提交',
      text: '已发送至专栏创建者审核。',
      timer: 1500,
      showConfirmButton: false,
    })
    inclusionMessage.value = ''
    selectedColumnId.value = null
    customColumnId.value = ''
    inclusionActiveTab.value = 'records'
    await loadArticleInclusionRequests()
    await loadArticle()
  } catch (err: any) {
    Swal.fire({
      icon: 'error',
      title: '提交失败',
      text: err.response?.data?.detail || err.message,
    })
  } finally {
    submittingInclusion.value = false
  }
}

const handleCancelInclusionRequest = async (req: ColumnInclusionRequestItem) => {
  const confirmRes = await Swal.fire({
    title: '确认撤回该收录申请？',
    icon: 'question',
    showCancelButton: true,
    confirmButtonText: '撤回',
    cancelButtonText: '取消',
    confirmButtonColor: '#ef4444',
  })
  if (!confirmRes.isConfirmed) return

  cancellingRequestId.value = req.id
  try {
    await columnsApi.cancelInclusionRequest(req.column_id, req.id)
    Swal.fire({ icon: 'success', title: '申请已撤回', timer: 1200, showConfirmButton: false })
    await loadArticleInclusionRequests()
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '撤回失败', text: err.response?.data?.detail || err.message })
  } finally {
    cancellingRequestId.value = null
  }
}

watch(
  () => route.params.articleId,
  (newId) => {
    if (newId) {
      loadArticle()
      loadComments()
    }
  }
)

onMounted(() => {
  loadArticle()
  loadComments()
})
</script>

<template>
  <div class="article-detail-page">
    <div class="article-container">
      <!-- 导航面包屑 -->
      <div class="nav-breadcrumbs">
        <router-link to="/" class="crumb-link"><i class="fa-solid fa-house"></i> 首页</router-link>
        <span class="crumb-sep">/</span>
        <router-link to="/articles" class="crumb-link"><i class="fa-solid fa-newspaper"></i> 文章广场</router-link>
        <template v-if="article?.column_id">
          <span class="crumb-sep">/</span>
          <router-link :to="`/column/${article.column_id}`" class="crumb-link">
            <i class="fa-solid fa-book-bookmark"></i> {{ article?.column_title || '所属专栏' }}
          </router-link>
        </template>
        <span class="crumb-sep">/</span>
        <span class="crumb-current">正文阅读</span>
      </div>

      <!-- 加载中 / 错误 -->
      <div v-if="loading" class="state-card loading-card">
        <i class="fa-solid fa-spinner fa-spin"></i> 加载文章中...
      </div>

      <div v-else-if="error" class="state-card error-card">
        <i class="fa-solid fa-circle-exclamation"></i> {{ error }}
        <button class="btn-retry" @click="loadArticle">重试</button>
      </div>

      <!-- 文章卡片 -->
      <article v-else-if="article" class="card article-main-card">
        <header class="article-header">
          <div class="header-tags" v-if="article.is_recommended || article.category || article.column_id || article.problem_code || article.problem_id">
            <span v-if="article.is_recommended" class="badge-rec">
              <i class="fa-solid fa-fire"></i> 全站精选
            </span>
            <span v-if="article.category" class="badge-cat">
              {{ article.category }}
            </span>
            <router-link
              v-if="article.problem_code || article.problem_id"
              :to="`/problem/${article.problem_code || (article.problem_id ? 'P' + (1000 + article.problem_id) : '')}/solutions`"
              class="badge-problem"
              title="查看该题全部题解"
            >
              <i class="fa-solid fa-lightbulb"></i> 题目：{{ article.problem_code || (article.problem_id ? 'P' + (1000 + article.problem_id) : '') }} {{ article.problem_title ? ('· ' + article.problem_title) : '' }}
            </router-link>
            <router-link v-if="article.column_id" :to="`/column/${article.column_id}`" class="badge-col">
              <i class="fa-solid fa-book-bookmark"></i> 专栏：{{ article.column_title || '合集' }}
            </router-link>
          </div>

          <div v-if="article.is_draft" class="draft-banner">
            <i class="fa-regular fa-file-lines"></i>
            这是一篇<strong>草稿</strong>，尚未发布，仅你自己可见
          </div>

          <h1 class="article-title">{{ article.title }}</h1>

          <div class="article-meta-bar">
            <div class="author-block" v-if="article.author">
              <UserAvatarStatus :user="article.author" :size="8">
                <img
                  :src="article.author.avatar_url || letterAvatar(article.author.username)"
                  :alt="article.author.username"
                />
              </UserAvatarStatus>
              <div class="author-text">
                <router-link
                  :to="article.author.user_number ? `/user/${article.author.user_number}` : '#'"
                  class="author-name"
                  :style="{ color: userNameColor(article.author) }"
                >
                  {{ article.author.username }}
                </router-link>
                <span
                  v-if="article.author.user_tag"
                  class="user-tag"
                  :style="{ backgroundColor: userNameColor(article.author) }"
                >
                  {{ article.author.user_tag }}
                </span>
              </div>
            </div>

            <div class="meta-right">
              <span class="meta-tag"><i class="fa-regular fa-clock"></i> {{ fmtDateTime(article.created_at) }}</span>
              <span class="meta-tag"><i class="fa-regular fa-eye"></i> {{ article.view_count }} 阅读</span>
              <span class="meta-tag"><i class="fa-regular fa-thumbs-up"></i> {{ article.like_count || 0 }} 点赞</span>
              <span class="meta-tag"><i class="fa-regular fa-bookmark"></i> {{ article.star_count || 0 }} 收藏</span>
              <span class="meta-tag meta-comment-tag" @click="scrollToComments" title="跳转至评论区">
                <i class="fa-regular fa-comment-dots"></i> {{ article.comment_count || comments.length }} 评论
              </span>

              <!-- 操作按钮 -->
              <div class="action-btns">
                <button
                  v-if="isAdmin"
                  class="btn-sm"
                  :class="{ 'btn-rec-active': article.is_recommended }"
                  :disabled="recLoading"
                  @click="handleToggleRecommend"
                >
                  <i class="fa-solid" :class="article.is_recommended ? 'fa-star-half-stroke' : 'fa-star'"></i>
                  {{ article.is_recommended ? '取消精选' : '设为精选' }}
                </button>
                <!-- 草稿：作者可就地发布（发布后才允许申请推荐/投稿专栏） -->
                <button
                  v-if="isAuthor && article.is_draft"
                  class="btn-sm btn-publish-draft"
                  :disabled="publishingDraft"
                  @click="handlePublishDraft"
                  title="发布后文章才会进入公开列表"
                >
                  <i class="fa-solid fa-upload"></i>
                  {{ publishingDraft ? '发布中...' : '发布草稿' }}
                </button>
                <button
                  v-if="isAuthor && !article.is_draft && !article.is_recommended && article.recommend_status !== 'pending'"
                  class="btn-sm btn-apply-rec"
                  @click="handleApplyRecommend"
                  title="申请将文章展示至全站文章广场精选流与对应题目题解区"
                >
                  <i class="fa-solid fa-paper-plane"></i> 申请全站推荐
                </button>
                <button
                  v-if="isAuthor"
                  class="btn-sm btn-contribute-column"
                  @click="openArticleInclusionModal"
                  title="投稿到他人专栏合集或查看收录状态"
                >
                  <i class="fa-solid fa-paper-plane"></i> 投稿至专栏
                  <span v-if="pendingInclusionCount > 0" class="badge-dot"></span>
                </button>
                <button
                  v-if="article.column_id && canManage"
                  class="btn-sm btn-detach"
                  @click="handleDetachFromColumn"
                  title="将文章从专栏移出（保留文章本体）"
                >
                  <i class="fa-solid fa-arrow-right-from-bracket"></i> 移出专栏
                </button>
                <button v-if="canManage" class="btn-sm" @click="openEdit"><i class="fa-solid fa-pen"></i> 编辑</button>
                <button v-if="canManage" class="btn-sm danger" @click="handleDelete"><i class="fa-solid fa-trash"></i> 删除</button>
              </div>
            </div>
          </div>
        </header>

        <!-- 全站推荐状态横幅（待审核 / 驳回附带原因） -->
        <div v-if="article.recommend_status === 'pending'" class="recommend-status-banner pending">
          <div class="banner-left">
            <i class="fa-solid fa-clock"></i>
            <span>全站推荐申请正在等待管理员审核，审核期间仅你与管理员可见</span>
            <span v-if="article.recommend_reason" class="banner-reason">（申请理由：{{ article.recommend_reason }}）</span>
          </div>
          <div v-if="isAdmin" class="banner-actions">
            <button class="btn-banner-action approve" @click="handleReviewRecommend('approve')">
              <i class="fa-solid fa-check"></i> 审核通过推荐
            </button>
            <button class="btn-banner-action reject" @click="handleReviewRecommend('reject')">
              <i class="fa-solid fa-xmark"></i> 驳回
            </button>
          </div>
        </div>

        <div v-else-if="article.recommend_status === 'rejected'" class="recommend-status-banner rejected">
          <div class="banner-left">
            <i class="fa-solid fa-circle-exclamation"></i>
            <span>全站推荐申请未通过审核</span>
            <span v-if="article.recommend_reason" class="banner-reason">（驳回原因：{{ article.recommend_reason }}）</span>
          </div>
          <div v-if="isAuthor" class="banner-actions">
            <button class="btn-banner-action retry" @click="handleApplyRecommend">
              <i class="fa-solid fa-rotate-right"></i> 重新申请推荐
            </button>
          </div>
        </div>

        <!-- 文章主体 Markdown 渲染 -->
        <div class="article-body prose" v-html="renderMarkdown(article.content)"></div>

        <!-- 文章互动操作栏 -->
        <div class="article-actions-bar">
          <button
            class="action-btn btn-like"
            :class="{ 'is-liked': article.is_liked }"
            :disabled="liking"
            @click="handleToggleLike"
            title="点赞文章"
          >
            <i :class="article.is_liked ? 'fa-solid fa-thumbs-up' : 'fa-regular fa-thumbs-up'"></i>
            <span>{{ article.is_liked ? '已点赞' : '点赞' }}</span>
            <span class="action-count">{{ article.like_count || 0 }}</span>
          </button>

          <button
            class="action-btn btn-star"
            :class="{ 'is-starred': article.is_starred }"
            :disabled="starring"
            @click="handleToggleStar"
            title="收藏文章"
          >
            <i :class="article.is_starred ? 'fa-solid fa-bookmark' : 'fa-regular fa-bookmark'"></i>
            <span>{{ article.is_starred ? '已收藏' : '收藏' }}</span>
            <span class="action-count">{{ article.star_count || 0 }}</span>
          </button>

          <button
            class="action-btn btn-comment-anchor"
            @click="scrollToComments"
            title="前往评论区"
          >
            <i class="fa-regular fa-comment-dots"></i>
            <span>评论</span>
            <span class="action-count">{{ article.comment_count || comments.length }}</span>
          </button>
        </div>

        <!-- 底部返回与专栏跳转 -->
        <footer class="article-footer">
          <router-link v-if="article.column_id" :to="`/column/${article.column_id}`" class="back-column-btn">
            <i class="fa-solid fa-arrow-left"></i> 返回所属专栏 ({{ article.column_title }})
          </router-link>
          <router-link to="/articles" class="back-column-btn secondary">
            <i class="fa-solid fa-compass"></i> 返回文章广场
          </router-link>
        </footer>
      </article>

      <!-- 文章评论卡片 -->
      <div v-if="article" class="card comments-card" id="comments">
        <div class="comments-header">
          <h2 class="section-title">
            <i class="fa-solid fa-comments"></i> 评论
            <span class="count-pill">{{ comments.length }}</span>
          </h2>
        </div>

        <!-- 评论列表 -->
        <div v-if="commentsLoading" class="comment-loading">
          <i class="fa-solid fa-spinner fa-spin"></i> 正在加载评论...
        </div>
        <div v-else-if="comments.length === 0" class="empty-comments">
          <div class="empty-icon"><i class="fa-regular fa-comment-dots"></i></div>
          <p>暂无评论，来发表第一条评论吧~</p>
        </div>
        <div v-else class="comment-list">
          <div v-for="(cmt, idx) in comments" :key="cmt.id" class="comment-item">
            <div class="comment-avatar">
              <UserAvatarStatus v-if="cmt.author" :user="cmt.author" :size="7">
                <img
                  :src="cmt.author.avatar_url || letterAvatar(cmt.author.username)"
                  :alt="cmt.author.username"
                />
              </UserAvatarStatus>
              <img v-else :src="letterAvatar('?')" alt="已注销用户" />
            </div>
            <div class="comment-main">
              <div class="comment-top">
                <div class="comment-author-info">
                  <template v-if="cmt.author">
                    <router-link
                      :to="cmt.author.user_number ? `/user/${cmt.author.user_number}` : '#'"
                      class="comment-author-name"
                      :style="{ color: userNameColor(cmt.author) }"
                    >
                      {{ cmt.author.username }}
                    </router-link>
                    <span v-if="cmt.is_author" class="badge-col-author">文章作者</span>
                    <span
                      v-else-if="cmt.author.user_tag"
                      class="user-tag"
                      :style="{ backgroundColor: userNameColor(cmt.author) }"
                    >
                      {{ cmt.author.user_tag }}
                    </span>
                  </template>
                  <span v-else class="comment-author-name" style="color: #94a3b8;">已注销用户</span>
                  <span class="comment-floor">#{{ idx + 1 }}</span>
                  <span class="comment-time">
                    <i class="fa-regular fa-clock"></i> {{ fmtDateTime(cmt.created_at) }}
                  </span>
                </div>
                <div class="comment-actions">
                  <button v-if="isLoggedIn" class="btn-comment-act" @click="replyTo(cmt)" title="回复此评论">
                    <i class="fa-solid fa-reply"></i> 回复
                  </button>
                  <button
                    v-if="cmt.can_delete"
                    class="btn-comment-act danger"
                    @click="handleDeleteComment(cmt)"
                    title="删除此评论"
                  >
                    <i class="fa-solid fa-trash-can"></i> 删除
                  </button>
                </div>
              </div>

              <div class="comment-body markdown-body prose" v-html="renderMarkdown(cmt.content)"></div>
            </div>
          </div>
        </div>

        <!-- 发表评论区域 -->
        <div ref="commentBox" class="comment-editor-section">
          <h3 class="editor-section-title">
            <i class="fa-solid fa-pen-to-square"></i> 发表评论
            <span class="editor-tip">支持 Markdown 语法与 LaTeX 数学公式</span>
          </h3>
          <div v-if="isLoggedIn" class="editor-wrap">
            <MarkdownSplitEditor
              ref="commentEditor"
              v-model="commentContent"
              height="200px"
              :maxlength="10000"
              placeholder="写下你的想法或与作者讨论，支持 Markdown 及 $E=mc^2$ 公式..."
            />
            <div class="editor-bottom-bar">
              <span class="editor-hint">
                <i class="fa-solid fa-circle-info"></i> 请文明发言，遵守社区规范
              </span>
              <button
                class="btn-action btn-primary btn-submit-comment"
                :disabled="commentSubmitting || !commentContent.trim()"
                @click="submitComment"
              >
                <i v-if="commentSubmitting" class="fa-solid fa-spinner fa-spin"></i>
                <i v-else class="fa-solid fa-paper-plane"></i>
                {{ commentSubmitting ? '发送中...' : '发表评论' }}
              </button>
            </div>
          </div>
          <div v-else class="comment-login-prompt">
            <i class="fa-regular fa-user"></i>
            <span>登录后参与文章评论与讨论</span>
            <router-link :to="`/login?redirect=${route.fullPath}`" class="btn-action btn-primary btn-sm-link">
              立即登录
            </router-link>
          </div>
        </div>
      </div>
    </div>

    <!-- 弹窗：编辑文章 -->
    <div v-if="showEditModal" class="modal-backdrop" @click.self="showEditModal = false">
      <div class="modal-card modal-article-editor">
        <div class="modal-head">
          <h3>编辑文章</h3>
          <button class="close-btn" @click="showEditModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>文章标题 <span class="req">*</span></label>
            <input v-model="editForm.title" type="text" maxlength="150" class="form-input" placeholder="输入文章标题" />
          </div>

          <div class="form-row-2">
            <div class="form-group">
              <label>文章分类</label>
              <select v-model="editForm.category" class="form-select">
                <option v-for="cat in COLUMN_CATEGORIES" :key="cat" :value="cat">
                  {{ cat }}
                </option>
              </select>
            </div>
            <div class="form-group">
              <label>所属专栏（合集）</label>
              <select v-model="editForm.column_id" class="form-select">
                <option :value="null">独立文章（不归属任何专栏）</option>
                <option v-for="col in myColumns" :key="col.id" :value="col.id">
                  {{ col.title }}
                </option>
              </select>
              <p class="form-help-tip" v-if="article?.column_id && !myColumns.some(c => c.id === article?.column_id)">
                当前文章正收录于专栏「{{ article.column_title }}」，选择“独立文章”并保存可脱离该专栏。
              </p>
            </div>
          </div>

          <!-- 题解分类专属：关联题目 -->
          <div v-if="editForm.category === '题解'" class="solution-link-section">
            <div class="form-group">
              <label>关联题号 <span class="req">*</span></label>
              <div class="problem-input-wrap">
                <input
                  v-model="editForm.problem_code"
                  type="text"
                  class="form-input"
                  placeholder="请输入题号（如 P1001、T1、U1001）"
                  @blur="checkEditProblemCode"
                  @keydown.enter.prevent="checkEditProblemCode"
                />
                <button type="button" class="btn-check-prob" :disabled="editResolvingProblem" @click="checkEditProblemCode">
                  <i v-if="editResolvingProblem" class="fa-solid fa-spinner fa-spin"></i>
                  <i v-else class="fa-solid fa-magnifying-glass"></i> 校验题目
                </button>
              </div>
              <div v-if="editResolvedProblem" class="prob-resolved-hint success">
                <i class="fa-solid fa-circle-check"></i>
                已关联题目：<b>{{ editResolvedProblem.title }}</b>
                <span v-if="editResolvedProblem.difficulty" class="diff-tag">{{ editResolvedProblem.difficulty }}</span>
              </div>
              <div v-else-if="editProblemError" class="prob-resolved-hint error">
                <i class="fa-solid fa-circle-exclamation"></i>
                {{ editProblemError }}
              </div>
            </div>
          </div>

          <!-- 全站推荐申请（未推荐时可勾选） -->
          <div class="form-group rec-apply-card" v-if="!article?.is_recommended">
            <label class="checkbox-label">
              <input type="checkbox" v-model="editForm.apply_recommend" />
              <span><b>申请全站推荐</b>（审核通过后展示在文章广场精选流及题目题解区，并奖励 20 点贡献值）</span>
            </label>
            <div v-if="editForm.apply_recommend" class="rec-reason-wrap">
              <input
                v-model="editForm.recommend_reason"
                type="text"
                class="form-input form-input-sm"
                placeholder="申请理由或文章特色（选填，如：更新了解法思路与复杂度）"
                maxlength="200"
              />
            </div>
          </div>

          <div class="form-group">
            <label>封面图片链接（可选）</label>
            <input v-model="editForm.cover_url" type="url" maxlength="500" class="form-input" placeholder="https://..." />
          </div>

          <div class="form-group">
            <label>文章摘要（可选）</label>
            <input v-model="editForm.summary" type="text" maxlength="500" class="form-input" placeholder="文章概要简介" />
          </div>

          <div class="form-group">
            <label class="field-label-bold">
              文章正文 (支持 Markdown / LaTeX 公式，实时分栏渲染) <span class="req">*</span>
            </label>
            <MarkdownSplitEditor
              v-model="editForm.content"
              height="480px"
              placeholder="编写 Markdown 正文... 支持 KaTeX 公式（如 $O(n \log n)$ 与 $$\sum_{i=1}^n i$$）及代码高亮"
            />
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn-secondary" @click="showEditModal = false">取消</button>
          <button class="btn-primary" :disabled="editLoading" @click="handleUpdate">
            {{ editLoading ? '保存中...' : '保存更改' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 弹窗：专栏投稿与收录申请管理 -->
    <div v-if="showInclusionModal" class="modal-backdrop" @click.self="showInclusionModal = false">
      <div class="modal-card modal-inclusion">
        <div class="modal-head">
          <div class="modal-head-title">
            <h3>投稿至专栏</h3>
            <span v-if="article?.column_id" class="badge-current-col">
              当前收录于：{{ article.column_title }}
            </span>
          </div>
          <button class="close-btn" @click="showInclusionModal = false">&times;</button>
        </div>

        <div class="modal-tabs">
          <button
            class="tab-btn"
            :class="{ active: inclusionActiveTab === 'apply' }"
            @click="inclusionActiveTab = 'apply'"
          >
            <i class="fa-solid fa-paper-plane"></i> 申请收录
          </button>
          <button
            class="tab-btn"
            :class="{ active: inclusionActiveTab === 'records' }"
            @click="inclusionActiveTab = 'records'"
          >
            <i class="fa-solid fa-clock-rotate-left"></i> 申请记录
            <span v-if="inclusionRequests.length > 0" class="badge-pill">{{ inclusionRequests.length }}</span>
          </button>
        </div>

        <div class="modal-body modal-body-inclusion">
          <!-- 标签 1：申请收录 -->
          <div v-if="inclusionActiveTab === 'apply'" class="tab-content-apply">
            <p class="modal-tip-desc">
              向他人创建的专栏发送收录申请，专栏创建者审核同意后将收录该文章。
            </p>

            <div class="form-group">
              <label>目标专栏搜索与选择</label>
              <div class="search-input-wrap">
                <input
                  v-model="columnKeyword"
                  type="text"
                  class="form-input"
                  placeholder="搜索专栏标题关键词..."
                  @input="loadAvailableColumns"
                />
              </div>

              <div class="column-select-list">
                <div v-if="loadingColumns" class="column-list-empty">
                  <i class="fa-solid fa-spinner fa-spin"></i> 正在加载专栏列表...
                </div>
                <div v-else-if="availableColumns.length === 0" class="column-list-empty">
                  未找到匹配专栏
                </div>
                <div
                  v-for="col in availableColumns"
                  :key="col.id"
                  class="column-option-card"
                  :class="{ selected: selectedColumnId === col.id, disabled: col.id === article?.column_id }"
                  @click="col.id !== article?.column_id && (selectedColumnId = col.id, customColumnId = '')"
                >
                  <div class="col-opt-info">
                    <div class="col-opt-title">{{ col.title }}</div>
                    <div class="col-opt-meta">
                      <span class="col-opt-author">创建者: {{ col.author?.username || '用户' }}</span>
                      <span class="col-opt-count">{{ col.article_count }} 篇文章</span>
                    </div>
                  </div>
                  <div class="col-opt-badge" v-if="col.id === article?.column_id">当前专栏</div>
                  <div class="col-opt-check" v-else-if="selectedColumnId === col.id">
                    <i class="fa-solid fa-check"></i>
                  </div>
                </div>
              </div>
            </div>

            <div class="form-group">
              <label>或直接输入专栏 ID</label>
              <input
                v-model="customColumnId"
                type="number"
                class="form-input"
                placeholder="例如：12"
                @input="selectedColumnId = null"
              />
            </div>

            <div class="form-group">
              <label>申请理由 / 推荐语（可选）</label>
              <textarea
                v-model="inclusionMessage"
                rows="3"
                maxlength="500"
                class="form-textarea"
                placeholder="向专栏作者阐述文章内容与为何契合该专栏..."
              ></textarea>
            </div>

            <div class="apply-actions">
              <button
                class="btn-primary"
                :disabled="submittingInclusion || (!selectedColumnId && !customColumnId.trim())"
                @click="handleSubmitArticleInclusion"
              >
                {{ submittingInclusion ? '发送中...' : '提交投稿申请' }}
              </button>
            </div>
          </div>

          <!-- 标签 2：申请记录 -->
          <div v-else class="tab-content-records">
            <div v-if="inclusionLoading" class="column-list-empty">
              <i class="fa-solid fa-spinner fa-spin"></i> 正在加载申请记录...
            </div>
            <div v-else-if="inclusionRequests.length === 0" class="column-list-empty">
              暂无收录申请记录
            </div>
            <div v-else class="record-items-list">
              <div
                v-for="req in inclusionRequests"
                :key="req.id"
                class="record-card"
                :class="`status-${req.status}`"
              >
                <div class="record-head">
                  <div class="record-col-name" v-if="req.column">
                    <router-link :to="`/column/${req.column.id}`" target="_blank" class="record-col-link">
                      <i class="fa-solid fa-book-bookmark"></i> {{ req.column.title }}
                      <i class="fa-solid fa-arrow-up-right-from-square"></i>
                    </router-link>
                  </div>
                  <div class="req-status-tag" :class="`tag-${req.status}`">
                    <span v-if="req.status === 'pending'"><i class="fa-solid fa-hourglass-half"></i> 待审核</span>
                    <span v-else-if="req.status === 'approved'"><i class="fa-solid fa-check"></i> 已同意收录</span>
                    <span v-else-if="req.status === 'rejected'"><i class="fa-solid fa-xmark"></i> 已拒绝</span>
                    <span v-else-if="req.status === 'cancelled'"><i class="fa-solid fa-ban"></i> 申请人已撤回</span>
                  </div>
                </div>

                <div class="record-time">
                  申请时间：{{ fmtDateTime(req.created_at) }}
                </div>

                <div v-if="req.message" class="req-message-box">
                  <span class="message-label">我的附言：</span>
                  <span class="message-text">{{ req.message }}</span>
                </div>

                <div v-if="req.reply" class="req-reply-box">
                  <span class="reply-label">专栏作者回复：</span>
                  <span class="reply-text">{{ req.reply }}</span>
                </div>

                <div v-if="req.status === 'pending'" class="record-actions">
                  <button
                    class="btn-sm btn-cancel-request"
                    :disabled="cancellingRequestId === req.id"
                    @click="handleCancelInclusionRequest(req)"
                  >
                    撤回申请
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="modal-foot">
          <button class="btn-secondary" @click="showInclusionModal = false">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 草稿横幅：仅作者能看到草稿详情，横幅提示当前处于未发布状态 */
.draft-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 10px 0 6px;
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 13px;
  color: var(--warning-text);
  background: color-mix(in srgb, var(--warning) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--warning) 35%, transparent);
}

.btn-publish-draft {
  color: var(--primary);
  border-color: color-mix(in srgb, var(--primary) 45%, transparent);
}

.btn-publish-draft:disabled {
  opacity: .5;
  cursor: not-allowed;
}

.article-detail-page {
  padding: 24px 16px 60px;
  min-height: calc(100vh - 60px);
}

.article-container {
  max-width: 900px;
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

/* 状态卡片 */
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

/* 主文章卡片 */
.article-main-card {
  background: var(--surface-plain);
  border-radius: 14px;
  border: 1px solid rgba(226, 232, 240, 0.8);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04);
  padding: 36px 40px;
}

.article-header {
  margin-bottom: 28px;
  padding-bottom: 20px;
  border-bottom: 1px solid #f1f5f9;
}

.header-tags {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.badge-rec {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
color: var(--danger-text);
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border: 1px solid #fecaca;
  padding: 2px 10px;
  border-radius: 9999px;
}

.badge-cat {
  font-size: 12px;
  font-weight: 500;
color: var(--primary-text);
  background: color-mix(in srgb, var(--primary) 8%, transparent);
  border: 1px solid #dbeafe;
  padding: 2px 10px;
  border-radius: 9999px;
}

.badge-col {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-sub);
  background: var(--bg-subtle);
  border: 1px solid #e2e8f0;
  padding: 2px 10px;
  border-radius: 9999px;
  text-decoration: none;
  transition: all 0.2s;
}

.badge-col:hover {
  background: #e2e8f0;
  color: #0f172a;
}

.badge-problem {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 600;
  color: #b45309;
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.3);
  padding: 2px 10px;
  border-radius: 9999px;
  text-decoration: none;
  transition: all 0.2s;
}

.badge-problem:hover {
  background: rgba(245, 158, 11, 0.22);
  border-color: #f59e0b;
}

/* 全站推荐横幅 */
.recommend-status-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 18px;
  border-radius: 8px;
  margin-bottom: 24px;
  font-size: 13px;
  font-weight: 500;
  flex-wrap: wrap;
}

.recommend-status-banner.pending {
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.3);
  color: #b45309;
}

.recommend-status-banner.rejected {
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #b91c1c;
}

.banner-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.banner-reason {
  color: var(--text-sub);
  font-size: 12px;
}

.banner-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-banner-action {
  padding: 5px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid transparent;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  transition: all 0.2s;
}

.btn-banner-action.approve {
  background: #10b981;
  color: #fff;
}

.btn-banner-action.approve:hover {
  background: #059669;
}

.btn-banner-action.reject {
  background: #ef4444;
  color: #fff;
}

.btn-banner-action.reject:hover {
  background: #dc2626;
}

.btn-banner-action.retry {
  background: #f59e0b;
  color: #fff;
}

.btn-banner-action.retry:hover {
  background: #d97706;
}

.btn-apply-rec {
  background: rgba(245, 158, 11, 0.1);
  border-color: rgba(245, 158, 11, 0.4);
  color: #b45309;
}

.btn-apply-rec:hover {
  background: rgba(245, 158, 11, 0.2);
  border-color: #f59e0b;
}

.solution-link-section {
  background: rgba(245, 158, 11, 0.04);
  border: 1px dashed rgba(245, 158, 11, 0.35);
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 14px;
}

.problem-input-wrap {
  display: flex;
  gap: 8px;
  align-items: center;
}

.btn-check-prob {
  padding: 8px 14px;
  border-radius: 6px;
  border: 1px solid var(--border-color);
  background: var(--surface-plain);
  font-size: 13px;
  font-weight: 600;
  color: var(--text-sub);
  cursor: pointer;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s;
}

.btn-check-prob:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
}

.prob-resolved-hint {
  margin-top: 6px;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.prob-resolved-hint.success {
  color: var(--success-text, #16a34a);
}

.prob-resolved-hint.error {
  color: var(--danger, #ef4444);
}

.diff-tag {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--primary);
  color: #fff;
  font-weight: 600;
}

.rec-apply-card {
  background: var(--surface-plain);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 14px;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-strong);
}

.checkbox-label input[type="checkbox"] {
  cursor: pointer;
  width: 16px;
  height: 16px;
  accent-color: var(--primary);
}

.rec-reason-wrap {
  margin-top: 8px;
  padding-left: 24px;
}

.btn-rec-active {
  background: color-mix(in srgb, var(--danger) 10%, transparent) !important;
color: var(--danger-text) !important;
  border-color: #fca5a5 !important;
}

.form-row-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.form-select {
  width: 100%;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid #cbd5e1;
  font-size: 14px;
  outline: none;
  background-color: var(--surface-plain);
color: light-dark(#0f172a, #d5dae2);
  transition: border-color 0.2s;
  box-sizing: border-box;
}

.form-select:focus {
  border-color: var(--primary, #3b82f6);
}

.back-column-btn.secondary {
  margin-left: 12px;
  background: var(--surface-plain);
  border: 1px solid #e2e8f0;
}

.back-column-btn.secondary:hover {
  background: var(--surface-plain);
  border-color: #cbd5e1;
}

.article-title {
  font-size: 28px;
  font-weight: 800;
color: light-dark(#0f172a, #d5dae2);
  margin: 0 0 16px;
  line-height: 1.35;
}

.article-meta-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
}

.author-block {
  display: flex;
  align-items: center;
  gap: 10px;
}

.author-block img {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  object-fit: cover;
}

.author-text {
  display: flex;
  align-items: center;
  gap: 6px;
}

.author-name {
  font-size: 14px;
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

.meta-right {
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 13px;
  color: var(--text-sub);
}

.meta-tag {
  display: flex;
  align-items: center;
  gap: 6px;
}

.action-btns {
  display: flex;
  gap: 8px;
}

.btn-sm {
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid #cbd5e1;
  background: var(--surface-plain);
  color: var(--text-strong);
  font-size: 12px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.btn-sm:hover {
  background: var(--bg-subtle);
}

.btn-sm.danger:hover {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  color: #ef4444;
  border-color: #fca5a5;
}

/* 正文渲染 */
.article-body {
  font-size: 15px;
  line-height: 1.8;
  color: var(--text-strong);
  min-height: 200px;
}

.article-footer {
  margin-top: 40px;
  padding-top: 20px;
  border-top: 1px solid #f1f5f9;
  display: flex;
  justify-content: flex-start;
}

.back-column-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 18px;
  border-radius: 8px;
  background: var(--bg-subtle);
  color: var(--text-sub);
  text-decoration: none;
  font-size: 13px;
  font-weight: 500;
  transition: all 0.2s;
}

.back-column-btn:hover {
  background: #e2e8f0;
  color: var(--text-strong);
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
  min-height: 260px;
  max-height: 400px;
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

.btn-primary {
  background: var(--primary, #3b82f6);
  color: #fff;
}

.btn-secondary {
  background: var(--bg-subtle);
  color: var(--text-sub);
}

.meta-comment-tag {
  cursor: pointer;
  transition: color 0.2s;
}
.meta-comment-tag:hover {
  color: var(--primary, #3b82f6);
}

/* 文章互动操作栏 */
.article-actions-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  margin: 36px 0 20px;
  padding: 16px 0;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 22px;
  border-radius: 9999px;
  border: 1px solid #e2e8f0;
  background: var(--surface-plain);
  color: var(--text-sub);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.action-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 10px rgba(0, 0, 0, 0.08);
}

.action-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
}

.action-btn .action-count {
  font-weight: 600;
  padding-left: 2px;
}

.btn-like:hover {
  background: color-mix(in srgb, var(--primary) 8%, transparent);
color: var(--primary-text);
  border-color: #bfdbfe;
}
.btn-like.is-liked {
  background: color-mix(in srgb, var(--primary) 8%, transparent);
color: var(--primary-text);
  border-color: #93c5fd;
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.15);
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
  box-shadow: 0 2px 8px rgba(161, 98, 7, 0.15);
}

.btn-comment-anchor:hover {
  background: var(--bg-subtle);
color: light-dark(#0f172a, #d5dae2);
  border-color: #cbd5e1;
}

/* 评论卡片 */
.comments-card {
  background: var(--surface-plain);
  border-radius: 14px;
  border: 1px solid rgba(226, 232, 240, 0.8);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04);
  padding: 32px 40px;
  margin-top: 24px;
}

.comments-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
  padding-bottom: 14px;
  border-bottom: 1px solid #f1f5f9;
}

.section-title {
  font-size: 18px;
  font-weight: 700;
color: light-dark(#0f172a, #d5dae2);
  margin: 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.count-pill {
  font-size: 12px;
  background: var(--bg-subtle);
  color: var(--text-sub);
  padding: 2px 10px;
  border-radius: 9999px;
  font-weight: 600;
}

.comment-loading,
.empty-comments {
  text-align: center;
  padding: 40px 20px;
  color: #94a3b8;
  font-size: 14px;
}

.empty-comments .empty-icon {
  font-size: 36px;
  margin-bottom: 10px;
  color: #cbd5e1;
}

.comment-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.comment-item {
  display: flex;
  gap: 16px;
  padding-bottom: 20px;
  border-bottom: 1px solid #f1f5f9;
}

.comment-item:last-child {
  border-bottom: none;
}

.comment-avatar img {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  object-fit: cover;
}

.comment-main {
  flex: 1;
  min-width: 0;
}

.comment-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.comment-author-info {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  flex-wrap: wrap;
}

.comment-author-name {
  font-weight: 600;
  text-decoration: none;
}

.badge-col-author {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: color-mix(in srgb, var(--primary) 8%, transparent);
color: var(--primary-text);
  font-weight: 600;
}

.comment-floor {
  font-size: 12px;
  color: #94a3b8;
  font-weight: 600;
}

.comment-time {
  font-size: 12px;
  color: #94a3b8;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.comment-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-comment-act {
  background: none;
  border: none;
  font-size: 12px;
  color: var(--text-sub);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border-radius: 4px;
  transition: all 0.2s;
}

.btn-comment-act:hover {
  background: var(--bg-subtle);
color: light-dark(#0f172a, #d5dae2);
}

.btn-comment-act.danger:hover {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  color: #ef4444;
}

.comment-body {
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-strong);
  word-break: break-word;
}

.comment-editor-section {
  margin-top: 32px;
  padding-top: 24px;
  border-top: 1px solid #e2e8f0;
}

.editor-section-title {
  font-size: 15px;
  font-weight: 600;
color: light-dark(#0f172a, #d5dae2);
  margin: 0 0 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.editor-tip {
  font-size: 12px;
  color: #94a3b8;
  font-weight: normal;
}

.editor-bottom-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
}

.editor-hint {
  font-size: 12px;
  color: #94a3b8;
}

.btn-action.btn-submit-comment {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 20px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border: none;
}

.comment-login-prompt {
  background: var(--surface-plain);
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  padding: 30px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: var(--text-sub);
  font-size: 14px;
}

.comment-login-prompt i {
  font-size: 28px;
  color: #94a3b8;
}

.btn-sm-link {
  padding: 6px 16px;
  font-size: 13px;
  text-decoration: none;
  border-radius: 6px;
}

/* 专栏投稿与移出操作样式 */
.btn-contribute-column {
  background: color-mix(in srgb, var(--success) 10%, transparent);
color: var(--success-text);
  border: 1px solid #bbf7d0;
  position: relative;
}
.btn-contribute-column:hover {
  background: color-mix(in srgb, var(--success) 10%, transparent);
  border-color: #86efac;
}

.btn-detach {
  background: color-mix(in srgb, var(--warning) 12%, transparent);
color: var(--warning-text);
  border: 1px solid #fde68a;
}
.btn-detach:hover {
  background: color-mix(in srgb, var(--warning) 12%, transparent);
}

.badge-dot {
  width: 6px;
  height: 6px;
  background: #ef4444;
  border-radius: 50%;
  display: inline-block;
  margin-left: 2px;
}

.form-help-tip {
  margin: 6px 0 0;
  font-size: 12px;
color: light-dark(#b45309, #fbbf24);
  line-height: 1.4;
}

.badge-current-col {
  font-size: 12px;
color: var(--primary-text);
  background: color-mix(in srgb, var(--primary) 8%, transparent);
  padding: 2px 8px;
  border-radius: 6px;
  font-weight: normal;
}

.modal-inclusion {
  max-width: 650px;
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
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 6px;
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

.badge-pill {
  background: rgba(0, 0, 0, 0.15);
  font-size: 11px;
  padding: 0 6px;
  border-radius: 8px;
}

.modal-body-inclusion {
  max-height: calc(85vh - 180px);
  overflow-y: auto;
  padding: 20px;
}

.modal-tip-desc {
  font-size: 13px;
  color: var(--text-sub);
  margin: 0 0 16px;
  line-height: 1.5;
}

.search-input-wrap {
  margin-bottom: 8px;
}

.column-select-list {
  max-height: 200px;
  overflow-y: auto;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: var(--surface-plain);
}

.column-list-empty {
  padding: 20px;
  text-align: center;
  font-size: 13px;
  color: #94a3b8;
}

.column-option-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-radius: 6px;
  background: var(--surface-plain);
  border: 1px solid #e2e8f0;
  cursor: pointer;
  transition: all 0.2s;
}

.column-option-card:hover:not(.disabled) {
  border-color: #3b82f6;
  background: color-mix(in srgb, var(--primary) 8%, transparent);
}

.column-option-card.selected {
  border-color: #3b82f6;
  background: color-mix(in srgb, var(--primary) 8%, transparent);
}

.column-option-card.disabled {
  opacity: 0.6;
  cursor: not-allowed;
  background: var(--surface-plain);
}

.col-opt-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.col-opt-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-strong);
}

.col-opt-meta {
  font-size: 11px;
  color: var(--text-sub);
  display: flex;
  gap: 12px;
}

.col-opt-badge {
  font-size: 11px;
  padding: 2px 6px;
  background: #e2e8f0;
  color: var(--text-sub);
  border-radius: 4px;
}

.col-opt-check {
  color: #3b82f6;
  font-size: 14px;
}

.apply-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.record-items-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.record-card {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px 14px;
  background: var(--surface-plain);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.record-card.status-pending {
  border-left: 4px solid #3b82f6;
}
.record-card.status-approved {
  border-left: 4px solid #10b981;
}
.record-card.status-rejected {
  border-left: 4px solid #ef4444;
}
.record-card.status-cancelled {
  border-left: 4px solid #94a3b8;
}

.record-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.record-col-link {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-strong);
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.record-col-link:hover {
  color: #3b82f6;
}

.record-time {
  font-size: 12px;
  color: #94a3b8;
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

.req-message-box,
.req-reply-box {
  font-size: 12px;
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

.record-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 4px;
}

.btn-cancel-request {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
color: var(--danger-text);
  border: 1px solid #fca5a5;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}
.btn-cancel-request:hover {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
}
</style>
