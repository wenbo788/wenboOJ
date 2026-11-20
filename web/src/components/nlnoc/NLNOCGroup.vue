<script setup lang="ts">
/**
 * NLNOC 群聊会话页 —— 与私信同款手机 IM 体验（左收右发气泡、头像分组、
 * 组尾时间、右键/长按菜单、乐观发送），数据源换成群聊 API。
 *
 * 数据流：
 *   打开   GET /api/conversations/{id}（详情：群名/成员）+ .../messages（全量）
 *   轮询   每 5s 全量重拉（群聊接口无增量游标），在途/失败消息不覆盖
 *   发送   乐观插入（pending）→ 成功换真身 / 失败标红，点击气泡重填
 *   撤回   自己的消息、群管理可撤任何人的 → 右键/长按菜单
 *
 * 与私信页的差异：页头右上角是「群聊管理」入口；消息带发送者昵称
 * （群成员无头像字段，用字母头像）；无引用回复（群聊后端不支持）。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import apiClient from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { letterAvatar } from '@/utils/avatar'
import { renderRichText } from '@/utils/markdown'
import { userNameColor } from '@/utils/userColor'

const props = defineProps<{ conversationId: number }>()
const emit = defineEmits<{
  back: []
  /** 页头右上角「管理」：父级切到群聊管理视图 */
  manage: []
  /** 发送成功（已落库）：父级刷新会话列表最新预览 */
  sent: []
}>()

/** 被引用消息的快照（后端 list_messages 批量带出） */
interface ReplySnap {
  id: number
  sender_id: number | null
  sender_username: string
  content: string
  is_recalled: boolean
}

interface GMsg {
  id: number
  sender_id: number | null
  sender_username: string
  content: string
  created_at: string
  is_recalled?: boolean
  reply_to_id?: number | null
  reply_to?: ReplySnap | null
  pending?: boolean
  failed?: boolean
}

interface GMember {
  user_id: number
  username: string
  role: string
}

interface GDetail {
  id: number
  type: string
  title: string | null
  avatar_url?: string | null
  owner_id: number | null
  dissolved?: boolean
  member_count: number
  members: GMember[]
}

const authStore = useAuthStore()
const myId = computed(() => authStore.currentUser?.id ?? -1)

const detail = ref<GDetail | null>(null)
const msgs = ref<GMsg[]>([])
/** 本地消息变更序号：发送/重发/撤回时自增，用于让并发到达的全量轮询结果失效 */
let localSeq = 0
const loading = ref(true)
const loadError = ref('')
const input = ref('')
const sending = ref(false)
const sendError = ref('')
const listRef = ref<HTMLElement | null>(null)
const inputRef = ref<HTMLTextAreaElement | null>(null)
const chatRef = ref<HTMLElement | null>(null)

const title = computed(() => detail.value?.title || '未命名群组')

/** 群聊已解散：全员只读（历史可看，输入与发送禁用） */
const dissolved = computed(() => !!detail.value?.dissolved)

/** 群头像：设置并加载成功自定义图标时显示图片，否则回退默认占位图标 */
const avaFailed = ref(false)
const onAvaError = () => {
  avaFailed.value = true
}
watch(
  () => detail.value?.avatar_url,
  () => {
    avaFailed.value = false
  },
)

/* ---------------- 消息菜单：右键 / 长按（撤回） ---------------- */

const menu = ref<{ x: number; y: number; msg: GMsg } | null>(null)

/**
 * 点击菜单外关闭：遮罩只盖住手机屏内，这里兜住屏幕外的整个页面区域。
 * 打开后的 400ms 内忽略点击——长按呼出菜单的抬手 click 会紧跟其后，
 * 挡不住的话菜单会闪现即逝。
 */
let menuOpenedAt = 0
const onDocDismiss = (e: MouseEvent) => {
  if (!menu.value) return
  const t = e.target as HTMLElement | null
  if (t?.closest?.('.nlnoc-msg-menu')) return
  if (Date.now() - menuOpenedAt > 400) menu.value = null
}

watch(menu, (m) => {
  if (m) {
    menuOpenedAt = Date.now()
    document.addEventListener('click', onDocDismiss, true)
    document.addEventListener('contextmenu', onDocDismiss, true)
  } else {
    document.removeEventListener('click', onDocDismiss, true)
    document.removeEventListener('contextmenu', onDocDismiss, true)
  }
})

const openMenuAt = (clientX: number, clientY: number, m: GMsg) => {
  // 未落库 / 已撤回的消息不给菜单
  if (m.pending || m.failed || m.is_recalled) return
  const root = chatRef.value
  if (!root) return
  const r = root.getBoundingClientRect()
  menu.value = { x: clientX - r.left, y: clientY - r.top, msg: m }
}

const onMenuContext = (e: MouseEvent, m: GMsg) => {
  e.preventDefault()
  openMenuAt(e.clientX, e.clientY, m)
}

