<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { problemsApi } from '@/api/problems'
import { contestsApi, type ContestItem } from '@/api/contests'
import { teamsApi } from '@/api/teams'
import Swal from 'sweetalert2'
import { renderRichText } from '@/utils/markdown'
import { difficultyColor } from '@/utils/difficulty'
import { useDifficultyReveal } from '@/utils/academicMode'
import { fillSampleToTest } from '@/utils/testDraft'
import { userNameColor } from '@/utils/userColor'
import { copyText } from '@/utils/codeCopy'
import { problemReviewMeta } from '@/utils/problemReview'
import { formatBytes } from '@/utils/format'
import { downloadAttachmentFile } from '@/utils/attachment'
import type { Problem } from '@/types'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

// 学术模式：难度默认隐藏，点一下只看这道题（刷新即恢复隐藏）
const { isDifficultyVisible, revealDifficulty } = useDifficultyReveal()

// 严格只认题目管理权限
const canManage = computed(() => !!authStore.currentUser?.can_manage_problems)
// 可编辑：题目管理员，或主题库题的作者本人（团队题仍只走管理员/团队管理）
const canEdit = computed(() => {
  if (canManage.value) return true
  const p = problem.value
  if (!p || !authStore.currentUser || !p.author) return false
  const isTeamProblem = String(p.problem_number || '').startsWith('T')
  return !isTeamProblem && p.author.user_id === authStore.currentUser.id
})
// 可迁移：题管，或题目作者本人（与后端一致——团队题还要团队管理权，
// 团队管理员身份前端拿不到，交给后端按团队/比赛逐项校验并给出明确提示）
const canMigrate = computed(() => {
  if (canManage.value) return true
  const p = problem.value
  if (!p || !authStore.currentUser || !p.author) return false
  return p.author.user_id === authStore.currentUser.id
})

// ==================== 题目迁移（主题库 / 团队题 / 比赛赛题互搬） ====================
const showMigrateModal = ref(false)
const migrating = ref(false)
const migrateError = ref('')
const migrateOptionsLoading = ref(false)
// 选项加载成功后置真，重复打开弹窗直接复用，不再全量重拉比赛列表
const migrateOptionsLoaded = ref(false)
const myTeams = ref<{ id: number; name: string; is_owner: boolean }[]>([])
const contestOptions = ref<{ id: number; title: string }[]>([])
const migrateForm = ref({
  target: 'library' as 'library' | 'team' | 'contest',
  team_id: null as number | null,
  contest_id: null as number | null,
  keep_in_library: false,
})

/** 拉下拉选项：可管理的团队 + 比赛（避免手填 ID 填错搬到别人的归属里） */
/** 拉比赛全量（ID + 标题）：先取首页拿 total，再并发补齐剩余页 */
const loadAllContests = async (): Promise<ContestItem[]> => {
  const first = await contestsApi.list(0)
  const all: ContestItem[] = [...(first.items || [])]
  const total = first.total || all.length
  const pageSize = (first.items || []).length || 50
  const restPages = Math.min(Math.ceil((total - all.length) / pageSize), 19)
  if (restPages > 0) {
    const rest = await Promise.all(
      Array.from({ length: restPages }, (_, i) => contestsApi.list(i + 1))
    )
    for (const res of rest) all.push(...(res.items || []))
  }
  return all
}

const loadMigrateOptions = async () => {
  const hasCache = migrateOptionsLoaded.value
  // 有缓存时不遮罩、不清空：先展示旧选项，后台静默刷新，
  // 这样新建的团队/比赛下次打开弹窗就能看到（不会因为"缓存过"永远不更新）
  if (!hasCache) migrateOptionsLoading.value = true
  migrateError.value = ''
  try {
    const [teamsRes, contestList] = await Promise.all([
      teamsApi.myManageable(),
      // 比赛分页拉全：只取第一页会让靠后的比赛在下拉里选不到
      loadAllContests(),
    ])
    myTeams.value = teamsRes.items || []
    contestOptions.value = contestList.map((c: ContestItem) => ({ id: c.id, title: c.title }))
    migrateOptionsLoaded.value = true
  } catch (err: any) {
    // 有缓存时刷新失败不打扰用户（沿用旧选项）；无缓存才真正提示
    if (!hasCache) migrateError.value = `加载可选团队/比赛失败：${err?.message || err}`
  } finally {
    migrateOptionsLoading.value = false
  }
}

