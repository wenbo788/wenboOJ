<script setup lang="ts">
/**
 * 管理后台：提交查重（疑似抄袭榜）。
 *
 * 只出提示，不自动判罚：看完两边代码，再去题目/比赛后台走「标记作弊者」等流程。
 * 后端接口：POST /admin/plagiarism/scan、GET /admin/plagiarism、GET /admin/plagiarism/{id}
 * 权限与后端一致：题目管理（白名单/超管/大管/题管）。
 */
import { computed, onMounted, ref } from 'vue'
import apiClient from '@/api/client'

interface Brief {
  id: number
  user_id: number
  user_number: number | null
  username: string | null
  language: string
  status: string
  score: number
  judged_at: string | null
}

interface Pair {
  id: number
  score: number
  contest_id: number | null
  problem_id: number
  problem_title: string | null
  a: Brief
  b: Brief
  detail: Record<string, unknown> | null
}

interface ContestOption {
  id: number
  title: string
}

const contests = ref<ContestOption[]>([])
const contestId = ref<number | ''>('')
const threshold = ref(0.8)
const pairs = ref<Pair[]>([])
const loading = ref(false)
const scanning = ref(false)
const error = ref('')
// 正常提示（不是错误）：例如「扫了 N 份但没有超过阈值的组合」
const info = ref('')
const detail = ref<{ a: Brief & { code: string }; b: Brief & { code: string }; score: number; problem_title: string | null } | null>(null)

const hasScope = computed(() => contestId.value !== '')

async function loadContests() {
  try {
    const data: any = await apiClient.get('/api/contests', { params: { page: 0, page_size: 100 } })
    const items = data?.items ?? data?.contests ?? []
    contests.value = items.map((c: any) => ({ id: c.id, title: c.title }))
  } catch (e) {
    // 下拉拉不到不算致命：可以直接用「全部」看已扫出来的结果
    console.warn('拉比赛列表失败', e)
  }
}

async function loadPairs() {
  loading.value = true
  error.value = ''
  try {
    const params: Record<string, unknown> = { min_score: 0 }
    if (hasScope.value) params.contest_id = contestId.value
    const data: any = await apiClient.get('/api/admin/plagiarism', { params })
    pairs.value = data?.items ?? []
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '加载失败'
  } finally {
    loading.value = false
  }
}

