<script setup lang="ts">
/**
 * 顶栏中央「管理组公告」垂直轮播位。
 *
 * 数据来自公开接口 GET /api/site-settings/announcement（站点管理里配置）。
 * 未启用 / 拉取失败 → 整个组件不渲染、不占位，顶栏布局不受影响。
 * 多条公告每隔数秒上下滑动切换；点击当前条跳转其链接（无链接则只是提示不可点）。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import apiClient from '@/api/client'
import type { AnnouncementItem } from '@/types'

const router = useRouter()

const items = ref<AnnouncementItem[]>([])
const enabled = ref(false)
const index = ref(0)
let timer: number | null = null

const hasNotice = computed(() => enabled.value && items.value.length > 0)
const currentItem = computed(() => items.value[index.value])
const clickable = computed(() => !!currentItem.value?.link)

const load = async () => {
  try {
    const data: any = await apiClient.get('/api/site-settings/announcement')
    enabled.value = !!data?.enabled
    items.value = Array.isArray(data?.items)
      ? data.items.filter((it: any) => it && it.text)
      : []
  } catch {
    // 公告是锦上添花：拉不到就不占位，静默失败
    enabled.value = false
    items.value = []
  }
  if (items.value.length > 1 && !timer) {
    timer = window.setInterval(() => {
      index.value = (index.value + 1) % items.value.length
    }, 4500)
  }
}

const onItemClick = () => {
  const link = currentItem.value?.link
  if (!link) return
  if (/^https?:\/\//.test(link)) {
    window.open(link, '_blank', 'noopener,noreferrer')
    return
  }
  router.push(link)
}

onMounted(load)
onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div
    v-if="hasNotice"
    class="top-notice"
    :class="{ clickable }"
    :title="clickable ? (currentItem?.link ?? undefined) : undefined"
    @click="onItemClick"
  >
    <i class="fa-solid fa-bullhorn top-notice-icon"></i>
    <div class="notice-viewport">
      <!-- 轨道按「一条公告」的固定高度 20px 位移：
           早先写 -index*100% 是按整条轨道（n 条）算的，切一条就跳过头了 -->
      <div class="notice-track" :style="{ transform: `translateY(calc(-${index} * 20px))` }">
        <div v-for="(it, i) in items" :key="i" class="notice-item">{{ it.text }}</div>
      </div>
    </div>
    <!-- 单条以上才画指示点，点了直接切 -->
    <span v-if="items.length > 1" class="notice-dots">
      <i
        v-for="(_, i) in items"
        :key="i"
        class="notice-dot"
        :class="{ active: i === index }"
        @click.stop="index = i"
      ></i>
    </span>
  </div>
</template>

<style scoped>
/* 居中位：flex:1 吃掉 logo 与右侧按钮之间的空间，内容自身居中 */
.top-notice {
  flex: 1;
  min-width: 0;
  max-width: 520px;
  margin: 0 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 5px 12px;
  border: 1px solid color-mix(in srgb, var(--primary) 22%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--primary) 7%, transparent);
  color: var(--text-sub);
  font-size: 13px;
  cursor: default;
  transition: border-color 0.15s, background 0.15s;
}

.top-notice.clickable {
  cursor: pointer;
}

.top-notice.clickable:hover {
  border-color: color-mix(in srgb, var(--primary) 45%, transparent);
  background: color-mix(in srgb, var(--primary) 12%, transparent);
}

.top-notice-icon {
  flex: none;
  color: var(--primary);
  font-size: 12px;
}

/* 垂直轮播视口：一行高度，轨道整体上下滑动 */
.notice-viewport {
  flex: 1;
  min-width: 0;
  height: 20px;
  overflow: hidden;
}

.notice-track {
  display: flex;
  flex-direction: column;
  transition: transform 0.45s ease;
}

.notice-item {
  flex: none;
  height: 20px;
  line-height: 20px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--text-strong);
  font-weight: 600;
}

.notice-dots {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.notice-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--primary) 30%, transparent);
  cursor: pointer;
  transition: background 0.15s, transform 0.15s;
}

.notice-dot.active {
  background: var(--primary);
  transform: scale(1.25);
}

/* ≤900px：顶栏改两行，公告占满第二行（配合 TopBar 的 flex-wrap + order）。
   早先这里直接 display:none，移动端公告整条消失。 */
@media (max-width: 900px) {
  .top-notice {
    order: 3;
    flex: 1 0 100%;
    max-width: none;
    margin: 6px 0 0;
    padding: 5px 10px;
  }
}
</style>
