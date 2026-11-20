<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { problemsApi } from '@/api/problems'
import {
  articlesApi,
  columnsApi,
  COLUMN_CATEGORIES,
  type ColumnArticleItem,
  type ColumnItem
} from '@/api/columns'
import { userNameColor } from '@/utils/userColor'
import { fmtDateTime } from '@/utils/datetime'
import { renderRichText as renderMarkdown } from '@/utils/markdown'
import MarkdownSplitEditor from '@/components/MarkdownSplitEditor.vue'
import Swal from 'sweetalert2'

import { isSuperAdmin } from '@/utils/permissions'
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const isLoggedIn = computed(() => authStore.isAuthenticated)
const currentUser = computed(() => authStore.currentUser)
const isAdmin = computed(() => isSuperAdmin(currentUser.value))
const canManageProblems = computed(() => {
  const u = currentUser.value
  return !!u && (isAdmin.value || u.can_manage_problems === true)
})

// 视图模式：'articles' 精选文章 | 'columns' 专栏合集
const activeTab = ref<'articles' | 'columns'>('articles')

// 筛选与分页
const selectedCategory = ref<string>('all')
const adminShowPending = ref<boolean>(false) // 管理员审核视图：查看未推荐内容
const keyword = ref<string>('')
const page = ref<number>(1)
const pageSize = ref<number>(12)
const total = ref<number>(0)
const loading = ref<boolean>(false)

// 数据列表
const articles = ref<ColumnArticleItem[]>([])
const columns = ref<ColumnItem[]>([])

// 用户专栏列表（供发文时选择）
const myColumns = ref<ColumnItem[]>([])

// 弹窗状态：写文章
const showArticleModal = ref(false)
const articleSubmitting = ref(false)
const articleForm = ref({
  title: '',
  summary: '',
  category: '算法理论',
  cover_url: '',
  column_id: null as number | null,
  problem_code: '',
  apply_recommend: false,
  recommend_reason: '',
  content: ''
})

// 题号校验状态
const resolvingProblem = ref(false)
const resolvedProblem = ref<{ id: number; title: string; difficulty?: string } | null>(null)
const problemResolveError = ref('')

const checkProblemCode = async () => {
  const code = articleForm.value.problem_code.trim()
  if (!code) {
    resolvedProblem.value = null
    problemResolveError.value = ''
    return
  }
  resolvingProblem.value = true
  problemResolveError.value = ''
  try {
    const p = await problemsApi.getByCode(code)
    if (articleForm.value.category === '题解' && p.allow_solution_submission === false && !canManageProblems.value) {
      resolvedProblem.value = null
      problemResolveError.value = '因为题目做法足够充分或题目过于简单已关闭题解通道。'
      return
    }
    resolvedProblem.value = {
      id: p.id,
      title: p.title,
      difficulty: p.difficulty,
    }
  } catch {
    resolvedProblem.value = null
    problemResolveError.value = '未找到该题号对应的题目，请核对题号'
  } finally {
    resolvingProblem.value = false
  }
}

watch(
  () => articleForm.value.category,
  (newCat) => {
    if (newCat === '题解' && articleForm.value.problem_code.trim()) {
      checkProblemCode()
    } else if (newCat !== '题解' && problemResolveError.value.includes('已关闭题解通道')) {
      problemResolveError.value = ''
    }
  }
)

// 弹窗状态：新建专栏
const showColumnModal = ref(false)
const columnSubmitting = ref(false)
const columnForm = ref({
  title: '',
  description: '',
  cover_url: '',
  category: '算法理论'
})

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

// 加载文章列表（文章广场仅展示全站推荐文章，管理员可切换审核未推荐）
const loadArticles = async () => {
  loading.value = true
  try {
    const params: any = {
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value.trim() || undefined
    }
    if (selectedCategory.value !== 'all') {
      params.category = selectedCategory.value
    }
    if (isAdmin.value && adminShowPending.value) {
      params.is_recommended = false
    } else {
      params.is_recommended = true
    }

    const res = await articlesApi.list(params)
    articles.value = res.items
    total.value = res.total
  } catch (err: any) {
    console.error('加载文章列表失败:', err)
  } finally {
    loading.value = false
  }
}

// 加载专栏列表（文章广场仅展示全站推荐专栏，管理员可切换审核未推荐）
const loadColumns = async () => {
  loading.value = true
  try {
    const params: any = {
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value.trim() || undefined
    }
    if (selectedCategory.value !== 'all') {
      params.category = selectedCategory.value
    }
    if (isAdmin.value && adminShowPending.value) {
      params.is_recommended = false
    } else {
      params.is_recommended = true
    }

    const res = await columnsApi.list(params)
    columns.value = res.items
    total.value = res.total
  } catch (err: any) {
    console.error('加载专栏失败:', err)
  } finally {
    loading.value = false
  }
}

// 统一数据加载调度
const refreshData = () => {
  if (activeTab.value === 'articles') {
    loadArticles()
  } else {
    loadColumns()
  }
}

const switchTab = (tab: 'articles' | 'columns') => {
  if (activeTab.value === tab) return
  activeTab.value = tab
  page.value = 1
  adminShowPending.value = false
  refreshData()
}

