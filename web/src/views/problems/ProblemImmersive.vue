<script setup lang="ts">
/**
 * 沉浸式做题页（/problems/:id/immersive）：全站导航隐藏，左题面 + 右工作区
 * （代码编辑器 + 自测输入/输出），分屏比例可拖拽调整。
 *
 * 沉浸不打断：提交后不跳转详情页，就地轮询到出分显示徽标（编译错误直接
 * 展开 stderr），要看逐测试点再点「详情」。
 *
 * 草稿走 utils/testDraft（代码/语言/输入）：题面页样例「带入沉浸页」写的就是
 * 同一份，切页再回来原样保留；左栏样例「填充至输入」同样走 fillSampleToTest。
 * 首次进入的代码优先级：草稿 > 上次正式提交 > 偏好模板（与提交页同口径）。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Swal from 'sweetalert2'
import CodeEditor from '@/components/CodeEditor.vue'
import { problemsApi } from '@/api/problems'
import { submissionsApi } from '@/api/submissions'
import apiClient from '@/api/client'
import { LANGUAGES } from '@/constants/languages'
import { getCodeTemplate } from '@/utils/prefs'
import { renderRichText } from '@/utils/markdown'
import { difficultyColor } from '@/utils/difficulty'
import { useDifficultyReveal } from '@/utils/academicMode'
import { copyText } from '@/utils/codeCopy'
import { fillSignal, fillSampleToTest, getTestDraft } from '@/utils/testDraft'
import type { Problem, Submission } from '@/types'

const route = useRoute()
const router = useRouter()

const problemId = parseInt(route.params.id as string, 10)
// 比赛上下文：与提交页同口径（/problems/:id/immersive?contest=N）
const contestId = (() => {
  const v = parseInt(route.query.contest as string, 10)
  return Number.isFinite(v) && v > 0 ? v : null
})()

// 学术模式：难度默认隐藏，点一下只看这道题
const { isDifficultyVisible, revealDifficulty } = useDifficultyReveal()

const problem = ref<Problem | null>(null)
const loading = ref(true)
const loadError = ref('')

// ===== 草稿（模块级共享对象，跨页保留） =====
const draft = getTestDraft(problemId)
const language = ref(draft.language || 'cpp')
const code = ref(draft.code || '')
const input = ref(draft.input || '')

const editorLang = computed(
  () => LANGUAGES.find((l) => l.value === language.value)?.editorLang ?? 'cpp',
)

watch(language, (v) => {
  draft.language = v
  if (!code.value.trim()) code.value = getCodeTemplate(v)
})
watch(code, (v) => {
  draft.code = v
})
watch(input, (v) => {
  draft.input = v
})

// ===== 题面渲染（与题面页同口径的 markdown 分节） =====
const descriptionHtml = computed(() =>
  problem.value ? renderRichText(problem.value.description) : '',
)
const backgroundHtml = computed(() =>
  problem.value ? renderRichText(problem.value.background || '') : '',
)
const inputFormatHtml = computed(() =>
  problem.value ? renderRichText(problem.value.input_format || '') : '',
)
const outputFormatHtml = computed(() =>
  problem.value ? renderRichText(problem.value.output_format || '') : '',
)
const hintHtml = computed(() =>
  problem.value ? renderRichText(problem.value.hint || '') : '',
)

// 有任一扩展分节时，描述也带上「题目描述」小节标题（与题面页一致）
const hasSections = computed(() => {
  const p = problem.value
  if (!p) return false
  return !!(p.background || p.input_format || p.output_format || p.hint || (p.samples && p.samples.length))
})

const loadProblem = async () => {
  if (!Number.isFinite(problemId)) {
    loadError.value = '题目 ID 无效'
    return
  }
  try {
    problem.value = await problemsApi.get(problemId)
  } catch (err: any) {
    loadError.value = err?.response?.data?.detail || '加载题目失败'
  } finally {
    loading.value = false
  }
}

// ===== 样例：复制 / 填充至输入 =====
const fillToTest = (s: { input: string; output: string }) => {
  fillSampleToTest(problemId, s.input, s.output)
  input.value = draft.input
  verdict.value = null
}

// 外部样例填充广播（组件已挂载时的同步兜底；跳转进页的场景 onMounted 已读草稿）
watch(fillSignal, () => {
  input.value = draft.input
  verdict.value = null
})

// ===== 自测运行（try-run，与正式评测同口径） =====
const running = ref(false)
const runError = ref('')
const output = ref('')
const outputKind = ref<'idle' | 'stdout' | 'compile' | 'runtime'>('idle')
const timeMs = ref<number | null>(null)
const verdict = ref<'AC' | 'WA' | null>(null)

const RUN_STATUS_LABELS: Record<string, string> = {
  runtime_error: 'Runtime Error',
  time_limit_exceeded: 'Time Limit Exceeded',
  memory_limit_exceeded: 'Memory Limit Exceeded',
  output_limit_exceeded: 'Output Limit Exceeded',
  system_error: 'System Error',
}

/** 与正式评测同口径：每行去行尾空白、去结尾空行（judge.normalize_output） */
const norm = (s: string) => {
  const lines = s.replace(/\r\n/g, '\n').split('\n').map((l) => l.replace(/[ \t]+$/, ''))
  while (lines.length && lines[lines.length - 1] === '') lines.pop()
  return lines.join('\n')
}

