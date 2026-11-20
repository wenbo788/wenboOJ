<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import apiClient from '@/api/client'
import { userNameColor } from '@/utils/userColor'
import { getUserTagDisplay } from '@/utils/userTag'
import {
  isWhiteList,
  isSuperAdmin,
  isBigAdmin,
  isAnyAdmin,
} from '@/utils/permissions'

const router = useRouter()
const authStore = useAuthStore()

// 用户资料
const userProfile = ref({
  username: '',
  email: '',
  user_number: '',
  bio: '',
  avatar_url: '',
  user_tag: '',
  username_color: '',
  created_at: '',
  is_active: false,
  is_admin: false,            // 兼容保留，不再用于权限判断
  is_super_admin: false,
  is_big_admin: false,
  is_cheater: false,
  is_banned: false,
  can_speak: false,
  can_manage_users: false,
  can_manage_posts: false,
  can_manage_problems: false,
  can_manage_tags: false,
  academic_mode: false,
  phone: ''
} as any)

// ===== Tag 卡 =====
const tagCards = ref<any[]>([])
const tagCardsLoading = ref(false)

const loadTagCards = async () => {
  tagCardsLoading.value = true
  try {
    const data: any = await apiClient.get(`/users/me/tag-cards?_t=${Date.now()}`)
    tagCards.value = data.items || []
    if (userProfile.value) {
      userProfile.value.tag_cards = tagCards.value
    }
  } catch {
    tagCards.value = []
  } finally {
    tagCardsLoading.value = false
  }
}

const toggleTagCard = async (card: any) => {
  try {
    const updated: any = await apiClient.put(`/users/me/tag-cards/${card.id}/toggle`)
    await loadTagCards()
    await authStore.syncCurrentUser()
    await loadProfile()
    showMessage(updated.enabled ? `已佩戴「${card.name}」` : `已摘下「${card.name}」`, 'success')
  } catch (err: any) {
    showMessage(err.response?.data?.detail || '操作失败', 'error')
  }
}

const showTagHistoryModal = ref(false)
const tagHistoryList = ref<any[]>([])
const tagHistoryLoading = ref(false)

const openTagHistoryModal = async () => {
  if (!userProfile.value?.id) return
  showTagHistoryModal.value = true
  tagHistoryLoading.value = true
  try {
    const data: any = await apiClient.get(`/users/${userProfile.value.id}/tag-history`)
    tagHistoryList.value = data || []
  } catch {
    tagHistoryList.value = []
  } finally {
    tagHistoryLoading.value = false
  }
}


const isEditing = ref(false)
const editForm = ref({
  bio: ''
})

// ===== 用户名颜色购买 =====
const COLOR_TIER_LABEL: Record<string, string> = {
  gray: '灰名', blue: '蓝名', green: '绿名', orange: '橙名', red: '红名',
}

interface ColorTierView {
  tier: string
  label: string
  color: string
  desc: string
  requirement: { type: string; need: number; text: string } | null
  requirement_met: boolean
  price_exp: number
  price_contrib: number
  is_current: boolean
  eligible: boolean
  can_buy_exp: boolean
  can_buy_contrib: boolean
}
const colorTiersList = ref<ColorTierView[]>([])
const colorShopLoading = ref(false)
const colorPurchasing = ref(false)
const colorSolved = ref(0)
const colorOfficialSolved = ref(0)
const colorAuthored = ref(0)

const loadColorShop = async () => {
  colorShopLoading.value = true
  try {
    const data: any = await apiClient.get('/api/shop/colors')
    colorTiersList.value = data.colors || []
    colorSolved.value = data.solved || 0
    colorOfficialSolved.value = data.official_solved || 0
    colorAuthored.value = data.authored_official || 0
  } catch {
    colorTiersList.value = []
  } finally {
    colorShopLoading.value = false
  }
}

const purchaseColor = async (c: ColorTierView, currency: 'experience' | 'contribution') => {
  if (colorPurchasing.value || !c.eligible) return
  const currencyLabel = currency === 'experience' ? '经验' : '贡献'
  const price = currency === 'experience' ? c.price_exp : c.price_contrib
  colorPurchasing.value = true
  try {
    await apiClient.post('/api/shop/colors/purchase', { tier: c.tier, currency })
    showMessage(`已购买${c.label}（消耗 ${price} ${currencyLabel}）`, 'success')
    await Promise.all([loadColorShop(), loadProfile(), authStore.syncCurrentUser()])
  } catch (err: any) {
    showMessage(err.response?.data?.detail || '购买失败', 'error')
  } finally {
    colorPurchasing.value = false
  }
}

// 头部横幅上的用户名颜色：有购买/身份颜色时显示对应色，否则保持白色
const headerNameColor = computed(() => {
  const u = userProfile.value
  const hasIdentityColor = !!(u.is_banned || u.is_cheater || isAnyAdmin(u)
      || (u.color_tier && u.color_tier !== 'gray'))
  if (hasIdentityColor) {
    return userNameColor(u)
  }
  return '#ffffff'
})

// 实际生效的颜色名称：身份色优先（金/紫/青/深蓝/棕/黑），否则为购买档位名称
const effectiveColorLabel = computed(() => {
  const u = userProfile.value
  if (isSuperAdmin(u)) return '金名'
  if (isBigAdmin(u)) return '紫名'
  if (u.can_manage_problems) return '青名'
  if (u.can_manage_posts) return '深蓝名'
  if (u.is_cheater) return '棕名'
  if (u.is_banned) return '黑名'
  return colorTiersList.value.find(c => c.is_current)?.label
      || (COLOR_TIER_LABEL[u.color_tier] ?? '灰名')
})

const purchasedColorLabel = computed(
  () => colorTiersList.value.find(c => c.is_current)?.label
      || COLOR_TIER_LABEL[userProfile.value.color_tier] || '灰名')

const purchasedColorHex = computed(
  () => colorTiersList.value.find(c => c.is_current)?.color
      || '#95a5a6')

// ===== 头像上传 =====
const avatarUploading = ref(false)
const avatarInputRef = ref<HTMLInputElement | null>(null)

