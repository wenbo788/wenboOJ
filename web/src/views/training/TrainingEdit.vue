<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { trainingsApi } from '@/api/trainings'
import { problemsApi } from '@/api/problems'
import MarkdownSplitEditor from '@/components/MarkdownSplitEditor.vue'

const route = useRoute()
const router = useRouter()

// /training/new = 创建；/training/:id/edit = 编辑
const trainingId = computed(() => {
  const id = parseInt(route.params.id as string, 10)
  return Number.isFinite(id) && id > 0 ? id : null
})
const isEdit = computed(() => trainingId.value !== null)

const pageTitle = computed(() => (isEdit.value ? '编辑题单' : '创建题单'))

const form = ref({ title: '', description: '' })
const createError = ref('')
const submitting = ref(false)
const loading = ref(false)

// 题单题目：输入题号（如 P1001、U1001、T1001、1001）按顺序添加
const picked = ref<{ code: string; title: string }[]>([])
const codeInput = ref('')
const addingCode = ref(false)

const canSubmit = computed(() => form.value.title.trim() && picked.value.length > 0)

const addProblem = async () => {
  const code = codeInput.value.trim().toUpperCase()
  if (!code) return
  addingCode.value = true
  createError.value = ''
  try {
    const p = await problemsApi.getByCode(code)
    const normalizedCode = p.problem_number || code
    if (picked.value.some(item => item.code === normalizedCode)) {
      createError.value = `题目 ${normalizedCode} 已添加`
      return
    }
    picked.value.push({ code: normalizedCode, title: p.title })
    codeInput.value = ''
  } catch (err: any) {
    createError.value = err.response?.data?.detail === '题目不存在'
      ? `题目 ${code} 不存在或不可用` : (err.response?.data?.detail || `题目 ${code} 添加失败`)
  } finally {
    addingCode.value = false
  }
}

const removeProblem = (code: string) => {
  picked.value = picked.value.filter(p => p.code !== code)
}

const moveProblem = (index: number, dir: -1 | 1) => {
  const target = index + dir
  if (target < 0 || target >= picked.value.length) return
  const arr = [...picked.value]
  ;[arr[index], arr[target]] = [arr[target], arr[index]]
  picked.value = arr
}

const loadExisting = async () => {
  if (!isEdit.value) return
  loading.value = true
  try {
    const t = await trainingsApi.get(trainingId.value as number)
    form.value.title = t.title
    form.value.description = t.description || ''
    picked.value = (t.problems || []).map(p => ({ code: p.problem_number, title: p.title }))
  } catch (err: any) {
    createError.value = err.response?.data?.detail || err.message || '加载题单失败'
  } finally {
    loading.value = false
  }
}

const doSubmit = async () => {
  if (!form.value.title.trim()) { createError.value = '请输入题单名称'; return }
  if (picked.value.length === 0) { createError.value = '请至少添加一道题目'; return }
  submitting.value = true
  createError.value = ''
  try {
    const data = {
      title: form.value.title.trim(),
      description: form.value.description.trim() || undefined,
      problem_codes: picked.value.map(p => p.code),
    }
    if (isEdit.value) {
      await trainingsApi.update(trainingId.value as number, data)
      router.push(`/training/${trainingId.value}`)
    } else {
      const created = await trainingsApi.create(data)
      router.push(`/training/${created.id}`)
    }
  } catch (err: any) {
    createError.value = err.response?.data?.detail || (isEdit.value ? '保存失败' : '创建失败')
    submitting.value = false
  }
}

onMounted(loadExisting)
</script>

