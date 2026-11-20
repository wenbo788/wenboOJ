<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { contestsApi } from '@/api/contests'
import { teamsApi, type TeamProblemItem } from '@/api/teams'
import { problemsApi } from '@/api/problems'
import { userNameColor } from '@/utils/userColor'
import MarkdownSplitEditor from '@/components/MarkdownSplitEditor.vue'
import { canManageProblems } from '@/utils/permissions'

const router = useRouter()
const authStore = useAuthStore()
const me = computed(() => authStore.currentUser)

const canManageSite = computed(() => {
  const u = me.value
  return canManageProblems(u)
})

// 举办方：个人（站方赛）或我所管理的团队（团队赛）
const myTeams = ref<{ id: number; name: string; is_owner: boolean }[]>([])
const ownerKind = ref<'personal' | 'team'>('personal')
const teamId = ref<number | null>(null)
// 公开程度：站方赛 = 公开赛/邀请赛；团队赛 = 团队公开赛/团队内部赛/团队邀请赛
const visibility = ref<'public' | 'private' | 'team' | 'team_private' | 'team_public'>('public')
const inviteCode = ref('')
// 赛制：xcpc / oi / ioi
const ruleType = ref<'xcpc' | 'oi' | 'ioi'>('xcpc')
// 管理员防偷窥/参赛保护：默认开启
const hideSubmissionsFromAdmin = ref(true)
// 组队赛模式
const isTeamContest = ref(false)
const maxTeamMembers = ref(3)

// 快速新建团队状态
const showQuickTeam = ref(false)
const newTeamName = ref('')
const creatingTeam = ref(false)
const quickTeamError = ref('')

const setOwnerKind = (kind: 'personal' | 'team') => {
  ownerKind.value = kind
  if (kind === 'personal') {
    visibility.value = 'public'
    teamId.value = null
  } else {
    visibility.value = 'team_public'
    if (myTeams.value.length > 0 && !teamId.value) {
      teamId.value = myTeams.value[0].id
    }
  }
}

const quickCreateTeam = async () => {
  const name = newTeamName.value.trim()
  if (!name) {
    quickTeamError.value = '请输入团队名称'
    return
  }
  creatingTeam.value = true
  quickTeamError.value = ''
  try {
    const created = await teamsApi.create({ name })
    myTeams.value.unshift({ id: created.id, name: created.name, is_owner: true })
    ownerKind.value = 'team'
    teamId.value = created.id
    visibility.value = 'team_public'
    newTeamName.value = ''
    showQuickTeam.value = false
  } catch (err: any) {
    quickTeamError.value = err.response?.data?.detail || err.message || '团队创建失败'
  } finally {
    creatingTeam.value = false
  }
}

const loadMyTeams = async () => {
  try {
    const data = await teamsApi.myManageable()
    myTeams.value = data.items
    if (!canManageSite.value) {
      ownerKind.value = 'team'
      visibility.value = 'team_public'
      if (data.items.length > 0) {
        teamId.value = data.items[0].id
      }
    } else {
      if (ownerKind.value === 'team' && data.items.length > 0 && !teamId.value) {
        teamId.value = data.items[0].id
      }
    }
  } catch {
    myTeams.value = []
  }
}

const form = ref({ title: '', description: '', start_date: '', start_time: '', end_date: '', end_time: '' })
const createError = ref('')
const creating = ref(false)

// 比赛题目：直接输入题号（P1001 / U1001 / T10），按添加顺序作为 A/B/C/D…
const picked = ref<{ code: string; title: string }[]>([])
const codeInput = ref('')
const addingCode = ref(false)

const hostTeamProblems = ref<(TeamProblemItem & { is_public?: boolean })[]>([])
const loadingTeamProblems = ref(false)

const loadHostTeamProblems = async () => {
  if (ownerKind.value !== 'team' || !teamId.value) {
    hostTeamProblems.value = []
    return
  }
  loadingTeamProblems.value = true
  try {
    const list = await teamsApi.problems(teamId.value)
    hostTeamProblems.value = list
  } catch {
    hostTeamProblems.value = []
  } finally {
    loadingTeamProblems.value = false
  }
}

