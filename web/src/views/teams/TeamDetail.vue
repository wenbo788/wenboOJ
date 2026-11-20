<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  teamsApi,
  type TeamDetailItem,
  type TeamMemberItem,
  type TeamJoinRequestItem,
  type TeamProblemItem,
  type TeamPostItem,
  type TeamPostDetailItem,
} from '@/api/teams'
import { difficultyColor } from '@/utils/difficulty'
import { userNameColor } from '@/utils/userColor'
import { getUserTagDisplay } from '@/utils/userTag'
import { fmtDateTime } from '@/utils/datetime'
import { renderRichText } from '@/utils/markdown'
import MarkdownSplitEditor from '@/components/MarkdownSplitEditor.vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const isLoggedIn = computed(() => authStore.isAuthenticated)

const teamId = computed(() => parseInt(route.params.id as string, 10))
const team = ref<TeamDetailItem | null>(null)
const loading = ref(true)
const error = ref('')
const acting = ref(false)
const actionMsg = ref('')

const TABS = ['概览', '题目', '讨论', '作业', '题单', '比赛', '成员', '文件']
const activeTab = ref('概览')

const load = async () => {
  if (!Number.isFinite(teamId.value)) {
    error.value = '无效的团队 ID'
    loading.value = false
    return
  }
  loading.value = true
  error.value = ''
  try {
    team.value = await teamsApi.get(teamId.value)
  } catch (err: any) {
    error.value = err.response?.data?.detail || err.message || '加载失败'
    team.value = null
  } finally {
    loading.value = false
  }
}
watch(teamId, async () => {
  await load()
  if (activeTab.value === '题目') loadTeamProblems()
  if (activeTab.value === '讨论' && team.value?.is_member) loadTeamPosts()
})
onMounted(async () => {
  await load()
  if (route.query.tab && typeof route.query.tab === 'string' && TABS.includes(route.query.tab)) {
    activeTab.value = route.query.tab
  } else if (route.query.post) {
    activeTab.value = '讨论'
  }
  if (activeTab.value === '题目') {
    loadTeamProblems()
  } else if (activeTab.value === '讨论') {
    if (team.value?.is_member) {
      await loadTeamPosts()
      if (route.query.post) {
        openPost(parseInt(route.query.post as string, 10))
      }
    }
  }
})

const letterAvatar = (name: string) => {
  const ch = (name || 'U').trim().charAt(0).toUpperCase() || 'U'
  return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Crect width='40' height='40' fill='%23e74c3c'/%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' dy='.3em' fill='white' font-size='16' font-family='Arial'%3E${encodeURIComponent(ch)}%3C/text%3E%3C/svg%3E`
}

const userColor = (u: TeamMemberItem['user']) => userNameColor(u)
const userTag = (u: TeamMemberItem['user']) => getUserTagDisplay(u)
const fmtDate = (iso: string | null) => (iso ? fmtDateTime(iso, '未知').slice(0, 10) : '未知')

const switchTab = (t: string) => {
  activeTab.value = t
  if (t === '题目' && teamProblems.value.length === 0 && !problemsLoading.value) {
    loadTeamProblems()
  } else if (t === '讨论' && team.value?.is_member && teamPosts.value.length === 0 && !postsLoading.value) {
    loadTeamPosts()
  }
  const q = { ...route.query }
  if (t !== '概览') {
    q.tab = t
  } else {
    delete q.tab
  }
  if (t !== '讨论') {
    delete q.post
    activePostId.value = null
    postDetail.value = null
  }
  router.replace({ query: q })
}

const roleText = (role: string) =>
  role === 'owner' ? '团队主' : role === 'admin' ? '管理员' : ''

const doAction = async (fn: () => Promise<unknown>, okMsg: string) => {
  acting.value = true
  actionMsg.value = ''
  try {
    await fn()
    actionMsg.value = okMsg
    await load()
  } catch (err: any) {
    actionMsg.value = err.response?.data?.detail || '操作失败'
  } finally {
    acting.value = false
  }
}

const joinTeam = () => doAction(() => teamsApi.join(teamId.value), '申请已提交，等待团队管理员审核')
const leaveTeam = () => {
  if (!confirm('确定退出该团队吗？')) return
  doAction(() => teamsApi.leave(teamId.value), '已退出')
}
const dissolveTeam = () => {
  if (!confirm('确定解散该团队吗？所有成员将被移除，此操作不可恢复。')) return
  doAction(async () => {
    await teamsApi.dissolve(teamId.value)
    router.push('/teams')
  }, '已解散')
}

const showManage = ref(false)
const manageTarget = ref<TeamMemberItem | null>(null)
const manageNote = ref('')
const manageAdmin = ref(false)
const manageSaving = ref(false)
const manageError = ref('')

const canManage = computed(() => !!team.value?.is_team_admin)

// ===== 团队概览编辑（团主 / 团队管理员；被封禁团队禁止编辑）=====
const editingOverview = ref(false)
const overviewForm = ref({ name: '', description: '' })
const overviewSaving = ref(false)
const overviewError = ref('')

const canEditOverview = computed(
  () => !!team.value?.is_team_admin && !team.value?.is_banned
)

const startEditOverview = () => {
  if (!canEditOverview.value || !team.value) return
  overviewForm.value = {
    name: team.value.name,
    description: team.value.description || '',
  }
  overviewError.value = ''
  editingOverview.value = true
}

const cancelEditOverview = () => {
  editingOverview.value = false
  overviewError.value = ''
}

const saveOverview = async () => {
  if (!team.value) return
  const name = overviewForm.value.name.trim()
  const description = overviewForm.value.description.trim()
  // 前端先做一轮校验，给出即时反馈（后端仍会独立校验）
  if (!name) {
    overviewError.value = '团队名称不能为空'
    return
  }
  if (name.length > 50) {
    overviewError.value = '团队名称过长（≤50 字）'
    return
  }
  if (description.length > 500) {
    overviewError.value = '团队简介过长（≤500 字）'
    return
  }
  overviewSaving.value = true
  overviewError.value = ''
  try {
    await teamsApi.update(team.value.id, { name, description })
    editingOverview.value = false
    await load()
  } catch (err: any) {
    overviewError.value = err.response?.data?.detail || '保存失败'
  } finally {
    overviewSaving.value = false
  }
}

const openManage = (m: TeamMemberItem) => {
  if (!canManage.value || m.role === 'owner') return
  manageTarget.value = m
  manageNote.value = m.note || ''
  manageAdmin.value = m.role === 'admin'
  manageError.value = ''
  showManage.value = true
}

