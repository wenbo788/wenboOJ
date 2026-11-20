<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import apiClient from '@/api/client'
import Swal from 'sweetalert2'
import { userNameColor as userColor } from '@/utils/userColor'
import { getUserTagDisplay } from '@/utils/userTag'
import UserAvatarStatus from '@/components/UserAvatarStatus.vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const post = ref<any>(null)
const loading = ref(true)
const error = ref('')

const replyContent = ref('')
const replySubmitting = ref(false)
const replyEditor = ref<InstanceType<typeof MarkdownSplitEditor> | null>(null)
const replyBox = ref<HTMLElement | null>(null)

/**
 * 回复某条回复：只把 `@对方` 填进回复框，不做树状嵌套。
 * 服务端会从正文里解析 @ 并给被提及者发「提及」通知 ——
 * 被 @ 只代表提及，跟他有没有被「回复」是两回事。
 */
const replyTo = (comment: any) => {
  const name = comment?.author?.username
  if (!name) return
  // 已经有了就替换掉开头的那个 @，避免 @a @b 叠成一串
  // 字符集兼容中文用户名（与 utils/markdown.ts 的 @提及规则保持一致）
  replyContent.value = `@${name} ` + replyContent.value.replace(
    /^@[A-Za-z0-9_\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+\s*/, ''
  )
  replyBox.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  replyEditor.value?.focus()
}

// 编辑已发布帖子（仅秩序管理）
const editingPost = ref(false)
const editTitle = ref('')
const editContent = ref('')
const editSaving = ref(false)
const editProblemId = ref<number | null>(null)
const editProblemKeyword = ref('')
const editProblemResults = ref<any[]>([])
const editProblemSelected = ref<any | null>(null)
let editSearchTimer: any = null

const startEditPost = () => {
  editTitle.value = post.value.title
  editContent.value = post.value.content
  editProblemId.value = post.value.problem_id ?? null
  editProblemSelected.value = post.value.problem ? { ...post.value.problem } : null
  editProblemKeyword.value = ''
  editProblemResults.value = []
  editingPost.value = true
}

const cancelEditPost = () => {
  editingPost.value = false
}

const searchEditProblems = () => {
  if (editSearchTimer) clearTimeout(editSearchTimer)
  if (!editProblemKeyword.value.trim()) {
    editProblemResults.value = []
    return
  }
  editSearchTimer = setTimeout(async () => {
    try {
      const data: any = await apiClient.get('/api/problems', {
        params: { keyword: editProblemKeyword.value.trim(), page: 0, page_size: 10 }
      })
      editProblemResults.value = Array.isArray(data?.problems) ? data.problems : []
    } catch {
      editProblemResults.value = []
    }
  }, 250)
}

const pickEditProblem = (p: any) => {
  editProblemSelected.value = p
  editProblemId.value = p.id
  editProblemKeyword.value = ''
  editProblemResults.value = []
}

const clearEditProblem = () => {
  editProblemSelected.value = null
  editProblemId.value = null
  editProblemKeyword.value = ''
  editProblemResults.value = []
}

const saveEditPost = async () => {
  if (!editTitle.value.trim() || editTitle.value.trim().length < 3) {
    alert('标题至少 3 个字符')
    return
  }
  if (!editContent.value.trim()) {
    alert('正文不能为空')
    return
  }
  editSaving.value = true
  try {
    const res: any = await apiClient.put(`/api/forum/posts/${route.params.id}`, {
      title: editTitle.value.trim(),
      content: editContent.value.trim(),
      problem_id: editProblemId.value
    })
    post.value.title = res.title
    post.value.content = res.content
    post.value.problem_id = res.problem_id
    post.value.problem = res.problem
    editingPost.value = false
  } catch (err: any) {
    alert(err.response?.data?.detail || '保存失败')
  } finally {
    editSaving.value = false
  }
}

// 置顶/锁定（仅秩序管理）——乐观更新，失败回滚
const togglePinPost = async () => {
  const target = !post.value.is_pinned
  const result = await Swal.fire({
    title: target ? '确定要置顶这个帖子吗？' : '确定要取消置顶吗？',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonText: target ? '确认置顶' : '确认取消',
    cancelButtonText: '取消',
    confirmButtonColor: 'var(--primary)',
    cancelButtonColor: '#909399'
  })
  if (!result.isConfirmed) return
  post.value.is_pinned = target
  try {
    const res: any = await apiClient.put(`/api/forum/posts/${route.params.id}/moderate`, { is_pinned: target })
    post.value.is_pinned = res.is_pinned
  } catch (err: any) {
    post.value.is_pinned = !target
    Swal.fire({ icon: 'error', title: '操作失败', text: err.response?.data?.detail || err.message || '未知错误' })
  }
}

const toggleLockPost = async () => {
  const target = !post.value.is_locked
  const result = await Swal.fire({
    title: target ? '确定要锁定这个帖子吗？' : '确定要解除锁定吗？',
    text: target ? '锁定后所有人将无法回复' : '',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonText: target ? '确认锁定' : '确认解锁',
    cancelButtonText: '取消',
    confirmButtonColor: 'var(--primary)',
    cancelButtonColor: '#909399'
  })
  if (!result.isConfirmed) return
  post.value.is_locked = target
  try {
    const res: any = await apiClient.put(`/api/forum/posts/${route.params.id}/moderate`, { is_locked: target })
    post.value.is_locked = res.is_locked
  } catch (err: any) {
    post.value.is_locked = !target
    Swal.fire({ icon: 'error', title: '操作失败', text: err.response?.data?.detail || err.message || '未知错误' })
  }
}

const isLoggedIn = computed(() => authStore.isAuthenticated)
const isMuted = computed(() => authStore.currentUser?.can_speak === false)

const letterAvatar = (name: string) => {
  const ch = (name || 'U').trim().charAt(0).toUpperCase() || 'U'
  return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Crect width='40' height='40' fill='%23e74c3c'/%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' dy='.3em' fill='white' font-size='16' font-family='Arial'%3E${encodeURIComponent(ch)}%3C/text%3E%3C/svg%3E`
}

const fmtTime = (iso: string) => {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

// 富文本渲染（Markdown + LaTeX 公式）
import { renderRichText } from '@/utils/markdown'
import MarkdownSplitEditor from '@/components/MarkdownSplitEditor.vue'
const renderContent = (content: string) => renderRichText(content)

const loadPost = async () => {
  loading.value = true
  error.value = ''
  try {
    post.value = await apiClient.get(`/api/forum/posts/${route.params.id}`)
    document.title = `${post.value.title} - NLNOJ`
  } catch (err: any) {
    // 帖子已删除（含多人举报自动删除）：回到讨论列表
    if (err.response?.status === 404) {
      router.replace('/discuss')
      return
    }
    error.value = err.response?.data?.detail || err.message || '加载失败'
    document.title = '讨论详情 - NLNOJ'
  } finally {
    loading.value = false
  }
}

watch(() => post.value?.title, (title) => {
  if (title) document.title = `${title} - NLNOJ`
})

const submitReply = async () => {
  if (!replyContent.value.trim()) return
  replySubmitting.value = true
  try {
    await apiClient.post(`/api/forum/posts/${route.params.id}/comments`, {
      content: replyContent.value.trim()
    })
    replyContent.value = ''
    await loadPost()
  } catch (err: any) {
    alert(err.response?.data?.detail || '回复失败')
  } finally {
    replySubmitting.value = false
  }
}

const removePost = async () => {
  if (!confirm('确定删除这个帖子吗？回复将一并删除。')) return
  try {
    await apiClient.delete(`/api/forum/posts/${route.params.id}`)
    router.push('/discuss')
  } catch (err: any) {
    alert(err.response?.data?.detail || '删除失败')
  }
}

// ==================== 举报 ====================
// 跳转独立举报页：/report/post/:id（帖子）、/report/comment/:id（回复）。
// 返回时组件重建并 loadPost，被多人举报自动删除的回复会自动消失；
// 帖子本身被删除则由 loadPost 的 404 处理跳回列表。
const reportPost = () => {
  router.push(`/report/post/${route.params.id}`)
}

const reportComment = (c: any) => {
  router.push(`/report/comment/${c.id}`)
}

// ==================== 删除帖子回复 ====================
/**
 * 仅秩序管理（can_manage）、回复发送者本人、帖子发送者本人可删除。
 */
const canDeleteComment = (c: any) => {
  const me = authStore.currentUser
  if (!me) return false
  return !!(
    post.value?.can_manage
    || c.author?.id === me.id
    || (post.value?.is_author && c.author?.id !== me.id)
  )
}

const removeComment = async (c: any) => {
  const result = await Swal.fire({
    title: '确定删除这条回复吗？',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonText: '确认删除',
    cancelButtonText: '取消',
    confirmButtonColor: 'var(--primary)',
    cancelButtonColor: '#909399'
  })
  if (!result.isConfirmed) return
  try {
    await apiClient.delete(
      `/api/forum/posts/${route.params.id}/comments/${c.id}`
    )
    await loadPost()
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '删除失败', text: err.response?.data?.detail || err.message || '未知错误' })
  }
}

