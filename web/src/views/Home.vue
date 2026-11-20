<script setup lang="ts">
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
import HomeCloud from './HomeCloud.vue'
import HomeLuogu from './HomeLuogu.vue'

// 主题商店「洛谷风格主页」开关的分发点：
//   cloud（默认）= 新版云图首页（HomeCloud）
//   luogu        = 经典卡片首页（HomeLuogu，云图改版前的原样布局）
// 账号级偏好 users.home_style 随 /auth/me 下发，主题商店里切换后即时生效；
// 游客没有账号偏好，默认看云图首页。
const authStore = useAuthStore()
const homeStyle = computed(() => authStore.currentUser?.home_style || 'cloud')
</script>

<template>
  <HomeLuogu v-if="homeStyle === 'luogu'" />
  <HomeCloud v-else />
</template>