/** 消息区右键：气泡上开菜单；空白处只关菜单（原生菜单全程抑制） */
const onListContext = (e: MouseEvent) => {
  e.preventDefault()
  const t = e.target as HTMLElement
  if (!t.closest('.nlnoc-bubble')) menu.value = null
}

/* 触屏长按 480ms 呼出；位移 >10px 视为滚动/拖拽，取消 */
let pressTimer = 0
let pressPt = { x: 0, y: 0 }

const onBubbleDown = (e: PointerEvent, m: GMsg) => {
  if (e.pointerType === 'mouse') return // 鼠标走右键
  pressPt = { x: e.clientX, y: e.clientY }
  window.clearTimeout(pressTimer)
  pressTimer = window.setTimeout(() => openMenuAt(e.clientX, e.clientY, m), 480)
}

const cancelPress = () => {
  if (pressTimer) {
    window.clearTimeout(pressTimer)
    pressTimer = 0
  }
}

const onListMove = (e: PointerEvent) => {
  if (!pressTimer) return
  if (Math.abs(e.clientX - pressPt.x) > 10 || Math.abs(e.clientY - pressPt.y) > 10) {
    cancelPress()
  }
}

/** 菜单贴边夹紧：右/下越界时回收，始终完整可见 */
const menuPos = computed(() => {
  const m = menu.value
  const root = chatRef.value
  if (!m || !root) return { x: 0, y: 0 }
  const MW = 136
  const MH = 96
  const x = Math.min(Math.max(m.x, 6), Math.max(6, root.clientWidth - MW - 6))
  const y = Math.min(Math.max(m.y, 6), Math.max(6, root.clientHeight - MH - 6))
  return { x, y }
})

/* ---------------- 引用回复 ---------------- */

const replyTarget = ref<GMsg | null>(null)

const startReply = () => {
  if (!menu.value) return
  replyTarget.value = menu.value.msg
  menu.value = null
  inputRef.value?.focus()
}

const cancelReply = () => {
  replyTarget.value = null
}

/** 引用条名字：自己 → 「我」，否则用快照里的发送者昵称 */
const quoteName = (m: GMsg) =>
  m.reply_to?.sender_id === myId.value ? '我' : m.reply_to?.sender_username || '对方'

/** 引用条正文（被引消息已撤回时只留提示） */
const quoteText = (m: GMsg) => {
  const r = m.reply_to
  if (!r) return ''
  return r.is_recalled ? '该消息已被撤回' : r.content || '空消息'
}

/** 点引用块：滚动定位到被引消息并高亮 */
const jumpToQuote = (m: GMsg) => {
  const id = m.reply_to?.id
  if (!id) return
  const el = chatRef.value?.querySelector<HTMLElement>(`#nlnoc-msg-${id}`)
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  el.classList.add('nlnoc-msg-flash')
  window.setTimeout(() => el.classList.remove('nlnoc-msg-flash'), 1200)
}

/** 撤回：只能撤回自己的消息（右键他人消息不再显示撤回） */
const canRecall = (m: GMsg) => !m.is_recalled && m.sender_id === myId.value

const recallMsg = async () => {
  const m = menu.value?.msg
  menu.value = null
  if (!m) return
  try {
    await apiClient.post(`/api/conversations/${props.conversationId}/messages/${m.id}/recall`)
    m.is_recalled = true
    m.content = ''
    localSeq++
  } catch (err: any) {
    window.alert(err?.response?.data?.detail || '撤回失败，请稍后再试')
  }
}

const senderAvatar = (m: GMsg) => letterAvatar(m.sender_username || '?')
/** 群成员没有权限字段，统一按普通用户配色（与全站调用同源） */
const senderColor = (m: GMsg) => userNameColor({ username: m.sender_username })

const hhmm = (iso: string) => {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}

const nearBottom = () => {
  const el = listRef.value
  return !el || el.scrollHeight - el.scrollTop - el.clientHeight < 140
}

const scrollToBottom = async () => {
  await nextTick()
  const el = listRef.value
  if (!el) return
  el.scrollTop = el.scrollHeight
  // markdown 里的图片异步补高会改变 scrollHeight，下一帧再兜一次
  requestAnimationFrame(() => {
    if (el.isConnected) el.scrollTop = el.scrollHeight
  })
}

/* ---------------- 分组渲染 ---------------- */

const rows = computed(() =>
  msgs.value.map((m, i) => {
    // 系统消息（解散提示等）：sender_id 为空，居中渲染，不进气泡分组逻辑
    if (m.sender_id == null) return { m, system: true, mine: false, showHead: false, showTime: false }
    const prev = msgs.value[i - 1]
    const next = msgs.value[i + 1]
    const mine = m.sender_id === myId.value
    const gapPrev = prev ? new Date(m.created_at).getTime() - new Date(prev.created_at).getTime() : Infinity
    const sameAsPrev =
      !!prev && prev.sender_id === m.sender_id && !prev.failed && gapPrev < 5 * 60_000
    const gapNext = next ? new Date(next.created_at).getTime() - new Date(m.created_at).getTime() : Infinity
    const showTime = !next || next.sender_id !== m.sender_id || gapNext >= 5 * 60_000
    return { m, system: false, mine, showHead: !sameAsPrev, showTime }
  }),
)

