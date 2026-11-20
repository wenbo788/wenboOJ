<script setup lang="ts">
import { reactive, ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Swal from 'sweetalert2'
import { problemsApi } from '@/api/problems'
import { testCasesApi } from '@/api/submissions'
import { useAuthStore } from '@/stores/auth'
import { renderRichText } from '@/utils/markdown'
import MarkdownSplitEditor from '@/components/MarkdownSplitEditor.vue'
import CodeEditor from '@/components/CodeEditor.vue'
import { DIFFICULTY_LIST } from '@/utils/difficulty'
import { formatBytes } from '@/utils/format'
import { downloadAttachmentFile } from '@/utils/attachment'
import {
  parseProblemMarkdown,
  exportProblemMarkdown,
  type ParsedProblemMarkdown,
} from '@/utils/problemMarkdown'
import type { ProblemDifficulty, ProblemSample, ProblemReviewStatus, ProblemAttachment, TestCaseItem } from '@/types'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

// 题目管理员：公开即发布、可指派出题人；普通用户：公开需走审核
const canManage = computed(() => !!authStore.currentUser?.can_manage_problems)
// 当前题审核状态（编辑模式加载后填充）
const reviewStatus = ref<ProblemReviewStatus | ''>('')
const reviewReason = ref('')

const MAX_TEXT_CASE_BYTES = 20 * 1024 * 1024
const inputFileInputRef = ref<HTMLInputElement | null>(null)
const outputFileInputRef = ref<HTMLInputElement | null>(null)
const zipInputRef = ref<HTMLInputElement | null>(null)
const uploadingZip = ref(false)

const readTextCaseFile = async (file: File): Promise<string> => {
  if (file.size > MAX_TEXT_CASE_BYTES) {
    throw new Error(`文件过大：${(file.size / (1024 * 1024)).toFixed(1)} MB，单个文本文件最多支持 20 MB`)
  }
  return await file.text()
}

const importCaseInputFile = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return

  try {
    newCase.input_data = await readTextCaseFile(file)
    Swal.fire({
      icon: 'success',
      title: '已读取输入文件',
      timer: 1000,
      showConfirmButton: false,
    })
  } catch (err: any) {
    Swal.fire('读取失败', err?.message || '请重试', 'error')
  }
}

const importCaseOutputFile = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return

  try {
    newCase.expected_output = await readTextCaseFile(file)
    Swal.fire({
      icon: 'success',
      title: '已读取输出文件',
      timer: 1000,
      showConfirmButton: false,
    })
  } catch (err: any) {
    Swal.fire('读取失败', err?.message || '请重试', 'error')
  }
}

const editingId = computed(() => {
  const id = parseInt(route.params.id as string, 10)
  return Number.isFinite(id) ? id : null
})

const teamId = computed(() => {
  const v = parseInt(route.query.team_id as string, 10)
  return Number.isFinite(v) && v > 0 ? v : null
})
const editingTeamId = ref<number | null>(null)
const isTeamProblem = computed(() => !!teamId.value || !!editingTeamId.value || String(editingNumber.value).startsWith('T'))

// ===== 表单 =====
const form = reactive({
  title: '',
  difficulty: '暂无评定' as ProblemDifficulty,
  source: '',
  tagsInput: '',
  time_limit: 1000,
  memory_limit: 128,
  is_public: false,
  allow_solution_submission: true,
  is_spj: false,
  spj_language: 'cpp',
  spj_code: '',
  author: '',
  background: '',
  description: '',
  input_format: '',
  output_format: '',
  hint: '',
})
const spjEditorLang = computed(() => (form.spj_language === 'python3' ? 'python' : 'cpp'))
const samples = ref<ProblemSample[]>([])

// 洛谷式分节：每节都是「编辑器 + 实时预览」
const SECTIONS = [
  { key: 'background', label: '题目背景', placeholder: '题目背景（可留空）。例如：最近世界杯开始了，小B迫不及待想去看足球比赛。' },
  { key: 'description', label: '题目描述', placeholder: '题目描述。支持 Markdown 与 $LaTeX$ 公式。' },
  { key: 'input_format', label: '输入格式', placeholder: '输入格式说明。' },
  { key: 'output_format', label: '输出格式', placeholder: '输出格式说明。' },
  { key: 'hint', label: '提示说明', placeholder: '样例解释、数据范围等（可留空）。' },
] as const

type SectionKey = (typeof SECTIONS)[number]['key']

const previewOf = (key: SectionKey) => renderRichText(form[key] || '')

// ===== 加载（编辑模式） =====
const loading = ref(true)
const editingNumber = ref('')
const loadProblem = async () => {
  if (editingId.value === null) {
    loading.value = false
    return
  }
  try {
    const p = await problemsApi.get(editingId.value)
    editingNumber.value = p.problem_number || ''
    editingTeamId.value = p.team_id ?? null
    form.title = p.title
    form.difficulty = p.difficulty
    form.source = p.source || ''
    form.tagsInput = (p.tags || []).join(',')
    form.time_limit = p.time_limit
    form.memory_limit = p.memory_limit
    form.is_public = p.is_public
    form.allow_solution_submission = p.allow_solution_submission !== false
    reviewStatus.value = p.review_status || 'approved'
    reviewReason.value = p.review_reason || ''
    form.is_spj = !!p.is_spj
    form.spj_language = p.spj_language || 'cpp'
    form.spj_code = p.spj_code || ''
    form.author = p.author?.username || ''
    form.background = p.background || ''
    form.description = p.description || ''
    form.input_format = p.input_format || ''
    form.output_format = p.output_format || ''
    form.hint = p.hint || ''
    samples.value = (p.samples || []).map((s) => ({ input: s.input || '', output: s.output || '' }))
    attachments.value = p.attachments || []
    subtaskConfig.value = (p.subtask_config || []).map((s) => ({
      id: Number(s.id),
      score: Number(s.score) || 0,
      name: s.name || `Subtask #${s.id}`,
    }))
    loadTestCases()
  } catch (err: any) {
    Swal.fire('加载失败', err.response?.data?.detail || '请重试', 'error')
  } finally {
    loading.value = false
  }
}

// ===== 样例组 =====
const addSample = () => samples.value.push({ input: '', output: '' })
const removeSample = (i: number) => samples.value.splice(i, 1)

// ===== Markdown 题面导入与自动填充 =====
const mdFileInputRef = ref<HTMLInputElement | null>(null)
const MAX_MD_FILE_BYTES = 5 * 1024 * 1024

const triggerMdImport = () => {
  mdFileInputRef.value?.click()
}