const run = async () => {
  if (running.value || !code.value.trim()) return
  running.value = true
  runError.value = ''
  verdict.value = null
  output.value = ''
  outputKind.value = 'idle'
  timeMs.value = null
  try {
    const res: any = await apiClient.post(`/api/problems/${problemId}/try-run`, {
      language: language.value,
      code: code.value,
      input: input.value,
    })
    timeMs.value = typeof res.time_ms === 'number' ? res.time_ms : null
    if (res.status === 'compile_error') {
      outputKind.value = 'compile'
      output.value = res.stderr || 'Compile Error'
    } else if (res.status === 'ok') {
      outputKind.value = 'stdout'
      output.value = res.stdout || '（无输出）'
      // 输入就是填进来的样例 → 和样例输出比一比，给出判定
      const fill = draft.fill
      if (fill && input.value === fill.input) {
        verdict.value = norm(res.stdout || '') === norm(fill.expected) ? 'AC' : 'WA'
      }
    } else {
      outputKind.value = 'runtime'
      const head = RUN_STATUS_LABELS[res.status] || '运行异常'
      const tail = res.stderr || ''
      output.value = tail ? `${head}\n${tail}` : head
      if (res.stdout) {
        output.value = `—— 程序输出（中断前） ——\n${res.stdout}\n\n${output.value}`
      }
    }
  } catch (err: any) {
    runError.value = err?.response?.data?.detail || '运行失败：无法连接评测沙箱'
  } finally {
    running.value = false
  }
}

// ===== 正式提交：就地评测，不跳转（沉浸不打断） =====
const submitting = ref(false)
const lastSub = ref<Submission | null>(null)
let pollSeq = 0

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

const VERDICT_META: Record<string, { label: string; cls: string }> = {
  pending: { label: '排队中', cls: 'v-judging' },
  judging: { label: '评测中', cls: 'v-judging' },
  accepted: { label: 'Accepted', cls: 'v-ac' },
  wrong_answer: { label: 'Wrong Answer', cls: 'v-wa' },
  time_limit_exceeded: { label: 'Time Limit Exceeded', cls: 'v-tle' },
  memory_limit_exceeded: { label: 'Memory Limit Exceeded', cls: 'v-mle' },
  runtime_error: { label: 'Runtime Error', cls: 'v-re' },
  compile_error: { label: 'Compile Error', cls: 'v-ce' },
  output_limit_exceeded: { label: 'Output Limit Exceeded', cls: 'v-re' },
  system_error: { label: 'System Error', cls: 'v-se' },
  cancelled: { label: '成绩已取消', cls: 'v-se' },
}

const verdictMeta = computed(() => {
  const s = lastSub.value
  if (!s) return null
  return VERDICT_META[s.status] || { label: s.status, cls: 'v-se' }
})

const pollingVerdict = computed(
  () => !!lastSub.value && (lastSub.value.status === 'pending' || lastSub.value.status === 'judging'),
)