/* ---------------- 加载 ---------------- */

/** 打开/浏览群聊时把已读位点推进到最新，清掉未读（角标由父级轮询刷新） */
const markRead = async () => {
  try {
    await apiClient.post(`/api/conversations/${props.conversationId}/read`)
  } catch {
    /* 静默：清零失败不影响阅读 */
  }
}

const loadDetail = async () => {
  try {
    const data: any = await apiClient.get(`/api/conversations/${props.conversationId}`)
    detail.value = data
  } catch {
    /* 详情失败不拦消息流：页头先显示占位，管理按钮仍可点（管理视图会再报错） */
  }
}

const loadMsgs = async (opts: { scroll?: boolean } = {}) => {
  try {
    const data: any = await apiClient.get(`/api/conversations/${props.conversationId}/messages`)
    msgs.value = Array.isArray(data?.messages) ? data.messages : []
    loadError.value = ''
    void markRead()
    if (opts.scroll !== false) await scrollToBottom()
  } catch (err: any) {
    loadError.value = err?.response?.data?.detail || err?.message || '加载群消息失败'
  } finally {
    loading.value = false
  }
}

const retryLoad = () => {
  loadError.value = ''
  loading.value = true
  void loadMsgs()
}

/* ---------------- 全量轮询（群聊无增量游标） ---------------- */

const poll = async () => {
  if (document.visibilityState !== 'visible') return
  // 有在途/失败的乐观消息时不整表覆盖：全量重拉会把它们顶掉
  if (msgs.value.some((m) => m.pending || m.failed)) return
  const seqAtStart = localSeq
  try {
    const data: any = await apiClient.get(`/api/conversations/${props.conversationId}/messages`)
    // 拉取期间本地有新变化（刚发出/重发/撤回）：丢弃这次可能过期的全量结果，
    // 否则刚发出的消息会被顶掉（表现为「闪一下就没了」）。
    if (seqAtStart !== localSeq) return
    const fresh: GMsg[] = Array.isArray(data?.messages) ? data.messages : []
    const stick = nearBottom()
    msgs.value = fresh
    void markRead()
    if (stick) await scrollToBottom()
  } catch {
    /* 网络抖动：下一轮再试 */
  }
}

let pollTimer = 0

/* ---------------- 发送 ---------------- */

const send = async () => {
  const text = input.value.trim()
  if (!text || sending.value) return
  sending.value = true
  sendError.value = ''
  mentionOpen.value = false
  const target = replyTarget.value
  const tmp: GMsg = {
    id: -Date.now(),
    sender_id: myId.value,
    sender_username: authStore.currentUser?.username || '我',
    content: text,
    created_at: new Date().toISOString(),
    pending: true,
    reply_to_id: target ? target.id : null,
    reply_to: target
      ? {
          id: target.id,
          sender_id: target.sender_id,
          sender_username: target.sender_username,
          content: target.is_recalled ? '' : target.content,
          is_recalled: target.is_recalled ?? false,
        }
      : null,
  }
  msgs.value.push(tmp)
  localSeq++
  input.value = ''
  if (inputRef.value) inputRef.value.style.height = 'auto'
  await scrollToBottom()
  try {
    const real: any = await apiClient.post(`/api/conversations/${props.conversationId}/messages`, {
      content: text,
      reply_to_id: target ? target.id : null,
    })
    const i = msgs.value.findIndex((m) => m.id === tmp.id)
    // 服务端回包只有 {id, content, reply_to_id, created_at}：身份与引用快照本地补齐
    const saved: GMsg = {
      sender_id: myId.value,
      sender_username: tmp.sender_username,
      is_recalled: false,
      reply_to: tmp.reply_to ?? null,
      ...real,
    }
    if (i !== -1) {
      msgs.value.splice(i, 1, saved)
    } else {
      // 乐观消息可能已被并发轮询顶掉，这里补回，确保刚发出的消息一定可见
      msgs.value.push(saved)
    }
    localSeq++
    // 成功才撤引用条（失败保留，配合失败气泡重填重发）
    replyTarget.value = null
    emit('sent')
  } catch (err: any) {
    const i = msgs.value.findIndex((m) => m.id === tmp.id)
    if (i !== -1) {
      msgs.value[i].pending = false
      msgs.value[i].failed = true
    }
    localSeq++
    sendError.value = err?.response?.data?.detail || '发送失败'
  } finally {
    sending.value = false
    await scrollToBottom()
  }
}

/** 失败气泡点击：把文字还回输入框，由用户确认后重发 */
const retry = (m: GMsg) => {
  const i = msgs.value.findIndex((x) => x.id === m.id)
  if (i !== -1) msgs.value.splice(i, 1)
  localSeq++
  input.value = m.content
  sendError.value = ''
  inputRef.value?.focus()
}