const applyParsedProblem = async (parsed: ParsedProblemMarkdown, fileName: string) => {
  const detectedSections: string[] = []
  if (parsed.background) detectedSections.push('题目背景')
  if (parsed.description) detectedSections.push('题目描述')
  if (parsed.input_format) detectedSections.push('输入格式')
  if (parsed.output_format) detectedSections.push('输出格式')
  if (parsed.hint) detectedSections.push('提示说明')

  const sampleCount = parsed.samples?.length || 0

  const summaryItems: string[] = []
  if (parsed.title) {
    summaryItems.push(`<li><strong>题目名称</strong>：${parsed.title}</li>`)
  } else {
    summaryItems.push('<li style="color: #94a3b8;"><strong>题目名称</strong>：未识别（保留原值）</li>')
  }
  if (parsed.difficulty) {
    summaryItems.push(`<li><strong>题目难度</strong>：${parsed.difficulty}</li>`)
  }
  if (parsed.time_limit || parsed.memory_limit) {
    const limits = [
      parsed.time_limit ? `${parsed.time_limit} ms` : '',
      parsed.memory_limit ? `${parsed.memory_limit} MB` : '',
    ].filter(Boolean).join(' / ')
    summaryItems.push(`<li><strong>时空限制</strong>：${limits}</li>`)
  }
  if (parsed.source) {
    summaryItems.push(`<li><strong>题目来源</strong>：${parsed.source}</li>`)
  }
  if (parsed.tags && parsed.tags.length) {
    summaryItems.push(`<li><strong>算法标签</strong>：${parsed.tags.join(', ')}</li>`)
  }
  summaryItems.push(
    `<li><strong>题面分节</strong>：${detectedSections.length ? detectedSections.join('、') : '全文自动填入「题目描述」'}</li>`
  )
  summaryItems.push(`<li><strong>样例组</strong>：共 ${sampleCount} 组</li>`)

  const summaryHtml = `
    <div style="text-align: left; font-size: 13px; line-height: 1.8; color: var(--text-strong);">
      <p style="margin-bottom: 8px;">已成功解析「<strong>${fileName}</strong>」：</p>
      <ul style="margin: 0; padding-left: 20px; list-style-type: disc;">
        ${summaryItems.join('')}
      </ul>
      <p style="margin-top: 10px; color: var(--text-sub); font-size: 12px;">
        点击「确认填充」将自动覆盖对应表单项与样例组，未涉及的已有内容将保持原样。
      </p>
    </div>
  `

  const confirmRes = await Swal.fire({
    title: '自动填充题面',
    html: summaryHtml,
    icon: 'info',
    showCancelButton: true,
    confirmButtonText: '确认填充',
    cancelButtonText: '取消',
    confirmButtonColor: 'var(--primary)',
    cancelButtonColor: '#94a3b8',
  })

  if (!confirmRes.isConfirmed) return

  if (parsed.title) form.title = parsed.title
  if (parsed.difficulty) form.difficulty = parsed.difficulty
  if (parsed.source) form.source = parsed.source
  if (parsed.tags && parsed.tags.length) form.tagsInput = parsed.tags.join(',')
  if (typeof parsed.time_limit === 'number') form.time_limit = parsed.time_limit
  if (typeof parsed.memory_limit === 'number') form.memory_limit = parsed.memory_limit

  if (parsed.background !== undefined) form.background = parsed.background
  if (parsed.description !== undefined) form.description = parsed.description
  if (parsed.input_format !== undefined) form.input_format = parsed.input_format
  if (parsed.output_format !== undefined) form.output_format = parsed.output_format
  if (parsed.hint !== undefined) form.hint = parsed.hint

  if (parsed.samples && parsed.samples.length > 0) {
    samples.value = parsed.samples.map((s) => ({ input: s.input, output: s.output }))
  }

  Swal.fire({
    icon: 'success',
    title: '已自动填充题面',
    text: `已填充 ${detectedSections.length} 个分节与 ${sampleCount} 组样例`,
    timer: 1400,
    showConfirmButton: false,
  })
}

const importMdFile = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return

  if (file.size > MAX_MD_FILE_BYTES) {
    Swal.fire({
      icon: 'warning',
      title: '文件过大',
      text: `文件大小 ${(file.size / (1024 * 1024)).toFixed(1)} MB，单个 Markdown 题面文件最多支持 5 MB`,
    })
    return
  }

  try {
    const text = await file.text()
    if (!text.trim()) {
      Swal.fire('文件内容为空', '所选 Markdown 文件没有文本内容', 'warning')
      return
    }

    const parsed = parseProblemMarkdown(text)
    await applyParsedProblem(parsed, file.name)
  } catch (err: any) {
    Swal.fire('解析失败', err?.message || '读取或解析 Markdown 文件失败，请重试', 'error')
  }
}

const handleFileDrop = async (event: DragEvent) => {
  const file = event.dataTransfer?.files?.[0]
  if (!file) return
  if (!file.name.match(/\.(md|markdown|txt)$/i)) {
    Swal.fire('格式不支持', '请拖拽 .md / .markdown / .txt 格式的题面文件', 'warning')
    return
  }
  if (file.size > MAX_MD_FILE_BYTES) {
    Swal.fire({
      icon: 'warning',
      title: '文件过大',
      text: `文件大小 ${(file.size / (1024 * 1024)).toFixed(1)} MB，单个 Markdown 题面文件最多支持 5 MB`,
    })
    return
  }

  try {
    const text = await file.text()
    if (!text.trim()) {
      Swal.fire('文件内容为空', '所选 Markdown 文件没有文本内容', 'warning')
      return
    }
    const parsed = parseProblemMarkdown(text)
    await applyParsedProblem(parsed, file.name)
  } catch (err: any) {
    Swal.fire('解析失败', err?.message || '读取或解析 Markdown 文件失败，请重试', 'error')
  }
}

const exportMdFile = () => {
  try {
    const md = exportProblemMarkdown({
      title: form.title,
      difficulty: form.difficulty,
      source: form.source,
      tags: form.tagsInput.split(/[,，]/).map((t) => t.trim()).filter(Boolean),
      time_limit: form.time_limit,
      memory_limit: form.memory_limit,
      background: form.background,
      description: form.description,
      input_format: form.input_format,
      output_format: form.output_format,
      hint: form.hint,
      samples: samples.value,
    })
    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    const fileName = (form.title.trim() || 'problem') + '.md'
    a.href = url
    a.download = fileName
    a.click()
    URL.revokeObjectURL(url)
  } catch (err: any) {
    Swal.fire('导出失败', err?.message || '请重试', 'error')
  }
}

// ===== ZIP 压缩包导入（含题面与测试点） =====
const zipProblemInputRef = ref<HTMLInputElement | null>(null)
const importingZip = ref(false)

const triggerZipProblemImport = () => {
  zipProblemInputRef.value?.click()
}

const handleZipProblemImport = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return

  if (!file.name.toLowerCase().endsWith('.zip')) {
    Swal.fire('格式错误', '请选择 .zip 格式压缩包', 'warning')
    return
  }

  if (file.size > 50 * 1024 * 1024) {
    Swal.fire({
      icon: 'warning',
      title: '压缩包过大',
      text: `文件大小 ${(file.size / (1024 * 1024)).toFixed(1)} MB，ZIP 压缩包最多支持 50 MB`,
    })
    return
  }

  if (editingId.value !== null) {
    const confirmRes = await Swal.fire({
      title: '导入确认',
      html: `检测到正在编辑题目<strong>《${form.title || editingNumber.value}》</strong>。<br/>导入 ZIP 将更新题面分节，并<strong>重新导入全部测试点</strong>，是否继续？`,
      icon: 'question',
      showCancelButton: true,
      confirmButtonText: '确定导入',
      cancelButtonText: '取消',
    })
    if (!confirmRes.isConfirmed) return
  }

  importingZip.value = true
  try {
    const res = await problemsApi.importZip(file, {
      problem_id: editingId.value ?? undefined,
      team_id: teamId.value ?? undefined,
      is_public: form.is_public,
      clear_existing_cases: true,
    })

    if (editingId.value !== null) {
      await Swal.fire({
        icon: 'success',
        title: '题目与测试点导入成功！',
        html: `成功同步更新题面，并导入 <strong>${res.imported_test_cases}</strong> 个测试点。`,
      })
      await loadProblem()
      await loadTestCases()
    } else {
      await Swal.fire({
        icon: 'success',
        title: '题目导入成功！',
        html: `题目<strong>《${res.problem.title}》</strong>(${res.problem.problem_number}) 已成功创建，并导入 <strong>${res.imported_test_cases}</strong> 个测试点。`,
      })
      if (isTeamProblem.value && teamId.value) {
        router.push(`/problems/${res.problem.id}/edit?team_id=${teamId.value}`)
      } else {
        router.push(`/problems/${res.problem.id}/edit`)
      }
    }
  } catch (err: any) {
    const detail = err?.response?.data?.detail || err?.message || '导入失败，请检查压缩包内容'
    Swal.fire('导入失败', detail, 'error')
  } finally {
    importingZip.value = false
  }
}


// ===== 测试点（评测用，建题后管理） =====
const testCases = ref<TestCaseItem[]>([])
const newCase = reactive({ input_data: '', expected_output: '' })
const loadingCases = ref(false)
const deletingCaseId = ref<number | null>(null)
const clearingCases = ref(false)
const batchDeleting = ref(false)
const selectedCaseIds = ref<number[]>([])

const allSelected = computed(() => {
  return testCases.value.length > 0 && selectedCaseIds.value.length === testCases.value.length
})

const toggleSelectAll = () => {
  if (allSelected.value) {
    selectedCaseIds.value = []
  } else {
    selectedCaseIds.value = testCases.value.map((tc) => tc.id)
  }
}

// 体积格式化统一走 utils/format（与 ProblemDetail 共用同一实现）

const loadTestCases = async () => {
  if (editingId.value === null) return
  loadingCases.value = true
  try {
    const res = await testCasesApi.list(editingId.value)
    testCases.value = res
    selectedCaseIds.value = selectedCaseIds.value.filter((id) => res.some((tc) => tc.id === id))
  } catch (err: any) {
    testCases.value = []
    Swal.fire('加载测试点失败', err.response?.data?.detail || '网络连接超时或服务异常，请重试', 'error')
  } finally {
    loadingCases.value = false
  }
}

