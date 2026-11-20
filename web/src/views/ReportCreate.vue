<script setup lang="ts">
/**
 * 举报页面（犇犇 / 帖子 / 帖子回复通用）。
 * 路由：/report/:type/:id，例如 /report/benben/2
 *
 * 打开时查询当前用户对该内容的举报状态：
 *   - 未举报：选择举报分类（必选）+ 补充说明（选填）后提交；
 *   - 已举报且未审核：可撤销举报；
 *   - 已审核：展示判定结果，不能再操作。
 *
 * 有效举报达到 6 人的内容会被系统自动删除；返回原页面时
 * 路由组件重建会自动重新加载列表，无需手动刷新。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Swal from 'sweetalert2'
import apiClient from '@/api/client'

type TargetType = 'benben' | 'post' | 'comment'
type View = 'none' | 'reported' | 'guilty' | 'false_report'

const TARGET_NAMES: Record<TargetType, string> = {
  benben: '犇犇',
  post: '帖子',
  comment: '帖子回复',
}

const CATEGORIES = [
  { value: 'abuse', label: '辱骂攻击 / 人肉搜索', desc: '辱骂、人身攻击、引战、泄露他人隐私' },
  { value: 'spam', label: '广告刷屏', desc: '垃圾广告、恶意刷屏、无意义灌水' },
  { value: 'porn_illegal', label: '色情 / 违法违规', desc: '色情低俗、违法内容、政治敏感' },
  { value: 'infringe_other', label: '侵权抄袭 / 其他', desc: '侵权、抄袭、作弊，或其他违规原因' },
]

const route = useRoute()
const router = useRouter()

const targetType = computed<TargetType>(() => route.params.type as TargetType)
const targetId = computed<number>(() => Number(route.params.id))
const targetLabel = computed(
  () => `${TARGET_NAMES[targetType.value] ?? '内容'} #${targetId.value}`,
)

const loading = ref(true)
const submitting = ref(false)
const view = ref<View>('none')
const reportId = ref<number | null>(null)
const category = ref('abuse')
const detail = ref('')
const errorMsg = ref('')
const activeCount = ref(0)
const autoDeleted = ref(false)

function goBack() {
  // 有历史则返回；直接通过 URL 打开时回首页兜底
  if (window.history.state?.back) router.back()
  else router.push('/')
}

async function refreshState() {
  loading.value = true
  errorMsg.value = ''
  try {
    const data: any = await apiClient.get('/api/reports/check', {
      params: { target_type: targetType.value, target_id: targetId.value },
    })
    if (!data.reported) {
      view.value = data.verdict ? (data.verdict as 'guilty' | 'false_report') : 'none'
    } else {
      view.value = 'reported'
    }
    reportId.value = data.report_id ?? null
  } catch (err: any) {
    errorMsg.value = err.response?.data?.detail || '举报状态查询失败'
  } finally {
    loading.value = false
  }
}

async function submit() {
  if (submitting.value) return
  const confirm = await Swal.fire({
    icon: 'warning',
    title: '确认提交举报？',
    text: '恶意举报将被记录，请确认举报内容属实。',
    confirmButtonText: '确认举报',
    cancelButtonText: '再想想',
    showCancelButton: true,
  })
  if (!confirm.isConfirmed) return

  submitting.value = true
  errorMsg.value = ''
  try {
    const res: any = await apiClient.post('/api/reports', {
      target_type: targetType.value,
      target_id: targetId.value,
      category: category.value,
      detail: detail.value.trim() || null,
    })
    activeCount.value = res.active_count ?? 0
    autoDeleted.value = !!res.auto_deleted
    view.value = 'reported'
  } catch (err: any) {
    errorMsg.value = err.response?.data?.detail || '举报提交失败'
  } finally {
    submitting.value = false
  }
}

async function revoke() {
  if (reportId.value == null) return
  const confirm = await Swal.fire({
    icon: 'question',
    title: '撤销这条举报？',
    text: '撤销后举报计数减 1；若该内容因多人举报被自动删除，撤销后计数不足 6 人时内容将自动恢复。',
    confirmButtonText: '确认撤销',
    cancelButtonText: '取消',
    showCancelButton: true,
  })
  if (!confirm.isConfirmed) return

  submitting.value = true
  errorMsg.value = ''
  try {
    await apiClient.post(`/api/reports/${reportId.value}/revoke`)
    view.value = 'none'
    category.value = 'abuse'
    detail.value = ''
  } catch (err: any) {
    errorMsg.value = err.response?.data?.detail || '撤销失败'
  } finally {
    submitting.value = false
  }
}

onMounted(refreshState)
</script>

<template>
  <div class="report-page">
    <div class="report-container">
      <!-- 头部 -->
      <div class="card head-card">
        <div class="head-row">
          <h2 class="page-title">
            <i class="fa-solid fa-flag head-icon"></i> 举报{{ targetLabel }}
          </h2>
          <div class="head-actions">
            <button class="btn-ghost" @click="goBack">
              <i class="fa-solid fa-arrow-left"></i> 返回
            </button>
            <button v-if="view === 'none'" class="btn-primary" :disabled="submitting" @click="submit">
              {{ submitting ? '提交中...' : '提交举报' }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="loading" class="card state-card">
        <span class="loading-spinner"></span> 正在查询举报状态…
      </div>

      <template v-else>
        <div v-if="errorMsg" class="card error-card">
          <i class="fa-solid fa-circle-exclamation"></i> {{ errorMsg }}
        </div>

        <!-- 未举报：分类 + 补充说明 -->
        <div v-if="view === 'none'" class="card">
          <div class="section-title">举报原因</div>
          <div class="report-tip">
            <i class="fa-solid fa-shield-halved"></i>
            请如实选择举报原因，恶意举报将被记录。
          </div>
          <div class="cat-list">
            <label
              v-for="c in CATEGORIES"
              :key="c.value"
              class="cat-item"
              :class="{ active: category === c.value }"
            >
              <input v-model="category" type="radio" :value="c.value" />
              <span class="cat-text">
                <span class="cat-label">{{ c.label }}</span>
                <span class="cat-desc">{{ c.desc }}</span>
              </span>
            </label>
          </div>
          <div class="detail-field">
            <div class="field-label">补充说明（选填，最多 500 字）</div>
            <textarea
              v-model="detail"
              maxlength="500"
              rows="5"
              placeholder="可补充具体情况，帮助秩序管理员审核"
            ></textarea>
            <div class="detail-count">{{ detail.length }}/500</div>
          </div>
        </div>

        <!-- 已举报待审核 -->
        <div v-else-if="view === 'reported'" class="card">
          <div class="section-title">举报状态</div>
          <div class="result-alert result-alert--pending">
            <i class="fa-solid fa-circle-check"></i>
            <div>
              <strong>你已提交举报，等待秩序管理员审核。</strong>
              <span v-if="activeCount > 0">目前已有 {{ activeCount }} 人有效举报该内容，满 6 人将自动删除。</span>
              <span v-else>审核完成前可以撤销举报；该内容被 6 人以上举报时会被系统自动删除。</span>
            </div>
          </div>
          <div v-if="autoDeleted" class="result-alert result-alert--deleted">
            <i class="fa-solid fa-trash-can"></i>
            <div>
              <strong>该内容已被多人举报，系统已自动删除。</strong>
              <span>返回后它将从列表中消失。</span>
            </div>
          </div>
          <div class="action-row">
            <button class="btn-ghost" @click="goBack">返回</button>
            <button class="btn-danger" :disabled="submitting" @click="revoke">
              {{ submitting ? '处理中...' : '撤销举报' }}
            </button>
          </div>
        </div>

        <!-- 举报成立 -->
        <div v-else-if="view === 'guilty'" class="card">
          <div class="section-title">举报状态</div>
          <div class="result-alert result-alert--guilty">
            <i class="fa-solid fa-gavel"></i>
            <div>
              <strong>举报成立。</strong>
              <span>该内容已被认定为违规内容并删除，作者已被处理。</span>
            </div>
          </div>
          <div class="action-row">
            <button class="btn-ghost" @click="goBack">返回</button>
          </div>
        </div>

        <!-- 恶意举报 -->
        <div v-else class="card">
          <div class="section-title">举报状态</div>
          <div class="result-alert result-alert--false">
            <i class="fa-solid fa-triangle-exclamation"></i>
            <div>
              <strong>举报不成立。</strong>
              <span>该举报被认定为恶意举报，请遵守社区规范。</span>
            </div>
          </div>
          <div class="action-row">
            <button class="btn-ghost" @click="goBack">返回</button>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.report-page {
  min-height: 100vh;
  line-height: 1.5;
}

.report-container {
  max-width: 860px;
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

.head-icon {
  color: var(--primary);
  margin-right: 4px;
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

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
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

.btn-danger:hover:not(:disabled) {
  background: var(--primary);
  color: #fff;
}

.btn-danger:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.state-card {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text-sub);
  justify-content: center;
  padding: 40px 24px;
}

.error-card {
  color: var(--primary);
  font-size: 13px;
}

.section-title {
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--text-strong);
  border-left: 4px solid var(--primary);
  padding-left: 10px;
  margin-bottom: 16px;
}

.report-tip {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 13px;
  color: var(--text-sub);
  background: var(--surface-plain);
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 16px;
  line-height: 1.7;
}

.report-tip i {
  color: var(--primary);
  margin-top: 3px;
}

.cat-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 18px;
}

.cat-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.15s;
}

.cat-item:hover {
  border-color: #94a3b8;
}

.cat-item.active {
  border-color: var(--primary);
  background: rgba(231, 76, 60, 0.04);
}

.cat-item input {
  margin-top: 3px;
  accent-color: var(--primary);
  width: 15px;
  height: 15px;
}

.cat-text {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.cat-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-strong);
}

.cat-desc {
  font-size: 12px;
  color: #94a3b8;
}

.detail-field {
  position: relative;
}

.field-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-sub);
  margin-bottom: 6px;
}

.detail-field textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 13px;
  font-family: inherit;
  resize: vertical;
  outline: none;
  background: var(--surface-plain);
  color: var(--text-strong);
}

.detail-field textarea:focus {
  border-color: var(--primary);
}

.detail-count {
  position: absolute;
  right: 8px;
  bottom: 8px;
  font-size: 11px;
  color: #94a3b8;
  pointer-events: none;
}

.result-alert {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 10px;
  margin-bottom: 14px;
  font-size: 13px;
  line-height: 1.7;
}

.result-alert i {
  font-size: 18px;
  margin-top: 2px;
}

.result-alert span {
  display: block;
}

.result-alert--pending {
  background: color-mix(in srgb, var(--warning) 12%, transparent);
color: var(--warning-text);
  border: 1px solid #ffe2a8;
}

.result-alert--deleted {
  background: var(--bg-subtle);
  color: var(--text-sub);
  border: 1px solid #cbd5e1;
}

.result-alert--guilty {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
color: var(--danger-text);
  border: 1px solid #fbc4c4;
}

.result-alert--false {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
color: var(--danger-text);
  border: 1px solid #fbc4c4;
}

.action-row {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 4px;
}
</style>
