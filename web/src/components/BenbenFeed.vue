<script setup lang="ts">
/**
 * 犇犇列表（只读版）—— 用于用户主页的「动态」标签页。
 *
 * 与首页的犇犇模块同源但做了精简：
 *   - 没有发布框，没有「全部 / 我的」切换
 *   - 只保留「举报 / 删除」：查看他人主页时可举报违规动态，
 *     自己的动态可直接删除（是否本人由后端返回数据判断）
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import apiClient from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { userNameColor } from '@/utils/userColor'
import { getUserTagDisplay } from '@/utils/userTag'
import { renderRichText as renderMarkdown } from '@/utils/markdown'
import UserAvatarStatus from '@/components/UserAvatarStatus.vue'

const props = defineProps<{
  /** 要展示谁的动态（用户的 user_number，不是数据库主键） */
  userNumber: number
}>()

const PAGE_SIZE = 20

const router = useRouter()
const authStore = useAuthStore()
const list = ref<any[]>([])
const loading = ref(false)
const hasMore = ref(true)
const lastId = ref<number | null>(null)
const failed = ref(false)

const sentinelRef = ref<HTMLElement | null>(null)

const isSelf = computed(
  () => authStore.currentUser?.user_number === props.userNumber,
)
const isEmpty = computed(() => !loading.value && !failed.value && list.value.length === 0)
const emptyText = computed(() =>
  isSelf.value ? '你还没有发过动态' : 'TA 还没有发过动态',
)
const sentinelText = computed(() => {
  if (failed.value) return '加载出错，请刷新页面重试'
  if (loading.value) return '加载中...'
  if (list.value.length === 0) return ''
  return hasMore.value ? '点击加载更多' : '没有更多动态了'
})

/* ---------------- 展示用的小工具（与首页保持一致） ---------------- */

const getUserDisplayColor = (user: any) => userNameColor(user)


const letterAvatar = (name: string) => {
  const ch = (name || 'U').trim().charAt(0).toUpperCase() || 'U'
  return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Crect width='40' height='40' fill='%23e74c3c'/%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' dy='.3em' fill='white' font-size='16' font-family='Arial'%3E${encodeURIComponent(ch)}%3C/text%3E%3C/svg%3E`
}

const getUserAvatar = (item: any) => item.avatar_url || letterAvatar(item.username)

const formatTime = (dateStr: string) => new Date(dateStr).toLocaleString('zh-CN')

/* ---------------- 加载 ---------------- */

async function loadMore(reset = false) {
  if (loading.value) return
  if (!reset && !hasMore.value) return

  if (reset) {
    list.value = []
    lastId.value = null
    hasMore.value = true
    failed.value = false
  }

  loading.value = true
  try {
    let url = `/benben?limit=${PAGE_SIZE}&user_number=${props.userNumber}`
    if (lastId.value) url += `&before_id=${lastId.value}`

    const data = (await apiClient.get(url)) as any[]

    if (data && data.length > 0) {
      list.value = reset ? data : [...list.value, ...data]
      lastId.value = data[data.length - 1].id
      hasMore.value = data.length === PAGE_SIZE
    } else {
      hasMore.value = false
    }
  } catch (err) {
    console.error(err)
    failed.value = true
  } finally {
    loading.value = false
  }
}

/* ---------------- 删除（仅本人的犇犇会显示按钮） ---------------- */

async function remove(item: any) {
  try {
    await apiClient.delete(`/benben/${item.id}`)
    // 本地移除即可，不用整页重拉（列表会闪一下）
    list.value = list.value.filter((x) => x.id !== item.id)
  } catch (err: any) {
    alert('删除失败：' + (err.response?.data?.detail || err.message || '未知错误'))
  }
}

/* ---------------- 举报 ---------------- */

const openReport = (item: any) => {
  // 跳转独立举报页；返回时组件重建会自动重新加载列表
  router.push(`/report/benben/${item.id}`)
}

/* ---------------- 点击加载更多 ---------------- */

onMounted(() => {
  void loadMore(true)
})

// 在用户主页之间跳转时组件不会重建，得手动重新拉
watch(
  () => props.userNumber,
  () => {
    void loadMore(true)
  },
)

onBeforeUnmount(() => {
  // no-op: click-to-load mode no longer requires an observer
})
</script>