const pickAvatar = () => {
  if (avatarUploading.value) return
  avatarInputRef.value?.click()
}

const onAvatarChange = async (e: Event) => {
  const files = (e.target as HTMLInputElement).files
  if (!files || !files.length) return
  const file = files[0]

  if (!file.type.startsWith('image/')) {
    showMessage('请选择图片文件', 'error')
    return
  }
  if (file.size > 5 * 1024 * 1024) {
    showMessage('图片不能超过 5MB', 'error')
    return
  }

  avatarUploading.value = true
  const previousAvatar = userProfile.value.avatar_url || ''
  let failMsg = ''

  try {
    const fd = new FormData()
    fd.append('file', file)
    const res: any = await apiClient.post(`/users/me/avatar?_t=${Date.now()}`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    userProfile.value.avatar_url = res.avatar_url
  } catch (error: any) {
    failMsg = error.response?.data?.detail || ''
    try {
      const me: any = await apiClient.get(`/auth/me?_t=${Date.now()}`)
      if (me?.avatar_url && me.avatar_url !== previousAvatar) {
        userProfile.value.avatar_url = me.avatar_url
        failMsg = ''
      }
    } catch {
      /* 核实也失败则维持失败判定 */
    }
  }

  avatarUploading.value = false
  if (failMsg) {
    showMessage(failMsg || '头像上传失败，请稍后重试', 'error')
  } else {
    authStore.patchCurrentUser({ avatar_url: userProfile.value.avatar_url })
    showMessage('头像更新成功', 'success')
  }
  if (avatarInputRef.value) avatarInputRef.value.value = ''
}

// 加载状态
const loading = ref(false)
const saving = ref(false)

// 成功/失败消息
const message = ref('')
const messageType = ref<'success' | 'error'>('success')

// 计算头像显示
const avatarDisplay = computed(() => {
  if (userProfile.value.avatar_url) {
    return userProfile.value.avatar_url
  }
  const initial = userProfile.value.username?.charAt(0).toUpperCase() || 'U'
  return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Crect width='40' height='40' fill='%23e74c3c'/%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' dy='.3em' fill='white' font-size='16' font-family='Arial'%3E${encodeURIComponent(initial)}%3C/text%3E%3C/svg%3E`
})

// 格式化日期
const formatDate = (dateString: string) => {
  if (!dateString) return '未知'
  const date = new Date(dateString)
  return date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric'
  })
}

// 加载用户资料
const loadProfile = async () => {
  loading.value = true
  try {
    const response: any = await apiClient.get(`/auth/me?_t=${Date.now()}`)
    userProfile.value = response
    editForm.value = {
      bio: response.bio || ''
    }
    syncCertState(response)
  } catch (error: any) {
    console.error('加载用户资料失败:', error)
    showMessage('加载用户资料失败', 'error')
  } finally {
    loading.value = false
  }
}

// 开始编辑
const startEdit = () => {
  isEditing.value = true
  editForm.value = {
    bio: userProfile.value.bio || ''
  }
}

// 取消编辑
const cancelEdit = () => {
  isEditing.value = false
  editForm.value = {
    bio: userProfile.value.bio || ''
  }
}

// 保存资料
const saveProfile = async () => {
  if (saving.value) return

  saving.value = true
  try {
    const response: any = await apiClient.put('/users/me/profile', {
      bio: editForm.value.bio
    })

    userProfile.value = {
      ...userProfile.value,
      ...response
    }

    isEditing.value = false
    showMessage('资料更新成功', 'success')
  } catch (error: any) {
    const errorMsg = error.response?.data?.detail || '更新失败，请稍后重试'
    showMessage(errorMsg, 'error')
  } finally {
    saving.value = false
  }
}

// 显示消息
const showMessage = (msg: string, type: 'success' | 'error') => {
  message.value = msg
  messageType.value = type
  setTimeout(() => {
    message.value = ''
  }, 3000)
}

// ===== 学术模式（自律开关，不是权限）=====
const academicSaving = ref(false)
const toggleAcademicMode = async () => {
  if (academicSaving.value) return
  academicSaving.value = true
  const next = !userProfile.value.academic_mode

  let saved = next
  try {
    const res: any = await apiClient.put('/users/me/prefs', { academic_mode: next })
    // 以服务端回显为准（正常情况下就等于 next）：万一服务端做了别的处理，
    // 界面跟的是库里的值，而不是我们本地算出来的那个。
    if (typeof res?.academic_mode === 'boolean') saved = res.academic_mode
  } catch (err: any) {
    showMessage(err.response?.data?.detail || '操作失败', 'error')
    return
  } finally {
    // 放在 finally 里：无论上面是成功还是抛错都先放开按钮，
    // 免得中途一个意外异常把开关永久钉在禁用态。
    // 下面只剩本地同步，不再需要这个锁。
    academicSaving.value = false
  }

  // 到这里服务端已经存好了，下面全是本地同步 —— 不能再让它们的异常
  // 把「保存成功」报成「操作失败」，否则用户会重复点，界面也和服务端对不上。
  // 犇犇 / 灌水区 / 题目难度各处读的是 authStore.currentUser，
  // 所以先就地改一份让界面立刻生效，再在后台跟服务端对一次。
  userProfile.value.academic_mode = saved
  authStore.patchCurrentUser({ academic_mode: saved })
  // syncCurrentUser 内部失败会静默返回 null，这里再兜一层避免未处理的拒绝；
  // 同步挂了不影响界面（上面已按服务端值改好），只留个日志方便排查
  void authStore.syncCurrentUser().catch((err) => console.warn('同步用户信息失败', err))

  showMessage(
    saved
      ? '已开启学术模式：犇犇与灌水区已隐藏，题目难度默认收起'
      : '已关闭学术模式',
    'success',
  )
}

// ===== 安全设置（修改自己的密码） =====
const passwordForm = ref({
  old_password: '',
  new_password: '',
  confirm_password: ''
})
const changingPassword = ref(false)
const showPasswordForm = ref(false)

