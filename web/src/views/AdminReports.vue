<script setup lang="ts">
/**
 * 秩序管理 · 举报审核页（/admin/reports）
 *
 * 能看到所有被举报内容 —— 包括已被 6 人以上举报自动删除的，
 * 内容以快照形式保留展示。
 *
 * 审核操作（仅秩序管理）：
 *   - 举报成立：删除（或保持删除）内容，不自动禁言作者；
 *   - 举报不成立：恢复此前被自动删除的内容，不自动禁言举报人。
 *   禁言需在用户管理页由管理员手动操作（1/7/14 天或永久）。
 */
import { onMounted, ref } from 'vue'
import Swal from 'sweetalert2'
import apiClient from '@/api/client'
import { renderRichText } from '@/utils/markdown'

const loading = ref(false)
const items = ref<any[]>([])
const total = ref(0)
const page = ref(0)
const pageSize = 20

const verdictFilter = ref<'pending' | 'guilty' | 'false_report' | 'all'>('pending')
const typeFilter = ref<'all' | 'benben' | 'post' | 'comment'>('all')

const VERDICT_TABS = [
  { value: 'pending', label: '待审核' },
  { value: 'guilty', label: '举报成立' },
  { value: 'false_report', label: '恶意举报' },
  { value: 'all', label: '全部' },
] as const

const TYPE_TABS = [
  { value: 'all', label: '全部类型' },
  { value: 'benben', label: '犇犇' },
  { value: 'post', label: '帖子' },
  { value: 'comment', label: '帖子回复' },
] as const

const REASON_NAMES: Record<string, string> = {
  multi_report: '多人举报自动删除',
  moderator: '秩序管理员删除',
  self: '作者自行删除',
  report_guilty: '举报成立后删除',
}

const fmtTime = (iso: string | null) => {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-CN')
}

const renderContent = (text: string) => renderRichText(text || '')

async function load(resetPage = false) {
  if (loading.value) return
  if (resetPage) page.value = 0
  loading.value = true
  try {
    const data: any = await apiClient.get('/api/reports/admin', {
      params: {
        verdict: verdictFilter.value,
        target_type: typeFilter.value,
        page: page.value,
        page_size: pageSize,
      },
    })
    items.value = data.items || []
    total.value = data.total || 0
  } catch (err: any) {
    Swal.fire({ icon: 'error', title: '加载失败', text: err.response?.data?.detail || err.message })
  } finally {
    loading.value = false
  }
}

function switchVerdict(v: typeof verdictFilter.value) {
  if (verdictFilter.value === v) return
  verdictFilter.value = v
  void load(true)
}

function switchType(v: typeof typeFilter.value) {
  if (typeFilter.value === v) return
  typeFilter.value = v
  void load(true)
}

function goPage(delta: number) {
  const maxPage = Math.max(0, Math.ceil(total.value / pageSize) - 1)
  const next = Math.min(maxPage, Math.max(0, page.value + delta))
  if (next === page.value) return
  page.value = next
  void load()
}

/** 审核：guilty 举报成立 / false_report 恶意举报 */
async function review(item: any, verdict: 'guilty' | 'false_report') {
  const target = item.target
  const activeReporters = (item.reports || []).filter((r: any) => r.status === 'active')

  let html = ''
  let confirmText = ''
  if (verdict === 'guilty') {
    const deleted = target?.is_deleted
    confirmText = '举报成立，删除内容'
    html = `
      <div style="text-align:left;line-height:1.9;font-size:14px">
        <div>· 内容：<b>${deleted ? '保持删除状态' : '立即删除'}</b></div>
        <div>· 作者：<b>不自动禁言</b>，如需处罚请在用户管理页手动操作</div>
      </div>`
  } else {
    confirmText = '举报不成立，恢复内容'
    const willRestore = target?.is_deleted && target.delete_reason !== 'self'
    html = `
      <div style="text-align:left;line-height:1.9;font-size:14px">
        <div>· 内容：<b>${willRestore ? '恢复公开显示' : '保持现状'}</b></div>
        <div>· 举报人：<b>不自动禁言</b>，共 <b>${activeReporters.length}</b> 位有效举报人</div>
      </div>`
  }

  const result = await Swal.fire({
    title: verdict === 'guilty' ? '确认举报成立？' : '确认举报不成立（恶意举报）？',
    html,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonText: confirmText,
    cancelButtonText: '取消',
    confirmButtonColor: verdict === 'guilty' ? '#e74c3c' : '#d97706',
    cancelButtonColor: '#909399',
    width: 560,
  })
  if (!result.isConfirmed) return

  try {
    await apiClient.post(
      `/api/reports/admin/${item.target_type}/${item.target_id}/verdict`,
      { verdict }
    )
    await Swal.fire({
      icon: 'success',
      title: verdict === 'guilty' ? '已按举报成立处理' : '已按恶意举报处理',
      timer: 1500,
      showConfirmButton: false,
    })
    await load()
  } catch (err: any) {
    Swal.fire({
      icon: 'error',
      title: '操作失败',
      text: err.response?.data?.detail || err.message,
    })
  }
}