watch([ownerKind, teamId], () => {
  loadHostTeamProblems()
})

const addTeamProblemToPicked = (p: TeamProblemItem) => {
  if (picked.value.some(x => x.code === p.problem_number)) return
  picked.value.push({ code: p.problem_number, title: p.title })
}

const canSubmit = computed(() =>
  form.value.title.trim() && form.value.start_date && form.value.start_time
  && form.value.end_date && form.value.end_time && picked.value.length > 0
)

const addProblem = async () => {
  const code = codeInput.value.trim().toUpperCase()
  if (!code) return
  if (picked.value.some(p => p.code === code)) {
    createError.value = `题目 ${code} 已添加`
    return
  }
  addingCode.value = true
  createError.value = ''
  try {
    const p = await problemsApi.getByCode(code)
    picked.value.push({ code, title: p.title })
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

// 默认时间：今天 19:00 ~ 明天 21:00（东八区语义按浏览器本地时间）
const pad = (n: number) => String(n).padStart(2, '0')
const now = new Date()
form.value.start_date = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
form.value.start_time = '19:00'
const tomorrow = new Date(now.getTime() + 86400000)
form.value.end_date = `${tomorrow.getFullYear()}-${pad(tomorrow.getMonth() + 1)}-${pad(tomorrow.getDate())}`
form.value.end_time = '21:00'

const doCreate = async () => {
  if (!form.value.title.trim()) { createError.value = '请输入比赛名称'; return }
  if (ownerKind.value === 'team' && !teamId.value) {
    createError.value = '请选择或新建一个举办团队'
    return
  }
  if (!form.value.start_date || !form.value.start_time || !form.value.end_date || !form.value.end_time) {
    createError.value = '请选择完整的起止时间'
    return
  }
  const needCode = visibility.value === 'private' || visibility.value === 'team_private'
  if (needCode && inviteCode.value.trim().length < 3) {
    createError.value = '邀请赛需设置 3-32 位邀请码'
    return
  }
  creating.value = true
  createError.value = ''
  try {
    const created = await contestsApi.create({
      title: form.value.title.trim(),
      description: form.value.description.trim() || undefined,
      start_time: new Date(`${form.value.start_date}T${form.value.start_time}`).toISOString(),
      end_time: new Date(`${form.value.end_date}T${form.value.end_time}`).toISOString(),
      problem_codes: picked.value.map(p => p.code),
      visibility: visibility.value,
      team_id: ownerKind.value === 'team' ? (teamId.value != null ? Number(teamId.value) : undefined) : undefined,
      invite_code: needCode ? inviteCode.value.trim() : undefined,
      rule_type: ruleType.value,
      hide_submissions_from_admin: hideSubmissionsFromAdmin.value,
      is_team_contest: isTeamContest.value,
      max_team_members: isTeamContest.value ? Number(maxTeamMembers.value) : undefined,
    })
    router.push(`/contest/${created.id}`)
  } catch (err: any) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') {
      createError.value = detail
    } else if (Array.isArray(detail)) {
      createError.value = detail.map((e: any) => e.msg || e.detail || JSON.stringify(e)).join('；')
    } else if (detail && typeof detail === 'object') {
      createError.value = detail.msg || detail.message || JSON.stringify(detail)
    } else {
      createError.value = err.message || '创建失败'
    }
  } finally {
    creating.value = false
  }
}

onMounted(async () => {
  // 题目通过题号即时校验添加，无需预拉题库
  await loadMyTeams()
})
</script>