const changePassword = async () => {
  const { old_password, new_password, confirm_password } = passwordForm.value

  if (!old_password || !new_password || !confirm_password) {
    showMessage('请填写完整', 'error')
    return
  }
  if (new_password.length < 8) {
    showMessage('新密码至少需要 8 位', 'error')
    return
  }
  if (new_password === old_password) {
    showMessage('新密码不能与旧密码相同', 'error')
    return
  }
  if (new_password !== confirm_password) {
    showMessage('两次输入的新密码不一致', 'error')
    return
  }

  changingPassword.value = true
  try {
    await apiClient.put('/users/me/password', { old_password, new_password })
    passwordForm.value = { old_password: '', new_password: '', confirm_password: '' }
    showPasswordForm.value = false
    showMessage('密码修改成功', 'success')
  } catch (error: any) {
    showMessage(error.response?.data?.detail || '修改失败，请稍后重试', 'error')
  } finally {
    changingPassword.value = false
  }
}

// 退出登录
const handleLogout = () => {
  authStore.logout()
  router.push('/login')
}

// ===== 更换邮箱 =====
const showEmailForm = ref(false)
const emailForm = ref({ new_email: '', code: '' })
const emailToken = ref('')
const emailCodeSent = ref(false)
const sendingEmailCode = ref(false)
const changingEmail = ref(false)
const emailCountdown = ref(0)

const sendEmailCode = async () => {
  const addr = emailForm.value.new_email.trim()
  if (!addr) {
    showMessage('请输入新邮箱地址', 'error')
    return
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(addr)) {
    showMessage('邮箱格式不正确', 'error')
    return
  }
  sendingEmailCode.value = true
  try {
    const res: any = await apiClient.post('/auth/change-email/send-code', { email: addr })
    emailToken.value = res.token
    emailCodeSent.value = true
    emailCountdown.value = 60
    const timer = setInterval(() => {
      emailCountdown.value--
      if (emailCountdown.value <= 0) {
        clearInterval(timer)
      }
    }, 1000)
    showMessage('验证码已发送到新邮箱', 'success')
  } catch (e: any) {
    showMessage(e.response?.data?.detail || '发送验证码失败', 'error')
  } finally {
    sendingEmailCode.value = false
  }
}

const changeEmail = async () => {
  if (!emailCodeSent.value) {
    showMessage('请先获取验证码', 'error')
    return
  }
  if (!emailForm.value.code || emailForm.value.code.length !== 6) {
    showMessage('请输入6位验证码', 'error')
    return
  }
  changingEmail.value = true
  try {
    const res: any = await apiClient.post('/auth/change-email/confirm', {
      token: emailToken.value,
      code: emailForm.value.code
    })
    userProfile.value.email = res.email
    authStore.patchCurrentUser({ email: res.email })
    emailForm.value = { new_email: '', code: '' }
    emailCodeSent.value = false
    showEmailForm.value = false
    showMessage('邮箱更换成功', 'success')
  } catch (e: any) {
    showMessage(e.response?.data?.detail || '更换邮箱失败', 'error')
  } finally {
    changingEmail.value = false
  }
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

const syncCertState = (u: any) => {
  realName.value = u?.real_name || ''
  certStatus.value = u?.award_cert_status || 'none'
  oiLevel.value = u?.oi_level || ''
}

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
    const data: any = await apiClient.get('/api/users/oierdb/search', { params: { name } })
    if (data?.error) {
      oierdbError.value = data.error
    } else {
      oierdbResults.value = Array.isArray(data?.items) ? data.items : []
      if (oierdbResults.value.length === 0) {
        oierdbError.value = '未找到匹配的人员'
      }
    }
  } catch (e: any) {
    oierdbError.value = e.response?.data?.detail || '搜索失败，请稍后重试'
  } finally {
    oierdbLoading.value = false
  }
}

const selectPerson = (p: any) => {
  selectedPerson.value = p
}

const awardsOf = (p: any): any[] => {
  if (!p) return []
  if (Array.isArray(p.awards) && p.awards.length) return p.awards
  if (Array.isArray(p.records) && p.records.length) return p.records
  return [p]
}

