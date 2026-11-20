<script setup lang="ts">
// watch 在下面用到两处：学术模式撤掉某个 tab 时回退 activeTab（见「选项卡」段），
// 以及路由参数变化时重新拉数据。
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import apiClient from '@/api/client'
import { trainingsApi, type TrainingListItem } from '@/api/trainings'
import { columnsApi, COLUMN_CATEGORIES, type ColumnItem } from '@/api/columns'
import { teamsApi, type TeamJoinedItem } from '@/api/teams'
import { userNameColor } from '@/utils/userColor'
import { getUserTagDisplay, getUserRoleText } from '@/utils/userTag'
import { useAcademicMode } from '@/utils/academicMode'
import { canManageTags as canManageTagsFn } from '@/utils/permissions'
import { fmtDateTime } from '@/utils/datetime'
import { withBase } from '@/utils/base'
import Swal from 'sweetalert2'
import BenbenFeed from '@/components/BenbenFeed.vue'
import UserAvatarStatus from '@/components/UserAvatarStatus.vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

// 默认封面（与原站一致的图片）
const DEFAULT_COVER = 'https://cdn.luogu.org/images/bg/fe/DSCF0530-shrink.jpg'
const LAZY_TEXT = '这个家伙很懒，什么也没有留下'

// ==================== 用户数据 ====================
const profile = ref<any>(null)
const loading = ref(true)
const error = ref('')

// ==================== Tag 卡管理 ====================
// 统一走全站权限判定（高层级天然可以 + 被授予 can_manage_tags 的人），
// 别再就地读 user.can_manage_tags，那样和后台的判定会不一致
const canManageTags = computed(() => canManageTagsFn(currentUser.value))
const tagCards = ref<any[]>([])
const newTagName = ref('')
const tagOpLoading = ref(false)

const loadTargetTagCards = async () => {
  try {
    const data: any = await apiClient.get(resolveProfileUrl(route.params.id as string))
    tagCards.value = data.tag_cards || []
  } catch {
    tagCards.value = []
  }
}

// 本人佩戴 / 摘下 Tag 卡
const toggleTagCard = async (card: any) => {
  if (!isOwner.value) return
  tagOpLoading.value = true
  try {
    const updated: any = await apiClient.put(`/users/me/tag-cards/${card.id}/toggle`)
    await loadUserProfile()
    await authStore.syncCurrentUser()
    Swal.fire({
      icon: 'success',
      title: updated.enabled ? `已佩戴「${card.name}」` : `已摘下「${card.name}」`,
      timer: 1500,
      showConfirmButton: false,
    })
  } catch (err: any) {
    Swal.fire({
      icon: 'error',
      title: '操作失败',
      text: err.response?.data?.detail || err.message,
    })
  } finally {
    tagOpLoading.value = false
  }
}

const grantTag = async () => {
  const name = newTagName.value.trim()
  if (!name || !profile.value?.id) return
  tagOpLoading.value = true
  try {
    await apiClient.post(`/users/${profile.value.id}/tag-cards`, { name, enabled: true })
    newTagName.value = ''
    await loadUserProfile()
    if (isOwner.value) {
      await authStore.syncCurrentUser()
    }
  } catch (err: any) {
    alert(err.response?.data?.detail || '授予失败')
  } finally {
    tagOpLoading.value = false
  }
}

const removeTagCard = async (cardId: number) => {
  if (!profile.value?.id) return
  tagOpLoading.value = true
  try {
    await apiClient.delete(`/users/${profile.value.id}/tag-cards/${cardId}`)
    await loadUserProfile()
    if (isOwner.value) {
      await authStore.syncCurrentUser()
    }
  } catch (err: any) {
    alert(err.response?.data?.detail || '删除失败')
  } finally {
    tagOpLoading.value = false
  }
}

// ==================== 改名记录与 Tag 变动历史 ====================
const showUsernameHistoryModal = ref(false)
const usernameHistoryList = ref<any[]>([])
const usernameHistoryLoading = ref(false)

const openUsernameHistoryModal = async () => {
  if (!profile.value?.id) return
  showUsernameHistoryModal.value = true
  usernameHistoryLoading.value = true
  try {
    const data: any = await apiClient.get(`/users/${profile.value.id}/username-history`)
    usernameHistoryList.value = data || []
  } catch {
    usernameHistoryList.value = []
  } finally {
    usernameHistoryLoading.value = false
  }
}

const showTagHistoryModal = ref(false)
const tagHistoryList = ref<any[]>([])
const tagHistoryLoading = ref(false)

const openTagHistoryModal = async () => {
  if (!profile.value?.id) return
  showTagHistoryModal.value = true
  tagHistoryLoading.value = true
  try {
    const data: any = await apiClient.get(`/users/${profile.value.id}/tag-history`)
    tagHistoryList.value = data || []
  } catch {
    tagHistoryList.value = []
  } finally {
    tagHistoryLoading.value = false
  }
}

// ==================== 工具 ====================
const COLOR_RED = 'var(--primary)'
const COLOR_PURPLE = '#9C3DCF'
const COLOR_BROWN = '#AD8B00'

const getUserDisplayColor = (user: any) => userNameColor(user)

const letterAvatar = (name: string) => {
  const ch = (name || 'U').trim().charAt(0).toUpperCase() || 'U'
  return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Crect width='40' height='40' fill='%23e74c3c'/%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' dy='.3em' fill='white' font-size='16' font-family='Arial'%3E${encodeURIComponent(ch)}%3C/text%3E%3C/svg%3E`
}

// 注册时间显示（取日期部分）
const formatRegDate = (dateStr: string) => {
  if (!dateStr) return ''
  return String(dateStr).split('T')[0]
}

// ==================== 计算属性 ====================
const currentUser = computed<any>(() => authStore.currentUser)
// 封面URL（当前后端暂无封面字段，固定使用默认封面）
const coverUrl = ref('')
const isOwner = computed(() =>
  !!currentUser.value && !!profile.value && currentUser.value.id === profile.value.id
)
const displayName = computed(() => {
  if (isOwner.value && currentUser.value?.username) {
    return currentUser.value.username
  }
  return profile.value?.username || '用户'
})
const avatarDisplay = computed(() => profile.value?.avatar_url || letterAvatar(displayName.value))
const color = computed(() => getUserDisplayColor(profile.value))
const tagText = computed(() => getUserTagDisplay(profile.value))
const coverStyle = computed(() => ({ backgroundImage: `url('${coverUrl.value || DEFAULT_COVER}')` }))

// 用户类型文本
const userTypeText = computed(() => {
  const u = profile.value
  if (!u) return ''
  if (isBanned.value) return '封禁用户'
  return getUserRoleText(u)
})

// 是否处于封禁状态
const isBanned = computed(() => profile.value?.is_banned === true)

// ==================== 选项卡 ====================
const TABS = ['主页', '动态', '专栏', '练习', '关注', '我的', '题库', '收藏']
// 「我的 / 题库 / 收藏」是本人专属标签：访问他人主页时不展示
const PERSONAL_TABS = ['我的', '题库', '收藏']
// 学术模式：「动态」整栏就是犇犇，一并撤掉
const { academicMode } = useAcademicMode()
const visibleTabs = computed(() =>
  TABS.filter((tab) => !(academicMode.value && tab === '动态'))
    .filter((tab) => isOwner.value || !PERSONAL_TABS.includes(tab)),
)
const activeTab = ref('主页')
const switchTab = (tab: string) => {
  activeTab.value = tab
  if (tab === '关注') void loadFollowList(true)
  if (tab === '我的') {
    void loadMyTrainings()
    void loadMyColumns()
    void loadMyTeams()
  }
  if (tab === '专栏') {
    void loadUserColumns()
  }
  if (tab === '收藏') {
    void loadStarredColumns()
  }
}

// 学术模式把某栏撤掉时（现在只有「动态」），正停在这一栏的人得有个着落，
// 否则 tab 没了、面板全空。回落到当前可见的第一栏。
watch(visibleTabs, (tabs) => {
  if (!tabs.includes(activeTab.value)) {
    activeTab.value = tabs[0] ?? '主页'
  }
})

// ==================== 我的题单 ====================
const myTrainingLists = ref<TrainingListItem[]>([])
const myTrainingLoading = ref(false)

const loadMyTrainings = async () => {
  if (!profile.value?.id) return
  myTrainingLoading.value = true
  try {
    const res = await trainingsApi.list({ owner_id: profile.value.id, page: 1, page_size: 100 })
    myTrainingLists.value = res.items
  } catch (e) {
    console.error('加载题单失败:', e)
  } finally {
    myTrainingLoading.value = false
  }
}

// 新建题单弹窗
const showMyCreateModal = ref(false)
const myCreateLoading = ref(false)
const myCreateForm = ref({
  title: '',
  description: '',
  is_public: true
})

const openCreateTraining = () => {
  myCreateForm.value = {
    title: '',
    description: '',
    is_public: true
  }
  showMyCreateModal.value = true
}

const handleMyCreate = async () => {
  if (!myCreateForm.value.title.trim()) {
    Swal.fire({ icon: 'warning', title: '请输入题单标题', timer: 1500, showConfirmButton: false })
    return
  }
  myCreateLoading.value = true
  try {
    const created = await trainingsApi.create({
      title: myCreateForm.value.title.trim(),
      description: myCreateForm.value.description.trim(),
      is_public: myCreateForm.value.is_public
    })
    Swal.fire({ icon: 'success', title: '题单创建成功', timer: 1500, showConfirmButton: false })
    showMyCreateModal.value = false
    await loadMyTrainings()
    router.push(`/training/${created.id}`)
  } catch (e: any) {
    Swal.fire({ icon: 'error', title: '创建失败', text: e.response?.data?.detail || e.message })
  } finally {
    myCreateLoading.value = false
  }
}

// 编辑题单弹窗
const showMyEditModal = ref(false)
const myEditLoading = ref(false)
const myEditForm = ref({
  id: 0,
  title: '',
  description: '',
  is_public: true
})

const openEditMyTraining = (item: TrainingListItem) => {
  myEditForm.value = {
    id: item.id,
    title: item.title,
    description: item.description || '',
    is_public: item.is_public
  }
  showMyEditModal.value = true
}

const handleMyEdit = async () => {
  if (!myEditForm.value.title.trim()) {
    Swal.fire({ icon: 'warning', title: '请输入题单标题', timer: 1500, showConfirmButton: false })
    return
  }
  myEditLoading.value = true
  try {
    await trainingsApi.update(myEditForm.value.id, {
      title: myEditForm.value.title.trim(),
      description: myEditForm.value.description.trim(),
      is_public: myEditForm.value.is_public
    })
    Swal.fire({ icon: 'success', title: '题单更新成功', timer: 1500, showConfirmButton: false })
    showMyEditModal.value = false
    await loadMyTrainings()
  } catch (e: any) {
    Swal.fire({ icon: 'error', title: '更新失败', text: e.response?.data?.detail || e.message })
  } finally {
    myEditLoading.value = false
  }
}