<template>
  <div class="benben-feed">
    <div v-if="loading && list.length === 0" class="loading-state">
      <span class="loading-spinner"></span>
      <span>犇犇加载中…</span>
    </div>

    <div v-if="isEmpty" class="benben-empty">{{ emptyText }}</div>

    <div class="benben-list">
      <div v-for="item in list" :key="item.id" class="benben-item">
        <div class="benben-avatar">
          <UserAvatarStatus :user="item" :size="8">
            <router-link :to="`/user/${item.user_number}`">
              <img
                :src="getUserAvatar(item)"
                :alt="item.username"
                @error="($event.target as HTMLImageElement).src = letterAvatar(item.username)"
              >
            </router-link>
          </UserAvatarStatus>
        </div>

        <div class="benben-content">
          <div class="benben-item-header">
            <div class="post-author">
              <span class="benben-user">
                <router-link
                  :to="`/user/${item.user_number}`"
                  class="benben-username"
                  :style="{ color: getUserDisplayColor(item) }"
                >{{ item.username }}</router-link><span
                  v-if="getUserTagDisplay(item)"
                  class="user-tag-display"
                  :style="{ backgroundColor: getUserDisplayColor(item) }"
                >{{ getUserTagDisplay(item) }}</span>
              </span>
              <span class="benben-time">{{ formatTime(item.created_at) }}</span>
            </div>

            <!-- 本人的可删除；他人的可举报（需有自由发言） -->
            <div class="benben-actions">
              <button
                v-if="!item.is_owner && authStore.currentUser?.can_speak"
                class="benben-report"
                @click="openReport(item)"
              >举报</button>
              <button v-if="item.is_owner" class="benben-delete" @click="remove(item)">删除</button>
            </div>
          </div>

          <div class="benben-text prose" v-html="renderMarkdown(item.content)" />

          <div v-if="item.reply_to_username" class="benben-reply-hint">
            <i class="fa-solid fa-reply" /> 回复了 @{{ item.reply_to_username }}
          </div>
        </div>
      </div>
    </div>

    <div v-if="sentinelText" ref="sentinelRef" class="feed-sentinel">
      <button
        v-if="hasMore && !loading && !failed"
        class="feed-load-more"
        type="button"
        @click="loadMore(false)"
      >
        {{ sentinelText }}
      </button>
      <span v-else>{{ sentinelText }}</span>
    </div>
  </div>
</template>

<style scoped>
.benben-empty {
  padding: 48px 0;
  text-align: center;
  font-size: 14px;
  color: var(--text-sub);
}

.benben-list {
  margin-top: 4px;
}

.benben-item {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  position: relative;
}

.benben-avatar {
  flex-shrink: 0;
  width: 40px;
  margin-top: 2px;
}

.benben-avatar a {
  display: block;
}

.benben-avatar img {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--bg-subtle);
}

.benben-content {
  flex: 1;
  background: var(--surface);
  -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 10px 16px 12px;
  position: relative;
  box-shadow: 0 1px 3px rgba(31, 41, 85, 0.05);
}

/* 原来这里有一对 ::before/::after 小三角（聊天气泡的“箭头”），
   颜色是写死的 #f0f2f5/#e9ecef，跟半透明气泡对不上，看着很脏，已去掉。 */

/* 作者行：原来是一条负 margin 出血的 #f0f2f5 灰头条，改成透明的一行，
   用户名/时间/删除按钮直接坐在亚克力气泡上。 */
.benben-item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 12px;
  background: none;
  padding: 0;
  margin: 0 0 6px;
}

.post-author {
  display: flex;
  align-items: center;
  gap: 4px 8px;
  flex-wrap: wrap;
}

.benben-user {
  display: inline-flex;
  align-items: center;
  vertical-align: middle;
}

.benben-username {
  font-weight: 600;
  color: var(--text-main);
  text-decoration: none;
  font-size: 14px;
  vertical-align: middle;
}

.benben-username:hover {
  color: var(--primary);
}

.user-tag-display {
  display: inline-block;
  border-radius: 6px;
  padding: 1px 8px;
  color: #fff;
  font-size: 11.5px;
  font-weight: 600;
  margin: 0 0 0 6px;
  cursor: default;
  transition: filter 0.15s;
  vertical-align: middle;
}

.user-tag-display:hover {
  filter: brightness(0.9);
}

.benben-time {
  font-size: 12px;
  color: var(--text-sub);
}

.benben-time::before {
  content: '·';
  margin-right: 6px;
}

.benben-actions {
  display: flex;
  gap: 2px;
  align-items: center;
}

/* 删除按钮做成小胶囊：平时只有文字，悬停才浮出底色 */
.benben-report {
  background: transparent;
  border: none;
  color: var(--text-sub);
  font-size: 12px;
  cursor: pointer;
  padding: 3px 10px;
  border-radius: 999px;
  transition: color 0.15s ease, background-color 0.15s ease;
}

.benben-report:hover {
  color: var(--primary);
  background: rgba(231, 76, 60, 0.08);
}

.benben-delete {
  background: transparent;
  border: none;
  color: var(--text-sub);
  font-size: 12px;
  cursor: pointer;
  padding: 3px 10px;
  border-radius: 999px;
  transition: color 0.15s ease, background-color 0.15s ease;
}

.benben-delete:hover {
  color: var(--danger);
  background: rgba(239, 68, 68, 0.1);
}

.benben-text {
  word-break: break-word;
}

/* 代码块/行内代码交给 assets/markdown.css 的 .prose 统一方案（深色 oneDark），
   旧的浅色 pre/code 覆盖会让深底上的浅字看不清 */
.benben-text :deep(a) {
  color: var(--primary);
  text-decoration: none;
}

.benben-text :deep(a:hover) {
  text-decoration: underline;
}

.benben-reply-hint {
  font-size: 12px;
  color: var(--text-sub);
  margin-top: 6px;
}

.feed-sentinel {
  padding: 14px 0;
  text-align: center;
  font-size: 12px;
  color: var(--text-sub);
}
</style>