const submitCert = async () => {
  if (!selectedPerson.value) {
    showMessage('请选择一个 OIerDB 条目', 'error')
    return
  }
  certSubmitting.value = true
  try {
    const p = selectedPerson.value
    await apiClient.post('/api/users/me/award-certification', {
      real_name: realName.value.trim(),
      oierdb_uid: String(p.id ?? p.uid ?? ''),
      oi_awards: awardsOf(p)
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
    oierdbResults.value = []
    showMessage('已撤回认证申请', 'success')
  } catch (e: any) {
    showMessage(e.response?.data?.detail || '撤回失败', 'error')
  }
}

// 组件挂载时加载资料
onMounted(() => {
  loadProfile()
  loadTagCards()
  loadColorShop()
  syncCertState(authStore.currentUser)
})
</script>

<template>
  <div class="profile-page">
    <div class="profile-container">
      <!-- 头部 -->
      <div class="profile-header">
        <div class="avatar-section">
          <div class="avatar-wrapper avatar-clickable" title="点击更换头像" @click="pickAvatar">
            <img
              :src="avatarDisplay"
              :alt="userProfile.username"
              class="avatar"
              onerror="this.onerror=null;this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 40 40%22%3E%3Crect width=%2240%22 height=%2240%22 fill=%22%23e74c3c%22/%3E%3Ctext x=%2250%25%22 y=%2250%25%22 text-anchor=%22middle%22 dy=%22.3em%22 fill=%22white%22 font-size=%2216%22 font-family=%22Arial%22%3EU%3C/text%3E%3C/svg%3E'"
            />
            <div v-if="avatarUploading" class="avatar-overlay">上传中…</div>
            <div v-else class="avatar-overlay avatar-overlay-hover"><i class="fa-solid fa-camera"></i> 更换</div>
            <div v-if="isAnyAdmin(userProfile)" class="admin-badge">管理员</div>
          </div>
          <input
            ref="avatarInputRef"
            type="file"
            accept="image/jpeg,image/png,image/gif,image/webp"
            style="display: none"
            @change="onAvatarChange"
          >
        </div>

        <div class="user-info">
          <h1 class="username" :style="{ color: headerNameColor }">
            {{ userProfile.username }}
          </h1>
          <div class="user-meta">
            <span class="uid">UID: {{ userProfile.user_number }}</span>
            <span v-if="getUserTagDisplay(userProfile)" class="user-tag">{{ getUserTagDisplay(userProfile) }}</span>
          </div>
          <p v-if="userProfile.bio" class="bio">{{ userProfile.bio }}</p>
          <p v-else class="bio empty">这个人很懒，还没有填写个人简介</p>
        </div>

        <div class="actions">
          <button v-if="!isEditing" @click="startEdit" class="btn-edit">
            编辑资料
          </button>
          <div v-else class="edit-actions">
            <button @click="saveProfile" :disabled="saving" class="btn-save">
              {{ saving ? '保存中...' : '保存' }}
            </button>
            <button @click="cancelEdit" :disabled="saving" class="btn-cancel">
              取消
            </button>
          </div>
          <button @click="handleLogout" class="btn-logout">
            退出登录
          </button>
        </div>
      </div>

      <!-- 消息提示 -->
      <div v-if="message" :class="['message', messageType]">
        {{ message }}
      </div>

      <!-- 编辑表单 -->
      <div v-if="isEditing" class="edit-form">
        <div class="form-group">
          <label>个人简介</label>
          <textarea
            v-model="editForm.bio"
            rows="3"
            class="form-textarea"
            placeholder="介绍一下自己..."
            maxlength="200"
          />
          <span class="char-count">{{ editForm.bio.length }}/200</span>
        </div>

        <div class="form-group">
          <label>头像</label>
          <p class="avatar-hint">直接点击左上角头像即可上传新头像（支持 jpg/png/gif/webp，5MB 以内）</p>
        </div>
      </div>
    </div>

    <!-- Tag 卡 -->
    <div class="card settings-card">
      <div class="section-head" style="justify-content: space-between;">
        <div style="display: flex; gap: 14px; align-items: center;">
          <span class="section-icon"><i class="fa-solid fa-id-badge"></i></span>
          <div class="section-head-text">
            <h2 class="section-title">Tag 卡</h2>
            <p class="section-sub">点击佩戴显示在用户名旁，同一时间只能佩戴一张</p>
          </div>
        </div>
        <button type="button" class="history-pill-btn" @click="openTagHistoryModal">
          <i class="fa-solid fa-clock-rotate-left"></i> Tag 变动记录
        </button>
      </div>
      <div v-if="tagCardsLoading" class="tag-empty">加载中...</div>
      <div v-else-if="tagCards.length === 0" class="tag-empty">
        暂无 Tag 卡——被授予 Tag 后会出现在这里
      </div>
      <div v-else class="tag-cards-list">
        <div
          v-for="card in tagCards"
          :key="card.id"
          class="tag-card-item"
          :class="{ enabled: card.enabled }"
        >
          <div class="tag-card-content">
            <span class="tag-card-name" :class="{ enabled: card.enabled }">{{ card.name }}</span>
            <span class="tag-card-source">
              {{ card.granter_name ? `由 ${card.granter_name} 授予` : '商店兑换/系统' }}
              <template v-if="card.created_at"> · {{ formatDate(card.created_at) }}</template>
            </span>
          </div>
          <button
            class="tag-toggle"
            :class="{ enabled: card.enabled }"
            @click="toggleTagCard(card)"
          >
            {{ card.enabled ? '摘下' : '佩戴' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 用户名颜色 -->
    <div class="card settings-card">
      <div class="section-head">
        <span class="section-icon"><i class="fa-solid fa-palette"></i></span>
        <div class="section-head-text">
          <h2 class="section-title">用户名颜色</h2>
          <p class="section-sub">逐级购买升级；每档可用经验或贡献购买，二选一。身份颜色（金/紫/青/深蓝/棕/黑）优先显示。</p>
        </div>
      </div>

      <div class="color-summary">
        <span>当前：<b :style="{ color: userNameColor(userProfile) }">
          {{ effectiveColorLabel }}
        </b></span>
        <span>购买档位：<b :style="{ color: purchasedColorHex }">{{ purchasedColorLabel }}</b></span>
        <span>已通过题目：<b>{{ colorSolved }}</b> 道</span>
        <span>其中主题库：<b>{{ colorOfficialSolved }}</b> 道</span>
        <span>出题（已公开）：<b>{{ colorAuthored }}</b> 道</span>
      </div>

      <div v-if="colorShopLoading" class="tag-empty">加载中...</div>
      <div v-else class="color-list">
        <div
          v-for="c in colorTiersList"
          :key="c.tier"
          class="color-row"
          :class="{ current: c.is_current }"
        >
          <span class="color-dot" :style="{ background: c.color }"></span>
          <div class="color-info">
            <div class="color-label">
              <span :style="{ color: c.color }">{{ c.label }}</span>
              <span v-if="c.is_current" class="color-current-badge">已购</span>
            </div>
            <div class="color-desc">{{ c.desc }}</div>
            <div v-if="c.requirement" class="color-req" :class="c.requirement_met ? 'met' : 'unmet'">
              <i :class="c.requirement_met ? 'fa-solid fa-circle-check' : 'fa-solid fa-circle-xmark'"></i>
              {{ c.requirement.text }}
            </div>
          </div>
          <div v-if="!c.is_current" class="color-actions">
            <button
              class="color-buy"
              :disabled="colorPurchasing || !c.can_buy_exp"
              :title="c.requirement_met ? (c.can_buy_exp ? '' : '经验不足') : c.requirement?.text"
              @click="purchaseColor(c, 'experience')"
            >
              {{ c.price_exp.toLocaleString('zh-CN') }} 经验
            </button>
            <button
              class="color-buy secondary"
              :disabled="colorPurchasing || !c.can_buy_contrib"
              :title="c.requirement_met ? (c.can_buy_contrib ? '' : '贡献不足') : c.requirement?.text"
              @click="purchaseColor(c, 'contribution')"
            >
              {{ c.price_contrib.toLocaleString('zh-CN') }} 贡献
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 学术模式 -->
    <div class="card settings-card">
      <div class="section-head">
        <span class="section-icon"><i class="fa-solid fa-graduation-cap"></i></span>
        <div class="section-head-text">
          <h2 class="section-title">学术模式</h2>
          <p class="section-sub">
            开启后隐藏犇犇与灌水区，题目难度默认隐藏（可在题库页手动展开）。只影响你自己的界面，随时可关。
          </p>
        </div>
        <button
          type="button"
          class="academic-switch"
          :class="{ on: userProfile.academic_mode }"
          :disabled="academicSaving"
          role="switch"
          :aria-checked="userProfile.academic_mode"
          :aria-label="userProfile.academic_mode ? '关闭学术模式' : '开启学术模式'"
          @click="toggleAcademicMode"
        >
          <span class="academic-switch-knob"></span>
        </button>
      </div>
    </div>

    <!-- 账户信息 -->
    <div class="card settings-card">
      <div class="section-head">
        <span class="section-icon"><i class="fa-solid fa-address-card"></i></span>
        <h2 class="section-title">账户信息</h2>
      </div>
      <div class="info-grid">
        <div class="info-item">
          <span class="info-label">邮箱</span>
          <span class="info-value">
            {{ userProfile.email }}
            <button class="gc-inline-link" @click="showEmailForm = !showEmailForm">
              {{ showEmailForm ? '取消' : '更换邮箱' }}
            </button>
          </span>
        </div>
        <div class="info-item">
          <span class="info-label">手机号</span>
          <span class="info-value">{{ userProfile.phone || '未绑定' }}</span>
        </div>
        <div class="info-item">
          <span class="info-label">注册时间</span>
          <span class="info-value">{{ formatDate(userProfile.created_at) }}</span>
        </div>
        <div class="info-item">
          <span class="info-label">账户状态</span>
          <span class="info-value" :class="userProfile.is_active ? 'status-active' : 'status-inactive'">
            {{ userProfile.is_active ? '已激活' : '未激活' }}
          </span>
        </div>
        <div class="info-item">
          <span class="info-label">发言权限</span>
          <span class="info-value" :class="userProfile.can_speak ? 'status-active' : 'status-inactive'">
            {{ userProfile.can_speak ? '已启用' : '已禁用' }}
          </span>
        </div>
      </div>

      <form v-if="showEmailForm" class="password-form" @submit.prevent="changeEmail">
        <div class="form-group">
          <label>新邮箱</label>
          <div class="input-row">
            <input
              v-model="emailForm.new_email"
              type="email"
              class="form-input flex-input"
              placeholder="请输入新邮箱地址"
              :disabled="emailCodeSent"
            />
            <button
              type="button"
              class="btn-change-password"
              :disabled="sendingEmailCode || emailCountdown > 0"
              @click="sendEmailCode"
            >
              {{ emailCountdown > 0 ? `${emailCountdown}秒后重发` : (sendingEmailCode ? '发送中…' : (emailCodeSent ? '重新发送' : '获取验证码')) }}
            </button>
          </div>
        </div>
        <div class="form-group" v-if="emailCodeSent">
          <label>验证码</label>
          <input
            v-model="emailForm.code"
            class="form-input"
            placeholder="请输入 6 位验证码"
            maxlength="6"
          />
        </div>
        <div class="password-actions">
          <button type="submit" :disabled="changingEmail || !emailCodeSent" class="btn-save">
            {{ changingEmail ? '提交中...' : '确认更换' }}
          </button>
          <button type="button" :disabled="changingEmail" class="btn-cancel" @click="showEmailForm = false">
            取消
          </button>
        </div>
      </form>
    </div>

    <!-- 安全设置 -->
    <div class="card settings-card">
      <div class="section-head">
        <span class="section-icon"><i class="fa-solid fa-shield-halved"></i></span>
        <div class="section-head-text">
          <h2 class="section-title">安全设置</h2>
          <p class="section-sub">为了账号安全，请定期更换密码。密码需至少 8 位。</p>
        </div>
      </div>

      <button v-if="!showPasswordForm" class="btn-change-password" @click="showPasswordForm = true">
        修改密码
      </button>

      <form v-else class="password-form" @submit.prevent="changePassword">
        <div class="form-group">
          <label>当前密码</label>
          <input
            v-model="passwordForm.old_password"
            type="password"
            class="form-input"
            placeholder="请输入当前密码"
            autocomplete="current-password"
            required
          />
        </div>
        <div class="form-group">
          <label>新密码</label>
          <input
            v-model="passwordForm.new_password"
            type="password"
            class="form-input"
            placeholder="至少 8 位"
            maxlength="72"
            autocomplete="new-password"
            required
          />
        </div>
        <div class="form-group">
          <label>确认新密码</label>
          <input
            v-model="passwordForm.confirm_password"
            type="password"
            class="form-input"
            placeholder="再次输入新密码"
            maxlength="72"
            autocomplete="new-password"
            required
          />
        </div>
        <div class="password-actions">
          <button type="submit" :disabled="changingPassword" class="btn-save">
            {{ changingPassword ? '提交中...' : '确认修改' }}
          </button>
          <button type="button" :disabled="changingPassword" class="btn-cancel" @click="showPasswordForm = false">
            取消
          </button>
        </div>
      </form>
    </div>

    <!-- 奖项认证 -->
    <div class="card settings-card">
      <div class="section-head">
        <span class="section-icon"><i class="fa-solid fa-award"></i></span>
        <div class="section-head-text">
          <h2 class="section-title">奖项认证</h2>
          <p class="section-sub">输入真实姓名在 OIerDB 中查询竞赛获奖记录，提交后由管理员审核，通过后在个人主页展示 OI 等级</p>
        </div>
      </div>

      <div v-if="certStatus === 'approved'" class="cert-box approved">
        <p class="cert-line"><strong>认证已通过</strong></p>
        <p class="cert-line">OI 等级：{{ oiLevel || '—' }}</p>
      </div>

      <div v-else-if="certStatus === 'pending'" class="cert-box pending">
        <p class="cert-line">认证申请审核中，请耐心等待管理员审核。</p>
        <button class="gc-inline-link" @click="cancelCert">撤回申请</button>
      </div>

      <div v-else>
        <div v-if="certStatus === 'rejected'" class="cert-box rejected">
          <p class="cert-line">上次认证申请未通过，可修改后重新提交。</p>
        </div>

        <div class="form-group">
          <label>真实姓名</label>
          <input
            v-model="realName"
            class="form-input"
            placeholder="请输入真实姓名"
            maxlength="50"
          />
        </div>

        <button class="btn-change-password" :disabled="oierdbLoading" @click="searchOierdb">
          {{ oierdbLoading ? '搜索中…' : '搜索 OIerDB' }}
        </button>

        <p v-if="oierdbError" class="cert-error">{{ oierdbError }}</p>

        <div v-if="oierdbResults.length" class="cert-results">
          <p class="cert-hint">请选择匹配的条目：</p>
          <div
            v-for="(p, i) in oierdbResults"
            :key="p.id ?? p.uid ?? i"
            class="cert-item"
            :class="{ selected: selectedPerson === p }"
            @click="selectPerson(p)"
          >
            <p class="cert-item-name">{{ p.name || p.real_name || '未知' }}</p>
            <p v-if="p.school" class="cert-item-sub">{{ p.school }}</p>
            <div v-if="(p.awards || p.records || []).length" class="cert-item-awards">
              <span v-for="(a, j) in (p.awards || p.records || []).slice(0, 3)" :key="j">
                {{ a.contest || a.name }} {{ a.award || a.prize }}
              </span>
            </div>
          </div>
        </div>

        <button
          v-if="selectedPerson"
          class="btn-change-password cert-submit"
          :disabled="certSubmitting"
          @click="submitCert"
        >
          {{ certSubmitting ? '提交中…' : '提交认证申请' }}
        </button>
      </div>
    </div>

    <!-- 权限信息 -->
    <div v-if="isAnyAdmin(userProfile)" class="card settings-card">
      <div class="section-head">
        <span class="section-icon"><i class="fa-solid fa-user-shield"></i></span>
        <h2 class="section-title">管理权限</h2>
      </div>
      <div class="permissions-grid">
        <div v-if="isSuperAdmin(userProfile)" class="permission-item">
          <span class="permission-label">超级管理员</span>
          <span class="permission-value">✓</span>
        </div>
        <div v-if="isBigAdmin(userProfile)" class="permission-item">
          <span class="permission-label">大管理员</span>
          <span class="permission-value">✓</span>
        </div>
        <div v-if="userProfile.can_manage_problems" class="permission-item">
          <span class="permission-label">题目管理员</span>
          <span class="permission-value">✓</span>
        </div>
        <div v-if="userProfile.can_manage_posts" class="permission-item">
          <span class="permission-label">社区管理员</span>
          <span class="permission-value">✓</span>
        </div>
      </div>
    </div>

    <!-- Tag 变动历史弹窗 -->
    <div
      v-if="showTagHistoryModal"
      class="fixed inset-0 bg-black/45 flex items-center justify-center z-50 p-4"
      @click.self="showTagHistoryModal = false"
    >
      <div class="bg-white rounded-xl shadow-xl w-full max-w-lg p-6">
        <div class="flex items-center justify-between mb-4 border-b pb-3">
          <h3 class="text-base font-bold text-gray-800 flex items-center gap-2">
            <i class="fa-solid fa-tags text-blue-600"></i> Tag 变动历史记录
          </h3>
          <button @click="showTagHistoryModal = false" class="text-gray-400 hover:text-gray-600 text-lg cursor-pointer">
            &times;
          </button>
        </div>
        <div class="max-h-80 overflow-y-auto pr-1">
          <div v-if="tagHistoryLoading" class="text-center py-8 text-gray-400 text-sm">
            加载中...
          </div>
          <div v-else-if="tagHistoryList.length === 0" class="text-center py-8 text-gray-400 text-sm">
            暂无 Tag 变动记录
          </div>
          <div v-else class="space-y-3">
            <div
              v-for="item in tagHistoryList"
              :key="item.id"
              class="p-3 bg-gray-50 rounded-lg border border-gray-200 flex flex-col gap-1 text-sm"
            >
              <div class="flex items-center gap-2">
                <span
                  class="text-xs px-2 py-0.5 rounded font-semibold"
                  :class="{
                    'bg-green-100 text-green-700': item.action === 'grant',
                    'bg-red-100 text-red-700': item.action === 'revoke',
                    'bg-purple-100 text-purple-700': item.action === 'custom_tag',
                    'bg-amber-100 text-amber-700': item.action === 'shop_redeem',
                  }"
                >
                  {{ item.action_label }}
                </span>
                <span class="font-bold text-gray-800">「{{ item.tag_name }}」</span>
              </div>
              <div class="flex justify-between items-center text-xs text-gray-400 mt-1">
                <span>
                  操作人：<strong class="text-blue-600">{{ item.operator_name }}</strong>
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
            @click="showTagHistoryModal = false"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ============ 样式完全保持原样，未改动 ============ */

.profile-page {
  min-height: 100vh;
  padding: 20px;
}

.profile-container {
  max-width: 900px;
  margin: 0 auto 16px;
  background: var(--surface);
  -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}

.settings-card {
  max-width: 900px;
  margin: 0 auto 16px;
  padding: 22px 26px;
}

.settings-card:last-child {
  margin-bottom: 0;
}

.section-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.section-icon {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: color-mix(in srgb, var(--primary) 10%, transparent);
  color: var(--primary);
  font-size: 14px;
}

.section-head-text {
  min-width: 0;
}

.section-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-main);
  margin: 0;
}

.section-sub {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--text-sub);
}

