<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import apiClient from '@/api/client'
import { useAuthStore } from '@/stores/auth'

interface ConversationBrief {
  id: number
  type: string
  title: string | null
  avatar_url?: string | null
  is_private: boolean
  owner_id: number | null
  member_count: number
  last_message_at: string | null
  last_message_content: string | null
  created_at: string
}

interface MemberBrief {
  user_id: number
  username: string
  role: string
  joined_at: string
}

interface ConversationDetail {
  id: number
  type: string
  title: string | null
  avatar_url?: string | null
  is_private: boolean
  owner_id: number | null
  member_count: number
  members: MemberBrief[]
  created_at: string
}

interface MessageBrief {
  id: number
  sender_id: number | null
  sender_username: string | null
  content: string
  is_recalled: boolean
  created_at: string
}

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const conversations = ref<ConversationBrief[]>([])
const listLoading = ref(false)
const activeId = ref<number>(Number(route.params.conversationId) || 0)

const detail = ref<ConversationDetail | null>(null)
const messages = ref<MessageBrief[]>([])
const messagesLoading = ref(false)
const draft = ref('')
const sending = ref(false)
const error = ref('')
const notice = ref('')

// 新建群组
const showCreate = ref(false)
const createTitle = ref('')
const createMembers = ref('')

// 邀请成员 / 改名
const inviteIds = ref('')
const newTitle = ref('')

const meId = computed(() => authStore.currentUser?.id || 0)

/** 头像 URL 加载失败：隐藏叠放的 img，露出底层的占位字符 */
const onAvaError = (e: Event) => {
  const t = e.currentTarget as HTMLImageElement | null
  if (t) t.style.display = 'none'
}
const myRole = computed(() => {
  const m = detail.value?.members.find((x) => x.user_id === meId.value)
  return m?.role || ''
})
const canManage = computed(() => myRole.value === 'owner' || myRole.value === 'admin')
const isOwner = computed(() => myRole.value === 'owner')