const onKeydown = (e: KeyboardEvent) => {
  // @ 补全菜单开着时：↑↓ 选人、Enter/Tab 插入、Esc 关闭（优先于发送）
  if (mentionOpen.value && !e.isComposing && (e as any).keyCode !== 229) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      mentionIdx.value = (mentionIdx.value + 1) % mentionList.value.length
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      mentionIdx.value = (mentionIdx.value - 1 + mentionList.value.length) % mentionList.value.length
      return
    }
    if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault()
      const u = mentionList.value[mentionIdx.value]
      if (u) pickMention(u)
      return
    }
    if (e.key === 'Escape') {
      mentionOpen.value = false
      return
    }
  }
  if (e.key !== 'Enter') return
  if (e.isComposing || (e as any).keyCode === 229) return
  if (e.shiftKey) return
  e.preventDefault()
  void send()
}

/** 输入框随内容长高，最高 96px 后内部滚动；同时刷新 @ 补全菜单 */
const growInput = (e: Event) => {
  const el = e.target as HTMLTextAreaElement
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 96)}px`
  updateMention()
}

/* ---------------- @提及补全（从群成员里选，渲染走全站 @ 链接） ---------------- */

const mentionOpen = ref(false)
const mentionList = ref<GMember[]>([])
const mentionIdx = ref(0)
let mentionStart = 0

// 与全站 mention 渲染同字符集：@ 后跟字母/数字/下划线/中文
const MENTION_RE = /@([A-Za-z0-9_\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]{0,50})$/

const updateMention = () => {
  const el = inputRef.value
  if (!el) return
  const caret = el.selectionStart ?? input.value.length
  const m = MENTION_RE.exec(input.value.slice(0, caret))
  if (!m) {
    mentionOpen.value = false
    return
  }
  const q = m[1].toLowerCase()
  mentionStart = caret - m[0].length
  const members = detail.value?.members || []
  mentionList.value = members
    .filter((u) => u.username.toLowerCase().includes(q))
    .slice(0, 6)
  if (!mentionList.value.length) {
    mentionOpen.value = false
    return
  }
  mentionIdx.value = 0
  mentionOpen.value = true
}

const pickMention = (u: GMember) => {
  const el = inputRef.value
  if (!el) return
  const end = el.selectionStart ?? input.value.length
  input.value =
    input.value.slice(0, mentionStart) + '@' + u.username + ' ' + input.value.slice(end)
  mentionOpen.value = false
  void nextTick(() => {
    const pos = mentionStart + u.username.length + 2
    el.selectionStart = el.selectionEnd = pos
    el.focus()
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 96)}px`
  })
}

/* ---------------- 生命周期 ---------------- */

/** 切回标签页立即补一轮，不干等下一次心跳 */
const onTabVisible = () => {
  if (document.visibilityState === 'visible') void poll()
}

onMounted(async () => {
  void loadDetail()
  await loadMsgs()
  // 5s 一轮，与私信/犇犇同节奏
  pollTimer = window.setInterval(poll, 5000)
  document.addEventListener('visibilitychange', onTabVisible)
})

onBeforeUnmount(() => {
  window.clearInterval(pollTimer)
  document.removeEventListener('visibilitychange', onTabVisible)
})
</script>

