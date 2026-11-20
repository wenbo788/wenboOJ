<script setup lang="ts">
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useNlnocStore } from '@/stores/nlnoc'
import { canManageCommunity } from '@/utils/permissions'
import { withBase } from '@/utils/base'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const nlnoc = useNlnocStore()

// 是否为管理员/具备用户管理权限（工单「我负责的」「待认领」仅对其可见）
const isStaff = computed(() => canManageCommunity(authStore.currentUser))

// 当前激活的导航项
const activePath = ref(route.path)

// 监听路由变化（自动收起移动端抽屉）
watch(() => route.path, (newPath) => {
  activePath.value = newPath
  mobileMenuOpen.value = false
})

// 判断是否激活
const isActive = (path: string) => {
  // 精确匹配：主页、陶片放逐（避免 /judgement/admins 误高亮 /judgement）
  if (path === '/' || path === '/judgement') {
    return activePath.value === path
  }
  return activePath.value.startsWith(path)
}

// 移动端抽屉菜单展开状态（桌面端不受影响：恒为收起态，靠 hover 展开）
const mobileMenuOpen = ref(false)

// 移动端菜单开关：与 NLNOC 私信面板互斥
const toggleMobileMenu = () => {
  mobileMenuOpen.value = !mobileMenuOpen.value
  if (mobileMenuOpen.value) {
    nlnoc.close()
  }
}

const closeMobileMenu = () => {
  mobileMenuOpen.value = false
}

// 打开私信面板时自动收起移动端悬浮菜单
const onNlnocOpened = () => {
  mobileMenuOpen.value = false
}

// 监听 ESC 键关闭抽屉
const onKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Escape' && mobileMenuOpen.value) {
    mobileMenuOpen.value = false
  }
}

onMounted(() => {
  window.addEventListener('mobile-sidebar:toggle', toggleMobileMenu)
  window.addEventListener('mobile-sidebar:close', closeMobileMenu)
  window.addEventListener('nlnoc:opened', onNlnocOpened)
  document.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('mobile-sidebar:toggle', toggleMobileMenu)
  window.removeEventListener('mobile-sidebar:close', closeMobileMenu)
  window.removeEventListener('nlnoc:opened', onNlnocOpened)
  document.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})

// 抽屉展开时禁止底层背景滚动
watch(mobileMenuOpen, (isOpen) => {
  if (typeof window !== 'undefined' && window.innerWidth <= 768) {
    document.body.style.overflow = isOpen ? 'hidden' : ''
  }
})

// 导航到指定路径
const navigateTo = (path: string) => {
  // 移动端点完自动收起，避免菜单一直占着屏幕
  mobileMenuOpen.value = false
  router.push(path)
}

// 鼠标移出侧边栏时自动滚回顶部（与原站一致，仅桌面端宽侧交互）
const sidebarRef = ref<HTMLElement | null>(null)
const onSidebarLeave = () => {
  if (window.innerWidth > 900 && sidebarRef.value) {
    sidebarRef.value.scrollTop = 0
  }
}
</script>