const addCase = async () => {
  if (editingId.value === null) return
  if (!newCase.input_data && !newCase.expected_output) {
    Swal.fire('请填写测试点内容', '', 'warning')
    return
  }

  const inputBytes = new TextEncoder().encode(newCase.input_data).length
  const outputBytes = new TextEncoder().encode(newCase.expected_output).length
  if (inputBytes > MAX_TEXT_CASE_BYTES || outputBytes > MAX_TEXT_CASE_BYTES) {
    Swal.fire('测试点文件过大', '单个输入/输出文本最多支持 20 MB', 'warning')
    return
  }

  try {
    await testCasesApi.create(editingId.value, {
      input_data: newCase.input_data,
      expected_output: newCase.expected_output,
    })
    newCase.input_data = ''
    newCase.expected_output = ''
    await loadTestCases()
    Swal.fire({
      icon: 'success',
      title: '已添加测试点',
      timer: 1000,
      showConfirmButton: false,
    })
  } catch (err: any) {
    Swal.fire('添加失败', err.response?.data?.detail || '请重试', 'error')
  }
}

const removeCase = async (id: number, orderNum: number) => {
  if (editingId.value === null) return
  const confirmRes = await Swal.fire({
    title: `确定删除测试点 #${orderNum}？`,
    text: '此操作不可恢复',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonText: '确定删除',
    cancelButtonText: '取消',
    confirmButtonColor: '#d33',
  })
  if (!confirmRes.isConfirmed) return

  deletingCaseId.value = id
  try {
    await testCasesApi.remove(editingId.value, id)
    testCases.value = testCases.value.filter((tc) => tc.id !== id)
    selectedCaseIds.value = selectedCaseIds.value.filter((cid) => cid !== id)
    Swal.fire({
      icon: 'success',
      title: '已删除测试点',
      timer: 900,
      showConfirmButton: false,
    })
    await loadTestCases()
  } catch (err: any) {
    Swal.fire('删除失败', err.response?.data?.detail || '请重试', 'error')
  } finally {
    deletingCaseId.value = null
  }
}

const batchDeleteCases = async () => {
  if (editingId.value === null || selectedCaseIds.value.length === 0) return
  const count = selectedCaseIds.value.length
  const confirmRes = await Swal.fire({
    title: `确定删除选中的 ${count} 个测试点？`,
    text: '此操作不可恢复',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonText: '确定批量删除',
    cancelButtonText: '取消',
    confirmButtonColor: '#d33',
  })
  if (!confirmRes.isConfirmed) return

  batchDeleting.value = true
  try {
    const res = await testCasesApi.batchDelete(editingId.value, selectedCaseIds.value)
    selectedCaseIds.value = []
    Swal.fire({
      icon: 'success',
      title: `成功删除 ${res.deleted_count} 个测试点`,
      timer: 1200,
      showConfirmButton: false,
    })
    await loadTestCases()
  } catch (err: any) {
    Swal.fire('批量删除失败', err.response?.data?.detail || '请重试', 'error')
  } finally {
    batchDeleting.value = false
  }
}

const formatPreview = (s: string) => (!s ? '' : s.length > 300 ? s.slice(0, 300) + `\n... (共 ${s.length} 字符)` : s)

const uploadZip = async (e: Event) => {
  const inp = e.target as HTMLInputElement
  const f = inp.files?.[0]
  inp.value = ''
  if (!f || editingId.value === null) return

  const choiceRes = await Swal.fire({
    title: '选择导入方式',
    text: '请选择如何处理本次 ZIP 压缩包中的测试数据：',
    icon: 'question',
    showCancelButton: true,
    showDenyButton: true,
    confirmButtonText: '覆盖已有测试点',
    denyButtonText: '追加到末尾',
    cancelButtonText: '取消导入',
    confirmButtonColor: '#d33',
    denyButtonColor: '#3085d6',
  })

  let clear = false
  if (choiceRes.isConfirmed) {
    clear = true
  } else if (choiceRes.isDenied) {
    clear = false
  } else {
    return
  }

  uploadingZip.value = true
  try {
    const res: any = await testCasesApi.uploadZip(editingId.value, f, clear)
    await loadTestCases()
    if (res.subtask_config) {
      subtaskConfig.value = (res.subtask_config || []).map((s: any) => ({
        id: Number(s.id),
        score: Number(s.score) || 0,
        name: s.name || `Subtask #${s.id}`,
      }))
    }
    const extraMsg = res.detected_subtasks?.length ? `，已自动识别 ${res.detected_subtasks.length} 个子任务` : ''
    Swal.fire({
      icon: 'success',
      title: `成功导入 ${res.imported} 个测试点${extraMsg}`,
      timer: 1800,
      showConfirmButton: false,
    })
  } catch (err: any) {
    Swal.fire('导入失败', err.response?.data?.detail || err?.message || '请重试', 'error')
  } finally {
    uploadingZip.value = false
  }
}

// ===== 子任务（捆绑测试）管理 =====
const subtaskConfig = ref<{ id: number; score: number; name?: string }[]>([])
const savingSubtasks = ref(false)

const totalSubtaskScore = computed(() => {
  return subtaskConfig.value.reduce((acc, st) => acc + (Number(st.score) || 0), 0)
})

const addSubtask = () => {
  const nextId = subtaskConfig.value.length > 0 ? Math.max(...subtaskConfig.value.map((s) => s.id)) + 1 : 1
  subtaskConfig.value.push({
    id: nextId,
    score: 0,
    name: `Subtask #${nextId}`,
  })
}

const removeSubtask = (stId: number) => {
  subtaskConfig.value = subtaskConfig.value.filter((s) => s.id !== stId)
}

const distributeScores = () => {
  const n = subtaskConfig.value.length
  if (n === 0) return
  const each = Math.floor(100 / n)
  subtaskConfig.value.forEach((st, idx) => {
    st.score = idx === n - 1 ? 100 - each * (n - 1) : each
  })
}

const saveSubtasks = async () => {
  if (editingId.value === null) return
  savingSubtasks.value = true
  try {
    const res = await testCasesApi.updateSubtasks(editingId.value, {
      subtask_config: subtaskConfig.value.map((s) => ({
        id: s.id,
        score: Number(s.score) || 0,
        name: s.name?.trim() || `Subtask #${s.id}`,
      })),
    })
    subtaskConfig.value = (res.subtask_config || []).map((s: any) => ({
      id: Number(s.id),
      score: Number(s.score) || 0,
      name: s.name || `Subtask #${s.id}`,
    }))
    Swal.fire({
      icon: 'success',
      title: '子任务配置已保存',
      timer: 1000,
      showConfirmButton: false,
    })
  } catch (err: any) {
    Swal.fire('保存失败', err.response?.data?.detail || '请重试', 'error')
  } finally {
    savingSubtasks.value = false
  }
}

const updateCaseSubtask = async (tc: TestCaseItem, event: Event) => {
  if (editingId.value === null) return
  const target = event.target as HTMLSelectElement
  const val = target.value ? Number(target.value) : null
  try {
    await testCasesApi.update(editingId.value, tc.id, { subtask_id: val })
    tc.subtask_id = val
  } catch (err: any) {
    Swal.fire('设置失败', err.response?.data?.detail || '请重试', 'error')
  }
}

const onBatchSelectSubtask = async (event: Event) => {
  const target = event.target as HTMLSelectElement
  const val = target.value
  target.value = ''
  if (!val || editingId.value === null || selectedCaseIds.value.length === 0) return
  const stId = val === 'none' ? null : Number(val)
  try {
    const map: Record<number, number | null> = {}
    for (const cid of selectedCaseIds.value) {
      map[cid] = stId
    }
    await testCasesApi.updateSubtasks(editingId.value, {
      subtask_config: subtaskConfig.value,
      case_subtasks: map,
    })
    testCases.value.forEach((tc) => {
      if (selectedCaseIds.value.includes(tc.id)) {
        tc.subtask_id = stId
      }
    })
    Swal.fire({
      icon: 'success',
      title: `已批量归属 ${selectedCaseIds.value.length} 个测试点`,
      timer: 1000,
      showConfirmButton: false,
    })
  } catch (err: any) {
    Swal.fire('批量设置失败', err.response?.data?.detail || '请重试', 'error')
  }
}

