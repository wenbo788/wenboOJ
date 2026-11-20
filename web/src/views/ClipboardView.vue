<script setup lang="ts">
/**
 * 云剪贴板：跨设备同步文字与代码片段。
 *
 * 功能：
 *   - 顶部切换「文本 / 代码」两种新建模式
 *   - 列表支持 kind 筛选与关键字搜索
 *   - 列表操作：复制、编辑、删除
 *   - 新建/编辑共用一个弹出面板
 *   - 代码条目支持选择语言（供高亮展示）
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Swal from 'sweetalert2'
import { clipboardsApi, type ClipboardListParams } from '@/api/clipboards'
import { copyText } from '@/utils/codeCopy'
import { fmtDateTime } from '@/utils/datetime'
import type { ClipboardItem, ClipboardKind } from '@/types'

const PAGE_SIZE = 20
const LANGS = ['plaintext', 'cpp', 'c', 'python', 'java', 'go', 'rust', 'javascript', 'typescript', 'csharp', 'php', 'bash', 'sql', 'html', 'css', 'markdown']

const limits = ref({ max_content_len: 20000, max_items: 50, max_code_items: 10 })

const items = ref<ClipboardItem[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(true)
const kind = ref<'all' | ClipboardKind>('all')
const keyword = ref('')
const copiedId = ref<number | null>(null)

const modal = ref(false)
const editingId = ref<number | null>(null)
const draftKind = ref<ClipboardKind>('text')
const draftTitle = ref('')
const draftLang = ref('plaintext')
const draftContent = ref('')
const submitting = ref(false)

let searchTimer: ReturnType<typeof setTimeout> | undefined
let copiedTimer: ReturnType<typeof setTimeout> | undefined

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

const titleLabel = computed(() => (editingId.value ? '编辑条目' : '新建条目'))

const draftLen = computed(() => draftContent.value.length)

const contentPlaceholder = computed(() => {
  if (draftKind.value === 'code') return '粘贴你的代码…'
  return '粘贴或键入要存下来的文字…'
})

function lenWarn() {
  return draftLen.value > limits.value.max_content_len
}

async function load() {
  loading.value = true
  try {
    const params: ClipboardListParams = { page: page.value, page_size: PAGE_SIZE }
    if (kind.value !== 'all') params.kind = kind.value
    if (keyword.value.trim()) params.q = keyword.value.trim()
    const r = await clipboardsApi.list(params)
    items.value = r.items
    total.value = r.total
  } catch (err: any) {
    Swal.fire('加载失败', err.response?.data?.detail || '请刷新页面重试', 'error')
  } finally {
    loading.value = false
  }
}

watch(kind, () => {
  page.value = 1
  void load()
})

watch(keyword, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    page.value = 1
    void load()
  }, 300)
})

function goPage(p: number) {
  if (p < 1 || p > totalPages.value || p === page.value) return
  page.value = p
  void load()
}

function openNew() {
  editingId.value = null
  draftKind.value = 'text'
  draftTitle.value = ''
  draftLang.value = 'plaintext'
  draftContent.value = ''
  modal.value = true
}

function openEdit(it: ClipboardItem) {
  editingId.value = it.id
  draftKind.value = it.kind
  draftTitle.value = it.title || ''
  draftLang.value = it.language || 'plaintext'
  draftContent.value = it.content
  modal.value = true
}

function closeModal() {
  modal.value = false
}

async function submit() {
  if (!draftContent.value.trim()) {
    Swal.fire('内容不能为空', '请先输入文本或代码', 'warning')
    return
  }
  if (lenWarn()) {
    Swal.fire('内容过长', `单条最多 ${limits.value.max_content_len} 字符`, 'warning')
    return
  }

  submitting.value = true
  try {
    if (editingId.value) {
      await clipboardsApi.update(editingId.value, {
        kind: draftKind.value,
        title: draftTitle.value.trim() || null,
        language: draftKind.value === 'code' ? draftLang.value : null,
        content: draftContent.value,
      })
    } else {
      await clipboardsApi.create({
        kind: draftKind.value,
        title: draftTitle.value.trim() || null,
        language: draftKind.value === 'code' ? draftLang.value : null,
        content: draftContent.value,
      })
    }
    modal.value = false
    page.value = 1
    await load()
  } catch (err: any) {
    Swal.fire('保存失败', err.response?.data?.detail || '请重试', 'error')
  } finally {
    submitting.value = false
  }
}

async function copyContent(it: ClipboardItem) {
  const ok = await copyText(it.content)
  if (!ok) {
    Swal.fire('复制失败', '请手动复制正文', 'error')
    return
  }
  copiedId.value = it.id
  clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => {
    copiedId.value = null
  }, 1500)
}

async function removeItem(it: ClipboardItem) {
  const res = await Swal.fire({
    title: '删除这一条？',
    text: '删除后不可恢复。',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonText: '删除',
    cancelButtonText: '取消',
    confirmButtonColor: '#e74c3c',
  })
  if (!res.isConfirmed) return
  try {
    await clipboardsApi.remove(it.id)
    if (items.value.length === 1 && page.value > 1) page.value--
    await load()
  } catch (err: any) {
    Swal.fire('删除失败', err.response?.data?.detail || '请重试', 'error')
  }
}

// limitsFailed：限额拉取失败标记。为 true 时本地限额不可信，
// 页面禁用新建入口并提示重试，避免用户按默认值造出超限内容、提交时才吃 400。
const limitsFailed = ref(false)

async function loadLimits() {
  limitsFailed.value = false
  try {
    const r = await clipboardsApi.getLimits()
    limits.value = r
  } catch (e: any) {
    limitsFailed.value = true
    console.warn('[clipboard] 获取服务端限额失败，本地限额校验不可用', e)
  }
}

onMounted(async () => {
  await loadLimits()
  void load()
})

onBeforeUnmount(() => {
  clearTimeout(searchTimer)
  clearTimeout(copiedTimer)
})
</script>

<template>
  <div class="clip-page">
    <div class="page-container">
      <h1 class="page-title">云剪贴板</h1>
      <p class="page-desc">登录账号后自动跨设备同步你的文本与代码片段，最多 {{ limits.max_items }} 条文本 / {{ limits.max_code_items }} 份代码。</p>

      <div class="card toolbar">
        <div class="filters">
          <button
            v-for="f in ([
              { key: 'all', label: '全部' },
              { key: 'text', label: '文本' },
              { key: 'code', label: '代码' },
            ] as const)"
            :key="f.key"
            type="button"
            class="chip"
            :class="{ 'is-active': kind === f.key }"
            @click="kind = f.key"
          >
            {{ f.label }}
          </button>

          <input
            v-model="keyword"
            class="search"
            type="search"
            placeholder="按标题 / 正文搜索"
          >
        </div>

        <button
          v-if="limitsFailed"
          type="button"
          class="btn-primary"
          title="服务端限额获取失败，点击重试"
          @click="loadLimits"
        >
          <i class="fa-solid fa-rotate-right"></i> 重试加载限额
        </button>
        <button
          v-else
          type="button"
          class="btn-primary"
          @click="openNew"
        >
          <i class="fa-solid fa-plus"></i> 新建
        </button>
      </div>

      <div class="card list-card">
        <div v-if="loading" class="state-box">加载中…</div>
        <div v-else-if="items.length === 0" class="state-box">
          {{ keyword || kind !== 'all' ? '没有符合条件的条目' : '还没有保存过任何内容，点右上角「新建」开始吧' }}
        </div>

        <div v-else class="clip-list">
          <div v-for="it in items" :key="it.id" class="clip-item">
            <div class="clip-head">
              <span class="kind-badge" :class="it.kind">
                <i :class="it.kind === 'code' ? 'fa-solid fa-code' : 'fa-solid fa-font'"></i>
                {{ it.kind === 'code' ? `代码 · ${it.language || 'plaintext'}` : '文本' }}
              </span>
              <span class="clip-title">{{ it.title || '（未命名）' }}</span>
              <span class="clip-time">{{ fmtDateTime(it.created_at) }}</span>
            </div>

            <pre class="clip-pre">{{ it.content }}</pre>

            <div class="clip-foot">
              <span class="clip-stat">{{ it.content.length }} 字符</span>
              <div class="clip-actions">
                <button type="button" class="act" @click="copyContent(it)">
                  <i :class="copiedId === it.id ? 'fa-solid fa-check' : 'fa-solid fa-copy'"></i>
                  {{ copiedId === it.id ? '已复制' : '复制' }}
                </button>
                <button type="button" class="act" @click="openEdit(it)">
                  <i class="fa-solid fa-pen"></i> 编辑
                </button>
                <button type="button" class="act act-danger" @click="removeItem(it)">
                  <i class="fa-solid fa-trash-can"></i> 删除
                </button>
              </div>
            </div>
          </div>
        </div>

        <div v-if="!loading && totalPages > 1" class="pager">
          <button type="button" class="pg" :disabled="page <= 1" @click="goPage(page - 1)">
            上一页
          </button>
          <span class="pg-info">{{ page }} / {{ totalPages }}（共 {{ total }} 条）</span>
          <button type="button" class="pg" :disabled="page >= totalPages" @click="goPage(page + 1)">
            下一页
          </button>
        </div>
      </div>
    </div>

    <!-- 新建/编辑弹层 -->
    <div v-if="modal" class="modal-mask" @click.self="closeModal">
      <div class="modal-card">
        <div class="modal-head">
          <span class="modal-title">{{ titleLabel }}</span>
          <button type="button" class="modal-close" @click="closeModal">&times;</button>
        </div>

        <div class="modal-body">
          <div class="row">
            <div class="label">类型</div>
            <div class="seg">
              <label class="seg-item">
                <input v-model="draftKind" type="radio" value="text">
                文本
              </label>
              <label class="seg-item">
                <input v-model="draftKind" type="radio" value="code">
                代码
              </label>
            </div>
          </div>

          <div class="row">
            <div class="label">标题（可选）</div>
            <input v-model="draftTitle" class="input" type="text" maxlength="120" placeholder="给它起个方便回忆的名字">
          </div>

          <div v-if="draftKind === 'code'" class="row">
            <div class="label">语言</div>
            <select v-model="draftLang" class="input sel">
              <option v-for="l in LANGS" :key="l" :value="l">{{ l }}</option>
            </select>
          </div>

          <div class="row">
            <div class="label">正文</div>
            <textarea
              v-model="draftContent"
              class="input ta"
              :class="{ 'is-warn': lenWarn() }"
              rows="10"
              :placeholder="contentPlaceholder"
            />
            <div class="len-row">
              <span :class="{ 'is-warn': lenWarn() }">
                {{ draftLen }} / {{ limits.max_content_len }}
              </span>
            </div>
          </div>
        </div>

        <div class="modal-foot">
          <button type="button" class="btn-ghost" @click="closeModal">取消</button>
          <button type="button" class="btn-primary" :disabled="submitting || lenWarn()" @click="submit">
            {{ submitting ? '保存中…' : (editingId ? '保存修改' : '保存') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.clip-page {
  padding: 16px 16px 40px;
}

.page-container {
  max-width: 900px;
  margin: 0 auto;
}

.page-title {
  font-size: 20px;
  color: var(--text-strong);
  margin: 4px 0 6px;
}

.page-desc {
  margin: 0 0 14px;
  font-size: 12px;
  color: #90a0b4;
}

.card {
  background: var(--surface-plain);
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

/* ---------- toolbar ---------- */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  padding: 12px 14px;
  margin-bottom: 14px;
}