<template>
  <!-- 移动端抽屉遮罩背景 -->
  <Transition name="drawer-fade">
    <div
      v-if="mobileMenuOpen"
      class="drawer-backdrop"
      aria-hidden="true"
      @click="closeMobileMenu"
    ></div>
  </Transition>

  <div
    ref="sidebarRef"
    class="nav-sidebar"
    :class="{ 'nav-sidebar--open': mobileMenuOpen }"
    @mouseleave="onSidebarLeave"
  >
    <!-- 移动端抽屉顶栏（品牌名与关闭按钮，桌面端隐藏） -->
    <div class="drawer-header">
      <div class="drawer-brand">
        <img :src="withBase('favicon.svg')" width="22" height="22" alt="NLNOJ" />
        <span>NLNOJ</span>
      </div>
      <button
        type="button"
        class="drawer-close-btn"
        aria-label="关闭导航菜单"
        title="关闭导航菜单"
        @click="closeMobileMenu"
      >
        <i class="fa-solid fa-xmark"></i>
      </button>
    </div>

    <!-- 主菜单 第一部分（主页 ~ 评测记录） -->
    <div class="nav-group">
      <ul>
        <li>
          <a
            class="nav-item"
            :class="{ 'active': isActive('/') }"
            :href="withBase('/')"
            @click.prevent="navigateTo('/')"
          >
            <span class="nav-icon">
              <i class="fa-solid fa-house"></i>
            </span>
            <span class="nav-text">主页</span>
          </a>
        </li>
        
        <li>
          <a
            class="nav-item"
            :class="{ 'active': isActive('/training') }"
            :href="withBase('/training')"
            @click.prevent="navigateTo('/training')"
          >
            <span class="nav-icon">
              <i class="fa-solid fa-clipboard-list"></i>
            </span>
            <span class="nav-text">训练题单</span>
          </a>
        </li>
        <li>
          <a
            class="nav-item"
            :class="{ 'active': isActive('/contests') }"
            :href="withBase('/contests')"
            @click.prevent="navigateTo('/contests')"
          >
            <span class="nav-icon">
              <i class="fa-solid fa-chart-column"></i>
            </span>
            <span class="nav-text">比赛</span>
          </a>
        </li>
        <li>
          <a
            class="nav-item"
            :class="{ 'active': isActive('/arena') }"
            :href="withBase('/arena')"
            @click.prevent="navigateTo('/arena')"
          >
            <span class="nav-icon">
              <i class="fa-solid fa-gamepad"></i>
            </span>
            <span class="nav-text">对战</span>
          </a>
        </li>
        <li>
          <a
            class="nav-item"
            :class="{ 'active': isActive('/problems') }"
            :href="withBase('/problems')"
            @click.prevent="navigateTo('/problems')"
          >
            <span class="nav-icon">
                <i class="fa-solid fa-book"></i>
            </span>
            <span class="nav-text">题库</span>
          </a>
        </li>
        <li>
          <a
            class="nav-item"
            :class="{ 'active': isActive('/submissions') }"
            :href="withBase('/submissions')"
            @click.prevent="navigateTo('/submissions')"
          >
            <span class="nav-icon">
              <i class="fa-solid fa-chart-pie"></i>
            </span>
            <span class="nav-text">评测记录</span>
          </a>
        </li>
      </ul>
    </div>


    <!-- 主菜单 第二部分（讨论区、文章广场） -->
    <div class="nav-group">
      <ul>
        <li v-if="authStore.isAuthenticated">
          <a
            class="nav-item"
            :class="{ 'active': isActive('/discuss') }"
            :href="withBase('/discuss')"
            @click.prevent="navigateTo('/discuss')"
          >
            <span class="nav-icon">
              <i class="fa-solid fa-comments"></i>
            </span>
            <span class="nav-text">讨论区</span>
          </a>
        </li>
        <li v-if="authStore.isAuthenticated">
          <a
            class="nav-item"
            :class="{ 'active': isActive('/polls') }"
            :href="withBase('/polls')"
            @click.prevent="navigateTo('/polls')"
          >
            <span class="nav-icon">
              <i class="fa-solid fa-square-poll-vertical"></i>
            </span>
            <span class="nav-text">站内投票</span>
          </a>
        </li>
        <li>
          <a
            class="nav-item"
            :class="{ 'active': isActive('/articles') }"
            :href="withBase('/articles')"
            @click.prevent="navigateTo('/articles')"
          >
            <span class="nav-icon">
              <i class="fa-solid fa-newspaper"></i>
            </span>
            <span class="nav-text">文章广场</span>
          </a>
        </li>
        <li v-if="authStore.isAuthenticated">
          <a
            class="nav-item"
            :class="{ 'active': isActive('/teams') }"
            :href="withBase('/teams')"
            @click.prevent="navigateTo('/teams')"
          >
            <span class="nav-icon">
              <i class="fa-solid fa-people-group"></i>
            </span>
            <span class="nav-text">团队</span>
          </a>
        </li>
      </ul>
    </div>


    <!-- 更多功能（桌面端收缩时隐藏，展开后显示） -->
    <div class="nav-group nav-group--extra">
      <span class="group-title">
        <span class="nav-icon">
          <i class="fa-solid fa-toolbox"></i>
        </span>
        <span class="nav-text">更多功能</span>
      </span>
      <ul>
        <li>
          <a
            class="nav-item"
            :class="{ 'active': isActive('/shop') }"
            :href="withBase('/shop')"
            @click.prevent="navigateTo('/shop')"
          >
            <span class="nav-icon">
                <i class="fa-solid fa-store"></i>
            </span>
            <span class="nav-text">经验商店</span>
          </a>
        </li>
        <li>
          <a
            class="nav-item"
            :class="{ 'active': isActive('/image') }"
            :href="withBase('/image')"
            @click.prevent="navigateTo('/image')"
          >
            <span class="nav-icon">
                <i class="fa-solid fa-cloud-arrow-up"></i>
            </span>
            <span class="nav-text">图片上传</span>
          </a>
        </li>
        <li>
          <a
            class="nav-item"
            :class="{ 'active': isActive('/clipboard') }"
            :href="withBase('/clipboard')"
            @click.prevent="navigateTo('/clipboard')"
          >
            <span class="nav-icon">
                <i class="fa-solid fa-clipboard"></i>
            </span>
            <span class="nav-text">云剪贴板</span>
          </a>
        </li>
        <li>
          <a
            class="nav-item"
            :class="{ 'active': isActive('/themes') }"
            :href="withBase('/themes')"
            @click.prevent="navigateTo('/themes')"
          >
            <span class="nav-icon">
                <i class="fa-solid fa-brush"></i>
            </span>
            <span class="nav-text">主题商店</span>
          </a>
        </li>
        <li>
          <a
            class="nav-item"
            :class="{ 'active': isActive('/ranking') }"
            :href="withBase('/ranking')"
            @click.prevent="navigateTo('/ranking')"
          >
            <span class="nav-icon">
                <i class="fa-solid fa-flag-checkered"></i>
            </span>
            <span class="nav-text">排行榜</span>
          </a>
        </li>
      </ul>
    </div>


    <!-- 相关链接（桌面端收缩时隐藏，展开后显示） -->
    <div class="nav-group nav-group--extra">
      <span class="group-title">
        <span class="nav-icon">
          <i class="fa-solid fa-link"></i>
        </span>
        <span class="nav-text">相关链接</span>
      </span>
      <ul>
        <li>
          <a
            class="nav-item"
            :class="{ 'active': isActive('/help') }"
            :href="withBase('/help')"
            @click.prevent="navigateTo('/help')"
          >
            <span class="nav-icon">
                <i class="fa-solid fa-circle-question"></i>
            </span>
            <span class="nav-text">帮助中心</span>
          </a>
        </li>
        <li>
          <a
            class="nav-item"
            href="https://www.luogu.com.cn/team/136441"
            target="_blank"
            rel="noopener noreferrer"
            @click="closeMobileMenu"
          >
            <span class="nav-icon">
                <i class="fa-solid fa-envelope"></i>
            </span>
            <span class="nav-text">联系我们</span>
          </a>
        </li>
        <li>
          <a
            class="nav-item"
            :class="{ 'active': isActive('/rules') }"
            :href="withBase('/rules')"
            @click.prevent="navigateTo('/rules')"
          >
            <span class="nav-icon">
                <i class="fa-solid fa-scroll"></i>
            </span>
            <span class="nav-text">社区规则</span>
          </a>
        </li>
        <li>
          <a
            class="nav-item"
            :class="{ 'active': isActive('/judgement') }"
            :href="withBase('/judgement')"
            @click.prevent="navigateTo('/judgement')"
          >
            <span class="nav-icon">
                <i class="fa-solid fa-scale-balanced"></i>
            </span>
            <span class="nav-text">陶片放逐</span>
          </a>
        </li>
        <li>
          <a
            class="nav-item"
            :class="{ 'active': isActive('/judgement/admins') }"
            :href="withBase('/judgement/admins')"
            @click.prevent="navigateTo('/judgement/admins')"
          >
            <span class="nav-icon">
                <i class="fa-solid fa-user"></i>
            </span>
            <span class="nav-text">管理名单</span>
          </a>
        </li>
        <li v-if="authStore.currentUser">
          <a
            class="nav-item"
            :class="{ 'active': isActive('/tickets') }"
            :href="withBase('/tickets')"
            @click.prevent="navigateTo('/tickets')"
          >
            <span class="nav-icon">
                <i class="fa-solid fa-ticket"></i>
            </span>
            <span class="nav-text">工单/反馈</span>
          </a>
        </li>
        <li v-if="isStaff">
          <a
            class="nav-item"
            :class="{ 'active': isActive('/tickets/assigned') }"
            :href="withBase('/tickets/assigned')"
            @click.prevent="navigateTo('/tickets/assigned')"
          >
            <span class="nav-icon">
                <i class="fa-solid fa-check"></i>
            </span>
            <span class="nav-text">我负责的</span>
          </a>
        </li>
        <li v-if="isStaff">
          <a
            class="nav-item"
            :class="{ 'active': isActive('/tickets/unassigned') }"
            :href="withBase('/tickets/unassigned')"
            @click.prevent="navigateTo('/tickets/unassigned')"
          >
            <span class="nav-icon">
                <i class="fa-solid fa-inbox"></i>
            </span>
            <span class="nav-text">待认领</span>
          </a>
        </li>
        <li>
          <a
            class="nav-item"
            href="https://www.luogu.com.cn/team/136441"
            target="_blank"
            rel="noopener noreferrer"
            @click="closeMobileMenu"
          >
            <span class="nav-icon">
                <i class="fa-solid fa-circle-info"></i>
            </span>
            <span class="nav-text">关于我们</span>
          </a>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