<template>
  <div class="contest-create-page">
    <div class="contest-create-container">
      <div class="back-link">
        <a @click.prevent="router.push('/contests')" href="#">← 返回比赛列表</a>
      </div>

      <div class="card form-card">
        <div class="form-row">
          <span class="row-label">比赛名称</span>
          <div class="row-value">
            <input v-model="form.title" class="form-input w-title" maxlength="100" placeholder="例如：NLNOJ 月赛 #1" />
          </div>
        </div>

        <div class="form-row">
          <span class="row-label">举办者</span>
          <div class="row-value">
            <span class="owner-name" :style="{ color: userNameColor(me) }">{{ me?.username }}</span>
            <span class="owner-check"><i class="fa-solid fa-circle-check"></i></span>
          </div>
        </div>

        <div class="form-row">
          <span class="row-label">举办形式</span>
          <div class="row-value kind-selector">
            <label class="kind-option" :class="{ active: ownerKind === 'personal', disabled: !canManageSite }">
              <input
                type="radio"
                name="ownerKind"
                value="personal"
                :checked="ownerKind === 'personal'"
                :disabled="!canManageSite"
                @change="setOwnerKind('personal')"
              />
              <span class="kind-text">个人举办（站方赛）</span>
              <span v-if="!canManageSite" class="sub-hint">（需站方权限）</span>
            </label>
            <label class="kind-option" :class="{ active: ownerKind === 'team' }">
              <input
                type="radio"
                name="ownerKind"
                value="team"
                :checked="ownerKind === 'team'"
                @change="setOwnerKind('team')"
              />
              <span class="kind-text">团队举办（团队公开赛 / 团队内部赛）</span>
            </label>
          </div>
        </div>

        <div v-if="ownerKind === 'team'" class="form-row">
          <span class="row-label">举办团队</span>
          <div class="row-value team-manage-cell">
            <div v-if="myTeams.length > 0" class="team-dropdown-row">
              <select v-model="teamId" class="form-input w-select">
                <option v-for="t in myTeams" :key="t.id" :value="t.id">
                  {{ t.name }}
                </option>
              </select>
              <button
                type="button"
                class="btn-secondary btn-sm"
                @click="showQuickTeam = !showQuickTeam"
              >
                {{ showQuickTeam ? '收起新建' : '+ 新建团队' }}
              </button>
            </div>
            <div v-else class="team-empty-tip">
              <span class="tip-txt">你尚未加入或管理任何团队，举办团队赛需先指定一个团队。</span>
              <button
                type="button"
                class="btn-primary btn-sm"
                @click="showQuickTeam = true"
              >
                <i class="fa-solid fa-plus"></i> 新建团队
              </button>
            </div>

            <!-- 快捷创建团队面板 -->
            <div v-if="showQuickTeam || myTeams.length === 0" class="quick-team-box">
              <div class="quick-team-title">
                <i class="fa-solid fa-users"></i> 新建团队并选为举办团队
              </div>
              <div class="quick-team-row">
                <input
                  v-model="newTeamName"
                  class="form-input"
                  placeholder="输入新团队名称（如：星轨开发组）"
                  maxlength="30"
                  @keydown.enter.prevent="quickCreateTeam"
                />
                <button
                  type="button"
                  class="btn-primary btn-sm"
                  :disabled="creatingTeam || !newTeamName.trim()"
                  @click="quickCreateTeam"
                >
                  {{ creatingTeam ? '创建中...' : '创建并选定' }}
                </button>
              </div>
              <div v-if="quickTeamError" class="form-error quick-err">{{ quickTeamError }}</div>
            </div>
          </div>
        </div>

        <div class="form-row">
          <span class="row-label">公开程度</span>
          <div class="row-value">
            <select v-model="visibility" class="form-input w-select">
              <template v-if="ownerKind === 'team'">
                <option value="team_public">团队公开赛（公开团队赛，全站所有人均可自由报名）</option>
                <option value="team">团队内部赛（仅团队成员可报名）</option>
                <option value="team_private">团队邀请赛（凭邀请码报名）</option>
              </template>
              <template v-else>
                <option value="public">公开赛（全站自由报名）</option>
                <option value="private">邀请赛（报名需邀请码）</option>
              </template>
            </select>
          </div>
        </div>

        <div v-if="visibility === 'private' || visibility === 'team_private'" class="form-row">
          <span class="row-label">邀请码</span>
          <div class="row-value">
            <input v-model="inviteCode" class="form-input w-title" maxlength="32" placeholder="3-32 位，报名时需填写" />
          </div>
        </div>

        <div class="form-row">
          <span class="row-label">比赛赛制</span>
          <div class="row-value">
            <select v-model="ruleType" class="form-input w-select">
              <option value="xcpc">XCPC 赛制（通过数优先，总罚时升序；实时评测，无部分分）</option>
              <option value="oi">OI 赛制（部分分，以最后一次提交为准；赛中盲交不反馈结果，榜单赛后公布）</option>
              <option value="ioi">IOI 赛制（部分分，每题取最高得分；赛中实时评测与反馈，榜单实时公开）</option>
            </select>
          </div>
        </div>

        <div class="form-row">
          <span class="row-label">管理员参赛</span>
          <div class="row-value">
            <label class="checkbox-label" style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
              <input v-model="hideSubmissionsFromAdmin" type="checkbox" />
              <span>开启管理员防偷窥/参赛保护</span>
            </label>
            <div class="form-help" style="font-size: 12px; color: var(--text-secondary); margin-top: 4px;">
              开启后，比赛期间除举办个人/举办团队全员外，任何管理员均无法查看其他选手的提交记录与源码；支持管理员公平参赛。
            </div>
          </div>
        </div>

        <div class="form-row">
          <span class="row-label">组队赛模式</span>
          <div class="row-value">
            <label class="checkbox-label" style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
              <input v-model="isTeamContest" type="checkbox" />
              <span>开启组队赛模式（支持多人组队参赛与榜单合并）</span>
            </label>
            <div class="form-help" style="font-size: 12px; color: var(--text-secondary); margin-top: 4px;">
              开启后，选手以队伍为单位参赛，队内任意成员提交均算作队伍成绩并共享通过状态与罚时。
            </div>
            <div v-if="isTeamContest" style="margin-top: 10px; display: flex; align-items: center; gap: 10px;">
              <span style="font-size: 13px; color: var(--text-strong);">每队人数上限：</span>
              <input
                v-model.number="maxTeamMembers"
                type="number"
                min="1"
                max="10"
                class="form-input"
                style="width: 80px;"
              />
              <span style="font-size: 13px; color: var(--text-secondary);">人（推荐 3 人，范围 1~10）</span>
            </div>
          </div>
        </div>

        <div class="form-row">
          <span class="row-label">开始时间</span>
          <div class="row-value time-pair">
            <input v-model="form.start_date" type="date" class="form-input" />
            <input v-model="form.start_time" type="time" class="form-input" />
          </div>
        </div>

        <div class="form-row">
          <span class="row-label">结束时间</span>
          <div class="row-value time-pair">
            <input v-model="form.end_date" type="date" class="form-input" />
            <input v-model="form.end_time" type="time" class="form-input" />
          </div>
        </div>

        <div class="form-row top">
          <span class="row-label">比赛说明</span>
          <div class="row-value">
            <MarkdownSplitEditor
              v-model="form.description"
              height="300px"
              placeholder="邀请码、来源、描述、难度、赛时答疑与赛后题解……（支持 Markdown）"
            />
          </div>
        </div>

        <div class="form-row top">
          <span class="row-label">比赛题目</span>
          <div class="row-value">
            <div class="code-add-row">
              <input
                v-model="codeInput"
                class="form-input w-title"
                placeholder="输入题号，如 P1001、U1001 或 T5，回车添加"
                :disabled="addingCode"
                @keydown.enter.prevent="addProblem"
              />
              <button class="btn-secondary" :disabled="addingCode || !codeInput.trim()" @click="addProblem">
                {{ addingCode ? '校验中...' : '添加' }}
              </button>
            </div>
            <div v-if="picked.length" class="picked-list">
              <div v-for="(p, i) in picked" :key="p.code" class="picked-item">
                <span class="picked-alias">{{ String.fromCharCode(65 + i) }}</span>
                <span class="picked-code">{{ p.code }}</span>
                <span class="picked-title">{{ p.title }}</span>
                <button class="mini-btn" title="上移" :disabled="i === 0" @click="moveProblem(i, -1)">↑</button>
                <button class="mini-btn" title="下移" :disabled="i === picked.length - 1" @click="moveProblem(i, 1)">↓</button>
                <button class="mini-btn danger" title="移除" @click="removeProblem(p.code)"><i class="fa-solid fa-xmark"></i></button>
              </div>
            </div>
            <div v-if="ownerKind === 'team' && hostTeamProblems.length" class="team-pool-box">
              <div class="team-pool-title">
                <i class="fa-solid fa-shapes"></i> 举办团队题库快速选入：
              </div>
              <div class="team-pool-list">
                <div
                  v-for="tp in hostTeamProblems"
                  :key="tp.id"
                  class="team-pool-item"
                >
                  <span class="tp-code">{{ tp.problem_number }}</span>
                  <span class="tp-title">{{ tp.title }}</span>
                  <span v-if="tp.is_public" class="tp-badge pub">团队公开题</span>
                  <span v-else class="tp-badge priv">团队内部题</span>
                  <button
                    v-if="!picked.some(x => x.code === tp.problem_number)"
                    type="button"
                    class="mini-btn add"
                    @click="addTeamProblemToPicked(tp)"
                  >+ 添加</button>
                  <span v-else class="tp-added"><i class="fa-solid fa-check"></i> 已添加</span>
                </div>
              </div>
            </div>
            <div class="hint">按顺序作为比赛内的 A / B / C / D… 支持主题库题目（P）、自拟题目（U）与团队公开题（T，当前 {{ picked.length }} 道）</div>
          </div>
        </div>

        <div v-if="createError" class="form-error">{{ createError }}</div>

        <div class="submit-row">
          <button class="btn-secondary" @click="router.push('/contests')">取消</button>
          <button class="btn-primary" :disabled="creating || !canSubmit" @click="doCreate">
            {{ creating ? '创建中...' : '创建比赛' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.contest-create-page { min-height: calc(100vh - 60px); }
.contest-create-container { max-width: 920px; margin: 0 auto; padding: 20px; }
.back-link { margin-bottom: 12px; }
.back-link a { color: var(--primary); font-size: 14px; cursor: pointer; text-decoration: none; }
.back-link a:hover { text-decoration: underline; }

/* 背景/圆角/边框/阴影由全局 .card 基类统一提供（亚克力），这里只管布局 */
.card.form-card { padding: 26px 30px; }
.form-row { display: flex; align-items: center; gap: 18px; padding: 12px 0; border-bottom: 1px solid #f7f8fa; }
.form-row.top { align-items: flex-start; }
.row-label { width: 90px; flex-shrink: 0; font-size: 14px; font-weight: 600; color: var(--text-strong); text-align: right; }
.row-value { flex: 1; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.form-input { padding: 8px 12px; border: 1px solid #dce0e6; border-radius: 8px; font-size: 14px; outline: none; font-family: inherit; }
.form-input:focus { border-color: var(--primary); }
.form-input:disabled { background: var(--bg-subtle); color: var(--text-sub); }
.w-title { width: min(360px, 100%); }
.w-select { width: min(360px, 100%); background: var(--surface-plain); }
.time-pair .form-input { width: auto; }
textarea.form-input { width: 100%; box-sizing: border-box; resize: vertical; }
.owner-name { font-weight: 700; font-size: 15px; }
.owner-check {color: light-dark(#52c41a, #34d399); }
.hint { font-size: 12px; color: #8e9aaf; }
.hint.mb { margin-bottom: 8px; }

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
.pool-no { color: var(--primary); font-weight: 600; }

.form-error { color: #e74c3c; font-size: 13px; margin-top: 12px; }
.submit-row { display: flex; justify-content: flex-end; gap: 12px; margin-top: 18px; }
.btn-primary { background: var(--primary); color: #fff; border: none; border-radius: 8px; padding: 9px 26px; font-weight: 600; cursor: pointer; font-size: 14px; }
.btn-primary:hover:not(:disabled) { background: var(--primary-hover); }
.btn-primary:disabled { opacity: .55; cursor: not-allowed; }
.btn-secondary { background: var(--bg-subtle); color: var(--text-strong); border: none; border-radius: 8px; padding: 9px 26px; font-weight: 600; cursor: pointer; font-size: 14px; }
.btn-sm { padding: 6px 14px; font-size: 13px; border-radius: 6px; }

.kind-selector { display: flex; gap: 14px; flex-wrap: wrap; }
.kind-option { display: inline-flex; align-items: center; gap: 6px; padding: 6px 14px; border: 1px solid var(--border-color, #dce0e6); border-radius: 8px; cursor: pointer; font-size: 14px; background: var(--surface-plain, #fff); color: var(--text-strong); }
.kind-option.active { border-color: var(--primary); background: rgba(59, 130, 246, 0.06); font-weight: 600; color: var(--primary); }
.kind-option.disabled { opacity: 0.55; cursor: not-allowed; background: var(--bg-subtle, #f5f6f8); }
.sub-hint { font-size: 12px; color: var(--text-sub, #8e9aaf); margin-left: 2px; }

.team-manage-cell { display: flex; flex-direction: column; gap: 10px; width: 100%; }
.team-dropdown-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.team-empty-tip { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; font-size: 13px; color: var(--text-sub, #64748b); }
.tip-txt { font-size: 13px; color: var(--text-sub, #64748b); }
.quick-team-box { width: min(480px, 100%); background: var(--surface-plain, #f8fafc); border: 1px solid var(--border-color, #e2e8f0); border-radius: 8px; padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; }
.quick-team-title { font-size: 13px; font-weight: 600; color: var(--text-strong, #334155); }
.quick-team-row { display: flex; gap: 8px; width: 100%; }
.quick-team-row .form-input { flex: 1; }
.quick-err { margin-top: 4px; font-size: 12px; }

.team-pool-box { margin-top: 10px; background: var(--surface-plain); border: 1px dashed var(--border-color); border-radius: 8px; padding: 10px 14px; width: 100%; box-sizing: border-box; }
.team-pool-title { font-size: 13px; font-weight: 600; color: var(--text-strong); margin-bottom: 8px; display: flex; align-items: center; gap: 6px; }
.team-pool-list { display: flex; flex-direction: column; gap: 6px; max-height: 180px; overflow-y: auto; }
.team-pool-item { display: flex; align-items: center; gap: 8px; font-size: 13px; padding: 4px 6px; border-radius: 6px; }
.team-pool-item:hover { background: var(--bg-subtle); }
.tp-code { font-weight: 700; color: var(--primary); min-width: 44px; }
.tp-title { flex: 1; color: var(--text-strong); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tp-badge { font-size: 11px; padding: 1px 6px; border-radius: 4px; font-weight: 600; }
.tp-badge.pub { background: color-mix(in srgb, var(--primary) 12%, transparent); color: var(--primary); }
.tp-badge.priv { background: var(--bg-subtle); color: var(--text-sub); }
.tp-added { font-size: 12px; color: #10b981; font-weight: 600; }

@media (max-width: 640px) {
  .form-row { flex-direction: column; align-items: stretch; gap: 6px; }
  .row-label { width: auto; text-align: left; }
}

/* ===== 手机端：容器横向内边距归零 + 表单卡片收窄 =====
   .form-card 原本 26px 30px，是全场最大的表单内边距，手机上只剩 240px 左右。 */
@media (max-width: 600px) {
  .contest-create-container {
    padding: 16px 0;
  }

  .card.form-card {
    padding: 16px 14px;
  }
}
</style>
