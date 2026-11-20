<script setup lang="ts">
/**
 * NLNOC 私信聊天页 —— 模仿手机 IM（左收右发的气泡、头像分组、组尾时间）。
 *
 * 数据流：
 *   打开   GET /api/messages/{peer}?limit=30（旧→新）+ POST .../read（清角标）
 *   翻更早 before_id 向前分页，插入后保持滚动位置
 *   轮询   每 15s after_id 增量拉新，贴底时自动滚
 *   发送   乐观插入（pending）→ 成功换真身 / 失败标红，点击气泡把文字还给输入框重填
 *
 * 中文输入法：Enter 在选词期间（isComposing/keyCode 229）不能当发送，
 * 否则拼音回车选字会直接把半截话发出去。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import apiClient from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import type { NLNOCUser } from '@/stores/nlnoc'
import { useNlnocStore } from '@/stores/nlnoc'
import { letterAvatar } from '@/utils/avatar'
import { renderRichText } from '@/utils/markdown'
import { userNameColor } from '@/utils/userColor'
import UserAvatarStatus from '@/components/UserAvatarStatus.vue'

const nlnoc = useNlnocStore()
const props = defineProps<{ peer: NLNOCUser }>()
const emit = defineEmits<{
  back: []
  /** 发送成功（已落库）：父级据此把该会话合成进列表，发过的人必然可见 */
  sent: [payload: { peer: NLNOCUser; message: Msg }]
  /** 轮询带回的最新对方资料（last_seen）：父级据此刷新在线状态点 */
  'peer-updated': [peer: NLNOCUser]
}>()

/** 引用快照（后端随消息一并下发，前端免二次请求） */
interface ReplySnap {
  id: number
  sender_id: number
  content: string
  is_recalled?: boolean
}

interface Msg {
  id: number
  sender_id: number
  content: string
  created_at: string
  is_read?: boolean
  is_recalled?: boolean
  reply_to_id?: number | null
  reply_to?: ReplySnap | null
  pending?: boolean
  failed?: boolean
}

const authStore = useAuthStore()
const myId = computed(() => authStore.currentUser?.id ?? -1)

const msgs = ref<Msg[]>([])
const loading = ref(true)
const loadingOlder = ref(false)
const hasMore = ref(false)
const input = ref('')
const sending = ref(false)
const sendError = ref('')
const listRef = ref<HTMLElement | null>(null)
const inputRef = ref<HTMLTextAreaElement | null>(null)

/* ---------------- 消息菜单：右键 / 长按（回复、撤回） ---------------- */

const chatRef = ref<HTMLElement | null>(null)
/** 菜单状态：坐标相对聊天页根元素（机身整体有 transform，position: fixed 会错位） */
const menu = ref<{ x: number; y: number; msg: Msg } | null>(null)
/** 待回复的引用目标（composer 上方引用条） */
const replyTarget = ref<Msg | null>(null)

/**
 * 点击菜单外关闭：遮罩只盖住手机屏内，这里兜住屏幕外的整个页面区域。
 * 打开后的 400ms 内忽略点击——长按呼出菜单的抬手 click 会紧跟其后，
 * 不挡住它的话菜单会闪现即逝。
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

const openMenuAt = (clientX: number, clientY: number, m: Msg) => {
  // 未落库 / 已撤回的消息不给菜单
  if (m.pending || m.failed || m.is_recalled) return
  const root = chatRef.value
  if (!root) return
  const r = root.getBoundingClientRect()
  menu.value = { x: clientX - r.left, y: clientY - r.top, msg: m }
}

const onMenuContext = (e: MouseEvent, m: Msg) => {
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

const onBubbleDown = (e: PointerEvent, m: Msg) => {
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

const startReply = () => {
  if (!menu.value) return
  replyTarget.value = menu.value.msg
  menu.value = null
  inputRef.value?.focus()
}

const cancelReply = () => {
  replyTarget.value = null
}

/** 把「已撤回」应用到本地：消息本身 + 引用了它的其它消息的快照 */
const applyRecalled = (ids: number[]) => {
  if (!ids.length) return
  const set = new Set(ids)
  for (const m of msgs.value) {
    if (set.has(m.id) && !m.is_recalled) {
      m.is_recalled = true
      m.content = ''
      m.reply_to = null
    }
    if (m.reply_to && set.has(m.reply_to.id) && !m.reply_to.is_recalled) {
      m.reply_to.is_recalled = true
      m.reply_to.content = ''
    }
  }
}

