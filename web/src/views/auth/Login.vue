<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import apiClient from '@/api/client'
import { clearAliyunCaptchaCallbacks, isAliyunCaptchaReady, prepareAliyunCaptcha, triggerAliyunCaptcha } from '@/utils/aliyunCaptcha'
import { withBase } from '@/utils/base'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

// 表单数据
const identifier = ref('')
const password = ref('')
const captcha = ref('')
const captchaId = ref('')

// 验证码图片（后端生成，base64 data URL；答案不再下发给前端）
const captchaImage = ref('')
const ESA_CAPTCHA_PREFIX = (import.meta.env.VITE_ESA_CAPTCHA_PREFIX || '').trim()
// 旧单场景变量仅作为迁移期回退；当前登录规则使用专属 AUTH 场景。
const ESA_CAPTCHA_SCENE_ID = (
  import.meta.env.VITE_ESA_CAPTCHA_SCENE_ID_AUTH || import.meta.env.VITE_ESA_CAPTCHA_SCENE_ID || ''
).trim()
const useEsaCaptcha = !!(ESA_CAPTCHA_PREFIX && ESA_CAPTCHA_SCENE_ID)
const esaCaptchaReady = ref(false)
const esaCaptchaLoading = ref(false)
const esaCaptchaError = ref('')
const captchaPending = ref(false)
// 嵌入式验证持有的验签票据：先验证后登录、先登录后验证两种顺序都支持。
// ESA 票据 90 秒有效且单次使用，这里 60 秒提前作废，避免提交时撞 F019（超时）。
const esaVerifyParam = ref('')
const esaVerified = ref(false)
let esaExpiryTimer: number | null = null
let esaReadyTimer: number | null = null

const clearEsaVerify = () => {
  esaVerifyParam.value = ''
  esaVerified.value = false
  if (esaExpiryTimer !== null) {
    window.clearTimeout(esaExpiryTimer)
    esaExpiryTimer = null
  }
}

const storeEsaVerify = (param: string) => {
  esaVerifyParam.value = param
  esaVerified.value = true
  if (esaExpiryTimer !== null) window.clearTimeout(esaExpiryTimer)
  esaExpiryTimer = window.setTimeout(clearEsaVerify, 60000)
}

const esaHintText = computed(() => {
  if (esaCaptchaLoading.value) return '正在加载安全验证...'
  if (esaCaptchaError.value) return esaCaptchaError.value
  if (!esaCaptchaReady.value) return '安全验证准备中...'
  if (captchaPending.value) return '请完成表单中的安全验证'
  if (esaVerified.value) return '安全验证已通过，可直接登录'
  return '登录需完成表单中的安全验证'
})

// 错误和加载状态
const error = ref('')
const loading = ref(false)
const isSubmitting = ref(false)
const loginSuccess = ref(false)

// 获取验证码
const fetchCaptcha = async () => {
  try {
    // 响应拦截器已解包 response.data
    const data = (await apiClient.get('/auth/captcha')) as any
    captchaId.value = data.captcha_id
    captchaImage.value = data.image || ''
    // 不要清除错误消息，保持登录错误的显示
  } catch (err) {
    console.error('获取验证码失败:', err)
    error.value = '获取验证码失败，请刷新页面重试'
  }
}

// 刷新验证码
const refreshCaptcha = () => {
  captcha.value = ''
  // 不要清除错误消息，让用户能看到登录失败的原因
  fetchCaptcha()
}

const validateCredentials = () => {
  error.value = ''
  loginSuccess.value = false

  if (!identifier.value.trim()) {
    error.value = '请输入用户名、UID、手机或电子邮箱'
    return false
  }

  if (!password.value) {
    error.value = '请输入密码'
    return false
  }

  if (!useEsaCaptcha && !captcha.value.trim()) {
    error.value = '请输入图形验证码'
    return false
  }
  return true
}

const finishLogin = () => {
  loginSuccess.value = true
  error.value = ''
  setTimeout(() => {
    const redirect = route.query.redirect as string || '/'
    router.push(redirect)
  }, 1500)
}