const saveManage = async () => {
  if (!manageTarget.value || !team.value) return
  manageSaving.value = true
  manageError.value = ''
  try {
    const originalRole = manageTarget.value.role
    const newRole: 'member' | 'admin' = manageAdmin.value ? 'admin' : 'member'
    const payload: { role?: 'member' | 'admin'; note: string } = {
      // 清空备注要传空串：传 undefined 会被 JSON 丢弃，后端收不到就不会清空
      note: manageNote.value.trim(),
    }
    // 角色没改就不传 role，否则非团主只改备注也会被后端拒为「仅团队主可以设置团队管理员」
    if (newRole !== originalRole) {
      payload.role = newRole
    }
    await teamsApi.updateMember(team.value.id, manageTarget.value.user_id, payload)
    showManage.value = false
    await load()
  } catch (err: any) {
    manageError.value = err.response?.data?.detail || '保存失败'
  } finally {
    manageSaving.value = false
  }
}

const removeMember = async () => {
  if (!manageTarget.value || !team.value) return
  if (!confirm(`确定将 ${manageTarget.value.user.username} 移出团队吗？`)) return
  manageSaving.value = true
  try {
    await teamsApi.removeMember(team.value.id, manageTarget.value.user_id)
    showManage.value = false
    await load()
  } catch (err: any) {
    manageError.value = err.response?.data?.detail || '移除失败'
  } finally {
    manageSaving.value = false
  }
}

const transferTeam = async () => {
  if (!manageTarget.value || !team.value) return
  const name = manageTarget.value.user.username
  if (!confirm(`确定把团队「${team.value.name}」转让给 ${name} 吗？\n转让后你将变为普通成员，此操作不可撤销。`)) return
  manageSaving.value = true
  try {
    await teamsApi.transfer(team.value.id, manageTarget.value.user_id)
    showManage.value = false
    await load()
  } catch (err: any) {
    manageError.value = err.response?.data?.detail || '转让失败'
  } finally {
    manageSaving.value = false
  }
}

const teamProblems = ref<TeamProblemItem[]>([])
const problemsLoading = ref(false)

const loadTeamProblems = async () => {
  problemsLoading.value = true
  try {
    teamProblems.value = await teamsApi.problems(teamId.value)
  } catch {
    teamProblems.value = []
  } finally {
    problemsLoading.value = false
  }
}

const showRequests = ref(false)
const requestItems = ref<TeamJoinRequestItem[]>([])
const requestsLoading = ref(false)
const requestsError = ref('')
const processingReq = ref<number | null>(null)

const openRequests = async () => {
  showRequests.value = true
  requestsLoading.value = true
  requestsError.value = ''
  try {
    const data = await teamsApi.requests(teamId.value)
    requestItems.value = data.items
  } catch (err: any) {
    requestsError.value = err.response?.data?.detail || '加载失败'
  } finally {
    requestsLoading.value = false
  }
}

const handleRequest = async (userId: number, approve: boolean) => {
  processingReq.value = userId
  try {
    if (approve) {
      await teamsApi.approveRequest(teamId.value, userId)
    } else {
      await teamsApi.rejectRequest(teamId.value, userId)
    }
    requestItems.value = requestItems.value.filter(r => r.user_id !== userId)
    await load()
  } catch (err: any) {
    requestsError.value = err.response?.data?.detail || '操作失败'
  } finally {
    processingReq.value = null
  }
}

const teamPosts = ref<TeamPostItem[]>([])
const postsTotal = ref(0)
const postsPage = ref(0)
const postsLoading = ref(false)
const postsError = ref('')

const activePostId = ref<number | null>(null)
const postDetail = ref<TeamPostDetailItem | null>(null)
const postDetailLoading = ref(false)
const postDetailError = ref('')

const showCreatePostModal = ref(false)
const createPostForm = ref({ title: '', content: '' })
const submittingPost = ref(false)
const createPostError = ref('')

const showEditPostModal = ref(false)
const editPostForm = ref({ title: '', content: '' })
const submittingEdit = ref(false)
const editPostError = ref('')

const replyContent = ref('')
const submittingReply = ref(false)
const replyError = ref('')

const loadTeamPosts = async (page = 0) => {
  postsLoading.value = true
  postsError.value = ''
  try {
    const data = await teamsApi.posts(teamId.value, page, 20)
    teamPosts.value = data.items
    postsTotal.value = data.total
    postsPage.value = page
  } catch (err: any) {
    postsError.value = err.response?.data?.detail || '加载讨论失败'
    teamPosts.value = []
  } finally {
    postsLoading.value = false
  }
}

const openPost = async (postId: number) => {
  if (!team.value?.is_member) return
  activePostId.value = postId
  postDetailLoading.value = true
  postDetailError.value = ''
  replyContent.value = ''
  replyError.value = ''
  try {
    postDetail.value = await teamsApi.getPost(teamId.value, postId)
    router.replace({ query: { ...route.query, tab: '讨论', post: postId } })
  } catch (err: any) {
    postDetailError.value = err.response?.data?.detail || '加载讨论详情失败'
    postDetail.value = null
  } finally {
    postDetailLoading.value = false
  }
}

const closePost = () => {
  activePostId.value = null
  postDetail.value = null
  const q = { ...route.query }
  delete q.post
  router.replace({ query: q })
}

const openCreatePost = () => {
  createPostForm.value = { title: '', content: '' }
  createPostError.value = ''
  showCreatePostModal.value = true
}

const submitCreatePost = async () => {
  const t = createPostForm.value.title.trim()
  const c = createPostForm.value.content.trim()
  if (!t) {
    createPostError.value = '请输入讨论标题'
    return
  }
  if (!c) {
    createPostError.value = '请输入讨论内容'
    return
  }
  submittingPost.value = true
  createPostError.value = ''
  try {
    const created = await teamsApi.createPost(teamId.value, { title: t, content: c })
    showCreatePostModal.value = false
    await loadTeamPosts(0)
    openPost(created.id)
  } catch (err: any) {
    createPostError.value = err.response?.data?.detail || '发布失败'
  } finally {
    submittingPost.value = false
  }
}

const openEditPost = () => {
  if (!postDetail.value) return
  editPostForm.value = {
    title: postDetail.value.title,
    content: postDetail.value.content,
  }
  editPostError.value = ''
  showEditPostModal.value = true
}