const openMigrateModal = async () => {
  migrateForm.value = { target: 'library', team_id: null, contest_id: null, keep_in_library: false }
  migrateError.value = ''
  showMigrateModal.value = true
  await loadMigrateOptions()
}

const submitMigrate = async () => {
  const f = migrateForm.value
  migrateError.value = ''
  if (f.target === 'team' && !f.team_id) {
    migrateError.value = '请选择目标团队'
    return
  }
  if (f.target === 'contest' && !f.contest_id) {
    migrateError.value = '请选择目标比赛'
    return
  }

  // 迁移会改变题号（P/U/T 之间切换），指向旧题号的链接会失效，必须二次确认
  const targetLabel = f.target === 'library'
    ? '主题库'
    : f.target === 'team'
      ? `${myTeams.value.find(t => t.id === f.team_id)?.name || '所选团队'}（团队题）`
      : `${contestOptions.value.find(c => c.id === f.contest_id)?.title || '所选比赛'}（比赛赛题）`
  const confirmRes = await Swal.fire({
    title: '确认迁移这道题？',
    // 用 text 而不是 html：团队名/比赛标题是用户可控内容，拼进 html 会构成存储型 XSS
    text: `题目将搬到「${targetLabel}」，题号会随之变化，指向旧题号的链接将失效。`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonText: '确认迁移',
    cancelButtonText: '取消',
    confirmButtonColor: 'var(--primary)',
    cancelButtonColor: '#909399',
  })
  if (!confirmRes.isConfirmed) return

  migrating.value = true
  try {
    const res = await problemsApi.migrate(problem.value!.id, {
      target: f.target,
      team_id: f.target === 'team' && f.team_id ? Number(f.team_id) : undefined,
      contest_id: f.target === 'contest' && f.contest_id ? Number(f.contest_id) : undefined,
      keep_in_library: f.keep_in_library,
    })
    showMigrateModal.value = false
    await loadProblem()
    Swal.fire({
      icon: 'success',
      title: '迁移成功',
      text: `${res.moved_from} → ${res.problem_number}`,
      timer: 1800,
      showConfirmButton: false,
    })
  } catch (err: any) {
    migrateError.value = err.response?.data?.detail || err.message || '迁移失败'
  } finally {
    migrating.value = false
  }
}

const problem = ref<Problem | null>(null)
const loading = ref(true)
const error = ref('')

const problemId = computed(() => parseInt(route.params.id as string, 10))
// 统一题号入口：/problem/P1001、U1001 或 T10（团队私有题）
const problemCode = computed(() => (route.params.code as string || '').toUpperCase())

// ==================== 比赛上下文 ====================
// 从比赛页点题目进来时 URL 上带着 ?contest=N，**这个参数必须一路传到提交页**：
// 后端靠它把提交归到某场比赛，丢了就不会计分（排行榜会全员 0 分）。
// 曾经这个页面既不读、也不往下传，导致从比赛里提交永远不计成绩。
const contestId = computed(() => {
  const v = parseInt(route.query.contest as string, 10)
  return Number.isFinite(v) && v > 0 ? v : null
})

// 仅用于展示横幅；取不到（未报名 / 已删除等）就静默不显示，不影响做题
const contest = ref<ContestItem | null>(null)

const loadContest = async () => {
  if (contestId.value === null) {
    contest.value = null
    return
  }
  try {
    contest.value = await contestsApi.get(contestId.value)
  } catch {
    contest.value = null
  }
}

// 提交页靠 ?contest= 判断是否计分，这里提前把状态说清楚
// （比赛未开始/已结束时后端会直接拒收，不如先提醒）
const contestHint = computed(() => {
  const c = contest.value
  if (!c) return ''
  const rule = c.rule_type === 'oi' ? 'OI 赛制' : c.rule_type === 'ioi' ? 'IOI 赛制' : 'XCPC 赛制'
  if (c.status === 'running') return `比赛进行中（${rule}）· 本次提交将计入比赛成绩`
  if (c.status === 'pending') return '比赛尚未开始，现在提交不计成绩'
  return '比赛已结束，提交不计成绩'
})

