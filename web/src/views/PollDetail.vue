<script setup lang="ts">
/**
 * 单个投票的独立页面 `/polls/:id`。
 *
 * 关于「成功也弹失败」：请求失败**不等于**操作没生效（超时/连接中断时服务端
 * 可能已经提交）。所以失败后先重新拉一次真实状态：状态变了就按成功处理，
 * 没变才把真实原因告诉用户。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Swal from 'sweetalert2'
import { pollsApi, type Poll } from '@/api/polls'
import { useAuthStore } from '@/stores/auth'
import { isAnyAdmin } from '@/utils/permissions'
import { describePollError, looksLikePoll, pollTimeText, sameChoices } from '@/utils/poll'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const poll = ref<Poll | null>(null)
const loading = ref(true)
const error = ref('')
const acting = ref(false)
const picks = ref<number[]>([])

const pollId = computed(() => Number(route.params.id))
const isLoggedIn = computed(() => authStore.isAuthenticated)
const canCreate = computed(() => isAnyAdmin(authStore.currentUser))
const isCreator = computed(() =>
  !!poll.value && !!authStore.currentUser && authStore.currentUser.id === poll.value.created_by)
const canClose = computed(() => !!poll.value?.open && (canCreate.value || isCreator.value))

function applyPayload(payload: Poll) {
  poll.value = payload
  picks.value = [...(payload.my_votes || [])]
}

async function load(showSpinner = true) {
  if (!Number.isFinite(pollId.value)) {
    error.value = '投票不存在'
    loading.value = false
    return
  }
  if (showSpinner) loading.value = true
  error.value = ''
  try {
    const payload: any = await pollsApi.get(pollId.value)
    if (!looksLikePoll(payload)) {
      error.value = '投票不存在'
      return
    }
    applyPayload(payload)
  } catch (e: any) {
    const status = e?.response?.status
    error.value = status === 404 ? '投票不存在' : describePollError(e, '加载投票失败')
  } finally {
    loading.value = false
  }
}

function togglePick(optionId: number) {
  const p = poll.value
  if (!p || !p.open) return
  if (p.allow_multiple) {
    picks.value = picks.value.includes(optionId)
      ? picks.value.filter(x => x !== optionId)
      : [...picks.value, optionId]
  } else {
    picks.value = [optionId]
  }
}

async function submitVote() {
  const p = poll.value
  if (!p || acting.value) return
  const chosen = [...picks.value]
  if (!chosen.length) {
    await Swal.fire({ icon: 'info', text: '先选一个选项' })
    return
  }
  const before = [...(p.my_votes || [])]
  acting.value = true
  try {
    const payload: any = await pollsApi.vote(p.id, chosen)
    if (looksLikePoll(payload)) {
      applyPayload(payload)
    } else {
      await load(false)
    }
  } catch (e: any) {
    // 关键一步：先看服务端真实状态，别把「已生效但响应没回来」当成失败
    try {
      const fresh: any = await pollsApi.get(p.id)
      if (looksLikePoll(fresh)) {
        applyPayload(fresh)
        if (!sameChoices(fresh.my_votes, before)) return   // 已经生效 → 不弹错误
      }
    } catch {
      // 连刷新都失败：那就按原始错误提示
    }
    await Swal.fire({ icon: 'error', text: describePollError(e, '投票失败') })
  } finally {
    acting.value = false
  }
}

async function closePoll() {
  const p = poll.value
  if (!p || acting.value) return
  const ok = await Swal.fire({
    icon: 'warning', text: '结束这个投票？结束后不能再投票。',
    showCancelButton: true, confirmButtonText: '结束', cancelButtonText: '取消',
  })
  if (!ok.isConfirmed) return
  acting.value = true
  try {
    const payload: any = await pollsApi.close(p.id)
    if (looksLikePoll(payload)) applyPayload(payload)
    else await load(false)
  } catch (e: any) {
    try {
      const fresh: any = await pollsApi.get(p.id)
      if (looksLikePoll(fresh)) {
        applyPayload(fresh)
        if (!fresh.open) return    // 确实已经结束了 → 不弹错误
      }
    } catch { /* ignore */ }
    await Swal.fire({ icon: 'error', text: describePollError(e, '操作失败') })
  } finally {
    acting.value = false
  }
}

function copyLink() {
  const url = `${window.location.origin}/polls/${pollId.value}`
  void navigator.clipboard?.writeText(url).then(
    () => Swal.fire({ icon: 'success', text: '链接已复制', timer: 1200, showConfirmButton: false }),
    () => Swal.fire({ icon: 'error', text: '复制失败，请手动复制地址栏链接' }),
  )
}

watch(pollId, () => load())
onMounted(() => load())
</script>