// ==================== 置顶回复（仅秩序管理） ====================
/**
 * 楼层号按「发布顺序」计算（按 id 排序），不随置顶重排而改变——
 * 否则被置顶的回复会显示成 #1，看起来像是最早发的。
 */
const floorMap = computed(() => {
  const m = new Map<number, number>()
  ;[...(post.value?.comments || [])]
    .sort((a: any, b: any) => a.id - b.id)
    .forEach((c: any, idx: number) => m.set(c.id, idx + 1))
  return m
})

const pinningId = ref<number | null>(null)

const togglePin = async (c: any) => {
  pinningId.value = c.id
  try {
    await apiClient.post(
      `/api/forum/posts/${route.params.id}/comments/${c.id}/pin`
    )
    await loadPost()
  } catch (err: any) {
    Swal.fire({
      icon: 'error',
      title: '操作失败',
      text: err.response?.data?.detail || err.message || '未知错误'
    })
  } finally {
    pinningId.value = null
  }
}

onMounted(() => loadPost())
</script>

<template>
  <div class="post-detail-page">
    <div class="detail-container">
      <div v-if="loading" class="state-box">加载中...</div>
      <div v-else-if="error" class="state-box error-text">❌ {{ error }}</div>

      <template v-else-if="post">
        <!-- ===== 左主栏：标题/作者/正文/回复 ===== -->
        <div class="main-col">
          <div class="post-head-card">
            <h1 class="post-title">
              <router-link
                v-if="post.problem"
                :to="`/problem/${post.problem.id}`"
                class="head-problem-tag"
              >{{ post.problem.problem_number }}</router-link>
              {{ post.title }}
            </h1>
            <span v-if="post.is_pinned" class="pin-badge">置顶</span>
            <span v-if="post.is_locked" class="lock-badge"><i class="fa-solid fa-lock"></i> 已锁定</span>
            <div class="author-line">
              <UserAvatarStatus :user="post.author" :size="8">
                <img
                  :src="post.author?.avatar_url || letterAvatar(post.author?.username)"
                  class="author-avatar"
                  :alt="post.author?.username"
                >
              </UserAvatarStatus>
              <router-link
                :to="post.author?.user_number ? `/user/${post.author.user_number}` : '#'"
                class="post-author"
                :style="{ color: userColor(post.author) }"
              >{{ post.author?.username }}</router-link>
              <span
                v-if="getUserTagDisplay(post.author)"
                class="user-tag-display"
                :style="{ backgroundColor: userColor(post.author) }"
              >{{ getUserTagDisplay(post.author) }}</span>
              <span v-if="post.author?.is_admin" class="staff-badge">管理员</span>
              <span class="post-time">发表于 {{ fmtTime(post.created_at) }}</span>
              <button
                v-if="post.can_manage || post.is_author"
                class="head-btn danger"
                @click="removePost"
              >删除</button>
            </div>
          </div>

          <!-- 编辑模式（仅秩序管理）：标题与正文表单 -->
          <template v-if="editingPost">
            <div class="edit-card">
              <div class="edit-title-row">
                <span class="edit-label">标题</span>
                <input v-model="editTitle" class="edit-title-input" maxlength="100" />
              </div>
              <div class="edit-problem-row">
                <span class="edit-label">关联题目</span>
                <div v-if="!editProblemSelected" class="edit-problem-search">
                  <input
                    v-model="editProblemKeyword"
                    class="edit-problem-input"
                    placeholder="按题号或标题搜索"
                    @input="searchEditProblems"
                  />
                  <div v-if="editProblemResults.length" class="edit-problem-results">
                    <div
                      v-for="p in editProblemResults"
                      :key="p.id"
                      class="edit-problem-item"
                      @click="pickEditProblem(p)"
                    >
                      <span class="ep-num">{{ p.problem_number }}</span>
                      <span class="ep-title">{{ p.title }}</span>
                    </div>
                  </div>
                </div>
                <div v-else class="edit-problem-selected">
                  <span class="ep-num">{{ editProblemSelected.problem_number }}</span>
                  <span class="ep-title">{{ editProblemSelected.title }}</span>
                  <button type="button" class="ep-clear" @click="clearEditProblem">
                    <i class="fa-solid fa-xmark"></i>
                  </button>
                </div>
              </div>
              <span class="edit-label">正文</span>
              <MarkdownSplitEditor v-model="editContent" height="300px" :maxlength="20000" />
              <div class="edit-actions">
                <button class="btn-submit" :disabled="editSaving" @click="saveEditPost">
                  {{ editSaving ? '保存中...' : '保存' }}
                </button>
                <button class="btn-cancel-2" :disabled="editSaving" @click="editingPost = false">取消</button>
              </div>
            </div>
          </template>

          <!-- 正文卡片（非编辑模式） -->
          <div v-else class="content-card prose" v-html="renderContent(post.content)"></div>

          <!-- 回复列表 -->
          <div class="comments-head">回复（{{ post.comments.length }}）</div>
          <div v-if="post.comments.length === 0" class="state-box">暂无回复</div>
          <div v-else class="comments">
            <div v-for="(c, i) in post.comments" :key="c.id" class="comment-item" :class="{ pinned: c.is_pinned }">
              <div class="comment-head">
                <UserAvatarStatus :user="c.author" :size="8">
                  <img
                    :src="c.author?.avatar_url || letterAvatar(c.author?.username)"
                    class="comment-avatar"
                    :alt="c.author?.username"
                  >
                </UserAvatarStatus>
                <router-link
                  :to="c.author?.user_number ? `/user/${c.author.user_number}` : '#'"
                  class="post-author"
                  :style="{ color: userColor(c.author) }"
                >{{ c.author?.username }}</router-link>
                <span
                  v-if="getUserTagDisplay(c.author)"
                  class="user-tag-display"
                  :style="{ backgroundColor: userColor(c.author) }"
                >{{ getUserTagDisplay(c.author) }}</span>
                <span v-if="c.is_pinned" class="comment-pin-badge">
                  <i class="fa-solid fa-thumbtack"></i> 置顶
                </span>
                <span class="comment-floor">#{{ floorMap.get(c.id) ?? Number(i) + 1 }}</span>
                <span class="comment-time">{{ fmtTime(c.created_at) }}</span>
                <!-- 回复按钮：点一下只是 @ 对方，回复仍然是扁平的不分层 -->
                <button
                  v-if="isLoggedIn && !isMuted && !post.is_locked"
                  class="comment-reply-btn"
                  @click="replyTo(c)"
                >回复</button>
                <!-- 举报：不是自己发的、有自由发言 -->
                <button
                  v-if="isLoggedIn && authStore.currentUser?.can_speak && c.author?.id !== authStore.currentUser?.id"
                  class="comment-mini-btn report"
                  @click="reportComment(c)"
                >举报</button>
                <!-- 置顶：仅秩序管理 -->
                <button
                  v-if="post.can_manage"
                  class="comment-mini-btn pin"
                  :class="{ 'is-pinned': c.is_pinned }"
                  :disabled="pinningId === c.id"
                  @click="togglePin(c)"
                >{{ c.is_pinned ? '取消置顶' : '置顶' }}</button>
                <!-- 删除：秩序管理 / 回复作者 / 帖子作者 -->
                <button
                  v-if="canDeleteComment(c)"
                  class="comment-mini-btn delete"
                  @click="removeComment(c)"
                >删除</button>
              </div>
              <div class="comment-content prose" v-html="renderContent(c.content)"></div>
            </div>
          </div>

          <!-- 回复框 -->
          <div v-if="isLoggedIn && isMuted" class="state-box"><i class="fa-solid fa-ban"></i> 你已被禁言，无法回复</div>
          <div v-else-if="isLoggedIn && post.is_locked" class="state-box"><i class="fa-solid fa-lock"></i> 该帖子已锁定，无法回复</div>
          <div v-else-if="isLoggedIn" ref="replyBox" class="reply-box">
            <div class="reply-box-head">发表回复</div>
            <MarkdownSplitEditor
              ref="replyEditor"
              v-model="replyContent"
              height="220px"
              placeholder="支持 Markdown：**粗体**、*斜体*、代码块、$公式$"
              :maxlength="10000"
            />
            <div class="reply-actions">
              <button class="btn-submit" :disabled="replySubmitting || !replyContent.trim()" @click="submitReply">
                {{ replySubmitting ? '发送中...' : '回复' }}
              </button>
            </div>
          </div>
          <div v-else class="state-box">
            <router-link to="/login" class="link">登录</router-link> 后即可回复
          </div>
        </div>

        <!-- ===== 右侧信息栏 ===== -->
        <aside class="side-col">
          <div class="info-card">
            <div class="info-card-title">帖子信息</div>

            <div class="side-row">
              <span class="side-label">创建者</span>
              <span class="side-value">
                <img
                  :src="post.author?.avatar_url || letterAvatar(post.author?.username)"
                  class="side-avatar"
                  :alt="post.author?.username"
                >
                <router-link
                  :to="post.author?.user_number ? `/user/${post.author.user_number}` : '#'"
                  class="post-author"
                  :style="{ color: userColor(post.author) }"
                >{{ post.author?.username }}</router-link>
              </span>
            </div>

            <div class="side-row">
              <span class="side-label">发帖时间</span>
              <span class="side-value">{{ fmtTime(post.created_at) }}</span>
            </div>

            <div class="side-row">
              <span class="side-label">所属板块</span>
              <span class="side-value forum-text">{{ post.forum_name }}</span>
            </div>

            <div v-if="post.problem" class="side-row side-problem-row">
              <span class="side-label">关联题目</span>
              <router-link
                :to="`/problem/${post.problem.id}`"
                class="side-problem-link"
              >
                <span class="ep-num">{{ post.problem.problem_number }}</span>
                <span class="ep-title">{{ post.problem.title }}</span>
              </router-link>
            </div>

            <div class="side-row">
              <span class="side-label">状态</span>
              <span class="side-value">
                <span v-if="post.is_pinned" class="pin-badge">置顶中</span>
                <span v-if="post.is_locked" class="lock-badge-side">已锁定</span>
                <span v-if="!post.is_pinned && !post.is_locked">正常</span>
              </span>
            </div>

            <!-- 管理操作（仅秩序管理） -->
            <template v-if="post.can_manage">
              <div class="side-divider"></div>
              <div class="side-label manage-title">管理操作</div>
              <button class="side-action-btn" @click="startEditPost">
                <i class="fa-solid fa-pen"></i> 编辑帖子
              </button>
              <button class="side-action-btn" @click="togglePinPost">
                <i :class="post.is_pinned ? 'fa-solid fa-thumbtack-slash' : 'fa-solid fa-thumbtack'"></i>
                {{ post.is_pinned ? ' 取消置顶' : ' 置顶' }}
              </button>
              <button class="side-action-btn" @click="toggleLockPost">
                <i :class="post.is_locked ? 'fa-solid fa-unlock' : 'fa-solid fa-lock'"></i>
                {{ post.is_locked ? ' 解锁' : ' 锁定' }}
              </button>
            </template>

            <div class="side-divider"></div>
            <button v-if="!post.is_author && authStore.currentUser?.can_speak" class="report-btn" @click="reportPost"><i class="fa-solid fa-flag"></i> 举报</button>
          </div>
        </aside>
      </template>
    </div>
  </div>