const clearCases = async () => {
  if (editingId.value === null) return
  const res = await Swal.fire({
    title: '确定清空所有测试点？',
    text: '此操作将彻底删除该题目的所有评测数据，不可恢复',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonText: '确定清空',
    cancelButtonText: '取消',
    confirmButtonColor: '#d33',
  })
  if (!res.isConfirmed) return
  clearingCases.value = true
  try {
    await testCasesApi.clearAll(editingId.value)
    testCases.value = []
    selectedCaseIds.value = []
    Swal.fire({
      icon: 'success',
      title: '已清空所有测试点',
      timer: 1200,
      showConfirmButton: false,
    })
    await loadTestCases()
  } catch (err: any) {
    Swal.fire('清空失败', err.response?.data?.detail || '请重试', 'error')
  } finally {
    clearingCases.value = false
  }
}

// ===== 投题审核资格查询 =====
const eligibility = ref<{
  can_bypass: boolean
  threshold: number
  stats: Record<
    string,
    { exact_count: number; ge_count: number; threshold: number; qualified: boolean }
  >
} | null>(null)

const loadEligibility = async () => {
  if (teamId.value) return
  try {
    const res = await problemsApi.getSubmitEligibility()
    eligibility.value = res
  } catch {
    eligibility.value = null
  }
}

const currentDifficultyEligibility = computed(() => {
  if (!eligibility.value) return null
  if (eligibility.value.can_bypass) return { qualified: true, bypass: true, ge_count: 0, threshold: 15 }
  const stat = eligibility.value.stats[form.difficulty]
  if (!stat) {
    const fallback = eligibility.value.stats['入门']
    return fallback ? { ...fallback, bypass: false } : null
  }
  return { ...stat, bypass: false }
})

// ===== 附件管理（单文件最大 16MB） =====
const attachments = ref<ProblemAttachment[]>([])
const attachInputRef = ref<HTMLInputElement | null>(null)
const uploadingAttach = ref(false)
const deletingAttachId = ref<number | null>(null)
const MAX_ATTACH_BYTES = 16 * 1024 * 1024
const FORBIDDEN_ATTACH_EXT = ['.exe', '.bat', '.cmd', '.sh', '.msi', '.dll', '.so', '.jar', '.apk', '.ps1']

const triggerAttachUpload = () => {
  if (editingId.value === null) {
    Swal.fire('请先保存题目', '题目创建完成后即可上传附件', 'info')
    return
  }
  attachInputRef.value?.click()
}

const uploadAttachmentFile = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || editingId.value === null) return

  const dot = file.name.lastIndexOf('.')
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : ''
  if (FORBIDDEN_ATTACH_EXT.includes(ext)) {
    Swal.fire('格式不支持', `不允许上传 ${ext} 类型的文件`, 'warning')
    return
  }
  if (file.size === 0) {
    Swal.fire('文件为空', '', 'warning')
    return
  }
  if (file.size > MAX_ATTACH_BYTES) {
    Swal.fire('文件过大', `单文件最大 16MB（当前 ${(file.size / (1024 * 1024)).toFixed(1)}MB）`, 'warning')
    return
  }

  uploadingAttach.value = true
  try {
    const res = await problemsApi.uploadAttachment(editingId.value, file)
    attachments.value.push(res.attachment)
    Swal.fire({
      icon: 'success',
      title: '已上传附件',
      timer: 1000,
      showConfirmButton: false,
    })
  } catch (err: any) {
    Swal.fire('上传失败', err.response?.data?.detail || '请重试', 'error')
  } finally {
    uploadingAttach.value = false
  }
}

// 附件下载必须带 Bearer token：后端只认 Authorization 头，
// 用 <a href> 直接导航会 401 → 拦截器清 token 跳登录页（静默登出）。
const downloadingAttachId = ref<number | null>(null)
const onDownloadAttachment = async (att: ProblemAttachment) => {
  if (!att.download_url || downloadingAttachId.value !== null) return
  downloadingAttachId.value = att.id
  try {
    await downloadAttachmentFile(att.download_url, att.orig_name)
  } catch (err: any) {
    Swal.fire('下载失败', err?.message || '请重试', 'error')
  } finally {
    downloadingAttachId.value = null
  }
}

const removeAttachment = async (att: ProblemAttachment) => {
  if (editingId.value === null) return
  const confirmRes = await Swal.fire({
    title: `确定删除附件「${att.orig_name}」？`,
    text: '此操作不可恢复',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonText: '确定删除',
    cancelButtonText: '取消',
    confirmButtonColor: '#d33',
  })
  if (!confirmRes.isConfirmed) return

  deletingAttachId.value = att.id
  try {
    await problemsApi.deleteAttachment(editingId.value, att.id)
    attachments.value = attachments.value.filter((a) => a.id !== att.id)
    Swal.fire({
      icon: 'success',
      title: '已删除附件',
      timer: 900,
      showConfirmButton: false,
    })
  } catch (err: any) {
    Swal.fire('删除失败', err.response?.data?.detail || '请重试', 'error')
  } finally {
    deletingAttachId.value = null
  }
}

// ===== 保存 =====
const saving = ref(false)
const save = async () => {
  if (!form.title.trim()) {
    Swal.fire('请填写题目名称', '', 'warning')
    return
  }
  if (form.is_spj && !form.spj_code.trim()) {
    Swal.fire('请填写 Special Judge 评测代码', '', 'warning')
    return
  }
  // 普通用户投递公开题：门槛校验（需通过 >= 15 道该难度及以上题目；团队题免除）
  if (!isTeamProblem.value && form.is_public && !canManage.value) {
    const elig = currentDifficultyEligibility.value
    if (elig && !elig.bypass && !elig.qualified) {
      Swal.fire({
        icon: 'warning',
        title: '做题量未达标',
        html: `公开「<strong>${form.difficulty}</strong>」题目需要先在主题库通过至少 <strong>${elig.threshold || 15}</strong> 道同难度题（当前已通过 <strong>${elig.ge_count ?? 0}</strong> 道）。<br/><br/>可以先存为草稿，刷够题后再来提交公开审核。`,
      })
      return
    }
  }
  const payload = {
    title: form.title.trim(),
    difficulty: form.difficulty,
    source: form.source.trim() || null,
    tags: form.tagsInput
      .split(/[,，]/)
      .map((t) => t.trim())
      .filter(Boolean),
    time_limit: Number(form.time_limit),
    memory_limit: Number(form.memory_limit),
    is_public: form.is_public,
    is_spj: form.is_spj,
    spj_language: form.is_spj ? form.spj_language : null,
    spj_code: form.is_spj ? form.spj_code : null,
    background: form.background,
    description: form.description,
    input_format: form.input_format,
    output_format: form.output_format,
    hint: form.hint,
    samples: samples.value.map((s) => ({ input: s.input, output: s.output })),
  }
  if (canManage.value) {
    (payload as Record<string, unknown>).allow_solution_submission = form.allow_solution_submission
  }
  saving.value = true
  try {
    if (editingId.value === null) {
      // 团队私有题模式：携带 team_id，编号自动分配 T 系列
      const body: Record<string, unknown> = teamId.value
        ? { ...payload, team_id: teamId.value }
        : { ...payload }
      const created = await problemsApi.create(body as never)
      const title = created.review_status === 'pending'
        ? '已提交，等待管理员审核'
        : (created.review_status === 'draft' ? '已保存为草稿' : '创建成功')
      await Swal.fire({ icon: 'success', title, timer: 1400, showConfirmButton: false })
      router.push(teamId.value ? `/teams/${teamId.value}` : `/problems/${created.id}`)
    } else {
      // 编辑模式：仅题目管理员可指派出题人（后端按用户名/UID 解析）
      const body: Record<string, unknown> = canManage.value
        ? { ...payload, author: form.author.trim() }
        : { ...payload }
      const updated = await problemsApi.update(editingId.value, body as never)
      const title = updated.review_status === 'pending'
        ? '已提交，等待管理员审核'
        : (updated.review_status === 'draft' ? '已保存为草稿' : '保存成功')
      await Swal.fire({ icon: 'success', title, timer: 1200, showConfirmButton: false })
      router.push(`/problems/${editingId.value}`)
    }
  } catch (err: any) {
    Swal.fire('保存失败', err.response?.data?.detail || '请重试', 'error')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadProblem()
  loadEligibility()
})
</script>

