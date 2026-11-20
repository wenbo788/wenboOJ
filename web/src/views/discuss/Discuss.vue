<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import apiClient from '@/api/client'
import { userNameColor as userColor } from '@/utils/userColor'
import { getUserTagDisplay } from '@/utils/userTag'
import { useAcademicMode } from '@/utils/academicMode'
import { canManageCommunity } from '@/utils/permissions'

const router = useRouter()
const authStore = useAuthStore()

const FORUMS: Record<string, string> = {
  all: '全部',
  siteaffairs: '站务版',
  problem: '题目总版',
  academics: '学术版',
  relevantaffairs: '灌水区',
}

// 学术模式下灌水区整体不可见（纯前端隐藏，服务端不禁）。
// 注意模板是 v-for 遍历这个对象（不是键数组），所以这里必须过滤成新的对象，
// 只筛键名的话模板压根用不上。
const { academicMode } = useAcademicMode()
const visibleForums = computed(() =>
  Object.fromEntries(
    Object.entries(FORUMS).filter(
      ([key]) => !(academicMode.value && key === 'relevantaffairs'),
    ),
  ),
)

const currentForum = ref('all')
const posts = ref<any[]>([])
const page = ref(0)
const loading = ref(false)
const hasMore = ref(true)
const error = ref('')

const isStaff = computed(() => canManageCommunity(authStore.currentUser))

const letterAvatar = (name: string) => {
  const ch = (name || 'U').trim().charAt(0).toUpperCase() || 'U'
  return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Crect width='40' height='40' fill='%23e74c3c'/%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' dy='.3em' fill='white' font-size='16' font-family='Arial'%3E${encodeURIComponent(ch)}%3C/text%3E%3C/svg%3E`
}

const relTime = (iso: string) => {
  if (!iso) return ''
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  if (diff < 172800000) {
    const d = Math.floor(diff / 86400)
    if (d === 1) return '昨天'
    if (d === 2) return '前天'
    if (d < 30) return `${d} 天前`
  }
  return new Date(iso).toLocaleDateString('zh-CN')
}

const loadPosts = async (append = false) => {
  if (loading.value || !hasMore.value) return
  loading.value = true
  error.value = ''
  try {
    let url = `/api/forum/posts?page=${page.value}&page_size=30`
    if (currentForum.value !== 'all') url += `&forum=${currentForum.value}`
    // 学术模式下灌水区要「整块」看不见：光把 tab 藏了没用，
    // 「全部」里照样会冒出灌水区的帖子。过滤交给服务端做，分页才不会漏页。
    if (academicMode.value) url += '&exclude_forum=relevantaffairs'
    const data: any = await apiClient.get(url)
    const list = Array.isArray(data?.posts) ? data.posts : []
    posts.value = append ? [...posts.value, ...list] : list
    page.value++
    hasMore.value = list.length >= 30
  } catch (err: any) {
    error.value = err.response?.data?.detail || err.message || '加载失败'
  } finally {
    loading.value = false
  }
}

const switchForum = (f: string) => {
  currentForum.value = f
  page.value = 0
  hasMore.value = true
  posts.value = []
  loadPosts(false)
}

const removePost = async (id: number) => {
  if (!confirm('确定删除这个帖子吗？回复将一并删除。')) return
  try {
    await apiClient.delete(`/api/forum/posts/${id}`)
    posts.value = posts.value.filter(p => p.id !== id)
  } catch (err: any) {
    alert(err.response?.data?.detail || '删除失败')
  }
}

const canDelete = (p: any) =>
  isStaff.value || (authStore.currentUser && p.author?.user_id === authStore.currentUser.id)

// 置顶/锁定（仅秩序管理）——乐观更新：点击立即生效，请求失败回滚
const togglePin = async (p: any) => {
  const target = !p.is_pinned
  p.is_pinned = target
  try {
    const res: any = await apiClient.put(`/api/forum/posts/${p.id}/moderate`, { is_pinned: target })
    p.is_pinned = res.is_pinned
  } catch (err: any) {
    p.is_pinned = !target
    alert(err.response?.data?.detail || err.message || '操作失败')
  }
}