// 把整个 query 原样带过去（不只 contest，以后加新上下文参数也不不用再改这里）
// ==================== 样例 → 沉浸做题 ====================
/** 样例一键带进沉浸页：写入共享草稿（含期望输出，运行后自动给出 AC/WA 对比）再跳转 */
const fillToImmersive = (s: { input: string; output: string }) => {
  if (!problem.value) return
  fillSampleToTest(problem.value.id, s.input, s.output)
  openImmersive()
}

const openSubmit = () => {
  if (!problem.value) return
  router.push({ path: `/problems/${problem.value.id}/submit`, query: route.query })
}

const openImmersive = () => {
  if (!problem.value) return
  router.push({ path: `/problems/${problem.value.id}/immersive`, query: route.query })
}

const openSolutions = () => {
  if (!problem.value) return
  const code = problem.value.problem_number || (problem.value.team_id ? `T${problem.value.t_no || problem.value.id}` : `P${1000 + problem.value.id}`)
  router.push({ path: `/problem/${code}/solutions`, query: route.query })
}

// ---- otk 拉题命令（otk-remote 协议：otk fetch <地址> <题号>）----
const siteOrigin = window.location.origin
const problemNumberForCmd = computed(() => {
  const p = problem.value
  if (!p) return ''
  return p.problem_number || (p.team_id ? `T${p.t_no || p.id}` : `P${1000 + p.id}`)
})
const otkCopied = ref(false)
const copyOtkFetch = async () => {
  if (!problemNumberForCmd.value) return
  const ok = await copyText(`otk fetch ${siteOrigin} ${problemNumberForCmd.value}`)
  if (ok) {
    otkCopied.value = true
    setTimeout(() => { otkCopied.value = false }, 1500)
  }
}

const loadProblemByCode = async (code: string) => {
  try {
    loading.value = true
    error.value = ''
    problem.value = await problemsApi.getByCode(code)
    document.title = `${problem.value.title} - NLNOJ`
  } catch (err: any) {
    error.value = err.response?.data?.detail || err.message || '加载失败'
    problem.value = null
    document.title = '题目详情 - NLNOJ'
  } finally {
    loading.value = false
  }
}

const descriptionHtml = computed(() =>
  problem.value ? renderRichText(problem.value.description) : ''
)
const backgroundHtml = computed(() =>
  problem.value ? renderRichText(problem.value.background || '') : ''
)
const inputFormatHtml = computed(() =>
  problem.value ? renderRichText(problem.value.input_format || '') : ''
)
const outputFormatHtml = computed(() =>
  problem.value ? renderRichText(problem.value.output_format || '') : ''
)
const hintHtml = computed(() =>
  problem.value ? renderRichText(problem.value.hint || '') : ''
)

// 有任一扩展分节时，描述也加上「题目描述」小节标题（洛谷习惯）
const hasSections = computed(() => {
  const p = problem.value
  if (!p) return false
  return !!(p.background || p.input_format || p.output_format || p.hint || (p.samples && p.samples.length))
})

const loadProblem = async () => {
  if (!Number.isFinite(problemId.value)) return
  try {
    loading.value = true
    error.value = ''
    problem.value = await problemsApi.get(problemId.value)
    document.title = `${problem.value.title} - NLNOJ`
  } catch (err: any) {
    error.value = err.response?.data?.detail || err.message || '加载失败'
    problem.value = null
    document.title = '题目详情 - NLNOJ'
  } finally {
    loading.value = false
  }
}

watch(problemId, loadProblem)
watch(problemCode, (code) => { if (code) loadProblemByCode(code) })
watch(contestId, loadContest)
watch(() => problem.value?.title, (title) => {
  if (title) document.title = `${title} - NLNOJ`
})
onMounted(() => {
  if (problemCode.value) loadProblemByCode(problemCode.value)
  else loadProblem()
  loadContest()
})