.filters {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.chip {
  padding: 5px 12px;
  font-size: 12px;
  color: var(--text-sub);
  background: var(--bg-subtle);
  border: 1px solid #e3eaf3;
  border-radius: 14px;
  cursor: pointer;
  transition: background-color 0.15s, color 0.15s, border-color 0.15s;
}

.chip:hover {
  background: color-mix(in srgb, var(--primary) 8%, transparent);
}

.chip.is-active {
  color: #fff;
  background: var(--primary);
  border-color: var(--primary);
}

.search {
  width: 200px;
  padding: 6px 12px;
  font-size: 12px;
  border: 1px solid #e3eaf3;
  border-radius: 14px;
  outline: none;
}

.search:focus {
  border-color: var(--primary);
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  font-size: 13px;
  color: #fff;
  background: var(--primary);
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: filter 0.15s;
}

.btn-primary:hover:not(:disabled) {
  filter: brightness(1.08);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-ghost {
  padding: 7px 14px;
  font-size: 13px;
  color: var(--text-sub);
  background: transparent;
  border: 1px solid #e3eaf3;
  border-radius: 6px;
  cursor: pointer;
}

/* ---------- list ---------- */
.list-card {
  padding: 14px 16px 20px;
}

.state-box {
  padding: 40px 0;
  text-align: center;
  font-size: 13px;
  color: #a0aec0;
}

.clip-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.clip-item {
  border: 1px solid #eef2f7;
  border-radius: 10px;
  padding: 12px 14px;
  transition: border-color 0.18s, box-shadow 0.18s;
}

.clip-item:hover {
  border-color: #dbe6f3;
  box-shadow: 0 3px 10px rgba(0, 0, 0, 0.05);
}

.clip-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.kind-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  font-size: 11px;
  border-radius: 10px;
  background: #eef5ff;
  color: #3b6bc7;
}

.kind-badge.code {
  background: #eefaf4;
  color: #2f8a5f;
}

.clip-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-strong);
  flex: 1;
}