// 删除题单
const handleDeleteMyTraining = async (item: TrainingListItem) => {
  const result = await Swal.fire({
    title: `确定删除题单「${item.title}」？`,
    text: '题单删除后无法恢复，包含的题目不会被删除。',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#d33',
    cancelButtonColor: '#3085d6',
    confirmButtonText: '确定删除',
    cancelButtonText: '取消'
  })
  if (!result.isConfirmed) return

  try {
    await trainingsApi.remove(item.id)
    Swal.fire({ icon: 'success', title: '题单已删除', timer: 1500, showConfirmButton: false })
    await loadMyTrainings()
  } catch (e: any) {
    Swal.fire({ icon: 'error', title: '删除失败', text: e.response?.data?.detail || e.message })
  }
}

// ==================== 我的专栏与专栏列表 ====================
const myColumns = ref<ColumnItem[]>([])
const myColumnLoading = ref(false)

const loadMyColumns = async () => {
  if (!profile.value?.id) return
  myColumnLoading.value = true
  try {
    const res = await columnsApi.list({ author_id: profile.value.id, page: 1, page_size: 100 })
    myColumns.value = res.items
  } catch (e) {
    console.error('加载专栏失败:', e)
  } finally {
    myColumnLoading.value = false
  }
}

// 目标用户公开专栏列表（「专栏」标签页）
const userColumns = ref<ColumnItem[]>([])
const userColumnLoading = ref(false)

const loadUserColumns = async () => {
  if (!profile.value?.id) return
  userColumnLoading.value = true
  try {
    const res = await columnsApi.list({ author_id: profile.value.id, page: 1, page_size: 100 })
    userColumns.value = res.items
  } catch (e) {
    console.error('加载用户专栏失败:', e)
  } finally {
    userColumnLoading.value = false
  }
}

// 目标用户收藏专栏列表（「收藏」标签页）
const starredColumns = ref<ColumnItem[]>([])
const starredColumnLoading = ref(false)

const loadStarredColumns = async () => {
  if (!profile.value?.id) return
  starredColumnLoading.value = true
  try {
    const res = await columnsApi.list({ starred_by: profile.value.id, page: 1, page_size: 100 })
    starredColumns.value = res.items
  } catch (e) {
    console.error('加载收藏专栏失败:', e)
  } finally {
    starredColumnLoading.value = false
  }
}

// 分类样式映射
const getCategoryClass = (category?: string) => {
  switch (category) {
    case '算法理论':
      return 'cat-algo'
    case '科技工程':
      return 'cat-tech'
    case '题解':
      return 'cat-sol'
    case '娱乐':
      return 'cat-fun'
    default:
      return 'cat-default'
  }
}

// 新建专栏弹窗
const showMyCreateColumnModal = ref(false)
const myCreateColumnLoading = ref(false)
const myCreateColumnForm = ref({
  title: '',
  description: '',
  cover_url: '',
  category: '算法理论'
})

const openCreateColumn = () => {
  myCreateColumnForm.value = {
    title: '',
    description: '',
    cover_url: '',
    category: '算法理论'
  }
  showMyCreateColumnModal.value = true
}

const handleMyCreateColumn = async () => {
  if (!myCreateColumnForm.value.title.trim()) {
    Swal.fire({ icon: 'warning', title: '请输入专栏名称', timer: 1500, showConfirmButton: false })
    return
  }
  myCreateColumnLoading.value = true
  try {
    const created = await columnsApi.create({
      title: myCreateColumnForm.value.title.trim(),
      description: myCreateColumnForm.value.description.trim() || undefined,
      cover_url: myCreateColumnForm.value.cover_url.trim() || undefined,
      category: myCreateColumnForm.value.category
    })
    Swal.fire({ icon: 'success', title: '专栏创建成功', timer: 1500, showConfirmButton: false })
    showMyCreateColumnModal.value = false
    await loadMyColumns()
    if (activeTab.value === '专栏') {
      await loadUserColumns()
    }
    router.push(`/column/${created.id}`)
  } catch (e: any) {
    Swal.fire({ icon: 'error', title: '创建失败', text: e.response?.data?.detail || e.message })
  } finally {
    myCreateColumnLoading.value = false
  }
}

// 编辑专栏弹窗
const showMyEditColumnModal = ref(false)
const myEditColumnLoading = ref(false)
const myEditColumnForm = ref({
  id: 0,
  title: '',
  description: '',
  cover_url: '',
  category: '算法理论'
})

const openEditColumn = (col: ColumnItem) => {
  myEditColumnForm.value = {
    id: col.id,
    title: col.title,
    description: col.description || '',
    cover_url: col.cover_url || '',
    category: col.category || '算法理论'
  }
  showMyEditColumnModal.value = true
}

const handleMyEditColumn = async () => {
  if (!myEditColumnForm.value.title.trim()) {
    Swal.fire({ icon: 'warning', title: '请输入专栏名称', timer: 1500, showConfirmButton: false })
    return
  }
  myEditColumnLoading.value = true
  try {
    await columnsApi.update(myEditColumnForm.value.id, {
      title: myEditColumnForm.value.title.trim(),
      description: myEditColumnForm.value.description.trim() || undefined,
      cover_url: myEditColumnForm.value.cover_url.trim() || undefined,
      category: myEditColumnForm.value.category
    })
    Swal.fire({ icon: 'success', title: '专栏更新成功', timer: 1500, showConfirmButton: false })
    showMyEditColumnModal.value = false
    await loadMyColumns()
    if (activeTab.value === '专栏') {
      await loadUserColumns()
    }
  } catch (e: any) {
    Swal.fire({ icon: 'error', title: '更新失败', text: e.response?.data?.detail || e.message })
  } finally {
    myEditColumnLoading.value = false
  }
}

// 删除专栏
const handleDeleteColumn = async (col: ColumnItem) => {
  const result = await Swal.fire({
    title: `确定删除专栏「${col.title}」？`,
    text: '专栏删除后无法恢复，其中的文章将被彻底移除。',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#d33',
    cancelButtonColor: '#3085d6',
    confirmButtonText: '确定删除',
    cancelButtonText: '取消'
  })
  if (!result.isConfirmed) return

  try {
    await columnsApi.delete(col.id)
    Swal.fire({ icon: 'success', title: '专栏已删除', timer: 1500, showConfirmButton: false })
    await loadMyColumns()
    if (activeTab.value === '专栏') {
      await loadUserColumns()
    }
  } catch (e: any) {
    Swal.fire({ icon: 'error', title: '删除失败', text: e.response?.data?.detail || e.message })
  }
}

// ==================== 我加入的团队 ====================
const myJoinedTeams = ref<TeamJoinedItem[]>([])
const myTeamLoading = ref(false)

const loadMyTeams = async () => {
  if (!profile.value?.id) return
  myTeamLoading.value = true
  try {
    const res = await teamsApi.myJoined()
    myJoinedTeams.value = res.items || []
  } catch (e) {
    console.error('加载我加入的团队失败:', e)
  } finally {
    myTeamLoading.value = false
  }
}

// ==================== 签名编辑 ====================
const sloganEditing = ref(false)
const sloganValue = ref('')
const sloganInputRef = ref<HTMLInputElement | null>(null)

const startEditSlogan = () => {
  if (!isOwner.value || isBanned.value) return
  sloganValue.value = profile.value.bio || ''
  sloganEditing.value = true
  nextTick(() => {
    sloganInputRef.value?.focus()
    sloganInputRef.value?.select()
  })
}

const finishEditSlogan = async (cancel = false) => {
  if (!sloganEditing.value) return
  sloganEditing.value = false
  if (cancel) return

  const val = sloganValue.value.trim()
  const original = profile.value.bio || ''
  // 无变化则不请求
  if (val === original) return

  try {
    await apiClient.put('/users/me/profile', { bio: val })
    profile.value.bio = val
  } catch (err: any) {
    alert('保存失败：' + (err.response?.data?.detail || err.message || '未知错误'))
  }
}

const onSloganKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Enter') {
    e.preventDefault()
    ;(e.target as HTMLInputElement).blur()
  }
  if (e.key === 'Escape') {
    e.preventDefault()
    finishEditSlogan(true)
  }
}

// ==================== 关注功能 ====================
import { followApi, type FollowUser } from '@/api/follow'

const isFollowing = ref(false)
const followersCount = ref(0)
const followingCount = ref(0)
const followLoading = ref(false)

// 关注/取消关注
const handleFollowButton = async () => {
  if (!authStore.isAuthenticated) {
    router.push('/login')
    return
  }
  if (!profile.value) return

  followLoading.value = true
  try {
    if (isFollowing.value) {
      await followApi.unfollow(profile.value.id)
      isFollowing.value = false
      followersCount.value--
    } else {
      await followApi.follow(profile.value.id)
      isFollowing.value = true
      followersCount.value++
    }
  } catch (err: any) {
    alert(err.response?.data?.detail || '操作失败')
  } finally {
    followLoading.value = false
  }
}

// 加载关注统计
const loadFollowStats = async () => {
  if (!profile.value) return
  try {
    const stats = await followApi.getStats(profile.value.id)
    isFollowing.value = stats.is_following
    followersCount.value = stats.followers_count
    followingCount.value = stats.following_count
  } catch {
    // 静默失败
  }
}

// ==================== NLNOC 私信 ====================
import { useNlnocStore } from '@/stores/nlnoc'

const nlnoc = useNlnocStore()

/** 「发消息」：打开顶栏 NLNOC 面板并直达与 TA 的聊天 */
const handleSendMessage = () => {
  if (!authStore.isAuthenticated) {
    router.push('/login')
    return
  }
  if (!profile.value) return
  nlnoc.startChat({
    id: profile.value.id,
    username: profile.value.username,
    user_number: profile.value.user_number,
    avatar_url: profile.value.avatar_url,
    is_admin: profile.value.is_admin,
    is_super_admin: profile.value.is_super_admin,
    is_banned: profile.value.is_banned,
    is_cheater: profile.value.is_cheater,
    can_manage_users: profile.value.can_manage_users,
    can_manage_posts: profile.value.can_manage_posts,
    can_manage_problems: profile.value.can_manage_problems,
    username_color: profile.value.username_color,
    name_color: profile.value.name_color,
    user_tag: profile.value.display_tag ?? profile.value.user_tag ?? null,
    last_seen: profile.value.last_seen ?? null,
  })
}

// ==================== 关注选项卡 ====================
const followTabMode = ref<'followers' | 'following'>('followers')
const followList = ref<FollowUser[]>([])
const followListLoading = ref(false)
const followListPage = ref(0)
const followListHasMore = ref(true)