async function scan() {
  if (!hasScope.value) return
  scanning.value = true
  error.value = ''
  info.value = ''
  try {
    const data: any = await apiClient.post('/api/admin/plagiarism/scan', {
      contest_id: contestId.value,
      threshold: threshold.value,
    })
    await loadPairs()
    if (data?.pairs === 0) {
      info.value = `扫描了 ${data?.scanned ?? 0} 份提交，没有超过阈值的组合`
    }
    if (data?.truncated) {
      info.value = (info.value ? info.value + '；' : '') + '提交数超过单次扫描上限，本次只扫了一部分'
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '扫描失败'
  } finally {
    scanning.value = false
  }
}

async function openPair(id: number) {
  try {
    detail.value = await apiClient.get(`/api/admin/plagiarism/${id}`)
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '读取代码失败'
  }
}

function who(b: Brief) {
  return b.username ? `${b.username}（#${b.user_number ?? b.user_id}）` : `#${b.user_id}`
}

onMounted(async () => {
  await loadContests()
  if (contests.value.length) {
    contestId.value = contests.value[0].id
    await loadPairs()
  }
})
</script>

<template>
  <div class="page">
    <div class="card">
      <div class="card-header">
        <span>提交查重（疑似抄袭）</span>
        <span class="hint">只做提示，不自动判罚</span>
      </div>

      <div class="controls">
        <label>
          比赛
          <select v-model="contestId" @change="loadPairs">
            <option value="">（不选：只看已扫描结果）</option>
            <option v-for="c in contests" :key="c.id" :value="c.id">{{ c.title }}</option>
          </select>
        </label>
        <label>
          阈值
          <input v-model.number="threshold" type="number" min="0.1" max="1" step="0.05" />
        </label>
        <button class="primary" :disabled="!hasScope || scanning" @click="scan">
          {{ scanning ? '扫描中…' : '扫描这个比赛' }}
        </button>
        <button :disabled="loading" @click="loadPairs">刷新</button>
      </div>

      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="info" class="info">{{ info }}</p>

      <table v-if="pairs.length" class="pairs">
        <thead>
          <tr>
            <th>相似度</th>
            <th>题目</th>
            <th>提交 A</th>
            <th>提交 B</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in pairs" :key="p.id">
            <td class="score">{{ (p.score * 100).toFixed(1) }}%</td>
            <td>{{ p.problem_title || `#${p.problem_id}` }}</td>
            <td>{{ who(p.a) }}<span class="lang">{{ p.a.language }}</span></td>
            <td>{{ who(p.b) }}<span class="lang">{{ p.b.language }}</span></td>
            <td><button @click="openPair(p.id)">看代码</button></td>
          </tr>
        </tbody>
      </table>
      <p v-else-if="!loading" class="empty">
        还没有结果。选一个比赛点「扫描这个比赛」——同一题、同一语言、不同人的提交才会两两比较。
      </p>
    </div>

    <div v-if="detail" class="overlay" @click.self="detail = null">
      <div class="modal">
        <div class="modal-header">
          <span>
            相似度 {{ (detail.score * 100).toFixed(1) }}%
            <span class="hint">{{ detail.problem_title }}</span>
          </span>
          <button @click="detail = null">关闭</button>
        </div>
        <div class="codes">
          <div class="side">
            <div class="side-title">{{ who(detail.a) }}</div>
            <pre>{{ detail.a.code }}</pre>
          </div>
          <div class="side">
            <div class="side-title">{{ who(detail.b) }}</div>
            <pre>{{ detail.b.code }}</pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.card { background: var(--card-bg, #fff); border-radius: 8px; padding: 16px; }
.card-header { display: flex; align-items: baseline; gap: 8px; font-weight: 600; margin-bottom: 12px; }
.hint { font-size: 12px; font-weight: 400; opacity: .65; }
.controls { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-bottom: 12px; }
.controls label { display: flex; align-items: center; gap: 6px; font-size: 13px; }
.controls select, .controls input { padding: 4px 6px; border: 1px solid #ccc; border-radius: 4px; }
.controls input[type="number"] { width: 72px; }
.controls button { padding: 5px 10px; border-radius: 4px; border: 1px solid #ccc; cursor: pointer; }
.controls button.primary { background: #0d47a1; border-color: #0d47a1; color: #fff; }
.controls button:disabled { opacity: .5; cursor: not-allowed; }
.error { color: #c0392b; font-size: 13px; margin: 8px 0; }
.info { color: #0d47a1; font-size: 13px; margin: 8px 0; }
.empty { font-size: 13px; opacity: .7; }
table.pairs { width: 100%; border-collapse: collapse; font-size: 13px; }
table.pairs th, table.pairs td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #eee; }
.score { font-weight: 600; color: #c0392b; }
.lang { margin-left: 6px; font-size: 11px; opacity: .6; }
.overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, .5); display: flex; align-items: center; justify-content: center; z-index: 50; }
.modal { background: #fff; border-radius: 8px; width: 92vw; height: 86vh; display: flex; flex-direction: column; }
.modal-header { display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; border-bottom: 1px solid #eee; font-weight: 600; }
.codes { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; background: #eee; flex: 1; min-height: 0; }
.side { display: flex; flex-direction: column; background: #fff; min-height: 0; }
.side-title { padding: 6px 10px; font-size: 12px; font-weight: 600; border-bottom: 1px solid #eee; }
.side pre { margin: 0; padding: 10px; overflow: auto; font-size: 12px; line-height: 1.5; flex: 1; }
</style>
