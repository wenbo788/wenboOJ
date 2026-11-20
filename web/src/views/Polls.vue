<script setup lang="ts">
/**
 * 站内投票列表页：只负责「看列表 + 管理员发起」。
 * 投票本身在详情页 `/polls/:id`（每个投票一个独立页面）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Swal from 'sweetalert2'
import { pollsApi, type Poll } from '@/api/polls'
import { useAuthStore } from '@/stores/auth'
import { isAnyAdmin } from '@/utils/permissions'
import { describePollError, looksLikePoll, pollTimeText } from '@/utils/poll'

const router = useRouter()
const authStore = useAuthStore()

const polls = ref<Poll[]>([])
const loading = ref(true)
const error = ref('')
const statusFilter = ref<'all' | 'open' | 'closed'>('open')
const submitting = ref(false)

const canCreate = computed(() => isAnyAdmin(authStore.currentUser))
const isLoggedIn = computed(() => authStore.isAuthenticated)

const showForm = ref(false)
const form = ref({
  title: '',
  description: '',
  options: ['', ''],
  allow_multiple: false,
  anonymous: false,
  show_results_before_end: true,
  ends_at: '',
})

async function ensureCurrentUser() {
  // 直接打开 /polls（或刷新）时，store 里可能只有令牌、还没用户资料 ——
  // 那样「发起投票」按钮会一直不出现（isAuthenticated 需要 user）。
  // 这里补还原 + 拉取；失败就按普通用户渲染，不阻塞列表。
  try {
    if (!authStore.accessToken) authStore.restoreState()
    if (authStore.accessToken && !authStore.currentUser) await authStore.fetchCurrentUser()
  } catch {
    /* 静默失败：按普通用户渲染，不阻塞列表 */
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data: any = await pollsApi.list(statusFilter.value, 0, 50)
    polls.value = Array.isArray(data?.items) ? data.items : []
  } catch (e: any) {
    error.value = describePollError(e, '加载投票失败')
  } finally {
    loading.value = false
  }
}

function switchStatus(s: 'all' | 'open' | 'closed') {
  statusFilter.value = s
  load()
}

function openPoll(p: Poll) {
  router.push(`/polls/${p.id}`)
}

function addOption() {
  if (form.value.options.length >= 10) return
  form.value.options.push('')
}

function removeOption(i: number) {
  if (form.value.options.length <= 2) return
  form.value.options.splice(i, 1)
}

async function submitForm() {
  submitting.value = true
  const title = form.value.title.trim()
  try {
    const options = form.value.options.map(x => x.trim()).filter(Boolean)
    const payload = await pollsApi.create({
      title,
      description: form.value.description.trim(),
      options,
      allow_multiple: form.value.allow_multiple,
      anonymous: form.value.anonymous,
      show_results_before_end: form.value.show_results_before_end,
      ends_at: form.value.ends_at ? new Date(form.value.ends_at).toISOString() : null,
    })
    if (!looksLikePoll(payload)) {
      // 拿到怪响应也先别报失败：重新拉一次列表，以服务端为准
      await load()
      showForm.value = false
      return
    }
    polls.value = [payload, ...polls.value.filter(p => p.id !== payload.id)]
    showForm.value = false
    form.value = { title: '', description: '', options: ['', ''], allow_multiple: false,
      anonymous: false, show_results_before_end: true, ends_at: '' }
    router.push(`/polls/${payload.id}`)
  } catch (e: any) {
    // 请求失败 ≠ 没建成（超时/中断时服务端可能已经提交）：先刷新，列表里有了就按成功处理
    const before = new Set(polls.value.map(p => p.id))
    await load()
    const created = polls.value.find(p => !before.has(p.id) && p.title === title)
    if (created) {
      showForm.value = false
      router.push(`/polls/${created.id}`)
      return
    }
    await Swal.fire({ icon: 'error', text: describePollError(e, '创建失败') })
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await ensureCurrentUser()
  await load()
})
</script>