<template>
  <div class="problem-edit-page">
    <div class="problem-edit-container">
      <!-- 头部 -->
      <div class="card head-card">
        <div class="head-row">
          <h2 class="page-title">
            {{ editingId === null ? (isTeamProblem ? '创建团队题目' : '新建题目') : (isTeamProblem ? `编辑团队题目 ${editingNumber || ''}` : `编辑 ${editingNumber || ''}`) }}
          </h2>
          <div class="head-actions">
            <button type="button" class="btn-ghost" :disabled="importingZip" @click="triggerZipProblemImport">
              <i class="fa-solid" :class="importingZip ? 'fa-spinner fa-spin' : 'fa-file-zipper'"></i>
              {{ importingZip ? '正在导入 ZIP...' : 'ZIP 导入' }}
            </button>
            <button type="button" class="btn-ghost" @click="triggerMdImport">
              <i class="fa-solid fa-file-import"></i> 导入 MD
            </button>
            <button type="button" class="btn-ghost" @click="exportMdFile">
              <i class="fa-solid fa-file-export"></i> 导出 MD
            </button>
            <button v-if="editingId !== null" class="btn-ghost" @click="router.push(`/problems/${editingId}`)">查看题目</button>
            <button class="btn-primary" :disabled="saving" @click="save">
              {{ saving ? '保存中...' : '保存' }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="loading" class="empty">加载中...</div>

      <template v-else>
        <!-- 题目设置 -->
        <div class="card">
          <div class="section-title">题目设置</div>
          <!-- 审核状态提示 -->
          <div
            v-if="editingId !== null && reviewStatus === 'rejected'"
            class="review-alert review-alert--reject"
          >
            <i class="fa-solid fa-circle-exclamation"></i>
            <div>
              <strong>该题已被管理员驳回。</strong>
              <span v-if="reviewReason">驳回原因：{{ reviewReason }}</span>
              <span v-else>请按管理员要求修改后重新选择「公开（提交审核）」保存。</span>
            </div>
          </div>
          <div
            v-else-if="editingId !== null && reviewStatus === 'pending'"
            class="review-alert review-alert--pending"
          >
            <i class="fa-solid fa-hourglass-half"></i>
            <div>
              <strong>该题正在等待管理员审核。</strong>
              <span>修改并保存后会重新提交审核；选择「隐藏」可撤回为草稿。</span>
            </div>
          </div>
          <div class="form-grid">
            <label class="form-item span-2">
              <span class="form-label">题目名称 *</span>
              <input v-model="form.title" class="form-input" placeholder="例如：A+B Problem" />
            </label>
            <label class="form-item">
              <span class="form-label">难度</span>
              <select v-model="form.difficulty" class="form-input">
                <option v-for="d in DIFFICULTY_LIST" :key="d" :value="d">{{ d }}</option>
              </select>
            </label>
            <label class="form-item">
              <span class="form-label">来源</span>
              <input v-model="form.source" class="form-input" placeholder="例如：NOIP / 洛谷 / 自拟" />
            </label>
            <label class="form-item span-2">
              <span class="form-label">算法标签（逗号分隔，最多 10 个）</span>
              <input v-model="form.tagsInput" class="form-input" placeholder="例如：模拟, 前缀和, 动态规划" />
            </label>
            <label class="form-item">
              <span class="form-label">时间限制 (ms)</span>
              <input v-model.number="form.time_limit" type="number" class="form-input" min="100" max="60000" />
            </label>
            <label class="form-item">
              <span class="form-label">内存限制 (MB)</span>
              <input v-model.number="form.memory_limit" type="number" class="form-input" min="16" max="1024" />
            </label>
            <label v-if="editingId !== null && canManage" class="form-item">
              <span class="form-label">出题人</span>
              <input v-model="form.author" class="form-input" maxlength="50" placeholder="用户名或 UID，留空清除" />
            </label>
            <label class="form-item">
              <span class="form-label">题目状态</span>
              <select v-model="form.is_public" class="form-input">
                <template v-if="isTeamProblem">
                  <option :value="false">团队内部题（私有，仅本团队成员可见）</option>
                  <option :value="true">团队公开题（公开，可在公开比赛中供全站参赛者查看与提交）</option>
                </template>
                <template v-else>
                  <option :value="false">隐藏（草稿，仅自己和管理员可见）</option>
                  <option v-if="canManage" :value="true">公开（立即发布到题库）</option>
                  <option v-else :value="true">公开（提交后等待管理员审核）</option>
                </template>
              </select>
            </label>
            <label class="form-item">
              <span class="form-label">评测模式</span>
              <select v-model="form.is_spj" class="form-input">
                <option :value="false">普通文本比对</option>
                <option :value="true">Special Judge (特判)</option>
              </select>
            </label>
            <label v-if="canManage" class="form-item">
              <span class="form-label">题解提交通道</span>
              <select v-model="form.allow_solution_submission" class="form-input">
                <option :value="true">开启（允许提交题解）</option>
                <option :value="false">关闭（禁止提交题解）</option>
              </select>
            </label>
          </div>

          <!-- 投题资格提示（仅主题库普通出题人展示） -->
          <div
            v-if="!isTeamProblem && !canManage && currentDifficultyEligibility && !currentDifficultyEligibility.bypass"
            class="eligibility-banner"
            :class="currentDifficultyEligibility.qualified ? 'eligibility-banner--ok' : 'eligibility-banner--warn'"
          >
            <i :class="currentDifficultyEligibility.qualified ? 'fa-solid fa-circle-check' : 'fa-solid fa-triangle-exclamation'"></i>
            <div class="eligibility-banner__content">
              <div class="eligibility-banner__title">
                主题库「{{ form.difficulty }}」及以上做题进度：<strong>{{ currentDifficultyEligibility.ge_count }}</strong> / <strong>{{ currentDifficultyEligibility.threshold }}</strong>
              </div>
              <div class="eligibility-banner__desc">
                <template v-if="currentDifficultyEligibility.qualified">
                  ✅ 已满足要求，保存为「公开」即可提交审核。
                </template>
                <template v-else>
                  刷题量还没达标，可以先存为草稿，达标后再来公开。
                </template>
              </div>
            </div>
          </div>

          <div v-if="form.is_spj" class="spj-panel">
            <div class="spj-header">
              <div class="spj-title">Special Judge 评测程序</div>
              <div class="spj-lang-group">
                <span class="spj-lang-label">语言：</span>
                <select v-model="form.spj_language" class="form-input spj-lang-select">
                  <option value="cpp">C++ (支持 testlib.h)</option>
                  <option value="python3">Python 3</option>
                </select>
              </div>
            </div>
            <div class="spj-hint">
              运行参数：<code>argv[1]</code> 为输入文件 (<code>in.txt</code>)，<code>argv[2]</code> 为选手输出 (<code>out.txt</code>)，<code>argv[3]</code> 为标准答案 (<code>ans.txt</code>)。退出码 0 为 AC，非 0 为 WA。
            </div>
            <CodeEditor v-model="form.spj_code" :language="spjEditorLang" height="280px" />
          </div>
        </div>

        <!-- 题面设置 -->
        <div class="card" @dragover.prevent @drop.prevent="handleFileDrop">
          <div class="section-title-row">
            <div class="section-title">题面设置</div>
            <div class="section-actions">
              <button type="button" class="btn-ghost btn-sm" @click="triggerMdImport">
                <i class="fa-solid fa-file-import"></i> 导入 MD 文件
              </button>
              <button type="button" class="btn-ghost btn-sm" @click="exportMdFile">
                <i class="fa-solid fa-file-export"></i> 导出 MD
              </button>
            </div>
          </div>

          <div v-for="s in SECTIONS" :key="s.key" class="md-section">
            <div class="md-label">{{ s.label }}</div>
            <div class="md-editor">
              <MarkdownSplitEditor
                v-model="form[s.key]"
                height="220px"
                :placeholder="s.placeholder"
                :preview="false"
              />
              <div class="md-preview">
                <div class="prose preview-body" v-html="previewOf(s.key)"></div>
              </div>
            </div>
          </div>

          <!-- 样例组 -->
          <div class="md-section">
            <div class="md-label">样例</div>
            <div v-for="(s, i) in samples" :key="i" class="sample-group">
              <div class="sample-head">
                <span class="sample-name">样例组 #{{ i + 1 }}</span>
                <span class="action-link red" @click="removeSample(i)">删除此组</span>
              </div>
              <div class="sample-grid">
                <textarea v-model="s.input" class="md-textarea plain" rows="4" placeholder="样例输入"></textarea>
                <textarea v-model="s.output" class="md-textarea plain" rows="4" placeholder="样例输出"></textarea>
              </div>
            </div>
            <button class="btn-ghost add-sample" @click="addSample"><i class="fa-solid fa-plus"></i> 添加样例组</button>
          </div>
        </div>

        <!-- 附件 -->
        <div class="card">
          <div class="section-title-row">
            <div class="section-title">附件</div>
            <div class="section-actions">
              <button type="button" class="btn-ghost btn-sm" :disabled="uploadingAttach" @click="triggerAttachUpload">
                <i class="fa-solid" :class="uploadingAttach ? 'fa-spinner fa-spin' : 'fa-paperclip'"></i>
                {{ uploadingAttach ? '上传中...' : '上传附件' }}
              </button>
            </div>
          </div>
          <p class="attach-tip">单文件最大 16MB，禁止上传 .exe / .bat / .sh 等可执行文件。题目创建后即可上传。</p>
          <div v-if="attachments.length" class="attach-list">
            <div v-for="a in attachments" :key="a.id" class="attach-item">
              <i class="fa-solid fa-paperclip"></i>
              <span class="attach-name">{{ a.orig_name }}</span>
              <span class="attach-size">{{ formatBytes(a.size_bytes) }}</span>
              <button
                type="button"
                class="attach-dl"
                :title="downloadingAttachId === a.id ? '下载中...' : '下载'"
                :disabled="!a.download_url || downloadingAttachId !== null"
                @click="onDownloadAttachment(a)"
              >
                <i
                  class="fa-solid"
                  :class="downloadingAttachId === a.id ? 'fa-download fa-spin' : 'fa-download'"
                ></i>
              </button>
              <button
                type="button"
                class="btn-case-delete"
                :disabled="deletingAttachId === a.id"
                @click="removeAttachment(a)"
              >
                <i class="fa-solid" :class="deletingAttachId === a.id ? 'fa-spinner fa-spin' : 'fa-trash-can'"></i>
                {{ deletingAttachId === a.id ? '删除中...' : '删除' }}
              </button>
            </div>
          </div>
          <div v-else class="tc-empty">暂无附件</div>
          <input
            ref="attachInputRef"
            type="file"
            style="display: none"
            @change="uploadAttachmentFile"
          />
        </div>

        <!-- 测试数据（评测用） -->
        <div class="card">
          <div class="section-title">测试数据</div>
          <template v-if="editingId !== null">
            <p class="tc-tip">
              评测用测试点：提交的代码将逐点运行并与期望输出比对（忽略行尾空白）。至少添加 1 个测试点，否则该题无法提交评测。支持上传 ZIP 压缩包批量导入（.in/.out 或 .in/.ans 成对）。
            </p>
            <div class="tc-file-actions">
              <button class="btn-ghost add-sample" :disabled="uploadingZip" @click="zipInputRef?.click()">
                <i class="fa-solid fa-file-zipper"></i> {{ uploadingZip ? '正在导入 ZIP...' : '上传 ZIP 导入测试点' }}
              </button>
              <button
                class="btn-danger"
                :disabled="clearingCases"
                @click="clearCases"
              >
                <i class="fa-solid" :class="clearingCases ? 'fa-spinner fa-spin' : 'fa-trash-can'"></i>
                {{ clearingCases ? '正在清空...' : '清空全部测试点' }}
              </button>
              <button
                v-if="selectedCaseIds.length > 0"
                class="btn-danger"
                :disabled="batchDeleting"
                @click="batchDeleteCases"
              >
                <i class="fa-solid" :class="batchDeleting ? 'fa-spinner fa-spin' : 'fa-trash'"></i>
                {{ batchDeleting ? '正在删除...' : `批量删除 (${selectedCaseIds.length} 个)` }}
              </button>
              <button
                class="btn-ghost add-sample"
                :disabled="loadingCases"
                @click="loadTestCases"
              >
                <i class="fa-solid" :class="loadingCases ? 'fa-spinner fa-spin' : 'fa-rotate-right'"></i> 刷新
              </button>
            </div>
            <input
              ref="zipInputRef"
              type="file"
              accept=".zip"
              style="display: none"
              @change="uploadZip"
            />

            <!-- 子任务（捆绑测试）配置面板 -->
            <div class="subtask-config-box">
              <div class="subtask-box-header">
                <div class="subtask-box-title">
                  <i class="fa-solid fa-layer-group"></i> 子任务（捆绑测试）配置
                  <span v-if="subtaskConfig.length > 0" class="subtask-count-tag">共 {{ subtaskConfig.length }} 个子任务</span>
                </div>
                <div class="subtask-box-actions">
                  <button type="button" class="btn-subtask-action" @click="addSubtask">
                    <i class="fa-solid fa-plus"></i> 添加子任务
                  </button>
                  <button type="button" class="btn-subtask-action" :disabled="subtaskConfig.length === 0" @click="distributeScores">
                    <i class="fa-solid fa-scale-balanced"></i> 均分 100 分
                  </button>
                  <button type="button" class="btn-subtask-save" :disabled="savingSubtasks" @click="saveSubtasks">
                    <i class="fa-solid" :class="savingSubtasks ? 'fa-spinner fa-spin' : 'fa-check'"></i>
                    {{ savingSubtasks ? '保存中...' : '保存子任务配置' }}
                  </button>
                </div>
              </div>

              <div class="subtask-tip">
                开启子任务后，评测将按组捆绑打分：组内全部测试点通过方可获得该组分值。若某点发生超时（TLE），将自动跳过同组剩余测试点并继续评测后续子任务。
              </div>

              <div v-if="subtaskConfig.length > 0" class="subtask-table-wrap">
                <div class="subtask-table-header">
                  <span class="col-id">序号</span>
                  <span class="col-name">子任务名称</span>
                  <span class="col-score">分值 (pts)</span>
                  <span class="col-cases">包含测试点</span>
                  <span class="col-action">操作</span>
                </div>
                <div v-for="st in subtaskConfig" :key="st.id" class="subtask-table-row">
                  <span class="col-id">#{{ st.id }}</span>
                  <div class="col-name">
                    <input
                      v-model="st.name"
                      type="text"
                      class="subtask-name-input"
                      :placeholder="`Subtask #${st.id}`"
                    />
                  </div>
                  <div class="col-score">
                    <input
                      v-model.number="st.score"
                      type="number"
                      min="0"
                      max="100"
                      class="subtask-score-input"
                    />
                  </div>
                  <span class="col-cases">
                    {{ testCases.filter((tc) => tc.subtask_id === st.id).length }} 个点
                  </span>
                  <div class="col-action">
                    <button type="button" class="btn-subtask-del" title="删除子任务" @click="removeSubtask(st.id)">
                      <i class="fa-solid fa-trash-can"></i>
                    </button>
                  </div>
                </div>
                <div class="subtask-total-bar">
                  <span>总分值合计：</span>
                  <strong :class="totalSubtaskScore === 100 ? 'score-valid' : 'score-warn'">
                    {{ totalSubtaskScore }} / 100 分
                  </strong>
                  <span v-if="totalSubtaskScore !== 100" class="score-warn-tip">
                    （提示：建议分值总和为 100 分）
                  </span>
                </div>
              </div>
              <div v-else class="subtask-none-tip">
                当前未配置子任务（所有测试点将作为传统模式评测，满分 100 分）。点击上方「添加子任务」或上传包含子任务目录（如 subtask1/、1/）的 ZIP 包即可自动启用。
              </div>
            </div>

            <!-- 全选栏与批量归属 -->
            <div v-if="testCases.length > 0" class="tc-selection-bar">
              <label class="tc-select-all">
                <input
                  type="checkbox"
                  :checked="allSelected"
                  @change="toggleSelectAll"
                />
                <span>全选所有测试点 (共 {{ testCases.length }} 个)</span>
              </label>
              <div class="tc-selection-right">
                <span v-if="selectedCaseIds.length > 0" class="tc-selected-hint">
                  已选中 {{ selectedCaseIds.length }} 个测试点
                </span>
                <div v-if="selectedCaseIds.length > 0 && subtaskConfig.length > 0" class="tc-batch-subtask">
                  <select @change="onBatchSelectSubtask" class="tc-subtask-select">
                    <option value="">批量划分子任务...</option>
                    <option value="none">移出子任务 (无)</option>
                    <option v-for="st in subtaskConfig" :key="st.id" :value="st.id">
                      归入 {{ st.name || ('Subtask #' + st.id) }} ({{ st.score }}分)
                    </option>
                  </select>
                </div>
              </div>
            </div>

            <div v-if="loadingCases" class="tc-loading">
              <i class="fa-solid fa-spinner fa-spin"></i> 正在加载测试点...
            </div>

            <template v-else>
              <div v-for="(tc, i) in testCases" :key="tc.id" class="sample-group tc-card">
                <div class="sample-head">
                  <div class="tc-head-left">
                    <input
                      type="checkbox"
                      :value="tc.id"
                      v-model="selectedCaseIds"
                      class="tc-checkbox"
                    />
                    <span class="sample-name">测试点 #{{ i + 1 }}</span>
                    <span v-if="tc.input_size !== undefined || tc.expected_output_size !== undefined" class="tc-size-info">
                      输入: {{ formatBytes(tc.input_size) }} / 期望输出: {{ formatBytes(tc.expected_output_size) }}
                    </span>
                    <div v-if="subtaskConfig.length > 0" class="tc-subtask-badge-box">
                      <label class="tc-subtask-label">子任务：</label>
                      <select
                        :value="tc.subtask_id ?? ''"
                        @change="updateCaseSubtask(tc, $event)"
                        class="tc-subtask-select"
                      >
                        <option value="">独立评测 (无子任务)</option>
                        <option v-for="st in subtaskConfig" :key="st.id" :value="st.id">
                          {{ st.name || ('Subtask #' + st.id) }} ({{ st.score }}分)
                        </option>
                      </select>
                    </div>
                  </div>
                  <button
                    class="btn-case-delete"
                    :disabled="deletingCaseId === tc.id"
                    @click="removeCase(tc.id, i + 1)"
                  >
                    <i class="fa-solid" :class="deletingCaseId === tc.id ? 'fa-spinner fa-spin' : 'fa-trash-can'"></i>
                    {{ deletingCaseId === tc.id ? '删除中...' : '删除' }}
                  </button>
                </div>
                <div class="sample-grid">
                  <textarea class="md-textarea plain" rows="3" readonly :value="formatPreview(tc.input_data)" placeholder="输入"></textarea>
                  <textarea class="md-textarea plain" rows="3" readonly :value="formatPreview(tc.expected_output)" placeholder="期望输出"></textarea>
                </div>
              </div>
              <div v-if="testCases.length === 0" class="tc-empty">
                暂无测试点（提交代码将无法通过评测，请点击上方“上传 ZIP”或在下方新增）
              </div>
            </template>

            <div class="tc-add">
              <div class="tc-label">新增测试点</div>
              <div class="sample-grid">
                <textarea v-model="newCase.input_data" class="md-textarea plain" rows="3" placeholder="测试点输入"></textarea>
                <textarea v-model="newCase.expected_output" class="md-textarea plain" rows="3" placeholder="期望输出"></textarea>
              </div>
              <div class="tc-file-actions">
                <button class="btn-ghost add-sample" @click="inputFileInputRef?.click()">
                  <i class="fa-solid fa-file-import"></i> 导入输入文件
                </button>
                <button class="btn-ghost add-sample" @click="outputFileInputRef?.click()">
                  <i class="fa-solid fa-file-import"></i> 导入输出文件
                </button>
              </div>
              <input
                ref="inputFileInputRef"
                type="file"
                accept=".txt,.in,.out,.ans,.data,.log,text/plain"
                style="display: none"
                @change="importCaseInputFile"
              />
              <input
                ref="outputFileInputRef"
                type="file"
                accept=".txt,.in,.out,.ans,.data,.log,text/plain"
                style="display: none"
                @change="importCaseOutputFile"
              />
              <button class="btn-ghost add-sample" @click="addCase"><i class="fa-solid fa-plus"></i> 添加测试点</button>
            </div>
          </template>
          <p v-else class="tc-tip">题目创建后即可在这里添加评测测试点。</p>
        </div>

        <div class="save-row">
          <button class="btn-primary big" :disabled="saving" @click="save">
            {{ saving ? '保存中...' : '保存' }}
          </button>
        </div>
      </template>

      <!-- 隐藏的 Markdown 题面文件导入 input -->
      <input
        ref="mdFileInputRef"
        type="file"
        accept=".md,.markdown,.txt"
        style="display: none"
        @change="importMdFile"
      />
      <!-- 隐藏的 ZIP 题目包导入 input -->
      <input
        ref="zipProblemInputRef"
        type="file"
        accept=".zip"
        style="display: none"
        @change="handleZipProblemImport"
      />
    </div>
  </div>
</template>

<style scoped>
.problem-edit-page {
  min-height: 100vh;
  line-height: 1.5;
}

.problem-edit-container {
  max-width: 1100px;
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
  margin-bottom: 16px;
}

.head-card {
  padding: 16px 24px;
}

.head-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.page-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--text-strong);
  margin: 0;
}

