<script setup lang="ts">
/**
 * 偏好设置（顶栏头像菜单进入）：
 *   1. 代码模板 —— 自测/提交编辑器的初始填充（CodeMirror 编辑，按语言三选一），
 *      进页面自动载入账号已保存的模板（未保存过则显示内置默认）；
 *      停手 800ms 自动保存（与字体点选即存一致，避免「以为存了其实没存」）；
 *   2. 等宽字体 —— 编辑器与 code/pre 的字体（--font-mono），点选即时预览、保存落库。
 * 两者都走 PUT /api/users/me/prefs，换设备登录后同样生效。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Swal from 'sweetalert2'
import apiClient from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import CodeEditor from '@/components/CodeEditor.vue'
import { DEFAULT_CODE, LANGUAGES } from '@/constants/languages'
import { CODE_FONTS, codeFontCss } from '@/constants/codeFonts'

const authStore = useAuthStore()

// ===== 代码模板 =====
const TEMPLATE_LANGS = ['cpp', 'c', 'python3'] as const
const LANG_LABEL: Record<string, string> = { cpp: 'C++14', c: 'C', python3: 'Python 3' }

const activeLang = ref<string>('cpp')
const templates = ref<Record<string, string>>({
  cpp: DEFAULT_CODE['cpp'] ?? '',
  c: DEFAULT_CODE['c'] ?? '',
  python3: DEFAULT_CODE['python3'] ?? '',
})
const tplSaving = ref(false)
/** 自动保存状态：idle 待保存 / saving 保存中 / saved 已保存 / error 保存失败 */
const tplStatus = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
/** 首次载入账号模板完成前不触发自动保存，否则进页面就白发一次 PUT */
let tplHydrated = false
let tplSaveTimer: ReturnType<typeof setTimeout> | undefined

// CodeMirror 按当前 tab 的语言切换高亮（CodeEditor watch language 用 Compartment 重配）
const editorLang = computed(
  () => LANGUAGES.find((l) => l.value === activeLang.value)?.editorLang ?? 'cpp',
)

/** 账号里存的模板 → 本地编辑缓冲（没存的语言用内置默认显示） */
function loadTemplates() {
  const saved = authStore.currentUser?.code_template
  for (const lang of TEMPLATE_LANGS) {
    const v = saved?.[lang]
    templates.value[lang] = typeof v === 'string' && v ? v : (DEFAULT_CODE[lang] ?? '')
  }
}

function resetActiveLang() {
  templates.value[activeLang.value] = DEFAULT_CODE[activeLang.value] ?? ''
}

async function persistTemplates(auto: boolean) {
  if (tplSaving.value) return
  tplSaving.value = true
  tplStatus.value = 'saving'
  try {
    await apiClient.put('/api/users/me/prefs', {
      code_template: {
        cpp: templates.value.cpp,
        c: templates.value.c,
        python3: templates.value.python3,
      },
    })
    const u = authStore.currentUser
    if (u) u.code_template = { ...templates.value }
    tplStatus.value = 'saved'
    if (!auto) {
      Swal.fire({
        toast: true, position: 'top', icon: 'success',
        title: '代码模板已保存', showConfirmButton: false, timer: 1500,
      })
    }
  } catch (e: any) {
    // 自动保存失败不弹窗（会打断打字），状态行标红提示手动重试
    tplStatus.value = 'error'
    if (!auto) {
      Swal.fire('保存失败', e?.response?.data?.detail || '请重试', 'error')
    }
  } finally {
    tplSaving.value = false
  }
}

/** 手动保存按钮：立即落库并给明确反馈；编辑中的改动由下方 watch 自动保存 */
function saveTemplates() {
  if (tplSaveTimer !== undefined) {
    clearTimeout(tplSaveTimer)
    tplSaveTimer = undefined
  }
  void persistTemplates(false)
}