/** 就地轮询到终态；CE 把编译错误直接摊进输出区，不跳详情就能改 */
const pollVerdict = async (subId: number) => {
  const mySeq = ++pollSeq
  while (mySeq === pollSeq) {
    let s: Submission | null = null
    try {
      s = await submissionsApi.get(subId)
    } catch {
      await sleep(1500) // 网络抖动：退避后继续轮询（unmount 会终止）
      continue
    }
    if (mySeq !== pollSeq) return
    lastSub.value = s
    if (s.status !== 'pending' && s.status !== 'judging') {
      if (s.status === 'compile_error' && s.error_message) {
        outputKind.value = 'compile'
        output.value = s.error_message
        outputScrollTop()
      }
      break
    }
    await sleep(900)
  }
}

const outputScrollTop = () => {
  // 输出区可能正滚在中间：终态来了回到顶部让人先看到编译错误头
  document.querySelector('.im-output')?.scrollTo({ top: 0 })
}

const submit = async () => {
  if (submitting.value || !code.value.trim()) return
  submitting.value = true
  try {
    const sub = await submissionsApi.create(problemId, {
      code: code.value,
      language: language.value,
      contest_id: contestId ?? undefined,
    })
    lastSub.value = sub
    void pollVerdict(sub.id)
  } catch (err: any) {
    Swal.fire('提交失败', err?.response?.data?.detail || '请重试', 'error')
  } finally {
    submitting.value = false
  }
}

// ===== 首载：题目 + 代码（草稿 > 上次提交 > 偏好模板） =====
onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  document.addEventListener('mousemove', onDividerMove) // dragging 时才生效
  matchMedia('(max-width: 860px)').addEventListener('change', onStackChange)

  const problemPromise = loadProblem()
  if (!code.value) {
    // 草稿为空才拉上次提交；两者并行，就绪后再结束 loading（避免模板闪现被覆盖）
    const last = await submissionsApi.getMyLast(problemId).catch(() => null)
    if (last?.code && !code.value) {
      code.value = last.code
      if (LANGUAGES.some((l) => l.value === last.language)) language.value = last.language
    } else if (!code.value) {
      code.value = getCodeTemplate(language.value)
    }
  }
  await problemPromise
})

onBeforeUnmount(() => {
  pollSeq++ // 终止在途轮询
  window.removeEventListener('keydown', onKeydown)
  document.removeEventListener('mousemove', onDividerMove)
  document.removeEventListener('mouseup', onDividerUp)
  matchMedia('(max-width: 860px)').removeEventListener('change', onStackChange)
})

// ===== 退出：Esc（编辑器内不触发，留给补全/选区） + 工具条按钮 =====
const exit = () => {
  router.push({ path: `/problems/${problemId}`, query: route.query })
}

const onKeydown = (e: KeyboardEvent) => {
  // Ctrl/Cmd+Enter：编辑器内也能用 —— 运行自测，加 Shift 提交
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault()
    if (e.shiftKey) void submit()
    else void run()
    return
  }
  if (e.key !== 'Escape') return
  const t = e.target as HTMLElement | null
  if (t && t.closest('.cm-editor')) return // 编辑器焦点内 Esc 让给补全层
  exit()
}

// ===== 分屏拖拽（25%~75%，双击复位）；窄屏降级上下堆叠 =====
const leftPct = ref(42)
const dragging = ref(false)
const isStack = ref(window.matchMedia('(max-width: 860px)').matches)

const onStackChange = (e: MediaQueryListEvent) => {
  isStack.value = e.matches
}

const onDividerDown = (e: MouseEvent) => {
  if (isStack.value) return
  e.preventDefault()
  dragging.value = true
  document.body.classList.add('im-dragging')
  document.addEventListener('mouseup', onDividerUp)
}

const onDividerMove = (e: MouseEvent) => {
  if (!dragging.value) return
  const pct = (e.clientX / window.innerWidth) * 100
  leftPct.value = Math.min(75, Math.max(25, pct))
}

const onDividerUp = () => {
  dragging.value = false
  document.body.classList.remove('im-dragging')
  document.removeEventListener('mouseup', onDividerUp)
}

const bodyStyle = computed(() =>
  isStack.value ? {} : { gridTemplateColumns: `${leftPct.value}% 8px minmax(0, 1fr)` },
)
</script>