</template>

<style scoped>
.post-detail-page {
  min-height: 100vh;
  line-height: 1.6;
}

.detail-container {
  max-width: 1100px;
  margin: 0 auto;
}

/* ===== 双栏布局 ===== */
.detail-container {
  display: grid;
  grid-template-columns: 1fr 300px;
  gap: 16px;
  align-items: start;
}

.main-col {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.side-col {
  position: sticky;
  top: 70px;
}

/* ===== 标题与作者 ===== */
.post-head-card {
  background: var(--surface);
  -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: 20px 24px 14px;
}

.post-title {
  font-size: 1.55rem;
  font-weight: 700;
  color: var(--text-strong);
  margin: 0 0 12px;
  word-break: break-word;
  line-height: 1.4;
}

.pin-badge {
  display: inline-block;
  background: var(--primary);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  padding: 2px 10px;
  border-radius: 4px;
  margin-right: 8px;
  vertical-align: middle;
}

.lock-badge-side {
  display: inline-block;
  background: #e67e22;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  padding: 2px 10px;
  border-radius: 4px;
  margin-right: 8px;
  vertical-align: middle;
}

.author-line {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 14px;
  color: var(--text-sub);
}

.author-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--bg-subtle);
}

.post-author {
  font-weight: 700;
  text-decoration: none;
}

