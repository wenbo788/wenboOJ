<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from './stores/auth'
import * as session from './utils/session'
import { codeFontCss } from './constants/codeFonts'
import { withBase } from './utils/base'
import TopBar from './components/TopBar.vue'
import SideBar from './components/SideBar.vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const isNavigating = ref(false)
/** 空壳模式：后端尚未接入时由构建环境变量打开，仅用于提示 */
const shellMode = import.meta.env.VITE_SHELL_MODE === '1'
const DEFAULT_PAGE_TITLE = 'NLNOJ - 新一代社交型 Online Judge 平台'
const routeTitleMap: Record<string, string> = {
  Home: '首页',
  Login: '登录',
  Register: '注册',
  ForgotPassword: '找回密码',
  ResetPassword: '重设密码',
  Profile: '我的主页',
  Preferences: '偏好设置',
  UserDetail: '用户主页',
  Notifications: '消息通知',
  Admin: '管理后台',
  AdminAwardCert: '奖项认证审核',
  SiteAdmin: '站点管理',
  Judgement: '陶片放逐',
  Discuss: '讨论区',
  DiscussNew: '发帖',
  TeamList: '团队',
  Tickets: '工单',
  ProblemList: '题库',
  ProblemDetail: '题目详情',
  SubmissionList: '提交记录',
  ContestList: '比赛'
}

const resolvePageTitle = () => {
  const explicit = typeof route.meta.title === 'string' ? route.meta.title.trim() : ''
  const fallback = routeTitleMap[String(route.name)] || String(route.name || '首页')
  const title = String(explicit || fallback)
  return `${title} - ${DEFAULT_PAGE_TITLE}`
}

router.beforeEach(() => {
  isNavigating.value = true
})
router.afterEach(() => {
  isNavigating.value = false
})
router.onError(() => {
  isNavigating.value = false
})

// 判断是否显示导航栏
const showNav = computed(() => {
  // 沉浸做题页：全站导航隐藏，专注做题
  if (route.name === 'ProblemImmersive') return false
  // 登录注册页面不显示导航栏
  return !['Login', 'Register'].includes(route.name as string)
})

// 沉浸做题页：内容区去掉外层留白与登录页居中规则，整页撑满视口
const isImmersive = computed(() => route.name === 'ProblemImmersive')

// 判断是否显示侧边栏
const showSidebar = computed(() => {
  return showNav.value
})

// 监听路由变化，恢复认证状态
// 用户资料的补拉交给路由守卫统一处理，这里不再重复请求 /auth/me
watch(() => route.path, () => {
  document.title = resolvePageTitle()

  if (!authStore.accessToken && session.hasSession()) {
    authStore.restoreState()
  }
}, { immediate: true })

const handleLogout = async () => {
  await authStore.logout()
  router.push('/login')
}

// ===== 用户主题背景（主题商店设置，只影响自己的浏览效果） =====
// 与 ThemeShop.vue / 后端 _ALLOWED_THEME_PRESETS 保持同一组 key
const PRESET_GRADIENTS: Record<string, string> = {
  dawn: 'linear-gradient(135deg, #ffd8a8 0%, #ff9db8 50%, #a8c8ff 100%)',
  ocean: 'linear-gradient(160deg, #0f3057 0%, #00587a 55%, #008891 100%)',
  dusk: 'linear-gradient(160deg, #2b1b4d 0%, #7a3b8f 55%, #ff7e5f 100%)',
  sakura: 'linear-gradient(150deg, #ffe3ec 0%, #ffc7de 55%, #ffd8b1 100%)',
}
const themeStyle = computed(() => {
  const me = authStore.currentUser
  if (!me?.theme_enabled || !me.theme_background) return undefined
  const bg = me.theme_background
  if (bg.startsWith('preset:')) {
    const css = PRESET_GRADIENTS[bg.split(':')[1]]
    if (!css) return undefined
    return { backgroundImage: css }
  }
  return {
    backgroundImage: `url(${bg})`,
    backgroundSize: 'cover',
    backgroundPosition: 'center',
  }
})
// 主题启用时挂 theme-on：给主题模式留的样式开关。
// 悬停提亮（0.62 → 0.94）因前后透明度跳变太大已移除，卡片悬停与一般状态无差别。
const themeOn = computed(() => !!themeStyle.value)

// ===== 色相调整（主题商店「色相调整」滑块存的 theme_hue，-180..180）=====
// 写入 --hue-shift 后，style.css 里所有 calc(基准色相 + var(--hue-shift))
// 自动重算：主题色、初始背景光斑、装饰渐变；顶栏 Logo 的 <img> 内 svg
// 吃不到 CSS 变量，走下方全局 filter: hue-rotate 跟同一变量。
// 登出/换账号时 currentUser 清空 → 回 0（默认配色）。
watch(
  () => authStore.currentUser?.theme_hue,
  (hue) => {
    document.documentElement.style.setProperty('--hue-shift', String(hue ?? 0))
  },
  { immediate: true },
)