<template>
  <div class="training-edit-page">
    <div class="training-edit-container">
      <div class="back-link">
        <a @click.prevent="router.push('/training')" href="#">← 返回题单列表</a>
      </div>

      <div v-if="loading" class="empty">加载中...</div>

      <div v-else class="card form-card">
        <h2 class="form-title">{{ pageTitle }}</h2>

        <div class="form-row">
          <span class="row-label">题单名称</span>
          <div class="row-value">
            <input v-model="form.title" class="form-input w-title" maxlength="100" placeholder="例如：入门训练 · 二分查找专题" />
          </div>
        </div>

        <div class="form-row top">
          <span class="row-label">题单说明</span>
          <div class="row-value">
            <MarkdownSplitEditor
              v-model="form.description"
              height="260px"
              placeholder="题单目标、适合人群、做题建议……（支持 Markdown）"
            />
          </div>
        </div>

        <div class="form-row top">
          <span class="row-label">题单题目</span>
          <div class="row-value">
            <div class="code-add-row">
              <input
                v-model="codeInput"
                class="form-input w-title"
                placeholder="输入题号，如 P1001 或 U1001，回车添加"
                :disabled="addingCode"
                @keydown.enter.prevent="addProblem"
              />
              <button class="btn-secondary" :disabled="addingCode || !codeInput.trim()" @click="addProblem">
                {{ addingCode ? '校验中...' : '添加' }}
              </button>
            </div>
            <div v-if="picked.length" class="picked-list">
              <div v-for="(p, i) in picked" :key="p.code" class="picked-item">
                <span class="picked-alias">{{ i + 1 }}</span>
                <span class="picked-code">{{ p.code }}</span>
                <span class="picked-title">{{ p.title }}</span>
                <button class="mini-btn" title="上移" :disabled="i === 0" @click="moveProblem(i, -1)">↑</button>
                <button class="mini-btn" title="下移" :disabled="i === picked.length - 1" @click="moveProblem(i, 1)">↓</button>
                <button class="mini-btn danger" title="移除" @click="removeProblem(p.code)"><i class="fa-solid fa-xmark"></i></button>
              </div>
            </div>
            <div class="hint">题目按添加顺序显示（当前 {{ picked.length }} 道）</div>
          </div>
        </div>

        <div v-if="createError" class="form-error">{{ createError }}</div>

        <div class="submit-row">
          <button class="btn-secondary" @click="router.push('/training')">取消</button>
          <button class="btn-primary" :disabled="submitting || !canSubmit" @click="doSubmit">
            {{ submitting ? (isEdit ? '保存中...' : '创建中...') : (isEdit ? '保存修改' : '创建题单') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.training-edit-page { min-height: calc(100vh - 60px); }
.training-edit-container { max-width: 920px; margin: 0 auto; padding: 20px; }
.back-link { margin-bottom: 12px; }
.back-link a { color: var(--primary); font-size: 14px; cursor: pointer; text-decoration: none; }
.back-link a:hover { text-decoration: underline; }

/* 背景/圆角/边框/阴影由全局 .card 基类统一提供（亚克力），这里只管布局 */
.card.form-card { padding: 26px 30px; }
.form-title { margin: 0 0 6px; font-size: 18px; color: var(--text-strong); }
.form-row { display: flex; align-items: center; gap: 18px; padding: 12px 0; border-bottom: 1px solid #f7f8fa; }
.form-row.top { align-items: flex-start; }
.row-label { width: 90px; flex-shrink: 0; font-size: 14px; font-weight: 600; color: var(--text-strong); text-align: right; }
.row-value { flex: 1; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.form-input { padding: 8px 12px; border: 1px solid #dce0e6; border-radius: 8px; font-size: 14px; outline: none; font-family: inherit; }
.form-input:focus { border-color: var(--primary); }
.form-input:disabled { background: var(--bg-subtle); color: var(--text-sub); }
.w-title { width: min(360px, 100%); }
.hint { font-size: 12px; color: #8e9aaf; }

.code-add-row { display: flex; gap: 10px; width: 100%; }
.picked-list { width: 100%; display: flex; flex-direction: column; gap: 6px; }
.picked-item { display: flex; align-items: center; gap: 10px; background: var(--surface-strong); border: var(--border-width) solid var(--border-color); border-radius: 8px; padding: 7px 12px; font-size: 13px; }
.picked-alias { font-weight: 700; color: var(--primary); min-width: 18px; }
.picked-code { color: var(--primary); font-weight: 600; min-width: 52px; }
.picked-title { flex: 1; color: var(--text-strong); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mini-btn { border: 1px solid #e2e8f0; background: var(--surface-plain); border-radius: 6px; padding: 2px 8px; font-size: 12px; cursor: pointer; color: var(--text-sub); }
.mini-btn:hover:not(:disabled) { border-color: var(--primary); color: var(--primary); }
.mini-btn:disabled { opacity: .4; cursor: not-allowed; }
.mini-btn.danger:hover { border-color: #e74c3c; color: #e74c3c; }

.form-error { color: #e74c3c; font-size: 13px; margin-top: 12px; }
.submit-row { display: flex; justify-content: flex-end; gap: 12px; margin-top: 18px; }
.btn-primary { background: var(--primary); color: #fff; border: none; border-radius: 8px; padding: 9px 26px; font-weight: 600; cursor: pointer; font-size: 14px; }
.btn-primary:hover:not(:disabled) { background: var(--primary-hover); }
.btn-primary:disabled { opacity: .55; cursor: not-allowed; }
.btn-secondary { background: var(--bg-subtle); color: var(--text-strong); border: none; border-radius: 8px; padding: 9px 26px; font-weight: 600; cursor: pointer; font-size: 14px; }

.empty { text-align: center; color: var(--text-sub); padding: 48px 0; background: var(--surface); -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5); backdrop-filter: blur(var(--surface-blur)) saturate(1.5); border: var(--border-width) solid var(--border-color); border-radius: 12px; }

@media (max-width: 640px) {
  .form-row { flex-direction: column; align-items: stretch; gap: 6px; }
  .row-label { width: auto; text-align: left; }
}

/* ===== 手机端：容器横向内边距归零 + 表单卡片收窄 ===== */
@media (max-width: 600px) {
  .training-edit-container {
    padding: 16px 0;
  }

  .card.form-card {
    padding: 16px 14px;
  }
}
</style>