/* 侧边栏 */
.nav-sidebar {
  position: fixed;
  top: 80px;
  left: 0;
  height: calc(100vh - 120px);
  width: 62px;
  background: var(--surface-strong);
  -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: 16px 0;
  transition: width 0.3s ease;
  overflow-y: auto;
  overflow-x: hidden;
  white-space: nowrap;
  z-index: 150;
  margin: 10px;
}

.nav-sidebar::-webkit-scrollbar {
  width: 4px;
}

.nav-sidebar::-webkit-scrollbar-track {
  background: transparent;
}

.nav-sidebar::-webkit-scrollbar-thumb {
  background: #ccc;
  border-radius: 4px;
}

.nav-sidebar::-webkit-scrollbar-thumb:hover {
  background: #aaa;
}

/* ===== 深色主题 =====
   scoped 样式特异性带 data-v 属性，全局的 html[data-theme=dark] 规则
   压不过这里，所以在组件内补：侧栏滚动条 thumb 与分组标题的磨砂纱
   都跟暗色走（白纱在深色面板上会变成一条亮杠）。 */
html[data-theme="dark"] .nav-sidebar::-webkit-scrollbar-thumb {
  background: #4b515d;
}
html[data-theme="dark"] .nav-sidebar::-webkit-scrollbar-thumb:hover {
  background: #5b626f;
}
html[data-theme="dark"] .group-title {
  background: rgba(0, 0, 0, 0.22);
}

