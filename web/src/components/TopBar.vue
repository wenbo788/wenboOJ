<script setup lang="ts">
import { ref, computed, defineAsyncComponent, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useNlnocStore } from '@/stores/nlnoc'
import apiClient from '@/api/client'
import { withBase } from '@/utils/base'
import {
  isAnyAdmin,
  isSuperAdmin,
  isTopAdmin,
  canManageProblems,
  canManageCommunity,
  canReviewArticles,
  canManageTeams,
} from '@/utils/permissions'

// 面板按需加载：它连带 katex/highlight.js/marked 一大票渲染依赖，
// 同步引会把首屏包从 ~150kB 撑到 ~500kB（点开信封时再下载完全来得及）
const NLNOCPanel = defineAsyncComponent(
  () => import('@/components/nlnoc/NLNOCPanel.vue'),
)
// 顶栏中央的管理组公告垂直轮播（站点管理里配置，未启用不占位）
const TopNotice = defineAsyncComponent(() => import('@/components/TopNotice.vue'))

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const nlnoc = useNlnocStore()

// ===== 认证相关 =====
const currentUser = computed(() => authStore.currentUser)

// 验证码相关
const captchaCanvas = ref<HTMLCanvasElement | null>(null)
const currentCaptcha = ref('')

// 生成验证码
const generateCaptcha = () => {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'
  let captcha = ''
  for (let i = 0; i < 5; i++) captcha += chars[Math.floor(Math.random() * chars.length)]
  currentCaptcha.value = captcha.toUpperCase()

  if (captchaCanvas.value) {
    const ctx = captchaCanvas.value.getContext('2d')
    if (ctx) {
      const canvas = captchaCanvas.value
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      ctx.fillStyle = '#f9fafb'
      ctx.fillRect(0, 0, canvas.width, canvas.height)

      for (let i = 0; i < 10; i++) {
        ctx.beginPath()
        ctx.moveTo(Math.random() * canvas.width, Math.random() * canvas.height)
        ctx.lineTo(Math.random() * canvas.width, Math.random() * canvas.height)
        ctx.strokeStyle = `rgba(100,100,100,${0.2 + Math.random() * 0.5})`
        ctx.stroke()
      }

      for (let i = 0; i < 100; i++) {
        ctx.fillStyle = `rgba(0,0,0,${Math.random() * 0.5})`
        ctx.fillRect(Math.random() * canvas.width, Math.random() * canvas.height, 1, 1)
      }

      for (let i = 0; i < currentCaptcha.value.length; i++) {
        ctx.font = `${24 + Math.floor(Math.random() * 6)}px "Courier New", monospace`
        ctx.fillStyle = `rgb(${50 + Math.random() * 100}, ${30 + Math.random() * 80}, ${20 + Math.random() * 70})`
        const x = 12 + i * 20 + Math.random() * 6
        const y = 30 + Math.random() * 8
        ctx.save()
        ctx.translate(x, y)
        ctx.rotate((Math.random() - 0.5) * 0.4)
        ctx.fillText(currentCaptcha.value[i], 0, 0)
        ctx.restore()
      }
    }
  }
}

// 头像生成
const letterAvatar = (name: string) => {
  const ch = (name || 'U').trim().charAt(0).toUpperCase() || 'U'
  return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Crect width='40' height='40' fill='%23e74c3c'/%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' dy='.3em' fill='white' font-size='16' font-family='Arial'%3E${encodeURIComponent(ch)}%3C/text%3E%3C/svg%3E`
}

// 计算属性
const avatarUrl = computed(() => {
  return authStore.currentUser?.avatar_url || letterAvatar(authStore.currentUser?.username || 'U')
})

const displayName = computed(() => {
  return authStore.currentUser?.username || '用户'
})

const userNumber = computed(() => {
  return authStore.currentUser?.user_number || 0
})

const userId = computed(() => {
  return authStore.currentUser?.id || 0
})

// 下拉菜单（两个菜单互斥，避免同时开着）
const showAvatarMenu = ref(false)
const showAdminMenu = ref(false)

const toggleAvatarMenu = () => {
  showAdminMenu.value = false
  showAvatarMenu.value = !showAvatarMenu.value
}