.user-tag-display {
  display: inline-block;
  border-radius: 2px;
  padding: 1px 8px;
  color: #fff;
  font-size: 11px;
  font-weight: 600;
}

.staff-badge {
  background: var(--primary);
  color: #fff;
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 10px;
  font-weight: 600;
}

.post-time {
  color: #a0aec0;
  font-size: 13px;
}

.head-btn {
  margin-left: auto;
  background: none;
  border: none;
  color: #c0c8d0;
  font-size: 12px;
  cursor: pointer;
}

.head-btn:hover {
  color: var(--primary);
}

/* ===== 正文卡片 ===== */
.content-card {
  background: var(--surface);
  -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: 20px 24px;
  color: var(--text-strong);
  font-size: 15px;
  word-break: break-word;
}

.edit-card {
  background: var(--surface);
  -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: 20px 24px;
}

.edit-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.edit-label {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-sub);
  flex-shrink: 0;
}

.edit-title-input {
  flex: 1;
  padding: 10px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  outline: none;
  transition: border-color 0.2s;
}

.edit-title-input:focus {
  border-color: var(--primary);
}

.edit-content-input {
  width: 100%;
  padding: 12px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  font-size: 14px;
  font-family: inherit;
  resize: vertical;
  outline: none;
  box-sizing: border-box;
  margin-top: 8px;
  transition: border-color 0.2s;
}

