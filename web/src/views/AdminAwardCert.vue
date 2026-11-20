<script setup lang="ts">
/**
 * 奖项认证审核（独立页面，齿轮菜单进入）：
 * 列出所有 award_cert_status = pending 的用户，通过（需填写 OI 等级）或驳回。
 * 后端：GET /api/admin/award-certifications、POST /api/admin/users/{n}/award-certification/review。
 */
import { onMounted, ref } from 'vue'
import Swal from 'sweetalert2'
import apiClient from '@/api/client'

interface PendingCert {
  user_number: number
  username: string
  real_name: string | null
  oierdb_uid: string | null
  oi_awards: any[] | string | null
}

const items = ref<PendingCert[]>([])
const loading = ref(true)
const acting = ref<number | null>(null)

async function load() {
  loading.value = true
  try {
    // apiClient 响应拦截器已解包 response.data，此处 res 即 {items: [...]}
    const res: any = await apiClient.get('/api/admin/award-certifications')
    items.value = res?.items || []
  } catch (e: any) {
    Swal.fire('加载失败', e?.response?.data?.detail || '请重试', 'error')
  } finally {
    loading.value = false
  }
}

/** oi_awards 元素可能是对象（contest/name + award/prize）或纯字符串 */
function awardText(a: any): string {
  if (typeof a === 'string') return a
  return [a?.contest || a?.name, a?.award || a?.prize].filter(Boolean).join(' · ')
}

async function review(c: PendingCert, action: 'approve' | 'reject', oiLevel?: string) {
  acting.value = c.user_number
  try {
    await apiClient.post(`/api/admin/users/${c.user_number}/award-certification/review`, {
      action,
      oi_level: oiLevel || undefined,
    })
    items.value = items.value.filter((x) => x.user_number !== c.user_number)
    Swal.fire({
      toast: true, position: 'top', icon: 'success',
      title: action === 'approve' ? '已通过认证' : '已驳回认证',
      showConfirmButton: false, timer: 1500,
    })
  } catch (e: any) {
    Swal.fire('操作失败', e?.response?.data?.detail || '请重试', 'error')
  } finally {
    acting.value = null
  }
}

async function approve(c: PendingCert) {
  const { value, isConfirmed } = await Swal.fire({
    title: `通过 ${c.username} 的奖项认证？`,
    input: 'textarea',
    inputLabel: 'OI 等级（如：NOI 金牌、NOIP 一等奖）',
    inputPlaceholder: 'NOI 金牌',
    inputValidator: (v) => (v && v.trim() ? undefined : '请填写 OI 等级'),
    showCancelButton: true,
    confirmButtonText: '通过认证',
    cancelButtonText: '取消',
  })
  if (isConfirmed) await review(c, 'approve', String(value ?? '').trim())
}

async function reject(c: PendingCert) {
  const { isConfirmed } = await Swal.fire({
    title: `驳回 ${c.username} 的奖项认证？`,
    text: '对方可修改资料后重新申请。',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonText: '驳回',
    cancelButtonText: '取消',
  })
  if (isConfirmed) await review(c, 'reject')
}

onMounted(load)
</script>

<template>
  <div class="award-cert-page">
    <div class="card">
      <div class="card-header-row">
        <div class="card-header">奖项认证待审核</div>
        <button
          type="button"
          class="refresh-btn"
          :disabled="loading"
          title="刷新列表"
          @click="load"
        >
          <i class="fa-solid" :class="loading ? 'fa-circle-notch fa-spin' : 'fa-rotate'"></i> 刷新
        </button>
      </div>

      <div v-if="loading" class="empty">加载中...</div>
      <div v-else-if="!items.length" class="empty">
        <i class="fa-solid fa-circle-check"></i> 暂无待审核的申请
      </div>

      <div v-else class="cert-list">
        <div v-for="c in items" :key="c.user_number" class="cert-item">
          <div class="cert-info">
            <div class="cert-title">
              <strong>{{ c.username }}</strong>
              <span class="cert-uid">UID {{ c.user_number }}</span>
              <span v-if="c.real_name" class="cert-real">实名：{{ c.real_name }}</span>
            </div>
            <div v-if="c.oierdb_uid" class="cert-meta">oierdb：{{ c.oierdb_uid }}</div>
            <div v-if="Array.isArray(c.oi_awards) && c.oi_awards.length" class="cert-awards">
              <span v-for="(a, i) in c.oi_awards" :key="i" class="award-chip">
                {{ awardText(a) }}
              </span>
            </div>
          </div>
          <div class="cert-actions">
            <button
              type="button"
              class="act approve"
              :disabled="acting !== null"
              @click="approve(c)"
            >
              <i class="fa-solid fa-check"></i> 通过
            </button>
            <button
              type="button"
              class="act reject"
              :disabled="acting !== null"
              @click="reject(c)"
            >
              <i class="fa-solid fa-xmark"></i> 驳回
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.award-cert-page {
  max-width: 1000px;
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
}

.card-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}

.card-header {
  font-size: 1.25rem;
  font-weight: 600;
  border-left: 4px solid var(--primary);
  padding-left: 12px;
  margin-bottom: 0;
}

.refresh-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 7px 16px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm, 6px);
  background: transparent;
  color: var(--text-secondary, #666);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.refresh-btn:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
}

.refresh-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}

.empty {
  text-align: center;
  padding: 44px 0;
  color: var(--text-secondary, #888);
  font-size: 15px;
}

.empty i {
  margin-right: 8px;
  color: var(--success);
}

.cert-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.cert-item {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 14px 16px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm, 6px);
}

.cert-info {
  min-width: 0;
}

.cert-title {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 10px;
  font-size: 15px;
}

.cert-uid {
  color: var(--text-secondary, #888);
  font-size: 13px;
}

.cert-real {
  color: var(--text-secondary, #666);
  font-size: 13px;
}

.cert-meta {
  margin-top: 4px;
  color: var(--text-secondary, #888);
  font-size: 13px;
}

.cert-awards {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.award-chip {
  padding: 2px 10px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--primary) 10%, transparent);
  color: var(--primary);
  font-size: 12.5px;
}

.cert-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.act {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 16px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm, 6px);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.act:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.act.approve {
  background: var(--success);
  color: #fff;
}

.act.approve:hover:not(:disabled) {
  filter: brightness(0.92);
}

.act.reject {
  background: transparent;
  border-color: var(--danger);
  color: var(--danger);
}

.act.reject:hover:not(:disabled) {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
}

@media (max-width: 600px) {
  .card {
    padding: 16px 14px;
  }

  .cert-item {
    flex-direction: column;
  }

  .cert-actions {
    width: 100%;
  }

  .act {
    flex: 1;
    justify-content: center;
  }
}
</style>