/* 学术模式开关：靠右，与卡片标题同一行 */
.academic-switch {
  position: relative;
  flex: none;
  margin-left: auto;
  width: 44px;
  height: 24px;
  padding: 0;
  border: none;
  border-radius: 12px;
  background: var(--border, #d0d7de);
  cursor: pointer;
  transition: background 0.2s;
}

.academic-switch:disabled {
  opacity: 0.6;
  cursor: default;
}

.academic-switch.on {
  background: var(--primary);
}

.academic-switch-knob {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #fff;
  transition: transform 0.2s;
}

.academic-switch.on .academic-switch-knob {
  transform: translateX(20px);
}

.profile-header {
  background:
    radial-gradient(circle at 88% -30%, rgba(255, 255, 255, 0.28), transparent 55%),
    linear-gradient(135deg, var(--primary) 0%, var(--primary-hover) 100%);
  padding: 32px;
  color: white;
  display: flex;
  gap: 24px;
  align-items: center;
}

.avatar-section {
  flex-shrink: 0;
}

.avatar-wrapper {
  position: relative;
  display: inline-block;
}

.avatar-clickable {
  cursor: pointer;
}

.avatar-overlay {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 2px 0;
  text-align: center;
  font-size: 11px;
  color: #fff;
  background: rgba(0, 0, 0, 0.55);
  border-radius: 0 0 80px 80px;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.2s;
}

.avatar-clickable:hover .avatar-overlay-hover,
.avatar-overlay:not(.avatar-overlay-hover) {
  opacity: 1;
}

.avatar-hint {
  color: var(--text-sub);
  font-size: 13px;
}

.avatar {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  border: 4px solid white;
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.25);
  object-fit: cover;
  transition: transform 0.2s ease;
}