const toggleAdminMenu = () => {
  showAvatarMenu.value = false
  showAdminMenu.value = !showAdminMenu.value
}

// NLNOC 私信面板（点击式浮层，与头像/管理菜单互斥）
const toggleNlnoc = () => {
  showAvatarMenu.value = false
  showAdminMenu.value = false
  nlnoc.toggle()
}

// 通知铃铛：点击出「最近通知」下拉（条目跳通知链接，底部「查看更多」「全部已读」）
const showBellMenu = ref(false)
const bellMenuLoading = ref(false)
const bellNotis = ref<any[]>([])

const toggleBellMenu = () => {
  showAvatarMenu.value = false
  showAdminMenu.value = false
  if (showBellMenu.value) {
    showBellMenu.value = false
    return
  }
  showBellMenu.value = true
  void loadBellMenu()
}

/** 下拉打开即拉最新通知（最近 5 条） */
const loadBellMenu = async () => {
  bellMenuLoading.value = true
  try {
    const data: any = await apiClient.get('/api/notifications?page=0&page_size=5&group=all')
    bellNotis.value = Array.isArray(data?.notifications) ? data.notifications : []
  } catch {
    /* 拉失败显示空态，下次点开重试 */
  } finally {
    bellMenuLoading.value = false
  }
}

/** 点条目：未读先标记已读并刷新红点，再跳通知里的链接 */
const openBellNoti = async (n: any) => {
  showBellMenu.value = false
  if (!n.is_read) {
    try {
      await apiClient.put(`/api/notifications/${n.id}/read`)
      await fetchUnreadCount()
    } catch {
      /* 单条标记失败不拦跳转 */
    }
  }
  if (n.link) router.push(n.link)
}

/** 查看更多 → 通知页 */
const viewAllNotis = () => {
  showBellMenu.value = false
  router.push('/user/notification')
}

/** 全部已读：顶栏红点一键清零 */
const markAllNotisRead = async () => {
  try {
    await apiClient.put('/api/notifications/read-all')
    bellNotis.value = bellNotis.value.map((n: any) => ({ ...n, is_read: true }))
    await fetchUnreadCount()
  } catch (err: any) {
    window.alert(err?.response?.data?.detail || '操作失败，请稍后再试')
  }
}

// 未读通知数
const unreadCount = ref(0)

// 获取未读通知数量
const fetchUnreadCount = async () => {
  try {
    const data: any = await apiClient.get('/api/notifications/unread-count')
    unreadCount.value = data?.count || 0
    if (route.path === '/' && (data?.benben_mention || 0) > 0) {
      await apiClient.put('/api/notifications/read-all?type=mention&link=/').catch(() => {})
      const again: any = await apiClient
        .get('/api/notifications/unread-count')
        .catch(() => null)
      if (again) unreadCount.value = again?.count || 0
    }
  } catch {
    /* 静默失败（如网络抖动），下次轮询重试 */
  }
}

// 供其他组件在产生新通知后手动刷新红点
defineExpose({ fetchUnreadCount })

// 进入犇犇页面：立即清一遍犇犇 @提及 的未读
watch(
  () => route.path,
  (p) => {
    if (p === '/') void fetchUnreadCount()
  },
)

// 通知页里点掉一条 / 全部已读之后，角标立刻跟着掉
const handleNotificationsChanged = () => { fetchUnreadCount() }

onMounted(() => window.addEventListener('notifications:changed', handleNotificationsChanged))
onUnmounted(() => window.removeEventListener('notifications:changed', handleNotificationsChanged))

// NLNOC：会话已读后立刻刷新信封角标；ESC 关闭所有浮层
const handleNlnocChanged = () => { nlnoc.refreshUnread() }

const handleGlobalKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Escape') {
    nlnoc.close()
    showAvatarMenu.value = false
    showAdminMenu.value = false
  }
}

onMounted(() => window.addEventListener('nlnoc:unread-changed', handleNlnocChanged))
onMounted(() => document.addEventListener('keydown', handleGlobalKeydown))
onUnmounted(() => window.removeEventListener('nlnoc:unread-changed', handleNlnocChanged))
onUnmounted(() => document.removeEventListener('keydown', handleGlobalKeydown))