const submitEditPost = async () => {
  if (!postDetail.value) return
  const t = editPostForm.value.title.trim()
  const c = editPostForm.value.content.trim()
  if (!t) {
    editPostError.value = '请输入讨论标题'
    return
  }
  if (!c) {
    editPostError.value = '请输入讨论内容'
    return
  }
  submittingEdit.value = true
  editPostError.value = ''
  try {
    const updated = await teamsApi.updatePost(teamId.value, postDetail.value.id, { title: t, content: c })
    postDetail.value.title = updated.title
    postDetail.value.content = updated.content
    postDetail.value.updated_at = updated.updated_at
    showEditPostModal.value = false
    const p = teamPosts.value.find(item => item.id === updated.id)
    if (p) {
      p.title = updated.title
      p.content = updated.content
      p.updated_at = updated.updated_at
    }
  } catch (err: any) {
    editPostError.value = err.response?.data?.detail || '保存失败'
  } finally {
    submittingEdit.value = false
  }
}

const deletePost = async (postId: number) => {
  if (!confirm('确定删除该讨论吗？所有回复也将一并删除。')) return
  try {
    await teamsApi.deletePost(teamId.value, postId)
    closePost()
    await loadTeamPosts(postsPage.value)
  } catch (err: any) {
    alert(err.response?.data?.detail || '删除失败')
  }
}

const togglePin = async (postId: number) => {
  try {
    const res = await teamsApi.togglePostPin(teamId.value, postId)
    if (postDetail.value && postDetail.value.id === postId) {
      postDetail.value.is_pinned = res.is_pinned
    }
    const p = teamPosts.value.find(item => item.id === postId)
    if (p) p.is_pinned = res.is_pinned
    await loadTeamPosts(postsPage.value)
  } catch (err: any) {
    alert(err.response?.data?.detail || '操作失败')
  }
}

const toggleLock = async (postId: number) => {
  try {
    const res = await teamsApi.togglePostLock(teamId.value, postId)
    if (postDetail.value && postDetail.value.id === postId) {
      postDetail.value.is_locked = res.is_locked
    }
    const p = teamPosts.value.find(item => item.id === postId)
    if (p) p.is_locked = res.is_locked
  } catch (err: any) {
    alert(err.response?.data?.detail || '操作失败')
  }
}

const submitReply = async () => {
  if (!postDetail.value) return
  const c = replyContent.value.trim()
  if (!c) {
    replyError.value = '请输入回复内容'
    return
  }
  submittingReply.value = true
  replyError.value = ''
  try {
    const comment = await teamsApi.addPostComment(teamId.value, postDetail.value.id, { content: c })
    postDetail.value.comments.push(comment)
    postDetail.value.reply_count++
    replyContent.value = ''
    const p = teamPosts.value.find(item => item.id === postDetail.value!.id)
    if (p) p.reply_count++
  } catch (err: any) {
    replyError.value = err.response?.data?.detail || '回复失败'
  } finally {
    submittingReply.value = false
  }
}

const deleteComment = async (commentId: number) => {
  if (!confirm('确定删除该回复吗？')) return
  try {
    await teamsApi.deletePostComment(teamId.value, postDetail.value!.id, commentId)
    postDetail.value!.comments = postDetail.value!.comments.filter(c => c.id !== commentId)
    postDetail.value!.reply_count--
    const p = teamPosts.value.find(item => item.id === postDetail.value!.id)
    if (p) p.reply_count--
  } catch (err: any) {
    alert(err.response?.data?.detail || '删除失败')
  }
}

const canEditCurrentPost = computed(() => {
  if (!postDetail.value || !authStore.user) return false
  return postDetail.value.author.user_id === authStore.user.id
})

const canDeleteCurrentPost = computed(() => {
  if (!postDetail.value || !authStore.user) return false
  return postDetail.value.author.user_id === authStore.user.id || !!team.value?.is_team_admin
})

const canDeleteComment = (commentAuthorId: number | null | undefined) => {
  if (!authStore.user || commentAuthorId == null) return false
  return commentAuthorId === authStore.user.id || !!team.value?.is_team_admin
}
</script>