.head-actions {
  display: flex;
  gap: 10px;
}

.btn-primary {
  padding: 8px 26px;
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: 22px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.btn-primary:hover:not(:disabled) {
  background: var(--primary-hover);
}

.btn-primary.big {
  padding: 11px 46px;
  font-size: 14px;
}

.btn-primary:disabled {
  opacity: 0.6;
}

.btn-ghost {
  padding: 8px 20px;
  border: 1px solid #e2e8f0;
  background: var(--surface-plain);
  border-radius: 22px;
  font-size: 13px;
  color: var(--text-sub);
  cursor: pointer;
}

.btn-ghost:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.btn-danger {
  padding: 8px 20px;
  border: 1px solid var(--primary);
  background: var(--surface-plain);
  border-radius: 22px;
  font-size: 13px;
  color: var(--primary);
  cursor: pointer;
}

.btn-danger:hover {
  background: var(--primary);
  color: #fff;
}

.section-title {
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--text-strong);
  border-left: 4px solid var(--primary);
  padding-left: 10px;
  margin-bottom: 16px;
}

.section-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
}

.section-title-row .section-title {
  margin-bottom: 0;
}

.section-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.btn-ghost.btn-sm {
  padding: 6px 14px;
  font-size: 12px;
}

/* 审核状态横幅 */
.review-alert {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 13px;
  line-height: 1.6;
}