.edit-content-input:focus {
  border-color: var(--primary);
}

.edit-problem-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 12px;
  flex-direction: column;
}

.edit-problem-search {
  width: 100%;
  position: relative;
}

.edit-problem-input {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  box-sizing: border-box;
  transition: border-color 0.2s;
}

.edit-problem-input:focus {
  border-color: var(--primary);
}

.edit-problem-results {
  margin-top: 6px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: var(--surface-plain);
  max-height: 220px;
  overflow-y: auto;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.06);
}

.edit-problem-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  border-bottom: 1px solid #f1f1f4;
}

.edit-problem-item:last-child {
  border-bottom: none;
}

.edit-problem-item:hover {
  background: var(--surface-plain);
}

.edit-problem-selected {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: color-mix(in srgb, var(--primary) 7%, transparent);
  border: 1px solid color-mix(in srgb, var(--primary) 35%, transparent);
  border-radius: 8px;
}

.ep-num {
  font-weight: 700;
  color: var(--primary);
  font-size: 13px;
  flex-shrink: 0;
}

.ep-title {
  flex: 1;
  min-width: 0;
  color: var(--text-strong);
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ep-clear {
  background: none;
  border: none;
  color: #c0c8d0;
  cursor: pointer;
  flex-shrink: 0;
}

.ep-clear:hover {
  color: var(--primary);
}

.head-problem-tag {
  display: inline-block;
  background: color-mix(in srgb, var(--primary) 10%, transparent);
  color: var(--primary);
  font-size: 14px;
  font-weight: 700;
  padding: 2px 10px;
  border-radius: 6px;
  margin-right: 8px;
  text-decoration: none;
  vertical-align: middle;
}

.head-problem-tag:hover {
  background: var(--primary);
  color: #fff;
}

.side-problem-row {
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

.side-problem-link {
  display: flex;
  align-items: center;
  gap: 6px;
  text-decoration: none;
  width: 100%;
}

.side-problem-link:hover .ep-title {
  color: var(--primary);
}

.edit-actions {
  display: flex;
  gap: 12px;
  margin-top: 14px;
}

.btn-cancel-2 {
  padding: 8px 24px;
  background: var(--bg-subtle);
  color: var(--text-sub);
  border: none;
  border-radius: 20px;
  font-size: 14px;
  cursor: pointer;
}

/* 代码块/行内代码不再本地覆盖：统一交给 assets/markdown.css 的 .prose 深色方案
   （旧的 #f8f9fa 浅色 pre 覆盖比 .code-block 深底方案更早，两者叠加会出现
   深框里套浅底、浅色字看不清的问题） */
.content-card :deep(a) {
  color: var(--primary);
}

/* ===== 右侧信息卡 ===== */
.side-col {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.info-card {
  background: var(--surface);
  -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.info-card-title {
  font-weight: 700;
  font-size: 14px;
  color: var(--text-strong);
  padding-bottom: 10px;
  border-bottom: 1px solid #eef1f5;
}

.side-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}

.side-label {
  color: var(--text-sub);
  flex-shrink: 0;
}

.side-value {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-strong);
  font-weight: 600;
  text-align: right;
}

.side-avatar {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--bg-subtle);
}

.forum-text {
  color: #3498db;
}

.side-divider {
  height: 1px;
  background: var(--bg-subtle);
  margin: 2px 0;
}

.manage-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-sub);
}