const toggleAdminPending = () => {
  adminShowPending.value = !adminShowPending.value
  page.value = 1
  refreshData()
}

const setCategory = (cat: string) => {
  selectedCategory.value = cat
  page.value = 1
  refreshData()
}

const handleSearch = () => {
  page.value = 1
  refreshData()
}

const changePage = (p: number) => {
  page.value = p
  refreshData()
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

// 打开写文章弹窗
const openArticleModal = async (preset?: {
  category?: string
  problem_code?: string
  apply_recommend?: boolean
}) => {
  if (!isLoggedIn.value) {
    router.push('/login')
    return
  }
  try {
    myColumns.value = await columnsApi.getMyColumns()
  } catch {
    myColumns.value = []
  }
  resolvedProblem.value = null
  problemResolveError.value = ''
  const cat = preset?.category || '算法理论'
  articleForm.value = {
    title: '',
    summary: '',
    category: cat,
    cover_url: '',
    column_id: null,
    problem_code: preset?.problem_code || '',
    apply_recommend: preset?.apply_recommend ?? (cat === '题解'),
    recommend_reason: '',
    content: ''
  }
  if (articleForm.value.problem_code) {
    checkProblemCode()
  }
  showArticleModal.value = true
}

// 提交写文章（asDraft=true 时保存为草稿，不发布、不申请推荐）
const handleCreateArticle = async (asDraft = false) => {
  if (!articleForm.value.title.trim()) {
    Swal.fire({ icon: 'warning', title: '请输入文章标题', timer: 1500, showConfirmButton: false })
    return
  }
  if (!articleForm.value.content.trim()) {
    Swal.fire({ icon: 'warning', title: '请输入文章正文', timer: 1500, showConfirmButton: false })
    return
  }

  // 题解分类必须指定题号（草稿放宽，留到发布时再校验）
  if (!asDraft && articleForm.value.category === '题解') {
    if (!articleForm.value.problem_code.trim()) {
      Swal.fire({ icon: 'warning', title: '请填写关联题号', text: '发布题解分类文章必须指定关联题号（如 P1001、T1 或 U1001）' })
      return
    }
    if (problemResolveError.value) {
      Swal.fire({ icon: 'warning', title: '题目校验未通过', text: problemResolveError.value })
      return
    }
  }

  articleSubmitting.value = true
  try {
    const colId = articleForm.value.column_id ? Number(articleForm.value.column_id) : null
    const res = await articlesApi.create({
      title: articleForm.value.title.trim(),
      content: articleForm.value.content,
      summary: articleForm.value.summary.trim() || undefined,
      category: articleForm.value.category,
      cover_url: articleForm.value.cover_url.trim() || undefined,
      column_id: colId,
      problem_code: articleForm.value.problem_code.trim() || undefined,
      // 草稿不申请推荐（未发布的内容无从审核）
      apply_recommend: asDraft ? false : articleForm.value.apply_recommend,
      recommend_reason: asDraft ? undefined : (articleForm.value.recommend_reason.trim() || undefined),
      is_draft: asDraft || undefined,
    })
    if (asDraft) {
      Swal.fire({ icon: 'success', title: '草稿已保存', text: '可在「我的草稿」里继续编辑并发布', timer: 1600, showConfirmButton: false })
      showArticleModal.value = false
      // 只有草稿列表正开着才需要刷新，否则是白跑一次请求（还会盖掉上一条提示）
      if (showDraftModal.value) await loadDrafts()
    } else {
      Swal.fire({ icon: 'success', title: '文章发布成功', timer: 1200, showConfirmButton: false })
      showArticleModal.value = false
      router.push(`/article/${res.id}`)
    }
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: asDraft ? '保存草稿失败' : '发布失败', text: err.response?.data?.detail || err.message })
  } finally {
    articleSubmitting.value = false
  }
}

// ==================== 我的草稿 ====================
const showDraftModal = ref(false)
const drafts = ref<ColumnArticleItem[]>([])
const draftsLoading = ref(false)
const draftActing = ref<number | null>(null)

const loadDrafts = async () => {
  draftsLoading.value = true
  try {
    drafts.value = await articlesApi.listDrafts()
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '草稿加载失败', text: err.response?.data?.detail || err.message })
  } finally {
    draftsLoading.value = false
  }
}

const openDraftModal = async () => {
  // 与 openArticleModal 对齐：入口按钮虽有 v-if 保护，函数自身也要挡住未登录
  if (!isLoggedIn.value) {
    router.push('/login')
    return
  }
  showDraftModal.value = true
  await loadDrafts()
}

/** 继续编辑：草稿仅作者可见，详情页对作者正常展示，编辑后仍是草稿 */
const editDraft = (d: ColumnArticleItem) => {
  showDraftModal.value = false
  router.push(`/article/${d.id}`)
}

const publishDraft = async (d: ColumnArticleItem) => {
  draftActing.value = d.id
  try {
    await articlesApi.publishDraft(d.id)
    Swal.fire({ icon: 'success', title: '已发布', timer: 1200, showConfirmButton: false })
    await loadDrafts()
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '发布失败', text: err.response?.data?.detail || err.message })
  } finally {
    draftActing.value = null
  }
}

