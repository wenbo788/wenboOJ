<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import apiClient from '@/api/client'

const authStore = useAuthStore()
const me = computed(() => authStore.currentUser)

// 内置渐变预设（key 与后端 _ALLOWED_THEME_PRESETS 一致）
const PRESETS: Record<string, { name: string; css: string }> = {
  dawn: { name: '晨曦', css: 'linear-gradient(135deg, #ffd8a8 0%, #ff9db8 50%, #a8c8ff 100%)' },
  ocean: { name: '深海', css: 'linear-gradient(160deg, #0f3057 0%, #00587a 55%, #008891 100%)' },
  dusk: { name: '暮色', css: 'linear-gradient(160deg, #2b1b4d 0%, #7a3b8f 55%, #ff7e5f 100%)' },
  sakura: { name: '樱色', css: 'linear-gradient(150deg, #ffe3ec 0%, #ffc7de 55%, #ffd8b1 100%)' },
}

const enabled = computed(() => !!me.value?.theme_enabled)
const currentBg = computed(() => me.value?.theme_background || '')

const isPreset = (bg: string) => bg.startsWith('preset:')
const presetKey = (bg: string) => bg.split(':')[1] || ''
const presetCss = (bg: string) => PRESETS[presetKey(bg)]?.css || ''

// 自定义背景 URL（从完整字符串中解析）
const customUrl = computed(() =>
  currentBg.value && !isPreset(currentBg.value) ? currentBg.value : '',
)

const selectedPreset = computed(() =>
  isPreset(currentBg.value) ? presetKey(currentBg.value) : null,
)

// 预览样式：纯展示，不叠加暗遮罩
const previewStyle = computed(() => {
  const bg = currentBg.value
  if (!bg) return {}
  if (isPreset(bg)) {
    return { backgroundImage: presetCss(bg) }
  }
  return {
    backgroundImage: `url(${bg})`,
    backgroundSize: 'cover',
    backgroundPosition: 'center',
  }
})

const acting = ref(false)
const msg = ref('')

const customUrlInput = ref('')

// ===== 深色主题开关 =====
const isDark = computed(() => me.value?.theme_mode === 'dark')

const toggleDark = async () => {
  const me = authStore.currentUser
  if (!me || acting.value) return
  const next = isDark.value ? 'light' : 'dark'
  const prev = me.theme_mode
  me.theme_mode = next // 乐观更新：App.vue 的 watch 立即切 <html data-theme>
  acting.value = true
  msg.value = ''
  try {
    await apiClient.put('/api/users/me/theme', { mode: next })
  } catch (err: any) {
    me.theme_mode = prev
    msg.value = formatError(err, '切换失败')
  } finally {
    acting.value = false
  }
}

// ===== 洛谷风格主页开关 =====
const isLuogu = computed(() => me.value?.home_style === 'luogu')

const toggleHomeStyle = async () => {
  const me = authStore.currentUser
  if (!me || acting.value) return
  const next = isLuogu.value ? 'cloud' : 'luogu'
  const prev = me.home_style
  me.home_style = next // 乐观更新：回首页时 Home.vue 的 computed 立即换布局
  acting.value = true
  msg.value = ''
  try {
    await apiClient.put('/api/users/me/theme', { home_style: next })
  } catch (err: any) {
    me.home_style = prev
    msg.value = formatError(err, '切换失败')
  } finally {
    acting.value = false
  }
}

// FastAPI 校验错误（422）的 detail 是数组，拼成人话
const formatError = (err: any, fallback: string) => {
  const d = err?.response?.data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map((x: any) => x.msg || '').join('；') || fallback
  return fallback
}

// 乐观更新：先改本地状态立即生效（背景切换不等网络往返），失败再回滚。
const patchLocal = (bg: string | null, on: boolean | null) => {
  const me = authStore.currentUser
  if (!me) return false
  me.theme_background = bg
  if (on !== null) me.theme_enabled = on
  return true
}

const applyPreset = async (key: string) => {
  const me = authStore.currentUser
  if (!me) return
  const prev = { bg: me.theme_background, on: me.theme_enabled }
  patchLocal(`preset:${key}`, true)
  acting.value = true
  msg.value = ''
  try {
    await apiClient.put('/api/users/me/theme', { background: `preset:${key}` })
  } catch (err: any) {
    me.theme_background = prev.bg
    me.theme_enabled = prev.on
    msg.value = formatError(err, '设置失败')
  } finally {
    acting.value = false
  }
}