// 编辑即存：停手 800ms 自动保存。不这么做的话，字体点选即存、模板却要手动
// 点保存，用户改完就走会丢改动，表现为「第二次进入莫名恢复默认」。
watch(
  templates,
  () => {
    if (!tplHydrated) return
    tplStatus.value = 'idle'
    if (tplSaveTimer !== undefined) clearTimeout(tplSaveTimer)
    tplSaveTimer = setTimeout(() => {
      tplSaveTimer = undefined
      void persistTemplates(true)
    }, 800)
  },
  { deep: true },
)

// ===== 等宽字体 =====
/** 点选时先写 CSS 变量做全站即时预览（编辑器立即生效），保存成功才落到账号 */
const fontSaving = ref<string | null>(null)

async function pickFont(key: string) {
  if (key === (authStore.currentUser?.code_font ?? null) || fontSaving.value) return
  const prevKey = authStore.currentUser?.code_font ?? null
  document.documentElement.style.setProperty('--font-mono', codeFontCss(key))
  fontSaving.value = key
  try {
    await apiClient.put('/api/users/me/prefs', { code_font: key })
    const u = authStore.currentUser
    if (u) u.code_font = key
  } catch (e: any) {
    document.documentElement.style.setProperty('--font-mono', codeFontCss(prevKey))
    Swal.fire('保存失败', e?.response?.data?.detail || '请重试', 'error')
  } finally {
    fontSaving.value = null
  }
}

onMounted(async () => {
  // 刷新直开本页：守卫可能还没把 currentUser 恢复好，先拉一次
  if (!authStore.currentUser && authStore.accessToken) {
    try { await authStore.fetchCurrentUser() } catch { /* 守卫/接口失败时由保存兜底 */ }
  }
  loadTemplates()
  // 等载入的模板渲染进编辑器后再开自动保存，避免首屏赋值触发一次空 PUT
  await nextTick()
  tplHydrated = true
})

onBeforeUnmount(() => {
  // 防抖窗口内离开页面：把未保存的修改立即落库，不丢用户输入
  if (tplSaveTimer !== undefined) {
    clearTimeout(tplSaveTimer)
    tplSaveTimer = undefined
    void persistTemplates(true)
  }
})
</script>

<template>
  <div class="preferences-page">
    <div class="card intro-card">
      <div class="card-header">偏好设置</div>
      <p class="intro-desc">
        以下偏好与账号绑定，换设备登录后同样生效。保存后提交页与沉浸做题立即使用新的代码模板。
      </p>
    </div>

    <!-- ===== 代码模板 ===== -->
    <div class="card">
      <div class="card-header">代码模板</div>
      <p class="section-desc">
        进入沉浸做题或提交页时，若没有上次提交可回填，编辑器将用这里的模板初始化。
        恢复默认即使用内置模板。编辑停手后自动保存，也可手动点「保存模板」。
      </p>

      <div class="lang-tabs" role="tablist">
        <button
          v-for="lang in TEMPLATE_LANGS"
          :key="lang"
          type="button"
          class="lang-tab"
          :class="{ active: activeLang === lang }"
          role="tab"
          :aria-selected="activeLang === lang"
          @click="activeLang = lang"
        >
          {{ LANG_LABEL[lang] }}
        </button>
      </div>

      <CodeEditor
        v-model="templates[activeLang]"
        :language="editorLang"
        height="360px"
      />

      <div class="tpl-actions">
        <button type="button" class="btn ghost" @click="resetActiveLang">
          <i class="fa-solid fa-rotate-left"></i> 恢复{{ LANG_LABEL[activeLang] }}默认
        </button>
        <span class="tpl-status" :class="tplStatus" aria-live="polite">
          <template v-if="tplStatus === 'saving'">
            <i class="fa-solid fa-circle-notch fa-spin"></i> 保存中…
          </template>
          <template v-else-if="tplStatus === 'saved'">
            <i class="fa-solid fa-check"></i> 已自动保存
          </template>
          <template v-else-if="tplStatus === 'error'">
            <i class="fa-solid fa-triangle-exclamation"></i> 保存失败，点「保存模板」重试
          </template>
          <template v-else>编辑后自动保存</template>
        </span>
        <button
          type="button"
          class="btn primary"
          :disabled="tplSaving"
          @click="saveTemplates"
        >
          <i class="fa-solid" :class="tplSaving ? 'fa-circle-notch fa-spin' : 'fa-floppy-disk'"></i>
          {{ tplSaving ? '保存中…' : '保存模板' }}
        </button>
      </div>
    </div>

    <!-- ===== 等宽字体 ===== -->
    <div class="card">
      <div class="card-header">等宽字体</div>
      <p class="section-desc">
        代码编辑器与全站代码块（code / pre）使用的字体。点选立即预览并保存。
      </p>

      <div class="font-grid">
        <button
          v-for="f in CODE_FONTS"
          :key="f.key"
          type="button"
          class="font-option"
          :class="{ active: (authStore.currentUser?.code_font ?? null) === f.key }"
          :disabled="fontSaving !== null && fontSaving !== f.key"
          @click="pickFont(f.key)"
        >
          <span class="font-head">
            <span class="font-name">{{ f.label }}</span>
            <i
              v-if="(authStore.currentUser?.code_font ?? null) === f.key"
              class="fa-solid fa-circle-check"
            ></i>
            <i
              v-else-if="fontSaving === f.key"
              class="fa-solid fa-circle-notch fa-spin"
            ></i>
          </span>
          <span class="font-sample" :style="{ fontFamily: f.css }">
            if (n &lt;= 1) return 0O1lI;
          </span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.preferences-page {
  max-width: 900px;
  margin: 0 auto;
}

