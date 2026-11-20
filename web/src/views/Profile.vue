<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { userProfileApi, type UserProfileUpdate } from '@/api/userProfile'
import apiClient from '@/api/client'
import { getAccessToken } from '@/utils/session'
import { copyText } from '@/utils/codeCopy'

const router = useRouter()
const authStore = useAuthStore()

// 用户资料表单
const profileForm = ref<UserProfileUpdate>({
  username: '',
  bio: '',
  avatar_url: '',
  user_tag: '',
  username_color: ''
})

// 密码修改表单
const passwordForm = ref({
  old_password: '',
  new_password: '',
  confirm_password: ''
})

// UI状态
const loading = ref(false)
const saving = ref(false)
const passwordSaving = ref(false)
const activeTab = ref('profile')
const message = ref('')
const messageType = ref<'success' | 'error'>('success')
const showPasswordForm = ref(false)

// otk / API 令牌查看（安全设置 tab）：点「显示」才把 localStorage 里的
// 令牌填进 DOM，点「隐藏」即从 DOM 清出——页面常态不持有明文令牌
const showToken = ref(false)
const apiToken = ref('')
const tokenCopied = ref(false)
const toggleToken = () => {
  showToken.value = !showToken.value
  apiToken.value = showToken.value ? getAccessToken() : ''
}
const copyApiToken = async () => {
  const tok = apiToken.value || getAccessToken()
  if (!tok) return
  apiToken.value = tok
  if (await copyText(tok)) {
    tokenCopied.value = true
    setTimeout(() => { tokenCopied.value = false }, 1500)
  }
}
const lastUsernameChange = ref<string | null>(null)

// 改名冷却：30 天内只能改一次
const canChangeUsername = computed(() => {
  if (!lastUsernameChange.value) return true
  const last = new Date(lastUsernameChange.value)
  const now = new Date()
  return now.getTime() - last.getTime() >= 30 * 24 * 60 * 60 * 1000
})

const usernameCooldownText = computed(() => {
  if (!lastUsernameChange.value) return ''
  const last = new Date(lastUsernameChange.value)
  const now = new Date()
  const diff = 30 * 24 * 60 * 60 * 1000 - (now.getTime() - last.getTime())
  if (diff <= 0) return ''
  const days = Math.floor(diff / (24 * 60 * 60 * 1000))
  const hours = Math.floor((diff % (24 * 60 * 60 * 1000)) / (60 * 60 * 1000))
  return `还需等待 ${days} 天 ${hours} 小时`
})

// 改名历史
const showUsernameHistoryModal = ref(false)
const usernameHistoryList = ref<any[]>([])
const usernameHistoryLoading = ref(false)

const openUsernameHistoryModal = async () => {
  if (!authStore.currentUser?.id) return
  showUsernameHistoryModal.value = true
  usernameHistoryLoading.value = true
  try {
    const data: any = await apiClient.get(`/users/${authStore.currentUser.id}/username-history`)
    usernameHistoryList.value = data || []
  } catch {
    usernameHistoryList.value = []
  } finally {
    usernameHistoryLoading.value = false
  }
}

// 头像预览
const avatarPreview = computed(() => {
  return profileForm.value.avatar_url || generateAvatar(profileForm.value.username || 'U')
})

// 生成简单头像
const generateAvatar = (name: string) => {
  const initial = name.charAt(0).toUpperCase()
  return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Crect width='40' height='40' fill='%23e74c3c'/%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' dy='.3em' fill='white' font-size='16' font-family='Arial'%3E${encodeURIComponent(initial)}%3C/text%3E%3C/svg%3E`
}

// 格式化日期
const formatDate = (dateString: string) => {
  const date = new Date(dateString)
  return date.toLocaleDateString('zh-CN')
}

// 加载用户资料
const loadProfile = async () => {
  loading.value = true
  try {
    const user = await userProfileApi.getCurrentUser()
    profileForm.value = {
      username: user.username,
      bio: user.bio || '',
      avatar_url: user.avatar_url || '',
      user_tag: user.user_tag || '',
      username_color: user.username_color || ''
    }
    lastUsernameChange.value = user.last_username_change || null
  } catch (error: any) {
    showMessage('加载用户资料失败', 'error')
    console.error('Load profile error:', error)
  } finally {
    loading.value = false
  }
}

