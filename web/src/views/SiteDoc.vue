<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import apiClient from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { isSuperAdmin } from '@/utils/permissions'
import { renderRichText } from '@/utils/markdown'
import MarkdownSplitEditor from '@/components/MarkdownSplitEditor.vue'

interface SiteDoc {
  key: string
  title: string
  content: string
  updated_at: string | null
}

interface SiteDocLog {
  id: number
  editor: { id: number | null; username: string; user_number: number | null; avatar_url: string }
  old_title: string
  new_title: string
  old_content: string
  new_content: string
  created_at: string | null
}

const route = useRoute()
const authStore = useAuthStore()

const docKey = computed(() => String((route.meta as any).docKey || 'help'))
const fallbackTitle = computed(() => String((route.meta as any).docTitle || '文档'))

const doc = ref<SiteDoc>({ key: '', title: '', content: '', updated_at: null })
const loading = ref(true)
const error = ref('')
const editing = ref(false)
const saving = ref(false)
const saved = ref(false)
const draftTitle = ref('')
const draftContent = ref('')

// 秩序管理（社管及以上）：超管/社管
const isOrderAdmin = computed(() => {
  const u = authStore.currentUser
  if (!u) return false
  return isSuperAdmin(u) || u.can_manage_posts === true
})
const heading = computed(() => doc.value.title || fallbackTitle.value)
const rendered = computed(() => renderRichText(doc.value.content || ''))
const hasContent = computed(() => (doc.value.content || '').trim().length > 0)

// 修改日志（仅秩序管理可见）
const logs = ref<SiteDocLog[]>([])
const logsLoading = ref(false)
const logsOpen = ref(false)

