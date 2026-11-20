<script setup lang="ts">
/**
 * 犇犇发布框的 Markdown 编辑器（轻量版）。
 *
 * 为什么不用 MarkdownSplitEditor：那个是 CodeMirror 分栏编辑器，给题面/长文用的，
 * 塞进 3 行的犇犇框里太重（还要抢全屏、分栏）。这里只要「小工具栏 + 预览切换」：
 * 粗体 / 斜体 / 行内代码 / 链接 / 公式，加上 Ctrl+B、Ctrl+I 快捷键和「预览」。
 *
 * 预览走 @/utils/markdown 的 renderRichText —— 和犇犇最终渲染同一套管线，
 * 所见即所得（含 B 站 / 网易云播放卡片、@提及、公式）。
 */
import { computed, nextTick, ref } from 'vue'
import { renderRichText } from '@/utils/markdown'

const props = withDefaults(
  defineProps<{
    modelValue: string
    placeholder?: string
    maxlength?: string | number
    disabled?: boolean
    rows?: number
  }>(),
  { placeholder: '', maxlength: 0, disabled: false, rows: 3 },
)

const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>()

const textareaEl = ref<HTMLTextAreaElement | null>(null)
const showPreview = ref(false)

const maxLen = computed(() => {
  const n = Number(props.maxlength)
  return Number.isFinite(n) && n > 0 ? n : 0
})
const len = computed(() => (props.modelValue || '').length)
const previewHtml = computed(() =>
  showPreview.value ? renderRichText(props.modelValue || '') : '',
)

function setValue(v: string) {
  emit('update:modelValue', v)
}

/** 在光标处插入/包裹选中文本；replaceSelection 为 true 时直接替换选中内容 */
function surround(before: string, after = '', placeholder = '') {
  const el = textareaEl.value
  if (!el || props.disabled) return
  const start = el.selectionStart ?? 0
  const end = el.selectionEnd ?? 0
  const value = props.modelValue || ''
  const selected = value.slice(start, end)
  const body = selected || placeholder
  const next = value.slice(0, start) + before + body + after + value.slice(end)
  setValue(next)
  void nextTick(() => {
    el.focus()
    const caret = start + before.length + body.length
    el.setSelectionRange(caret, caret)
  })
}

function insertLink() {
  const el = textareaEl.value
  if (!el || props.disabled) return
  const start = el.selectionStart ?? 0
  const end = el.selectionEnd ?? 0
  const value = props.modelValue || ''
  const selected = value.slice(start, end)
  const text = selected || '链接文字'
  const snippet = `[${text}](https://)`
  const next = value.slice(0, start) + snippet + value.slice(end)
  setValue(next)
  void nextTick(() => {
    el.focus()
    // 光标落在 url 里，直接输入就行
    const at = start + text.length + 3
    el.setSelectionRange(at, at + 8)
  })
}

function onKeydown(e: KeyboardEvent) {
  if (!(e.ctrlKey || e.metaKey)) return
  const k = e.key.toLowerCase()
  if (k === 'b') {
    e.preventDefault()
    surround('**', '**', '加粗文字')
  } else if (k === 'i') {
    e.preventDefault()
    surround('*', '*', '斜体文字')
  }
}

defineExpose({
  focus: () => textareaEl.value?.focus(),
  /** 回复犇犇时把光标放到开头 */
  setCaretToStart: () => {
    const el = textareaEl.value
    if (!el) return
    el.focus()
    el.setSelectionRange(0, 0)
    el.scrollTop = 0
  },
})
</script>

<template>
  <div class="md-editor" :class="{ 'is-disabled': disabled }">
    <div class="md-toolbar">
      <!-- 用文字标签而不是图标字体：站内 FA 字体在部分网络/环境里加载失败，
           图标会变成方块；这几个按钮用文字反而更直观 -->
      <button type="button" class="md-btn md-bold" title="加粗 (Ctrl+B)" :disabled="disabled" @click="surround('**', '**', '加粗文字')">
        B
      </button>
      <button type="button" class="md-btn md-italic" title="斜体 (Ctrl+I)" :disabled="disabled" @click="surround('*', '*', '斜体文字')">
        I
      </button>
      <button type="button" class="md-btn md-mono" title="行内代码" :disabled="disabled" @click="surround('`', '`', 'code')">
        &lt;/&gt;
      </button>
      <button type="button" class="md-btn" title="链接" :disabled="disabled" @click="insertLink">
        链接
      </button>
      <button type="button" class="md-btn" title="行内公式" :disabled="disabled" @click="surround('$', '$', 'x^2')">
        ∑
      </button>
      <span class="md-spacer"></span>
      <span class="md-count" v-if="maxLen">{{ len }} / {{ maxLen }}</span>
      <button
        type="button"
        class="md-btn md-text"
        :class="{ on: showPreview }"
        :disabled="disabled"
        @click="showPreview = !showPreview"
      >
        {{ showPreview ? '编辑' : '预览' }}
      </button>
    </div>

    <textarea
      v-show="!showPreview"
      ref="textareaEl"
      :value="modelValue"
      :rows="rows"
      :maxlength="maxLen || undefined"
      :placeholder="placeholder"
      :disabled="disabled"
      class="md-textarea"
      @input="setValue(($event.target as HTMLTextAreaElement).value)"
      @keydown="onKeydown"
    ></textarea>

    <div v-if="showPreview" class="md-preview prose" v-html="previewHtml"></div>
    <div class="md-hint">
      支持 Markdown：**粗体**、*斜体*、`代码`、[链接](url)、$公式$；B 站 / 网易云链接单独一行会变播放器。
    </div>
  </div>
</template>

<style scoped>
.md-editor {
  width: 100%;
  border: var(--border-width, 1px) solid var(--border-color);
  border-radius: var(--radius-md, 8px);
  background: var(--bg-subtle);
  overflow: hidden;
}

.md-editor.is-disabled {
  opacity: .6;
}

.md-toolbar {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 4px 6px;
  border-bottom: 1px solid var(--border-color);
  background: var(--surface-plain);
}

.md-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 7px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-main);
  font-size: 13px;
  cursor: pointer;
  line-height: 1.4;
}

.md-btn:hover:not(:disabled) {
  background: color-mix(in srgb, var(--primary) 12%, transparent);
}

.md-btn:disabled {
  cursor: not-allowed;
  opacity: .5;
}

.md-btn.on {
  background: color-mix(in srgb, var(--primary) 16%, transparent);
  color: var(--primary-text);
}

.md-text {
  font-size: 12px;
}

.md-bold {
  font-weight: 700;
}

.md-italic {
  font-style: italic;
  font-family: Georgia, "Times New Roman", serif;
}

.md-mono {
  font-family: var(--font-mono, monospace);
  font-size: 12px;
}

.md-spacer {
  flex: 1;
}

.md-count {
  font-size: 12px;
  color: var(--text-sub);
  margin-right: 6px;
}

.md-textarea {
  display: block;
  width: 100%;
  padding: 10px 12px;
  border: none;
  outline: none;
  resize: vertical;
  background: transparent;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-main);
  background: transparent;
  font-family: inherit;
  min-height: 64px;
  box-sizing: border-box;
}

.md-preview {
  padding: 10px 12px;
  min-height: 64px;
  font-size: 14px;
  max-height: 320px;
  overflow: auto;
}

.md-hint {
  padding: 4px 8px 6px;
  font-size: 11px;
  color: var(--text-sub);
  border-top: 1px dashed var(--border-color);
}
</style>