<template>
  <div class="im-page">
    <!-- 顶条：退出 / 题头 / 语言 / 运行 / 提交 / 就地评测徽标 -->
    <header class="im-toolbar">
      <button type="button" class="im-exit" title="退出沉浸模式" @click="exit">
        <i class="fa-solid fa-arrow-left"></i> 退出沉浸
        <kbd>Esc</kbd>
      </button>

      <div v-if="problem" class="im-head">
        <span class="im-number">{{ problem.problem_number }}</span>
        <span class="im-title">{{ problem.title }}</span>
        <span
          v-if="isDifficultyVisible(problem.id)"
          class="im-diff"
          :style="{ background: difficultyColor(problem.difficulty) }"
        >{{ problem.difficulty }}</span>
        <button
          v-else
          type="button"
          class="im-diff im-diff-reveal"
          title="学术模式：难度默认隐藏，点一下只看这道题"
          @click="revealDifficulty(problem.id)"
        >显示难度</button>
        <span v-if="problem.is_spj" class="im-tag">Special Judge</span>
        <span v-if="contestId" class="im-tag im-contest">
          <i class="fa-solid fa-trophy"></i> 比赛模式
        </span>
      </div>

      <div class="im-actions">
        <select v-model="language" class="im-lang" title="选择语言">
          <option v-for="l in LANGUAGES" :key="l.value" :value="l.value">{{ l.label }}</option>
        </select>
        <button
          type="button"
          class="im-btn"
          :disabled="running || !code.trim()"
          title="用下方输入跑一次（Ctrl+Enter）"
          @click="run"
        >
          <i class="fa-solid" :class="running ? 'fa-circle-notch fa-spin' : 'fa-play'"></i>
          {{ running ? '运行中…' : '运行' }}
        </button>
        <button
          type="button"
          class="im-btn primary"
          :disabled="submitting || !code.trim()"
          title="正式提交评测（Ctrl+Shift+Enter）"
          @click="submit"
        >
          <i class="fa-solid fa-paper-plane"></i>
          {{ submitting ? '提交中…' : '提交' }}
        </button>

        <!-- 就地评测徽标：出分前脉动，出分后常驻；详情链接给想看逐测试点的人 -->
        <Transition name="im-badge-in">
          <span v-if="lastSub && verdictMeta" class="im-verdict" :class="verdictMeta.cls">
            <template v-if="pollingVerdict">
              <i class="fa-solid fa-circle-notch fa-spin"></i> {{ verdictMeta.label }}
            </template>
            <template v-else>
              <i
                class="fa-solid"
                :class="lastSub.status === 'accepted' ? 'fa-circle-check' : 'fa-circle-xmark'"
              ></i>
              {{ verdictMeta.label }}
              <span v-if="lastSub.time_used != null" class="im-vtime">{{ lastSub.time_used }} ms</span>
            </template>
          </span>
        </Transition>
        <button
          v-if="lastSub && !pollingVerdict"
          type="button"
          class="im-detail"
          title="查看逐测试点详情"
          @click="router.push({ path: `/submissions/${lastSub.id}`, query: route.query })"
        >详情</button>
      </div>
    </header>

    <!-- 主体：左题面 | 拖拽分隔条 | 右工作区 -->
    <div class="im-body" :class="{ stack: isStack }" :style="bodyStyle">
      <aside class="im-statement">
        <div v-if="loading" class="im-empty">加载中…</div>
        <div v-else-if="loadError" class="im-empty">
          {{ loadError }}
          <button type="button" class="im-btn" @click="router.push('/problems')">返回题库</button>
        </div>

        <template v-else-if="problem">
          <div class="im-limits">
            <span>时间限制：<b>{{ problem.time_limit }} ms</b></span>
            <span>内存限制：<b>{{ problem.memory_limit }} MB</b></span>
          </div>

          <template v-if="hasSections">
            <template v-if="problem.background">
              <div class="im-sec-head">题目背景</div>
              <div class="prose im-body-html" v-html="backgroundHtml"></div>
            </template>
            <template v-if="problem.description">
              <div class="im-sec-head">题目描述</div>
              <div class="prose im-body-html" v-html="descriptionHtml"></div>
            </template>
            <template v-if="problem.input_format">
              <div class="im-sec-head">输入格式</div>
              <div class="prose im-body-html" v-html="inputFormatHtml"></div>
            </template>
            <template v-if="problem.output_format">
              <div class="im-sec-head">输出格式</div>
              <div class="prose im-body-html" v-html="outputFormatHtml"></div>
            </template>
            <template v-if="problem.samples && problem.samples.length">
              <div class="im-sec-head">样例</div>
              <div v-for="(s, i) in problem.samples" :key="i" class="im-sample">
                <div class="im-sample-title">
                  样例 #{{ i + 1 }}
                  <button type="button" class="im-sample-fill" @click="fillToTest(s)">
                    <i class="fa-solid fa-arrow-right-to-bracket"></i> 填充至输入
                  </button>
                </div>
                <div class="im-io">
                  <div class="im-io-box">
                    <div class="im-io-label">
                      <span>输入</span>
                      <button type="button" class="im-copy" @click="copyText(s.input)">
                        <i class="fa-solid fa-copy"></i> 复制
                      </button>
                    </div>
                    <pre>{{ s.input }}</pre>
                  </div>
                  <div class="im-io-box">
                    <div class="im-io-label">
                      <span>输出</span>
                      <button type="button" class="im-copy" @click="copyText(s.output)">
                        <i class="fa-solid fa-copy"></i> 复制
                      </button>
                    </div>
                    <pre>{{ s.output }}</pre>
                  </div>
                </div>
              </div>
            </template>
            <template v-if="problem.hint">
              <div class="im-sec-head">提示说明</div>
              <div class="prose im-body-html" v-html="hintHtml"></div>
            </template>
          </template>
          <div v-else class="prose im-body-html" v-html="descriptionHtml"></div>
        </template>
      </aside>

      <div
        class="im-divider"
        :class="{ dragging }"
        title="拖动调整分屏比例（双击复位）"
        @mousedown="onDividerDown"
        @dblclick="leftPct = 42"
      ></div>

      <section class="im-work">
        <div class="im-editor-wrap">
          <CodeEditor
            v-model="code"
            :language="editorLang"
            height="100%"
            loadable
            :max-chars="100000"
          />
        </div>

        <div class="im-bottom">
          <div class="im-pane">
            <div class="im-pane-head">
              <span><i class="fa-solid fa-arrow-left-long"></i> 输入</span>
              <span v-if="draft.fill && input === draft.fill.input" class="im-fill-hint">样例已填充</span>
              <button v-if="input" type="button" class="im-pane-op" @click="input = ''">清空</button>
            </div>
            <textarea
              v-model="input"
              class="im-input"
              spellcheck="false"
              placeholder="自测输入（可从左侧样例一键填充）"
            ></textarea>
          </div>
          <div class="im-pane">
            <div class="im-pane-head">
              <span><i class="fa-solid fa-arrow-right-long"></i> 输出</span>
              <span v-if="verdict === 'AC'" class="im-run-verdict ac">
                <i class="fa-solid fa-circle-check"></i> Accepted
              </span>
              <span v-else-if="verdict === 'WA'" class="im-run-verdict wa">
                <i class="fa-solid fa-circle-xmark"></i> Wrong Answer
              </span>
              <span v-if="timeMs !== null" class="im-time">{{ timeMs }} ms</span>
            </div>
            <pre class="im-output" :class="outputKind"><template v-if="runError"><span class="im-run-error">{{ runError }}</span></template><template v-else>{{ output || (running ? '运行中…' : '') }}</template></pre>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.im-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg, #f4f6fb);
  overflow: hidden;
}