<template>
  <div class="team-detail-page">
    <div class="team-detail-container">
      <div class="back-link">
        <a @click.prevent="router.push('/teams')" href="#">← 返回团队列表</a>
      </div>

      <div v-if="loading" class="empty">加载中...</div>
      <div v-else-if="error" class="empty">{{ error }}</div>

      <template v-else-if="team">
        <!-- 团队头卡 -->
        <div class="card head-card">
          <div class="title-row">
            <h1>{{ team.name }}</h1>
            <div class="team-stats">
              <span class="stat-label">队员人数</span>
              <span class="stat-label">创建时间</span>
              <span class="stat-value">{{ team.member_count }}</span>
              <span class="stat-value">{{ fmtDate(team.created_at) }}</span>
            </div>
          </div>
          <!-- 简介在「概览」tab 完整呈现，其他 tab 用这里做上下文提示 -->
          <div v-if="team.description && activeTab !== '概览'" class="team-desc">{{ team.description }}</div>
          <div class="tab-row">
            <div class="setting-nav">
              <span
                v-for="t in TABS"
                :key="t"
                class="nav-btn"
                :class="{ active: activeTab === t }"
                @click="switchTab(t)"
              >{{ t }}</span>
            </div>
            <div class="head-actions">
              <template v-if="isLoggedIn">
                <button
                  v-if="team.is_team_admin"
                  class="btn-secondary"
                  @click="openRequests"
                >入队申请（{{ team.pending_count }}）</button>
                <button v-if="team.is_owner" class="btn-danger" :disabled="acting" @click="dissolveTeam">解散团队</button>
                <button v-else-if="team.is_member" class="btn-secondary" :disabled="acting" @click="leaveTeam">退出团队</button>
                <button v-else-if="team.is_pending" class="btn-secondary" disabled>审核中…</button>
                <button v-else class="btn-primary" :disabled="acting || team.is_banned" @click="joinTeam">
                  {{ acting ? '处理中...' : (team.is_banned ? '团队已被封禁' : '申请加入') }}
                </button>
              </template>
              <router-link v-else class="btn-secondary" to="/login">登录后可申请</router-link>
            </div>
          </div>
        </div>

        <div v-if="actionMsg" class="action-msg">{{ actionMsg }}</div>

        <div v-if="team.is_banned" class="ban-banner">
          <i class="fa-solid fa-ban"></i>
          该团队已被管理员封禁，暂时无法发帖、加人、创建题目等操作。
        </div>

        <!-- 概览：团队简介 + 基础信息，团主/团队管理员可编辑 -->
        <div v-if="activeTab === '概览'" class="card body-card">
          <div class="section-title-row">
            <div class="section-title">团队概览</div>
            <div class="section-actions">
              <button
                v-if="canEditOverview && !editingOverview"
                type="button"
                class="btn-secondary btn-sm"
                @click="startEditOverview"
              >
                <i class="fa-solid fa-pen"></i> 编辑概览
              </button>
            </div>
          </div>

          <!-- 编辑态 -->
          <div v-if="editingOverview" class="overview-form">
            <label class="overview-field">
              <span class="overview-label">团队名称</span>
              <input
                v-model="overviewForm.name"
                class="overview-input"
                type="text"
                maxlength="50"
                placeholder="请输入团队名称"
              />
              <span class="overview-counter">{{ overviewForm.name.length }} / 50</span>
            </label>
            <label class="overview-field">
              <span class="overview-label">团队简介</span>
              <textarea
                v-model="overviewForm.description"
                class="overview-textarea"
                rows="6"
                maxlength="500"
                placeholder="介绍一下你的团队：目标、方向、招人要求等"
              ></textarea>
              <span class="overview-counter">{{ overviewForm.description.length }} / 500</span>
            </label>
            <div v-if="overviewError" class="overview-error">{{ overviewError }}</div>
            <div class="overview-actions">
              <button type="button" class="btn-primary" :disabled="overviewSaving" @click="saveOverview">
                {{ overviewSaving ? '保存中...' : '保存' }}
              </button>
              <button type="button" class="btn-secondary" :disabled="overviewSaving" @click="cancelEditOverview">
                取消
              </button>
            </div>
          </div>

          <!-- 展示态 -->
          <template v-else>
            <div v-if="team.description" class="overview-body">{{ team.description }}</div>
            <div v-else class="tc-empty">
              {{ canEditOverview ? '还没有团队简介，点击右上角「编辑概览」补充一下吧' : '该团队还没有填写简介' }}
            </div>
            <div class="overview-meta">
              <div class="meta-item">
                <span class="meta-label">团长</span>
                <span class="meta-value">{{ team.owner.username }}</span>
              </div>
              <div class="meta-item">
                <span class="meta-label">成员数</span>
                <span class="meta-value">{{ team.member_count }} 人</span>
              </div>
              <div class="meta-item">
                <span class="meta-label">创建时间</span>
                <span class="meta-value">{{ fmtDate(team.created_at) }}</span>
              </div>
              <div class="meta-item">
                <span class="meta-label">团队状态</span>
                <span class="meta-value" :class="{ 'is-banned': team.is_banned }">
                  {{ team.is_banned ? '已封禁' : '正常' }}
                </span>
              </div>
            </div>
          </template>
        </div>

        <!-- 成员：成员列表（管理员可点开管理） -->
        <div v-else-if="activeTab === '成员'" class="card body-card">
          <h4 class="section-title">团队成员 <span class="member-count">（{{ team.member_count }} 人）</span></h4>
          <div class="member-grid">
            <div
              v-for="m in team.members"
              :key="m.user_id"
              class="member-item"
              :class="{ manageable: canManage && m.role !== 'owner' }"
              @click="openManage(m)"
            >
              <div class="member-left">
                <img class="member-avatar" :src="m.user.avatar_url || letterAvatar(m.user.username)" alt="" />
                <span class="member-name">
                  <router-link :to="`/user/${m.user.user_number}`" class="username-link" :style="{ color: userColor(m.user) }">
                    {{ m.note ? `${m.note}（${m.user.username}）` : m.user.username }}
                  </router-link>
                  <span v-if="userTag(m.user)" class="user-tag" :style="{ background: userColor(m.user) }">{{ userTag(m.user) }}</span>
                </span>
              </div>
              <span v-if="m.role !== 'member'" class="role-tag" :class="m.role">{{ roleText(m.role) }}</span>
              <span v-else-if="canManage && m.role === 'member'" class="manage-hint">管理</span>
            </div>
          </div>
        </div>

        <div v-else-if="activeTab === '题目'" class="card body-card">
          <div class="prob-head">
            <h4 class="section-title">团队题目 <span class="member-count">（{{ teamProblems.length }} 道）</span></h4>
            <div class="prob-head-actions">
              <router-link to="/team/problems" class="view-all">查看全部团队题目 →</router-link>
              <button
                v-if="team.is_team_admin && !team.is_banned"
                class="btn-primary"
                @click="router.push(`/problems/new?team_id=${team.id}`)"
              ><i class="fa-solid fa-plus"></i> 创建题目</button>
            </div>
          </div>
          <div v-if="problemsLoading" class="empty small">加载中...</div>
          <div v-else-if="teamProblems.length === 0" class="empty small">暂无题目</div>
          <div v-else class="team-problem-list">
            <div
              v-for="p in teamProblems"
              :key="p.id"
              class="team-problem-item"
              @click="router.push(`/problem/${p.problem_number}`)"
            >
              <span class="prob-no">{{ p.problem_number }}</span>
              <span class="prob-title">{{ p.title }}</span>
              <span v-if="p.is_public" class="tp-badge pub">公开</span>
              <span v-else class="tp-badge priv">内部</span>
              <span class="prob-stats">{{ p.solved_count }} / {{ p.submit_count }}</span>
              <span class="diff-badge" :style="{ background: difficultyColor(p.difficulty) }">{{ p.difficulty }}</span>
            </div>
          </div>
        </div>

        <div v-else-if="activeTab === '讨论'" class="card body-card">
          <div v-if="!team.is_member" class="empty small">
            仅团队成员可见
          </div>
          <div v-else-if="activePostId !== null" class="discuss-detail-wrap">
            <div class="discuss-detail-nav">
              <a href="#" class="back-link-btn" @click.prevent="closePost">← 返回</a>
              <div v-if="postDetail" class="discuss-top-actions">
                <button
                  v-if="team.is_team_admin"
                  class="btn-secondary small"
                  @click="togglePin(postDetail.id)"
                >{{ postDetail.is_pinned ? '取消置顶' : '置顶' }}</button>
                <button
                  v-if="team.is_team_admin"
                  class="btn-secondary small"
                  @click="toggleLock(postDetail.id)"
                >{{ postDetail.is_locked ? '解锁' : '锁定' }}</button>
                <button
                  v-if="canEditCurrentPost"
                  class="btn-secondary small"
                  @click="openEditPost"
                >编辑</button>
                <button
                  v-if="canDeleteCurrentPost"
                  class="btn-danger small"
                  @click="deletePost(postDetail.id)"
                >删除</button>
              </div>
            </div>

            <div v-if="postDetailLoading" class="empty small">加载中...</div>
            <div v-else-if="postDetailError" class="form-error">{{ postDetailError }}</div>
            <div v-else-if="postDetail" class="post-detail-main">
              <div class="post-header-card">
                <div class="post-title-line">
                  <span v-if="postDetail.is_pinned" class="badge-pin">置顶</span>
                  <span v-if="postDetail.is_locked" class="badge-lock"><i class="fa-solid fa-lock"></i> 锁定</span>
                  <h2 class="post-title-text">{{ postDetail.title }}</h2>
                </div>
                <div class="post-author-row">
                  <img
                    :src="postDetail.author.avatar_url || letterAvatar(postDetail.author.username)"
                    class="detail-avatar"
                    alt=""
                  />
                  <router-link
                    :to="`/user/${postDetail.author.user_number}`"
                    class="author-username"
                    :style="{ color: userColor(postDetail.author) }"
                  >
                    {{ postDetail.author.username }}
                  </router-link>
                  <span v-if="userTag(postDetail.author)" class="user-tag" :style="{ background: userColor(postDetail.author) }">{{ userTag(postDetail.author) }}</span>
                  <span v-if="postDetail.author.user_id === team.owner_id" class="role-tag owner mini">团队主</span>
                  <span class="post-created-time">{{ fmtDateTime(postDetail.created_at) }}</span>
                </div>
              </div>

              <div class="post-body-render prose" v-html="renderRichText(postDetail.content)"></div>

              <div class="post-comments-section">
                <h4 class="comments-heading">
                  回复 <span class="member-count">（{{ postDetail.comments.length }}）</span>
                </h4>

                <div v-if="postDetail.comments.length === 0" class="empty small">
                  暂无回复
                </div>
                <div v-else class="comments-list">
                  <div
                    v-for="(c, cIdx) in postDetail.comments"
                    :key="c.id"
                    class="comment-row"
                  >
                    <div class="comment-head">
                      <div class="comment-left">
                        <img
                          :src="c.author.avatar_url || letterAvatar(c.author.username)"
                          class="comment-avatar"
                          alt=""
                        />
                        <router-link
                          :to="`/user/${c.author.user_number}`"
                          class="comment-author-name"
                          :style="{ color: userColor(c.author) }"
                        >
                          {{ c.author.username }}
                        </router-link>
                        <span v-if="userTag(c.author)" class="user-tag" :style="{ background: userColor(c.author) }">{{ userTag(c.author) }}</span>
                        <span v-if="c.author.user_id === team.owner_id" class="role-tag owner mini">团队主</span>
                        <span class="comment-floor">#{{ cIdx + 1 }}</span>
                        <span class="comment-time">{{ fmtDateTime(c.created_at) }}</span>
                      </div>
                      <div class="comment-right">
                        <button
                          v-if="canDeleteComment(c.author.user_id)"
                          class="btn-text-danger"
                          @click="deleteComment(c.id)"
                        >删除</button>
                      </div>
                    </div>
                    <div class="comment-body prose" v-html="renderRichText(c.content)"></div>
                  </div>
                </div>

                <div class="reply-box-wrap">
                  <div v-if="!team.is_member" class="lock-hint">
                    仅团队成员可回复
                  </div>
                  <div v-else-if="postDetail.is_locked && !team.is_team_admin" class="lock-hint">
                    <i class="fa-solid fa-lock"></i> 讨论已锁定
                  </div>
                  <div v-else class="reply-box">
                    <textarea
                      v-model="replyContent"
                      class="reply-textarea"
                      placeholder="写下你的回复..."
                      rows="4"
                    ></textarea>
                    <div v-if="replyError" class="form-error">{{ replyError }}</div>
                    <div class="reply-action-row">
                      <button
                        class="btn-primary"
                        :disabled="submittingReply || !replyContent.trim()"
                        @click="submitReply"
                      >
                        {{ submittingReply ? '提交中...' : '回复' }}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div v-else class="discuss-list-wrap">
            <div class="discuss-header">
              <h4 class="section-title">团队讨论 <span class="member-count">（{{ postsTotal }}）</span></h4>
              <div class="discuss-actions">
                <button
                  v-if="team.is_member && !team.is_banned"
                  class="btn-primary"
                  @click="openCreatePost"
                ><i class="fa-solid fa-plus"></i> 发起讨论</button>
              </div>
            </div>

            <div v-if="!team.is_member" class="empty small">
              仅团队成员可见
            </div>
            <div v-else-if="postsLoading" class="empty small">加载中...</div>
            <div v-else-if="postsError" class="form-error">{{ postsError }}</div>
            <div v-else-if="teamPosts.length === 0" class="empty small">
              暂无讨论
            </div>
            <div v-else class="team-posts-table">
              <div
                v-for="p in teamPosts"
                :key="p.id"
                class="team-post-card"
                @click="openPost(p.id)"
              >
                <div class="post-card-left">
                  <div class="post-card-title-row">
                    <span v-if="p.is_pinned" class="badge-pin">置顶</span>
                    <span v-if="p.is_locked" class="badge-lock"><i class="fa-solid fa-lock"></i> 锁定</span>
                    <span class="post-card-title">{{ p.title }}</span>
                  </div>
                  <div class="post-card-meta">
                    <img
                      :src="p.author.avatar_url || letterAvatar(p.author.username)"
                      class="card-avatar"
                      alt=""
                    />
                    <span class="card-author" :style="{ color: userColor(p.author) }">{{ p.author.username }}</span>
                    <span v-if="userTag(p.author)" class="user-tag" :style="{ background: userColor(p.author) }">{{ userTag(p.author) }}</span>
                    <span class="meta-dot">·</span>
                    <span class="card-date">{{ fmtDate(p.created_at) }}</span>
                  </div>
                </div>
                <div class="post-card-right">
                  <span class="reply-pill">
                    <i class="fa-regular fa-comment-dots"></i> {{ p.reply_count }}
                  </span>
                </div>
              </div>

              <div v-if="postsTotal > 20" class="pagination-bar">
                <button
                  class="btn-secondary small"
                  :disabled="postsPage === 0 || postsLoading"
                  @click="loadTeamPosts(postsPage - 1)"
                >上一页</button>
                <span class="page-info">第 {{ postsPage + 1 }} / {{ Math.ceil(postsTotal / 20) }} 页</span>
                <button
                  class="btn-secondary small"
                  :disabled="(postsPage + 1) * 20 >= postsTotal || postsLoading"
                  @click="loadTeamPosts(postsPage + 1)"
                >下一页</button>
              </div>
            </div>
          </div>
        </div>

        <div v-else class="card body-card">
          <div class="empty">「{{ activeTab }}」功能开发中，敬请期待</div>
        </div>

        <!-- 入队申请审核弹窗 -->
        <div v-if="showRequests" class="modal-overlay" @click.self="showRequests = false">
          <div class="modal-box">
            <div class="modal-header">
              <h3>入队申请（{{ requestItems.length }}）</h3>
              <button class="modal-close" @click="showRequests = false"><i class="fa-solid fa-xmark"></i></button>
            </div>
            <div v-if="requestsLoading" class="empty small">加载中...</div>
            <div v-else-if="requestsError" class="form-error">{{ requestsError }}</div>
            <div v-else-if="requestItems.length === 0" class="empty small">暂无待审核申请</div>
            <div v-else class="request-list">
              <div v-for="r in requestItems" :key="r.user_id" class="request-item">
                <div class="member-left">
                  <img class="member-avatar" :src="r.user.avatar_url || letterAvatar(r.user.username)" alt="" />
                  <router-link :to="`/user/${r.user.user_number}`" class="username-link" :style="{ color: userColor(r.user) }">
                    {{ r.user.username }}
                  </router-link>
                </div>
                <div class="request-actions">
                  <button class="btn-primary small" :disabled="processingReq === r.user_id" @click="handleRequest(r.user_id, true)">通过</button>
                  <button class="btn-secondary small" :disabled="processingReq === r.user_id" @click="handleRequest(r.user_id, false)">拒绝</button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 管理成员弹窗 -->
        <div v-if="showManage" class="modal-overlay" @click.self="showManage = false">
          <div class="modal-box">
            <div class="modal-header">
              <h3>成员信息</h3>
              <button class="modal-close" @click="showManage = false"><i class="fa-solid fa-xmark"></i></button>
            </div>
            <div class="modal-body" v-if="manageTarget">
              <div class="field-row">
                <span class="field-label">成员</span>
                <div class="field-value">
                  <router-link :to="`/user/${manageTarget.user.user_number}`" :style="{ color: userColor(manageTarget.user), fontWeight: 600 }">
                    {{ manageTarget.user.username }}
                  </router-link>
                </div>
              </div>
              <div class="field-row">
                <span class="field-label">备注名</span>
                <div class="field-value">
                  <input v-model="manageNote" class="form-input" maxlength="50" placeholder="团队内显示的备注名" />
                </div>
              </div>
              <div class="field-row">
                <span class="field-label">权限</span>
                <div class="field-value">
                  <label class="checkbox-label">
                    <input v-model="manageAdmin" type="checkbox" :disabled="!team.is_owner" />
                    团队管理员 <span class="hint">（可管理团队成员，仅团队主可设置）</span>
                  </label>
                </div>
              </div>
              <div v-if="manageError" class="form-error">{{ manageError }}</div>
            </div>
            <div class="modal-footer three">
              <button class="btn-danger-outline" :disabled="manageSaving" @click="removeMember">移出团队</button>
              <button
                v-if="team?.is_owner"
                class="btn-danger-outline"
                :disabled="manageSaving"
                @click="transferTeam"
              >转让团队</button>
              <span class="spacer"></span>
              <button class="btn-secondary" @click="showManage = false">取消</button>
              <button class="btn-primary" :disabled="manageSaving" @click="saveManage">
                {{ manageSaving ? '保存中...' : '保存' }}
              </button>
            </div>
          </div>
        </div>

        <div v-if="showCreatePostModal" class="modal-overlay" @click.self="showCreatePostModal = false">
          <div class="modal-box modal-box-large">
            <div class="modal-header">
              <h3>发起讨论</h3>
              <button class="modal-close" @click="showCreatePostModal = false"><i class="fa-solid fa-xmark"></i></button>
            </div>
            <div class="modal-body">
              <div class="form-group">
                <label class="form-label">标题 <span class="required">*</span></label>
                <input
                  v-model="createPostForm.title"
                  class="form-input"
                  placeholder="标题"
                  maxlength="100"
                />
              </div>
              <div class="form-group">
                <label class="form-label">内容 <span class="required">*</span></label>
                <MarkdownSplitEditor
                  v-model="createPostForm.content"
                  height="300px"
                  placeholder="内容"
                />
              </div>
              <div v-if="createPostError" class="form-error">{{ createPostError }}</div>
            </div>
            <div class="modal-footer">
              <span class="spacer"></span>
              <button class="btn-secondary" @click="showCreatePostModal = false">取消</button>
              <button class="btn-primary" :disabled="submittingPost" @click="submitCreatePost">
                {{ submittingPost ? '发布中...' : '发布' }}
              </button>
            </div>
          </div>
        </div>

        <div v-if="showEditPostModal" class="modal-overlay" @click.self="showEditPostModal = false">
          <div class="modal-box modal-box-large">
            <div class="modal-header">
              <h3>编辑讨论</h3>
              <button class="modal-close" @click="showEditPostModal = false"><i class="fa-solid fa-xmark"></i></button>
            </div>
            <div class="modal-body">
              <div class="form-group">
                <label class="form-label">标题 <span class="required">*</span></label>
                <input
                  v-model="editPostForm.title"
                  class="form-input"
                  placeholder="标题"
                  maxlength="100"
                />
              </div>
              <div class="form-group">
                <label class="form-label">内容 <span class="required">*</span></label>
                <MarkdownSplitEditor
                  v-model="editPostForm.content"
                  height="300px"
                  placeholder="内容"
                />
              </div>
              <div v-if="editPostError" class="form-error">{{ editPostError }}</div>
            </div>
            <div class="modal-footer">
              <span class="spacer"></span>
              <button class="btn-secondary" @click="showEditPostModal = false">取消</button>
              <button class="btn-primary" :disabled="submittingEdit" @click="submitEditPost">
                {{ submittingEdit ? '保存中...' : '保存' }}
              </button>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.team-detail-page { min-height: calc(100vh - 60px); }