const loadFollowList = async (reset = false) => {
  if (!profile.value) return
  if (reset) {
    followListPage.value = 0
    followList.value = []
    followListHasMore.value = true
  }
  if (!followListHasMore.value) return

  followListLoading.value = true
  try {
    const data = followTabMode.value === 'followers'
      ? await followApi.getFollowers(profile.value.id, followListPage.value)
      : await followApi.getFollowing(profile.value.id, followListPage.value)

    const list = followTabMode.value === 'followers' ? data.followers : data.following
    if (reset) {
      followList.value = list || []
    } else {
      followList.value = [...followList.value, ...(list || [])]
    }
    followListHasMore.value = (list?.length || 0) >= 20
    followListPage.value++
  } catch {
    // 静默失败
  } finally {
    followListLoading.value = false
  }
}

const switchFollowTab = (mode: 'followers' | 'following') => {
  followTabMode.value = mode
  loadFollowList(true)
}

// 关注/取消关注列表中的用户
const handleFollowUser = async (user: FollowUser) => {
  if (!authStore.isAuthenticated) {
    router.push('/login')
    return
  }
  followLoading.value = true
  try {
    if (user.is_following) {
      await followApi.unfollow(user.id)
      user.is_following = false
    } else {
      await followApi.follow(user.id)
      user.is_following = true
    }
  } catch (err: any) {
    alert(err.response?.data?.detail || '操作失败')
  } finally {
    followLoading.value = false
  }
}

// ==================== 封面更换 ====================
const showCoverOverlay = ref(false)
const selectedFile = ref<File | null>(null)
const uploadFeedback = ref('')
const uploadFeedbackColor = ref('#999')
const uploading = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)

const openCoverUpload = () => {
  showCoverOverlay.value = true
  selectedFile.value = null
  uploadFeedback.value = ''
  if (fileInputRef.value) fileInputRef.value.value = ''
}

const closeCoverUpload = () => {
  showCoverOverlay.value = false
  selectedFile.value = null
  uploadFeedback.value = ''
}

const pickFile = () => {
  fileInputRef.value?.click()
}

const onDragOver = (e: DragEvent) => {
  ;(e.currentTarget as HTMLElement).style.borderColor = 'var(--primary)'
}

const onDragLeave = (e: DragEvent) => {
  ;(e.currentTarget as HTMLElement).style.borderColor = '#ddd'
}

const onDropEvent = (e: DragEvent) => {
  ;(e.currentTarget as HTMLElement).style.borderColor = '#ddd'
  onDrop(e)
}

const setFile = (file: File) => {
  if (file.type.startsWith('image/')) {
    selectedFile.value = file
    uploadFeedback.value = `✅ 已选择: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`
    uploadFeedbackColor.value = '#27ae60'
  } else {
    selectedFile.value = null
    uploadFeedback.value = '❌ 请选择图片文件'
    uploadFeedbackColor.value = 'var(--primary)'
  }
}

const onFileChange = (e: Event) => {
  const files = (e.target as HTMLInputElement).files
  if (files && files.length) setFile(files[0])
}

const onDrop = (e: DragEvent) => {
  if (e.dataTransfer && e.dataTransfer.files.length) {
    setFile(e.dataTransfer.files[0])
  }
}