<template>
  <div class="poll-page">
    <div class="back-row">
      <a class="back-link" @click.prevent="router.push('/polls')">
        <i class="fa-solid fa-angle-left"></i> 全部投票
      </a>
      <button v-if="poll" class="btn-ghost" @click="copyLink">
        <i class="fa-solid fa-link"></i> 复制链接
      </button>
    </div>

    <div v-if="loading" class="poll-card empty"><span class="loading-spinner"></span> 加载中…</div>
    <div v-else-if="error" class="poll-card empty error">
      {{ error }}
      <div style="margin-top:10px">
        <button class="btn-ghost" @click="router.push('/polls')">返回列表</button>
      </div>
    </div>

    <template v-else-if="poll">
      <div class="poll-card">
        <div class="poll-title-row">
          <h2>{{ poll.title }}</h2>
          <span class="badge" :class="poll.open ? 'open' : 'closed'">{{ poll.open ? '进行中' : '已结束' }}</span>
          <span v-if="poll.allow_multiple" class="badge">多选</span>
          <span v-if="poll.anonymous" class="badge">匿名</span>
        </div>
        <p v-if="poll.description" class="poll-desc">{{ poll.description }}</p>
        <p class="poll-meta">
          #{{ poll.id }} · 共 {{ poll.voter_count }} 人参与
          <span v-if="poll.ends_at"> · 截止 {{ pollTimeText(poll.ends_at) }}</span>
          <span v-else> · 手动结束</span>
          <span v-if="poll.created_at"> · 发起于 {{ pollTimeText(poll.created_at) }}</span>
        </p>

        <div class="poll-options">
          <button
            v-for="o in poll.options"
            :key="o.id"
            class="option"
            :class="{ picked: picks.includes(o.id), disabled: !poll.open }"
            :disabled="!poll.open"
            @click="togglePick(o.id)"
          >
            <span class="tick" :class="{ on: picks.includes(o.id) }">
              <i :class="poll.allow_multiple ? 'fa-solid fa-square-check' : 'fa-solid fa-circle-check'"></i>
            </span>
            <span class="text">{{ o.text }}</span>
            <span v-if="poll.results_visible && o.votes !== null" class="count">
              {{ o.votes }} 票 · {{ o.percent }}%
            </span>
          </button>
          <div v-if="!poll.results_visible" class="hidden-results">投票结束前不公开票数</div>
        </div>

        <div class="poll-actions">
          <button
            v-if="poll.open && isLoggedIn"
            class="btn-primary"
            :disabled="acting"
            @click="submitVote"
          >{{ (poll.my_votes || []).length ? '修改我的投票' : '投票' }}</button>
          <button
            v-if="canClose"
            class="btn-ghost"
            :disabled="acting"
            @click="closePoll"
          >结束投票</button>
          <span v-if="!isLoggedIn" class="hint">登录后才能投票</span>
        </div>

        <div v-if="poll.results_visible && !poll.anonymous && poll.voters.length" class="voters">
          <span class="voters-label">投票人（{{ poll.voters.length }}）</span>
          <a
            v-for="v in poll.voters"
            :key="v.user_number"
            class="voter"
            @click.prevent="router.push(`/user/${v.user_number}`)"
          >{{ v.username }}</a>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.poll-page { max-width: 760px; margin: 0 auto; padding: 16px; color: var(--text-main); }
.back-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.back-link { cursor: pointer; font-size: 14px; color: var(--primary-text); }
.btn-primary { padding: 6px 16px; border-radius: 6px; border: 1px solid var(--primary); background: var(--primary); color: #fff; cursor: pointer; }
.btn-primary:disabled { opacity: .6; cursor: not-allowed; }
.btn-ghost { padding: 5px 12px; border-radius: 6px; border: 1px solid var(--border-color); background: transparent;
  color: var(--text-main); cursor: pointer; font-size: 13px; }
.poll-card { background: var(--surface-plain); color: var(--text-main); border: 1px solid var(--border-color);
  border-radius: 10px; padding: 16px 18px; margin-bottom: 12px; box-shadow: var(--shadow-card); }
.poll-card.empty { text-align: center; color: var(--text-sub); }
.poll-card.error { color: var(--danger-text); }
.poll-title-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.poll-title-row h2 { font-size: 19px; font-weight: 700; color: var(--text-strong); }
.badge { font-size: 11px; padding: 1px 8px; border-radius: 10px;
  background: color-mix(in srgb, var(--primary) 14%, transparent); color: var(--primary-text); }
.badge.closed { background: var(--bg-subtle); color: var(--text-sub); }
.badge.open { background: color-mix(in srgb, var(--success) 16%, transparent); color: var(--success-text); }
.poll-desc { font-size: 14px; margin-top: 8px; white-space: pre-wrap; color: var(--text-main); }
.poll-meta { font-size: 12px; color: var(--text-sub); margin-top: 6px; }
.poll-options { margin-top: 12px; display: flex; flex-direction: column; gap: 8px; }
.option { display: flex; align-items: center; gap: 10px; text-align: left; padding: 10px 12px; border-radius: 8px;
  border: 1px solid var(--border-color); background: transparent; color: var(--text-main); cursor: pointer; font-size: 14px; }
.option:hover:not(:disabled) { border-color: var(--primary); }
.option.picked { border-color: var(--primary); background: color-mix(in srgb, var(--primary) 10%, transparent); }
.option.disabled { cursor: default; opacity: .85; }
.tick { color: var(--border-color); }
.tick.on { color: var(--primary); }
.option .text { flex: 1; }
.option .count { font-size: 12px; color: var(--text-sub); }
.hidden-results { font-size: 12px; color: var(--text-sub); }
.poll-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 14px; }
.hint { font-size: 13px; color: var(--text-sub); }
.voters { margin-top: 16px; border-top: 1px dashed var(--border-color); padding-top: 10px; font-size: 13px;
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.voters-label { color: var(--text-sub); }
.voter { color: var(--primary-text); cursor: pointer; }
</style>