/* ===== 顶条 ===== */
.im-toolbar {
  flex: none;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 14px;
  background: var(--surface);
  border-bottom: 1px solid var(--border-color);
  box-shadow: 0 2px 10px rgba(15, 18, 32, 0.06);
  min-width: 0;
}

.im-exit {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 32px;
  padding: 0 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--surface-plain, var(--surface));
  color: var(--text-sub);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.im-exit:hover {
  background: var(--surface-strong);
  color: var(--text-strong);
}

.im-exit kbd {
  padding: 1px 5px;
  border: 1px solid var(--border-color);
  border-bottom-width: 2px;
  border-radius: 4px;
  background: var(--surface);
  color: var(--text-sub);
  font-family: inherit;
  font-size: 10.5px;
}

.im-head {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 9px;
  overflow: hidden;
}

.im-number {
  flex: none;
  padding: 2px 8px;
  border-radius: 6px;
  background: color-mix(in srgb, var(--primary) 12%, transparent);
  color: var(--primary);
  font-size: 12px;
  font-weight: 700;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.im-title {
  min-width: 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.im-diff {
  flex: none;
  padding: 2px 9px;
  border-radius: 999px;
  color: #fff;
  font-size: 11.5px;
  font-weight: 700;
}

.im-diff-reveal {
  border: 1px dashed var(--border-color);
  background: var(--surface-strong);
  color: var(--text-sub);
  cursor: pointer;
}

.im-tag {
  flex: none;
  padding: 2px 8px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: var(--surface-strong);
  color: var(--text-sub);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.im-contest {
  color: #b45309;
  border-color: color-mix(in srgb, #f59e0b 55%, transparent);
}

.im-actions {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
}

.im-lang {
  height: 32px;
  padding: 0 8px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text-strong);
  font-size: 12.5px;
  outline: none;
  cursor: pointer;
}

.im-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 14px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text-strong);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, opacity 0.15s;
  white-space: nowrap;
}

.im-btn:hover:not(:disabled) {
  background: var(--surface-strong);
}

.im-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.im-btn.primary {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}

.im-btn.primary:hover:not(:disabled) {
  filter: brightness(1.08);
}

/* ===== 就地评测徽标 ===== */
.im-verdict {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 12px;
  border-radius: 8px;
  font-size: 12.5px;
  font-weight: 700;
  white-space: nowrap;
}

.im-verdict.v-judging {
  background: color-mix(in srgb, var(--primary) 12%, transparent);
  color: var(--primary);
}

.im-verdict.v-ac {
  background: color-mix(in srgb, #16a34a 14%, transparent);
  color: #16a34a;
}

.im-verdict.v-wa,
.im-verdict.v-ce {
  background: color-mix(in srgb, #dc2626 13%, transparent);
  color: #dc2626;
}

.im-verdict.v-tle,
.im-verdict.v-mle,
.im-verdict.v-re {
  background: color-mix(in srgb, #f59e0b 16%, transparent);
  color: #b45309;
}

.im-verdict.v-se {
  background: color-mix(in srgb, #64748b 15%, transparent);
  color: #64748b;
}

.im-vtime {
  font-weight: 500;
  opacity: 0.75;
  font-variant-numeric: tabular-nums;
}

.im-detail {
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text-sub);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.im-detail:hover {
  background: var(--surface-strong);
  color: var(--text-strong);
}

.im-badge-in-enter-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}

.im-badge-in-enter-from {
  opacity: 0;
  transform: translateY(-4px);
}

/* ===== 主体分屏 ===== */
.im-body {
  flex: 1;
  min-height: 0;
  display: grid;
}

.im-statement {
  min-width: 0;
  overflow-y: auto;
  padding: 18px 22px 40px;
  background: var(--surface);
  scroll-behavior: smooth;
}

.im-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 60px 0;
  color: var(--text-sub);
  font-size: 14px;
}

.im-limits {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 14px;
  padding: 9px 13px;
  border: 1px solid var(--border-color);
  border-radius: 9px;
  background: var(--surface-strong);
  color: var(--text-sub);
  font-size: 12.5px;
}

.im-limits b {
  color: var(--text-strong);
}

.im-sec-head {
  margin: 20px 0 8px;
  padding-bottom: 6px;
  border-bottom: 2px solid color-mix(in srgb, var(--primary) 30%, transparent);
  color: var(--text-strong);
  font-size: 14.5px;
  font-weight: 700;
}

.im-sec-head:first-of-type {
  margin-top: 4px;
}

.im-body-html {
  color: var(--text-primary);
  font-size: 14px;
  line-height: 1.75;
  word-break: break-word;
}

.im-sample {
  margin-bottom: 16px;
}

.im-sample-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
  color: var(--text-strong);
  font-size: 13px;
  font-weight: 700;
}

.im-sample-fill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border: 1px solid color-mix(in srgb, var(--primary) 40%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--primary) 8%, transparent);
  color: var(--primary);
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}