onMounted(() => void load(true))
</script>

<template>
  <div class="reports-page">
    <div class="reports-container">
      <div class="page-head">
        <h1 class="page-title"><i class="fa-solid fa-flag"></i> 举报审核</h1>
        <p class="page-sub">仅秩序管理员可审核。有效举报达到 6 人的内容会被系统自动删除，删除后内容仍在此保留备查。</p>
      </div>

      <!-- 筛选 -->
      <div class="filters card-box">
        <div class="filter-group">
          <button
            v-for="t in VERDICT_TABS"
            :key="t.value"
            class="filter-chip"
            :class="{ active: verdictFilter === t.value }"
            @click="switchVerdict(t.value)"
          >{{ t.label }}</button>
        </div>
        <div class="filter-divider"></div>
        <div class="filter-group">
          <button
            v-for="t in TYPE_TABS"
            :key="t.value"
            class="filter-chip small"
            :class="{ active: typeFilter === t.value }"
            @click="switchType(t.value)"
          >{{ t.label }}</button>
        </div>
      </div>

      <div v-if="loading && items.length === 0" class="state-box">
        <span class="loading-spinner"></span> 加载中…
      </div>
      <div v-else-if="items.length === 0" class="state-box">
        <i class="fa-regular fa-circle-check" style="color:#52b788;font-size:22px"></i>
        <div>当前筛选下没有举报记录</div>
      </div>

      <!-- 举报卡片 -->
      <div v-else class="report-cards">
        <div v-for="item in items" :key="`${item.target_type}-${item.target_id}`" class="report-card card-box">
          <!-- 卡片头 -->
          <div class="card-top">
            <span class="type-badge" :class="item.target_type">{{ item.target_name }} #{{ item.target_id }}</span>
            <span v-if="item.verdict === 'guilty'" class="verdict-badge guilty">举报成立</span>
            <span v-else-if="item.verdict === 'false_report'" class="verdict-badge false">恶意举报</span>
            <span v-else class="verdict-badge pending">待审核</span>
            <span class="count-info">
              有效举报 <b>{{ item.active_count }}</b> / {{ item.total_count }} 人
            </span>
            <span class="last-time">最近举报：{{ fmtTime(item.last_at) }}</span>
          </div>

          <div class="card-main">
            <!-- 内容快照 -->
            <div class="snapshot">
              <div v-if="!item.target" class="snapshot-missing">
                <i class="fa-solid fa-question"></i> 目标内容不存在（可能已从数据库移除）
              </div>
              <template v-else>
                <div v-if="item.target.is_deleted" class="deleted-strip">
                  <i class="fa-solid fa-ban"></i>
                  该内容已删除：{{ REASON_NAMES[item.target.delete_reason || ''] || item.target.delete_reason }}
                  <span v-if="item.target.deleted_at">· {{ fmtTime(item.target.deleted_at) }}</span>
                </div>

                <!-- 帖子标题 -->
                <div v-if="item.target.kind === 'post'" class="snap-title">
                  {{ item.target.title }}
                  <span class="snap-forum">{{ item.target.forum }}</span>
                </div>
                <div v-else-if="item.target.kind === 'comment'" class="snap-title comment-title">
                  回复于帖子：{{ item.target.post_title || `#${item.target.post_id}` }}
                  <router-link class="goto-link" :to="`/discuss/${item.target.post_id}`">前往查看 →</router-link>
                </div>

                <div class="snap-body prose" v-html="renderContent(item.target.content)"></div>

                <div class="snap-author">
                  <img
                    v-if="item.target.author?.avatar_url"
                    :src="item.target.author.avatar_url"
                    class="snap-avatar"
                  >
                  <router-link
                    v-if="item.target.author"
                    :to="`/user/${item.target.author.user_number}`"
                    class="snap-name"
                  >{{ item.target.author.username }}</router-link>
                  <span class="snap-time">{{ fmtTime(item.target.created_at) }}</span>
                </div>
              </template>
            </div>

            <!-- 举报明细 -->
            <div class="reporters">
              <div class="reporters-title">举报明细（{{ item.reports.length }}）</div>
              <div
                v-for="r in item.reports"
                :key="r.id"
                class="reporter-row"
                :class="{ revoked: r.status === 'revoked' }"
              >
                <img v-if="r.reporter.avatar_url" :src="r.reporter.avatar_url" class="reporter-avatar">
                <router-link :to="`/user/${r.reporter.user_number}`" class="reporter-name">
                  {{ r.reporter.username }}
                </router-link>
                <span class="reporter-cat">{{ r.category_name }}</span>
                <span v-if="r.detail" class="reporter-detail">“{{ r.detail }}”</span>
                <span v-if="r.status === 'revoked'" class="revoked-tag">已撤销</span>
                <span class="reporter-time">{{ fmtTime(r.created_at) }}</span>
              </div>
            </div>
          </div>

          <!-- 待审核操作 -->
          <div v-if="!item.verdict" class="card-actions">
            <button class="action-btn false-btn" @click="review(item, 'false_report')">
              <i class="fa-solid fa-rotate-left"></i> 举报不成立（恢复内容）
            </button>
            <button class="action-btn guilty-btn" @click="review(item, 'guilty')">
              <i class="fa-solid fa-gavel"></i> 举报成立（删除内容）
            </button>
          </div>
        </div>
      </div>

      <!-- 分页 -->
      <div v-if="total > pageSize" class="pagination">
        <button class="page-btn" :disabled="page === 0" @click="goPage(-1)">上一页</button>
        <span class="page-info">{{ page + 1 }} / {{ Math.max(1, Math.ceil(total / pageSize)) }}</span>
        <button
          class="page-btn"
          :disabled="page >= Math.ceil(total / pageSize) - 1"
          @click="goPage(1)"
        >下一页</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.reports-page {
  min-height: 100vh;
  padding: 24px 16px 60px;
}