// 附件必须带 Bearer token 下载：后端只认 Authorization 头，
// 直接用 <a href> 导航会 401 → 拦截器清 token 跳登录页。
const downloadingAttachId = ref<number | null>(null)
const onDownloadAttachment = async (a: { id: number; download_url: string | null; orig_name: string }) => {
  if (!a.download_url || downloadingAttachId.value !== null) return
  downloadingAttachId.value = a.id
  try {
    await downloadAttachmentFile(a.download_url, a.orig_name)
  } catch (e) {
    // 失败提示交由全局拦截器处理（401 会自动走刷新/登出流程）
    console.error('附件下载失败', e)
  } finally {
    downloadingAttachId.value = null
  }
}
</script>

<template>
  <div class="problem-detail-page">
    <div class="problem-detail-container">
      <div v-if="loading" class="empty">加载中...</div>
      <div v-else-if="error" class="empty">
        {{ error }}
        <div class="empty-actions">
          <button class="btn-back" @click="router.push('/problems')">返回题库</button>
        </div>
      </div>

      <template v-else-if="problem">
        <!-- 比赛模式横幅：提醒当前提交会计入哪场比赛（以前这个状态完全不可见） -->
        <div
          v-if="contest"
          class="contest-banner"
          :class="{ 'is-warn': contest.status !== 'running' }"
        >
          <i class="fa-solid fa-trophy" />
          <span>比赛模式</span>
          <router-link :to="`/contest/${contest.id}`" class="cb-link">{{ contest.title }}</router-link>
          <span class="cb-text">{{ contestHint }}</span>
        </div>

        <div class="problem-detail-layout">
        <div class="problem-detail-main">
        <div class="card">
          <!-- 题头 -->
          <div class="p-head">
            <span class="p-number">{{ problem.problem_number }}</span>
            <h1 class="p-title">{{ problem.title }}</h1>
            <span
              v-if="isDifficultyVisible(problem.id)"
              class="diff-badge"
              :style="{ background: difficultyColor(problem.difficulty) }"
            >{{ problem.difficulty }}</span>
            <button
              v-else
              type="button"
              class="diff-reveal-btn"
              title="学术模式：难度默认隐藏，点一下只看这道题"
              @click="revealDifficulty(problem.id)"
            >显示难度</button>
            <span v-if="problem.is_spj" class="spj-badge">Special Judge</span>
            <span
              v-if="problem.review_status && problem.review_status !== 'approved'"
              class="review-badge"
              :style="{
                background: problemReviewMeta(problem.review_status).bg,
                color: problemReviewMeta(problem.review_status).color,
              }"
            >{{ problem.is_public ? problemReviewMeta(problem.review_status).text : '草稿' }}</span>
            <span v-if="canEdit || canMigrate" class="head-ops">
              <button v-if="canEdit" class="btn-op" @click="router.push(`/problems/${problem.id}/edit`)">编辑</button>
              <button v-if="canMigrate" class="btn-op" title="把题目在主题库 / 团队题 / 比赛赛题之间搬迁" @click="openMigrateModal">迁移</button>
            </span>
          </div>

          <!-- 驳回原因（仅作者与管理员可见该页时） -->
          <div
            v-if="problem.review_status === 'rejected' && problem.review_reason"
            class="review-reason-box"
          >
            <i class="fa-solid fa-circle-exclamation"></i>
            <span>驳回原因：{{ problem.review_reason }}</span>
          </div>

          <!-- 限制与统计 -->
          <div class="p-limits">
            <span>时间限制：<b>{{ problem.time_limit }} ms</b></span>
            <span>内存限制：<b>{{ problem.memory_limit }} MB</b></span>
            <span v-if="problem.source">来源：<b>{{ problem.source }}</b></span>
            <span v-if="problem.author">
              出题人：<router-link
                :to="`/user/${problem.author.user_number}`"
                class="author-link"
                :style="{ color: userNameColor(problem.author) }"
              >{{ problem.author.username }}</router-link>
            </span>
            <span>提交：<b>{{ problem.submit_count }}</b></span>
            <span>通过：<b>{{ problem.solved_count }}</b></span>
            <span>通过率：<b>{{ problem.pass_rate === null ? '暂无' : problem.pass_rate + '%' }}</b></span>
          </div>

          <!-- 标签 -->
          <div v-if="problem.tags && problem.tags.length" class="p-tags">
            <RouterLink
              v-for="t in problem.tags"
              :key="t"
              class="tag-badge"
              :to="{ path: '/problems', query: { tag: t } }"
            >{{ t }}</RouterLink>
          </div>
        </div>

        <!-- 题面 -->
        <div class="card">
          <template v-if="hasSections">
            <template v-if="problem.background">
              <div class="section-head">题目背景</div>
              <div class="prose p-body" v-html="backgroundHtml"></div>
            </template>
            <template v-if="problem.description">
              <div class="section-head">题目描述</div>
              <div class="prose p-body" v-html="descriptionHtml"></div>
            </template>
            <template v-if="problem.input_format">
              <div class="section-head">输入格式</div>
              <div class="prose p-body" v-html="inputFormatHtml"></div>
            </template>
            <template v-if="problem.output_format">
              <div class="section-head">输出格式</div>
              <div class="prose p-body" v-html="outputFormatHtml"></div>
            </template>
            <template v-if="problem.samples && problem.samples.length">
              <div class="section-head">样例</div>
              <div v-for="(s, i) in problem.samples" :key="i" class="sample-block">
                <div class="sample-title">
                  样例 #{{ i + 1 }}
                  <button
                    type="button"
                    class="fill-test-btn"
                    title="带样例进入沉浸做题页，运行后自动与样例输出对比"
                    @click="fillToImmersive(s)"
                  >
                    <i class="fa-solid fa-arrow-right-to-bracket"></i> 带入沉浸页
                  </button>
                </div>
                <div class="sample-io">
                  <div class="io-box">
                    <div class="io-label">
                      <span>输入</span>
                      <button type="button" class="code-copy code-copy-light" data-copy>
                        <i class="fa-solid fa-copy" /><span data-copy-label>复制</span>
                      </button>
                    </div>
                    <pre>{{ s.input }}</pre>
                  </div>
                  <div class="io-box">
                    <div class="io-label">
                      <span>输出</span>
                      <button type="button" class="code-copy code-copy-light" data-copy>
                        <i class="fa-solid fa-copy" /><span data-copy-label>复制</span>
                      </button>
                    </div>
                    <pre>{{ s.output }}</pre>
                  </div>
                </div>
              </div>
            </template>
            <template v-if="problem.hint">
              <div class="section-head">提示说明</div>
              <div class="prose p-body" v-html="hintHtml"></div>
            </template>
          </template>
          <div v-else class="prose p-body" v-html="descriptionHtml"></div>
        </div>

        <!-- 附件 -->
        <div v-if="problem.attachments && problem.attachments.length" class="card">
          <div class="section-head">附件</div>
          <div class="attach-list">
            <div
              v-for="a in problem.attachments"
              :key="a.id"
              class="attach-item"
              role="button"
              tabindex="0"
              :aria-disabled="!a.download_url || downloadingAttachId !== null"
              @click="onDownloadAttachment(a)"
              @keydown.enter.prevent="onDownloadAttachment(a)"
              @keydown.space.prevent="onDownloadAttachment(a)"
            >
              <i class="fa-solid fa-paperclip"></i>
              <span class="attach-name">{{ a.orig_name }}</span>
              <span class="attach-size">{{ formatBytes(a.size_bytes) }}</span>
              <i
                class="fa-solid attach-dl"
                :class="downloadingAttachId === a.id ? 'fa-download fa-spin' : 'fa-download'"
              ></i>
            </div>
          </div>
        </div>

        </div>

        <!-- 右栏：操作卡 -->
        <aside class="problem-actions-card">
          <div class="actions-card-title">题目操作</div>
          <button class="action-button action-primary" @click="openSubmit">
            <i class="fa-solid fa-code"></i> 提交代码
          </button>
          <button class="action-button" title="全屏专注：左题面右编辑器，就地评测不跳转" @click="openImmersive">
            <i class="fa-solid fa-expand"></i> 沉浸做题
          </button>
          <button class="action-button action-solution" @click="openSolutions">
            <i class="fa-solid fa-lightbulb"></i> 查看题解
          </button>
          <button class="action-button" @click="router.push({ path: '/submissions', query: { problem_id: problem.id, ...(contestId ? { contest: String(contestId) } : {}) } })">
            <i class="fa-solid fa-list"></i> 提交记录
          </button>
          <button class="action-button" @click="router.push('/problems')">
            <i class="fa-solid fa-arrow-left"></i> 返回题库
          </button>
          <button v-if="contestId" class="action-button action-contest" @click="router.push(`/contest/${contestId}`)">
            <i class="fa-solid fa-trophy"></i> 返回比赛
          </button>
          <div class="otk-fetch" title="otk：OierToolKit 命令行工具，一条命令把题目拉到本地（otk fetch 后可用 otk submit 本地提交）">
            <div class="otk-fetch-head">
              <i class="fa-solid fa-terminal"></i> otk 拉题
            </div>
            <button class="otk-fetch-cmd" @click="copyOtkFetch">
              <code>otk fetch {{ siteOrigin }} {{ problemNumberForCmd }}</code>
              <i :class="otkCopied ? 'fa-solid fa-check' : 'fa-regular fa-copy'"></i>
            </button>
          </div>
        </aside>
        </div>
      </template>
    </div>

    <!-- 迁移题目弹窗 -->
    <div v-if="showMigrateModal" class="migrate-backdrop" @click.self="showMigrateModal = false">
      <div class="migrate-card">
        <div class="migrate-head">
          <h3>迁移题目</h3>
          <button class="btn-op" @click="showMigrateModal = false">关闭</button>
        </div>
        <div class="migrate-body">
          <p class="migrate-tip">
            迁移是「搬家」不是复制：题目编号会随归属变化（主题库 P / 未公开 U / 团队题 T），
            提交记录与题解都跟着这道理走。
          </p>
          <label class="migrate-label">目标归属</label>
          <select v-model="migrateForm.target" class="migrate-input">
            <option value="library">主题库（正式公开）</option>
            <option value="team">团队题（不公开，需团队管理权）</option>
            <option value="contest">比赛赛题（需比赛管理权）</option>
          </select>

          <template v-if="migrateForm.target === 'team'">
            <label class="migrate-label">目标团队</label>
            <select
              v-model.number="migrateForm.team_id"
              class="migrate-input"
              :disabled="migrateOptionsLoading"
            >
              <option :value="null">请选择团队</option>
              <option v-for="t in myTeams" :key="t.id" :value="t.id">{{ t.name }}（ID {{ t.id }}）</option>
            </select>
            <p v-if="!migrateOptionsLoading && myTeams.length === 0" class="migrate-hint">
              没有你可管理的团队（需要是团主或团队管理员）
            </p>
          </template>

          <template v-if="migrateForm.target === 'contest'">
            <label class="migrate-label">目标比赛</label>
            <select
              v-model.number="migrateForm.contest_id"
              class="migrate-input"
              :disabled="migrateOptionsLoading"
            >
              <option :value="null">请选择比赛</option>
              <option v-for="c in contestOptions" :key="c.id" :value="c.id">{{ c.title }}（ID {{ c.id }}）</option>
            </select>
            <p v-if="!migrateOptionsLoading && contestOptions.length === 0" class="migrate-hint">
              暂无可选的比赛
            </p>
            <label class="migrate-check">
              <input v-model="migrateForm.keep_in_library" type="checkbox">
              同时保留在主题库（不勾选则从主题库撤下，成为比赛独占题）
            </label>
          </template>

          <div v-if="migrateError" class="migrate-error">{{ migrateError }}</div>
        </div>
        <div class="migrate-foot">
          <button class="btn-op" @click="showMigrateModal = false">取消</button>
          <button class="btn-op primary" :disabled="migrating" @click="submitMigrate">
            {{ migrating ? '迁移中...' : '确认迁移' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ===== 迁移题目弹窗 ===== */
.migrate-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, .45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
}

.migrate-card {
  width: min(460px, 92vw);
  background: var(--surface);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: 18px 20px;
}

.migrate-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.migrate-head h3 {
  margin: 0;
  font-size: 16px;
  color: var(--text-strong);
}

.migrate-tip {
  font-size: 12px;
  color: var(--text-sub);
  line-height: 1.6;
  margin: 0 0 12px;
}

.migrate-label {
  display: block;
  font-size: 13px;
  color: var(--text-sub);
  margin: 10px 0 4px;
}

.migrate-input {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-subtle);
  color: var(--text-strong);
  font-size: 14px;
}

