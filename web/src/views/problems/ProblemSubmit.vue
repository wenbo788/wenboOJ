<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Swal from 'sweetalert2'
import CodeEditor from '@/components/CodeEditor.vue'
import { problemsApi } from '@/api/problems'
import { submissionsApi } from '@/api/submissions'
import { difficultyColor } from '@/utils/difficulty'
import { LANGUAGES } from '@/constants/languages'
import { getCodeTemplate } from '@/utils/prefs'
import type { Problem, Submission } from '@/types'

// 模块级草稿缓存：按 problemId 存 { code, language }。
// 组件卸载后保留（切走看题面再切回来能恢复），刷新页面丢失（回到上次提交），
// 提交成功后清除（下次进入用新的"上次提交"）。
const drafts = new Map<number, { code: string; language: string }>()

const route = useRoute()
const router = useRouter()

const problemId = computed(() => parseInt(route.params.id as string, 10))
// 比赛上下文：从比赛详情页进入提交时（/problems/:id?contest=N），提交计入比赛
const contestId = computed(() => {
  const v = parseInt(route.query.contest as string, 10)
  return Number.isFinite(v) && v > 0 ? v : null
})
const problem = ref<Problem | null>(null)
const loading = ref(true)

const language = ref('cpp')
const editorLang = computed(
  () => LANGUAGES.find((l) => l.value === language.value)?.editorLang ?? 'cpp',
)
const code = ref('')

const submitting = ref(false)
// 是否回填了上次提交的代码（用于给用户一个提示）
const restoredFromLast = ref(false)

const loadProblem = async () => {
  try {
    problem.value = await problemsApi.get(problemId.value)
  } catch (err: any) {
    Swal.fire('题目不存在', err.response?.data?.detail || '', 'error').then(() =>
      router.push('/problems')
    )
  }
}

// 我在这题的最后一次提交（从未提交 / 请求异常都按「无」处理）
const fetchLastSubmission = async (): Promise<Submission | null> => {
  try {
    return await submissionsApi.getMyLast(problemId.value)
  } catch {
    return null
  }
}

// 与后端 schemas/submission.py 的 max_length 保持一致，载入文件时据此校验
const MAX_CODE_LENGTH = 100_000

const onFileLoaded = ({ name, chars }: { name: string; chars: number }) => {
  Swal.fire({
    icon: 'success',
    title: '已载入代码',
    text: `${name}（${chars} 字符）`,
    timer: 1600,
    showConfirmButton: false,
  })
}

const onFileLoadError = (message: string) => {
  Swal.fire('载入失败', message, 'error')
}

const submit = async () => {
  if (!code.value.trim()) {
    Swal.fire('请填写代码', '', 'warning')
    return
  }
  submitting.value = true
  try {
    const sub = await submissionsApi.create(problemId.value, {
      code: code.value,
      language: language.value,
      contest_id: contestId.value ?? undefined,
    })
    drafts.delete(problemId.value)
    router.push({ path: `/submissions/${sub.id}`, query: route.query })
  } catch (err: any) {
    Swal.fire('提交失败', err.response?.data?.detail || '请重试', 'error')
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  // 优先恢复草稿（用户切走看题面又切回来）；否则拉上次提交或用偏好设置里的代码模板。
  const draft = drafts.get(problemId.value)
  if (draft) {
    language.value = draft.language
    code.value = draft.code
    await loadProblem()
    loading.value = false
    return
  }
  // 并行拉取题目与上次提交；有上次提交则回填代码与语言，否则用偏好模板（缺省即内置默认）。
  // 等两者都就绪再结束 loading，避免编辑器先渲染模板再被覆盖（闪一下）
  const [, last] = await Promise.all([loadProblem(), fetchLastSubmission()])
  if (last?.code) {
    if (LANGUAGES.some((l) => l.value === last.language)) {
      language.value = last.language
    }
    code.value = last.code
    restoredFromLast.value = true
  } else {
    code.value = getCodeTemplate(language.value)
  }
  loading.value = false
})

// 实时保存草稿（loading 期间不写，避免覆盖恢复的值）
watch([code, language], () => {
  if (!loading.value) {
    drafts.set(problemId.value, { code: code.value, language: language.value })
  }
})
</script>