const toggleLock = async (p: any) => {
  const target = !p.is_locked
  p.is_locked = target
  try {
    const res: any = await apiClient.put(`/api/forum/posts/${p.id}/moderate`, { is_locked: target })
    p.is_locked = res.is_locked
  } catch (err: any) {
    p.is_locked = !target
    alert(err.response?.data?.detail || err.message || '操作失败')
  }
}

// 开关在别的标签页拨动后回到本页：把停在灌水区的状态收回来。
// 必须走 switchForum（而不是只改 currentForum）——否则标题跳回「全部」，
// 底下还挂着灌水区的旧帖子。immediate 是给「进页面时就已经是开启状态」兜底。
watch(academicMode, (on) => {
  if (on && currentForum.value === 'relevantaffairs') {
    switchForum('all')
  }
}, { immediate: true })

onMounted(() => loadPosts(false))
</script>

<template>
  <div class="discuss-page">
    <div class="discuss-container">
      <!-- 头部 -->
      <div class="page-head">
        <div>
          <h2 class="page-title">讨论区</h2>
          <p class="page-sub">文明发言，理性讨论</p>
        </div>
        <button class="btn-new" @click="router.push('/discuss/new')"><i class="fa-solid fa-pen"></i> 发布帖子</button>
      </div>

      <!-- 版块筛选 -->
      <div class="forum-tabs">
        <button
          v-for="(name, key) in visibleForums"
          :key="key"
          class="forum-tab"
          :class="{ active: currentForum === key }"
          @click="switchForum(key)"
        >{{ name }}</button>
      </div>

      <!-- 帖子列表 -->
      <div v-if="error && posts.length === 0" class="empty">{{ error }}</div>
      <div v-else-if="!loading && posts.length === 0" class="empty">暂无帖子，来发第一贴吧</div>

      <div v-else class="post-list">
        <div v-for="p in posts" :key="p.id" class="post-card" :class="{ pinned: p.is_pinned }" @click="router.push(`/discuss/${p.id}`)">
          <div class="post-avatar">
            <img
              :src="p.author?.avatar_url || letterAvatar(p.author?.username)"
              :alt="p.author?.username"
              @error="($event.target as HTMLImageElement).src = letterAvatar(p.author?.username)"
            >
          </div>
          <div class="post-main">
            <div class="post-title">
              <span v-if="p.is_pinned" class="pin-badge">置顶</span>
              <span v-if="p.is_locked" class="lock-badge"><i class='fa-solid fa-lock'></i></span>
              <router-link
                v-if="p.problem"
                :to="`/problem/${p.problem.id}`"
                class="post-problem-tag"
                @click.stop
              >{{ p.problem.problem_number }}</router-link>
              {{ p.title }}
            </div>
            <div class="post-meta">
              <router-link
                :to="p.author?.user_number ? `/user/${p.author.user_number}` : '#'"
                class="post-author"
                :style="{ color: userColor(p.author) }"
                @click.stop
              >{{ p.author?.username }}</router-link>
              <span
                v-if="getUserTagDisplay(p.author)"
                class="user-tag-display"
                :style="{ backgroundColor: userColor(p.author) }"
              >{{ getUserTagDisplay(p.author) }}</span>
              <span class="post-forum">{{ p.forum_name }}</span>
              <span v-if="p.problem" class="post-problem-name">{{ p.problem.title }}</span>
              <span class="post-time">{{ relTime(p.created_at) }}</span>
              <span class="post-replies">{{ p.reply_count }} 回复</span>
              <template v-if="isStaff">
                <button class="post-mod-btn" @click.stop="togglePin(p)">{{ p.is_pinned ? '取消置顶' : '置顶' }}</button>
                <button class="post-mod-btn" @click.stop="toggleLock(p)">{{ p.is_locked ? '解锁' : '锁定' }}</button>
              </template>
              <button
                v-if="canDelete(p)"
                class="post-delete"
                title="删除帖子"
                @click.stop="removePost(p.id)"
              >删除</button>
            </div>
          </div>
        </div>
      </div>

      <div class="load-more-wrap">
        <button v-if="hasMore && posts.length" class="btn-more" :disabled="loading" @click="loadPosts(true)">
          {{ loading ? '加载中...' : '加载更多' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.discuss-page {
  min-height: 100vh;
  line-height: 1.5;
}

.discuss-container {
  max-width: 1000px;
  margin: 0 auto;
}

.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 14px;
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

.forum-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.forum-tab {
  padding: 7px 20px;
  border: 1px solid #e2e8f0;
  background: var(--surface-plain);
  border-radius: 20px;
  font-size: 13px;
  cursor: pointer;
  color: var(--text-sub);
  transition: all 0.2s;
}

.forum-tab.active {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}

.post-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.post-card {
  display: flex;
  gap: 14px;
  background: var(--surface);
  -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: 16px 18px;
  cursor: pointer;
  transition: box-shadow 0.2s;
}

.post-card:hover {
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.08);
}

/* 置顶样式：底色/边框都是主色 #4a4ae0 的浅色调。
   原来是旧红色主题的 #fffdf5 + #f5deb3（暖奶油/小麦色），
   放在蓝紫色站里怎么看都违和。 */
.post-card.pinned {
  background: color-mix(in srgb, var(--primary) 7%, transparent);
  border-color: color-mix(in srgb, var(--primary) 35%, transparent);
}

/* 与 DiscussPost / Home 的置顶徽章保持一致（之前这里漏改，还是旧的红色主题色） */
.pin-badge {
  display: inline-block;
  background: var(--primary);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  padding: 1px 8px;
  border-radius: 4px;
  margin-right: 6px;
  vertical-align: middle;
}

.lock-badge {
  margin-right: 6px;
  font-size: 13px;
  vertical-align: middle;
}

.post-mod-btn {
  background: none;
  border: none;
  color: #3498db;
  font-size: 12px;
  cursor: pointer;
  padding: 0;
}

.post-mod-btn:hover {
  text-decoration: underline;
}

.post-avatar img {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--bg-subtle);
}