const handleGraphLogin = async () => {
  if (isSubmitting.value || !validateCredentials()) return
  isSubmitting.value = true
  loading.value = true

  try {
    const success = await authStore.loginWithIdentifier({
      identifier: identifier.value.trim(),
      password: password.value,
      captcha_id: captchaId.value,
      captcha: captcha.value.trim()
    })

    if (success) {
      finishLogin()
    } else {
      error.value = '登录失败：用户名或密码错误'
      refreshCaptcha()
    }
  } catch (err: any) {
    // 根据不同的错误类型显示具体的失败原因
    let errorMsg = '登录失败'

    if (err.response?.data?.detail) {
      const detail = err.response.data.detail

      // 根据后端返回的具体错误信息进行友好提示
      if (detail.includes('验证码') || detail.includes('captcha')) {
        errorMsg = '登录失败：图形验证码错误或已过期'
      } else if (detail.includes('用户不存在') || detail.includes('用户名或密码')) {
        errorMsg = '登录失败：用户名或密码错误'
      } else if (detail.includes('封禁') || detail.includes(' banned')) {
        errorMsg = '登录失败：账号已被封禁，请联系管理员'
      } else if (detail.includes('网络') || detail.includes('超时')) {
        errorMsg = '登录失败：网络连接超时，请检查网络连接'
      } else {
        errorMsg = `登录失败：${detail}`
      }
    } else if (err.message) {
      errorMsg = `登录失败：${err.message}`
    } else {
      errorMsg = '登录失败：服务器响应异常，请稍后重试'
    }

    error.value = errorMsg
    refreshCaptcha()
  } finally {
    isSubmitting.value = false
    loading.value = false
  }
}

const handleEsaLogin = async (captchaVerifyParam: string) => {
  captchaPending.value = false
  if (isSubmitting.value) return
  // 表单没填好时保留票据：用户补好后点登录可直接用，不必重新验证
  if (!validateCredentials()) return
  // 提交即消费票据（单次有效，防 F018 复用）；util 在业务请求后 refresh 复位组件
  clearEsaVerify()
  isSubmitting.value = true
  loading.value = true
  try {
    await authStore.loginWithAliyunCaptcha({
      identifier: identifier.value.trim(),
      password: password.value,
    }, captchaVerifyParam)
    finishLogin()
  } catch (err: any) {
    error.value = err?.message || err?.response?.data?.detail || '安全验证或登录失败，请重试'
  } finally {
    isSubmitting.value = false
    loading.value = false
  }
}

const handleSubmit = (event: Event) => {
  event.preventDefault()
  if (isSubmitting.value || captchaPending.value || !validateCredentials()) return
  if (!useEsaCaptcha) {
    void handleGraphLogin()
    return
  }
  if (!esaCaptchaReady.value) {
    error.value = esaCaptchaError.value || '安全验证正在准备，请稍后重试'
    return
  }

  error.value = ''
  // 已持有新鲜票据（先完成了表单内的验证）：直接提交
  if (esaVerified.value) {
    void handleEsaLogin(esaVerifyParam.value)
    return
  }
  // 无票：等待用户完成表单内的验证组件，success 回调会自动续上登录
  captchaPending.value = true
  document.getElementById('nlnoj-aliyun-captcha-element')?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  // 兼容部分形态：点击 SDK 绑定的触发器会直接激活内嵌验证；嵌入式下也可能
  // 为空操作，失败无妨——用户直接与表单内组件交互，success 回调会继续提交。
  void triggerAliyunCaptcha().catch(() => {})
}