.review-alert i {
  margin-top: 3px;
}

.review-alert--reject {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
color: var(--danger-text);
  border: 1px solid #fbc4c4;
}

.review-alert--pending {
  background: color-mix(in srgb, var(--warning) 12%, transparent);
color: var(--warning-text);
  border: 1px solid #ffe2a8;
}

.review-alert span {
  display: block;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 4px 16px;
}

.form-item {
  display: block;
  margin-bottom: 12px;
}

.span-2 {
  grid-column: span 2;
}

.form-label {
  display: block;
  font-size: 13px;
  color: var(--text-sub);
  margin-bottom: 4px;
}

.form-input {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 13px;
  color: var(--text-strong);
  outline: none;
  background: var(--surface-plain);
}

.form-input:focus {
  border-color: var(--primary);
}

/* 分节编辑器 */
.md-section {
  margin-bottom: 22px;
}

.md-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-sub);
  margin-bottom: 6px;
}

.md-editor {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.md-textarea {
  width: 100%;
  height: 100%;
  min-height: 120px;
  box-sizing: border-box;
  padding: 10px 12px;
  border: none;
  outline: none;
  resize: vertical;
  font-size: 13px;
  font-family: ui-monospace, Consolas, monospace;
  color: var(--text-strong);
  background: var(--surface-plain);
}

.md-textarea.plain {
  border-radius: 0;
  background: var(--surface-plain);
}

.md-preview {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: var(--surface-plain);
  padding: 10px 14px;
  min-height: 120px;
  max-height: 480px;
  overflow-y: auto;
}

/* 预览代码块交给 assets/markdown.css 的 .prose 统一方案，
   与题面最终展示（ProblemDetail）保持同一套样式 */

/* 样例组 */
.sample-group {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 12px;
  margin-bottom: 10px;
}

.sample-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.sample-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-strong);
}

.sample-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.add-sample {
  border-radius: 8px;
}

.tc-tip {
  color: var(--text-sub);
  font-size: 12px;
  margin-bottom: 12px;
}

.tc-empty {
  color: #b6c2cf;
  font-size: 13px;
  padding: 8px 0 12px;
}

.tc-add {
  margin-top: 4px;
}

.tc-label {
  font-size: 13px;
  color: var(--text-sub);
  margin-bottom: 6px;
}

.tc-file-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 8px;
  margin-bottom: 8px;
}