const recallMsg = async () => {
  const m = menu.value?.msg
  menu.value = null
  if (!m) return
  try {
    await apiClient.post(`/api/messages/${m.id}/recall`)
    applyRecalled([m.id])
  } catch (err: any) {
    window.alert(err?.response?.data?.detail || '撤回失败，请稍后再试')
  }
}

/** 引用条名字：自己 → 「我」，对方 → 用户名 */
const quoteName = (m: Msg) =>
  m.reply_to?.sender_id === myId.value ? '我' : props.peer.username

/** 引用条正文（被引消息已撤回时只留提示） */
const quoteText = (m: Msg) => {
  const r = m.reply_to
  if (!r) return ''
  return r.is_recalled ? '该消息已被撤回' : r.content || '空消息'
}

/** 点引用块：滚动定位到被引消息并高亮 */
const jumpToQuote = (m: Msg) => {
  const id = m.reply_to?.id
  if (!id) return
  const el = chatRef.value?.querySelector<HTMLElement>(`#nlnoc-msg-${id}`)
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  el.classList.add('nlnoc-msg-flash')
  window.setTimeout(() => el.classList.remove('nlnoc-msg-flash'), 1200)
}

const avatarOf = (u: NLNOCUser) => u.avatar_url || letterAvatar(u.username)
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
    const prev = msgs.value[i - 1]
    const next = msgs.value[i + 1]
    const mine = m.sender_id === myId.value
    const gapPrev = prev ? new Date(m.created_at).getTime() - new Date(prev.created_at).getTime() : Infinity
    const sameAsPrev =
      !!prev && prev.sender_id === m.sender_id && !prev.failed && gapPrev < 5 * 60_000
    const gapNext = next ? new Date(next.created_at).getTime() - new Date(m.created_at).getTime() : Infinity
    const showTime = !next || next.sender_id !== m.sender_id || gapNext >= 5 * 60_000
    return { m, mine, showHead: !sameAsPrev, showTime }
  }),
)

/* ---------------- 加载 ---------------- */

const loadError = ref('')

const loadLatest = async () => {
  try {
    const data: any = await apiClient.get(`/api/messages/${props.peer.id}`, {
      params: { limit: 30 },
    })
    msgs.value = data?.messages || []
    hasMore.value = !!data?.has_more
  } catch (err: any) {
    // 显性失败：以前这里静默吞掉异常，界面看起来就是「聊天记录没了」，
    // 现在把真实错误亮出来并给重试入口，方便定位（401/500/表未迁移等）
    loadError.value = err?.response?.data?.detail || err?.message || '加载聊天记录失败'
  } finally {
    // 必须先撤 loading 再滚：v-if="loading" 为真时消息 DOM 尚未渲染，
    // 此时设 scrollTop 只会作用在占位元素上，等列表出现就停在顶部了
    loading.value = false
  }
  await scrollToBottom()
  try {
    await apiClient.post(`/api/messages/${props.peer.id}/read`)
    window.dispatchEvent(new Event('nlnoc:unread-changed'))
  } catch {
    /* 已读上报失败只影响角标时效，下轮轮询兜底 */
  }
}

/** 加载失败后的重试 */
const retryLoad = () => {
  loadError.value = ''
  loading.value = true
  void loadLatest()
}

const loadOlder = async () => {
  // 乐观消息 id 是负数，拿它当分页游标会查出空页；只认真实落库的 id
  const firstReal = msgs.value.find((m) => m.id > 0)
  if (!hasMore.value || loadingOlder.value || !firstReal) return
  loadingOlder.value = true
  const el = listRef.value
  const keep = el ? el.scrollHeight : 0
  try {
    const data: any = await apiClient.get(`/api/messages/${props.peer.id}`, {
      params: { before_id: firstReal.id, limit: 30 },
    })
    msgs.value = [...(data?.messages || []), ...msgs.value]
    hasMore.value = !!data?.has_more
    await nextTick()
    if (el) el.scrollTop = el.scrollHeight - keep
  } finally {
    loadingOlder.value = false
  }
}

/* ---------------- 增量轮询 ---------------- */

// 防重入：切回前台瞬间，节流挤压的 interval tick 与 visibilitychange 补刷会并发，
// 两轮拿同一个 after_id 会把同一批新消息各追加一次（显示两遍）。
let polling = false