<template>
  <div class="poll-page">
    <div class="poll-head">
      <div>
        <h2 class="page-title"><i class="fa-solid fa-square-poll-vertical"></i> 站内投票</h2>
        <p class="page-sub">管理员发起，登录用户一人一票；多选投票可以勾多个，截止前可以改票。</p>
      </div>
      <div class="poll-head-actions">
        <div class="tab-group">
          <button class="tab-btn" :class="{ active: statusFilter === 'open' }" @click="switchStatus('open')">进行中</button>
          <button class="tab-btn" :class="{ active: statusFilter === 'closed' }" @click="switchStatus('closed')">已结束</button>
          <button class="tab-btn" :class="{ active: statusFilter === 'all' }" @click="switchStatus('all')">全部</button>
        </div>
        <button v-if="canCreate" class="btn-primary" @click="showForm = !showForm">
          <i class="fa-solid fa-plus"></i> 发起投票
        </button>
      </div>
    </div>

    <!-- 发起投票 -->
    <div v-if="showForm" class="poll-card form-card">
      <h3>发起投票</h3>
      <label>标题<input v-model="form.title" maxlength="200" placeholder="例如：下次训练赛时间" /></label>
      <label>说明（可选）<textarea v-model="form.description" rows="2" /></label>
      <div class="options-edit">
        <div v-for="(_, i) in form.options" :key="i" class="option-row">
          <input v-model="form.options[i]" maxlength="200" :placeholder="`选项 ${i + 1}`" />
          <button class="btn-icon" :disabled="form.options.length <= 2" @click="removeOption(i)">
            <i class="fa-solid fa-xmark"></i>
          </button>
        </div>
        <button class="btn-ghost" :disabled="form.options.length >= 10" @click="addOption">+ 加一个选项</button>
      </div>
      <div class="form-flags">
        <label class="inline"><input v-model="form.allow_multiple" type="checkbox" /> 多选</label>
        <label class="inline"><input v-model="form.anonymous" type="checkbox" /> 匿名（不展示投票人）</label>
        <label class="inline"><input v-model="form.show_results_before_end" type="checkbox" /> 结束前公开票数</label>
        <label class="inline">截止时间（可选）<input v-model="form.ends_at" type="datetime-local" /></label>
      </div>
      <div class="form-actions">
        <button class="btn-primary" :disabled="submitting" @click="submitForm">
          {{ submitting ? '提交中…' : '发布投票' }}
        </button>
        <button class="btn-ghost" @click="showForm = false">取消</button>
      </div>
    </div>

    <div v-if="!isLoggedIn" class="poll-card empty">登录后才能投票。</div>
    <div v-else-if="loading" class="poll-card empty"><span class="loading-spinner"></span> 加载中…</div>
    <div v-else-if="error" class="poll-card empty error">{{ error }}</div>
    <div v-else-if="!polls.length" class="poll-card empty">还没有投票。</div>

    <div
      v-for="p in polls"
      :key="p.id"
      class="poll-card list-card"
      role="link"
      tabindex="0"
      @click="openPoll(p)"
      @keydown.enter="openPoll(p)"
    >
      <div class="poll-title-row">
        <h3>{{ p.title }}</h3>
        <span class="badge" :class="p.open ? 'open' : 'closed'">{{ p.open ? '进行中' : '已结束' }}</span>
        <span v-if="p.allow_multiple" class="badge">多选</span>
        <span v-if="p.anonymous" class="badge">匿名</span>
      </div>
      <p v-if="p.description" class="poll-desc">{{ p.description }}</p>
      <p class="poll-meta">
        共 {{ p.voter_count }} 人参与
        <span v-if="p.ends_at"> · 截止 {{ pollTimeText(p.ends_at) }}</span>
        <span v-else> · 手动结束</span>
        <span v-if="(p.my_votes || []).length" class="voted-tag"> · 我已投票</span>
      </p>
      <div class="list-foot">
        <span class="option-preview">{{ p.options.map(o => o.text).join(' / ') }}</span>
        <span class="go">进入投票 <i class="fa-solid fa-angle-right"></i></span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.poll-page { max-width: 880px; margin: 0 auto; padding: 16px; color: var(--text-main); }
.poll-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.page-title { font-size: 20px; font-weight: 700; color: var(--text-strong); }
.page-sub { font-size: 13px; color: var(--text-sub); margin-top: 4px; }
.poll-head-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.tab-group { display: inline-flex; border: 1px solid var(--border-color); border-radius: 8px; overflow: hidden; }
.tab-btn { padding: 6px 12px; background: transparent; border: none; cursor: pointer; font-size: 13px; color: var(--text-main); }
.tab-btn.active { background: var(--primary); color: #fff; }
.btn-primary { padding: 6px 14px; border-radius: 6px; border: 1px solid var(--primary); background: var(--primary); color: #fff; cursor: pointer; }
.btn-primary:disabled { opacity: .6; cursor: not-allowed; }
.btn-ghost { padding: 6px 12px; border-radius: 6px; border: 1px solid var(--border-color); background: transparent; color: var(--text-main); cursor: pointer; }
.btn-icon { border: none; background: transparent; color: var(--text-sub); cursor: pointer; }
.poll-card { background: var(--surface-plain); color: var(--text-main); border: 1px solid var(--border-color); border-radius: 10px; padding: 14px 16px; margin-bottom: 12px; box-shadow: var(--shadow-card); }
.poll-card.empty { text-align: center; color: var(--text-sub); }
.poll-card.error { color: var(--danger-text); }
.list-card { cursor: pointer; transition: box-shadow .15s, transform .15s; }
.list-card:hover { box-shadow: var(--shadow-card-hover); transform: translateY(-1px); }
.poll-title-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.poll-title-row h3 { font-size: 16px; font-weight: 600; color: var(--text-strong); }
.badge { font-size: 11px; padding: 1px 8px; border-radius: 10px;
  background: color-mix(in srgb, var(--primary) 14%, transparent); color: var(--primary-text); }
.badge.closed { background: var(--bg-subtle); color: var(--text-sub); }
.badge.open { background: color-mix(in srgb, var(--success) 16%, transparent); color: var(--success-text); }
.poll-desc { font-size: 13px; margin-top: 6px; white-space: pre-wrap; color: var(--text-main); }
.poll-meta { font-size: 12px; color: var(--text-sub); margin-top: 4px; }
.voted-tag { color: var(--success-text); }
.list-foot { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 10px; }
.option-preview { font-size: 13px; color: var(--text-sub); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.go { font-size: 13px; color: var(--primary-text); white-space: nowrap; }
.form-card label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--text-sub); margin-bottom: 8px; }
.form-card input, .form-card textarea { padding: 6px 8px; border: 1px solid var(--border-color); border-radius: 6px; font: inherit;
  background: var(--bg-subtle); color: var(--text-main); }
.options-edit { display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; }
.option-row { display: flex; gap: 6px; align-items: center; }
.option-row input { flex: 1; }
.form-flags { display: flex; flex-wrap: wrap; gap: 14px; font-size: 13px; color: var(--text-sub); margin-bottom: 10px; }
.form-flags label.inline { flex-direction: row; align-items: center; gap: 6px; margin: 0; }
.form-actions { display: flex; gap: 10px; }
</style>