const fmtTime = (iso: string | null) => {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const loadLogs = async () => {
  if (!isOrderAdmin.value) return
  logsLoading.value = true
  try {
    const data: any = await apiClient.get(`/api/site-docs/${docKey.value}/logs`)
    logs.value = Array.isArray(data?.logs) ? data.logs : []
  } catch {
    logs.value = []
  } finally {
    logsLoading.value = false
  }
}

const toggleLogs = () => {
  logsOpen.value = !logsOpen.value
  if (logsOpen.value && logs.value.length === 0) loadLogs()
}

const updatedText = computed(() => {
  if (!doc.value.updated_at) return ''
  const d = new Date(doc.value.updated_at)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
})

const load = async () => {
  loading.value = true
  error.value = ''
  editing.value = false
  saved.value = false
  try {
    const data: any = await apiClient.get(`/api/site-docs/${docKey.value}`)
    doc.value = {
      key: data?.key || docKey.value,
      title: data?.title || '',
      content: data?.content || '',
      updated_at: data?.updated_at || null,
    }
  } catch (err: any) {
    error.value = err?.response?.data?.detail || '文档加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

const startEdit = () => {
  draftTitle.value = doc.value.title || ''
  draftContent.value = doc.value.content || ''
  saved.value = false
  editing.value = true
}

const cancelEdit = () => {
  editing.value = false
}

const save = async () => {
  saving.value = true
  error.value = ''
  saved.value = false
  try {
    const data: any = await apiClient.put(`/api/site-docs/${docKey.value}`, {
      title: draftTitle.value,
      content: draftContent.value,
    })
    doc.value = {
      key: data?.key || docKey.value,
      title: data?.title || '',
      content: data?.content || '',
      updated_at: data?.updated_at || null,
    }
    editing.value = false
    saved.value = true
    loadLogs()
  } catch (err: any) {
    error.value = err?.response?.data?.detail || '保存失败，请稍后重试'
  } finally {
    saving.value = false
  }
}

watch(docKey, () => {
  logs.value = []
  logsOpen.value = false
  load()
})
onMounted(load)
</script>

<template>
  <div class="doc-page">
    <header class="doc-header">
      <div class="doc-heading">
        <p class="eyebrow">NLNOJ / DOCUMENT</p>
        <h1>{{ heading }}</h1>
        <p v-if="updatedText" class="doc-meta">最后更新：{{ updatedText }}</p>
      </div>
      <div class="doc-actions">
        <button v-if="isOrderAdmin && !editing" class="btn btn-primary" @click="startEdit">
          <i class="fa-solid fa-pen"></i> 编辑
        </button>
        <template v-else-if="isOrderAdmin && editing">
          <button class="btn" :disabled="saving" @click="cancelEdit">取消</button>
          <button class="btn btn-primary" :disabled="saving" @click="save">
            <i class="fa-solid fa-check"></i> {{ saving ? '保存中...' : '保存' }}
          </button>
        </template>
      </div>
    </header>

    <div v-if="error" class="notice error"><i class="fa-solid fa-circle-exclamation"></i>{{ error }}</div>
    <div v-if="saved" class="notice ok"><i class="fa-solid fa-circle-check"></i>已保存</div>

    <div v-if="loading" class="doc-empty">正在加载...</div>

    <template v-else>
      <section v-if="editing" class="doc-editor">
        <input v-model="draftTitle" class="title-input" maxlength="100" placeholder="文档标题">
        <MarkdownSplitEditor
          v-model="draftContent"
          height="480px"
          :maxlength="100000"
          placeholder="使用 Markdown 编写内容..."
        />
      </section>

      <section v-else-if="hasContent" class="doc-body prose" v-html="rendered"></section>
      <div v-else class="doc-empty">
        <i class="fa-regular fa-file-lines"></i>
        <p>这里还没有内容</p>
        <button v-if="isOrderAdmin" class="btn btn-primary" @click="startEdit">去编写</button>
      </div>
    </template>

    <!-- 修改日志（仅秩序管理可见） -->
    <section v-if="isOrderAdmin && !loading" class="logs-card">
      <button class="logs-toggle" @click="toggleLogs">
        <i class="fa-solid" :class="logsOpen ? 'fa-chevron-down' : 'fa-chevron-right'"></i>
        修改日志
        <span v-if="logs.length" class="logs-count">{{ logs.length }}</span>
        <span class="logs-tip">仅秩序管理可见</span>
      </button>
      <div v-if="logsOpen" class="logs-body">
        <div v-if="logsLoading" class="logs-empty">正在加载...</div>
        <div v-else-if="logs.length === 0" class="logs-empty">暂无修改记录</div>
        <div v-for="log in logs" :key="log.id" class="log-item">
          <div class="log-head">
            <img v-if="log.editor?.avatar_url" :src="log.editor.avatar_url" class="log-avatar" alt="">
            <i v-else class="fa-solid fa-circle-user log-avatar-icon"></i>
            <span class="log-editor">{{ log.editor?.username || '已删除' }}</span>
            <span v-if="log.editor?.user_number != null" class="log-uid">#{{ log.editor.user_number }}</span>
            <span class="log-time">{{ fmtTime(log.created_at) }}</span>
          </div>
          <div class="log-changes">
            <div v-if="log.old_title !== log.new_title" class="log-line">
              标题：<s v-if="log.old_title">{{ log.old_title }}</s><span v-else>（无）</span>
              → <b>{{ log.new_title || '（无）' }}</b>
            </div>
            <div v-else class="log-line muted">标题未变：{{ log.new_title || '（无）' }}</div>
            <div class="log-line">
              内容：<template v-if="log.old_content === log.new_content"><span class="muted">未变化</span></template>
              <template v-else>{{ log.old_content.length }} 字 → <b>{{ log.new_content.length }} 字</b></template>
            </div>
            <details v-if="log.old_content !== log.new_content" class="log-detail">
              <summary>查看修改前 / 修改后内容</summary>
              <div class="log-snapshot">
                <div class="snapshot-label">修改前</div>
                <pre>{{ log.old_content || '（空）' }}</pre>
              </div>
              <div class="log-snapshot">
                <div class="snapshot-label">修改后</div>
                <pre>{{ log.new_content || '（空）' }}</pre>
              </div>
            </details>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.doc-page {
  max-width: 900px;
  margin: 0 auto;
  padding: 32px clamp(16px, 4vw, 40px) 72px;
  color: var(--text-strong);
}

.doc-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
  margin-bottom: 22px;
}

.eyebrow {
  margin: 0 0 8px;
  color: var(--primary);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 1.6px;
}

.doc-heading h1 {
  margin: 0;
  font-size: 28px;
  line-height: 1.25;
  color: var(--text-strong);
}

.doc-meta {
  margin: 8px 0 0;
  color: var(--text-sub);
  font-size: 12px;
}

.doc-actions {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}

.btn {
  padding: 9px 16px;
  border: 1px solid #dce3ee;
  border-radius: 9px;
  background: var(--surface-plain);
  color: var(--text-sub);
  font: inherit;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.btn:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  border-color: transparent;
  background: var(--primary);
  color: #fff;
}

.btn-primary:hover:not(:disabled) {
  filter: brightness(1.06);
  color: #fff;
}

.notice {
  margin-bottom: 16px;
  padding: 11px 15px;
  border-radius: 10px;
  font-size: 13px;
}

.notice i {
  margin-right: 8px;
}

.notice.error {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
color: var(--danger-text);
}

.notice.ok {
  background: color-mix(in srgb, var(--success) 10%, transparent);
color: var(--success-text);
}

.doc-body {
  padding: 26px 28px;
  border: 1px solid #e6ebf3;
  border-radius: 16px;
  background: var(--surface-plain);
  box-shadow: 0 8px 24px rgba(42, 58, 83, 0.05);
  line-height: 1.75;
}

.doc-editor {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.title-input {
  padding: 11px 14px;
  border: 1px solid #dbe3ef;
  border-radius: 10px;
  font: inherit;
  font-size: 15px;
  font-weight: 700;
  color: var(--text-strong);
}

.title-input:focus {
  outline: 2px solid rgba(92, 101, 207, 0.16);
  border-color: var(--primary);
}

.doc-empty {
  display: flex;
  min-height: 240px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  border: 1px dashed #d5deeb;
  border-radius: 16px;
  color: var(--text-sub);
  font-size: 14px;
}

.doc-empty i {
  font-size: 30px;
  color: #b4bfd0;
}

/* ===== 修改日志（仅秩序管理可见） ===== */
.logs-card {
  margin-top: 20px;
  border: 1px solid #e6ebf3;
  border-radius: 14px;
  background: var(--surface-plain);
  overflow: hidden;
}

.logs-toggle {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 8px;
  padding: 13px 18px;
  border: none;
  background: var(--bg-subtle);
  color: var(--text-sub);
  font: inherit;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.logs-toggle:hover {
  color: var(--primary);
}

.logs-count {
  padding: 1px 8px;
  border-radius: 10px;
  background: var(--primary);
  color: #fff;
  font-size: 11px;
}

.logs-tip {
  margin-left: auto;
  color: #9aa8bd;
  font-size: 11px;
  font-weight: 500;
}

.logs-body {
  padding: 6px 18px 14px;
}

.logs-empty {
  padding: 18px 0;
  color: var(--text-sub);
  font-size: 13px;
  text-align: center;
}

.log-item {
  padding: 13px 0;
  border-bottom: 1px dashed #e6ebf3;
}

.log-item:last-child {
  border-bottom: none;
}

.log-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 7px;
}

.log-avatar {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  object-fit: cover;
}

.log-avatar-icon {
  font-size: 22px;
  color: #b4bfd0;
}

.log-editor {
  font-weight: 700;
  font-size: 13px;
  color: var(--text-strong);
}

.log-uid {
  color: #9aa8bd;
  font-size: 12px;
}

.log-time {
  margin-left: auto;
  color: #9aa8bd;
  font-size: 12px;
}

.log-line {
  font-size: 13px;
  color: var(--text-sub);
  line-height: 1.7;
}

.log-line.muted {
  color: #9aa8bd;
}

.log-detail {
  margin-top: 8px;
}

.log-detail summary {
  cursor: pointer;
  color: var(--primary);
  font-size: 12px;
  font-weight: 600;
}

.log-snapshot {
  margin-top: 10px;
}

.snapshot-label {
  margin-bottom: 5px;
  color: var(--text-sub);
  font-size: 11px;
  font-weight: 700;
}

.log-snapshot pre {
  max-height: 260px;
  overflow: auto;
  padding: 10px 12px;
  border: 1px solid #e6ebf3;
  border-radius: 10px;
  background: var(--bg-subtle);
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-sub);
}

@media (max-width: 640px) {
  .doc-header {
    flex-direction: column;
  }
}
</style>