<template>
  <div ref="chatRef" class="nlnoc-page nlnoc-chat">
    <!-- 页头：返回 + 群头像 + 群名/成员数 + 右上角管理 -->
    <div class="nlnoc-chat-head">
      <button type="button" class="nlnoc-back" title="返回" @click="emit('back')">
        <i class="fa-solid fa-chevron-left"></i>
      </button>
      <span class="nlnoc-chat-ava">
        <span class="nlnoc-avatar-img nlnoc-group-ava">
          <i v-if="!detail?.avatar_url || avaFailed" class="fa-solid fa-user-group"></i>
          <img
            v-if="detail?.avatar_url && !avaFailed"
            :src="detail.avatar_url"
            class="nlnoc-ava-img"
            alt=""
            @error="onAvaError"
          />
        </span>
      </span>
      <div class="nlnoc-chat-id">
        <div class="nlnoc-chat-name">{{ title }}</div>
        <div class="nlnoc-chat-sub">
          {{ detail ? `${detail.member_count} 名成员` : '群聊' }}
        </div>
      </div>
      <button
        type="button"
        class="nlnoc-back nlnoc-head-gear"
        title="群聊管理"
        @click="emit('manage')"
      >
        <i class="fa-solid fa-users-gear"></i>
      </button>
    </div>

    <!-- 消息流 -->
    <div
      ref="listRef"
      class="nlnoc-msgs"
      @contextmenu="onListContext"
      @pointermove="onListMove"
      @pointerup="cancelPress"
      @pointercancel="cancelPress"
      @scroll.passive="cancelPress"
    >
      <div v-if="loading" class="nlnoc-msgs-tip">
        <i class="fa-solid fa-spinner fa-spin"></i>
      </div>
      <div v-else-if="loadError" class="nlnoc-empty">
        <i class="fa-solid fa-triangle-exclamation"></i>
        <p>{{ loadError }}</p>
        <button type="button" class="nlnoc-msgs-more" @click="retryLoad">重试</button>
      </div>
      <template v-else>
        <div v-if="msgs.length === 0" class="nlnoc-empty">
          <i class="fa-regular fa-hand-wave"></i>
          <p>还没有消息，打个招呼吧</p>
        </div>

        <div
          v-for="r in rows"
          :key="r.m.id"
          :id="'nlnoc-msg-' + r.m.id"
          class="nlnoc-msg"
          :class="[r.mine ? 'mine' : 'theirs', { compact: !r.showHead }]"
        >
          <!-- 系统消息（如「群主 xxx 解散了群聊」）：居中小字提示 -->
          <div v-if="r.system" class="nlnoc-sysmsg">{{ r.m.content }}</div>
          <template v-else>
          <div v-if="!r.mine" class="nlnoc-msg-ava">
            <img
              v-if="r.showHead"
              :src="senderAvatar(r.m)"
              class="nlnoc-avatar-img xs"
              alt=""
            />
            <span v-else class="nlnoc-avatar-img xs ghost"></span>
          </div>
          <div class="nlnoc-msg-body">
            <div v-if="!r.mine && r.showHead" class="nlnoc-msg-name" :style="{ color: senderColor(r.m) }">
              {{ r.m.sender_username || '已注销用户' }}
            </div>
            <div
              class="nlnoc-bubble"
              :class="{
                pending: r.m.pending,
                failed: r.m.failed,
                recalled: r.m.is_recalled,
              }"
              @click="r.m.failed && retry(r.m)"
              @contextmenu="onMenuContext($event, r.m)"
              @pointerdown="onBubbleDown($event, r.m)"
            >
              <button
                v-if="r.m.reply_to && !r.m.is_recalled"
                type="button"
                class="nlnoc-bubble-quote"
                title="跳转到被引用的消息"
                @click.stop="jumpToQuote(r.m)"
              >
                <span class="nlnoc-bubble-quote-name">{{ quoteName(r.m) }}：</span>
                <span class="nlnoc-bubble-quote-text">{{ quoteText(r.m) }}</span>
              </button>
              <div v-if="r.m.is_recalled" class="nlnoc-recalled">
                <i class="fa-solid fa-rotate-left"></i>
                {{ r.mine ? '你撤回了一条消息' : '一条消息已撤回' }}
              </div>
              <div v-else class="nlnoc-bubble-text prose" v-html="renderRichText(r.m.content)"></div>
              <span v-if="r.m.pending" class="nlnoc-bubble-state" title="发送中">
                <i class="fa-solid fa-circle-notch fa-spin"></i>
              </span>
              <span
                v-else-if="r.m.failed"
                class="nlnoc-bubble-state fail"
                title="发送失败，点击重填"
              >
                <i class="fa-solid fa-triangle-exclamation"></i>
              </span>
            </div>
            <div v-if="r.showTime" class="nlnoc-msg-time">{{ hhmm(r.m.created_at) }}</div>
          </div>
          </template>
        </div>
      </template>
    </div>

    <div v-if="sendError" class="nlnoc-send-error">
      <i class="fa-solid fa-circle-exclamation"></i> {{ sendError }}
    </div>

    <!-- 回复引用条（菜单里点「回复」后出现，发送成功自动收起） -->
    <div v-if="replyTarget" class="nlnoc-reply-strip">
      <i class="fa-solid fa-reply nlnoc-reply-strip-ico"></i>
      <span class="nlnoc-reply-strip-name">
        回复 {{ replyTarget.sender_id === myId ? '我' : replyTarget.sender_username }}：
      </span>
      <span class="nlnoc-reply-strip-text">{{ replyTarget.content }}</span>
      <button type="button" class="nlnoc-reply-strip-x" title="取消回复" @click="cancelReply">
        <i class="fa-solid fa-xmark"></i>
      </button>
    </div>

    <!-- 输入区（群聊已解散时全员只读，仅显示底部系统提示） -->
    <div v-if="dissolved" class="nlnoc-dissolved-bar">
      <i class="fa-solid fa-ban"></i> 群聊已解散，仅可查看历史消息
    </div>
    <div v-else class="nlnoc-composer">
      <textarea
        ref="inputRef"
        v-model="input"
        class="nlnoc-input"
        rows="1"
        maxlength="2000"
        placeholder="发消息…（输入 @ 提到群成员）"
        @input="growInput"
        @keydown="onKeydown"
        @blur="mentionOpen = false"
      ></textarea>
      <!-- @ 补全：从群成员里选，↑↓ 切换 / Enter 或 Tab 插入 / Esc 关闭 -->
      <div v-if="mentionOpen" class="nlnoc-mention-menu">
        <button
          v-for="(u, i) in mentionList"
          :key="u.user_id"
          type="button"
          class="nlnoc-mention-item"
          :class="{ active: i === mentionIdx }"
          @mousedown.prevent
          @click="pickMention(u)"
        >
          <img :src="letterAvatar(u.username)" class="nlnoc-mention-ava" alt="" />
          <span class="nlnoc-mention-name">{{ u.username }}</span>
        </button>
      </div>
      <button
        type="button"
        class="nlnoc-send"
        :disabled="!input.trim() || sending"
        title="发送"
        @click="send"
      >
        <i class="fa-solid fa-paper-plane"></i>
      </button>
    </div>

    <!-- 消息菜单：右键 / 长按呼出（遮罩负责点击关闭，同时抑制原生菜单） -->
    <div
      v-if="menu"
      class="nlnoc-menu-mask"
      @click="menu = null"
      @contextmenu.prevent="menu = null"
    ></div>
    <div
      v-if="menu"
      class="nlnoc-msg-menu"
      :style="{ left: menuPos.x + 'px', top: menuPos.y + 'px' }"
    >
      <button type="button" @click="startReply">
        <i class="fa-solid fa-reply"></i> 回复
      </button>
      <button v-if="canRecall(menu.msg)" type="button" class="nlnoc-danger" @click="recallMsg">
        <i class="fa-solid fa-rotate-left"></i> 撤回
      </button>
    </div>
  </div>