.nav-sidebar:hover {
  width: 260px;
}

/* 导航组 */
.nav-group {
  margin-bottom: 0;
}

.nav-group ul {
  list-style: none;
  padding: 0;
  margin: 0;
}

/* 分组标题：灰底小字分隔条。
   注意：原来这里 + 下面共享块 + 再下面的重复块共三处定义互相覆盖，
   12px/#9ca3af 的设计意图被导航项规则改成 14px 深色、margin 8px 被
   hover 规则拉回 5px 产生抖动 —— 收敛为单处定义，间距与导航项统一。
   min-height 28 = 图标高：展开态组图标 width→0 后行高仍锁定 42，
   收展时组标题不跳高（content-box：28 + 上下 padding 14 = 42） */
.group-title {
  display: flex;
  align-items: center;
  padding: 7px 16px;
  margin: 5px;
  min-height: 28px;
  font-size: 12px;
  font-weight: 600;
  color: #9ca3af;
  cursor: default;
  white-space: nowrap;
  /* 分割小标题：原来的 #f9fafb 是实心色，磨砂面板在这条下面被糊住了 */
  background: rgba(255, 255, 255, 0.55);
  border-radius: 13px;
  /* 展开态组标题 gap 0→8 需要跟随过渡，否则收展瞬间文字位置跳动 */
  transition: gap 0.25s ease;
}