const removeDraft = async (d: ColumnArticleItem) => {
  const result = await Swal.fire({
    title: '确定删除这条草稿吗？',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonText: '确认删除',
    cancelButtonText: '取消',
    confirmButtonColor: 'var(--primary)',
    cancelButtonColor: '#909399',
  })
  if (!result.isConfirmed) return
  draftActing.value = d.id
  try {
    await articlesApi.delete(d.id)
    // 与发布草稿一样给个反馈，否则只看列表刷新容易以为没生效
    Swal.fire({ icon: 'success', title: '草稿已删除', timer: 1200, showConfirmButton: false })
    await loadDrafts()
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '删除失败', text: err.response?.data?.detail || err.message })
  } finally {
    draftActing.value = null
  }
}

const fmtDraftTime = (s?: string) => {
  if (!s) return ''
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

// 打开新建专栏弹窗
const openColumnModal = () => {
  if (!isLoggedIn.value) {
    router.push('/login')
    return
  }
  columnForm.value = {
    title: '',
    description: '',
    cover_url: '',
    category: '算法理论'
  }
  showColumnModal.value = true
}

// 提交新建专栏
const handleCreateColumn = async () => {
  if (!columnForm.value.title.trim()) {
    Swal.fire({ icon: 'warning', title: '请输入专栏名称', timer: 1500, showConfirmButton: false })
    return
  }
  columnSubmitting.value = true
  try {
    const created = await columnsApi.create({
      title: columnForm.value.title.trim(),
      description: columnForm.value.description.trim() || undefined,
      cover_url: columnForm.value.cover_url.trim() || undefined,
      category: columnForm.value.category
    })
    Swal.fire({ icon: 'success', title: '专栏创建成功', timer: 1500, showConfirmButton: false })
    showColumnModal.value = false
    router.push(`/column/${created.id}`)
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '创建失败', text: err.response?.data?.detail || err.message })
  } finally {
    columnSubmitting.value = false
  }
}

onMounted(() => {
  refreshData()
  if (route.query.write === 'solution' || route.query.write === 'article') {
    const cat = route.query.write === 'solution' ? '题解' : '算法理论'
    const prob = route.query.problem ? String(route.query.problem) : ''
    openArticleModal({
      category: cat,
      problem_code: prob,
      apply_recommend: cat === '题解',
    })
  }
})
</script>