.migrate-check {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-sub);
}

.migrate-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--warning-text);
}

.migrate-error {
  margin-top: 10px;
  font-size: 13px;
  color: var(--danger-text);
}

.migrate-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}

.problem-detail-page {
  min-height: 100vh;
  line-height: 1.5;
}

.problem-detail-container {
  max-width: 1280px;
  margin: 0 auto;
}

.problem-detail-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 210px;
  align-items: start;
  gap: 18px;
}

/* 右栏「查看题解」入口按钮 */
.action-button.action-solution {
  background: color-mix(in srgb, #f59e0b 10%, transparent);
  border-color: #fde68a;
  color: #b45309;
}

.action-button.action-solution:hover {
  background: color-mix(in srgb, #f59e0b 18%, transparent);
  border-color: #f59e0b;
  color: #92400e;
}

.problem-detail-main {
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

/* otk 拉题命令：操作卡底部的可复制命令条（otk-remote 协议拉题入口） */
.otk-fetch {
  margin-top: 4px;
  padding: 9px 10px;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-md);
  background: var(--surface-strong);
}

.otk-fetch-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  color: var(--text-sub);
  font-size: 11.5px;
  font-weight: 700;
}

.otk-fetch-cmd {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 6px;
  width: 100%;
  padding: 0;
  border: 0;
  background: none;
  color: var(--primary);
  text-align: left;
  cursor: pointer;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  line-height: 1.55;
}

.otk-fetch-cmd code {
  word-break: break-all;
}

.otk-fetch-cmd:hover {
  text-decoration: underline;
}

.otk-fetch-cmd i {
  flex-shrink: 0;
  margin-top: 2px;
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
  justify-content: flex-start;
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

.action-button:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.action-button.action-primary {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
}

.action-button.action-primary:hover {
  background: var(--primary-hover);
  color: #fff;
}

.action-button.action-contest {
  border-color: #e6a23c;
  background: color-mix(in srgb, var(--warning) 12%, transparent);
color: var(--warning-text);
}

.action-button.action-contest:hover {
  background: color-mix(in srgb, var(--warning) 12%, transparent);
  border-color: #d99018;
color: var(--warning-text);
}

.card {
  background: var(--surface);
  -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: 24px 28px;
  margin-bottom: 16px;
}

/* ===== 比赛模式横幅 ===== */
.contest-banner {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  background: color-mix(in srgb, var(--primary) 8%, transparent);
  border: 1px solid #cfe3ff;
  border-radius: 12px;
  padding: 10px 16px;
  margin-bottom: 16px;
  font-size: 13px;
color: var(--primary-text);
}

.contest-banner i {
  color: var(--primary);
}

/* 比赛未开始 / 已结束时换成暖色，和「会计分」区分开 */
.contest-banner.is-warn {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border-color: #f6d5cd;
color: var(--danger-text);
}

.contest-banner.is-warn i {
  color: #c0392b;
}

.cb-link {
  color: var(--primary);
  font-weight: 700;
  text-decoration: none;
}

.cb-link:hover {
  text-decoration: underline;
}

.is-warn .cb-link {
  color: #a1432f;
}

.cb-text {
  color: #7b8aa0;
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
  font-size: 1.1rem;
}

.p-title {
  font-size: 1.35rem;
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
  white-space: nowrap;
}

.draft-badge {
  padding: 2px 10px;
  border-radius: 4px;
  background: var(--bg-subtle);
  color: var(--text-sub);
  font-size: 12px;
}

/* 审核状态徽章 */
.review-badge {
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 12px;
  white-space: nowrap;
}

/* 驳回原因横幅 */
.review-reason-box {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  padding: 8px 12px;
  border-radius: 6px;
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border: 1px solid #fbc4c4;
color: var(--danger-text);
  font-size: 13px;
}

.spj-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  background: #722ed1;
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.head-ops {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

.btn-op {
  padding: 6px 18px;
  border: 1px solid #e2e8f0;
  background: var(--surface-plain);
  border-radius: 18px;
  font-size: 12px;
  color: var(--text-sub);
  cursor: pointer;
}

.btn-op:hover {
  border-color: #3498db;
  color: #3498db;
}

.btn-op.danger {
  color: var(--primary);
  border-color: #f5b7b1;
}

.btn-op.danger:hover {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}

.p-limits {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid #f0f2f5;
  color: var(--text-sub);
  font-size: 13px;
}

.p-actions {
  display: flex;
  gap: 10px;
  margin-top: 14px;
}

.btn-primary {
  padding: 9px 28px;
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: 22px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.btn-primary:hover {
  background: var(--primary-hover);
}

.author-link {
  font-weight: 700;
  text-decoration: none;
}
.author-link:hover { text-decoration: underline; }

.p-limits b {
  color: var(--text-strong);
}

.p-tags {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 20px;
  background: var(--bg-subtle);
  color: var(--text-sub);
  font-size: 12px;
  text-decoration: none;
}

.tag-badge:hover {
  background: #e2e8f0;
}

.p-body {
  color: var(--text-strong);
}

.section-head {
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--text-strong);
  border-bottom: 1px solid #edf2f7;
  padding-bottom: 8px;
  margin-bottom: 12px;
}

.sample-block {
  margin-bottom: 16px;
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
  padding: 10px 14px;
  border: var(--border-width) solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-subtle);
  color: var(--text-strong);
  text-decoration: none;
  transition: border-color .15s, background .15s;
}

.attach-item:hover {
  border-color: var(--primary);
  background: color-mix(in srgb, var(--primary) 6%, transparent);
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
}

.sample-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-sub);
  margin-bottom: 6px;
}