const applyCustomUrl = async () => {
  const url = customUrlInput.value.trim()
  if (!url) return
  const me = authStore.currentUser
  if (!me) return
  const prev = { bg: me.theme_background, on: me.theme_enabled }
  patchLocal(url, true)
  acting.value = true
  msg.value = ''
  try {
    await apiClient.put('/api/users/me/theme', { background: url })
    msg.value = '背景已应用'
  } catch (err: any) {
    me.theme_background = prev.bg
    me.theme_enabled = prev.on
    msg.value = formatError(err, '应用失败')
  } finally {
    acting.value = false
  }
}

const toggleEnabled = async () => {
  const me = authStore.currentUser
  if (!me) return
  const prev = me.theme_enabled
  me.theme_enabled = !prev
  acting.value = true
  msg.value = ''
  try {
    await apiClient.put('/api/users/me/theme', { enabled: !prev })
    msg.value = prev ? '主题已停用' : '主题已启用'
  } catch (err: any) {
    me.theme_enabled = prev
    msg.value = formatError(err, '操作失败')
  } finally {
    acting.value = false
  }
}

const resetTheme = async () => {
  const me = authStore.currentUser
  if (!me) return
  const prev = { bg: me.theme_background, on: me.theme_enabled }
  patchLocal(null, false)
  customUrlInput.value = ''
  acting.value = true
  msg.value = ''
  try {
    await apiClient.put('/api/users/me/theme', { background: null })
    msg.value = '已恢复默认主题'
  } catch (err: any) {
    me.theme_background = prev.bg
    me.theme_enabled = prev.on
    msg.value = formatError(err, '操作失败')
  } finally {
    acting.value = false
  }
}

// ===== 色相调整 =====
// -180..180（0 = 默认配色）。拖动 input 时直接写 --hue-shift 即时预览
// （style.css 里所有 calc(基准色相 + var(--hue-shift)) 全站重算，
// 顶栏 Logo 滤镜也跟同一变量），松手 change 才落库。
// 与背景图主题相互独立：未设置背景时色相同样生效。
const hueValue = ref(0)

const applyHue = (v: number) => {
  document.documentElement.style.setProperty('--hue-shift', String(v))
}

// 拖动即时预览：直接从事件取值，不依赖 v-model 的更新时序
const onHueInput = (e: Event) => {
  const v = Number((e.target as HTMLInputElement).value)
  hueValue.value = v
  applyHue(v)
}

const saveHue = async () => {
  const me = authStore.currentUser
  if (!me) return
  const prev = me.theme_hue ?? 0
  const v = hueValue.value
  if (v === prev) return
  me.theme_hue = v // 乐观更新（App.vue 的 watch 会同步写 --hue-shift）
  acting.value = true
  msg.value = ''
  try {
    await apiClient.put('/api/users/me/theme', { hue: v })
    msg.value = '色相已保存'
  } catch (err: any) {
    me.theme_hue = prev
    hueValue.value = prev
    applyHue(prev)
    msg.value = formatError(err, '保存失败')
  } finally {
    acting.value = false
  }
}

const resetHue = () => {
  hueValue.value = 0
  void saveHue()
}

// 用户数据晚到（挂载时 syncCurrentUser / 重新登录）→ 同步滑块与预览
watch(
  () => me.value?.theme_hue,
  (v) => {
    if (typeof v === 'number' && v !== hueValue.value) {
      hueValue.value = v
      applyHue(v)
    }
  },
  { immediate: true },
)

onMounted(() => {
  if (!me.value) void authStore.syncCurrentUser()
})
</script>