.clip-time {
  font-size: 11px;
  color: #90a0b4;
}

.clip-pre {
  margin: 0 0 8px;
  padding: 10px 12px;
  max-height: 260px;
  overflow: auto;
  background: var(--bg-subtle);
  border-radius: 6px;
  font-size: 12.5px;
  font-family: 'Consolas', 'Menlo', 'Fira Code', 'Courier New', monospace;
  line-height: 1.55;
  color: var(--text-strong);
  white-space: pre-wrap;
  word-break: break-word;
}

.clip-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.clip-stat {
  font-size: 11px;
  color: #a0aec0;
}

.clip-actions {
  display: flex;
  gap: 4px;
}

.act {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  font-size: 11px;
  color: var(--text-sub);
  background: var(--surface-plain);
  border: 1px solid #e8eef5;
  border-radius: 6px;
  cursor: pointer;
  transition: background-color 0.15s, color 0.15s;
}

.act:hover {
  color: var(--primary-text);
  background: color-mix(in srgb, var(--primary) 8%, transparent);
}

.act-danger:hover {
  color: #e74c3c;
  background: color-mix(in srgb, var(--danger) 10%, transparent);
}

/* ---------- pager ---------- */
.pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  margin-top: 18px;
}

.pg {
  padding: 5px 14px;
  font-size: 12px;
  color: var(--text-sub);
  background: var(--bg-subtle);
  border: 1px solid #e3eaf3;
  border-radius: 6px;
  cursor: pointer;
}

