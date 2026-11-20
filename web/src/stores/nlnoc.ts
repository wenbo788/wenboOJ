import { defineStore } from 'pinia'
import { ref } from 'vue'
import apiClient from '@/api/client'

/**
 * NLNOC 会话/搜索结果里的用户摘要（与后端 app.api.messages.user_brief 同形）。
 * 字段足够画出列表行、聊天页头部，并复算全站统一的用户名配色。
 */
export interface NLNOCUser {
  id: number
  username: string
  user_number: number
  avatar_url?: string | null
  is_admin?: boolean
  is_super_admin?: boolean
  is_banned?: boolean
  is_cheater?: boolean
  can_manage_users?: boolean
  can_manage_posts?: boolean
  can_manage_problems?: boolean
  username_color?: string | null
  name_color?: string | null
  user_tag?: string | null
  last_seen?: string | null
}

/**
 * NLNOC 私信的全局状态。
 *
 * 面板本体挂在 TopBar（顶栏常驻，跨路由不卸载），但入口有两个：
 *   1. 顶栏信封 —— toggle 开合；
 *   2. 用户主页「发消息」—— startChat 直接开面板并跳进与该用户的聊天。
 * 因此开关状态必须提升到 store，而不能各自 local。
 */
export const useNlnocStore = defineStore('nlnoc', () => {
  /** 面板开合 */
  const open = ref(false)
  /** 顶栏信封角标（未读私信总数） */
  const unread = ref(0)
  /** 用户主页「发消息」写入：面板挂载后直接进入与该用户的聊天 */
  const pendingPeer = ref<NLNOCUser | null>(null)
  /** 当前正在对话的对方（NLNOCChat 挂载期间设置；角标刷新时排除他发来的未读） */
  const activePeerId = ref<number | null>(null)

  function emitOpened() {
    // 与移动端悬浮菜单互斥：打开私信时通知 SideBar 收起菜单
    window.dispatchEvent(new Event('nlnoc:opened'))
  }

  function toggle() {
    open.value = !open.value
    if (open.value) emitOpened()
    else pendingPeer.value = null
  }

  function close() {
    open.value = false
    pendingPeer.value = null
  }

  /** 用户主页「发消息」：开面板并直接进入与该用户的聊天 */
  function startChat(user: NLNOCUser) {
    pendingPeer.value = user
    open.value = true
    emitOpened()
  }

  /**
   * 标记「正在与谁对话」：角标刷新时排除他发来的未读——
   * 正聊着的人发消息，手机图标不再亮通知点。
   */
  function setActivePeer(id: number | null) {
    if (activePeerId.value === id) return
    activePeerId.value = id
    void refreshUnread()
  }

  /** 顶栏信封角标刷新（登录后、15s 轮询、会话已读后都会调） */
  async function refreshUnread() {
    try {
      const data: any = await apiClient.get('/api/messages/unread-count', {
        params:
          activePeerId.value != null ? { exclude_peer_id: activePeerId.value } : undefined,
      })
      unread.value = data?.count || 0
    } catch {
      /* 未登录或网络抖动：保留旧值，等下一轮轮询兜底 */
    }
  }

  return {
    open,
    unread,
    pendingPeer,
    activePeerId,
    toggle,
    close,
    startChat,
    setActivePeer,
    refreshUnread,
  }
})