// ===== 等宽字体（偏好设置的 code_font → 编辑器与 code/pre 共用的 --font-mono）=====
// Preferences 页点选字体时会先写同值做即时预览、保存成功后 store 属性变化
// 再由这里落定，两边写的是同一个 fontFamily 值，重复写幂等。
// 登出/换账号 → code_font 变 null → 回默认（style.css 里 --font-mono 的定义）。
watch(
  () => authStore.currentUser?.code_font,
  (fontKey) => {
    document.documentElement.style.setProperty('--font-mono', codeFontCss(fontKey))
  },
  { immediate: true },
)

// ===== 深色主题（主题商店「深色主题」开关存的 theme_mode）=====
// 挂到 <html> 上的 data-theme 属性，style.css 里 html[data-theme="dark"]
// 整块翻转设计令牌（组件里凡是 var() 的地方零改动跟随）。
// undefined（登出/未登录）不动属性：保留 localStorage 的设备记忆，
// 未登录进站也按上次选择渲染；换账号登录后按新账号的值立即切换。
watch(
  () => authStore.currentUser?.theme_mode,
  (mode) => {
    if (mode === 'dark') {
      document.documentElement.dataset.theme = 'dark'
      localStorage.setItem('nlnoj-theme-mode', 'dark')
    } else if (mode === 'light') {
      delete document.documentElement.dataset.theme
      localStorage.setItem('nlnoj-theme-mode', 'light')
    }
  },
  { immediate: true },
)
</script>

<template>
  <div id="app" :class="{ 'theme-on': themeOn }">
    <div class="app-background" :style="themeStyle" aria-hidden="true"></div>
    <div class="route-loading-bar" :class="{ active: isNavigating }" aria-hidden="true"></div>
    <!-- 空壳模式提示：后端 API 未接入时避免访客误以为站点坏了 -->
    <div v-if="shellMode" class="shell-banner" role="status">
      演示模式：后端 API 尚未接入，登录、题目与评测暂不可用
    </div>
    <!-- 顶部导航栏 -->
    <TopBar v-if="showNav" />

    <!-- 侧边导航栏 -->
    <SideBar v-if="showSidebar" />

    <!-- 主内容区域 -->
    <main :class="['main-content', { 'with-sidebar': showSidebar, 'is-immersive': isImmersive }]">
      <router-view v-slot="{ Component, route }">
        <Transition name="route" mode="out-in">
          <Suspense timeout="0">
            <component :is="Component" :key="route.fullPath" />
            <template #fallback>
              <div class="route-loading-screen" role="status" aria-live="polite">
                <span class="loading-spinner"></span>
                <span>页面加载中...</span>
              </div>
            </template>
          </Suspense>
        </Transition>
      </router-view>
    </main>

    <!-- 页脚 -->
    <footer v-if="showNav" class="page-footer">
      <div class="footer-content">
        <p class="footer-text">Copyright © 2026 NLNOJ Team</p>
        <p class="footer-text">
          <a href="http://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer">蜀ICP备2026036126号</a>
          | <a href="https://icp.gov.moe/?keyword=20262482" target="_blank" rel="noopener noreferrer">萌ICP备20262482号</a>
          | <!-- 公安联网备案：按公安部要求需展示徽标 + 备案号，并链接到官方查询页 -->
          <a
            class="beian-link"
            href="https://beian.mps.gov.cn/#/query/webSearch?code=51170002000138"
            target="_blank"
            rel="noopener noreferrer"
            title="公安联网备案查询"
          >
            <img class="beian-badge" :src="withBase('beian-badge.png')" alt="公安联网备案" width="16" height="17" />
            川公网安备51170002000138号
          </a>
        </p>
      </div>
    </footer>
  </div>
</template>

<style>
/* 全局样式重置 */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: inherit;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  background: var(--bg-page);
}

/* 顶栏/登录/注册页的 favicon Logo：svg 在 <img> 里是独立文档，
   吃不到 CSS 变量，用滤镜跟主题色相偏移同步旋转；
   svg 里的白色百分号是灰度色，hue-rotate 对其无影响。 */
img[src$="/favicon.svg"] {
  filter: hue-rotate(calc(var(--hue-shift) * 1deg));
}

/* 空壳模式提示条：固定在底部，避免挡住顶栏 */
.shell-banner {
  position: fixed;
  left: 50%;
  bottom: 16px;
  transform: translateX(-50%);
  z-index: 9999;
  max-width: calc(100vw - 32px);
  padding: 9px 16px;
  border-radius: 999px;
  background: rgba(17, 24, 39, 0.92);
  color: #fff;
  font-size: 13px;
  line-height: 1.4;
  text-align: center;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
  pointer-events: none;
}

/* 页面背景层：光斑/主题图独立成 fixed 图层。
   不用 background-attachment:fixed —— 那会让每帧滚动/重绘都全屏
   重采样（叠加全站 backdrop-filter 时点击切换主题肉眼可见地卡），
   独立图层只合成一次，卡片毛玻璃对它采样也快得多。 */