const uploadCover = async () => {
  if (!selectedFile.value) return
  uploading.value = true
  const previousCover = coverUrl.value || ''
  let success = false

  try {
    const fd = new FormData()
    fd.append('file', selectedFile.value)
    // 加时间戳参数绕开浏览器缓存的跳转劫持
    const res: any = await apiClient.post(`/users/me/cover?_t=${Date.now()}`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    coverUrl.value = res.cover_url
    success = true
  } catch (err: any) {
    // 请求报错时向服务端核实真实结果——请求可能被代理/插件改写，但实际已成功
    try {
      const me: any = await apiClient.get(`${resolveProfileUrl(route.params.id as string)}?_t=${Date.now()}`)
      if (me?.cover_url && me.cover_url !== previousCover) {
        coverUrl.value = me.cover_url
        success = true
      }
    } catch {
      /* 核实也失败则维持失败判定 */
    }
    if (!success) {
      uploading.value = false
      uploadFeedback.value = '❌ ' + (err.response?.data?.detail || '上传失败，请稍后重试')
      uploadFeedbackColor.value = 'var(--primary)'
      return
    }
  }

  uploading.value = false
  uploadFeedback.value = '✅ 封面更新成功！'
  uploadFeedbackColor.value = '#27ae60'
  setTimeout(closeCoverUpload, 1200)
}

// ==================== 加载用户信息 ====================
/**
 * 路由参数既接受用户编号也接受用户名。
 * 讨论区/犇犇里的 @提及 只知道用户名，把它们直接链到 /user/{用户名}，
 * 就不用为了渲染一个链接再去批量换一次用户编号了。
 */
const resolveProfileUrl = (raw: string) => {
  const param = decodeURIComponent(String(raw || ''))
  const base = /^\d+$/.test(param)
    ? `/users/number/${param}`
    : `/users/by-username/${encodeURIComponent(param)}`
  return `${base}?_t=${Date.now()}`
}

const loadUserProfile = async () => {
  loading.value = true
  error.value = ''

  try {
    const rawId = String(route.params.id || '')
    let data: any
    try {
      data = await apiClient.get(resolveProfileUrl(rawId))
    } catch (primaryErr: any) {
      // 容错回退：若全数字按编号查失败（可能用户名为纯数字），回退按用户名查一次
      const decoded = decodeURIComponent(rawId)
      if (/^\d+$/.test(decoded)) {
        try {
          data = await apiClient.get(`/users/by-username/${encodeURIComponent(decoded)}?_t=${Date.now()}`)
        } catch {
          throw primaryErr
        }
      } else {
        throw primaryErr
      }
    }
    profile.value = data
    tagCards.value = data.tag_cards || []
    coverUrl.value = data.cover_url || ''
    document.title = `${data.username} 的个人主页 - NLNOJ`
    if (isOwner.value) {
      await authStore.syncCurrentUser()
    }
    await loadFollowStats()
    if (activeTab.value === '关注') await loadFollowList(true)
    if (activeTab.value === '我的') {
      void loadMyTrainings()
      void loadMyColumns()
      void loadMyTeams()
    }
    if (activeTab.value === '专栏') {
      void loadUserColumns()
    }
  } catch (err: any) {
    console.error('加载用户信息失败:', err)
    error.value = err.response?.status === 404 ? '用户不存在' : '加载失败: ' + (err.message || '未知错误')
  } finally {
    loading.value = false
  }
}

watch(
  () => route.params.id,
  (newId, oldId) => {
    if (newId && newId !== oldId) {
      void loadUserProfile()
    }
  }
)

onMounted(() => {
  loadUserProfile()
  // 预加载关注数据
  if (profile.value) {
    void loadFollowStats()
  }
})
</script>

<template>
  <div class="user-page">
    <div class="user-container">
      <!-- 加载中 -->
      <div v-if="loading" class="loading-box">加载中...</div>

      <!-- 出错 -->
      <div v-else-if="error" class="loading-box error-text">❌ {{ error }}</div>

      <template v-else-if="profile">
        <!-- ===== 封禁视图 ===== -->
        <div v-if="isBanned" class="user-header banned-header">
          <div class="user-header-bg" :style="coverStyle"></div>
          <div class="user-header-content" style="justify-content:center;text-align:center;">
            <div style="color:#fff;text-shadow:0 2px 12px rgba(0,0,0,0.6);">
              <div style="font-size:48px;margin-bottom:8px;"><i class="fa-solid fa-ban"></i></div>
              <h1 style="font-size:1.75rem;margin:0;">该用户已被封禁</h1>
            </div>
          </div>
        </div>

        <!-- ===== 正常视图 ===== -->
        <template v-else>
          <!-- 用户头部（封面） -->
          <div class="user-header">
            <div class="user-header-bg" :style="coverStyle"></div>

            <!-- 右上角更换封面按钮（仅本人） -->
            <span v-if="isOwner" class="btn-action-cover" title="更换封面" @click.stop.prevent="openCoverUpload">
              <svg viewBox="0 0 384 512" width="16" height="16">
                <path d="M162.4 6c-1.5-3.6-5-6-8.9-6l-19 0c-3.9 0-7.5 2.4-8.9 6L104.9 57.7c-3.2 8-14.6 8-17.8 0L66.4 6c-1.5-3.6-5-6-8.9-6L48 0C21.5 0 0 21.5 0 48l0 208 384 0 0-208c0-26.5-21.5-48-48-48L230.5 0c-3.9 0-7.5 2.4-8.9 6L200.9 57.7c-3.2 8-14.6 8-17.8 0L162.4 6zM0 304l0 16c0 35.3 28.7 64 64 64l64 0 0 64c0 35.3 28.7 64 64 64s64-28.7 64-64l0-64 64 0c35.3 0 64-28.7 64-64l0-16-384 0zM192 464c-8.8 0-16-7.2-16-16s7.2-16 16-16 16 7.2 16 16-7.2 16-16 16z"/>
              </svg>
            </span>

            <div class="user-header-content">
              <div class="user-header-avatar">
                <UserAvatarStatus :user="profile" :size="12">
                  <img
                    :src="avatarDisplay"
                    :alt="displayName"
                    @error="($event.target as HTMLImageElement).src = letterAvatar(displayName)"
                  >
                </UserAvatarStatus>
              </div>

              <div class="user-header-info">
                <div class="user-header-name">
                  <h1 :style="{ color }">{{ displayName }}</h1>
                  <span
                    v-if="tagText"
                    class="user-tag-display"
                    :style="{ backgroundColor: color }"
                  >{{ tagText }}</span>
                  <span
                    v-if="profile.award_cert_status === 'approved' && profile.oi_level"
                    class="user-tag-display"
                    style="background:#f39c12;"
                  >{{ profile.oi_level }}</span>
                </div>

                <div class="header-row">
                  <div class="follow-stats">
                    <span>关注 <span class="num">{{ followingCount }}</span></span>
                    <span>粉丝 <span class="num">{{ followersCount }}</span></span>
                    <span>经验 <span class="num">{{ profile.experience ?? 0 }}</span></span>
                    <span v-if="(profile.rated_contests ?? 0) > 0" title="比赛等级分（历史最高）">
                      等级分 <span class="num">{{ profile.rating ?? 1500 }}</span>
                      <span class="rating-max">（最高 {{ profile.max_rating ?? 1500 }}）</span>
                    </span>
                  </div>
                  <!-- 关注按钮（非本人显示） -->
                  <a
                    v-if="!isOwner && !authStore.isAuthenticated"
                    :href="withBase('/login')"
                    class="follow-btn following"
                    style="background:#7f8c8d;text-decoration:none;display:inline-block;"
                    @click.prevent="handleFollowButton"
                  >登录后关注</a>
                  <button
                    v-else-if="!isOwner"
                    class="follow-btn"
                    :class="{ following: isFollowing }"
                    :disabled="followLoading"
                    @click="handleFollowButton"
                  >{{ isFollowing ? '取消关注' : '关注' }}</button>
                  <!-- NLNOC 私信：打开顶栏面板并直达聊天 -->
                  <button
                    v-if="!isOwner"
                    type="button"
                    class="follow-btn msg-btn"
                    title="发送私信"
                    @click.stop="handleSendMessage"
                  >
                    <i class="fa-solid fa-paper-plane"></i> 发消息
                  </button>
                </div>

                <div class="header-row slogan-row">
                  <template v-if="sloganEditing">
                    <input
                      ref="sloganInputRef"
                      v-model="sloganValue"
                      class="slogan-editor-input"
                      :placeholder="LAZY_TEXT"
                      maxlength="500"
                      @blur="finishEditSlogan()"
                      @keydown="onSloganKeydown"
                    >
                  </template>
                  <template v-else>
                    <div
                      class="user-header-slogan"
                      :class="{ empty: !profile.bio }"
                      :data-editable="isOwner ? 'true' : 'false'"
                      @dblclick="startEditSlogan"
                    >{{ profile.bio?.trim() || LAZY_TEXT }}</div>
                  </template>

                  <!-- 个人设置按钮（仅本人） -->
                  <router-link v-if="isOwner" to="/profile" class="btn-luogu-setting">
                    <svg viewBox="0 0 640 512" width="16" height="16" fill="currentColor">
                      <path d="M256.5 8a120 120 0 1 1 0 240 120 120 0 1 1 0-240zM226.7 304l59.4 0 1.5 0c-12.9 26.8-7.8 58.2 11.5 79.5-20.2 22.3-24.8 55.8-9.4 83.4l22.5 40.4c.9 1.6 1.9 3.2 2.9 4.7l-237 0c-16.4 0-29.7-13.3-29.7-29.7 0-98.5 79.8-178.3 178.3-178.3zm205.9-56.4c0-13.3 10.7-24 24-24l48 0c13.3 0 24 10.7 24 24l0 6.1c0 18.9 24.1 32.8 40.5 23.4l5-2.9c11.6-6.7 26.5-2.6 33 9.1l22.4 40.2c6.2 11.2 2.6 25.2-8.2 32l-4.7 2.9c-16.2 10.1-16.2 39.9 0 50.1l4.6 2.9c10.8 6.8 14.5 20.8 8.3 32L607 483.8c-6.5 11.7-21.4 15.9-33 9.1l-4.9-2.9c-16.4-9.5-40.5 4.5-40.5 23.4l0 6.1c0 13.3-10.7 24-24 24l-48 0c-13.3 0-24-10.7-24-24l0-5.9c0-19-24.2-33-40.7-23.5l-4.8 2.8c-11.6 6.7-26.4 2.6-33-9.1l-22.6-40.4c-6.2-11.2-2.6-25.3 8.3-32.1l4.4-2.7c16.3-10.1 16.3-40.1 0-50.2l-4.5-2.8c-10.9-6.8-14.5-20.9-8.3-32.1l22.5-40.3c6.5-11.7 21.4-15.8 32.9-9.1l4.8 2.8c16.5 9.5 40.7-4.5 40.7-23.5l0-5.9zm99.9 136.2a52 52 0 1 0 -104 0 52 52 0 1 0 104 0z"/>
                    </svg>
                    个人设置
                  </router-link>
                </div>
              </div>
            </div>
          </div>

          <!-- ===== 选项卡导航 ===== -->
          <div class="new-card">
            <div class="profile-tabs">
              <nav class="tab-nav">
                <button
                  v-for="tab in visibleTabs"
                  :key="tab"
                  class="tab-btn"
                  :class="{ active: activeTab === tab }"
                  @click="switchTab(tab)"
                >{{ tab }}</button>
              </nav>
            </div>
          </div>

          <!-- ===== 选项卡内容 ===== -->
          <!-- 主页：用户信息卡片 -->
          <div v-if="activeTab === '主页'" class="l-card">
            <div class="l-flex-info-row">
              <span>用户编号</span>
              <div class="right">{{ profile.user_number }}</div>
            </div>
            <div class="l-flex-info-row">
              <span>用户类型</span>
              <div class="right">{{ userTypeText }}</div>
            </div>
            <div class="l-flex-info-row">
              <span>注册时间</span>
              <div class="right"><time :datetime="profile.created_at">{{ formatRegDate(profile.created_at) }}</time></div>
            </div>
            <div class="l-flex-info-row">
              <span>曾用名 / 改名记录</span>
              <div class="right">
                <button type="button" class="history-pill-btn" @click="openUsernameHistoryModal">
                  <i class="fa-solid fa-clock-rotate-left"></i> 查看记录
                </button>
              </div>
            </div>
            <template v-if="isOwner || canManageTags">
              <div class="l-flex-info-row">
                <span>{{ isOwner ? '我的 Tag 卡' : 'Tag 卡' }}</span>
                <div class="right">
                  <button type="button" class="history-pill-btn" @click="openTagHistoryModal">
                    <i class="fa-solid fa-clock-rotate-left"></i> Tag 变动记录
                  </button>
                </div>
              </div>
              <div class="tag-manage">
                <div v-if="tagCards.length === 0" class="tag-manage-empty">
                  {{ isOwner ? '暂无 Tag 卡，在经验商店兑换或出题后将在此展示' : '该用户暂无 Tag 卡' }}
                </div>
                <div v-for="card in tagCards" :key="card.id" class="tag-manage-item">
                  <div class="tag-manage-info">
                    <div class="tag-manage-title-row">
                      <span class="tag-manage-name" :class="{ enabled: card.enabled }">{{ card.name }}</span>
                      <span class="tag-manage-state">{{ card.enabled ? '佩戴中' : '未佩戴' }}</span>
                    </div>
                    <div class="tag-manage-source">
                      <span v-if="card.granter_name">授予人：<strong>{{ card.granter_name }}</strong></span>
                      <span v-else>来源：商店兑换/系统</span>
                      <span v-if="card.created_at" class="tag-time"> · {{ formatRegDate(card.created_at) }}</span>
                    </div>
                  </div>
                  <div class="tag-manage-actions">
                    <button
                      v-if="isOwner"
                      type="button"
                      class="tag-manage-btn"
                      :class="{ 'tag-btn-enabled': card.enabled }"
                      :disabled="tagOpLoading"
                      @click="toggleTagCard(card)"
                    >
                      {{ card.enabled ? '摘下' : '佩戴' }}
                    </button>
                    <button
                      v-if="canManageTags"
                      type="button"
                      class="tag-manage-btn danger"
                      :disabled="tagOpLoading"
                      @click="removeTagCard(card.id)"
                    >删除</button>
                  </div>
                </div>
                <div v-if="canManageTags" class="tag-manage-add">
                  <input
                    v-model="newTagName"
                    class="tag-manage-input"
                    maxlength="50"
                    placeholder="输入 Tag 名称授予"
                    @keydown.enter.prevent="grantTag"
                  >
                  <button class="tag-manage-btn" :disabled="tagOpLoading || !newTagName.trim()" @click="grantTag">授予</button>
                </div>
              </div>
            </template>
          </div>

          <!-- 动态：TA 发过的犇犇（只读，仅本人的保留删除按钮） -->
          <div v-else-if="activeTab === '动态'" class="benben-pane">
            <BenbenFeed :user-number="profile.user_number" />
          </div>

          <!-- 关注：粉丝/关注列表 -->
          <div v-else-if="activeTab === '关注'" class="l-card">
            <div class="follow-tabs">
              <button
                class="follow-tab"
                :class="{ active: followTabMode === 'followers' }"
                @click="switchFollowTab('followers')"
              >粉丝 ({{ followersCount }})</button>
              <button
                class="follow-tab"
                :class="{ active: followTabMode === 'following' }"
                @click="switchFollowTab('following')"
              >关注 ({{ followingCount }})</button>
            </div>

            <div v-if="followListLoading && followList.length === 0" class="follow-empty">加载中...</div>
            <div v-else-if="followList.length === 0" class="follow-empty">暂无数据</div>
            <div v-else class="follow-list">
              <div v-for="user in followList" :key="user.id" class="follow-item">
                <router-link :to="`/user/${user.user_number}`" class="follow-user">
                  <img
                    :src="user.avatar_url || letterAvatar(user.username)"
                    :alt="user.username"
                    class="follow-avatar"
                  >
                  <div class="follow-info">
                    <span class="follow-name" :style="{ color: userNameColor(user) }">{{ user.username }}</span>
                    <span v-if="getUserTagDisplay(user)" class="follow-tag">{{ getUserTagDisplay(user) }}</span>
                  </div>
                </router-link>
                <button
                  v-if="!isOwner && user.is_following"
                  class="follow-btn-sm"
                  @click="handleFollowUser(user)"
                >取消关注</button>
                <button
                  v-else-if="!isOwner"
                  class="follow-btn-sm primary"
                  @click="handleFollowUser(user)"
                >关注</button>
              </div>
            </div>

            <div v-if="followListHasMore" class="follow-more">
              <button class="btn" :disabled="followListLoading" @click="loadFollowList(false)">
                {{ followListLoading ? '加载中...' : '加载更多' }}
              </button>
            </div>
          </div>

          <!-- 我的：专栏与题单管理 -->
          <div v-else-if="activeTab === '我的'" class="my-workspace-pane">
            <!-- 我的专栏 -->
            <div class="l-card my-training-pane">
              <div class="my-training-header">
                <div>
                  <h3 class="pane-title"><i class="fa-solid fa-book-open"></i> 我的专栏</h3>
                  <span class="pane-sub">沉淀技术文章，分享算法思考与解题心得</span>
                </div>
                <button v-if="isOwner" class="btn-create-list" @click="openCreateColumn">
                  <i class="fa-solid fa-plus"></i> 新建专栏
                </button>
              </div>

              <div v-if="myColumnLoading" class="training-empty">
                <div class="empty-icon"><i class="fa-solid fa-spinner fa-spin"></i></div>
                <p>加载专栏中...</p>
              </div>

              <div v-else-if="myColumns.length === 0" class="training-empty">
                <div class="empty-icon"><i class="fa-solid fa-book"></i></div>
                <p>暂无创建的专栏</p>
                <button v-if="isOwner" class="btn-create-sm" @click="openCreateColumn">
                  立即新建一个专栏
                </button>
              </div>

              <div v-else class="my-training-grid">
                <div
                  v-for="item in myColumns"
                  :key="item.id"
                  class="my-training-card"
                  @click="router.push(`/column/${item.id}`)"
                >
                  <div class="my-card-top">
                    <span class="my-card-title">{{ item.title }}</span>
                    <div class="my-card-badges">
                      <span class="badge-cat-sm" :class="getCategoryClass(item.category)">
                        {{ item.category || '算法理论' }}
                      </span>
                      <span v-if="item.is_recommended" class="badge-featured-sm">
                        <i class="fa-solid fa-star"></i> 推荐
                      </span>
                    </div>
                  </div>

                  <p class="my-card-desc">{{ item.description || '暂无描述' }}</p>

                  <div class="my-card-meta">
                    <span><i class="fa-solid fa-newspaper"></i> {{ item.article_count }} 篇</span>
                    <span>{{ fmtDateTime(item.created_at) }}</span>
                  </div>

                  <div v-if="isOwner" class="my-card-actions" @click.stop>
                    <button class="btn-text" @click="openEditColumn(item)">
                      <i class="fa-solid fa-pen-to-square"></i> 编辑
                    </button>
                    <button class="btn-text text-danger" @click="handleDeleteColumn(item)">
                      <i class="fa-solid fa-trash"></i> 删除
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <!-- 我的题单 -->
            <div class="l-card my-training-pane">
              <div class="my-training-header">
                <div>
                  <h3 class="pane-title"><i class="fa-solid fa-layer-group"></i> 我的题单</h3>
                  <span class="pane-sub">创建、组织并管理属于你的个性化题单</span>
                </div>
                <button v-if="isOwner" class="btn-create-list" @click="openCreateTraining">
                  <i class="fa-solid fa-plus"></i> 新建题单
                </button>
              </div>

              <div v-if="myTrainingLoading" class="training-empty">
                <div class="empty-icon"><i class="fa-solid fa-spinner fa-spin"></i></div>
                <p>加载题单中...</p>
              </div>

              <div v-else-if="myTrainingLists.length === 0" class="training-empty">
                <div class="empty-icon"><i class="fa-solid fa-folder-open"></i></div>
                <p>暂无创建的题单</p>
                <button v-if="isOwner" class="btn-create-sm" @click="openCreateTraining">
                  立即新建一个题单
                </button>
              </div>

              <div v-else class="my-training-grid">
                <div
                  v-for="item in myTrainingLists"
                  :key="item.id"
                  class="my-training-card"
                  @click="router.push(`/training/${item.id}`)"
                >
                  <div class="my-card-top">
                    <span class="my-card-title">{{ item.title }}</span>
                    <div class="my-card-badges">
                      <span v-if="item.is_featured" class="badge-featured-sm">
                        <i class="fa-solid fa-star"></i> 精选
                      </span>
                      <span class="badge-vis-sm" :class="item.is_public ? 'pub' : 'pri'">
                        {{ item.is_public ? '公开' : '私有' }}
                      </span>
                    </div>
                  </div>

                  <p class="my-card-desc">{{ item.description || '暂无描述' }}</p>

                  <div class="my-card-meta">
                    <span><i class="fa-solid fa-clipboard-list"></i> {{ item.problem_count }} 题</span>
                    <span>{{ fmtDateTime(item.created_at) }}</span>
                  </div>

                  <div v-if="isOwner" class="my-card-actions" @click.stop>
                    <button class="btn-text" @click="openEditMyTraining(item)">
                      <i class="fa-solid fa-pen-to-square"></i> 编辑
                    </button>
                    <button class="btn-text text-danger" @click="handleDeleteMyTraining(item)">
                      <i class="fa-solid fa-trash"></i> 删除
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <!-- 我加入的团队 -->
            <div class="l-card my-training-pane">
              <div class="my-training-header">
                <div>
                  <h3 class="pane-title"><i class="fa-solid fa-users"></i> 我加入的团队</h3>
                  <span class="pane-sub">查看你已加入的团队，点击卡片直接进入团队主页</span>
                </div>
                <button class="btn-create-list" @click="router.push('/teams')">
                  <i class="fa-solid fa-compass"></i> 团队大厅
                </button>
              </div>

              <div v-if="myTeamLoading" class="training-empty">
                <div class="empty-icon"><i class="fa-solid fa-spinner fa-spin"></i></div>
                <p>加载团队中...</p>
              </div>

              <div v-else-if="myJoinedTeams.length === 0" class="training-empty">
                <div class="empty-icon"><i class="fa-solid fa-users-slash"></i></div>
                <p>暂未加入任何团队</p>
                <button class="btn-create-sm" @click="router.push('/teams')">
                  前往团队大厅发现或创建团队
                </button>
              </div>

              <div v-else class="my-training-grid">
                <div
                  v-for="item in myJoinedTeams"
                  :key="item.id"
                  class="my-training-card my-team-card"
                  @click="router.push(`/teams/${item.id}`)"
                >
                  <div class="my-card-top">
                    <span class="my-card-title">{{ item.name }}</span>
                    <div class="my-card-badges">
                      <span v-if="item.user_role === 'owner'" class="badge-role-owner">
                        <i class="fa-solid fa-crown"></i> 团主
                      </span>
                      <span v-else-if="item.user_role === 'admin'" class="badge-role-admin">
                        <i class="fa-solid fa-shield"></i> 管理员
                      </span>
                      <span v-else class="badge-role-member">
                        <i class="fa-solid fa-user"></i> 成员
                      </span>
                      <span v-if="item.is_banned" class="badge-banned-sm">
                        <i class="fa-solid fa-ban"></i> 已封禁
                      </span>
                    </div>
                  </div>

                  <p class="my-card-desc">{{ item.description || '暂无团队简介' }}</p>

                  <div class="my-card-meta">
                    <span><i class="fa-solid fa-users"></i> {{ item.member_count }} 人</span>
                    <span><i class="fa-solid fa-user-tie"></i> 团主：{{ item.owner?.username || '—' }}</span>
                    <span>{{ fmtDateTime(item.joined_at || item.created_at) }}</span>
                  </div>

                  <div class="my-card-actions" @click.stop>
                    <button class="btn-text btn-enter-team" @click="router.push(`/teams/${item.id}`)">
                      进入团队 <i class="fa-solid fa-arrow-right"></i>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 专栏标签页：用户公开专栏列表 -->
          <div v-else-if="activeTab === '专栏'" class="l-card my-training-pane">
            <div class="my-training-header">
              <div>
                <h3 class="pane-title"><i class="fa-solid fa-book-open"></i> {{ isOwner ? '我的专栏' : (displayName + ' 的专栏') }}</h3>
                <span class="pane-sub">共 {{ userColumns.length }} 个公开专栏</span>
              </div>
              <button v-if="isOwner" class="btn-create-list" @click="openCreateColumn">
                <i class="fa-solid fa-plus"></i> 新建专栏
              </button>
            </div>

            <div v-if="userColumnLoading" class="training-empty">
              <div class="empty-icon"><i class="fa-solid fa-spinner fa-spin"></i></div>
              <p>加载专栏中...</p>
            </div>

            <div v-else-if="userColumns.length === 0" class="training-empty">
              <div class="empty-icon"><i class="fa-solid fa-book"></i></div>
              <p>暂无专栏</p>
              <button v-if="isOwner" class="btn-create-sm" @click="openCreateColumn">
                立即新建一个专栏
              </button>
            </div>

            <div v-else class="my-training-grid">
              <div
                v-for="item in userColumns"
                :key="item.id"
                class="my-training-card"
                @click="router.push(`/column/${item.id}`)"
              >
                <div class="my-card-top">
                  <span class="my-card-title">{{ item.title }}</span>
                  <div class="my-card-badges">
                    <span class="badge-cat-sm" :class="getCategoryClass(item.category)">
                      {{ item.category || '算法理论' }}
                    </span>
                    <span v-if="item.is_recommended" class="badge-featured-sm">
                      <i class="fa-solid fa-star"></i> 推荐
                    </span>
                  </div>
                </div>

                <p class="my-card-desc">{{ item.description || '暂无描述' }}</p>

                <div class="my-card-meta">
                  <span><i class="fa-solid fa-newspaper"></i> {{ item.article_count }} 篇</span>
                  <span>{{ fmtDateTime(item.created_at) }}</span>
                </div>

                <div v-if="isOwner" class="my-card-actions" @click.stop>
                  <button class="btn-text" @click="openEditColumn(item)">
                    <i class="fa-solid fa-pen-to-square"></i> 编辑
                  </button>
                  <button class="btn-text text-danger" @click="handleDeleteColumn(item)">
                    <i class="fa-solid fa-trash"></i> 删除
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- 收藏标签页：用户收藏的专栏列表 -->
          <div v-else-if="activeTab === '收藏'" class="l-card my-training-pane">
            <div class="my-training-header">
              <div>
                <h3 class="pane-title"><i class="fa-solid fa-bookmark"></i> 我收藏的专栏</h3>
                <span class="pane-sub">共 {{ starredColumns.length }} 个收藏专栏</span>
              </div>
            </div>

            <div v-if="starredColumnLoading" class="training-empty">
              <div class="empty-icon"><i class="fa-solid fa-spinner fa-spin"></i></div>
              <p>加载收藏专栏中...</p>
            </div>

            <div v-else-if="starredColumns.length === 0" class="training-empty">
              <div class="empty-icon"><i class="fa-regular fa-bookmark"></i></div>
              <p>暂无收藏的专栏</p>
              <button class="btn-create-sm" @click="router.push('/articles')">
                前往文章广场浏览
              </button>
            </div>

            <div v-else class="my-training-grid">
              <div
                v-for="item in starredColumns"
                :key="item.id"
                class="my-training-card"
                @click="router.push(`/column/${item.id}`)"
              >
                <div class="my-card-top">
                  <span class="my-card-title">{{ item.title }}</span>
                  <div class="my-card-badges">
                    <span class="badge-cat-sm" :class="getCategoryClass(item.category)">
                      {{ item.category || '算法理论' }}
                    </span>
                    <span v-if="item.is_recommended" class="badge-featured-sm">
                      <i class="fa-solid fa-star"></i> 推荐
                    </span>
                  </div>
                </div>

                <p class="my-card-desc">{{ item.description || '暂无描述' }}</p>

                <div class="my-card-meta">
                  <span><i class="fa-solid fa-newspaper"></i> {{ item.article_count }} 篇</span>
                  <span v-if="item.like_count"><i class="fa-regular fa-thumbs-up"></i> {{ item.like_count }}</span>
                  <span v-if="item.star_count"><i class="fa-regular fa-bookmark"></i> {{ item.star_count }}</span>
                  <span>{{ fmtDateTime(item.created_at) }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 其余标签：功能尚未开发 -->
          <div v-else class="l-card tab-placeholder">
            <div class="placeholder-icon"><i class='fa-solid fa-person-digging'></i></div>
            <p class="placeholder-title">本功能暂未开放</p>
            <p class="placeholder-sub">「{{ activeTab }}」正在开发中，敬请期待</p>
          </div>
        </template>
      </template>
    </div>

    <!-- ===== 封面更换浮层 ===== -->
    <div v-show="showCoverOverlay" class="cover-upload-overlay active" @click.self="closeCoverUpload">
      <div class="cover-upload-panel">
        <h2><i class="fa-solid fa-image"></i> 更换封面</h2>
        <div
          class="upload-area"
          @click="pickFile"
          @dragover.prevent="onDragOver"
          @dragleave="onDragLeave"
          @drop.prevent="onDropEvent"
        >
          <input ref="fileInputRef" type="file" accept="image/*" style="display:none;" @change="onFileChange">
          <div class="hint">点击选择图片，或拖拽到此处<br><strong>建议尺寸 1800×600px</strong></div>
        </div>
        <div class="lfe-caption">
          <i class="fa-solid fa-triangle-exclamation"></i> 为了文字可读性，请勿使用浅色背景图。
        </div>
        <div class="panel-actions">
          <button class="btn-cancel-cover" @click="closeCoverUpload">取消</button>
          <button class="btn-upload-cover" :disabled="!selectedFile || uploading" @click="uploadCover">
            {{ uploading ? '上传中…' : '上传' }}
          </button>
        </div>
        <div class="cover-feedback">{{ uploadFeedback }}</div>
      </div>
    </div>

    <!-- ===== 新建模态框 ===== -->
    <div v-if="showMyCreateModal" class="modal-backdrop" @click.self="showMyCreateModal = false">
      <div class="modal-card">
        <div class="modal-header">
          <h3><i class="fa-solid fa-plus-circle"></i> 新建题单</h3>
          <button class="close-btn" @click="showMyCreateModal = false"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>题单标题 <span class="req">*</span></label>
            <input v-model="myCreateForm.title" type="text" class="form-input" placeholder="请输入题单名称（如：新手动态规划）" maxlength="100">
          </div>
          <div class="form-group">
            <label>题单介绍 / Markdown 描述</label>
            <textarea v-model="myCreateForm.description" class="form-textarea" rows="4" placeholder="介绍一下这个题单的学习路线或目标..."></textarea>
          </div>
          <div class="form-group">
            <label>公开性设置</label>
            <div class="radio-row">
              <label class="radio-label">
                <input v-model="myCreateForm.is_public" type="radio" :value="true">
                <span>公开（所有人均可在题单广场中查阅与练习）</span>
              </label>
              <label class="radio-label">
                <input v-model="myCreateForm.is_public" type="radio" :value="false">
                <span>私有（仅自己与管理员可见）</span>
              </label>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn-cancel" @click="showMyCreateModal = false">取消</button>
          <button class="btn-confirm" :disabled="myCreateLoading" @click="handleMyCreate">
            {{ myCreateLoading ? '创建中...' : '立即创建' }}
          </button>
        </div>
      </div>
    </div>

    <!-- ===== 编辑模态框 ===== -->
    <div v-if="showMyEditModal" class="modal-backdrop" @click.self="showMyEditModal = false">
      <div class="modal-card">
        <div class="modal-header">
          <h3><i class="fa-solid fa-pen-to-square"></i> 编辑题单</h3>
          <button class="close-btn" @click="showMyEditModal = false"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>题单标题 <span class="req">*</span></label>
            <input v-model="myEditForm.title" type="text" class="form-input" placeholder="请输入题单名称" maxlength="100">
          </div>
          <div class="form-group">
            <label>题单介绍 / Markdown 描述</label>
            <textarea v-model="myEditForm.description" class="form-textarea" rows="4" placeholder="介绍一下这个题单的学习路线或目标..."></textarea>
          </div>
          <div class="form-group">
            <label>公开性设置</label>
            <div class="radio-row">
              <label class="radio-label">
                <input v-model="myEditForm.is_public" type="radio" :value="true">
                <span>公开（所有人均可在题单广场中查阅与练习）</span>
              </label>
              <label class="radio-label">
                <input v-model="myEditForm.is_public" type="radio" :value="false">
                <span>私有（仅自己与管理员可见）</span>
              </label>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn-cancel" @click="showMyEditModal = false">取消</button>
          <button class="btn-confirm" :disabled="myEditLoading" @click="handleMyEdit">
            {{ myEditLoading ? '保存中...' : '保存更改' }}
          </button>
        </div>
      </div>
    </div>

    <!-- ===== 新建专栏模态框 ===== -->
    <div v-if="showMyCreateColumnModal" class="modal-backdrop" @click.self="showMyCreateColumnModal = false">
      <div class="modal-card">
        <div class="modal-header">
          <h3><i class="fa-solid fa-plus-circle"></i> 新建专栏</h3>
          <button class="close-btn" @click="showMyCreateColumnModal = false"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>专栏名称 <span class="req">*</span></label>
            <input v-model="myCreateColumnForm.title" type="text" class="form-input" placeholder="请输入专栏名称（如：动态规划专题精讲）" maxlength="100">
          </div>
          <div class="form-group">
            <label>专栏分类 <span class="req">*</span></label>
            <div class="category-select-group">
              <label
                v-for="cat in COLUMN_CATEGORIES"
                :key="cat"
                class="cat-radio-label"
                :class="{ active: myCreateColumnForm.category === cat }"
              >
                <input
                  v-model="myCreateColumnForm.category"
                  type="radio"
                  :value="cat"
                  style="display: none;"
                />
                {{ cat }}
              </label>
            </div>
          </div>
          <div class="form-group">
            <label>专栏简介</label>
            <textarea v-model="myCreateColumnForm.description" class="form-textarea" rows="3" placeholder="简要介绍这个专栏的内容和适合读者..."></textarea>
          </div>
          <div class="form-group">
            <label>封面图片 URL（选填）</label>
            <input v-model="myCreateColumnForm.cover_url" type="text" class="form-input" placeholder="https://example.com/cover.png">
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn-cancel" @click="showMyCreateColumnModal = false">取消</button>
          <button class="btn-confirm" :disabled="myCreateColumnLoading" @click="handleMyCreateColumn">
            {{ myCreateColumnLoading ? '创建中...' : '立即创建' }}
          </button>
        </div>
      </div>
    </div>

    <!-- ===== 编辑专栏模态框 ===== -->
    <div v-if="showMyEditColumnModal" class="modal-backdrop" @click.self="showMyEditColumnModal = false">
      <div class="modal-card">
        <div class="modal-header">
          <h3><i class="fa-solid fa-pen-to-square"></i> 编辑专栏</h3>
          <button class="close-btn" @click="showMyEditColumnModal = false"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>专栏名称 <span class="req">*</span></label>
            <input v-model="myEditColumnForm.title" type="text" class="form-input" placeholder="请输入专栏名称" maxlength="100">
          </div>
          <div class="form-group">
            <label>专栏分类 <span class="req">*</span></label>
            <div class="category-select-group">
              <label
                v-for="cat in COLUMN_CATEGORIES"
                :key="cat"
                class="cat-radio-label"
                :class="{ active: myEditColumnForm.category === cat }"
              >
                <input
                  v-model="myEditColumnForm.category"
                  type="radio"
                  :value="cat"
                  style="display: none;"
                />
                {{ cat }}
              </label>
            </div>
          </div>
          <div class="form-group">
            <label>专栏简介</label>
            <textarea v-model="myEditColumnForm.description" class="form-textarea" rows="3" placeholder="简要介绍这个专栏的内容和适合读者..."></textarea>
          </div>
          <div class="form-group">
            <label>封面图片 URL（选填）</label>
            <input v-model="myEditColumnForm.cover_url" type="text" class="form-input" placeholder="https://example.com/cover.png">
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn-cancel" @click="showMyEditColumnModal = false">取消</button>
          <button class="btn-confirm" :disabled="myEditColumnLoading" @click="handleMyEditColumn">
            {{ myEditColumnLoading ? '保存中...' : '保存修改' }}
          </button>
        </div>
      </div>
    </div>

    <!-- ===== 改名历史弹窗 ===== -->
    <div v-if="showUsernameHistoryModal" class="modal-backdrop" @click.self="showUsernameHistoryModal = false">
      <div class="modal-card history-modal-card">
        <div class="modal-header">
          <h3><i class="fa-solid fa-clock-rotate-left"></i> 改名历史记录</h3>
          <button class="close-btn" @click="showUsernameHistoryModal = false"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="modal-body">
          <div v-if="usernameHistoryLoading" class="history-empty">加载中...</div>
          <div v-else-if="usernameHistoryList.length === 0" class="history-empty">暂无改名历史记录</div>
          <div v-else class="history-list">
            <div v-for="item in usernameHistoryList" :key="item.id" class="history-item">
              <div class="history-change">
                <span class="old-val">{{ item.old_username }}</span>
                <i class="fa-solid fa-arrow-right history-arrow"></i>
                <span class="new-val">{{ item.new_username }}</span>
              </div>
              <div class="history-meta">
                <span class="history-operator">
                  操作人：<strong :class="{ 'self-op': item.is_self }">{{ item.is_self ? '用户本人' : item.operator_name }}</strong>
                </span>
                <span class="history-time">{{ formatRegDate(item.created_at) }}</span>
              </div>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn-cancel" @click="showUsernameHistoryModal = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- ===== Tag 变动历史弹窗 ===== -->
    <div v-if="showTagHistoryModal" class="modal-backdrop" @click.self="showTagHistoryModal = false">
      <div class="modal-card history-modal-card">
        <div class="modal-header">
          <h3><i class="fa-solid fa-tags"></i> Tag 变动历史记录</h3>
          <button class="close-btn" @click="showTagHistoryModal = false"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="modal-body">
          <div v-if="tagHistoryLoading" class="history-empty">加载中...</div>
          <div v-else-if="tagHistoryList.length === 0" class="history-empty">暂无 Tag 变动记录</div>
          <div v-else class="history-list">
            <div v-for="item in tagHistoryList" :key="item.id" class="history-item">
              <div class="history-change">
                <span class="action-badge" :class="item.action">{{ item.action_label }}</span>
                <span class="tag-val">「{{ item.tag_name }}」</span>
              </div>
              <div class="history-meta">
                <span class="history-operator">
                  操作人：<strong>{{ item.operator_name }}</strong>
                </span>
                <span class="history-time">{{ formatRegDate(item.created_at) }}</span>
              </div>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn-cancel" @click="showTagHistoryModal = false">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rating-max { font-size: 12px; opacity: .6; }
/* ===== 页面容器 ===== */
.user-page {
  min-height: 100vh;
  line-height: 1.5;
}

.user-container {
  max-width: 1400px;
  margin: 0 auto;
}

.loading-box {
  text-align: center;
  padding: 40px;
  color: var(--text-sub);
  font-size: 16px;
}

.error-text {
  color: var(--primary);
}

/* ===== 用户头部（封面）===== */
.user-header {
  position: relative;
  border-radius: 16px 16px 0 0;
  overflow: hidden;
  margin-bottom: 0;
  background: #1a1a2e;
  min-height: 250px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
}

.banned-header {
  min-height: 160px;
}

.user-header-bg {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
  transition: opacity 0.3s;
}

.user-header-content {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  padding: 20px 32px 24px;
  gap: 8px;
  flex-wrap: wrap;
  width: 100%;
}

.user-header-avatar {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  overflow: hidden;
  flex-shrink: 0;
  border: none;
  box-shadow: none;
  background: var(--bg-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
}

.user-header-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.user-header-info {
  flex: 1;
  min-width: 200px;
  color: #fff;
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
}

.user-header-name {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.user-header-name h1 {
  font-size: 1.75rem;
  font-weight: 700;
  margin: 0;
  letter-spacing: 0.5px;
}

.header-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 4px;
}

.slogan-row {
  margin-top: 6px;
}

.follow-stats {
  display: flex;
  gap: 20px;
  font-size: 14px;
  color: #fff;
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
}

.follow-stats span {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
}

.follow-stats .num {
  font-weight: 700;
  font-size: 1.1em;
}

.follow-btn {
  padding: 4px 18px;
  border-radius: 30px;
  font-size: 14px;
  font-weight: 600;
  border: none;
  cursor: pointer;
  transition: all 0.25s;
  background: var(--primary);
  color: #fff;
  font-family: inherit;
}

.follow-btn.following {
  background: #7f8c8d;
}

/* 「发消息」：与关注按钮同排的次级描边样式（NLNOC 私信入口） */
.follow-btn.msg-btn {
  background: transparent;
  color: var(--primary);
  border: 1.5px solid var(--primary);
  margin-left: -2px;
}

.follow-btn.msg-btn:hover {
  background: var(--primary);
  color: #fff;
}

.follow-btn:not(:disabled):hover {
  transform: scale(1.04);
}

/* ===== 右上角更换封面按钮 ===== */
.btn-action-cover {
  position: absolute;
  top: 16px;
  right: 16px;
  z-index: 10;
  color: #404040;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.25s;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.55);
}

.btn-action-cover svg {
  width: 18px;
  height: 18px;
  fill: currentColor;
}

.btn-action-cover:hover {
  color: #fff;
  background: rgba(0, 0, 0, 0.45);
}

/* ===== 个人设置按钮 ===== */
.btn-luogu-setting {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 5px 15px;
  border-radius: 5px;
  border: 1px solid rgba(255, 255, 255, 0.5);
  background: rgba(0, 0, 0, 0.5);
  color: #fff;
  font-size: 0.875em;
  font-weight: 500;
  text-decoration: none;
  cursor: pointer;
  transition: background 0.25s, transform 0.2s, border-color 0.25s, box-shadow 0.25s;
  user-select: none;
  font-family: inherit;
  line-height: 1.5;
  white-space: nowrap;
  flex-shrink: 0;
  margin-left: auto;
}

.btn-luogu-setting:hover {
  background: rgba(255, 255, 255, 0.18);
  border-color: rgba(255, 255, 255, 0.75);
  text-decoration: none;
}

.btn-luogu-setting:active {
  transform: scale(0.96) translateY(0);
  background: rgba(255, 255, 255, 0.12);
}

/* ===== 签名 ===== */
.user-header-slogan {
  font-size: 1.1rem;
  opacity: 0.92;
  max-width: 600px;
  word-break: break-word;
  white-space: pre-wrap;
  line-height: 1.6;
  min-height: 28px;
  margin-top: -2px;
  padding: 0 0 2px 0;
  border-radius: 0;
  display: block;
  transition: background 0.2s, color 0.3s;
  color: #fff;
  font-style: normal;
  text-align: left;
}

.user-header-slogan[data-editable='true'] {
  cursor: pointer;
}

.slogan-editor-input {
  border: 1px solid var(--primary);
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 16px;
  width: 100%;
  max-width: 500px;
  min-width: 100px;
  outline: none;
  background: var(--surface-plain);
  color: var(--text-strong);
  font-family: inherit;
  box-sizing: border-box;
}

.slogan-editor-input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px rgba(231, 76, 60, 0.2);
}

/* ===== 选项卡导航卡片 ===== */
.new-card {
  border-radius: 0 0 16px 16px;
  margin-bottom: 24px;
  padding: 0 30px 0 40px;
  /* 与全站 .card 同款亚克力：半透明 + 背后模糊（原先是不透明 #fff，没有毛玻璃） */
  background: var(--surface);
  -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  overflow: hidden;
  height: 60px;
  display: flex;
  align-items: stretch;
}

.profile-tabs {
  width: 100%;
}

.tab-nav {
  display: flex;
  gap: 32px;
  height: 100%;
  align-items: stretch;
  width: 100%;
}

.tab-nav .tab-btn {
  position: relative;
  background: none;
  border: none;
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  color: var(--text-strong);
  padding: 0;
  text-decoration: none;
  transition: color 0.25s;
  font-family: inherit;
  line-height: 1.4;
  white-space: nowrap;
  display: flex;
  align-items: center;
  height: 100%;
}

.tab-nav .tab-btn::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 50%;
  width: 0;
  height: 5px;
  background: #d0d7de;
  transition: all 0.3s ease;
  transform: translateX(-50%);
}

.tab-nav .tab-btn:hover::after {
  width: calc(100% + 16px);
  left: -8px;
  transform: translateX(0);
}

.tab-nav .tab-btn.active {
  color: var(--primary);
  cursor: default;
}

.tab-nav .tab-btn.active::after {
  background: var(--primary);
  width: 100%;
  left: 0;
  transform: translateX(0);
  height: 5px;
}

.tab-nav .tab-btn.active:hover::after {
  width: calc(100% + 16px);
  left: -8px;
  height: 5px;
}

/* ===== 信息卡片 ===== */
.l-card {
  /* 与全站 .card 同款亚克力：半透明 + 背后模糊（原先是不透明 #fff，没有毛玻璃） */
  background: var(--surface);
  -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: 16px;
  padding: 18px 24px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  margin-bottom: 24px;
}

/* 未开发标签的占位内容（与 ComingSoon 页文案保持一致） */
.tab-placeholder {
  text-align: center;
  padding: 48px 24px;
}

/* 「动态」标签页：犇犇气泡自带半透明底色与描边，不需要再套一层卡片 */
.benben-pane {
  padding: 4px 0 0;
}

.placeholder-icon {
  font-size: 44px;
  line-height: 1;
  margin-bottom: 12px;
}

.placeholder-title {
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--text-strong);
  margin: 0 0 6px;
}