// 轮询通知
let notificationTimer: number | null = null

const startNotificationPolling = () => {
  if (notificationTimer) clearInterval(notificationTimer)
  notificationTimer = window.setInterval(() => {
    if (document.visibilityState === 'visible') {
      fetchUnreadCount()
      nlnoc.refreshUnread()
    }
  }, 15000)
}

const stopNotificationPolling = () => {
  if (notificationTimer) {
    clearInterval(notificationTimer)
    notificationTimer = null
  }
}

/** 切回标签页立即刷角标，不干等下一轮 */
const onVisibleRefresh = () => {
  if (document.visibilityState !== 'visible') return
  fetchUnreadCount()
  nlnoc.refreshUnread()
}
onMounted(() => document.addEventListener('visibilitychange', onVisibleRefresh))
onUnmounted(() => document.removeEventListener('visibilitychange', onVisibleRefresh))

// 登出
const handleLogout = async () => {
  showAvatarMenu.value = false
  await authStore.logout()
  router.push('/login')
}

// 生命周期
onMounted(() => {
  if (authStore.isAuthenticated) {
    fetchUnreadCount()
    nlnoc.refreshUnread()
    startNotificationPolling()
  }
})

onUnmounted(() => {
  stopNotificationPolling()
})

// 点击外部关闭菜单
const handleClickOutside = (event: MouseEvent) => {
  const target = event.target as HTMLElement
  if (!target.closest('.top-avatar-wrap') && !target.closest('.admin-menu-wrap')) {
    showAvatarMenu.value = false
    showAdminMenu.value = false
  }
  if (!target.closest('.bell-wrap')) showBellMenu.value = false
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

const openMobileDrawer = () => {
  window.dispatchEvent(new CustomEvent('mobile-sidebar:toggle'))
}

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>

<template>
  <div class="topbar">
    <!-- 品牌与移动端汉堡菜单 -->
    <div class="topbar-brand">
      <button
        type="button"
        class="mobile-menu-btn"
        aria-label="打开导航菜单"
        title="打开导航菜单"
        @click="openMobileDrawer"
      >
        <i class="fa-solid fa-bars"></i>
      </button>
      <a :href="withBase('/')" class="logo"><img :src="withBase('favicon.svg')" width="30"> <span>NLNOJ</span></a>
    </div>

    <!-- 顶栏中央：管理组公告垂直轮播（未配置不占位） -->
    <TopNotice />

    <!-- 认证按钮区域 -->
    <div class="auth-buttons" v-if="!authStore.isAuthenticated">
      <a :href="withBase('/login')" class="auth-btn">登录</a>
      <a :href="withBase('/register')" class="auth-btn">注册</a>
    </div>

    <!-- 用户信息区域 -->
    <div class="auth-buttons" v-else>
      <!-- 头像：点击弹出账号下拉菜单 -->
      <div class="top-avatar-wrap">
        <button
          type="button"
          class="top-avatar-btn"
          :aria-expanded="showAvatarMenu"
          aria-haspopup="menu"
          :title="displayName"
          @click.stop="toggleAvatarMenu"
        >
          <img
            :src="avatarUrl"
            :alt="displayName"
            class="avatar-img"
            onerror="this.onerror=null;this.src='data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 40 40%27%3E%3Crect width=%2740%27 height=%2740%27 fill=%27%23e74c3c%27/%3E%3Ctext x=%2750%25%27 y=%2750%25%27 text-anchor=%27middle%27 dy=%27.3em%27 fill=%27white%27 font-size=%2716%27 font-family=%27Arial%27%3EU%3C/text%3E%3C/svg%3E'"
          />
        </button>
        <div v-if="showAvatarMenu" class="top-avatar-menu" role="menu">
          <router-link
            :to="`/user/${userNumber}`"
            class="top-avatar-menu-item"
            role="menuitem"
            @click="showAvatarMenu = false"
          >
            <i class="fa-solid fa-user"></i> 个人主页
          </router-link>
          <router-link
            to="/profile"
            class="top-avatar-menu-item"
            role="menuitem"
            @click="showAvatarMenu = false"
          >
            <i class="fa-solid fa-gear"></i> 个人设置
          </router-link>
          <router-link
            to="/preferences"
            class="top-avatar-menu-item"
            role="menuitem"
            @click="showAvatarMenu = false"
          >
            <i class="fa-solid fa-sliders"></i> 偏好设置
          </router-link>
          <div class="top-avatar-menu-divider"></div>
          <button
            type="button"
            class="top-avatar-menu-item danger"
            role="menuitem"
            @click="handleLogout"
          >
            <i class="fa-solid fa-right-from-bracket"></i> 退出登录
          </button>
        </div>
      </div>

      <!-- 通知铃铛：点击出「最近通知」下拉 -->
      <div class="bell-wrap">
        <button
          type="button"
          class="bell-icon"
          title="消息通知"
          :aria-expanded="showBellMenu"
          @click.stop="toggleBellMenu"
        >
          <i class='fa-solid fa-bell'></i>
          <sup v-if="unreadCount > 0" class="bell-badge">{{ unreadCount > 99 ? '99+' : unreadCount }}</sup>
        </button>

        <div v-if="showBellMenu" class="bell-menu" role="menu">
          <div class="bell-menu-title">
            <i class="fa-solid fa-bell"></i> 最近通知
          </div>

          <div v-if="bellMenuLoading" class="bell-menu-empty">
            <i class="fa-solid fa-circle-notch fa-spin"></i> 加载中…
          </div>
          <div v-else-if="bellNotis.length === 0" class="bell-menu-empty">
            暂无通知
          </div>
          <template v-else>
            <button
              v-for="n in bellNotis"
              :key="n.id"
              type="button"
              class="bell-menu-item"
              @click="openBellNoti(n)"
            >
              <span class="bell-menu-dot" :class="{ on: !n.is_read }"></span>
              <span class="bell-menu-text">{{ n.content }}</span>
            </button>
          </template>

          <div class="top-avatar-menu-divider"></div>
          <button type="button" class="bell-menu-foot" @click="viewAllNotis">
            <i class="fa-solid fa-list"></i> 查看更多
          </button>
          <button type="button" class="bell-menu-foot" @click="markAllNotisRead">
            <i class="fa-solid fa-check-double"></i> 全部已读
          </button>
        </div>
      </div>

      <!-- NLNOC 私信 -->
      <div class="nlnoc-wrap">
        <button
          type="button"
          class="bell-icon nlnoc-trigger"
          title="NLNOC 私信"
          :aria-expanded="nlnoc.open"
          @click.stop="toggleNlnoc"
        >
          <i class="fa-solid fa-mobile-screen-button"></i>
          <sup v-if="nlnoc.unread > 0" class="bell-badge">
            {{ nlnoc.unread > 99 ? '99+' : nlnoc.unread }}
          </sup>
        </button>
        <NLNOCPanel v-if="nlnoc.open" />
      </div>

      <!-- 管理菜单入口：任意管理角色可见 -->
      <div
        v-if="isAnyAdmin(currentUser)"
        class="admin-menu-wrap"
      >
        <button
          class="admin-gear"
          title="管理菜单"
          aria-label="管理菜单"
          @click.stop="toggleAdminMenu"
        ><i class='fa-solid fa-gear'></i></button>
        <div v-if="showAdminMenu" class="admin-menu">
          <!-- 题目审核：题管及以上 -->
          <router-link
            v-if="canManageProblems(currentUser)"
            to="/admin/problems"
            class="admin-menu-item"
            @click="showAdminMenu = false"
          >
            <i class="fa-solid fa-gavel"></i> 题目审核
          </router-link>
          <!-- 题解文章审核：社管及以上 -->
          <router-link
            v-if="canReviewArticles(currentUser)"
            to="/admin/articles"
            class="admin-menu-item"
            @click="showAdminMenu = false"
          >
            <i class="fa-solid fa-newspaper"></i> 题解文章审核
          </router-link>
          <!-- 举报审核：社管及以上 -->
          <router-link
            v-if="canManageCommunity(currentUser)"
            to="/admin/reports"
            class="admin-menu-item"
            @click="showAdminMenu = false"
          >
            <i class="fa-solid fa-flag"></i> 举报审核
          </router-link>
          <!-- 奖项认证：超管及以上 -->
          <router-link
            v-if="isTopAdmin(currentUser)"
            to="/admin/award-cert"
            class="admin-menu-item"
            @click="showAdminMenu = false"
          >
            <i class="fa-solid fa-certificate"></i> 奖项认证
          </router-link>
          <!-- 团队封禁：大管及以上 -->
          <router-link
            v-if="canManageTeams(currentUser)"
            to="/admin/teams"
            class="admin-menu-item"
            @click="showAdminMenu = false"
          >
            <i class="fa-solid fa-people-group"></i> 团队封禁
          </router-link>
          <!-- 管理日志：超管及以上 -->
          <router-link
            v-if="isTopAdmin(currentUser)"
            to="/admin/logs"
            class="admin-menu-item"
            @click="showAdminMenu = false"
          >
            <i class="fa-solid fa-clock-rotate-left"></i> 管理日志
          </router-link>
          <!-- 用户管理：超管及以上 -->
          <router-link
            v-if="isTopAdmin(currentUser)"
            to="/admin/user"
            class="admin-menu-item"
            @click="showAdminMenu = false"
          >
            <i class="fa-solid fa-users"></i> 用户管理
          </router-link>
          <!-- 站点管理：超管及以上 -->
          <router-link
            v-if="isTopAdmin(currentUser)"
            to="/admin/site"
            class="admin-menu-item"
            @click="showAdminMenu = false"
          >
            <i class="fa-solid fa-sliders"></i> 站点管理
          </router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 顶部栏基础样式 */
.topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--surface-strong);
  -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  padding: 12px 24px;
  box-shadow: var(--shadow-card);
  position: sticky;
  top: 10px;
  z-index: 200;
  font-family: inherit;
  margin: 10px;
  border-radius: var(--radius-lg);
}