.im-sample-fill:hover {
  background: color-mix(in srgb, var(--primary) 16%, transparent);
}

.im-io {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.im-io-box {
  min-width: 0;
  border: 1px solid var(--border-color);
  border-radius: 9px;
  overflow: hidden;
  background: var(--surface-strong);
}

.im-io-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 10px;
  border-bottom: 1px solid var(--border-color);
  color: var(--text-sub);
  font-size: 11.5px;
  font-weight: 700;
}

.im-copy {
  border: none;
  background: none;
  color: var(--primary);
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  padding: 2px 4px;
}

.im-io-box pre {
  margin: 0;
  padding: 9px 11px;
  overflow-x: auto;
  color: var(--text-primary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ===== 分隔条 ===== */
.im-divider {
  position: relative;
  cursor: col-resize;
  background: var(--border-color);
  transition: background 0.15s;
}

.im-divider:hover,
.im-divider.dragging {
  background: var(--primary);
}

/* ===== 右侧工作区 ===== */
.im-work {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface-plain, var(--surface));
}

.im-editor-wrap {
  flex: 3;
  min-height: 0;
}

.im-bottom {
  flex: 1;
  min-height: 132px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1px;
  background: var(--border-color);
  border-top: 1px solid var(--border-color);
}

.im-pane {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  background: var(--surface-plain, var(--surface));
}

.im-pane-head {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 11px;
  border-bottom: 1px solid var(--border-color);
  color: var(--text-sub);
  font-size: 11.5px;
  font-weight: 700;
}

.im-fill-hint {
  color: var(--primary);
  font-weight: 600;
}

.im-pane-op {
  margin-left: auto;
  border: none;
  background: none;
  color: var(--text-sub);
  font-size: 11px;
  cursor: pointer;
  padding: 2px 4px;
}

.im-pane-op:hover {
  color: #dc2626;
}

.im-input {
  flex: 1;
  min-height: 0;
  resize: none;
  border: none;
  outline: none;
  padding: 8px 11px;
  background: var(--surface-plain, var(--surface));
  color: var(--text-strong);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.55;
}

.im-input::placeholder {
  color: var(--text-sub);
  opacity: 0.7;
}

.im-output {
  flex: 1;
  min-height: 0;
  margin: 0;
  padding: 8px 11px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--surface-plain, var(--surface));
  color: var(--text-strong);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.55;
}