.action-link.red {
  color: #ef4444;
  cursor: pointer;
  font-size: 12px;
}

.action-link.red:hover {
  text-decoration: underline;
}

.btn-danger {
  padding: 8px 18px;
  border: 1px solid #fecaca;
  background: color-mix(in srgb, var(--danger) 10%, transparent);
color: var(--danger-text);
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s;
}

.btn-danger:hover:not(:disabled) {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border-color: #fca5a5;
color: var(--danger-text);
}

.btn-danger:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.tc-selection-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: var(--surface-plain);
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  margin-bottom: 12px;
  font-size: 13px;
  color: var(--text-sub);
}

.tc-selection-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.tc-select-all {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-weight: 500;
}

.tc-selected-hint {
  color: #ef4444;
  font-weight: 600;
}

.tc-head-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.tc-checkbox {
  width: 16px;
  height: 16px;
  cursor: pointer;
  accent-color: var(--primary);
}

.tc-size-info {
  font-size: 12px;
  color: var(--text-sub);
  font-weight: 400;
}

.tc-subtask-badge-box {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: 6px;
}

.tc-subtask-label {
  font-size: 12px;
  color: var(--text-sub);
  font-weight: 500;
}

.tc-subtask-select {
  padding: 3px 8px;
  font-size: 12px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background-color: var(--surface-plain);
  color: var(--text-strong);
  cursor: pointer;
  outline: none;
  transition: border-color 0.15s;
}

.tc-subtask-select:focus {
  border-color: var(--primary);
}

/* 子任务配置面板样式 */
.subtask-config-box {
  margin-bottom: 18px;
  padding: 16px;
  background: var(--surface-plain);
  border: 1px solid #e2e8f0;
  border-radius: 10px;
}

.subtask-box-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 8px;
}

.subtask-box-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-strong);
  display: flex;
  align-items: center;
  gap: 8px;
}

.subtask-count-tag {
  font-size: 12px;
  font-weight: normal;
  padding: 2px 8px;
  background: #e2e8f0;
  color: var(--text-sub);
  border-radius: 12px;
}

.subtask-box-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-subtask-action {
  padding: 5px 10px;
  background: var(--surface-plain);
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 12px;
  color: var(--text-sub);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: all 0.15s;
}

.btn-subtask-action:hover:not(:disabled) {
  background: var(--bg-subtle);
  border-color: #94a3b8;
  color: var(--text-strong);
}

.btn-subtask-action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-subtask-save {
  padding: 5px 12px;
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  transition: opacity 0.15s;
}

.btn-subtask-save:hover:not(:disabled) {
  opacity: 0.9;
}

.btn-subtask-save:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.subtask-tip {
  font-size: 12px;
  color: var(--text-sub);
  line-height: 1.5;
  margin-bottom: 12px;
}

.subtask-table-wrap {
  background: var(--surface-plain);
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
}

.subtask-table-header {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  background: var(--bg-subtle);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-sub);
  border-bottom: 1px solid #e2e8f0;
}

.subtask-table-row {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  font-size: 13px;
  border-bottom: 1px solid #f1f5f9;
}

.subtask-table-row:last-child {
  border-bottom: none;
}

.col-id {
  width: 50px;
  font-weight: 600;
  color: var(--text-sub);
}

.col-name {
  flex: 1;
  padding-right: 12px;
}

.col-score {
  width: 120px;
  padding-right: 12px;
}

.col-cases {
  width: 90px;
  font-size: 12px;
  color: var(--text-sub);
}

.col-action {
  width: 50px;
  text-align: right;
}

.subtask-name-input {
  width: 100%;
  padding: 4px 8px;
  font-size: 13px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  outline: none;
  background: var(--surface-plain);
}

.subtask-name-input:focus {
  border-color: var(--primary);
}

.subtask-score-input {
  width: 80px;
  padding: 4px 8px;
  font-size: 13px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  outline: none;
  background: var(--surface-plain);
}

.subtask-score-input:focus {
  border-color: var(--primary);
}

.btn-subtask-del {
  background: none;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  font-size: 13px;
  padding: 4px 6px;
  border-radius: 4px;
  transition: all 0.15s;
}

.btn-subtask-del:hover {
  color: #ef4444;
  background: color-mix(in srgb, var(--danger) 10%, transparent);
}

.subtask-total-bar {
  display: flex;
  align-items: center;
  padding: 10px 14px;
  background: var(--surface-plain);
  border-top: 1px solid #e2e8f0;
  font-size: 13px;
  color: var(--text-strong);
}

.score-valid {
color: light-dark(#10b981, #34d399);
  font-size: 14px;
  margin-left: 4px;
}

.score-warn {
  color: #f59e0b;
  font-size: 14px;
  margin-left: 4px;
}

.score-warn-tip {
  font-size: 12px;
color: light-dark(#d97706, #fbbf24);
  margin-left: 8px;
}

.subtask-none-tip {
  font-size: 12px;
  color: #94a3b8;
  padding: 10px 12px;
  background: var(--surface-plain);
  border: 1px dashed #cbd5e1;
  border-radius: 6px;
  line-height: 1.5;
}

.btn-case-delete {
  padding: 4px 10px;
  border: 1px solid #fecaca;
  background: var(--surface-plain);
  color: #ef4444;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: all 0.15s;
}

.btn-case-delete:hover:not(:disabled) {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border-color: #f87171;
}

.btn-case-delete:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.tc-loading {
  text-align: center;
  padding: 24px 0;
  color: var(--text-sub);
  font-size: 13px;
}

.tc-card {
  transition: border-color 0.2s;
}

.tc-card:hover {
  border-color: #cbd5e1;
}

.save-row {
  text-align: center;
  padding: 4px 0 20px;
}

.attach-tip {
  color: var(--text-sub);
  font-size: 12px;
  margin-bottom: 12px;
}

.attach-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.attach-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: var(--surface-plain);
  font-size: 13px;
  color: var(--text-strong);
}

.attach-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
}

.attach-size {
  font-size: 12px;
  color: var(--text-sub);
}

.attach-dl {
  color: var(--primary);
  text-decoration: none;
  background: none;
  border: none;
  cursor: pointer;
  padding: 0 2px;
  font-size: inherit;
}

.attach-dl:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.empty {
  text-align: center;
  padding: 60px 20px;
  color: var(--text-sub);
  background: var(--surface-plain);
  border-radius: 16px;
}

@media (max-width: 760px) {
  .md-editor,
  .sample-grid,
  .form-grid {
    grid-template-columns: 1fr;
  }

  .span-2 {
    grid-column: span 1;
  }
}

.spj-panel {
  margin-top: 16px;
  padding: 16px;
  background: var(--surface-plain);
  border: 1px solid #e2e8f0;
  border-radius: var(--radius-sm);
}

.spj-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.spj-title {
  font-weight: 600;
  color: var(--text-strong);
  font-size: 14px;
}

.spj-lang-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.spj-lang-label {
  font-size: 13px;
  color: var(--text-sub);
}

.spj-lang-select {
  padding: 4px 8px;
  font-size: 13px;
  width: auto;
}

.spj-hint {
  font-size: 12px;
  color: var(--text-sub);
  margin-bottom: 12px;
  line-height: 1.4;
}

.spj-hint code {
  background: var(--bg-subtle);
  padding: 2px 4px;
  border-radius: 3px;
  color: var(--text-sub);
}

.eligibility-banner {
  margin-top: 14px;
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 13px;
  line-height: 1.5;
}

.eligibility-banner i {
  font-size: 16px;
  margin-top: 2px;
}

.eligibility-banner--ok {
  background: color-mix(in srgb, var(--success) 10%, transparent);
  border: 1px solid #b7eb8f;
color: var(--success-text);
}

.eligibility-banner--ok .eligibility-banner__title {
color: light-dark(#135200, #34d399);
  font-weight: 600;
}

.eligibility-banner--ok .eligibility-banner__desc {
color: light-dark(#389e0d, #34d399);
  font-size: 12px;
}

.eligibility-banner--warn {
  background: color-mix(in srgb, var(--warning) 12%, transparent);
  border: 1px solid #ffe58f;
color: var(--warning-text);
}

.eligibility-banner--warn .eligibility-banner__title {
color: light-dark(#873800, #fbbf24);
  font-weight: 600;
}

.eligibility-banner--warn .eligibility-banner__desc {
color: light-dark(#d46b08, #fbbf24);
  font-size: 12px;
}
</style>