<template>
  <div class="theme-page">
    <div class="theme-container">
      <!-- 头部 -->
      <div class="theme-head card">
        <div>
          <h2 class="page-title">主题商店</h2>
        </div>
        <div class="status-box" :class="{ on: enabled }">
          <div class="status-label">当前状态</div>
          <div class="status-value">{{ enabled ? '已启用' : '未启用' }}</div>
        </div>
      </div>

      <div v-if="msg" class="action-msg">{{ msg }}</div>

      <!-- 深色主题 -->
      <div class="card section dark-section">
        <div class="dark-row">
          <div class="dark-copy">
            <h3 class="section-title">深色主题</h3>
          </div>
          <button
            type="button"
            class="dark-toggle"
            :class="{ on: isDark }"
            role="switch"
            :aria-checked="isDark"
            aria-label="深色主题开关"
            :disabled="acting"
            @click="toggleDark"
          >
            <span class="dark-knob" aria-hidden="true">
              <i class="fa-solid" :class="isDark ? 'fa-moon' : 'fa-sun'"></i>
            </span>
          </button>
        </div>
      </div>

      <!-- 洛谷风格主页（行布局与开关复用深色主题的 dark-row / dark-toggle 样式） -->
      <div class="card section dark-section">
        <div class="dark-row">
          <div class="dark-copy">
            <h3 class="section-title">洛谷风格主页</h3>
          </div>
          <button
            type="button"
            class="dark-toggle"
            :class="{ on: isLuogu }"
            role="switch"
            :aria-checked="isLuogu"
            aria-label="洛谷风格主页开关"
            :disabled="acting"
            @click="toggleHomeStyle"
          >
            <span class="dark-knob" aria-hidden="true">
              <i class="fa-solid" :class="isLuogu ? 'fa-house' : 'fa-cloud'"></i>
            </span>
          </button>
        </div>
      </div>

      <!-- 内置配色 -->
      <div class="card section">
        <h3 class="section-title">内置配色</h3>
        <div class="preset-grid">
          <button
            v-for="(p, key) in PRESETS"
            :key="key"
            class="preset"
            :class="{ active: selectedPreset === key }"
            :style="{ backgroundImage: p.css }"
            :disabled="acting"
            @click="applyPreset(String(key))"
          >
            <span class="preset-name">{{ p.name }}</span>
            <span v-if="selectedPreset === key" class="preset-check">✓ 使用中</span>
          </button>
        </div>
      </div>

      <!-- 自定义背景 URL -->
      <div class="card section">
        <h3 class="section-title">自定义背景</h3>
        <div class="url-input-row">
          <input
            v-model="customUrlInput"
            type="text"
            placeholder="粘贴图片 URL（如 https://example.com/bg.png）"
            :disabled="acting"
            class="url-input"
            @keyup.enter="applyCustomUrl"
          >
          <button
            class="btn primary"
            :disabled="acting || !customUrlInput.trim()"
            @click="applyCustomUrl"
          >应用图片</button>
        </div>
      </div>

      <!-- 色相调整 -->
      <div class="card section">
        <h3 class="section-title">色相调整</h3>
        <div class="hue-row">
          <input
            v-model.number="hueValue"
            type="range"
            min="-180"
            max="180"
            step="1"
            class="hue-slider"
            :disabled="acting"
            @input="onHueInput"
            @change="saveHue"
          >
          <span class="hue-deg">{{ hueValue > 0 ? '+' : '' }}{{ hueValue }}°</span>
          <!-- 当前主题色即时预览（240 为主色基准色相，色相自动 mod 360） -->
          <span
            class="hue-dot"
            :style="{ background: `hsl(${240 + hueValue} 70.75% 58.43%)` }"
            title="调整后的主题色"
          />
          <button
            class="btn ghost btn-sm"
            :disabled="acting || hueValue === 0"
            @click="resetHue"
          >恢复默认</button>
        </div>
        <!-- 色带：滑轨每个位置对应旋转后的主题色（-180° → 60° … 0° → 240° … +180° → 420°） -->
        <div class="hue-track" aria-hidden="true" />
      </div>

      <!-- 预览 -->
      <div class="card section">
        <h3 class="section-title">效果预览</h3>
        <div class="preview" :style="previewStyle">
          <div class="preview-card">卡片将像这样浮在你的背景上</div>
        </div>
      </div>

      <!-- 底部操作按钮 -->
      <div class="card bottom-actions">
        <button
          class="btn primary btn-lg"
          :disabled="acting || !enabled"
          @click="toggleEnabled"
        >{{ enabled ? '停用主题' : '启用主题' }}</button>
        <button
          class="btn ghost btn-lg"
          :disabled="acting || !currentBg"
          @click="resetTheme"
        >恢复默认</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.theme-page { min-height: calc(100vh - 60px - 80px); }
.theme-container { max-width: 860px; margin: 0 auto; padding: 4px 0 24px; display: flex; flex-direction: column; gap: 16px; }