const poll = async () => {
  if (polling || document.visibilityState !== 'visible') return
  // 负数 id（乐观/失败消息）当 after_id，会把全量历史当「新消息」重复插进来
  const lastReal = [...msgs.value].reverse().find((m) => m.id > 0)
  if (!lastReal) return
  polling = true
  try {
    const data: any = await apiClient.get(`/api/messages/${props.peer.id}`, {
      params: { after_id: lastReal.id, limit: 50 },
    })
    // 顺带同步对方在线状态：接口每次都返回最新 peer（含 last_seen）
    const fresh = data?.peer
    if (fresh && fresh.last_seen !== props.peer.last_seen) emit('peer-updated', fresh)
    // 旧消息的撤回不在增量里：后端每轮附带会话内最近的撤回 id 同步本地
    applyRecalled(data?.recalled_ids || [])
    const incoming: Msg[] = data?.messages || []
    if (incoming.length) {
      const stick = nearBottom()
      // 去重兜底：send() 替换乐观消息与在途轮询撞车时，刚发的消息会两边各来一次
      const seen = new Set(msgs.value.map((m) => m.id))
      const add = incoming.filter((m) => !seen.has(m.id))
      if (add.length) {
        msgs.value.push(...add)
        // 对话进行中：拉到的新消息顺手标已读，信封角标不为当前会话亮起
        void apiClient
          .post(`/api/messages/${props.peer.id}/read`)
          .then(() => window.dispatchEvent(new Event('nlnoc:unread-changed')))
          .catch(() => {
            /* 网络抖动：下一轮轮询补标 */
          })
        if (stick) await scrollToBottom()
      }
    }
  } catch {
    /* 网络抖动：下一轮再试 */
  } finally {
    polling = false
  }
}

let pollTimer = 0

/* ---------------- 发送 ---------------- */

const send = async () => {
  const text = input.value.trim()
  if (!text || sending.value) return
  sending.value = true
  sendError.value = ''
  const target = replyTarget.value
  const tmp: Msg = {
    id: -Date.now(),
    sender_id: myId.value,
    content: text,
    created_at: new Date().toISOString(),
    pending: true,
    reply_to_id: target ? target.id : null,
    reply_to: target
      ? {
          id: target.id,
          sender_id: target.sender_id,
          content: target.is_recalled ? '' : target.content,
          is_recalled: target.is_recalled,
        }
      : null,
  }
  msgs.value.push(tmp)
  input.value = ''
  if (inputRef.value) inputRef.value.style.height = 'auto'
  await scrollToBottom()
  try {
    const real: any = await apiClient.post('/api/messages', {
      recipient_id: props.peer.id,
      content: text,
      reply_to_id: target ? target.id : null,
    })
    const i = msgs.value.findIndex((m) => m.id === tmp.id)
    if (i !== -1) msgs.value.splice(i, 1, real)
    // 服务端已落库：通知父级把该会话合成进列表（发过的人必然可见）
    emit('sent', { peer: props.peer, message: real })
    // 成功才撤引用条（失败保留，配合失败气泡重填重发）
    replyTarget.value = null
  } catch (err: any) {
    const i = msgs.value.findIndex((m) => m.id === tmp.id)
    if (i !== -1) {
      msgs.value[i].pending = false
      msgs.value[i].failed = true
    }
    sendError.value = err?.response?.data?.detail || '发送失败'
  } finally {
    sending.value = false
    await scrollToBottom()
  }
}

/** 失败气泡点击：把文字还回输入框，由用户确认后重发 */
const retry = (m: Msg) => {
  const i = msgs.value.findIndex((x) => x.id === m.id)
  if (i !== -1) msgs.value.splice(i, 1)
  input.value = m.content
  sendError.value = ''
  inputRef.value?.focus()
}

const onKeydown = (e: KeyboardEvent) => {
  if (e.key !== 'Enter') return
  if (e.isComposing || (e as any).keyCode === 229) return
  if (e.shiftKey) return
  e.preventDefault()
  void send()
}