.fill-test-btn {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border: 1px solid #bbf7d0;
  border-radius: 999px;
  background: color-mix(in srgb, var(--success) 10%, transparent);
color: var(--success-text);
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.fill-test-btn:hover {
  background: color-mix(in srgb, var(--success) 10%, transparent);
}

.sample-io {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.io-box {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  overflow: hidden;
}

.io-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  background: var(--surface-plain);
  color: var(--text-sub);
  font-size: 12px;
  padding: 4px 8px 4px 12px;
  border-bottom: 1px solid #edf2f7;
}

.io-box pre {
  margin: 0;
  padding: 10px 12px;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--text-strong);
  min-height: 42px;
}

@media (max-width: 600px) {
  .sample-io {
    grid-template-columns: 1fr;
  }
}

.back-row {
  text-align: center;
  padding: 4px 0 12px;
}

.btn-back {
  padding: 8px 24px;
  border: 1px solid #e2e8f0;
  background: var(--surface-plain);
  border-radius: 22px;
  font-size: 13px;
  color: var(--text-sub);
  cursor: pointer;
}

.btn-back:hover {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}

.empty {
  text-align: center;
  padding: 60px 20px;
  color: var(--text-sub);
  background: var(--surface-plain);
  border-radius: 16px;
}

.empty-actions {
  margin-top: 16px;
}

/* ===== 手机端：.card 原本 24px 28px，是全站最大的卡片内边距 ===== */
@media (max-width: 600px) {
  .card {
    padding: 16px 14px;
  }
}

@media (max-width: 900px) {
  .problem-detail-layout {
    grid-template-columns: minmax(0, 1fr) 190px;
    gap: 12px;
  }

  .problem-detail-layout.is-testing {
    grid-template-columns: minmax(0, 1fr) 460px;
  }
}

@media (max-width: 700px) {
  .problem-detail-layout {
    grid-template-columns: 1fr;
  }

  /* 单栏后 aside 会落回 DOM 末尾沉底，order 提到题面上方 */
  .problem-actions-card {
    order: -1;
    position: static;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .actions-card-title {
    grid-column: 1 / -1;
  }

  .otk-fetch {
    grid-column: 1 / -1;
  }
}
</style>

