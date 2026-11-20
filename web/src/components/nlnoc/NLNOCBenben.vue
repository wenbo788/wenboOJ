<script setup lang="ts">
/**
 * NLNOC「全服犇犇」会话 —— 就是首页那条犇犇流，换成群聊形态展示。
 *
 * 同源保证：读写都走 /benben 系列端点（GET 列表 / POST 发布），
 * 首页发的这里看得到，这里发的首页也看得到，不存在第二份数据。
 *
 * 列表方向：后端返回新→旧（首页Feed 用），聊天要旧→新，进页 reverse；
 * 轮询用 after_id 取比屏顶更新的动态，append 到底部。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import apiClient from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { letterAvatar } from '@/utils/avatar'
import { renderRichText } from '@/utils/markdown'
import { userNameColor } from '@/utils/userColor'
import UserAvatarStatus from '@/components/UserAvatarStatus.vue'

const emit = defineEmits<{ back: [] }>()

interface BenbenItem {
  id: number
  user_number: number
  username: string
  avatar_url?: string | null
  is_admin?: boolean
  is_super_admin?: boolean
  is_banned?: boolean
  is_cheater?: boolean
  can_manage_users?: boolean
  can_manage_posts?: boolean
  can_manage_problems?: boolean
  username_color?: string | null
  user_tag?: string | null
  content: string
  created_at: string
  is_owner?: boolean
  /** 该条回复了谁（后端数据字段；频道内不展示该提示） */
  reply_to_username?: string | null
  /** 在线状态（后端 benben_dict 返回，头像在线点用） */
  last_seen?: string | null
}

const authStore = useAuthStore()
const list = ref<BenbenItem[]>([])
const loading = ref(true)
const input = ref('')
const sending = ref(false)
const sendError = ref('')
const listRef = ref<HTMLElement | null>(null)
const inputRef = ref<HTMLTextAreaElement | null>(null)

const myNumber = computed(() => authStore.currentUser?.user_number ?? -1)
const isMine = (item: BenbenItem) =>
  item.is_owner === true || item.user_number === myNumber.value

const avatarOf = (item: BenbenItem) => item.avatar_url || letterAvatar(item.username)