.topbar-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.mobile-menu-btn {
  display: none;
}

@media (max-width: 768px) {
  .mobile-menu-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    background: transparent;
    border: none;
    border-radius: var(--radius-sm, 8px);
    color: var(--text-color);
    font-size: 19px;
    cursor: pointer;
    transition: background-color 0.18s, color 0.18s;
    padding: 0;
    -webkit-tap-highlight-color: transparent;
  }

  .mobile-menu-btn:hover,
  .mobile-menu-btn:active {
    background: var(--bg-subtle, rgba(0, 0, 0, 0.06));
    color: var(--primary);
  }
}

.logo {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--primary);
  text-decoration: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
}

.logo:hover {
  color: var(--primary-hover);
}

.auth-buttons {
  display: flex;
  gap: 16px;
  align-items: center;
}

.auth-btn {
  background: var(--primary);
  color: white;
  border: none;
  border-radius: 30px;
  padding: 6px 20px;
  font-size: 14px;
  cursor: pointer;
  text-decoration: none;
  display: inline-block;
  transition: background 0.2s;
}

.auth-btn:hover {
  background: var(--primary-hover);
  text-decoration: none;
  color: white;
}

/* ===== 头像下拉菜单 ===== */
.top-avatar-btn {
  display: inline-flex;
  align-items: center;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
  border-radius: 50%;
  transition: box-shadow 0.15s ease;
}