@media (min-width: 769px) {
  /* 桌面端收缩态（未 hover）：只保留「更多功能」以上的按钮，
     「更多功能」「相关链接」整组隐藏，展开后才淡入出现 */
  .nav-group--extra {
    transition: opacity 0.2s ease;
  }
  .nav-sidebar:not(:hover) .nav-group--extra {
    display: none;
    opacity: 0;
  }
  .nav-sidebar:hover .nav-group--extra {
    opacity: 1;
  }

  /* 折叠态：文字退出布局 —— opacity:0 仍占位会把图标挤偏（图标
     中心右移数像素），display:none 后配合 justify-content 真正居中 */
  .nav-sidebar:not(:hover) .nav-text {
    display: none;
  }
  .nav-sidebar:not(:hover) .nav-item,
  .nav-sidebar:not(:hover) .group-title {
    justify-content: center;
  }
  .nav-sidebar:not(:hover) .nav-icon {
    margin-right: 0;
  }

  /* 折叠态只剩图标宽度，整行窄条背景又挤又难看 → hover/active 反馈
     画在图标圆上；颜色严格沿用展开态原配色（灰 0.16 / 蓝 0.1 + 主色
     图标），只换形状不动色，无投影无实底 */
  .nav-sidebar:not(:hover) .nav-item:hover {
    background: transparent;
  }
  .nav-sidebar:not(:hover) .nav-item:hover .nav-icon {
    background: rgba(148, 163, 184, 0.16);
  }
  .nav-sidebar:not(:hover) .nav-item.active {
    background: transparent;
  }
  .nav-sidebar:not(:hover) .nav-item.active .nav-icon {
    background: color-mix(in srgb, var(--primary) 10%, transparent);
  }
  /* active hover 加深一档，与展开态 .nav-item.active:hover 同色 */
  .nav-sidebar:not(:hover) .nav-item.active:hover .nav-icon {
    background: color-mix(in srgb, var(--primary) 16%, transparent);
  }
}

/* 展开态：组图标收起（width+opacity 过渡，比 display:none 瞬变更平滑），
   文字显示规则统一走下方 .nav-sidebar:hover .nav-text */
.nav-sidebar:hover .group-title .nav-icon {
  width: 0;
  margin: 0;
  opacity: 0;
  overflow: hidden;
}

/* 展开态：文字两侧细线淡入（基础态是 opacity:0 占位，见下） */
@media (min-width: 769px) {
  .nav-sidebar:hover .group-title {
    gap: 8px;
  }
  .nav-sidebar:hover .group-title::before,
  .nav-sidebar:hover .group-title::after {
    opacity: 1;
  }
}

/* 组标题左右细线：默认透明占位 —— 折叠态 62px 里若细线可见，
   会把图标挤得左右不对称；展开才淡入 */
.group-title::before,
.group-title::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border-color);
  opacity: 0;
  transition: opacity 0.2s ease;
}



/* 导航项（padding 7px 配合 28px 图标容器：行高 14+28=42，与改造前
   10px padding + ~20px 图标基本一致，密度不变） */
.nav-item {
  padding: 7px 16px;
  margin: 5px;
  font-size: 14px;
  color: var(--text-strong);
  cursor: pointer;
  transition: background 0.2s, color 0.2s;
  display: flex;
  align-items: center;
  text-decoration: none;
  border-radius: 15px;
}

/* 悬停反馈只给可点击的导航项：组标题不可点（cursor: default），此前
   被一并命中会出现「hover 变灰盖掉白底 + margin 8→5 跳动」两个毛病 */
.nav-item:hover {
  background: rgba(148, 163, 184, 0.16);
  color: var(--primary);
  text-decoration: none;
}

.nav-item.active {
  background: color-mix(in srgb, var(--primary) 10%, transparent);
  color: var(--primary);
}

/* active 项 hover 加深一档 —— 此前 hover 规则写在 active 前面、同特异性
   被 active 压住，鼠标扫过选中项毫无反应 */
.nav-item.active:hover {
  background: color-mix(in srgb, var(--primary) 16%, transparent);
}

/* 图标容器：28×28 flex 居中 —— 折叠态 hover/active 的圆形高亮直接画在
   这里（28 圆托 20 图标，每边 4px 内边距，紧凑不臃肿）；
   border-radius 50% 与 transition(all .25s) 让组图标收起
   （28↔0，见上方 :hover 规则）在收展过渡里平滑。字号定 20px，
   图标 inherit 跟随容器（此前 i 固定 20px，移动端容器字号 16/14
   被无视导致图标溢出容器） */
.nav-icon {
  width: 28px;
  height: 28px;
  font-size: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-right: 12px;
  border-radius: 50%;
  transition: all 0.25s ease;
}

/* 统一走 FontAwesome 字体图标（与全站 <i class="fa-solid fa-*"> 口径一致）；
   fa-solid 自带 inline-block + line-height:1 */
.nav-icon i {
  font-size: inherit;
  line-height: 1;
}

.group-title:first-of-type {
  border-top: none;
  margin-top: 0;
}

/* 导航文字：折叠态在桌面 media 里 display:none 退出布局，
   展开态 display 恢复 + opacity 淡入 */
.nav-text {
  opacity: 0;
  transition: opacity 0.2s ease;
}

.nav-sidebar:hover .nav-text {
  display: block;
  opacity: 1;
}

