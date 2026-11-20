<script setup lang="ts">
/**
 * 团队封禁管理（用户管理权限可见）：
 * 列出全部团队，展示封禁状态与成员数，支持封禁/解封。
 * 后端：GET /api/admin/teams、PATCH /api/admin/teams/{id}/ban。
 */
import { onMounted, ref } from 'vue'
import Swal from 'sweetalert2'
import apiClient from '@/api/client'

interface AdminTeam {
  id: number
  name: string
  description: string
  owner_id: number
  owner_username: string
  owner_user_number: number | null
  member_count: number
  is_banned: boolean
  created_at: string | null
}

const items = ref<AdminTeam[]>([])
const loading = ref(true)
const acting = ref<number | null>(null)
const search = ref('')

async function load() {
  loading.value = true
  try {
    // apiClient 响应拦截器已解包 response.data，此处 res 即 {items: [...]}
    const res: any = await apiClient.get('/api/admin/teams', {
      params: { search: search.value.trim() || undefined, limit: 200 },
    })
    items.value = res?.items || []
  } catch (e: any) {
    Swal.fire('加载失败', e?.response?.data?.detail || '请重试', 'error')
  } finally {
    loading.value = false
  }
}

async function toggleBan(t: AdminTeam) {
  const willBan = !t.is_banned
  const { isConfirmed } = await Swal.fire({
    title: willBan ? `封禁团队「${t.name}」？` : `解封团队「${t.name}」？`,
    text: willBan
      ? '封禁后该团队将无法发帖、加人、创建题目等操作。'
      : '解封后该团队恢复正常操作。',
    icon: willBan ? 'warning' : 'question',
    showCancelButton: true,
    confirmButtonText: willBan ? '封禁' : '解封',
    cancelButtonText: '取消',
  })
  if (!isConfirmed) return

  acting.value = t.id
  try {
    const res: any = await apiClient.patch(`/api/admin/teams/${t.id}/ban`, {
      is_banned: willBan,
    })
    t.is_banned = !!res?.is_banned
    Swal.fire({
      toast: true, position: 'top', icon: 'success',
      title: willBan ? '已封禁团队' : '已解封团队',
      showConfirmButton: false, timer: 1500,
    })
  } catch (e: any) {
    Swal.fire('操作失败', e?.response?.data?.detail || '请重试', 'error')
  } finally {
    acting.value = null
  }
}

function onSearch() {
  load()
}

onMounted(load)
</script>

<template>
  <div class="team-ban-page">
    <div class="card">
      <div class="card-header-row">
        <div class="card-header">团队封禁管理</div>
        <div class="header-tools">
          <div class="search-wrap">
            <i class="fa-solid fa-magnifying-glass"></i>
            <input
              v-model="search"
              type="text"
              placeholder="搜索团队名称"
              @keyup.enter="onSearch"
            />
          </div>
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
      </div>

      <div v-if="loading" class="empty">加载中...</div>
      <div v-else-if="!items.length" class="empty">
        <i class="fa-solid fa-people-group"></i> 暂无团队
      </div>

      <div v-else class="team-list">
        <div
          v-for="t in items"
          :key="t.id"
          class="team-item"
          :class="{ banned: t.is_banned }"
        >
          <div class="team-info">
            <div class="team-title">
              <strong>{{ t.name }}</strong>
              <span class="team-id">ID {{ t.id }}</span>
              <span v-if="t.is_banned" class="ban-tag">
                <i class="fa-solid fa-ban"></i> 已封禁
              </span>
            </div>
            <div v-if="t.description" class="team-desc">{{ t.description }}</div>
            <div class="team-meta">
              团主：{{ t.owner_username }}
              <span v-if="t.owner_user_number !== null">（UID {{ t.owner_user_number }}）</span>
              · 成员 {{ t.member_count }} 人
            </div>
          </div>
          <div class="team-actions">
            <button
              type="button"
              class="act"
              :class="t.is_banned ? 'unban' : 'ban'"
              :disabled="acting !== null"
              @click="toggleBan(t)"
            >
              <i class="fa-solid" :class="t.is_banned ? 'fa-unlock' : 'fa-ban'"></i>
              {{ t.is_banned ? '解封' : '封禁' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.team-ban-page {
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
  flex-wrap: wrap;
}

.card-header {
  font-size: 1.25rem;
  font-weight: 600;
  border-left: 4px solid var(--primary);
  padding-left: 12px;
}

.header-tools {
  display: flex;
  align-items: center;
  gap: 10px;
}

.search-wrap {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm, 6px);
  color: var(--text-secondary, #888);
}

.search-wrap input {
  border: 0;
  background: transparent;
  outline: none;
  color: var(--text-primary, inherit);
  font-size: 14px;
  width: 160px;
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
  color: var(--primary);
}

.team-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.team-item {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 14px 16px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm, 6px);
}

.team-item.banned {
  border-color: color-mix(in srgb, var(--danger) 45%, var(--border-color));
  background: color-mix(in srgb, var(--danger) 5%, transparent);
}

.team-info {
  min-width: 0;
}

.team-title {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 10px;
  font-size: 15px;
}

.team-id {
  color: var(--text-secondary, #888);
  font-size: 13px;
}

.ban-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 8px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--danger) 12%, transparent);
  color: var(--danger);
  font-size: 12px;
}

.team-desc {
  margin-top: 5px;
  color: var(--text-secondary, #666);
  font-size: 13.5px;
}

.team-meta {
  margin-top: 5px;
  color: var(--text-secondary, #888);
  font-size: 13px;
}

.team-actions {
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

.act.ban {
  background: var(--danger);
  color: #fff;
}

.act.ban:hover:not(:disabled) {
  filter: brightness(0.92);
}

.act.unban {
  background: transparent;
  border-color: var(--success);
  color: var(--success);
}

.act.unban:hover:not(:disabled) {
  background: color-mix(in srgb, var(--success) 10%, transparent);
}

@media (max-width: 600px) {
  .card {
    padding: 16px 14px;
  }

  .team-item {
    flex-direction: column;
  }

  .team-actions {
    width: 100%;
  }

  .act {
    width: 100%;
    justify-content: center;
  }
}
</style>