.app-background {
  position: fixed;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  background:
    radial-gradient(560px 420px at 12% 8%, var(--bg-page-glow-1), transparent 70%),
    radial-gradient(620px 460px at 88% 18%, var(--bg-page-glow-2), transparent 70%),
    radial-gradient(720px 520px at 50% 96%, var(--bg-page-glow-3), transparent 70%),
    var(--bg-page);
}

#app {
  min-height: 100vh;
}

.route-loading-bar {
  position: fixed;
  z-index: 3000;
  top: 0;
  left: 0;
  width: 100%;
  height: 3px;
  pointer-events: none;
  opacity: 0;
  background: linear-gradient(90deg, var(--primary), var(--accent), var(--primary));
  background-size: 200% 100%;
  transform: scaleX(0);
  transform-origin: left;
  transition: opacity 0.18s ease, transform 0.2s ease;
}

.route-loading-bar.active {
  opacity: 1;
  transform: scaleX(0.82);
  animation: loading-bar-sweep 1.15s ease-in-out infinite;
}

.route-loading-screen {
  min-height: calc(100vh - 180px);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--text-sub);
  font-size: 13px;
}

.loading-spinner {
  width: 18px;
  height: 18px;
  border: 2px solid #dce3f2;
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spinner-rotate 0.72s linear infinite;
}

@keyframes loading-bar-sweep {
  0% { background-position: 100% 0; transform: scaleX(0.2); }
  55% { transform: scaleX(0.78); }
  100% { background-position: -100% 0; transform: scaleX(0.94); }
}

@keyframes spinner-rotate {
  to { transform: rotate(360deg); }
}

button,
a,
input,
textarea,
select {
  transition: color 0.18s ease, background-color 0.18s ease, border-color 0.18s ease,
    box-shadow 0.18s ease, opacity 0.18s ease, transform 0.18s ease;
}

/* 链接样式 */
a {
  color: inherit;
  text-decoration: none;
}

a:hover {
  text-decoration: underline;
}

/* 按钮重置 */
button {
  font-family: inherit;
  font-size: inherit;
  line-height: inherit;
}

/* 输入框重置 */
input, textarea, select {
  font-family: inherit;
  font-size: inherit;
  line-height: inherit;
}

/* 滚动条样式 */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: var(--bg-subtle);
}

::-webkit-scrollbar-thumb {
  background: #c1c1c1;
  border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
  background: #a8a8a8;
}
</style>

<style scoped>
/* 主内容区域 */
.main-content {
  min-height: calc(100vh - 60px - 80px); /* 减去顶部导航和页脚高度 */
  padding: 20px;
  transition: all 0.3s ease;
}

/* 页面跳转过渡：淡入 + 轻微上浮回正，顺滑曲线（配合顶部加载条） */
.route-enter-active,
.route-leave-active {
  transition: opacity 0.28s cubic-bezier(0.22, 0.61, 0.36, 1),
    transform 0.28s cubic-bezier(0.22, 0.61, 0.36, 1);
}

.route-enter-from {
  opacity: 0;
  transform: translateY(14px) scale(0.992);
}

.route-leave-to {
  opacity: 0;
  transform: translateY(-8px) scale(0.996);
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    scroll-behavior: auto !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}

.main-content.with-sidebar {
  margin-left: 64px; /* 为侧边栏留出空间 */
  padding-top: 20px;
}

/* 桌面端适配 */
@media (min-width: 768px) {
  .main-content.with-sidebar {
    padding: 24px;
  }
}

/* 移动端适配 */
@media (max-width: 767px) {
  .main-content {
    padding: 16px;
  }

  .main-content.with-sidebar {
    margin-left: 0;
  }
}

/* 页脚 */
.page-footer {
  background: var(--surface);
  -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border-top: var(--border-width) solid var(--border-color);
  padding: 20px 24px;
  text-align: center;
  margin-top: 20px;
}

.footer-content {
  max-width: 1200px;
  margin: 0 auto;
}

.footer-text {
  color: var(--text-sub);
  font-size: 14px;
  margin: 4px 0;
}

/* 公安联网备案：徽标 62×67 原图，页脚里缩到 16×17 与文字对齐 */
.beian-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  vertical-align: middle;
}

.beian-badge {
  width: 16px;
  height: 17px;
  display: block;
  flex: none;
}

/* 响应式页脚 */
@media (max-width: 600px) {
  /* 手机端整页留白收紧。
     这里是「第一层」：各页面自己的 *-container / .card 还在下面叠加，
     三层加起来才是用户看到的留白，改一层不管另外两层等于白干。 */
  .main-content,
  .main-content.with-sidebar {
    padding: 12px;
  }

  .page-footer {
    padding: 16px;
  }

  .footer-text {
    font-size: 12px;
  }
}

/* 登录注册页面特殊处理 */
.main-content:not(.with-sidebar) {
  margin-left: 0;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 沉浸做题页：全屏铺满（必须在上面那条之后，特异性相同靠顺序取胜） */
.main-content.is-immersive {
  margin-left: 0;
  min-height: 100vh;
  padding: 0;
  display: block;
}
</style>