</template>

<style scoped>
.nlnoc-chat {
  position: relative; /* 消息菜单/遮罩的定位上下文 */
  background: transparent;
}

/* ===== 页头 ===== */
.nlnoc-chat-head {
  flex: none;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 12px 12px 10px;
  background: rgba(255, 255, 255, 0.72);
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid rgba(15, 18, 32, 0.06);
}

.nlnoc-back {
  flex: none;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 50%;
  background: rgba(15, 18, 32, 0.06);
  color: var(--text-strong);
  font-size: 13px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s;
}

.nlnoc-back:hover {
  background: rgba(15, 18, 32, 0.12);
}

.nlnoc-chat-ava {
  flex: none;
  line-height: 0;
}

/* 页头头像 40：与聊天页同一规格（返回键/发送键统一 36） */
.nlnoc-avatar-img {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  object-fit: cover;
  display: block;
  box-shadow: 0 1px 4px rgba(15, 18, 32, 0.16);
}

.nlnoc-avatar-img.xs {
  width: 26px;
  height: 26px;
  box-shadow: none;
}

.nlnoc-avatar-img.ghost {
  background: transparent;
}

.nlnoc-chat-id {
  flex: 1;
  min-width: 0;
}

.nlnoc-chat-name {
  font-size: 14.5px;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 用户名跳主页的链接：吃继承色、去下划线，悬停示意可点 */
.nlnoc-ulink {
  color: inherit;
  text-decoration: none;
}

.nlnoc-ulink:hover {
  text-decoration: underline;
}

.nlnoc-chat-sub {
  font-size: 10.5px;
  color: #98a1b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ===== 消息流 ===== */
.nlnoc-msgs {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 10px 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  scrollbar-width: thin;
}

.nlnoc-msgs::-webkit-scrollbar {
  width: 4px;
}

.nlnoc-msgs::-webkit-scrollbar-thumb {
  background: rgba(15, 18, 32, 0.16);
  border-radius: 2px;
}

.nlnoc-msgs-tip {
  margin: auto;
  color: #a3aabd;
  font-size: 14px;
}

.nlnoc-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  margin: auto;
  padding: 40px 20px;
  color: #a3aabd;
  font-size: 13px;
  text-align: center;
}

.nlnoc-empty i {
  font-size: 26px;
  color: #c2c9dc;
}

.nlnoc-empty p {
  margin: 0;
}

.nlnoc-msgs-more {
  align-self: center;
  border: none;
  background: rgba(15, 18, 32, 0.05);
  color: var(--text-sub);
  font-size: 11px;
  padding: 5px 12px;
  border-radius: 999px;
  cursor: pointer;
  margin-bottom: 8px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: inherit;
  transition: background 0.15s;
}

.nlnoc-msgs-more:hover {
  background: rgba(15, 18, 32, 0.1);
}

.nlnoc-msg {
  display: flex;
  gap: 7px;
  margin-top: 8px;
}

.nlnoc-msg.compact {
  margin-top: 2px;
}

.nlnoc-msg.mine {
  flex-direction: row-reverse;
}

.nlnoc-msg-ava {
  flex: none;
  width: 26px;
}

.nlnoc-msg-body {
  max-width: 76%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}

.nlnoc-msg.mine .nlnoc-msg-body {
  align-items: flex-end;
}

.nlnoc-msg-name {
  font-size: 10.5px;
  margin: 0 0 3px 4px;
  color: #98a1b8;
}

.nlnoc-bubble {
  position: relative;
  padding: 8px 12px;
  border-radius: 16px;
  background: var(--surface-plain);
  color: var(--text-strong);
  box-shadow: 0 1px 4px rgba(15, 18, 32, 0.08);
  word-break: break-word;
  overflow-wrap: anywhere;
  transition: opacity 0.2s;
}

/* 左侧小尾巴（对方）、右侧小尾巴（自己） */
.nlnoc-msg.theirs .nlnoc-bubble {
  border-top-left-radius: 6px;
}

.nlnoc-msg.mine .nlnoc-bubble {
  border-top-right-radius: 6px;
  background: linear-gradient(135deg, var(--primary), var(--grad-indigo));
  color: #fff;
}

.nlnoc-bubble.pending {
  opacity: 0.62;
}

.nlnoc-bubble.failed {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
color: var(--danger-text);
  box-shadow: inset 0 0 0 1.5px rgba(244, 63, 94, 0.5);
  cursor: pointer;
}

/* 气泡内 markdown（v-html 注入，需 :deep） */
.nlnoc-bubble-text :deep(p) {
  margin: 0 0 0.4em;
}

.nlnoc-bubble-text :deep(p:last-child) {
  margin-bottom: 0;
}

.nlnoc-bubble-text :deep(a) {
  color: #2563eb;
}

.nlnoc-msg.mine .nlnoc-bubble-text {
  color: #fff;
}

.nlnoc-msg.mine .nlnoc-bubble-text :deep(a) {
  color: #cfe0ff;
}

.nlnoc-msg.mine .nlnoc-bubble-text :deep(code) {
  background: rgba(255, 255, 255, 0.18);
  color: #ffe9a8;
}

.nlnoc-bubble-text :deep(img) {
  max-width: 100%;
  border-radius: 8px;
}

.nlnoc-bubble-text :deep(pre) {
  max-width: 100%;
}

.nlnoc-bubble-state {
  position: absolute;
  right: -18px;
  bottom: -2px;
  font-size: 10px;
  color: #98a1b8;
}

.nlnoc-bubble-state.fail {
  color: #f43f5e;
}

.nlnoc-msg.mine .nlnoc-bubble-state {
  right: auto;
  left: -18px;
}

/* ===== 引用回复 ===== */
.nlnoc-bubble-quote {
  display: flex;
  align-items: baseline;
  width: 100%;
  min-width: 0;
  margin: 0 0 5px;
  padding: 4px 8px;
  border: none;
  border-left: 3px solid color-mix(in srgb, var(--primary) 55%, transparent);
  border-radius: 6px;
  background: rgba(15, 18, 32, 0.06);
  color: inherit;
  font-family: inherit;
  font-size: 11.5px;
  line-height: 1.4;
  text-align: left;
  cursor: pointer;
  overflow: hidden;
}

.nlnoc-msg.mine .nlnoc-bubble-quote {
  background: rgba(255, 255, 255, 0.18);
  border-left-color: rgba(255, 255, 255, 0.7);
}

.nlnoc-bubble-quote-name {
  flex: none;
  font-weight: 700;
}

.nlnoc-bubble-quote-text {
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  opacity: 0.85;
}

/* ===== 撤回 ===== */
.nlnoc-bubble.recalled,
.nlnoc-msg.mine .nlnoc-bubble.recalled {
  background: rgba(15, 18, 32, 0.05);
  color: #98a1b8;
  box-shadow: none;
}

.nlnoc-recalled {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  font-style: italic;
}

/* 引用跳转的定位高亮 */
.nlnoc-msg-flash .nlnoc-bubble {
  box-shadow:
    0 0 0 2.5px color-mix(in srgb, var(--primary) 55%, transparent),
    0 1px 4px rgba(15, 18, 32, 0.08);
}

.nlnoc-msg-time {
  font-size: 9.5px;
  color: #b0b7ca;
  margin-top: 3px;
  padding: 0 4px;
}

/* ===== 发送错误提示 ===== */
.nlnoc-send-error {
  flex: none;
  padding: 5px 14px;
  background: color-mix(in srgb, var(--danger) 10%, transparent);
color: var(--danger-text);
  font-size: 11.5px;
}

/* ===== 消息菜单（右键 / 长按） ===== */
.nlnoc-menu-mask {
  position: absolute;
  inset: 0;
  z-index: 50;
}

.nlnoc-msg-menu {
  position: absolute;
  z-index: 51;
  min-width: 136px;
  padding: 4px;
  background: var(--surface-plain);
  border-radius: 12px;
  box-shadow: 0 10px 30px rgba(15, 18, 32, 0.24);
}

.nlnoc-msg-menu button {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  border: none;
  background: none;
  padding: 9px 12px;
  font-size: 13px;
  color: var(--text-strong);
  font-family: inherit;
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
  transition: background 0.12s;
}

.nlnoc-msg-menu button:hover {
  background: rgba(15, 18, 32, 0.07);
}

.nlnoc-msg-menu button.nlnoc-danger {
  color: #e11d48;
}

/* ===== 输入区 ===== */
.nlnoc-composer {
  position: relative; /* @ 补全菜单的定位上下文 */
  flex: none;
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 9px 10px;
  background: rgba(255, 255, 255, 0.82);
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
  border-top: 1px solid rgba(15, 18, 32, 0.06);
}

.nlnoc-input {
  flex: 1;
  min-width: 0;
  resize: none;
  border: 1px solid rgba(15, 18, 32, 0.1);
  background: var(--surface-plain);
  border-radius: 14px;
  padding: 8px 12px;
  font-size: 13.5px;
  line-height: 1.45;
  font-family: inherit;
  color: var(--text-strong);
  outline: none;
  max-height: 96px;
  transition: border-color 0.15s;
}

.nlnoc-input:focus {
  border-color: color-mix(in srgb, var(--primary) 55%, transparent);
}

.nlnoc-input::placeholder {
  color: #a9b0c3;
}

.nlnoc-send {
  flex: none;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 50%;
  background: var(--primary, #4a4ae0);
  color: #fff;
  font-size: 13px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.15s, opacity 0.15s;
}

.nlnoc-send:disabled {
  opacity: 0.4;
  cursor: default;
}

.nlnoc-send:not(:disabled):hover {
  transform: scale(1.08);
}

/* ===== 回复引用条 ===== */
.nlnoc-reply-strip {
  flex: none;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: color-mix(in srgb, var(--primary) 7%, transparent);
  border-top: 1px solid color-mix(in srgb, var(--primary) 14%, transparent);
  font-size: 11.5px;
  color: var(--text-sub);
}

.nlnoc-reply-strip-ico {
  flex: none;
  color: var(--primary);
}

.nlnoc-reply-strip-name {
  flex: none;
  font-weight: 700;
  color: var(--primary);
}

.nlnoc-reply-strip-text {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nlnoc-reply-strip-x {
  flex: none;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: 50%;
  background: rgba(15, 18, 32, 0.08);
  color: var(--text-sub);
  font-size: 11px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s;
}

.nlnoc-reply-strip-x:hover {
  background: rgba(15, 18, 32, 0.14);
}

/* ===== 群聊差异样式 ===== */
/* 群头像：字母头像底 + 图标居中（沿用 nlnoc-avatar-img 的尺寸） */
.nlnoc-group-ava {
  position: relative; /* 群头像 URL 图片叠在占位图标上 */
  display: inline-flex;
  align-items: center;
  justify-content: center;
  /* 父级 .nlnoc-chat-ava 设了 line-height: 0，会让 FA 字形行盒塌成 0 高，
     flex 居中的是 0 高盒子、字形墨水挂在基线下方，图标看起来偏下；恢复行高才能真居中 */
  line-height: 1;
  background: color-mix(in srgb, var(--primary) 8%, transparent);
  color: #6366f1;
}
.nlnoc-group-ava i {
  font-size: 0.85em;
}

.nlnoc-ava-img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 50%;
  display: block;
}

/* 页头右侧「群聊管理」按钮推到最右 */
.nlnoc-head-gear {
  margin-left: auto;
}

/* ===== @ 提及补全 ===== */
/* @补全菜单：锚定在输入框正上方、宽度与输入框对齐；
   高度随可视区收缩，避免高屏以下超出手机屏被裁切或错位 */
.nlnoc-mention-menu {
  position: absolute;
  left: 10px;
  right: 10px;
  bottom: calc(100% + 8px);
  max-height: min(200px, calc(100vh - 260px));
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 6px;
  background: var(--surface-plain);
  border: 1px solid rgba(15, 18, 32, 0.08);
  border-radius: 14px;
  box-shadow: 0 14px 34px rgba(15, 18, 32, 0.22);
  z-index: 60;
}

.nlnoc-mention-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 8px;
  border: none;
  border-radius: 10px;
  background: none;
  color: var(--text-strong);
  font-family: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}

.nlnoc-mention-ava {
  flex: none;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  object-fit: cover;
}

.nlnoc-mention-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nlnoc-mention-item:hover,
.nlnoc-mention-item.active {
  background: color-mix(in srgb, var(--primary) 10%, transparent);
  color: var(--primary);
}

/* 系统消息（解散提示等）：整行居中、弱化小字，不进气泡 */
.nlnoc-sysmsg {
  width: 100%;
  text-align: center;
  font-size: 12px;
  color: var(--text-sub, #8a8f99);
  padding: 6px 12px;
}

/* 解散后底部只读提示条（替代输入框位置） */
.nlnoc-dissolved-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 12px;
  font-size: 13px;
  color: var(--text-sub, #8a8f99);
  background: color-mix(in srgb, var(--text-sub, #8a8f99) 8%, transparent);
}

/* ===== 手机端（≤640px）：机身准全屏，输入字号抬到 16 防 iOS 聚焦缩放 ===== */
@media (max-width: 640px) {
  .nlnoc-input {
    font-size: 16px;
  }
}
</style>