.card {
  background: var(--surface);
  -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: 20px 24px;
  margin-bottom: 24px;
}

.card-header {
  font-size: 1.25rem;
  font-weight: 600;
  border-left: 4px solid var(--primary);
  padding-left: 12px;
  margin-bottom: 16px;
}

.intro-desc,
.section-desc {
  color: var(--text-secondary, #666);
  font-size: 14px;
  line-height: 1.7;
  margin-bottom: 16px;
}

/* ===== 语言 tab ===== */
.lang-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.lang-tab {
  padding: 7px 18px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm, 6px);
  background: transparent;
  color: var(--text-secondary, #666);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.lang-tab:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.lang-tab.active {
  background: color-mix(in srgb, var(--primary) 12%, transparent);
  border-color: var(--primary);
  color: var(--primary);
  font-weight: 600;
}

/* 模板编辑区用 CodeEditor（CodeMirror），容器只需留出间距 */
.tpl-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 14px;
}

/* 自动保存状态行：idle 灰、saving 主色、saved 绿、error 红 */
.tpl-status {
  font-size: 13px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.tpl-status.saving {
  color: var(--primary);
}

.tpl-status.saved {
  color: var(--success);
}

.tpl-status.error {
  color: var(--danger);
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 8px 18px;
  border-radius: var(--radius-sm, 6px);
  font-size: 14px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.15s ease;
}

.btn.ghost {
  background: transparent;
  border-color: var(--border-color);
  color: var(--text-secondary, #666);
}

.btn.ghost:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.btn.primary {
  background: var(--primary);
  color: #fff;
}

.btn.primary:hover:not(:disabled) {
  background: var(--primary-hover);
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* ===== 字体选项 ===== */
.font-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}

.font-option {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm, 6px);
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s ease;
}

.font-option:hover:not(:disabled) {
  border-color: var(--primary);
}

.font-option.active {
  border-color: var(--primary);
  background: color-mix(in srgb, var(--primary) 8%, transparent);
}

.font-option:disabled {
  opacity: 0.55;
  cursor: wait;
}

.font-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.font-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #222);
}

.font-head i {
  color: var(--primary);
}

.font-sample {
  font-size: 13px;
  color: var(--text-secondary, #666);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width: 600px) {
  .card {
    padding: 16px 14px;
  }

  .tpl-actions {
    flex-direction: column;
  }

  .btn {
    justify-content: center;
  }
}
</style>