.placeholder-sub {
  font-size: 13px;
  color: var(--text-sub);
  margin: 0;
}

.tag-manage { display: flex; flex-direction: column; gap: 8px; padding: 10px 12px; background: var(--surface-strong); border: var(--border-width) solid var(--border-color); border-radius: 8px; }
.tag-manage-empty { color: var(--text-sub); font-size: 13px; }
.tag-manage-item { display: flex; align-items: center; justify-content: space-between; gap: 10px; font-size: 13px; padding: 6px 0; border-bottom: 1px dashed var(--border-color, #e2e8f0); }
.tag-manage-item:last-of-type { border-bottom: none; }
.tag-manage-info { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
.tag-manage-title-row { display: flex; align-items: center; gap: 8px; }
.tag-manage-name { font-weight: 700; color: var(--text-strong); }
.tag-manage-name.enabled { color: var(--primary); }
.tag-manage-state { color: var(--text-sub); font-size: 12px; }
.tag-manage-source { font-size: 11px; color: var(--text-muted, #94a3b8); }
.tag-manage-source strong { color: var(--text-sub, #64748b); }
.tag-manage-actions { display: flex; align-items: center; gap: 6px; }
.tag-manage-btn { border: none; background: var(--primary); color: #fff; border-radius: 6px; padding: 4px 12px; font-size: 12px; cursor: pointer; transition: all 0.2s; }
.tag-manage-btn.danger { background: #e74c3c; }
.tag-manage-btn.tag-btn-enabled { background: #64748b; }
.tag-manage-btn:disabled { opacity: .5; cursor: not-allowed; }
.tag-manage-add { display: flex; gap: 8px; margin-top: 4px; }
.tag-manage-input { flex: 1; padding: 6px 10px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 13px; outline: none; }
.tag-manage-input:focus { border-color: var(--primary); }

.history-pill-btn {
  border: 1px solid var(--border-color, #cbd5e1);
  background: var(--surface-strong, #fff);
  color: var(--primary, #3b82f6);
  padding: 4px 12px;
  border-radius: 14px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s;
}
.history-pill-btn:hover {
  background: var(--primary, #3b82f6);
  color: #fff;
  border-color: var(--primary, #3b82f6);
}

.history-modal-card { max-width: 540px; }
.history-empty { text-align: center; padding: 36px 0; color: var(--text-muted, #94a3b8); font-size: 14px; }
.history-list { display: flex; flex-direction: column; gap: 10px; max-height: 420px; overflow-y: auto; padding-right: 4px; }
.history-item { padding: 12px 14px; background: var(--surface-sub, rgba(0, 0, 0, 0.02)); border: 1px solid var(--border-color, #e2e8f0); border-radius: 8px; display: flex; flex-direction: column; gap: 6px; }
.history-change { display: flex; align-items: center; gap: 8px; font-size: 14px; }
.old-val { color: var(--text-sub, #64748b); text-decoration: line-through; }
.history-arrow { color: var(--text-muted, #94a3b8); font-size: 11px; }
.new-val { color: var(--primary, #3b82f6); font-weight: 600; }
.history-meta { display: flex; justify-content: space-between; align-items: center; font-size: 12px; color: var(--text-muted, #94a3b8); }
.history-operator strong { color: var(--text-strong, #1e293b); }
.history-operator .self-op { color: #10b981; }
.action-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.action-badge.grant { background: #dcfce7; color: #15803d; }
.action-badge.revoke { background: #fee2e2; color: #b91c1c; }
.action-badge.custom_tag { background: #f3e8ff; color: #7e22ce; }
.action-badge.shop_redeem { background: #fef3c7; color: #b45309; }
.tag-val { font-weight: 600; color: var(--text-strong, #1e293b); }

.l-flex-info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
}

.l-flex-info-row:last-child {
  border-bottom: none;
}

.l-flex-info-row span {
  font-size: 14px;
  color: var(--text-strong);
  font-weight: 700;
  letter-spacing: 0.3px;
}

.l-flex-info-row .right {
  font-size: 14px;
  color: var(--text-strong);
  font-weight: 500;
  text-align: right;
  word-break: break-all;
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.l-flex-info-row .right time {
  color: var(--text-strong);
}

/* ===== 身份标签 ===== */
.user-tag-display {
  display: inline-block;
  border-radius: 2px;
  padding: 2px 9px;
  color: #fff;
  font-size: 11.5px;
  font-weight: 600;
  margin: 0 0 0 4px;
  cursor: default;
  transition: filter 0.15s;
  vertical-align: middle;
  text-shadow: none;
}

.user-tag-display:hover {
  filter: brightness(0.9);
}

/* ===== 封面更换浮层 ===== */
.cover-upload-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 999;
  justify-content: center;
  align-items: center;
  -webkit-backdrop-filter: blur(4px);
  backdrop-filter: blur(4px);
}

.cover-upload-overlay.active {
  display: flex;
}

.cover-upload-panel {
  background: var(--surface-plain);
  border-radius: 20px;
  padding: 32px 40px;
  max-width: 480px;
  width: 90%;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}

.cover-upload-panel h2 {
  font-size: 1.3rem;
  margin-bottom: 16px;
  color: var(--text-strong);
}

.cover-upload-panel .upload-area {
  border: 2px dashed #ddd;
  border-radius: 12px;
  padding: 30px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s;
  margin-bottom: 12px;
}

.cover-upload-panel .upload-area:hover {
  border-color: var(--primary);
}

.cover-upload-panel .upload-area .hint {
  font-size: 14px;
  color: var(--text-sub);
}

.cover-upload-panel .upload-area .hint strong {
  color: var(--primary);
}

.cover-upload-panel .lfe-caption {
  font-size: 13px;
  color: var(--text-sub);
  line-height: 1.6;
  margin: 12px 0;
}

.cover-upload-panel .panel-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 16px;
}

.cover-upload-panel .panel-actions button {
  padding: 8px 24px;
  border-radius: 30px;
  border: none;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
  font-family: inherit;
}

.cover-upload-panel .panel-actions .btn-cancel-cover {
  background: var(--bg-subtle);
  color: var(--text-sub);
}

.cover-upload-panel .panel-actions .btn-cancel-cover:hover {
  background: #dde0e3;
}

.cover-upload-panel .panel-actions .btn-upload-cover {
  background: var(--primary);
  color: #fff;
}

.cover-upload-panel .panel-actions .btn-upload-cover:hover:not(:disabled) {
  background: var(--primary-hover);
}

.cover-upload-panel .panel-actions .btn-upload-cover:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.cover-feedback {
  margin-top: 10px;
  font-size: 13px;
  color: v-bind('uploadFeedbackColor');
}

/* ===== 响应式 ===== */
@media (max-width: 900px) {
  .user-header {
    min-height: 220px;
  }

  .user-header-content {
    padding: 16px 24px 20px;
    gap: 6px;
  }

  .user-header-name h1 {
    font-size: 1.5rem;
  }

  .user-header-avatar {
    width: 64px;
    height: 64px;
  }

  .slogan-editor-input {
    max-width: 100%;
    min-width: 120px;
  }

  .tab-nav {
    gap: 16px;
  }

  .tab-nav .tab-btn {
    font-size: 14px;
    padding: 8px 0 10px 0;
  }

  .new-card {
    padding: 0 16px 10px;
  }
}

@media (max-width: 600px) {
  .user-header {
    min-height: 180px;
  }

  .user-header-content {
    padding: 12px 16px;
    gap: 4px;
  }

  .user-header-avatar {
    width: 56px;
    height: 56px;
  }

  .user-header-name h1 {
    font-size: 1.3rem;
  }

  .user-header-slogan {
    font-size: 0.95rem;
    padding: 4px 12px;
  }

  .cover-upload-panel {
    padding: 24px 20px;
  }

  .slogan-editor-input {
    font-size: 14px;
    padding: 2px 4px;
    min-width: 100px;
  }

  .tab-nav {
    gap: 10px;
  }

  .tab-nav .tab-btn {
    font-size: 13px;
    padding: 6px 0 8px 0;
  }

  .new-card {
    padding: 0 12px 8px;
  }
}

/* ===== 手机端：主内容卡片内边距收窄（.l-card 原本 24px）===== */
@media (max-width: 600px) {
  .l-card {
    padding: 14px;
  }
}

/* ===== 关注选项卡 ===== */
.follow-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--border-color);
  padding-bottom: 12px;
}

.follow-tab {
  padding: 6px 16px;
  border-radius: 20px;
  border: 1px solid var(--border-color);
  background: var(--surface-strong);
  color: var(--text-main);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.follow-tab:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.follow-tab.active {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}

.follow-empty {
  text-align: center;
  padding: 40px 20px;
  color: var(--text-sub);
  font-size: 14px;
}

.follow-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.follow-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: var(--surface);
  -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  transition: all 0.2s;
}

.follow-item:hover {
  border-color: var(--primary);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.follow-user {
  display: flex;
  align-items: center;
  gap: 12px;
  text-decoration: none;
  color: inherit;
  flex: 1;
}

.follow-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--bg-subtle);
}

.follow-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.follow-name {
  font-weight: 600;
  color: var(--text-main);
  font-size: 14px;
}

.follow-tag {
  font-size: 12px;
  color: var(--text-sub);
}

.follow-btn-sm {
  padding: 4px 14px;
  border-radius: 16px;
  border: 1px solid var(--border-color);
  background: var(--surface-strong);
  color: var(--text-main);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.follow-btn-sm:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.follow-btn-sm.primary {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}

.follow-btn-sm.primary:hover {
  background: var(--primary-hover);
}

.follow-more {
  text-align: center;
  margin-top: 16px;
}

.follow-more .btn {
  padding: 8px 24px;
  border-radius: 20px;
  border: 1px solid var(--border-color);
  background: var(--surface-strong);
  color: var(--text-main);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.follow-more .btn:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
}

.follow-more .btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ===== 我的工作区（专栏与题单） ===== */
.my-workspace-pane {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* ===== 我的专栏与题单面板 ===== */
.my-training-pane {
  padding: 24px;
}

.my-training-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border-color);
}

.pane-title {
  margin: 0 0 4px 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--text-main);
  display: flex;
  align-items: center;
  gap: 8px;
}

.pane-title i {
  color: var(--primary);
}

.pane-sub {
  font-size: 13px;
  color: var(--text-muted);
}

.btn-create-list {
  background: var(--primary);
  color: #fff;
  border: none;
  padding: 8px 18px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s;
}

.btn-create-list:hover {
  filter: brightness(1.08);
  transform: translateY(-1px);
}

.training-empty {
  text-align: center;
  padding: 48px 20px;
  color: var(--text-muted);
}

.training-empty .empty-icon {
  font-size: 40px;
  color: #cbd5e1;
  margin-bottom: 12px;
}

.btn-create-sm {
  margin-top: 12px;
  background: var(--primary);
  color: #fff;
  border: none;
  padding: 6px 16px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
}

.my-training-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.my-training-card {
  background: var(--surface);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 16px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  flex-direction: column;
}

.my-training-card:hover {
  transform: translateY(-2px);
  border-color: var(--primary);
  box-shadow: var(--shadow-card-hover);
}

.my-card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.my-card-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-main);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.my-card-badges {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

.badge-featured-sm {
  background: color-mix(in srgb, var(--warning) 12%, transparent);
color: var(--warning-text);
  border: 1px solid #ffd591;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.badge-vis-sm {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
}

.badge-vis-sm.pub {
  background: color-mix(in srgb, var(--success) 10%, transparent);
color: var(--success-text);
}

.badge-vis-sm.pri {
  background: var(--bg-subtle);
  color: var(--text-sub);
}

.badge-cat-sm {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.cat-algo {
  background: color-mix(in srgb, var(--primary) 8%, transparent);
color: var(--primary-text);
  border: 1px solid #91caff;
}

.cat-tech {
  background: color-mix(in srgb, var(--accent) 8%, transparent);
color: var(--accent-text);
  border: 1px solid #d3adf7;
}

.cat-sol {
  background: color-mix(in srgb, var(--success) 10%, transparent);
color: var(--success-text);
  border: 1px solid #b7eb8f;
}

.cat-fun {
  background: color-mix(in srgb, var(--warning) 12%, transparent);
color: var(--warning-text);
  border: 1px solid #ffd591;
}

.cat-default {
  background: var(--bg-subtle);
  color: var(--text-sub);
  border: 1px solid #d9d9d9;
}

.category-select-group {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.cat-radio-label {
  border: 1px solid var(--border-color);
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
  color: var(--text-muted);
}

.cat-radio-label:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.cat-radio-label.active {
  background: var(--primary);
  color: #fff;
  border-color: var(--primary);
}

.my-card-desc {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0 0 12px 0;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 38px;
}

.my-card-meta {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--text-muted);
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px dashed var(--border-color, #e2e8f0);
}

.my-card-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 10px;
}

.btn-text {
  background: none;
  border: none;
  padding: 0;
  font-size: 13px;
  color: var(--primary);
  cursor: pointer;
}

.btn-text:hover {
  text-decoration: underline;
}

.btn-text.text-danger {
  color: #ef4444;
}

.badge-role-owner {
  background: color-mix(in srgb, #f59e0b 15%, transparent);
  color: #d97706;
  border: 1px solid #fcd34d;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.badge-role-admin {
  background: color-mix(in srgb, #8b5cf6 15%, transparent);
  color: #7c3aed;
  border: 1px solid #c4b5fd;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.badge-role-member {
  background: color-mix(in srgb, var(--primary) 12%, transparent);
  color: var(--primary);
  border: 1px solid color-mix(in srgb, var(--primary) 30%, transparent);
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.badge-banned-sm {
  background: color-mix(in srgb, #ef4444 15%, transparent);
  color: #dc2626;
  border: 1px solid #fca5a5;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.btn-enter-team {
  color: var(--primary);
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: all 0.2s;
}

.btn-enter-team:hover {
  transform: translateX(2px);
  color: var(--primary-hover, var(--primary));
}

/* Modal 弹窗通用样式 */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
}

.modal-card {
  background: var(--surface-plain);
  border-radius: 14px;
  width: 90%;
  max-width: 520px;
  padding: 24px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.15);
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 18px;
}

.modal-header h3 {
  margin: 0;
  font-size: 18px;
  color: var(--text-strong);
  display: flex;
  align-items: center;
  gap: 8px;
}

.close-btn {
  background: none;
  border: none;
  font-size: 18px;
  color: #94a3b8;
  cursor: pointer;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-strong);
  margin-bottom: 6px;
}

.form-group .req {
  color: #ef4444;
}

.form-input,
.form-textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 9px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 14px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.15s;
}

.form-input:focus,
.form-textarea:focus {
  border-color: var(--primary);
}

.radio-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.radio-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-sub);
  cursor: pointer;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 24px;
}

.btn-cancel {
  background: var(--bg-subtle);
  color: var(--text-sub);
  border: none;
  padding: 8px 18px;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
}

.btn-confirm {
  background: var(--primary);
  color: #fff;
  border: none;
  padding: 8px 22px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.btn-confirm:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