// 组件挂载时按配置选择 ESA 或兼容图形码。
onMounted(async () => {
  if (!useEsaCaptcha) {
    await fetchCaptcha()
    return
  }

  esaCaptchaLoading.value = true
  try {
    await prepareAliyunCaptcha(ESA_CAPTCHA_PREFIX, ESA_CAPTCHA_SCENE_ID, {
      onSuccess: (param: string) => {
        storeEsaVerify(param)
        // 用户已点过登录（在等验证）：票据到手立即续上登录流程
        if (captchaPending.value) void handleEsaLogin(param)
      },
      onFailure: message => {
        captchaPending.value = false
        error.value = message
      },
      onClose: () => {
        if (!isSubmitting.value) captchaPending.value = false
      },
    })
    const wait = Math.max(0, 2000)
    esaReadyTimer = window.setTimeout(() => {
      esaCaptchaReady.value = isAliyunCaptchaReady()
    }, wait)
    if (isAliyunCaptchaReady()) esaCaptchaReady.value = true
  } catch (err: any) {
    esaCaptchaError.value = err?.message || '阿里云安全验证加载失败'
    error.value = esaCaptchaError.value
  } finally {
    esaCaptchaLoading.value = false
  }
})

onUnmounted(() => {
  if (esaReadyTimer !== null) window.clearTimeout(esaReadyTimer)
  clearEsaVerify()
  clearAliyunCaptchaCallbacks()
})
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <h1 class="login-title"><img :src="withBase('favicon.svg')" width="45"> NLNOJ</h1>
      <div class="login-subtitle">登录账号</div>

      <!-- 登录表单 -->
      <form @submit.prevent="handleSubmit" class="login-form">
        <!-- 用户标识符 -->
        <div class="form-group">
          <input
            v-model="identifier"
            type="text"
            class="form-input"
            placeholder="用户名、UID、手机或电子邮箱"
            autocomplete="off"
          />
        </div>

        <!-- 密码 -->
        <div class="form-group">
          <input
            v-model="password"
            type="password"
            class="form-input"
            placeholder="输入密码"
            autocomplete="current-password"
          />
        </div>

        <!-- ESA 嵌入式验证组件：一点即过/滑块直接渲染在表单内，不再弹窗 -->
        <div v-if="useEsaCaptcha" id="nlnoj-aliyun-captcha-element" class="esa-embed-slot" />

        <!-- 未配置 ESA 时保留原图形验证码；配置完成后由 ESA 提供内嵌验证 -->
        <div v-if="!useEsaCaptcha" class="form-group">
          <div class="captcha-row">
            <input
              v-model="captcha"
              type="text"
              class="form-input captcha-input"
              placeholder="请输入图形验证码"
              autocomplete="off"
              maxlength="6"
            />
            <img
              v-if="captchaImage"
              :src="captchaImage"
              alt="图形验证码"
              title="点击刷新"
              class="captcha-canvas"
              @click="refreshCaptcha"
            />
          </div>
        </div>
        <p v-if="useEsaCaptcha" class="esa-captcha-hint">
          <i class="fa-solid fa-shield-halved"></i>
          {{ esaHintText }}
        </p>

        <!-- 成功信息 -->
        <div v-if="loginSuccess" class="success-message">
          ✓ 登录成功！正在跳转...
        </div>

        <!-- 错误信息 -->
        <div v-if="error" class="error-message">
          {{ error }}
        </div>

        <!-- 登录按钮 -->
        <button
          id="nlnoj-login-button"
          type="submit"
          :disabled="loading || captchaPending || (useEsaCaptcha && !esaCaptchaReady)"
          class="login-btn"
        >
          {{ loading ? '登录中...' : captchaPending ? '等待安全验证...' : (useEsaCaptcha ? '验证并登录' : '使用账户密码登录') }}
        </button>
      </form>

      <!-- 底部链接 -->
      <div class="footer-links">
        <router-link to="/register" class="footer-link">
          没有账号？
        </router-link>
        <router-link to="/forgot-password" class="footer-link">
          忘记密码？
        </router-link>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 页面容器 */
.login-page {
  min-height: 100vh;
  
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 20px;
  font-family: inherit;
  /* 这里是 flex 项（.main-content 是 display:flex），
     min-width:auto 默认会撑到内容的 max-content（400px + padding = 440px），
     结果 .login-card 的 max-width:90% 反向按 400px 解析成 360px，
     在 375px 屏上溢出 33px。改成占满可用行宽即可。 */
  flex: 1;
  width: 100%;
  min-width: 0;
}