<template>
  <div class="plaza-container">
    <!-- 顶部 Banner -->
    <div class="plaza-header-card">
      <div class="header-left">
        <h1 class="plaza-title"><i class="fa-solid fa-newspaper"></i> 文章广场</h1>
        <p class="plaza-sub">汇聚全站技术博客、专题合集与解题心得，自由交流，启发思考</p>
      </div>
      <div class="header-actions">
        <button class="btn-primary" @click="openArticleModal()">
          <i class="fa-solid fa-pen-nib"></i> 写文章
        </button>
        <button v-if="isLoggedIn" class="btn-secondary" @click="openDraftModal()">
          <i class="fa-regular fa-file-lines"></i> 我的草稿
        </button>
        <button class="btn-secondary" @click="openColumnModal">
          <i class="fa-solid fa-book-bookmark"></i> 新建专栏
        </button>
      </div>
    </div>

    <!-- 顶部视图切换 Tab -->
    <div class="view-switch-tabs">
      <button
        class="switch-btn"
        :class="{ active: activeTab === 'articles' }"
        @click="switchTab('articles')"
      >
        <i class="fa-solid fa-file-lines"></i> 精选文章
      </button>
      <button
        class="switch-btn"
        :class="{ active: activeTab === 'columns' }"
        @click="switchTab('columns')"
      >
        <i class="fa-solid fa-layer-group"></i> 精选专栏
      </button>
    </div>

    <!-- 筛选工具栏 -->
    <div class="filter-card">
      <div class="category-tabs">
        <button
          class="cat-tab"
          :class="{ active: selectedCategory === 'all' }"
          @click="setCategory('all')"
        >
          全部
        </button>
        <button
          v-for="cat in COLUMN_CATEGORIES"
          :key="cat"
          class="cat-tab"
          :class="{ active: selectedCategory === cat }"
          @click="setCategory(cat)"
        >
          {{ cat }}
        </button>
      </div>

      <div class="filter-right">
        <!-- 管理员可切换查看待审核未推荐（文章/专栏） -->
        <button
          v-if="isAdmin"
          class="btn-admin-filter"
          :class="{ active: adminShowPending }"
          @click="toggleAdminPending"
          :title="adminShowPending ? `点击返回精选推荐${activeTab === 'articles' ? '文章' : '专栏'}` : `点击查看未推荐${activeTab === 'articles' ? '文章' : '专栏'}以进行审核推荐`"
        >
          <i class="fa-solid" :class="adminShowPending ? 'fa-eye' : 'fa-shield-halved'"></i>
          {{ adminShowPending ? (activeTab === 'articles' ? '待审核未推荐文章' : '待审核未推荐专栏') : (activeTab === 'articles' ? '审核未推荐文章' : '审核未推荐专栏') }}
        </button>

        <!-- 普通用户提示 -->
        <span v-else class="badge-only-rec">
          <i class="fa-solid fa-fire"></i> 仅展示全站精选{{ activeTab === 'articles' ? '文章' : '专栏' }}
        </span>

        <div class="search-box">
          <input
            v-model="keyword"
            type="text"
            :placeholder="activeTab === 'articles' ? '搜索精选文章标题或摘要...' : '搜索精选专栏名称或描述...'"
            @keyup.enter="handleSearch"
          />
          <button class="search-btn" @click="handleSearch">
            <i class="fa-solid fa-magnifying-glass"></i>
          </button>
        </div>
      </div>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="plaza-loading">
      <i class="fa-solid fa-spinner fa-spin"></i> 加载中...
    </div>

    <!-- 视图 1：文章信息流列表 -->
    <div v-else-if="activeTab === 'articles'">
      <div v-if="articles.length === 0" class="plaza-empty">
        <div class="empty-icon"><i class="fa-solid fa-file-lines"></i></div>
        <p class="empty-text">
          {{ adminShowPending ? '暂无待审核的未推荐文章' : '暂无精选推荐文章' }}
        </p>
        <button v-if="isLoggedIn" class="btn-create-sm" @click="openArticleModal()">
          立即写一篇
        </button>
      </div>

      <div v-else class="article-list-stream">
        <div
          v-for="art in articles"
          :key="art.id"
          class="article-stream-card"
          @click="router.push(`/article/${art.id}`)"
        >
          <div class="article-main-content">
            <div class="article-top-row">
              <span v-if="art.is_recommended" class="badge-rec">
                <i class="fa-solid fa-fire"></i> 全站精选
              </span>
              <span class="badge-cat" :class="getCategoryClass(art.category)">
                {{ art.category || '算法理论' }}
              </span>
              <span
                v-if="art.problem_code || art.problem_id"
                class="badge-problem-link"
                @click.stop="router.push(`/problem/${art.problem_code || (art.problem_id ? 'P' + (1000 + art.problem_id) : '')}/solutions`)"
                title="查看该题全部题解"
              >
                <i class="fa-solid fa-lightbulb"></i> {{ art.problem_code || (art.problem_id ? 'P' + (1000 + art.problem_id) : '') }} {{ art.problem_title ? ('· ' + art.problem_title) : '' }}
              </span>
              <span
                v-if="art.column_id"
                class="badge-column-link"
                @click.stop="router.push(`/column/${art.column_id}`)"
                title="点击前往所属专栏"
              >
                <i class="fa-solid fa-book-bookmark"></i> {{ art.column_title || '合集' }}
              </span>
            </div>

            <h3 class="article-card-title">{{ art.title }}</h3>

            <p class="article-card-summary">
              {{ art.summary || '作者暂未提供简介，点击阅读全文了解详情...' }}
            </p>

            <div class="article-card-footer">
              <div class="author-block" v-if="art.author">
                <img
                  :src="art.author.avatar_url || letterAvatar(art.author.username)"
                  class="author-avatar"
                />
                <span
                  class="author-name"
                  :style="{ color: userNameColor(art.author) }"
                >
                  {{ art.author.username }}
                </span>
                <span
                  v-if="art.author.user_tag"
                  class="user-tag"
                  :style="{ backgroundColor: art.author.username_color || userNameColor(art.author) }"
                >
                  {{ art.author.user_tag }}
                </span>
              </div>

              <div class="article-meta-info">
                <span><i class="fa-regular fa-clock"></i> {{ fmtDateTime(art.created_at) }}</span>
                <span><i class="fa-regular fa-eye"></i> {{ art.view_count }}</span>
                <span title="点赞数"><i class="fa-regular fa-thumbs-up"></i> {{ art.like_count || 0 }}</span>
                <span title="收藏数"><i class="fa-regular fa-bookmark"></i> {{ art.star_count || 0 }}</span>
                <span title="评论数"><i class="fa-regular fa-comment-dots"></i> {{ art.comment_count || 0 }}</span>
              </div>
            </div>
          </div>

          <div
            v-if="art.cover_url"
            class="article-cover-thumb"
            :style="{ backgroundImage: `url('${art.cover_url}')` }"
          ></div>
        </div>
      </div>
    </div>

    <!-- 视图 2：精选专栏网格 -->
    <div v-else-if="activeTab === 'columns'">
      <div v-if="columns.length === 0" class="plaza-empty">
        <div class="empty-icon"><i class="fa-solid fa-book-open"></i></div>
        <p class="empty-text">
          {{ adminShowPending ? '暂无待审核的未推荐专栏' : '暂无精选推荐专栏' }}
        </p>
        <button v-if="isLoggedIn" class="btn-create-sm" @click="openColumnModal">
          立即新建专栏
        </button>
      </div>

      <div v-else class="column-grid">
        <div
          v-for="col in columns"
          :key="col.id"
          class="column-card"
          @click="router.push(`/column/${col.id}`)"
        >
          <div v-if="col.cover_url" class="card-cover" :style="{ backgroundImage: `url('${col.cover_url}')` }"></div>
          <div class="card-body">
            <div class="card-top">
              <h3 class="col-title" :title="col.title">{{ col.title }}</h3>
              <div class="card-badges">
                <span class="badge-cat" :class="getCategoryClass(col.category)">
                  {{ col.category || '算法理论' }}
                </span>
                <span v-if="col.is_recommended" class="badge-rec">
                  <i class="fa-solid fa-fire"></i> 精选
                </span>
              </div>
            </div>

            <p class="col-desc">{{ col.description || '作者很懒，还没有填写专栏简介' }}</p>

            <div class="card-footer">
              <div class="author-info">
                <img
                  :src="col.author?.avatar_url || letterAvatar(col.author?.username || 'U')"
                  class="author-avatar"
                />
                <span
                  class="author-name"
                  :style="{ color: col.author?.username_color || userNameColor(col.author) }"
                >
                  {{ col.author?.username || '未知作者' }}
                </span>
              </div>
              <div class="col-meta">
                <span><i class="fa-solid fa-file-lines"></i> {{ col.article_count }} 篇</span>
                <span v-if="col.like_count" title="点赞数"><i class="fa-regular fa-thumbs-up"></i> {{ col.like_count }}</span>
                <span v-if="col.star_count" title="收藏数"><i class="fa-regular fa-bookmark"></i> {{ col.star_count }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 分页 -->
    <div v-if="total > pageSize" class="plaza-pagination">
      <button :disabled="page <= 1" class="page-btn" @click="changePage(page - 1)">上一页</button>
      <span class="page-info">第 {{ page }} 页 / 共 {{ Math.ceil(total / pageSize) }} 页</span>
      <button :disabled="page * pageSize >= total" class="page-btn" @click="changePage(page + 1)">下一页</button>
    </div>

    <!-- 弹窗：我的草稿 -->
    <div v-if="showDraftModal" class="modal-backdrop" @click.self="showDraftModal = false">
      <div class="modal-card modal-drafts">
        <div class="modal-header">
          <h3><i class="fa-regular fa-file-lines"></i> 我的草稿</h3>
          <button class="close-btn" @click="showDraftModal = false">
            <i class="fa-solid fa-xmark"></i>
          </button>
        </div>
        <div class="modal-body">
          <div v-if="draftsLoading" class="drafts-empty">加载中...</div>
          <div v-else-if="drafts.length === 0" class="drafts-empty">
            还没有草稿。写文章时点「保存草稿」就会出现在这里。
          </div>
          <div v-else class="draft-list">
            <div v-for="d in drafts" :key="d.id" class="draft-row">
              <div class="draft-main">
                <div class="draft-title">{{ d.title }}</div>
                <div class="draft-meta">
                  <span class="draft-tag">草稿</span>
                  <span v-if="d.category">{{ d.category }}</span>
                  <span>更新于 {{ fmtDraftTime(d.updated_at) }}</span>
                </div>
              </div>
              <div class="draft-actions">
                <button class="draft-btn" :disabled="draftActing === d.id" @click="editDraft(d)">继续编辑</button>
                <button class="draft-btn primary" :disabled="draftActing === d.id" @click="publishDraft(d)">发布</button>
                <button class="draft-btn danger" :disabled="draftActing === d.id" @click="removeDraft(d)">删除</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 弹窗：写文章 -->
    <div v-if="showArticleModal" class="modal-backdrop" @click.self="showArticleModal = false">
      <div class="modal-card modal-article-editor">
        <div class="modal-header">
          <h3><i class="fa-solid fa-pen-nib"></i> 发布文章</h3>
          <button class="close-btn" @click="showArticleModal = false">
            <i class="fa-solid fa-xmark"></i>
          </button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>文章标题 <span class="req">*</span></label>
            <input
              v-model="articleForm.title"
              type="text"
              class="form-input"
              placeholder="请输入标题（如：浅谈动态规划优化技巧）"
              maxlength="150"
            />
          </div>

          <div class="form-row-2">
            <div class="form-group">
              <label>文章分类 <span class="req">*</span></label>
              <select v-model="articleForm.category" class="form-select">
                <option v-for="cat in COLUMN_CATEGORIES" :key="cat" :value="cat">
                  {{ cat }}
                </option>
              </select>
            </div>
            <div class="form-group">
              <label>收录于专栏（可选）</label>
              <select v-model="articleForm.column_id" class="form-select">
                <option :value="null">独立文章（不归属任何专栏）</option>
                <option v-for="col in myColumns" :key="col.id" :value="col.id">
                  {{ col.title }}
                </option>
              </select>
            </div>
          </div>

          <!-- 题解分类专属：关联题目 -->
          <div v-if="articleForm.category === '题解'" class="solution-link-section">
            <div class="form-group">
              <label>关联题号 <span class="req">*</span></label>
              <div class="problem-input-wrap">
                <input
                  v-model="articleForm.problem_code"
                  type="text"
                  class="form-input"
                  placeholder="请输入题号（如 P1001、T1、U1001）"
                  @blur="checkProblemCode"
                  @keydown.enter.prevent="checkProblemCode"
                />
                <button type="button" class="btn-check-prob" :disabled="resolvingProblem" @click="checkProblemCode">
                  <i v-if="resolvingProblem" class="fa-solid fa-spinner fa-spin"></i>
                  <i v-else class="fa-solid fa-magnifying-glass"></i> 校验题目
                </button>
              </div>
              <div v-if="resolvedProblem" class="prob-resolved-hint success">
                <i class="fa-solid fa-circle-check"></i>
                已关联题目：<b>{{ resolvedProblem.title }}</b>
                <span v-if="resolvedProblem.difficulty" class="diff-tag">{{ resolvedProblem.difficulty }}</span>
              </div>
              <div v-else-if="problemResolveError" class="prob-resolved-hint error">
                <i class="fa-solid fa-circle-exclamation"></i>
                {{ problemResolveError }}
              </div>
              <div v-else class="form-hint">
                题解审核通过后将同时展示在全站文章广场与对应题目的「题解」专区中。
              </div>
            </div>
          </div>

          <!-- 全站推荐申请 -->
          <div class="form-group rec-apply-card">
            <label class="checkbox-label">
              <input type="checkbox" v-model="articleForm.apply_recommend" />
              <span><b>申请全站推荐</b>（审核通过后展示在文章广场精选流及题目题解区，并奖励 20 点贡献值）</span>
            </label>
            <div v-if="articleForm.apply_recommend" class="rec-reason-wrap">
              <input
                v-model="articleForm.recommend_reason"
                type="text"
                class="form-input form-input-sm"
                placeholder="申请理由或文章特色（选填，如：包含严谨推导与复杂度分析）"
                maxlength="200"
              />
            </div>
          </div>

          <div class="form-group">
            <label>封面图片 URL（选填）</label>
            <input
              v-model="articleForm.cover_url"
              type="url"
              class="form-input"
              placeholder="https://example.com/cover.png"
            />
          </div>

          <div class="form-group">
            <label>文章摘要（选填）</label>
            <input
              v-model="articleForm.summary"
              type="text"
              class="form-input"
              placeholder="简单介绍文章主要内容，显示在列表中"
              maxlength="500"
            />
          </div>

          <div class="form-group">
            <label class="field-label-bold">
              文章正文 (支持 Markdown / LaTeX 公式，实时分栏渲染) <span class="req">*</span>
            </label>
            <MarkdownSplitEditor
              v-model="articleForm.content"
              height="480px"
              placeholder="请使用 Markdown 编写文章正文，支持 KaTeX 数学公式（如 $O(n \log n)$ 与 $$\sum_{i=1}^n i$$）及代码高亮..."
            />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn-cancel" @click="showArticleModal = false">取消</button>
          <button
            class="btn-draft"
            :disabled="articleSubmitting"
            title="保存为草稿：仅自己可见，稍后可继续编辑并发布"
            @click="handleCreateArticle(true)"
          >保存草稿</button>
          <button class="btn-confirm" :disabled="articleSubmitting" @click="handleCreateArticle(false)">
            {{ articleSubmitting ? '发布中...' : '立即发布' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 弹窗：新建专栏 -->
    <div v-if="showColumnModal" class="modal-backdrop" @click.self="showColumnModal = false">
      <div class="modal-card">
        <div class="modal-header">
          <h3><i class="fa-solid fa-book-bookmark"></i> 新建专栏合集</h3>
          <button class="close-btn" @click="showColumnModal = false">
            <i class="fa-solid fa-xmark"></i>
          </button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>专栏名称 <span class="req">*</span></label>
            <input
              v-model="columnForm.title"
              type="text"
              class="form-input"
              placeholder="请输入专栏名称（如：从零开始学后缀自动机）"
              maxlength="100"
            />
          </div>
          <div class="form-group">
            <label>专栏分类 <span class="req">*</span></label>
            <div class="category-select-group">
              <label
                v-for="cat in COLUMN_CATEGORIES"
                :key="cat"
                class="cat-radio-label"
                :class="{ active: columnForm.category === cat }"
              >
                <input
                  v-model="columnForm.category"
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
            <textarea
              v-model="columnForm.description"
              class="form-textarea"
              rows="3"
              placeholder="介绍专栏内容、学习目标或面向人群..."
            ></textarea>
          </div>
          <div class="form-group">
            <label>封面图片 URL（选填）</label>
            <input
              v-model="columnForm.cover_url"
              type="url"
              class="form-input"
              placeholder="https://example.com/cover.png"
            />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn-cancel" @click="showColumnModal = false">取消</button>
          <button class="btn-confirm" :disabled="columnSubmitting" @click="handleCreateColumn">
            {{ columnSubmitting ? '创建中...' : '立即创建' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.plaza-container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px 16px 60px;
}

.plaza-header-card {
  background: var(--surface);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 24px 28px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: var(--shadow-card);
  margin-bottom: 20px;
}

.plaza-title {
  margin: 0 0 6px 0;
  font-size: 24px;
  font-weight: 700;
  color: var(--text-main);
  display: flex;
  align-items: center;
  gap: 10px;
}

.plaza-title i {
  color: var(--primary);
}

.plaza-sub {
  margin: 0;
  font-size: 14px;
  color: var(--text-muted);
}

.header-actions {
  display: flex;
  gap: 12px;
}

.btn-primary {
  background: var(--primary);
  color: #fff;
  border: none;
  padding: 9px 18px;
  border-radius: var(--radius-md);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  transition: all 0.2s;
}

.btn-primary:hover {
  filter: brightness(1.08);
  transform: translateY(-1px);
}

.btn-secondary {
  background: var(--surface);
  color: var(--text-main);
  border: 1px solid var(--border-color);
  padding: 9px 18px;
  border-radius: var(--radius-md);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  transition: all 0.2s;
}

.btn-secondary:hover {
  background: var(--surface-hover, #f1f5f9);
  border-color: var(--primary);
  color: var(--primary);
}

/* 顶部视图切换 Tab */
.view-switch-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  border-bottom: 2px solid var(--border-color);
  padding-bottom: 2px;
}

.switch-btn {
  background: transparent;
  border: none;
  padding: 8px 18px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border-radius: 8px 8px 0 0;
  position: relative;
  transition: all 0.2s;
}

.switch-btn:hover {
  color: var(--primary);
}

.switch-btn.active {
  color: var(--primary);
}

.switch-btn.active::after {
  content: '';
  position: absolute;
  bottom: -4px;
  left: 0;
  right: 0;
  height: 3px;
  background: var(--primary);
  border-radius: 2px;
}

/* 筛选卡片 */
.filter-card {
  background: var(--surface);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 12px 18px;
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
  box-shadow: var(--shadow-sm);
}

.category-tabs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.cat-tab {
  border: 1px solid var(--border-color);
  background: var(--surface);
  color: var(--text-muted);
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.cat-tab:hover {
  color: var(--primary);
  border-color: var(--primary);
}

.cat-tab.active {
  background: var(--primary);
  color: #fff;
  border-color: var(--primary);
}

.filter-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.btn-recommend-filter {
  background: var(--surface);
  border: 1px solid var(--border-color);
  color: var(--text-muted);
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  transition: all 0.2s;
}

.btn-recommend-filter i {
  color: #ea580c;
}

.btn-recommend-filter.active {
  border-color: #f97316;
  background: color-mix(in srgb, var(--warning) 12%, transparent);
color: var(--warning-text);
}

.btn-admin-filter {
  background: var(--surface);
  border: 1px solid var(--border-color);
  color: var(--text-muted);
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s;
}

.btn-admin-filter:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.btn-admin-filter.active {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border-color: #fca5a5;
color: var(--danger-text);
  font-weight: 600;
}

.badge-only-rec {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 500;
color: var(--warning-text);
  background: color-mix(in srgb, var(--warning) 12%, transparent);
  border: 1px solid #ffedd5;
  padding: 5px 12px;
  border-radius: 20px;
}

.search-box {
  display: flex;
  align-items: center;
  border: 1px solid var(--border-color);
  border-radius: 20px;
  background: var(--surface);
  overflow: hidden;
  padding: 2px 4px 2px 12px;
}

.search-box input {
  border: none;
  background: transparent;
  outline: none;
  font-size: 13px;
  color: var(--text-main);
  width: 200px;
}

.search-btn {
  border: none;
  background: transparent;
  color: var(--text-muted);
  padding: 6px 8px;
  cursor: pointer;
  transition: color 0.2s;
}

.search-btn:hover {
  color: var(--primary);
}

/* 文章流列表 */
.article-list-stream {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.article-stream-card {
  background: var(--surface);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 20px 24px;
  display: flex;
  gap: 20px;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: var(--shadow-sm);
}

.article-stream-card:hover {
  transform: translateY(-2px);
  border-color: var(--primary);
  box-shadow: var(--shadow-card-hover);
}

.article-main-content {
  flex: 1;
  min-width: 0;
}

.article-top-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.badge-rec {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
color: var(--danger-text);
  border: 1px solid #fecaca;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.badge-cat {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 600;
}

.badge-column-link {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--bg-subtle);
  color: var(--text-sub);
  border: 1px solid #e2e8f0;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: all 0.2s;
}

.badge-column-link:hover {
  background: #e2e8f0;
  color: #0f172a;
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

.article-card-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-main);
  margin: 0 0 8px 0;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.article-card-summary {
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.6;
  margin: 0 0 14px 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.article-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--text-muted);
}

.author-block {
  display: flex;
  align-items: center;
  gap: 6px;
}

.author-avatar {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  object-fit: cover;
}

.author-name {
  font-weight: 600;
  font-size: 13px;
}

.user-tag {
  color: #fff;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 500;
}

.article-meta-info {
  display: flex;
  gap: 14px;
}

.article-cover-thumb {
  width: 140px;
  height: 95px;
  border-radius: var(--radius-sm, 6px);
  background-size: cover;
  background-position: center;
  flex-shrink: 0;
  border: 1px solid var(--border-color);
}

/* 专栏网格与卡片 */
.column-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 18px;
}

.column-card {
  background: var(--surface);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  overflow: hidden;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;
}

.column-card:hover {
  transform: translateY(-3px);
  border-color: var(--primary);
  box-shadow: var(--shadow-card-hover);
}

.card-cover {
  width: 100%;
  height: 120px;
  background-size: cover;
  background-position: center;
  border-bottom: 1px solid var(--border-color);
}

.card-body {
  padding: 16px;
  display: flex;
  flex-direction: column;
  flex: 1;
}

.card-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 8px;
}

.col-title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-main);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.card-badges {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

.col-desc {
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.5;
  margin: 0 0 16px 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 38px;
}

.card-footer {
  margin-top: auto;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 10px;
  border-top: 1px solid var(--border-color);
  font-size: 12px;
}

.author-info {
  display: flex;
  align-items: center;
  gap: 6px;
}

.col-meta {
  color: var(--text-muted);
  display: flex;
  gap: 10px;
}

/* 状态 */
.plaza-loading,
.plaza-empty {
  text-align: center;
  padding: 60px 20px;
  color: var(--text-muted);
}

.plaza-empty .empty-icon {
  font-size: 48px;
  color: #cbd5e1;
  margin-bottom: 12px;
}

.empty-text {
  font-size: 15px;
  margin-bottom: 16px;
}

.btn-create-sm {
  background: var(--primary);
  color: #fff;
  border: none;
  padding: 8px 18px;
  border-radius: var(--radius-md);
  cursor: pointer;
}

.plaza-pagination {
  margin-top: 30px;
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16px;
}

.page-btn {
  background: var(--surface);
  border: 1px solid var(--border-color);
  padding: 6px 16px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  color: var(--text-main);
  transition: all 0.2s;
}

.page-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.page-info {
  font-size: 13px;
  color: var(--text-muted);
}

/* 模态框 */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(4px);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
  padding: 16px;
}

.modal-card {
  background: var(--surface);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-lg);
  width: 90%;
  max-width: 520px;
  box-shadow: var(--shadow-lg);
  overflow: hidden;
  display: flex;
  flex-direction: column;
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
  color: var(--text-main);
  margin-bottom: 8px;
}