const hhmm = (iso: string) => {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
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

const nearBottom = () => {
  const el = listRef.value
  return !el || el.scrollHeight - el.scrollTop - el.clientHeight < 140
}

/* ---------------- 加载与轮询 ---------------- */

const loadError = ref('')

const loadInitial = async () => {
  try {
    const data: any = await apiClient.get('/benben', { params: { limit: 30 } })
    list.value = [...(Array.isArray(data) ? data : [])].reverse()
  } catch (err: any) {
    // 显性失败：静默吞异常会让人以为「动态都没了」，亮出错误并给重试入口
    loadError.value = err?.response?.data?.detail || err?.message || '加载犇犇失败'
  } finally {
    // 先撤 loading 再滚：loading 期间消息 DOM 未渲染，滚动作用在占位上无效
    loading.value = false
  }
  await scrollToBottom()
}

/** 加载失败后的重试 */
const retryLoad = () => {
  loadError.value = ''
  loading.value = true
  void loadInitial()
}

// 防重入：后台挂久了切回前台的瞬间，节流挤压出的 interval tick 和 visibilitychange
// 补刷会同时开跑，两轮拿同一个 after_id 取到同一批新条目会各追加一次（显示两遍）。
let polling = false

const poll = async () => {
  if (polling || document.visibilityState !== 'visible' || list.value.length === 0) return
  polling = true
  try {
    const topId = list.value[list.value.length - 1].id
    const data: any = await apiClient.get('/benben', {
      params: { limit: 50, after_id: topId },
    })
    const fresh: BenbenItem[] = Array.isArray(data) ? data : []
    if (fresh.length) {
      const stick = nearBottom()
      // 去重兜底：send() 乐观插入与在途轮询撞车时，刚发的动态会两边各来一次
      const seen = new Set(list.value.map((it) => it.id))
      const add = fresh.filter((it) => !seen.has(it.id))
      if (add.length) {
        list.value.push(...add.reverse())
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

/* ---------------- 发布 ---------------- */

/** 回复某条犇犇：与首页同一套交互——文本框塞前缀、光标回开头，所见即所得 */
const replyingId = ref<number | null>(null)
const replyingName = ref<string | null>(null)

const replyTo = (item: BenbenItem) => {
  replyingId.value = item.id
  replyingName.value = item.username
  input.value = ` || @${item.username} : ${item.content}`
  nextTick(() => {
    const el = inputRef.value
    if (el) {
      el.focus()
      el.setSelectionRange(0, 0)
      el.scrollTop = 0
      growInput({ target: el } as unknown as Event)
    }
  })
}

const send = async () => {
  const text = input.value.trim()
  if (!text || sending.value) return
  sending.value = true
  sendError.value = ''

  // 回复前缀校验（与首页同一套）：|| @用户名 : 开头才算回复，改没了就自动解绑
  let replyToId: number | null = null
  if (replyingId.value && replyingName.value) {
    if (text.startsWith(`|| @${replyingName.value} :`)) {
      replyToId = replyingId.value
    } else {
      replyingId.value = null
      replyingName.value = null
    }
  }

  try {
    const created: any = await apiClient.post('/benben', {
      content: text,
      ...(replyToId ? { reply_to: replyToId } : {}),
    })
    if (created?.id) list.value.push(created)
    input.value = ''
    replyingId.value = null
    replyingName.value = null
    if (inputRef.value) inputRef.value.style.height = 'auto'
    await scrollToBottom()
  } catch (err: any) {
    sendError.value = err?.response?.data?.detail || '发布失败，请稍后再试'
  } finally {
    sending.value = false
  }
}

const onKeydown = (e: KeyboardEvent) => {
  if (e.key !== 'Enter') return
  if (e.isComposing || (e as any).keyCode === 229) return
  if (e.shiftKey) return
  e.preventDefault()
  void send()
}

const growInput = (e: Event) => {
  const el = e.target as HTMLTextAreaElement
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 96)}px`
}

/** 切回标签页立即补一轮（与首页犇犇同款） */
const onTabVisible = () => {
  if (document.visibilityState === 'visible') void poll()
}

onMounted(async () => {
  await loadInitial()
  // 5s 一轮，与首页 REFRESH_INTERVAL 同节奏——频道消息不再「迟到」
  pollTimer = window.setInterval(poll, 5000)
  document.addEventListener('visibilitychange', onTabVisible)
})

onBeforeUnmount(() => {
  window.clearInterval(pollTimer)
  document.removeEventListener('visibilitychange', onTabVisible)
})
</script>

<template>
  <div class="nlnoc-page nlnoc-benben">
    <!-- 页头 -->
    <div class="nlnoc-bb-head">
      <button type="button" class="nlnoc-back" title="返回" @click="emit('back')">
        <i class="fa-solid fa-chevron-left"></i>
      </button>
      <span class="nlnoc-bb-avatar"><i class="fa-solid fa-bullhorn"></i></span>
      <div class="nlnoc-bb-id">
        <div class="nlnoc-bb-name">全服犇犇</div>
        <div class="nlnoc-bb-sub">全站公开 · 与首页同源</div>
      </div>
    </div>

    <!-- 消息流 -->
    <div ref="listRef" class="nlnoc-msgs">
      <div v-if="loading" class="nlnoc-msgs-tip">
        <i class="fa-solid fa-spinner fa-spin"></i>
      </div>
      <div v-else-if="loadError" class="nlnoc-empty">
        <i class="fa-solid fa-triangle-exclamation"></i>
        <p>{{ loadError }}</p>
        <button type="button" class="nlnoc-msgs-more" @click="retryLoad">重试</button>
      </div>
      <template v-else>
        <div v-if="list.length === 0" class="nlnoc-empty">
          <i class="fa-solid fa-bullhorn"></i>
          <p>还没有动态，来发第一条吧</p>
        </div>

        <div
          v-for="item in list"
          :key="item.id"
          class="nlnoc-msg"
          :class="isMine(item) ? 'mine' : 'theirs'"
        >
          <div v-if="!isMine(item)" class="nlnoc-msg-ava">
            <UserAvatarStatus :user="item" :size="7" class="nlnoc-ava-status">
              <img :src="avatarOf(item)" class="nlnoc-avatar-img xs" alt="" />
            </UserAvatarStatus>
          </div>
          <div class="nlnoc-msg-body">
            <div
              v-if="!isMine(item)"
              class="nlnoc-msg-name"
              :style="{ color: userNameColor(item) }"
            >
              <router-link
                class="nlnoc-ulink"
                :to="`/user/${item.user_number}`"
                title="查看用户主页"
              >{{ item.username }}</router-link>
              <span v-if="item.user_tag" class="nlnoc-msg-tag">{{ item.user_tag }}</span>
            </div>
            <div class="nlnoc-bubble" :class="{ mine: isMine(item) }">
              <div class="nlnoc-bubble-text prose" v-html="renderRichText(item.content)"></div>
            </div>
            <div class="nlnoc-msg-time">
              {{ hhmm(item.created_at) }}
              <button
                type="button"
                class="nlnoc-bb-reply-btn"
                title="回复这条犇犇"
                @click="replyTo(item)"
              >
                <i class="fa-solid fa-reply"></i> 回复
              </button>
            </div>
          </div>
        </div>
      </template>
    </div>

    <div v-if="sendError" class="nlnoc-send-error">
      <i class="fa-solid fa-circle-exclamation"></i> {{ sendError }}
    </div>

    <!-- 发布区（就是首页那个犇犇输入框的手机版） -->
    <div class="nlnoc-composer">
      <textarea
        ref="inputRef"
        v-model="input"
        class="nlnoc-input"
        rows="1"
        maxlength="2000"
        placeholder="发布一条犇犇…"
        @input="growInput"
        @keydown="onKeydown"
      ></textarea>
      <button
        type="button"
        class="nlnoc-send"
        :disabled="!input.trim() || sending"
        title="发布"
        @click="send"
      >
        <i :class="sending ? 'fa-solid fa-circle-notch fa-spin' : 'fa-solid fa-paper-plane'"></i>
      </button>
    </div>
  </div>
</template>

<style scoped>
/* ===== 页头 ===== */
.nlnoc-bb-head {
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
  width: 32px;
  height: 32px;
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

.nlnoc-bb-avatar {
  flex: none;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 13px;
  background: linear-gradient(135deg, var(--primary), var(--grad-violet));
  box-shadow: 0 3px 10px color-mix(in srgb, var(--primary) 35%, transparent);
}

.nlnoc-bb-id {
  flex: 1;
  min-width: 0;
}

.nlnoc-bb-name {
  font-size: 14.5px;
  font-weight: 700;
  color: var(--text-strong);
}

.nlnoc-bb-sub {
  font-size: 10.5px;
  color: #98a1b8;
}

/* ===== 消息气泡（复用 DM 的类名形态，但每条独立成组） ===== */
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
  margin-top: 9px;
}

.nlnoc-msg.mine {
  flex-direction: row-reverse;
}

.nlnoc-msg-ava {
  flex: none;
  width: 26px;
}

.nlnoc-avatar-img {
  border-radius: 50%;
  object-fit: cover;
  display: block;
}

.nlnoc-avatar-img.xs {
  width: 26px;
  height: 26px;
}

.nlnoc-msg-body {
  max-width: 78%;
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

/* 用户名跳主页的链接：吃继承色、去下划线，悬停示意可点 */
.nlnoc-ulink {
  color: inherit;
  text-decoration: none;
}

.nlnoc-ulink:hover {
  text-decoration: underline;
}

.nlnoc-msg-tag {
  display: inline-block;
  margin-left: 5px;
  padding: 0 5px;
  border-radius: 6px;
  background: rgba(15, 18, 32, 0.06);
  color: var(--text-sub);
  font-size: 9.5px;
}

.nlnoc-bubble {
  padding: 8px 12px;
  border-radius: 16px;
  border-top-left-radius: 6px;
  background: var(--surface-plain);
  color: var(--text-strong);
  box-shadow: 0 1px 4px rgba(15, 18, 32, 0.08);
  word-break: break-word;
  overflow-wrap: anywhere;
}

.nlnoc-bubble.mine {
  border-top-left-radius: 16px;
  border-top-right-radius: 6px;
  background: linear-gradient(135deg, var(--primary), var(--grad-indigo));
  color: #fff;
}

.nlnoc-bubble-text :deep(p) {
  margin: 0 0 0.4em;
}

.nlnoc-bubble-text :deep(p:last-child) {
  margin-bottom: 0;
}

.nlnoc-bubble-text :deep(a) {
  color: #2563eb;
}

.nlnoc-bubble.mine .nlnoc-bubble-text {
  color: #fff;
}

.nlnoc-bubble.mine .nlnoc-bubble-text :deep(a) {
  color: #cfe0ff;
}

.nlnoc-bubble.mine .nlnoc-bubble-text :deep(code) {
  background: rgba(255, 255, 255, 0.18);
  color: #ffe9a8;
}

.nlnoc-bubble-text :deep(img) {
  max-width: 100%;
  border-radius: 8px;
}

.nlnoc-msg-time {
  font-size: 9.5px;
  color: #b0b7ca;
  margin-top: 3px;
  padding: 0 4px;
}

/* ===== 发布错误 ===== */
.nlnoc-send-error {
  flex: none;
  padding: 5px 14px;
  background: color-mix(in srgb, var(--danger) 10%, transparent);
color: var(--danger-text);
  font-size: 11.5px;
}

/* ===== 犇犇回复（与首页同一套交互） ===== */
.nlnoc-bb-reply-btn {
  margin-left: 6px;
  padding: 0;
  border: none;
  background: none;
  font-family: inherit;
  font-size: 10.5px;
  color: var(--primary, #4a4ae0);
  opacity: 0.75;
  cursor: pointer;
}

.nlnoc-bb-reply-btn:hover {
  opacity: 1;
  text-decoration: underline;
}

/* ===== 发布区 ===== */
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
</style>