/* 登录卡片 */
.login-card {
  background: var(--surface-plain);
  width: 400px;
  max-width: 90%;
  border-radius: 16px;
  padding: 32px 28px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

/* 标题 */
.login-title {
  font-size: 28px;
  text-align: center;
  color: var(--primary);
  margin-bottom: 8px;
  font-weight: 700;
  display: flex;
  align-items: center;    
  justify-content: center;
  gap: 10px;              
  margin: 0;
}

.login-subtitle {
  text-align: center;
  color: var(--text-sub);
  margin-bottom: 28px;
  font-size: 14px;
}

/* 表单样式 */
.login-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-group {
  margin-bottom: 8px;
}

.form-input {
  width: 100%;
  padding: 12px 16px;
  border: 1px solid #d1d5db;
  border-radius: 12px;
  font-size: 15px;
  background: var(--surface-plain);
  transition: all 0.2s;
}

.form-input:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--glow-blue) 10%, transparent);
  background: var(--surface-plain);
}

.form-input::placeholder {
  color: #9ca3af;
}

/* 验证码行 */
.captcha-row {
  display: flex;
  gap: 12px;
  align-items: center;
}

.captcha-input {
  flex: 1;
}

.captcha-canvas {
  cursor: pointer;
  border-radius: 12px;
  border: 1px solid #d1d5db;
  background: var(--surface-plain);
  width: 120px;
  height: 44px;
  transition: border-color 0.2s;
}

.captcha-canvas:hover {
  border-color: #9ca3af;
}

.esa-captcha-hint {
  margin: 0 0 14px;
  color: #6b7a90;
  font-size: 13px;
  text-align: center;
}

.esa-captcha-hint i {
  margin-right: 6px;
  color: var(--primary);
}

/* ESA 嵌入式验证组件占位：SDK 向其中渲染滑块/勾选框 */
.esa-embed-slot {
  display: flex;
  justify-content: center;
  align-items: center;
  scroll-margin: 24px;
}

/* 错误信息 */
.error-message {
  padding: 8px;
  border-radius: 12px;
  font-size: 13px;
  text-align: center;
  background: color-mix(in srgb, var(--danger) 10%, transparent);
color: var(--danger-text);
}

/* 成功信息 */
.success-message {
  padding: 12px;
  border-radius: 12px;
  font-size: 14px;
  text-align: center;
  background: color-mix(in srgb, var(--success) 10%, transparent);
color: var(--success-text);
  font-weight: 600;
  animation: slideDown 0.3s ease-out;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 登录按钮 */
.login-btn {
  width: 100%;
  padding: 12px;
  background: var(--primary);
  border: none;
  border-radius: 40px;
  color: white;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
}

.login-btn:hover:not(:disabled) {
  background: var(--primary-hover);
}

.login-btn:disabled {
  opacity: 0.6;
  cursor: notallowed;
}

/* 底部链接 */
.footer-links {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 24px;
  font-size: 14px;
}

.footer-link {
  color: var(--primary);
  text-decoration: none;
  transition: color 0.2s;
}

.footer-link:hover {
  color: var(--primary-hover);
  text-decoration: underline;
}

/* 响应式适配 */
@media (max-width: 480px) {
  /* 卡片只有 max-width:90%，窄屏上会缩到 280px（内容仅 240px），
     直接占满可用宽度更合理 */
  .login-card {
    width: 100%;
    max-width: 100%;
    padding: 24px 20px;
  }

  .login-title {
    font-size: 24px;
  }

  .form-input {
    padding: 10px 14px;
    font-size: 14px;
  }

  .captcha-canvas {
    width: 100px;
    height: 36px;
  }

  .login-btn {
    padding: 10px;
    font-size: 15px;
  }

  .footer-links {
    flex-direction: column;
    gap: 12px;
    text-align: center;
  }
}
</style>