/* 分割线 */
.divider {
  height: 1px;
  background: var(--border-color);
  margin: 8px 0;
}

/* ===== 抽屉遮罩层与抽屉顶栏（桌面端隐藏） ===== */
.drawer-backdrop {
  display: none;
}

.drawer-header {
  display: none;
}

/* ===== 移动端抽屉式导航（≤768px） ===== */
@media (max-width: 768px) {
  /* 遮罩背景：半透明黑色毛玻璃 */
  .drawer-backdrop {
    display: block;
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.45);
    -webkit-backdrop-filter: blur(2px);
    backdrop-filter: blur(2px);
    z-index: 390;
  }

  .drawer-fade-enter-active,
  .drawer-fade-leave-active {
    transition: opacity 0.24s ease;
  }

  .drawer-fade-enter-from,
  .drawer-fade-leave-to {
    opacity: 0;
  }

  /* 侧边栏转为左侧滑出式抽屉 */
  .nav-sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    width: min(290px, 82vw);
    height: 100vh;
    height: 100dvh;
    margin: 0;
    border-radius: 0 16px 16px 0;
    border-left: none;
    border-top: none;
    border-bottom: none;
    border-right: var(--border-width) solid var(--border-color);
    padding: 0 0 calc(24px + env(safe-area-inset-bottom, 0px));
    background: var(--surface-strong);
    -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
    backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
    box-shadow: 4px 0 28px rgba(0, 0, 0, 0.22);
    overflow-y: auto;
    overscroll-behavior: contain;
    z-index: 400;
    transform: translateX(-100%);
    visibility: hidden;
    transition: transform 0.28s cubic-bezier(0.4, 0, 0.2, 1), visibility 0.28s;
    white-space: normal;
  }

  .nav-sidebar.nav-sidebar--open {
    transform: translateX(0);
    visibility: visible;
  }

  .nav-sidebar:hover {
    width: min(290px, 82vw);
    box-shadow: 4px 0 28px rgba(0, 0, 0, 0.22);
  }

  .nav-sidebar::-webkit-scrollbar {
    width: 3px;
  }

  /* 抽屉顶部标题与关闭按钮 */
  .drawer-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 18px;
    border-bottom: 1px solid var(--border-color, rgba(148, 163, 184, 0.2));
    margin-bottom: 8px;
    position: sticky;
    top: 0;
    background: var(--surface-strong);
    z-index: 10;
    -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
    backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  }

  .drawer-brand {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 16px;
    font-weight: 700;
    color: var(--primary);
  }

  .drawer-close-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    background: transparent;
    border: none;
    border-radius: var(--radius-sm, 6px);
    color: var(--text-sub, #64748b);
    font-size: 18px;
    cursor: pointer;
    transition: background-color 0.18s, color 0.18s;
    padding: 0;
    -webkit-tap-highlight-color: transparent;
  }

  .drawer-close-btn:hover,
  .drawer-close-btn:active {
    background: var(--bg-subtle, rgba(0, 0, 0, 0.06));
    color: var(--text-strong, #1e293b);
  }

  /* 抽屉导航项：清晰单列纵向排布 */
  .nav-text {
    display: block !important;
    opacity: 1 !important;
  }

  .nav-group {
    margin-bottom: 4px;
  }

  .nav-group--extra {
    display: block !important;
    opacity: 1 !important;
  }

  .nav-group ul {
    display: flex;
    flex-direction: column;
    padding: 0 10px;
    gap: 2px;
  }

  .nav-item {
    display: flex;
    align-items: center;
    flex-direction: row;
    padding: 10px 14px;
    margin: 2px 0;
    font-size: 14px;
    border-radius: 12px;
    text-align: left;
    gap: 12px;
  }

  .nav-icon {
    font-size: 16px;
    width: 24px;
    height: 24px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    margin-right: 0;
    flex-shrink: 0;
  }

  .group-title {
    display: flex;
    align-items: center;
    padding: 10px 14px 4px;
    font-size: 12px;
    font-weight: 600;
    color: var(--text-muted, #94a3b8);
    background: transparent;
    border-radius: 0;
    margin-top: 6px;
    gap: 8px;
    min-height: 0;
  }

  .group-title::before,
  .group-title::after {
    opacity: 0.5;
  }

  .group-title .nav-text {
    display: block !important;
  }

  .group-title .nav-icon {
    display: none;
  }

  .divider {
    display: block;
    margin: 8px 12px;
    opacity: 0.5;
  }
}
</style>