const fmtTime = (iso: string | null) => {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const roleLabel = (r: string) => (r === 'owner' ? '群主' : r === 'admin' ? '管理员' : '成员')

const flash = (msg: string) => {
  notice.value = msg
  setTimeout(() => {
    notice.value = ''
  }, 2500)
}

const parseIds = (raw: string): number[] =>
  raw
    .split(/[\s,，]+/)
    .map((s) => Number(s))
    .filter((n) => Number.isInteger(n) && n > 0)

const loadList = async () => {
  listLoading.value = true
  try {
    const data: any = await apiClient.get('/api/conversations')
    conversations.value = Array.isArray(data?.items) ? data.items : []
  } catch (err: any) {
    error.value = err?.response?.data?.detail || '加载会话列表失败'
  } finally {
    listLoading.value = false
  }
}

const loadDetail = async () => {
  if (!activeId.value) {
    detail.value = null
    messages.value = []
    return
  }
  try {
    const data: any = await apiClient.get(`/api/conversations/${activeId.value}`)
    detail.value = data
    newTitle.value = data?.title || ''
  } catch (err: any) {
    error.value = err?.response?.data?.detail || '加载群信息失败'
    detail.value = null
  }
}

const loadMessages = async () => {
  if (!activeId.value) return
  messagesLoading.value = true
  try {
    const data: any = await apiClient.get(`/api/conversations/${activeId.value}/messages`)
    messages.value = Array.isArray(data?.messages) ? data.messages : []
  } catch (err: any) {
    error.value = err?.response?.data?.detail || '加载消息失败'
  } finally {
    messagesLoading.value = false
  }
}

const openConversation = async (id: number) => {
  activeId.value = id
  router.replace({ name: 'GroupChat', params: { conversationId: String(id) } })
  await Promise.all([loadDetail(), loadMessages()])
}

const send = async () => {
  const content = draft.value.trim()
  if (!content || sending.value || !activeId.value) return
  sending.value = true
  try {
    await apiClient.post(`/api/conversations/${activeId.value}/messages`, { content })
    draft.value = ''
    await loadMessages()
    await loadList()
  } catch (err: any) {
    error.value = err?.response?.data?.detail || '发送失败'
  } finally {
    sending.value = false
  }
}

const recall = async (m: MessageBrief) => {
  if (!confirm('确认撤回这条消息？')) return
  try {
    await apiClient.post(`/api/conversations/${activeId.value}/messages/${m.id}/recall`)
    await loadMessages()
  } catch (err: any) {
    error.value = err?.response?.data?.detail || '撤回失败'
  }
}

const removeMsg = async (m: MessageBrief) => {
  if (!confirm('确认删除这条消息？')) return
  try {
    await apiClient.delete(`/api/conversations/${activeId.value}/messages/${m.id}`)
    await loadMessages()
  } catch (err: any) {
    error.value = err?.response?.data?.detail || '删除失败'
  }
}

const submitCreate = async () => {
  error.value = ''
  if (!createTitle.value.trim()) {
    error.value = '请输入群组名称'
    return
  }
  try {
    const data: any = await apiClient.post('/api/conversations', {
      type: 'group',
      title: createTitle.value.trim(),
      member_ids: parseIds(createMembers.value)
    })
    showCreate.value = false
    createTitle.value = ''
    createMembers.value = ''
    await loadList()
    await openConversation(data.id)
    flash('群组创建成功')
  } catch (err: any) {
    error.value = err?.response?.data?.detail || '创建失败'
  }
}

const submitInvite = async () => {
  const ids = parseIds(inviteIds.value)
  if (!ids.length) {
    error.value = '请输入要邀请的 UID'
    return
  }
  try {
    await apiClient.post(`/api/conversations/${activeId.value}/members`, { member_ids: ids })
    inviteIds.value = ''
    await loadDetail()
    flash('邀请成功')
  } catch (err: any) {
    error.value = err?.response?.data?.detail || '邀请失败'
  }
}

const kick = async (m: MemberBrief) => {
  if (!confirm(`确认将 ${m.username} 移出群组？`)) return
  try {
    await apiClient.delete(`/api/conversations/${activeId.value}/members/${m.user_id}`)
    await loadDetail()
    flash('已移除')
  } catch (err: any) {
    error.value = err?.response?.data?.detail || '移除失败'
  }
}

const toggleAdmin = async (m: MemberBrief) => {
  const role = m.role === 'admin' ? 'member' : 'admin'
  try {
    await apiClient.put(`/api/conversations/${activeId.value}/members/${m.user_id}/role`, { role })
    await loadDetail()
    flash(role === 'admin' ? '已设为管理员' : '已取消管理员')
  } catch (err: any) {
    error.value = err?.response?.data?.detail || '操作失败'
  }
}

const saveTitle = async () => {
  if (!newTitle.value.trim()) return
  try {
    await apiClient.put(`/api/conversations/${activeId.value}`, { title: newTitle.value.trim() })
    await Promise.all([loadDetail(), loadList()])
    flash('群名已更新')
  } catch (err: any) {
    error.value = err?.response?.data?.detail || '更新失败'
  }
}

const canRecall = (m: MessageBrief) =>
  !m.is_recalled && (m.sender_id === meId.value || canManage.value)
const canDelete = (m: MessageBrief) => m.sender_id === meId.value

watch(
  () => route.params.conversationId,
  (v) => {
    const id = Number(v) || 0
    if (id !== activeId.value) {
      activeId.value = id
      void loadDetail()
      void loadMessages()
    }
  }
)

onMounted(async () => {
  await loadList()
  if (activeId.value) {
    await Promise.all([loadDetail(), loadMessages()])
  }
})
</script>

<template>
  <div class="gc-page">
    <div v-if="error" class="gc-banner error">{{ error }}</div>
    <div v-if="notice" class="gc-banner ok">{{ notice }}</div>

    <div class="gc-layout">
      <!-- 左侧：会话列表 -->
      <aside class="gc-side">
        <div class="gc-side-head">
          <span class="gc-side-title">群组与私聊</span>
          <button class="gc-btn primary sm" @click="showCreate = true">新建群组</button>
        </div>
        <div v-if="listLoading" class="gc-empty">加载中…</div>
        <div v-else-if="conversations.length === 0" class="gc-empty">暂无会话，先新建一个群组吧</div>
        <div v-else class="gc-conv-list">
          <button
            v-for="c in conversations"
            :key="c.id"
            class="gc-conv"
            :class="{ active: c.id === activeId }"
            @click="openConversation(c.id)"
          >
            <span class="gc-conv-avatar">
              {{ (c.title || '群').charAt(0) }}
              <img
                v-if="c.avatar_url"
                :src="c.avatar_url"
                class="gc-ava-img"
                alt=""
                @error="onAvaError"
              />
            </span>
            <span class="gc-conv-main">
              <span class="gc-conv-name">{{ c.title || '未命名群组' }}</span>
              <span class="gc-conv-last">{{ c.last_message_content || '暂无消息' }}</span>
            </span>
            <span class="gc-conv-count">{{ c.member_count }}人</span>
          </button>
        </div>
      </aside>

      <!-- 右侧：会话详情 -->
      <section class="gc-main">
        <div v-if="!detail" class="gc-empty big">请选择或创建一个群组</div>
        <template v-else>
          <header class="gc-head">
            <span class="gc-head-ava gc-conv-avatar">
              {{ (detail.title || '群').charAt(0) }}
              <img
                v-if="detail.avatar_url"
                :src="detail.avatar_url"
                class="gc-ava-img"
                alt=""
                @error="onAvaError"
              />
            </span>
            <div class="gc-head-info">
              <h2 class="gc-title">{{ detail.title || '未命名群组' }}</h2>
              <span class="gc-sub">{{ detail.member_count }} 名成员</span>
            </div>
          </header>

          <div class="gc-members">
            <div class="gc-members-head">成员</div>
            <div class="gc-members-list">
              <div v-for="m in detail.members" :key="m.user_id" class="gc-member">
                <span class="gc-member-name">{{ m.username }}</span>
                <span class="gc-role" :class="m.role">{{ roleLabel(m.role) }}</span>
                <span class="gc-member-actions">
                  <button
                    v-if="isOwner && m.role !== 'owner'"
                    class="gc-link"
                    @click="toggleAdmin(m)"
                  >{{ m.role === 'admin' ? '取消管理' : '设为管理' }}</button>
                  <button
                    v-if="canManage && m.role !== 'owner' && m.user_id !== meId"
                    class="gc-link danger"
                    @click="kick(m)"
                  >移除</button>
                </span>
              </div>
            </div>

            <div v-if="canManage" class="gc-invite">
              <input
                v-model="inviteIds"
                class="gc-input"
                placeholder="邀请 UID，逗号分隔"
              />
              <button class="gc-btn" @click="submitInvite">邀请</button>
            </div>
            <div v-if="canManage" class="gc-invite">
              <input v-model="newTitle" class="gc-input" placeholder="修改群名称" />
              <button class="gc-btn" @click="saveTitle">保存群名</button>
            </div>
          </div>

          <div class="gc-msg-box">
            <div v-if="messagesLoading" class="gc-empty">加载中…</div>
            <div v-else-if="messages.length === 0" class="gc-empty">暂无消息</div>
            <div v-for="m in messages" v-else :key="m.id" class="gc-msg" :class="{ mine: m.sender_id === meId }">
              <div class="gc-msg-meta">
                <span class="gc-msg-sender">{{ m.sender_username || '已注销用户' }}</span>
                <span class="gc-msg-time">{{ fmtTime(m.created_at) }}</span>
              </div>
              <div class="gc-msg-body">
                <span v-if="m.is_recalled" class="gc-recalled">（消息已撤回）</span>
                <span v-else>{{ m.content }}</span>
              </div>
              <div class="gc-msg-tools">
                <button v-if="canRecall(m)" class="gc-link" @click="recall(m)">撤回</button>
                <button v-if="canDelete(m)" class="gc-link danger" @click="removeMsg(m)">删除</button>
              </div>
            </div>
          </div>

          <footer class="gc-input-row">
            <input
              v-model="draft"
              class="gc-input flex"
              placeholder="输入消息…"
              @keyup.enter="send"
            />
            <button class="gc-btn primary" :disabled="sending || !draft.trim()" @click="send">
              {{ sending ? '发送中…' : '发送' }}
            </button>
          </footer>
        </template>
      </section>
    </div>

    <!-- 新建群组弹窗 -->
    <div v-if="showCreate" class="gc-modal-mask" @click.self="showCreate = false">
      <div class="gc-modal">
        <h3 class="gc-modal-title">新建群组</h3>
        <label class="gc-label">群组名称</label>
        <input v-model="createTitle" class="gc-input" placeholder="给群组起个名字" />
        <label class="gc-label">初始成员 UID（可留空，逗号分隔）</label>
        <input v-model="createMembers" class="gc-input" placeholder="例如：2, 5, 8" />
        <div class="gc-modal-actions">
          <button class="gc-btn" @click="showCreate = false">取消</button>
          <button class="gc-btn primary" @click="submitCreate">创建</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.gc-page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 20px;
}
.gc-banner {
  padding: 10px 14px;
  border-radius: var(--radius-md);
  margin-bottom: 12px;
  font-size: 14px;
}
.gc-banner.error { background: color-mix(in srgb, var(--danger) 10%, transparent);color: var(--danger-text); border: 1px solid #fecaca; }
.gc-banner.ok { background: color-mix(in srgb, var(--success) 10%, transparent);color: var(--success-text); border: 1px solid #a7f3d0; }

.gc-layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 16px;
  align-items: start;
}

.gc-side,
.gc-main {
  background: var(--surface);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}

.gc-side { padding: 14px; }
.gc-side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.gc-side-title { font-weight: 700; color: var(--text-main); }

.gc-conv-list { display: flex; flex-direction: column; gap: 6px; }
.gc-conv {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border: var(--border-width) solid transparent;
  border-radius: var(--radius-md);
  background: var(--surface-strong);
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.gc-conv:hover { border-color: var(--border-color); }
.gc-conv.active { border-color: var(--primary); background: color-mix(in srgb, var(--primary) 8%, transparent); }
.gc-conv-avatar {
  position: relative; /* 群头像 URL 图片叠在占位字符上 */
  width: 32px; height: 32px; flex-shrink: 0;
  border-radius: 50%;
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--primary); color: #fff; font-weight: 600;
}
.gc-ava-img {
  position: absolute; inset: 0;
  width: 100%; height: 100%;
  object-fit: cover; border-radius: 50%;
  display: block;
}
.gc-conv-main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.gc-conv-name { font-size: 14px; font-weight: 600; color: var(--text-main); }
.gc-conv-last {
  font-size: 12px; color: var(--text-sub);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.gc-conv-count { font-size: 11px; color: var(--text-sub); flex-shrink: 0; }

.gc-main { padding: 16px 18px; min-height: 420px; }
.gc-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.gc-head-ava { width: 40px; height: 40px; font-size: 16px; }
.gc-title { margin: 0; font-size: 18px; font-weight: 700; color: var(--text-main); }
.gc-sub { font-size: 12px; color: var(--text-sub); }

.gc-members { border-top: 1px dashed var(--border-color); padding-top: 12px; margin-bottom: 12px; }
.gc-members-head { font-size: 13px; font-weight: 600; color: var(--text-sub); margin-bottom: 8px; }
.gc-members-list { display: flex; flex-wrap: wrap; gap: 8px; }
.gc-member {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 4px 10px;
  border: var(--border-width) solid var(--border-color);
  border-radius: 999px;
  background: var(--surface-strong);
  font-size: 13px;
}
.gc-member-name { color: var(--text-main); font-weight: 500; }
.gc-role { font-size: 11px; padding: 1px 8px; border-radius: 999px; background: rgba(148,163,184,.22); color: var(--text-sub); }
.gc-role.owner { background: rgba(244,63,94,.14); color: #e11d48; }
.gc-role.admin { background: rgba(245,158,11,.16);color: light-dark(#b45309, #fbbf24); }
.gc-member-actions { display: inline-flex; gap: 8px; }

.gc-invite { display: flex; gap: 8px; margin-top: 10px; }

.gc-msg-box {
  height: 320px;
  overflow-y: auto;
  padding: 10px;
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--surface-strong);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.gc-msg { padding: 8px 10px; border-radius: var(--radius-md); background: var(--surface); }
.gc-msg.mine { background: color-mix(in srgb, var(--primary) 8%, transparent); }
.gc-msg-meta { display: flex; gap: 10px; align-items: baseline; margin-bottom: 2px; }
.gc-msg-sender { font-size: 12px; font-weight: 600; color: var(--text-main); }
.gc-msg-time { font-size: 11px; color: var(--text-sub); }
.gc-msg-body { font-size: 14px; color: var(--text-main); word-break: break-word; }
.gc-recalled { color: var(--text-sub); font-style: italic; }
.gc-msg-tools { display: flex; gap: 10px; margin-top: 4px; }

.gc-input-row { display: flex; gap: 8px; margin-top: 12px; }

.gc-input {
  padding: 8px 12px;
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--surface-strong);
  color: var(--text-main);
  font-size: 14px;
  outline: none;
}
.gc-input:focus { border-color: var(--primary); }
.gc-input.flex { flex: 1; }

.gc-btn {
  padding: 8px 16px;
  border: none;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.22);
  color: var(--text-main);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}
.gc-btn:hover { background: rgba(148, 163, 184, 0.34); }
.gc-btn.primary { background: var(--primary); color: #fff; }
.gc-btn.primary:hover { background: var(--primary-hover); }
.gc-btn.sm { padding: 5px 12px; font-size: 12px; }
.gc-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.gc-link {
  background: none;
  border: none;
  padding: 0;
  font-size: 12px;
  color: var(--primary);
  cursor: pointer;
}
.gc-link:hover { text-decoration: underline; }
.gc-link.danger { color: #e11d48; }

.gc-empty { padding: 30px 10px; text-align: center; color: var(--text-sub); font-size: 13px; }
.gc-empty.big { padding: 120px 10px; }

.gc-modal-mask {
  position: fixed; inset: 0;
  background: rgba(15, 23, 42, 0.35);
  display: flex; align-items: center; justify-content: center;
  z-index: 50;
}
.gc-modal {
  width: 420px; max-width: 92vw;
  background: var(--surface);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: 20px;
}
.gc-modal-title { margin: 0 0 12px; font-size: 16px; font-weight: 700; color: var(--text-main); }
.gc-label { display: block; font-size: 13px; color: var(--text-sub); margin: 10px 0 4px; }
.gc-modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
.gc-modal .gc-input { width: 100%; box-sizing: border-box; }

@media (max-width: 768px) {
  .gc-layout { grid-template-columns: 1fr; }
}
</style>