// 保存用户资料
const saveProfile = async () => {
  if (saving.value) return

  saving.value = true
  message.value = ''

  try {
    const updatedUser = await userProfileApi.updateProfile(profileForm.value)
    // 更新本地用户状态
    if (authStore.currentUser) {
      Object.assign(authStore.currentUser, updatedUser)
    }
    showMessage('资料更新成功', 'success')
  } catch (error: any) {
    const errorMsg = error.response?.data?.detail || '更新失败，请稍后重试'
    showMessage(errorMsg, 'error')
  } finally {
    saving.value = false
  }
}

// 修改密码
const updatePassword = async () => {
  if (passwordSaving.value) return

  // 验证密码
  if (passwordForm.value.new_password.length < 8) {
    showMessage('新密码至少需要8个字符', 'error')
    return
  }

  if (passwordForm.value.new_password !== passwordForm.value.confirm_password) {
    showMessage('两次输入的密码不一致', 'error')
    return
  }

  passwordSaving.value = true
  message.value = ''

  try {
    await userProfileApi.updatePassword({
      old_password: passwordForm.value.old_password,
      new_password: passwordForm.value.new_password
    })

    showMessage('密码修改成功', 'success')
    // 清空密码表单
    passwordForm.value = {
      old_password: '',
      new_password: '',
      confirm_password: ''
    }
    showPasswordForm.value = false
  } catch (error: any) {
    const errorMsg = error.response?.data?.detail || '密码修改失败'
    showMessage(errorMsg, 'error')
  } finally {
    passwordSaving.value = false
  }
}

// 显示消息
const showMessage = (msg: string, type: 'success' | 'error') => {
  message.value = msg
  messageType.value = type
  setTimeout(() => {
    message.value = ''
  }, 5000)
}

// 切换标签
const setActiveTab = (tab: string) => {
  activeTab.value = tab
}

// ===== 奖项认证 =====
const realName = ref('')
const oierdbResults = ref<any[]>([])
const oierdbLoading = ref(false)
const oierdbError = ref('')
const selectedPerson = ref<any>(null)
const certSubmitting = ref(false)
const certStatus = ref<string>('none')
const oiLevel = ref<string>('')

const searchOierdb = async () => {
  const name = realName.value.trim()
  if (!name) {
    oierdbError.value = '请输入真实姓名'
    return
  }
  oierdbLoading.value = true
  oierdbError.value = ''
  oierdbResults.value = []
  selectedPerson.value = null
  try {
    const res = await apiClient.get('/api/users/oierdb/search', { params: { name } })
    if (res.data?.error) {
      oierdbError.value = res.data.error
    } else {
      oierdbResults.value = res.data?.items || []
      if (oierdbResults.value.length === 0) {
        oierdbError.value = '未找到匹配的人员'
      }
    }
  } catch (e: any) {
    oierdbError.value = e.response?.data?.detail || '搜索失败'
  } finally {
    oierdbLoading.value = false
  }
}

const selectPerson = (p: any) => {
  selectedPerson.value = p
}

const submitCert = async () => {
  if (!selectedPerson.value) {
    showMessage('请选择一个 OIerDB 条目', 'error')
    return
  }
  certSubmitting.value = true
  try {
    await apiClient.post('/api/users/me/award-certification', {
      real_name: realName.value.trim(),
      oierdb_uid: String(selectedPerson.value.id || selectedPerson.value.uid || ''),
      oi_awards: selectedPerson.value.awards || selectedPerson.value.records || []
    })
    certStatus.value = 'pending'
    showMessage('认证申请已提交，等待管理员审核', 'success')
  } catch (e: any) {
    showMessage(e.response?.data?.detail || '提交失败', 'error')
  } finally {
    certSubmitting.value = false
  }
}

const cancelCert = async () => {
  try {
    await apiClient.delete('/api/users/me/award-certification')
    certStatus.value = 'none'
    selectedPerson.value = null
    showMessage('已撤回认证申请', 'success')
  } catch (e: any) {
    showMessage(e.response?.data?.detail || '撤回失败', 'error')
  }
}