.side-action-btn {
  padding: 8px 14px;
  background: var(--surface-plain);
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 13px;
  color: var(--text-sub);
  cursor: pointer;
  text-align: left;
  transition: all 0.2s;
}

.side-action-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.report-btn {
  margin-top: 4px;
  padding: 8px 14px;
  background: var(--surface-plain);
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 13px;
  color: var(--primary);
  cursor: pointer;
  text-align: left;
  transition: all 0.2s;
}

.report-btn:hover {
  border-color: var(--primary);
  background: color-mix(in srgb, var(--danger) 10%, transparent);
}

/* ===== 回复 ===== */
.comments-head {
  font-weight: 700;
  font-size: 15px;
  color: var(--text-strong);
  margin-bottom: 10px;
}

.comments {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.comment-item {
  background: var(--surface);
  -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: 14px 18px;
}

.comment-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.comment-avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--bg-subtle);
}

.comment-floor {
  color: #c0c8d0;
  font-size: 12px;
}

.comment-time {
  color: #a0aec0;
  font-size: 12px;
  margin-left: auto;
}

/* 「回复」按钮：平时低调，hover 才明显，避免每条回复都挂一个醒目按钮 */
.comment-reply-btn {
  padding: 2px 10px;
  border: 1px solid #e2e8f0;
  background: var(--surface-plain);
  border-radius: 12px;
  font-size: 12px;
  color: var(--text-sub);
  cursor: pointer;
  transition: all 0.2s;
}