/* ===== 头部 ===== */
.theme-head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 14px; padding: 20px 26px; }
.page-title { color: var(--primary); font-size: 22px; margin: 0; }
.page-sub { color: var(--text-sub); font-size: 13px; margin: 6px 0 0; }
.status-box { text-align: center; background: var(--bg-subtle); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 10px 26px; }
.status-box.on { background: var(--bg-subtle); border-color: #cdebd6; }
.status-label { font-size: 12px; color: var(--text-sub); }
.status-value { font-size: 22px; font-weight: 800; color: var(--text-sub); }
.status-box.on .status-value {color: light-dark(#27ae60, #34d399); }

.action-msg { background: color-mix(in srgb, var(--success) 10%, transparent);color: var(--success-text); padding: 10px 16px; border-radius: var(--radius-sm); font-size: 14px; }

/* ===== 深色主题开关 ===== */
.dark-section { padding: 20px 24px; }
.dark-row { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.dark-copy { flex: 1; }
.dark-copy .section-title { margin-bottom: 6px; }
.dark-copy .tip { margin: 0; }
.dark-toggle {
  flex-shrink: 0;
  width: 60px;
  height: 32px;
  border-radius: 16px;
  border: var(--border-width) solid var(--border-color);
  background: var(--bg-subtle);
  cursor: pointer;
  position: relative;
  padding: 0;
  transition: background 0.2s ease, border-color 0.2s ease;
}
.dark-toggle.on { background: var(--primary); border-color: transparent; }
.dark-toggle:disabled { opacity: 0.6; cursor: not-allowed; }
.dark-knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--surface-plain);
  color: var(--text-sub);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.25);
  transition: transform 0.2s ease;
}
.dark-toggle.on .dark-knob { transform: translateX(28px); color: #f5b301; }

/* ===== 通用区块 ===== */
.section { padding: 20px 24px; }
.section-title { color: var(--text-main); font-size: 15px; margin: 0 0 14px; }

/* ===== 内置配色网格 ===== */
.preset-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; }
.preset {
  position: relative;
  height: 84px;
  border-radius: var(--radius-md);
  border: 2px solid transparent;
  cursor: pointer;
  display: flex;
  align-items: flex-end;
  padding: 10px 12px;
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}
.preset:hover { transform: translateY(-2px); box-shadow: var(--shadow-card-hover); }
.preset.active { border-color: var(--primary); }
.preset-name { color: #fff; font-weight: 800; font-size: 14px; text-shadow: 0 1px 4px rgba(0,0,0,.45); }
.preset-check { position: absolute; top: 8px; right: 10px; background: rgba(255,255,255,.9); color: var(--primary); font-size: 11px; font-weight: 800; border-radius: 10px; padding: 2px 8px; }

/* ===== 色相调整 ===== */
.hue-row { display: flex; align-items: center; gap: 12px; }
.hue-slider {
  flex: 1;
  accent-color: var(--primary);
  cursor: pointer;
  height: 22px;
}
.hue-slider:disabled { opacity: 0.5; cursor: not-allowed; }
.hue-deg {
  min-width: 52px;
  text-align: right;
  font-size: 15px;
  font-weight: 800;
  color: var(--text-main);
  font-variant-numeric: tabular-nums;
}
.hue-dot {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: 2px solid var(--border-color);
  flex-shrink: 0;
}
/* 色带与滑块对齐：每个位置 = 该角度旋转后的主题色 */
.hue-track {
  height: 10px;
  border-radius: 5px;
  margin-top: 8px;
  border: var(--border-width) solid var(--border-color);
  background: linear-gradient(
    to right,
    hsl(60 70.75% 58.43%),
    hsl(120 70.75% 58.43%),
    hsl(180 70.75% 58.43%),
    hsl(240 70.75% 58.43%),
    hsl(300 70.75% 58.43%),
    hsl(360 70.75% 58.43%),
    hsl(420 70.75% 58.43%)
  );
}
.btn-sm { padding: 6px 16px; font-size: 13px; }

/* ===== 自定义 URL 输入 ===== */
.url-input-row { display: flex; gap: 10px; flex-wrap: wrap; }
.url-input {
  flex: 1;
  min-width: 280px;
  padding: 9px 16px;
  border: var(--border-width) solid var(--border-color);
  border-radius: 22px;
  font-size: 14px;
  font-family: inherit;
  outline: none;
  background: var(--surface-strong);
}
.url-input:focus { border-color: var(--primary); }
.url-input:disabled { opacity: .5; cursor: not-allowed; }
.tip { color: var(--text-sub); font-size: 12px; margin: 8px 0 0; }

/* ===== 预览区 ===== */
.preview {
  height: 260px;
  border-radius: var(--radius-md);
  border: var(--border-width) solid var(--border-color);
  background-color: var(--bg-page);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.preview-card {
  background: var(--surface);
  -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: 22px 34px;
  color: var(--text-main);
  font-size: 14px;
  font-weight: 700;
}

/* ===== 底部操作按钮 ===== */
.bottom-actions {
  display: flex;
  justify-content: center;
  gap: 16px;
  padding: 18px 24px;
}
.btn {
  border: var(--border-width) solid var(--border-color);
  background: var(--surface-strong);
  color: var(--text-sub);
  border-radius: 22px;
  padding: 9px 24px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.2s;
}
.btn:hover:not(:disabled) { box-shadow: var(--shadow-card); }
.btn.primary { background: var(--primary); border-color: var(--primary); color: #fff; }
.btn.primary:hover:not(:disabled) { background: var(--primary-hover); }
.btn:disabled { opacity: .5; cursor: not-allowed; }
.btn-lg { padding: 11px 32px; font-size: 15px; }
.btn.ghost { background: transparent; }

@media (max-width: 600px) {
  .theme-container { padding: 2px 0 18px; }
  .theme-head { padding: 16px 18px; }
  .section { padding: 16px 18px; }
  .bottom-actions { flex-direction: column; align-items: stretch; }
}
</style>