.reports-container {
  max-width: 1000px;
  margin: 0 auto;
}

.page-head {
  margin-bottom: 18px;
}

.page-title {
  font-size: 24px;
  font-weight: 800;
  color: var(--text-strong);
  margin: 0 0 6px;
}

.page-sub {
  font-size: 13px;
  color: var(--text-sub);
  margin: 0;
}

.card-box {
  background: var(--surface, #fff);
  border: var(--border-width, 1px) solid var(--border-color, #e8ecf1);
  border-radius: 14px;
  box-shadow: 0 2px 12px rgba(30, 50, 80, 0.06);
}

/* 筛选 */
.filters {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.filter-group {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.filter-divider {
  width: 1px;
  height: 22px;
  background: var(--bg-subtle);
}

.filter-chip {
  padding: 6px 16px;
  border: 1px solid #e2e8f0;
  background: var(--surface-plain);
  border-radius: 999px;
  font-size: 13px;
  color: var(--text-sub);
  cursor: pointer;
  transition: all 0.15s;
}

.filter-chip.small {
  font-size: 12px;
  padding: 5px 12px;
}

.filter-chip:hover {
  border-color: #b8c4d0;
  color: var(--text-strong);
}

.filter-chip.active {
  background: var(--primary, #e74c3c);
  border-color: var(--primary, #e74c3c);
  color: #fff;
  font-weight: 600;
}

.state-box {
  background: var(--surface, #fff);
  border-radius: 14px;
  text-align: center;
  padding: 60px 20px;
  color: #94a3b8;
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: center;
}

/* 卡片 */
.report-cards {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.report-card {
  padding: 16px 18px;
}

.card-top {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding-bottom: 12px;
  border-bottom: 1px solid #f0f3f7;
}

.type-badge {
  font-size: 13px;
  font-weight: 700;
  padding: 3px 12px;
  border-radius: 6px;
  color: #fff;
  background: #64748b;
}

.type-badge.benben { background: #8b5cf6; }
.type-badge.post { background: #3b82f6; }
.type-badge.comment { background: #0ea5e9; }

.verdict-badge {
  font-size: 12px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 6px;
}

.verdict-badge.pending { background: color-mix(in srgb, var(--warning) 12%, transparent);color: var(--warning-text); }
.verdict-badge.guilty { background: color-mix(in srgb, var(--danger) 10%, transparent);color: var(--danger-text); }
.verdict-badge.false { background: color-mix(in srgb, var(--warning) 12%, transparent);color: var(--warning-text); }

.count-info {
  font-size: 13px;
  color: var(--text-sub);
}

.last-time {
  margin-left: auto;
  font-size: 12px;
  color: #a0aec0;
}

.card-main {
  display: grid;
  grid-template-columns: 1fr 260px;
  gap: 16px;
  padding: 14px 0;
}

@media (max-width: 820px) {
  .card-main {
    grid-template-columns: 1fr;
  }
}

/* 内容快照 */
.snapshot {
  border: 1px solid #eef1f5;
  border-radius: 10px;
  padding: 12px 14px;
  min-width: 0;
}

.snapshot-missing {
  color: #94a3b8;
  font-size: 13px;
  padding: 16px 0;
  text-align: center;
}

.deleted-strip {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border: 1px solid #fecaca;
color: var(--danger-text);
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 6px;
  margin-bottom: 10px;
}

.snap-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-strong);
  margin-bottom: 8px;
  word-break: break-word;
}

.snap-forum {
  font-size: 11px;
  font-weight: 500;
  color: #94a3b8;
  background: var(--bg-subtle);
  padding: 2px 8px;
  border-radius: 4px;
  margin-left: 8px;
  vertical-align: middle;
}

.comment-title {
  font-size: 13px;
}

.goto-link {
  font-size: 12px;
  color: var(--primary, #e74c3c);
  margin-left: 8px;
  font-weight: 600;
  text-decoration: none;
}

.snap-body {
  font-size: 13px;
  color: var(--text-strong);
  max-height: 280px;
  overflow-y: auto;
  margin-bottom: 10px;
}

.snap-author {
  display: flex;
  align-items: center;
  gap: 8px;
  border-top: 1px solid #f4f6f9;
  padding-top: 8px;
}

.snap-avatar,
.reporter-avatar {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  object-fit: cover;
}

.snap-name,
.reporter-name {
  font-size: 13px;
  font-weight: 600;
  color: #3b82f6;
  text-decoration: none;
}

.snap-time,
.reporter-time {
  font-size: 11px;
  color: #a0aec0;
  margin-left: auto;
}

/* 举报明细 */
.reporters-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-sub);
  margin-bottom: 8px;
}

.reporter-row {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 8px;
  border-radius: 8px;
  flex-wrap: wrap;
}

.reporter-row:nth-child(odd) {
  background: var(--surface-plain);
}

.reporter-cat {
  font-size: 11px;
  color: var(--text-sub);
  background: var(--bg-subtle);
  padding: 1px 8px;
  border-radius: 4px;
}

.reporter-detail {
  font-size: 11px;
  color: #94a3b8;
  font-style: italic;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.revoked-tag {
  font-size: 11px;
  color: #b8c4d0;
}

.reporter-row.revoked {
  opacity: 0.55;
}

/* 操作按钮 */
.card-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 12px;
  border-top: 1px solid #f0f3f7;
  flex-wrap: wrap;
}

.action-btn {
  padding: 9px 18px;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.15s;
}

.guilty-btn {
  background: #e74c3c;
  color: #fff;
}

.guilty-btn:hover {
  background: #d63c2d;
}

.false-btn {
  background: var(--surface-plain);
color: light-dark(#d97706, #fbbf24);
  border-color: #f5cf7a;
}

.false-btn:hover {
  background: color-mix(in srgb, var(--warning) 12%, transparent);
}

/* 分页 */
.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16px;
  margin-top: 22px;
}

.page-btn {
  padding: 7px 20px;
  border: 1px solid #e2e8f0;
  background: var(--surface-plain);
  border-radius: 8px;
  font-size: 13px;
  color: var(--text-sub);
  cursor: pointer;
}

.page-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.page-info {
  font-size: 13px;
  color: var(--text-sub);
}
</style>