.post-main {
  flex: 1;
  min-width: 0;
}

.post-title {
  font-weight: 700;
  font-size: 15px;
  color: var(--text-strong);
  margin-bottom: 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.post-card:hover .post-title {
  color: var(--primary);
}

.post-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 13px;
  color: var(--text-sub);
}

.post-author {
  font-weight: 600;
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

.post-forum {
  background: var(--bg-subtle);
  padding: 1px 10px;
  border-radius: 12px;
  font-size: 12px;
  color: var(--text-sub);
}

.post-problem-tag {
  display: inline-block;
  background: color-mix(in srgb, var(--primary) 10%, transparent);
  color: var(--primary);
  font-size: 12px;
  font-weight: 700;
  padding: 1px 8px;
  border-radius: 4px;
  margin-right: 6px;
  text-decoration: none;
  vertical-align: middle;
}

.post-problem-tag:hover {
  background: var(--primary);
  color: #fff;
}

.post-problem-name {
  color: var(--text-sub);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 200px;
}

.post-replies {
  margin-left: auto;
}

.post-delete {
  background: none;
  border: none;
  color: #c0c8d0;
  font-size: 12px;
  cursor: pointer;
}

.post-delete:hover {
  color: var(--primary);
}

.empty {
  text-align: center;
  padding: 60px 20px;
  color: var(--text-sub);
  background: var(--surface);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
}

.load-more-wrap {
  text-align: center;
  padding: 16px 0;
}

.btn-more {
  padding: 9px 36px;
  border: 1px solid #e2e8f0;
  background: var(--surface-plain);
  border-radius: 22px;
  font-size: 13px;
  color: var(--text-sub);
  cursor: pointer;
}

.btn-more:hover:not(:disabled) {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}

/* ===== 手机端：原本无任何媒体查询 ===== */
@media (max-width: 600px) {
  .post-card {
    padding: 14px;
  }

  .empty {
    padding: 40px 14px;
  }
}
</style>