.im-output.compile {
  color: #dc2626;
}

.im-output.runtime {
  color: #b45309;
}

.im-run-error {
  color: #dc2626;
  font-weight: 600;
}

.im-run-verdict {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-weight: 700;
}

.im-run-verdict.ac {
  color: #16a34a;
}

.im-run-verdict.wa {
  color: #dc2626;
}

.im-time {
  margin-left: auto;
  font-weight: 500;
  color: var(--text-sub);
  font-variant-numeric: tabular-nums;
}

/* 拖拽期间禁掉全局选区，免得拖出一屏高亮 */
:global(body.im-dragging) {
  user-select: none;
  cursor: col-resize;
}

/* ===== 窄屏：上下堆叠（题面在上、工作区在下），分隔条退役 ===== */
@media (max-width: 860px) {
  .im-page {
    height: auto;
    min-height: 100vh;
    overflow: visible;
  }

  .im-body.stack {
    display: flex;
    flex-direction: column;
  }

  .im-statement {
    max-height: 46vh;
    padding: 14px 14px 24px;
  }

  .im-divider {
    display: none;
  }

  .im-work {
    min-height: 72vh;
  }

  .im-editor-wrap {
    min-height: 300px;
  }

  .im-bottom {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(96px, 1fr) minmax(110px, 1fr);
  }

  .im-io {
    grid-template-columns: 1fr;
  }

  .im-toolbar {
    flex-wrap: wrap;
    gap: 8px;
  }

  .im-head {
    order: 3;
    width: 100%;
  }

  .im-title {
    font-size: 14px;
  }
}
</style>