.comment-reply-btn:hover {
  color: var(--primary);
  border-color: var(--primary);
}

/* 举报/删除小按钮：比「回复」更低调，hover 才显色 */
.comment-mini-btn {
  padding: 2px 10px;
  border: 1px solid transparent;
  background: transparent;
  border-radius: 12px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.comment-mini-btn.report {
  color: #a0aec0;
}

.comment-mini-btn.report:hover {
color: var(--primary-text);
  border-color: #f3c1bb;
  background: color-mix(in srgb, var(--danger) 10%, transparent);
}

.comment-mini-btn.delete {
  color: #a0aec0;
}

.comment-mini-btn.delete:hover {
color: var(--danger-text);
  border-color: #f3c1bb;
  background: color-mix(in srgb, var(--danger) 10%, transparent);
}

/* ===== 回复置顶 ===== */
.comment-item.pinned {
  border-left: 3px solid var(--primary);
  background: color-mix(in srgb, var(--primary) 5%, transparent);
}

.comment-pin-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--primary);
  background: color-mix(in srgb, var(--primary) 12%, transparent);
  border-radius: 4px;
  padding: 1px 7px;
}

.comment-mini-btn.pin:hover {
  color: var(--primary);
  border-color: color-mix(in srgb, var(--primary) 45%, transparent);
  background: color-mix(in srgb, var(--primary) 10%, transparent);
}