.team-detail-container { max-width: 1000px; margin: 0 auto; padding: 20px; }
.back-link { margin-bottom: 12px; }
.back-link a { color: var(--primary); font-size: 14px; cursor: pointer; text-decoration: none; }
.back-link a:hover { text-decoration: underline; }

.card { padding: 20px 26px; margin-bottom: 16px; }
.title-row { display: flex; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
.title-row h1 { color: var(--primary); font-size: 24px; margin: 0; }
.team-desc { margin-top: 8px; color: var(--text-sub); font-size: 14px; white-space: pre-wrap; }

.team-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 2px 20px; }
.stat-label { color: var(--text-strong); font-size: 14px; text-align: center; }
.stat-value { color: var(--text-strong); font-weight: 600; font-size: 14px; text-align: center; }

.tab-row { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-top: 6px; border-bottom: 1px solid #f0f2f5; padding-bottom: 0; }
.setting-nav { display: flex; gap: 28px; flex-wrap: wrap; }
.nav-btn { position: relative; padding: 12px 0; font-size: 15px; color: var(--text-sub); cursor: pointer; }
.nav-btn::after { content: ''; position: absolute; bottom: 0; left: 50%; width: 0; height: 4px; background: #d0d7de; transform: translateX(-50%); transition: all .2s; }
.nav-btn:hover::after { width: calc(100% + 16px); left: -8px; transform: translateX(0); }
.nav-btn.active { color: var(--primary); }
.nav-btn.active::after { background: var(--primary); width: 100%; left: 0; transform: translateX(0); }
.head-actions { display: flex; gap: 10px; flex-shrink: 0; }

.action-msg { background: color-mix(in srgb, var(--success) 10%, transparent);color: var(--success-text); padding: 10px 16px; border-radius: 8px; margin-bottom: 16px; font-size: 14px; }
.ban-banner { display: flex; align-items: center; gap: 8px; background: color-mix(in srgb, var(--danger) 10%, transparent); color: var(--danger); padding: 10px 16px; border-radius: 8px; margin-bottom: 16px; font-size: 14px; }

.section-title { margin: 4px 0 14px; color: var(--text-strong); }
.section-title-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.section-title-row .section-title { margin: 0; }
.section-actions { display: flex; gap: 8px; align-items: center; }
.btn-sm { padding: 5px 12px; font-size: 13px; }

/* 团队概览 */
.tc-empty { color: var(--text-sub); font-size: 14px; padding: 18px 0; }
.overview-body { color: var(--text-strong); font-size: 14px; line-height: 1.8; white-space: pre-wrap; overflow-wrap: anywhere; }
.overview-meta { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-top: 18px; padding-top: 16px; border-top: 1px solid #f0f2f5; }
.meta-item { display: flex; flex-direction: column; gap: 4px; }
.meta-label { color: var(--text-sub); font-size: 12px; }
.meta-value { color: var(--text-strong); font-size: 14px; font-weight: 600; }
.meta-value.is-banned { color: var(--danger); }
.overview-form { display: flex; flex-direction: column; gap: 14px; }
.overview-field { display: flex; flex-direction: column; gap: 6px; position: relative; }
.overview-label { color: var(--text-strong); font-size: 13px; font-weight: 600; }
.overview-input, .overview-textarea { background: var(--surface-strong); border: var(--border-width) solid var(--border-color); border-radius: 8px; padding: 9px 12px; color: var(--text-strong); font-size: 14px; font-family: inherit; outline: none; }
.overview-input:focus, .overview-textarea:focus { border-color: var(--primary); }
.overview-textarea { resize: vertical; line-height: 1.7; min-height: 120px; }
.overview-counter { align-self: flex-end; color: var(--text-sub); font-size: 12px; }
.overview-error { color: var(--danger); font-size: 13px; }
.overview-actions { display: flex; gap: 10px; }

.member-count { color: var(--text-sub); font-weight: 400; font-size: 13px; }
.member-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.member-item { background: var(--surface-strong); border: var(--border-width) solid var(--border-color); border-radius: 8px; padding: 10px 14px; display: flex; align-items: center; justify-content: space-between; min-height: 48px; gap: 8px; }
.member-item.manageable { cursor: pointer; }
.member-item.manageable:hover { border-color: rgba(231, 76, 60, 0.4); background: rgba(231, 76, 60, 0.06); }
.member-left { display: flex; align-items: center; gap: 10px; overflow: hidden; min-width: 0; }
.member-avatar { width: 32px; height: 32px; border-radius: 50%; object-fit: cover; flex-shrink: 0; }
.member-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.username-link { font-weight: 700; font-size: 14px; text-decoration: none; }
.username-link:hover { text-decoration: underline; }
.user-tag { display: inline-block; border-radius: 2px; padding: 2px 8px; color: #fff; font-size: 11px; font-weight: 600; margin-left: 4px; vertical-align: middle; }
.role-tag { flex-shrink: 0; font-size: 12px; padding: 2px 14px; border-radius: 20px; font-weight: 600; }
.role-tag.owner { color: #fff; background: #ffc116; }
.role-tag.admin {color: var(--primary-text); background: color-mix(in srgb, var(--danger) 10%, transparent); }
.manage-hint { flex-shrink: 0; font-size: 12px; color: #c2c9d4; }

.empty { text-align: center; color: var(--text-sub); padding: 40px 0; }

.btn-primary { background: var(--primary); color: #fff; border: none; border-radius: 8px; padding: 8px 20px; font-weight: 600; cursor: pointer; font-size: 14px; }
.btn-primary:hover { background: var(--primary-hover); }
.btn-secondary { background: var(--bg-subtle); color: var(--text-strong); border: none; border-radius: 8px; padding: 8px 20px; font-weight: 600; cursor: pointer; font-size: 14px; text-decoration: none; display: inline-block; }
.btn-danger { background: transparent; color: var(--primary); border: 1px solid var(--primary); border-radius: 8px; padding: 8px 20px; font-weight: 600; cursor: pointer; font-size: 14px; }
.btn-danger-outline { background: none; color: var(--primary); border: none; font-size: 13px; cursor: pointer; }
button:disabled { opacity: .6; cursor: not-allowed; }

.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 999; display: flex; justify-content: center; align-items: center; }
.modal-box { background: var(--surface-plain); border-radius: 14px; width: 90%; max-width: 440px; padding: 24px 28px; }
.modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.modal-header h3 { margin: 0; font-size: 18px; color: var(--text-strong); }
.modal-close { background: none; border: none; font-size: 20px; color: #8e9aaf; cursor: pointer; }
.field-row { display: flex; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid #f0f2f5; }
.field-label { width: 64px; flex-shrink: 0; font-size: 14px; color: var(--text-strong); font-weight: 600; }
.field-value { flex: 1; font-size: 14px; }
.form-input { width: 100%; box-sizing: border-box; padding: 7px 10px; border: 1px solid #dce0e6; border-radius: 8px; font-size: 14px; outline: none; }
.form-input:focus { border-color: var(--primary); }
.checkbox-label { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.checkbox-label input { accent-color: var(--primary); }
.hint { font-size: 12px; color: #8e9aaf; }
.form-error { color: var(--primary); font-size: 13px; margin-top: 10px; }
.modal-footer { display: flex; align-items: center; gap: 12px; margin-top: 16px; padding-top: 14px; border-top: 1px solid #f0f2f5; }
.modal-footer.three .spacer { flex: 1; }

.prob-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.prob-head-actions { display: flex; align-items: center; gap: 14px; }
.view-all { color: var(--primary); font-size: 13px; text-decoration: none; }
.view-all:hover { text-decoration: underline; }
.team-problem-list { display: flex; flex-direction: column; gap: 8px; }
.team-problem-item { display: flex; align-items: center; gap: 12px; background: var(--surface-strong); border: var(--border-width) solid var(--border-color); border-radius: 8px; padding: 10px 14px; cursor: pointer; transition: border-color .15s, background .15s; }
.team-problem-item:hover { border-color: rgba(231, 76, 60, 0.4); background: rgba(231, 76, 60, 0.06); }
.prob-no { font-weight: 700; color: #e74c3c; font-size: 14px; min-width: 48px; }
.prob-title { flex: 1; color: var(--text-strong); font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.prob-stats { color: #8e9aaf; font-size: 13px; }
.diff-badge { color: #fff; font-size: 12px; padding: 2px 10px; border-radius: 4px; font-weight: 600; }
.tp-badge { font-size: 11px; padding: 1px 6px; border-radius: 4px; font-weight: 600; flex-shrink: 0; }
.tp-badge.pub { background: color-mix(in srgb, var(--primary) 12%, transparent); color: var(--primary); }
.tp-badge.priv { background: var(--bg-subtle, #f1f5f9); color: var(--text-sub, #64748b); }

.request-list { max-height: 320px; overflow-y: auto; }
.request-item { display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #f0f2f5; }
.request-item:last-child { border-bottom: none; }
.request-actions { display: flex; gap: 8px; }
.btn-primary.small, .btn-secondary.small, .btn-danger.small { padding: 5px 14px; font-size: 13px; }
.empty.small { padding: 16px 0; font-size: 13px; }

.modal-box.modal-box-large {
  max-width: 760px;
}

.form-group {
  margin-bottom: 16px;
}

.form-label {
  display: block;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-strong);
  margin-bottom: 6px;
}

.form-label .required {
  color: var(--primary);
}

.discuss-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}

.discuss-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.team-posts-table {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.team-post-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--surface-strong);
  border: var(--border-width) solid var(--border-color);
  border-radius: 8px;
  padding: 12px 16px;
  cursor: pointer;
  transition: border-color .15s, background .15s;
}

.team-post-card:hover {
  border-color: rgba(231, 76, 60, 0.4);
  background: rgba(231, 76, 60, 0.06);
}

.post-card-left {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  flex: 1;
}

.post-card-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.post-card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.post-card-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #8e9aaf;
}

.card-avatar {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  object-fit: cover;
}

.card-author {
  font-weight: 600;
  font-size: 13px;
}

.meta-dot {
  color: #c2c9d4;
}

.post-card-right {
  margin-left: 12px;
  flex-shrink: 0;
}

.reply-pill {
  font-size: 13px;
  color: var(--text-sub);
  background: rgba(0, 0, 0, 0.04);
  padding: 4px 10px;
  border-radius: 12px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.badge-pin {
  background: #e74c3c;
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  line-height: 1.2;
  flex-shrink: 0;
}

.badge-lock {
  background: #6c7a8e;
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  line-height: 1.2;
  flex-shrink: 0;
}

.role-tag.mini {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 10px;
  line-height: 1.3;
}

.pagination-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid #f0f2f5;
}

.page-info {
  font-size: 13px;
  color: #8e9aaf;
}

.discuss-detail-wrap {
  display: flex;
  flex-direction: column;
}

.discuss-detail-nav {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f0f2f5;
}

.back-link-btn {
  color: var(--primary);
  text-decoration: none;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.back-link-btn:hover {
  text-decoration: underline;
}

.discuss-top-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.post-header-card {
  margin-bottom: 16px;
}

.post-title-line {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.post-title-text {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-strong);
  margin: 0;
}

.post-author-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #8e9aaf;
}

.detail-avatar {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  object-fit: cover;
}

.author-username {
  font-weight: 600;
  font-size: 14px;
  text-decoration: none;
}

.author-username:hover {
  text-decoration: underline;
}

.post-created-time {
  margin-left: 4px;
}

.post-body-render {
  padding: 16px 0;
  border-bottom: 1px solid #f0f2f5;
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-strong);
  min-height: 60px;
}

.post-body-render :deep(a) {
  color: var(--primary);
}

.post-comments-section {
  margin-top: 20px;
}

.comments-heading {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-strong);
  margin-bottom: 14px;
}

.comments-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 24px;
}

.comment-row {
  background: var(--surface-strong);
  border: var(--border-width) solid var(--border-color);
  border-radius: 8px;
  padding: 12px 16px;
}

.comment-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.comment-left {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  flex-wrap: wrap;
}

.comment-avatar {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  object-fit: cover;
}

.comment-author-name {
  font-weight: 600;
  font-size: 13px;
  text-decoration: none;
}

.comment-author-name:hover {
  text-decoration: underline;
}

.comment-floor {
  color: #8e9aaf;
  font-size: 12px;
  font-weight: 600;
}

.comment-time {
  color: #8e9aaf;
  font-size: 12px;
}

.btn-text-danger {
  background: none;
  border: none;
  color: #e74c3c;
  font-size: 12px;
  cursor: pointer;
  padding: 0;
}

.btn-text-danger:hover {
  text-decoration: underline;
}

.comment-body {
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-strong);
}

.comment-body :deep(a) {
  color: var(--primary);
}

.reply-box-wrap {
  margin-top: 20px;
  border-top: 1px solid #f0f2f5;
  padding-top: 16px;
}

.lock-hint {
  background: rgba(0, 0, 0, 0.03);
  color: #8e9aaf;
  padding: 12px;
  border-radius: 8px;
  text-align: center;
  font-size: 14px;
}

.reply-box-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-strong);
  margin: 0 0 8px 0;
}

.reply-textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 10px 12px;
  border: 1px solid #dce0e6;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  font-family: inherit;
  resize: vertical;
}

.reply-textarea:focus {
  border-color: var(--primary);
}

.reply-action-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 10px;
}

@media (max-width: 640px) {
  .member-grid { grid-template-columns: 1fr; }
  .team-stats { grid-template-columns: 1fr; text-align: left; }
  .title-row h1 { font-size: 20px; }
}

@media (max-width: 600px) {
  .team-detail-container {
    padding: 16px 0;
  }

  .card {
    padding: 14px;
  }
}
</style>