.avatar-clickable:hover .avatar {
  transform: scale(1.03);
}

.admin-badge {
  position: absolute;
  bottom: -4px;
  right: -8px;
  background: #f59e0b;
  color: white;
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 12px;
  border: 2px solid white;
  font-weight: 600;
}

.user-info {
  flex: 1;
  min-width: 0;
}

.username {
  font-size: 24px;
  font-weight: 700;
  margin: 0 0 8px 0;
  color: white;
}

.user-meta {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.uid {
  background: rgba(255, 255, 255, 0.2);
  padding: 4px 12px;
  border-radius: 16px;
  font-size: 13px;
  font-weight: 500;
}

.history-pill-btn {
  border: 1px solid var(--border-color, #cbd5e1);
  background: var(--surface-strong, #fff);
  color: var(--primary, #3b82f6);
  padding: 5px 14px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s ease;
}
.history-pill-btn:hover {
  background: var(--primary, #3b82f6);
  color: #fff;
  border-color: var(--primary, #3b82f6);
}

.tag-cards-list { display: flex; flex-wrap: wrap; gap: 12px; }
.tag-card-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md, 12px);
  padding: 10px 14px;
  background: var(--surface-strong);
  min-width: 220px;
}
.tag-card-item.enabled {
  border-color: color-mix(in srgb, var(--primary) 45%, transparent);
  background: color-mix(in srgb, var(--primary) 8%, transparent);
}
.tag-card-content {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.tag-card-name { font-size: 14px; font-weight: 600; color: var(--text-sub); }
.tag-card-name.enabled { color: var(--primary); }
.tag-card-source {
  font-size: 11px;
  color: var(--text-sub);
  opacity: 0.85;
}
.tag-toggle {
  border: none;
  border-radius: 999px;
  padding: 5px 14px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  background: rgba(148, 163, 184, 0.22);
  color: var(--text-main);
  transition: background 0.15s ease, color 0.15s ease;
  flex-shrink: 0;
}
.tag-toggle:hover { background: rgba(148, 163, 184, 0.34); }
.tag-toggle.enabled { background: var(--primary); color: #fff; }
.tag-toggle.enabled:hover { background: var(--primary-hover); }

.color-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  font-size: 13px;
  color: var(--text-sub);
  margin-bottom: 14px;
}
.color-summary b { color: var(--text-main); font-weight: 700; }

.color-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.color-row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 14px;
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--surface-strong);
}
.color-row.current {
  border-color: color-mix(in srgb, var(--primary) 40%, transparent);
  background: color-mix(in srgb, var(--primary) 6%, transparent);
}

.color-dot {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  flex-shrink: 0;
  border: 2px solid #fff;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.12);
}

.color-info { flex: 1; min-width: 0; }
.color-label {
  font-size: 14px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 8px;
}
.color-current-badge {
  font-size: 11px;
  font-weight: 600;
  color: var(--primary);
  border: 1px solid color-mix(in srgb, var(--primary) 40%, transparent);
  border-radius: 999px;
  padding: 0 8px;
}
.color-desc { font-size: 12px; color: var(--text-sub); margin-top: 2px; }
.color-req {
  font-size: 12px;
  margin-top: 4px;
  display: flex;
  align-items: center;
  gap: 5px;
}
.color-req.met {color: light-dark(#10b981, #34d399); }
.color-req.unmet { color: #94a3b8; }

.color-actions {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex-shrink: 0;
}

.color-buy {
  border: none;
  border-radius: 999px;
  padding: 6px 16px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  background: var(--primary);
  color: #fff;
  transition: background 0.15s ease;
}
.color-buy:hover:not(:disabled) { background: var(--primary-hover); }
.color-buy.secondary {
  background: #f59e0b;
}
.color-buy.secondary:hover:not(:disabled) { background: #d97706; }
.color-buy:disabled {
  background: rgba(148, 163, 184, 0.35);
  color: var(--text-sub);
  cursor: not-allowed;
}

.tag-empty {
  padding: 22px 16px;
  text-align: center;
  font-size: 13px;
  color: var(--text-sub);
  background: var(--surface-strong);
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-md);
}

.user-tag {
  background: rgba(255, 255, 255, 0.2);
  padding: 4px 12px;
  border-radius: 16px;
  font-size: 13px;
}

.bio {
  font-size: 14px;
  line-height: 1.5;
  opacity: 0.9;
  margin: 0;
  max-width: 500px;
}

.bio.empty {
  opacity: 0.6;
  font-style: italic;
}

.actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}

.btn-edit {
  padding: 8px 16px;
  background: var(--surface-plain);
  color: var(--primary);
  border: none;
  border-radius: 20px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-edit:hover {
  background: var(--surface-plain);
  transform: translateY(-1px);
}

.edit-actions {
  display: flex;
  gap: 8px;
  flex-direction: column;
}

.btn-save {
  padding: 8px 16px;
  background: var(--surface-plain);
  color: var(--primary);
  border: none;
  border-radius: 20px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-save:hover:not(:disabled) {
  background: var(--surface-plain);
  transform: translateY(-1px);
}

.btn-save:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-cancel {
  padding: 8px 16px;
  background: rgba(255, 255, 255, 0.2);
  color: white;
  border: none;
  border-radius: 20px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-cancel:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.3);
}

.btn-logout {
  padding: 8px 16px;
  background: rgba(255, 255, 255, 0.2);
  color: white;
  border: none;
  border-radius: 20px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-logout:hover {
  background: rgba(255, 255, 255, 0.3);
}

.message {
  margin: 20px 32px;
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
  text-align: center;
  animation: slideDown 0.3s ease-out;
}

.message.success {
  background: color-mix(in srgb, var(--success) 10%, transparent);
color: var(--success-text);
  border: 1px solid #a7f3d0;
}

.message.error {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
color: var(--danger-text);
  border: 1px solid #fecaca;
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

.edit-form {
  padding: 32px;
}

.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-strong);
  margin-bottom: 8px;
}

.form-input,
.form-textarea {
  width: 100%;
  padding: 10px 12px;
  border: var(--border-width) solid var(--border-color);
  background: var(--surface-strong);
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-family: inherit;
  color: var(--text-main);
  transition: border-color 0.2s, box-shadow 0.2s;
}

.form-input:focus,
.form-textarea:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 15%, transparent);
}

.form-textarea {
  resize: vertical;
  min-height: 80px;
}

.char-count {
  display: block;
  text-align: right;
  font-size: 12px;
  color: var(--text-sub);
  margin-top: 4px;
}

.btn-change-password {
  padding: 9px 22px;
  background: var(--primary);
  color: white;
  border: none;
  border-radius: 999px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.btn-change-password:hover {
  background: var(--primary-hover);
}

.btn-change-password:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.input-row {
  display: flex;
  gap: 10px;
  align-items: center;
}

.input-row .btn-change-password {
  white-space: nowrap;
}

.flex-input {
  flex: 1;
  min-width: 0;
}

.password-form {
  max-width: 420px;
}

.password-actions {
  display: flex;
  gap: 10px;
  margin-top: 4px;
}

.password-actions .btn-save {
  background: var(--primary);
  color: white;
}

.password-actions .btn-save:hover:not(:disabled) {
  background: var(--primary-hover);
}

.password-actions .btn-cancel {
  background: rgba(148, 163, 184, 0.2);
  color: var(--text-main);
}

.password-actions .btn-cancel:hover:not(:disabled) {
  background: rgba(148, 163, 184, 0.32);
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 16px;
}

.info-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 13px 16px;
  background: var(--surface-strong);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
}

.info-label {
  font-size: 13px;
  color: var(--text-sub);
  font-weight: 500;
  flex-shrink: 0;
}

.info-value {
  font-size: 14px;
  color: var(--text-main);
  font-weight: 600;
  text-align: right;
  word-break: break-all;
}

.status-active {
color: light-dark(#10b981, #34d399);
  font-weight: 600;
}

.status-inactive {
  color: #ef4444;
  font-weight: 600;
}

.permissions-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
}

.permission-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: color-mix(in srgb, var(--warning) 12%, transparent);
  border-radius: var(--radius-md);
  border: 1px solid #fde68a;
}

.permission-label {
  font-size: 14px;
  color: var(--warning-text);
  font-weight: 500;
}

.permission-value {
  font-size: 18px;
  color: var(--warning-text);
  font-weight: 700;
}

.cert-box {
  padding: 12px 14px;
  border-radius: var(--radius-md);
  margin-bottom: 14px;
  font-size: 14px;
}
.cert-box.approved { background: color-mix(in srgb, var(--success) 10%, transparent);color: var(--success-text); border: 1px solid #a7f3d0; }
.cert-box.pending { background: color-mix(in srgb, var(--warning) 12%, transparent);color: var(--warning-text); border: 1px solid #fde68a; }
.cert-box.rejected { background: color-mix(in srgb, var(--danger) 10%, transparent);color: var(--danger-text); border: 1px solid #fecaca; }
.cert-line { margin: 0 0 4px; }
.cert-error { margin-top: 8px; font-size: 13px; color: #ef4444; }
.cert-hint { margin: 14px 0 8px; font-size: 13px; color: var(--text-sub); }
.cert-results { display: flex; flex-direction: column; gap: 8px; margin-top: 4px; }
.cert-item {
  padding: 10px 14px;
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--surface-strong);
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.cert-item:hover { border-color: var(--primary); }
.cert-item.selected { border-color: var(--primary); background: color-mix(in srgb, var(--primary) 8%, transparent); }
.cert-item-name { margin: 0; font-size: 14px; font-weight: 600; color: var(--text-main); }
.cert-item-sub { margin: 2px 0 0; font-size: 12px; color: var(--text-sub); }
.cert-item-awards { margin-top: 4px; font-size: 12px; color: var(--text-sub); display: flex; flex-wrap: wrap; gap: 10px; }
.cert-submit { margin-top: 14px; }
.gc-inline-link {
  margin-top: 6px;
  background: none;
  border: none;
  padding: 0;
  font-size: 13px;
  color: inherit;
  text-decoration: underline;
  cursor: pointer;
}

@media (max-width: 768px) {
  .profile-page {
    padding: 16px;
  }

  .profile-header {
    flex-direction: column;
    text-align: center;
    padding: 24px;
  }

  .actions {
    flex-direction: row;
    width: 100%;
    justify-content: center;
  }

  .edit-actions {
    flex-direction: row;
    width: 100%;
    justify-content: center;
  }

  .username {
    font-size: 20px;
  }

  .info-grid {
    grid-template-columns: 1fr;
  }

  .info-item {
    flex-direction: column;
    gap: 4px;
    text-align: center;
  }

  .info-value {
    text-align: center;
  }
}

@media (max-width: 600px) {
  .profile-page {
    padding: 12px;
  }

  .settings-card,
  .edit-form {
    padding: 18px 14px;
  }

  .message {
    margin: 14px;
  }

  .profile-header {
    padding: 16px 14px;
  }

  .info-item {
    padding: 14px;
  }
}
</style>