.comment-mini-btn.pin.is-pinned {
  color: var(--primary);
  border-color: color-mix(in srgb, var(--primary) 45%, transparent);
}

.comment-mini-btn:disabled {
  opacity: .5;
  cursor: not-allowed;
}

.comment-content {
  color: var(--text-strong);
  font-size: 14px;
  word-break: break-word;
}

/* ===== 回复框 ===== */
.reply-box {
  background: var(--surface);
  -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: 16px 18px;
}

.reply-box-head {
  font-size: 13px;
  color: var(--text-sub);
  margin-bottom: 10px;
}

.reply-textarea {
  width: 100%;
  padding: 12px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  font-size: 14px;
  font-family: inherit;
  resize: vertical;
  outline: none;
  box-sizing: border-box;
}

.reply-textarea:focus {
  border-color: var(--primary);
}

.reply-actions {
  margin-top: 10px;
  text-align: right;
}

.btn-submit {
  padding: 8px 28px;
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: 20px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.btn-submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.state-box {
  text-align: center;
  padding: 40px 20px;
  color: var(--text-sub);
  background: var(--surface-plain);
  border-radius: 12px;
}

.error-text {
  color: var(--primary);
}

.link {
  color: var(--primary);
  margin: 0 4px;
}

/* ===== 响应式：窄屏单列 ===== */
@media (max-width: 900px) {
  .detail-container {
    grid-template-columns: 1fr;
  }

  .side-col {
    position: static;
  }
}

/* ===== 手机端：帖子内容占比大，内边距收窄收益明显 ===== */
@media (max-width: 600px) {
  .post-head-card,
  .content-card,
  .edit-card {
    padding: 16px 14px;
  }

  .comment-item,
  .info-card {
    padding: 12px 14px;
  }
}
</style>