.modal-header {
  padding: 16px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--border-color);
}

.modal-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-main);
  display: flex;
  align-items: center;
  gap: 8px;
}

.close-btn {
  border: none;
  background: transparent;
  font-size: 18px;
  cursor: pointer;
  color: var(--text-muted);
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
  font-weight: 600;
  color: var(--text-main);
  margin-bottom: 6px;
}

.req {
  color: var(--primary);
}

.form-row-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.form-input,
.form-textarea,
.form-select {
  width: 100%;
  padding: 9px 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--surface);
  color: var(--text-main);
  font-size: 13px;
  outline: none;
  box-sizing: border-box;
  transition: border-color 0.2s;
}

.form-input:focus,
.form-textarea:focus,
.form-select:focus {
  border-color: var(--primary);
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

.code-editor {
  font-family: Menlo, Monaco, Consolas, 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.5;
  resize: vertical;
}

.markdown-preview {
  min-height: 220px;
  max-height: 380px;
  overflow-y: auto;
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--surface-plain);
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

.modal-footer {
  padding: 12px 20px;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  border-top: 1px solid var(--border-color);
}

.btn-cancel {
  border: 1px solid var(--border-color);
  background: transparent;
  padding: 7px 16px;
  border-radius: 6px;
  cursor: pointer;
  color: var(--text-muted);
}

.btn-confirm {
  background: var(--primary);
  color: #fff;
  border: none;
  padding: 7px 18px;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 600;
}

.btn-confirm:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 题目关联与题解样式 */
.badge-problem-link {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(245, 158, 11, 0.12);
  color: #b45309;
  border: 1px solid rgba(245, 158, 11, 0.28);
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  transition: all 0.18s ease;
}

.badge-problem-link:hover {
  background: rgba(245, 158, 11, 0.22);
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

.form-hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-sub);
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

.form-input-sm {
  padding: 6px 10px;
  font-size: 12px;
}

@media (max-width: 640px) {
  .form-row-2 {
    grid-template-columns: 1fr;
  }
  .article-stream-card {
    flex-direction: column-reverse;
    align-items: stretch;
  }
  .article-cover-thumb {
    width: 100%;
    height: 140px;
  }
}

/* ===== 我的草稿 ===== */
.modal-drafts {
  max-width: 680px;
}

/* 「保存草稿」按钮：与「取消」区分开（同一个 modal-footer 里三个按钮） */
.btn-draft {
  padding: 8px 16px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  background: transparent;
  color: var(--text-strong);
  font-size: 14px;
  cursor: pointer;
}

.btn-draft:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
}

.btn-draft:disabled {
  opacity: .5;
  cursor: not-allowed;
}

.drafts-empty {
  padding: 28px 8px;
  text-align: center;
  color: var(--text-sub);
  font-size: 14px;
}

.draft-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 60vh;
  overflow-y: auto;
}

.draft-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--bg-subtle);
}

.draft-main {
  min-width: 0;
}

.draft-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.draft-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-sub);
}

.draft-tag {
  color: var(--warning-text);
  background: color-mix(in srgb, var(--warning) 14%, transparent);
  border-radius: 4px;
  padding: 1px 6px;
  font-weight: 600;
}

.draft-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.draft-btn {
  font-size: 13px;
  padding: 5px 12px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  background: transparent;
  color: var(--text-strong);
  cursor: pointer;
}

.draft-btn:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
}

.draft-btn.primary {
  border-color: var(--primary);
  color: var(--primary);
}

.draft-btn.danger:hover:not(:disabled) {
  border-color: #f3c1bb;
  color: var(--danger-text);
}

.draft-btn:disabled {
  opacity: .5;
  cursor: not-allowed;
}
</style>