const loadCertStatus = () => {
  const u = authStore.currentUser
  realName.value = u?.real_name || ''
  certStatus.value = u?.award_cert_status || 'none'
  oiLevel.value = u?.oi_level || ''
}

// 退出登录
const handleLogout = () => {
  authStore.logout()
  router.push('/login')
}

// 组件挂载时加载用户资料
onMounted(() => {
  if (authStore.currentUser) {
    profileForm.value = {
      username: authStore.currentUser.username,
      bio: authStore.currentUser.bio || '',
      avatar_url: authStore.currentUser.avatar_url || '',
      user_tag: authStore.currentUser.user_tag || '',
      username_color: authStore.currentUser.username_color || ''
    }
    lastUsernameChange.value = authStore.currentUser.last_username_change || null
  } else {
    loadProfile()
  }
  loadCertStatus()
})
</script>

<template>
  <div class="max-w-4xl mx-auto">
    <h1 class="text-3xl font-bold text-gray-900 mb-6">个人中心</h1>

    <div class="bg-white shadow-md rounded-lg overflow-hidden">
      <!-- 头部 -->
      <div class="bg-gradient-to-r from-red-500 to-red-600 px-6 py-8">
        <div class="flex items-center space-x-6">
          <div class="relative">
            <img
              :src="avatarPreview"
              :alt="profileForm.username"
              class="w-24 h-24 rounded-full border-4 border-white shadow-lg"
              onerror="this.onerror=null;this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 40 40%22%3E%3Crect width=%2240%22 height=%2240%22 fill=%22%23e74c3c%22/%3E%3Ctext x=%2250%25%22 y=%2250%25%22 text-anchor=%22middle%22 dy=%22.3em%22 fill=%22white%22 font-size=%2216%22 font-family=%22Arial%22%3EU%3C/text%3E%3C/svg%3E'"
            />
          </div>
          <div class="text-white">
            <h1 class="text-2xl font-bold">{{ profileForm.username }}</h1>
            <p class="text-red-100 mt-1">
              UID: {{ authStore.currentUser?.user_number }}
            </p>
            <p v-if="profileForm.user_tag" class="text-red-100 mt-1">
              {{ profileForm.user_tag }}
            </p>
          </div>
        </div>
      </div>

      <!-- 消息提示 -->
      <div v-if="message" :class="`p-4 mx-6 mt-6 rounded-lg ${messageType === 'success' ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'}`">
        {{ message }}
      </div>

      <!-- 标签导航 -->
      <div class="border-b border-gray-200">
        <nav class="flex -mb-px">
          <button
            @click="setActiveTab('profile')"
            :class="`px-6 py-4 text-sm font-medium ${activeTab === 'profile' ? 'text-red-600 border-b-2 border-red-600' : 'text-gray-500 hover:text-gray-700'}`"
          >
            基本资料
          </button>
          <button
            @click="setActiveTab('security')"
            :class="`px-6 py-4 text-sm font-medium ${activeTab === 'security' ? 'text-red-600 border-b-2 border-red-600' : 'text-gray-500 hover:text-gray-700'}`"
          >
            安全设置
          </button>
          <button
            @click="setActiveTab('stats')"
            :class="`px-6 py-4 text-sm font-medium ${activeTab === 'stats' ? 'text-red-600 border-b-2 border-red-600' : 'text-gray-500 hover:text-gray-700'}`"
          >
            统计信息
          </button>
          <button
            @click="setActiveTab('award')"
            :class="`px-6 py-4 text-sm font-medium ${activeTab === 'award' ? 'text-red-600 border-b-2 border-red-600' : 'text-gray-500 hover:text-gray-700'}`"
          >
            奖项认证
          </button>
        </nav>
      </div>

      <!-- 内容区域 -->
      <div class="p-6">
        <!-- 基本资料 -->
        <div v-show="activeTab === 'profile'">
          <div class="space-y-6">
            <div>
              <div class="flex items-center justify-between mb-2">
                <label class="block text-sm font-medium text-gray-700">用户名</label>
                <button
                  type="button"
                  @click="openUsernameHistoryModal"
                  class="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1 font-normal cursor-pointer"
                >
                  <i class="fa-solid fa-clock-rotate-left"></i> 查看改名记录
                </button>
              </div>
              <input
                v-model="profileForm.username"
                type="text"
                :disabled="!canChangeUsername"
                class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-red-500 focus:border-transparent disabled:bg-gray-100 disabled:cursor-not-allowed"
                placeholder="请输入用户名"
              />
              <p v-if="!canChangeUsername" class="mt-1 text-sm text-gray-500">
                用户名每 30 天只能修改一次，{{ usernameCooldownText }}
              </p>
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">个人简介</label>
              <textarea
                v-model="profileForm.bio"
                rows="4"
                class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-red-500 focus:border-transparent"
                placeholder="介绍一下自己..."
              />
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">头像URL</label>
              <input
                v-model="profileForm.avatar_url"
                type="url"
                class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-red-500 focus:border-transparent"
                placeholder="https://example.com/avatar.jpg"
              />
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">用户标签</label>
              <p class="text-sm text-gray-400">用户标签由 Tag 卡决定——请在下方 Tag 卡区佩戴；Tag 卡由持有 Tag 管理权限的管理员授予</p>
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">用户名颜色</label>
              <input
                v-model="profileForm.username_color"
                type="text"
                class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-red-500 focus:border-transparent"
                placeholder="var(--primary)"
              />
            </div>

            <div class="pt-4">
              <button
                @click="saveProfile"
                :disabled="saving"
                class="px-6 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 focus:ring-2 focus:ring-red-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {{ saving ? '保存中...' : '保存资料' }}
              </button>
            </div>
          </div>
        </div>

        <!-- 安全设置 -->
        <div v-show="activeTab === 'security'">
          <div class="space-y-6">
            <!-- otk / API 访问令牌：只读密码框，点按钮才显示明文 -->
            <div class="border border-gray-300 rounded-lg p-4">
              <label class="block text-sm font-medium text-gray-700 mb-2">API 访问令牌（otk 命令行）</label>
              <div class="flex space-x-2">
                <input
                  readonly
                  :type="showToken ? 'text' : 'password'"
                  :value="apiToken"
                  placeholder="点击「显示」读取令牌"
                  class="flex-1 px-4 py-2 border border-gray-300 rounded-lg bg-gray-50 font-mono text-sm focus:ring-2 focus:ring-red-500 focus:border-transparent"
                />
                <button
                  @click="toggleToken"
                  :title="showToken ? '隐藏令牌' : '显示令牌（明文）'"
                  class="px-4 py-2 border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-100"
                >
                  <i :class="showToken ? 'fa-solid fa-eye-slash' : 'fa-solid fa-eye'"></i>
                  {{ showToken ? '隐藏' : '显示' }}
                </button>
                <button
                  @click="copyApiToken"
                  title="复制令牌到剪贴板"
                  class="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700"
                >
                  <i :class="tokenCopied ? 'fa-solid fa-check' : 'fa-solid fa-copy'"></i>
                  {{ tokenCopied ? '已复制' : '复制' }}
                </button>
              </div>
              <p class="text-xs text-gray-500 mt-2">
                给 otk（OierToolKit）等命令行工具认证：
                <code class="px-1 bg-gray-100 rounded">otk config remote_token &lt;令牌&gt;</code>
                · 有效期 30 天 · 令牌等同密码，不要截图外发
              </p>
            </div>

            <div v-if="!showPasswordForm" class="text-center py-8">
              <p class="text-gray-500 mb-4">为了账户安全，建议定期修改密码</p>
              <button
                @click="showPasswordForm = true"
                class="px-6 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700"
              >
                修改密码
              </button>
            </div>

            <div v-else class="space-y-6">
              <div>
                <label class="block text-sm font-medium text-gray-700 mb-2">当前密码</label>
                <input
                  v-model="passwordForm.old_password"
                  type="password"
                  class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-red-500 focus:border-transparent"
                  placeholder="请输入当前密码"
                />
              </div>

              <div>
                <label class="block text-sm font-medium text-gray-700 mb-2">新密码</label>
                <input
                  v-model="passwordForm.new_password"
                  type="password"
                  class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-red-500 focus:border-transparent"
                  placeholder="请输入新密码（至少8个字符）"
                />
              </div>

              <div>
                <label class="block text-sm font-medium text-gray-700 mb-2">确认新密码</label>
                <input
                  v-model="passwordForm.confirm_password"
                  type="password"
                  class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-red-500 focus:border-transparent"
                  placeholder="请再次输入新密码"
                />
              </div>

              <div class="flex space-x-4">
                <button
                  @click="updatePassword"
                  :disabled="passwordSaving"
                  class="px-6 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 focus:ring-2 focus:ring-red-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {{ passwordSaving ? '修改中...' : '确认修改' }}
                </button>
                <button
                  @click="showPasswordForm = false; passwordForm = { old_password: '', new_password: '', confirm_password: '' }"
                  class="px-6 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300"
                >
                  取消
                </button>
              </div>
            </div>

            <!-- 危险操作 -->
            <div class="pt-6 border-t border-gray-200">
              <h3 class="text-lg font-semibold text-gray-900 mb-4">危险操作</h3>
              <button
                @click="handleLogout"
                class="w-full px-4 py-3 bg-red-600 text-white rounded-lg hover:bg-red-700 transition"
              >
                退出登录
              </button>
            </div>
          </div>
        </div>

        <!-- 统计信息 -->
        <div v-show="activeTab === 'stats'">
          <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div class="bg-gray-50 rounded-lg p-6 text-center">
              <div class="text-3xl font-bold text-red-600 mb-2">0</div>
              <div class="text-gray-600">已解决题目</div>
            </div>
            <div class="bg-gray-50 rounded-lg p-6 text-center">
              <div class="text-3xl font-bold text-green-600 mb-2">0</div>
              <div class="text-gray-600">提交次数</div>
            </div>
            <div class="bg-gray-50 rounded-lg p-6 text-center">
              <div class="text-3xl font-bold text-blue-600 mb-2">0%</div>
              <div class="text-gray-600">通过率</div>
            </div>
          </div>

          <div class="mt-6 p-4 bg-gray-50 rounded-lg">
            <h3 class="text-sm font-medium text-gray-700 mb-2">账户信息</h3>
            <div class="text-sm text-gray-600 space-y-1">
              <p>邮箱: {{ authStore.currentUser?.email }}</p>
              <p>注册时间: {{ formatDate(authStore.currentUser?.created_at || '') }}</p>
              <p>账户状态:
                <span v-if="authStore.currentUser?.is_active" class="text-green-600">已激活</span>
                <span v-else class="text-red-600">未激活</span>
              </p>
            </div>
          </div>
        </div>

        <!-- 奖项认证 -->
        <div v-show="activeTab === 'award'">
          <div class="space-y-6">
            <div class="p-4 bg-blue-50 rounded-lg border border-blue-200">
              <p class="text-sm text-blue-700">
                通过输入真实姓名在 OIerDB 中查询竞赛获奖记录，提交后由管理员审核，
                审核通过将在个人主页展示 OI 等级。
              </p>
            </div>

            <div v-if="certStatus === 'approved'" class="p-4 bg-green-50 rounded-lg border border-green-200">
              <p class="text-green-700 font-medium">认证已通过</p>
              <p class="text-green-600 mt-1">OI 等级：{{ oiLevel }}</p>
            </div>

            <div v-if="certStatus === 'pending'" class="p-4 bg-yellow-50 rounded-lg border border-yellow-200">
              <p class="text-yellow-700">认证申请审核中，请耐心等待管理员审核。</p>
              <button @click="cancelCert" class="mt-2 text-sm text-yellow-700 underline hover:text-yellow-900">
                撤回申请
              </button>
            </div>

            <div v-if="certStatus === 'rejected'" class="p-4 bg-red-50 rounded-lg border border-red-200">
              <p class="text-red-700">认证申请未通过，可重新提交。</p>
            </div>

            <div v-if="certStatus !== 'approved' && certStatus !== 'pending'">
              <div>
                <label class="block text-sm font-medium text-gray-700 mb-2">真实姓名</label>
                <input
                  v-model="realName"
                  type="text"
                  class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-red-500 focus:border-transparent"
                  placeholder="请输入真实姓名"
                />
              </div>

              <button
                @click="searchOierdb"
                :disabled="oierdbLoading"
                class="mt-3 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
              >
                {{ oierdbLoading ? '搜索中...' : '搜索 OIerDB' }}
              </button>

              <p v-if="oierdbError" class="mt-2 text-sm text-red-600">{{ oierdbError }}</p>

              <div v-if="oierdbResults.length" class="mt-4 space-y-2">
                <p class="text-sm text-gray-600">请选择匹配的条目：</p>
                <div
                  v-for="p in oierdbResults"
                  :key="p.id || p.uid || p.name"
                  @click="selectPerson(p)"
                  :class="`p-3 border rounded-lg cursor-pointer ${selectedPerson?.id === p.id || selectedPerson?.uid === p.uid ? 'border-red-500 bg-red-50' : 'border-gray-200 hover:border-gray-400'}`"
                >
                  <p class="font-medium text-gray-800">{{ p.name || p.real_name }}</p>
                  <p v-if="p.school" class="text-sm text-gray-500">{{ p.school }}</p>
                  <div v-if="p.awards?.length" class="mt-1 text-xs text-gray-600">
                    <span v-for="(a, i) in (p.awards || []).slice(0, 3)" :key="i" class="mr-2">
                      {{ a.contest || a.name }} {{ a.award || a.prize }}
                    </span>
                  </div>
                </div>
              </div>

              <button
                v-if="selectedPerson"
                @click="submitCert"
                :disabled="certSubmitting"
                class="mt-4 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
              >
                {{ certSubmitting ? '提交中...' : '提交认证申请' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 改名历史弹窗 -->
    <div
      v-if="showUsernameHistoryModal"
      class="fixed inset-0 bg-black/45 flex items-center justify-center z-50 p-4"
      @click.self="showUsernameHistoryModal = false"
    >
      <div class="bg-white rounded-xl shadow-xl w-full max-w-lg p-6">
        <div class="flex items-center justify-between mb-4 border-b pb-3">
          <h3 class="text-base font-bold text-gray-800 flex items-center gap-2">
            <i class="fa-solid fa-clock-rotate-left text-blue-600"></i> 改名历史记录
          </h3>
          <button @click="showUsernameHistoryModal = false" class="text-gray-400 hover:text-gray-600 text-lg cursor-pointer">
            &times;
          </button>
        </div>
        <div class="max-h-80 overflow-y-auto pr-1">
          <div v-if="usernameHistoryLoading" class="text-center py-8 text-gray-400 text-sm">
            加载中...
          </div>
          <div v-else-if="usernameHistoryList.length === 0" class="text-center py-8 text-gray-400 text-sm">
            暂无改名历史记录
          </div>
          <div v-else class="space-y-3">
            <div
              v-for="item in usernameHistoryList"
              :key="item.id"
              class="p-3 bg-gray-50 rounded-lg border border-gray-200 flex flex-col gap-1 text-sm"
            >
              <div class="flex items-center gap-2">
                <span class="text-gray-500 line-through">{{ item.old_username }}</span>
                <i class="fa-solid fa-arrow-right text-gray-400 text-xs"></i>
                <span class="font-bold text-blue-600">{{ item.new_username }}</span>
              </div>
              <div class="flex justify-between items-center text-xs text-gray-400 mt-1">
                <span>
                  操作人：
                  <strong :class="item.is_self ? 'text-green-600' : 'text-blue-600'">
                    {{ item.is_self ? '用户本人' : item.operator_name }}
                  </strong>
                </span>
                <span>{{ formatDate(item.created_at) }}</span>
              </div>
            </div>
          </div>
        </div>
        <div class="mt-6 flex justify-end">
          <button
            type="button"
            class="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg text-sm transition cursor-pointer"
            @click="showUsernameHistoryModal = false"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