/** 输入框随内容长高，最高 96px 后内部滚动 */
const growInput = (e: Event) => {
  const el = e.target as HTMLTextAreaElement
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 96)}px`
}

/* ---------------- 生命周期 ---------------- */

/** 切回标签页立即补一轮，不干等下一次心跳 */
const onTabVisible = () => {
  if (document.visibilityState === 'visible') void poll()
}

onMounted(async () => {
  nlnoc.setActivePeer(props.peer.id)
  await loadLatest()
  // 5s 一轮，与首页犇犇同节奏——新消息不再「迟到」十几秒
  pollTimer = window.setInterval(poll, 5000)
  document.addEventListener('visibilitychange', onTabVisible)
})

// 面板里切换对话：角标的「排除对象」跟着换人
watch(
  () => props.peer.id,
  (id) => nlnoc.setActivePeer(id),
)

onBeforeUnmount(() => {
  window.clearInterval(pollTimer)
  document.removeEventListener('visibilitychange', onTabVisible)
  nlnoc.setActivePeer(null)
})
</script>

<template>
  <div ref="chatRef" class="nlnoc-page nlnoc-chat">
    <!-- 聊天页头 -->
    <div class="nlnoc-chat-head">
      <button type="button" class="nlnoc-back" title="返回" @click="emit('back')">
        <i class="fa-solid fa-chevron-left"></i>
      </button>
      <UserAvatarStatus :user="peer" :size="8" class="nlnoc-chat-ava">
        <img :src="avatarOf(peer)" class="nlnoc-avatar-img" alt="" />
      </UserAvatarStatus>
      <div class="nlnoc-chat-id">
        <div class="nlnoc-chat-name" :style="{ color: userNameColor(peer) }">
          <router-link
            class="nlnoc-ulink"
            :to="`/user/${peer.user_number}`"
            title="查看用户主页"
          >{{ peer.username }}</router-link>
        </div>
        <div class="nlnoc-chat-sub">
          {{ peer.user_tag ? peer.user_tag + ' · ' : '' }}UID {{ peer.user_number }}
        </div>
      </div>
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
        <button v-if="hasMore" type="button" class="nlnoc-msgs-more" @click="loadOlder">
          <i :class="loadingOlder ? 'fa-solid fa-spinner fa-spin' : 'fa-solid fa-angles-up'"></i>
          {{ loadingOlder ? '加载中…' : '加载更早的消息' }}
        </button>
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
          <div v-if="!r.mine" class="nlnoc-msg-ava">
            <UserAvatarStatus v-if="r.showHead" :user="peer" :size="7" class="nlnoc-ava-status">
              <img :src="avatarOf(peer)" class="nlnoc-avatar-img xs" alt="" />
            </UserAvatarStatus>
            <span v-else class="nlnoc-avatar-img xs ghost"></span>
          </div>
          <div class="nlnoc-msg-body">
            <div
              v-if="!r.mine && r.showHead"
              class="nlnoc-msg-name"
              :style="{ color: userNameColor(peer) }"
            >
              <router-link
                class="nlnoc-ulink"
                :to="`/user/${peer.user_number}`"
                title="查看用户主页"
              >{{ peer.username }}</router-link>
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
                {{ r.mine ? '你撤回了一条消息' : '对方撤回了一条消息' }}
              </div>
              <div
                v-else
                class="nlnoc-bubble-text prose"
                v-html="renderRichText(r.m.content)"
              ></div>
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
        回复 {{ replyTarget.sender_id === myId ? '我' : peer.username }}：
      </span>
      <span class="nlnoc-reply-strip-text">{{ replyTarget.content }}</span>
      <button type="button" class="nlnoc-reply-strip-x" title="取消回复" @click="cancelReply">
        <i class="fa-solid fa-xmark"></i>
      </button>
    </div>

    <!-- 输入区 -->
    <div class="nlnoc-composer">
      <textarea
        ref="inputRef"
        v-model="input"
        class="nlnoc-input"
        rows="1"
        maxlength="1000"
        placeholder="发消息…"
        @input="growInput"
        @keydown="onKeydown"
      ></textarea>
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
      <button
        v-if="menu.msg.sender_id === myId && !menu.msg.is_recalled"
        type="button"
        class="nlnoc-danger"
        @click="recallMsg"
      >
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

/* 页头头像 40：比 36 的返回键/发送键大一号，比列表 42 视觉接得上 */
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

/* ===== 手机端（≤640px）：机身准全屏，输入字号抬到 16 防 iOS 聚焦缩放 ===== */
@media (max-width: 640px) {
  .nlnoc-input {
    font-size: 16px;
  }
}
</style>