<template>
  <div class="problem-submit-page">
    <div class="problem-submit-container">
      <div v-if="loading" class="empty">加载中...</div>

      <template v-else-if="problem">
        <div class="problem-submit-layout">
        <div class="problem-submit-main">
        <!-- 题头 -->
        <div class="card">
          <div class="p-head">
            <span class="p-number">{{ problem.problem_number }}</span>
            <h2 class="p-title">{{ problem.title }}</h2>
            <span class="diff-badge" :style="{ background: difficultyColor(problem.difficulty) }">
              {{ problem.difficulty }}
            </span>
          </div>
          <div class="p-limits">
            <span>时间限制：<b>{{ problem.time_limit }} ms</b></span>
            <span>内存限制：<b>{{ problem.memory_limit }} MB</b></span>
            <span v-if="contestId" class="contest-tag"><i class="fa-solid fa-trophy"></i> 比赛模式：本次提交计入比赛成绩</span>
          </div>
        </div>

        <!-- 提交区 -->
        <div class="card">
          <div class="submit-toolbar">
            <label class="lang-label">
              语言
              <select v-model="language" class="lang-select">
                <option v-for="l in LANGUAGES" :key="l.value" :value="l.value">{{ l.label }}</option>
              </select>
            </label>
          </div>

          <CodeEditor
            v-model="code"
            :language="editorLang"
            height="480px"
            loadable
            :max-chars="MAX_CODE_LENGTH"
            @load="onFileLoaded"
            @load-error="onFileLoadError"
          />

          <p class="tip"><template v-if="restoredFromLast">已载入你上次提交的代码。<br /></template>支持 C++14 / C / Python 3；评测在隔离沙箱中运行，每个测试点限时 {{ problem.time_limit }} ms。</p>
        </div>
        </div>

        <aside class="problem-actions-card">
          <div class="actions-card-title">快速导航</div>
          <button class="action-button action-primary" :disabled="submitting" @click="submit">
            <i class="fa-solid fa-paper-plane"></i> {{ submitting ? '提交中...' : '提交评测' }}
          </button>
          <button class="action-button" @click="router.push({ path: `/problems/${problem.id}`, query: route.query })">
            <i class="fa-solid fa-book-open"></i> 返回题目
          </button>
          <button
            class="action-button"
            title="全屏专注：左题面右编辑器，就地评测不跳转；草稿与本页互通"
            @click="router.push({ path: `/problems/${problem.id}/immersive`, query: route.query })"
          >
            <i class="fa-solid fa-expand"></i> 沉浸做题
          </button>
          <button class="action-button" @click="router.push({ path: '/submissions', query: { problem_id: String(problem.id), ...(contestId ? { contest: String(contestId) } : {}) } })">
            <i class="fa-solid fa-list"></i> 提交记录
          </button>
          <button class="action-button" @click="router.push('/problems')">
            <i class="fa-solid fa-arrow-left"></i> 返回题库
          </button>
          <button v-if="contestId" class="action-button action-contest" @click="router.push(`/contest/${contestId}`)">
            <i class="fa-solid fa-trophy"></i> 返回比赛
          </button>
        </aside>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.problem-submit-page {
  min-height: 100vh;
  line-height: 1.5;
}

.problem-submit-container {
  max-width: 1280px;
  margin: 0 auto;
}

.problem-submit-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 210px;
  align-items: start;
  gap: 18px;
}

.problem-submit-main {
  min-width: 0;
}

.problem-actions-card {
  position: sticky;
  top: 88px;
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 16px;
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--surface);
  box-shadow: var(--shadow-card);
}

.actions-card-title {
  margin-bottom: 3px;
  color: var(--text-sub);
  font-size: 13px;
  font-weight: 700;
}

.action-button {
  display: flex;
  min-height: 40px;
  align-items: center;
  gap: 9px;
  padding: 9px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: var(--surface-plain);
  color: var(--text-sub);
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  text-align: left;
}

.action-button:hover { border-color: var(--primary); color: var(--primary); }
.action-button:disabled { opacity: 0.55; cursor: not-allowed; }
.action-button.action-primary { border-color: var(--primary); background: var(--primary); color: #fff; }
.action-button.action-primary:hover:not(:disabled) { border-color: var(--primary-hover); background: var(--primary-hover); color: #fff; }
.action-button.action-contest { border-color: #e6a23c; background: color-mix(in srgb, var(--warning) 12%, transparent);color: var(--warning-text); }
.action-button.action-contest:hover { border-color: #d99018; background: color-mix(in srgb, var(--warning) 12%, transparent);color: var(--warning-text); }

.card {
  background: var(--surface);
  -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: 20px 24px;
  margin-bottom: 16px;
}

.p-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.p-number {
  color: var(--text-sub);
  font-weight: 700;
}

.p-title {
  font-size: 1.2rem;
  font-weight: 700;
  color: var(--text-strong);
  margin: 0;
}

.diff-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  color: #fff;
  font-size: 12px;
  font-weight: 600;
}

.p-limits {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  margin-top: 10px;
  color: var(--text-sub);
  font-size: 13px;
}

.p-limits b {
  color: var(--text-strong);
}

.contest-tag {
color: var(--warning-text);
  background: color-mix(in srgb, var(--warning) 12%, transparent);
  padding: 2px 10px;
  border-radius: 12px;
}

.submit-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
}

.lang-label {
  font-size: 13px;
  color: var(--text-sub);
  display: flex;
  align-items: center;
  gap: 8px;
}

.lang-select {
  padding: 7px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 13px;
  color: var(--text-strong);
  background: var(--surface-plain);
}

.toolbar-actions {
  display: flex;
  gap: 10px;
}

.btn-ghost {
  padding: 8px 18px;
  border: 1px solid #e2e8f0;
  background: var(--surface-plain);
  border-radius: 20px;
  font-size: 13px;
  color: var(--text-sub);
  cursor: pointer;
}

.btn-ghost:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.btn-submit {
  padding: 8px 26px;
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.btn-submit:hover:not(:disabled) {
  background: var(--primary-hover);
}

.btn-submit:disabled {
  opacity: 0.6;
}

.tip {
  margin-top: 10px;
  color: var(--text-sub);
  font-size: 12px;
}

.empty {
  text-align: center;
  padding: 60px 20px;
  color: var(--text-sub);
  background: var(--surface-plain);
  border-radius: 16px;
}

/* ===== 手机端：卡片内边距收窄 ===== */
@media (max-width: 600px) {
  .card {
    padding: 16px 14px;
  }
}

@media (max-width: 900px) {
  .problem-submit-layout { grid-template-columns: minmax(0, 1fr) 190px; gap: 12px; }
}

@media (max-width: 700px) {
  .problem-submit-layout { grid-template-columns: 1fr; }
  /* 单栏后 aside 会落回 DOM 末尾沉底，order 提到表单上方 */
  .problem-actions-card {
    order: -1;
    position: static;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .actions-card-title { grid-column: 1 / -1; }
}
</style>