.pg:disabled {
  color: #c3ccd8;
  cursor: not-allowed;
}

.pg-info {
  font-size: 12px;
  color: #90a0b4;
}

/* ---------- modal ---------- */
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 16px;
}

.modal-card {
  width: min(560px, 100%);
  max-height: 90vh;
  background: var(--surface-plain);
  border-radius: 12px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.15);
  display: flex;
  flex-direction: column;
}

.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #eef2f7;
}

.modal-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-strong);
}

.modal-close {
  width: 26px;
  height: 26px;
  font-size: 22px;
  line-height: 22px;
  color: #90a0b4;
  background: transparent;
  border: none;
  border-radius: 50%;
  cursor: pointer;
}

.modal-close:hover {
  background: var(--bg-subtle);
}

.modal-body {
  padding: 14px 16px;
  overflow: auto;
}

.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid #eef2f7;
}

.row {
  margin-bottom: 12px;
}

.label {
  font-size: 12px;
  color: var(--text-sub);
  margin-bottom: 4px;
  display: block;
}

.input {
  width: 100%;
  padding: 8px 10px;
  font-size: 13px;
  color: var(--text-strong);
  background: var(--bg-subtle);
  border: 1px solid #e3eaf3;
  border-radius: 6px;
  outline: none;
  box-sizing: border-box;
}

.input:focus {
  border-color: var(--primary);
}

.input.sel {
  padding: 7px 10px;
}

.input.ta {
  font-family: 'Consolas', 'Menlo', 'Fira Code', 'Courier New', monospace;
  font-size: 12.5px;
  line-height: 1.55;
  resize: vertical;
}

.input.is-warn {
  border-color: #e74c3c;
}

.len-row {
  text-align: right;
  font-size: 11px;
  color: #90a0b4;
  margin-top: 4px;
}

.len-row .is-warn {
  color: #e74c3c;
}

.seg {
  display: inline-flex;
  border: 1px solid #e3eaf3;
  border-radius: 6px;
  overflow: hidden;
}

.seg-item {
  padding: 6px 14px;
  font-size: 12px;
  color: var(--text-sub);
  cursor: pointer;
  background: var(--bg-subtle);
}

.seg-item input {
  display: none;
}

.seg-item:has(input:checked) {
  color: #fff;
  background: var(--primary);
}

/* ---------- responsive ---------- */
@media (max-width: 600px) {
  .clip-page {
    padding: 12px 0 32px;
  }

  .search {
    width: 140px;
  }

  .clip-pre {
    max-height: 180px;
  }
}
</style>