.top-avatar-btn:hover,
.top-avatar-btn[aria-expanded='true'] {
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary) 35%, transparent);
}

.top-avatar-menu {
  position: absolute;
  top: calc(100% + 10px);
  right: 0;
  min-width: 150px;
  padding: 6px;
  background: var(--surface-plain);
  border: 1px solid #e6ebf2;
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(31, 41, 55, 0.14);
  z-index: 300;
}

.top-avatar-menu-item {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 9px 11px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--text-strong);
  font: inherit;
  font-size: 13px;
  text-align: left;
  text-decoration: none;
  cursor: pointer;
  box-sizing: border-box;
  transition: background 0.15s, color 0.15s;
}

.top-avatar-menu-item i {
  width: 16px;
  text-align: center;
}

.top-avatar-menu-item:hover {
  background: color-mix(in srgb, var(--primary) 10%, transparent);
  color: var(--primary);
}

.top-avatar-menu-item.danger {
  color: #dc2626;
}

.top-avatar-menu-item.danger:hover {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  color: #dc2626;
}

.top-avatar-menu-divider {
  height: 1px;
  margin: 5px 4px;
  background: var(--bg-subtle);
}

.bell-icon {
  position: relative;
  display: inline-flex;
  align-items: center;
  text-decoration: none;
  color: var(--text-sub);
  transition: color 0.2s;
  background: none;
  border: none;
  padding: 0;
  font: inherit;
  cursor: pointer;
}

