import apiClient from './client'
import { apiUrl } from '@/utils/base'
import type { LoginCredentials, RegisterData, TokenResponse, User } from '@/types'

export const authApi = {
  // 注册
  async register(data: RegisterData): Promise<any> {
    return apiClient.post('/auth/register', data)
  },

  // 发送邮箱验证码
  async sendEmailVerification(email: string): Promise<any> {
    return apiClient.post('/auth/send-verification', { email })
  },

  // 测试邮箱配置
  async testEmailConfig(): Promise<any> {
    return apiClient.get('/auth/email-config-test')
  },

  // 登录（使用用户名/UID/手机/邮箱）
  async loginWithIdentifier(credentials: {
    identifier: string
    password: string
    captcha_id: string
    captcha: string
  }): Promise<TokenResponse> {
    return apiClient.post('/auth/login', credentials)
  },

  // ESA 验证：请求必须走同源受保护 URI，只有 ESA 响应头明确返回通过码才接受 token。
  async loginWithAliyunCaptcha(
    credentials: { identifier: string; password: string },
    captchaVerifyParam: string,
  ): Promise<TokenResponse> {
    const query = new URLSearchParams({ captcha_verify_param: captchaVerifyParam })
    const response = await fetch(apiUrl(`/auth/login?${query.toString()}`), {
      method: 'POST',
      // 同源时带 cookie；跨域（GitHub Pages）时后端未开 allow_credentials，
      // 用 same-origin 可避免预检被拒。
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      // ESA 按 query 参数验签；body 副本供源站 ESA_CAPTCHA_REQUIRED 开关检查。
      body: JSON.stringify({ ...credentials, captcha_verify_param: captchaVerifyParam }),
    })
    const verifyCode = response.headers.get('X-Captcha-Verify-Code')?.toUpperCase() || ''
    const body: any = await response.json().catch(() => ({}))
    const passed = ['T001', 'T005', 'T006'].includes(verifyCode)
    if (!passed) {
      throw new Error(body?.detail || `ESA 安全验证未通过${verifyCode ? `（${verifyCode}）` : ''}`)
    }
    if (!response.ok) {
      throw new Error(body?.detail || '登录失败，请重试')
    }
    return body as TokenResponse
  },

  // 登录
  async login(credentials: LoginCredentials): Promise<TokenResponse> {
    const formData = new URLSearchParams()
    formData.append('username', credentials.username)
    formData.append('password', credentials.password)

    return apiClient.post('/tokens', formData, {
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded'
      }
    })
  },

  // 刷新 token
  async refreshToken(refreshToken: string): Promise<TokenResponse> {
    return apiClient.post('/tokens/refresh', { refresh_token: refreshToken })
  },

  // 获取当前用户信息
  async getCurrentUser(): Promise<User> {
    // 加时间戳避免浏览器/中间层缓存旧资料（如刚上传的头像在刷新后仍显示旧图）
    return apiClient.get(`/auth/me?_t=${Date.now()}`)
  },

  // 请求密码重置
  async requestPasswordReset(email: string): Promise<any> {
    return apiClient.post('/auth/password-reset/request', { email })
  },

  // 确认密码重置
  async confirmPasswordReset(token: string, new_password: string): Promise<any> {
    return apiClient.post('/auth/password-reset/confirm', { token, new_password })
  },

  // 发送更换邮箱验证码
  async sendChangeEmailCode(email: string): Promise<any> {
    return apiClient.post('/auth/change-email/send-code', { email })
  },

  // 确认更换邮箱
  async confirmChangeEmail(token: string, code: string): Promise<any> {
    return apiClient.post('/auth/change-email/confirm', { token, code })
  }
}