.bell-icon:hover {
  color: var(--primary-hover);
}

.bell-badge {
  position: absolute;
  top: -8px;
  right: -12px;
  background-color: var(--primary);
  color: white;
  font-size: 10px;
  font-weight: bold;
  min-width: 16px;
  height: 16px;
  border-radius: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 4px;
  box-shadow: 0 0 2px rgba(0, 0, 0, 0.2);
  line-height: 1;
}

.nlnoc-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
}

.nlnoc-trigger {
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  font-family: inherit;
}

.bell-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
}

.bell-menu {
  position: absolute;
  top: calc(100% + 10px);
  right: 0;
  width: 300px;
  padding: 6px;
  background: var(--surface-plain);
  border: 1px solid #e6ebf2;
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(31, 41, 55, 0.14);
  z-index: 300;
}

.bell-menu-title {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 10px 6px;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-sub);
}

.bell-menu-empty {
  padding: 16px 10px;
  text-align: center;
  font-size: 12.5px;
  color: #9ca3af;
}

.bell-menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
  box-sizing: border-box;
  transition: background 0.15s;
}

.bell-menu-item:hover {
  background: color-mix(in srgb, var(--primary) 10%, transparent);
}

.bell-menu-dot {
  flex: none;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: transparent;
}

.bell-menu-dot.on {
  background: #ef4444;
}

.bell-menu-text {
  flex: 1;
  min-width: 0;
  font-size: 12.5px;
  color: var(--text-strong);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.bell-menu-foot {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 9px 11px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--text-strong);
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  box-sizing: border-box;
  transition: background 0.15s, color 0.15s;
}

.bell-menu-foot i {
  width: 16px;
  text-align: center;
}

.bell-menu-foot:hover {
  background: color-mix(in srgb, var(--primary) 10%, transparent);
  color: var(--primary);
}

.top-avatar-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
}

.avatar-img {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  object-fit: cover;
  display: block;
  cursor: pointer;
  flex-shrink: 0;
}

.admin-gear {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  margin-left: 8px;
  color: var(--text-sub);
  border: 0;
  background: transparent;
  text-decoration: none;
  font-size: 18px;
  cursor: pointer;
  transition: color 0.2s;
}

.admin-gear:hover {
  color: var(--primary);
}

.admin-menu-wrap {
  position: relative;
  margin-left: 8px;
}

.admin-menu {
  position: absolute;
  top: calc(100% + 10px);
  right: 0;
  min-width: 142px;
  padding: 6px;
  background: var(--surface-plain);
  border: 1px solid #e6ebf2;
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(31, 41, 55, 0.14);
  z-index: 210;
}

.admin-menu-item {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 9px 11px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--text-strong);
  font: inherit;
  font-size: 13px;
  text-align: left;
  text-decoration: none;
  cursor: pointer;
  box-sizing: border-box;
}

.admin-menu-item:hover {
  background: color-mix(in srgb, var(--primary) 10%, transparent);
  color: var(--primary);
}

.admin-menu-item i {
  width: 16px;
  text-align: center;
}

@media (max-width: 900px) {
  .topbar {
    flex-wrap: wrap;
    row-gap: 4px;
  }
}

@media (max-width: 600px) {
  .topbar {
    padding: 10px 16px;
    flex-wrap: wrap;
    gap: 8px;
  }

  .logo {
    font-size: 1.2rem;
  }

  .auth-btn {
    padding: 4px 14px;
    font-size: 12px;
  }
}

@media (max-width: 400px) {
  .auth-btn {
    padding: 4px 10px;
    font-size: 11px;
  }
}
</style>