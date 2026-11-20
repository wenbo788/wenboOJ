<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import apiClient from '@/api/client'

interface AdItem {
  image: string
  link: string
}

interface FriendLinkItem {
  title: string
  icon: string
  url: string
}

type Section = 'ads' | 'friends' | 'notice' | 'cloud'

interface NoticeItem {
  text: string
  link: string
}

const router = useRouter()
const MAX_ADS = 6
const DEFAULT_IMAGE = '/welcome.png'

const ads = ref<AdItem[]>([])
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const saved = ref(false)
const previewIndex = ref(0)
const activeSection = ref<Section>('ads')
const friendLinks = ref<FriendLinkItem[]>([])
const friendLinksLoading = ref(false)
const friendLinksSaving = ref(false)
const friendLinksSaved = ref(false)
const friendLinksError = ref('')

const canAdd = computed(() => ads.value.length < MAX_ADS)

/** 切 tab 时懒加载新面板（广告/友链在 onMounted 已加载） */
const switchSection = (section: Section) => {
  activeSection.value = section
  if (section === 'notice' && !noticeLoaded.value) void loadNotice()
  if (section === 'cloud' && !cloudLoaded.value) void loadCloud()
}
const previewAd = computed(() => ads.value[previewIndex.value])
const previewFriends = computed(() => friendLinks.value.filter(item => item.title.trim() && item.icon.trim()))

const loadAds = async () => {
  loading.value = true
  error.value = ''
  try {
    const data: any = await apiClient.get('/api/home-ads')
    const items = Array.isArray(data?.ads) ? data.ads : []
    ads.value = items.map((item: any) => ({
      image: item.image || '',
      link: item.link || '',
    }))
    previewIndex.value = 0
  } catch (err: any) {
    error.value = err?.response?.data?.detail || '广告加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

const loadFriendLinks = async () => {
  friendLinksLoading.value = true
  friendLinksError.value = ''
  try {
    const data: any = await apiClient.get('/api/friend-links')
    const items = Array.isArray(data?.links) ? data.links : []
    friendLinks.value = items.map((item: any) => ({
      title: item.title || '',
      icon: item.icon || '',
      url: item.url || '',
    }))
  } catch (err: any) {
    friendLinksError.value = err?.response?.data?.detail || '友情链接加载失败，请稍后重试'
  } finally {
    friendLinksLoading.value = false
  }
}

const addAd = () => {
  if (!canAdd.value) return
  ads.value.push({ image: '', link: '/' })
  previewIndex.value = ads.value.length - 1
  saved.value = false
}

const removeAd = (index: number) => {
  ads.value.splice(index, 1)
  if (previewIndex.value >= ads.value.length) previewIndex.value = Math.max(0, ads.value.length - 1)
  saved.value = false
}

const moveAd = (index: number, direction: -1 | 1) => {
  const target = index + direction
  if (target < 0 || target >= ads.value.length) return
  const current = ads.value[index]
  ads.value[index] = ads.value[target]
  ads.value[target] = current
  previewIndex.value = target
  saved.value = false
}

const saveAds = async () => {
  error.value = ''
  saved.value = false
  const invalid = ads.value.findIndex(ad => !ad.image.trim() || !ad.link.trim())
  if (invalid >= 0) {
    error.value = `请先完善第 ${invalid + 1} 个广告的图片地址和跳转链接`
    previewIndex.value = invalid
    return
  }

  saving.value = true
  try {
    await apiClient.put('/api/home-ads', ads.value.map(ad => ({
      image: ad.image.trim(),
      link: ad.link.trim(),
    })))
    await loadAds()
    saved.value = true
  } catch (err: any) {
    error.value = err?.response?.data?.detail || '保存失败，请稍后重试'
  } finally {
    saving.value = false
  }
}

const previewImage = (event: Event) => {
  const image = event.target as HTMLImageElement
  image.src = DEFAULT_IMAGE
}

const addFriendLink = () => {
  if (friendLinks.value.length >= 40) return
  friendLinks.value.push({ title: '', icon: '', url: 'https://' })
  friendLinksSaved.value = false
}

const removeFriendLink = (index: number) => {
  friendLinks.value.splice(index, 1)
  friendLinksSaved.value = false
}

const moveFriendLink = (index: number, direction: -1 | 1) => {
  const target = index + direction
  if (target < 0 || target >= friendLinks.value.length) return
  ;[friendLinks.value[index], friendLinks.value[target]] = [friendLinks.value[target], friendLinks.value[index]]
  friendLinksSaved.value = false
}

const saveFriendLinks = async () => {
  friendLinksError.value = ''
  friendLinksSaved.value = false
  const invalid = friendLinks.value.findIndex(item => !item.title.trim() || !item.icon.trim() || !item.url.trim())
  if (invalid >= 0) {
    friendLinksError.value = `请完善第 ${invalid + 1} 个友链的名称、图标和跳转地址`
    return
  }
  friendLinksSaving.value = true
  try {
    await apiClient.put('/api/friend-links', friendLinks.value.map(item => ({
      title: item.title.trim(), icon: item.icon.trim(), url: item.url.trim(),
    })))
    await loadFriendLinks()
    friendLinksSaved.value = true
  } catch (err: any) {
    friendLinksError.value = err?.response?.data?.detail || '保存失败，请稍后重试'
  } finally {
    friendLinksSaving.value = false
  }
}

const previewFriendIcon = (event: Event) => {
  const image = event.target as HTMLImageElement
  image.style.visibility = 'hidden'
}

/* ================= 顶栏公告 ================= */
const notice = ref<NoticeItem[]>([])
const noticeEnabled = ref(false)
const noticeLoading = ref(false)
const noticeSaving = ref(false)
const noticeSaved = ref(false)
const noticeError = ref('')
const noticeLoaded = ref(false)

const loadNotice = async () => {
  noticeLoading.value = true
  noticeError.value = ''
  try {
    const data: any = await apiClient.get('/api/site-settings/announcement')
    noticeEnabled.value = !!data?.enabled
    notice.value = Array.isArray(data?.items)
      ? data.items.map((it: any) => ({ text: it.text || '', link: it.link || '' }))
      : []
    noticeLoaded.value = true
  } catch (err: any) {
    noticeError.value = err?.response?.data?.detail || '公告配置加载失败'
  } finally {
    noticeLoading.value = false
  }
}

const addNotice = () => {
  if (notice.value.length >= 10) return
  notice.value.push({ text: '', link: '' })
  noticeSaved.value = false
}

const removeNotice = (index: number) => {
  notice.value.splice(index, 1)
  noticeSaved.value = false
}

const moveNotice = (index: number, step: number) => {
  const target = index + step
  if (target < 0 || target >= notice.value.length) return
  const [item] = notice.value.splice(index, 1)
  notice.value.splice(target, 0, item)
  noticeSaved.value = false
}

const saveNotice = async () => {
  noticeError.value = ''
  noticeSaved.value = false
  const invalid = notice.value.findIndex(item => !item.text.trim())
  if (invalid >= 0) {
    noticeError.value = `请填写第 ${invalid + 1} 条公告内容`
    return
  }
  if (noticeEnabled.value && notice.value.length === 0) {
    noticeError.value = '启用公告时至少要有一条内容'
    return
  }
  noticeSaving.value = true
  try {
    await apiClient.put('/api/site-settings/announcement', {
      enabled: noticeEnabled.value,
      items: notice.value.map(item => ({
        text: item.text.trim(),
        link: item.link.trim() || null,
      })),
    })
    noticeSaved.value = true
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    noticeError.value = typeof detail === 'string' ? detail : '保存失败，请稍后重试'
  } finally {
    noticeSaving.value = false
  }
}

/* ================= 首页云图栏目 ================= */
// 三张固定随机卡（友情链接随机 / 随机题目 / 随机讨论）由后端生成、
// 不进配置：启用云图就展示，管理员不可修改。管理端只配两张可修改卡：
// 精选题目（选题）与置顶讨论（选帖），各最多 4 条，空卡自动隐藏。
type CloudSlotKey = 'featured' | 'pinned'

interface CloudSlotDraft {
  enabled: boolean
  title: string
  ids: number[]
  /** 编辑器用：已选内容的标题缓存（后端只存 id，展示标题要靠它） */
  labels: Record<number, string>
}

const CLOUD_FIXED = [
  { icon: 'fa-solid fa-link', name: '友情链接（随机）' },
  { icon: 'fa-solid fa-code', name: '随机题目' },
  { icon: 'fa-solid fa-message', name: '随机讨论' },
]
const CLOUD_SLOT_MAX = 4

const emptySlot = (): CloudSlotDraft => ({ enabled: false, title: '', ids: [], labels: {} })

const cloudEnabled = ref(false)
const cloudFeatured = ref<CloudSlotDraft>(emptySlot())
const cloudPinned = ref<CloudSlotDraft>(emptySlot())
const cloudLoading = ref(false)
const cloudSaving = ref(false)
const cloudSaved = ref(false)
const cloudError = ref('')
const cloudLoaded = ref(false)
/** 两张可修改卡的搜索关键词与结果（管理端选内容用） */
const cloudSearch = ref<Record<CloudSlotKey, string>>({ featured: '', pinned: '' })
const cloudResults = ref<Record<CloudSlotKey, any[]>>({ featured: [], pinned: [] })
const cloudSearching = ref<Record<CloudSlotKey, boolean>>({ featured: false, pinned: false })

const cloudSlot = (key: CloudSlotKey): CloudSlotDraft =>
  key === 'featured' ? cloudFeatured.value : cloudPinned.value

const loadCloud = async () => {
  cloudLoading.value = true
  cloudError.value = ''
  try {
    const data: any = await apiClient.get('/api/site-settings/home-cloud')
    cloudEnabled.value = !!data?.enabled
    cloudFeatured.value = {
      enabled: !!data?.featured_problems?.enabled,
      title: data?.featured_problems?.title || '',
      ids: Array.isArray(data?.featured_problems?.problem_ids)
        ? data.featured_problems.problem_ids
        : [],
      labels: {},
    }
    cloudPinned.value = {
      enabled: !!data?.pinned_posts?.enabled,
      title: data?.pinned_posts?.title || '',
      ids: Array.isArray(data?.pinned_posts?.post_ids) ? data.pinned_posts.post_ids : [],
      labels: {},
    }
    // 回填已选帖子 / 题目的标题（后端只存 id）
    await Promise.all([resolveSlotLabels('featured'), resolveSlotLabels('pinned')])
    cloudLoaded.value = true
  } catch (err: any) {
    cloudError.value = err?.response?.data?.detail || '云图配置加载失败'
  } finally {
    cloudLoading.value = false
  }
}

/** 按 id 拉一次帖子 / 题目详情，把标题塞进 label 缓存 */
const resolveSlotLabels = async (key: CloudSlotKey) => {
  const slot = cloudSlot(key)
  const isProblem = key === 'featured'
  await Promise.all(
    slot.ids.map(async id => {
      if (slot.labels[id]) return
      try {
        const data: any = await apiClient.get(
          isProblem ? `/api/problems/${id}` : `/api/forum/posts/${id}`,
        )
        if (data?.id) slot.labels[id] = data.title || `#${id}`
      } catch {
        slot.labels[id] = `#${id}`
      }
    }),
  )
}

const searchCloudSlot = async (key: CloudSlotKey) => {
  const keyword = (cloudSearch.value[key] || '').trim()
  if (!keyword) return
  cloudSearching.value[key] = true
  try {
    // 拦截器已把 response.data 透传出来；编译期类型不准，转 any 后自行取字段
    const res: any =
      key === 'featured'
        ? await apiClient.get('/api/problems', { params: { keyword, page_size: 8 } })
        : await apiClient.get('/api/forum/posts', { params: { keyword, page_size: 8 } })
    const items = (res?.items || res?.posts || []) as any[]
    const slot = cloudSlot(key)
    for (const p of items) slot.labels[p.id] = p.title
    cloudResults.value[key] = items
  } catch (err: any) {
    cloudError.value = err?.response?.data?.detail || '搜索失败，请稍后重试'
  } finally {
    cloudSearching.value[key] = false
  }
}

const toggleCloudSlotItem = (key: CloudSlotKey, id: number) => {
  const slot = cloudSlot(key)
  const at = slot.ids.indexOf(id)
  if (at >= 0) slot.ids.splice(at, 1)
  else {
    if (slot.ids.length >= CLOUD_SLOT_MAX) return
    slot.ids.push(id)
  }
  cloudSaved.value = false
}

/** 预览小窗里按椭圆摆位（与首页同款角度算法，缩小版） */
const cloudPreviewStyle = (index: number, total: number) => {
  if (!total) return {}
  const angle = ((-90 + (360 / total) * index) * Math.PI) / 180
  return {
    left: `${50 + 40 * Math.cos(angle)}%`,
    top: `${50 + 40 * Math.sin(angle)}%`,
  }
}

/** 预览节点：固定 3 张 + 可修改 2 张（未启用 / 没选内容时置灰） */
const cloudPreviewNodes = computed(() => [
  ...CLOUD_FIXED.map(c => ({
    name: c.name,
    sub: '随机 3~4 条',
    icon: c.icon,
    active: true,
  })),
  {
    name: cloudFeatured.value.title || '精选题目',
    sub: `${cloudFeatured.value.ids.length} 题`,
    icon: 'fa-solid fa-code',
    active: cloudFeatured.value.enabled && cloudFeatured.value.ids.length > 0,
  },
  {
    name: cloudPinned.value.title || '置顶讨论',
    sub: `${cloudPinned.value.ids.length} 帖`,
    icon: 'fa-solid fa-message',
    active: cloudPinned.value.enabled && cloudPinned.value.ids.length > 0,
  },
])

const saveCloud = async () => {
  cloudError.value = ''
  cloudSaved.value = false
  cloudSaving.value = true
  try {
    await apiClient.put('/api/site-settings/home-cloud', {
      enabled: cloudEnabled.value,
      featured_problems: {
        enabled: cloudFeatured.value.enabled,
        title: cloudFeatured.value.title.trim(),
        problem_ids: cloudFeatured.value.ids,
      },
      pinned_posts: {
        enabled: cloudPinned.value.enabled,
        title: cloudPinned.value.title.trim(),
        post_ids: cloudPinned.value.ids,
      },
    })
    cloudSaved.value = true
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    cloudError.value = typeof detail === 'string' ? detail : '保存失败，请稍后重试'
  } finally {
    cloudSaving.value = false
  }
}

onMounted(() => {
  void loadAds()
  void loadFriendLinks()
})
</script>

<template>
  <div class="ads-page">
    <header class="ads-header">
      <div>
        <button class="back-button" title="返回首页" @click="router.push('/')">
          <i class="fa-solid fa-arrow-left"></i>
        </button>
        <div class="ads-heading">
          <p class="eyebrow">ADMIN / SITE</p>
          <h1>站点管理</h1>
          <p class="ads-subtitle">统一配置首页广告、友情链接、顶栏公告与首页云图，保存后立即生效。</p>
        </div>
      </div>
      <div class="ads-header-actions">
        <span v-if="activeSection === 'ads'" class="ads-count">{{ ads.length }} / {{ MAX_ADS }}</span>
        <span v-else-if="activeSection === 'friends'" class="ads-count">{{ friendLinks.length }} / 40</span>
        <span v-else-if="activeSection === 'notice'" class="ads-count">{{ notice.length }} / 10</span>
        <span v-else class="ads-count">3 固定 + 2 可配</span>
        <button v-if="activeSection === 'ads'" class="save-button" :disabled="saving || loading" @click="saveAds">
          <i class="fa-solid fa-check"></i>
          {{ saving ? '保存中...' : '保存全部' }}
        </button>
        <button v-else-if="activeSection === 'friends'" class="save-button" :disabled="friendLinksSaving || friendLinksLoading" @click="saveFriendLinks">
          <i class="fa-solid fa-check"></i>
          {{ friendLinksSaving ? '保存中...' : '保存全部' }}
        </button>
        <button v-else-if="activeSection === 'notice'" class="save-button" :disabled="noticeSaving || noticeLoading" @click="saveNotice">
          <i class="fa-solid fa-check"></i>
          {{ noticeSaving ? '保存中...' : '保存全部' }}
        </button>
        <button v-else class="save-button" :disabled="cloudSaving || cloudLoading" @click="saveCloud">
          <i class="fa-solid fa-check"></i>
          {{ cloudSaving ? '保存中...' : '保存全部' }}
        </button>
      </div>
    </header>

    <nav class="site-tabs" aria-label="站点配置分类">
      <button :class="{ active: activeSection === 'ads' }" @click="activeSection = 'ads'">
        <i class="fa-solid fa-rectangle-ad"></i> 首页广告
      </button>
      <button :class="{ active: activeSection === 'friends' }" @click="activeSection = 'friends'">
        <i class="fa-solid fa-link"></i> 友情链接
      </button>
      <button :class="{ active: activeSection === 'notice' }" @click="switchSection('notice')">
        <i class="fa-solid fa-bullhorn"></i> 顶栏公告
      </button>
      <button :class="{ active: activeSection === 'cloud' }" @click="switchSection('cloud')">
        <i class="fa-solid fa-circle-nodes"></i> 首页云图
      </button>
    </nav>

    <div v-if="activeSection === 'ads' && error" class="notice error-notice">
      <i class="fa-solid fa-circle-exclamation"></i>{{ error }}
    </div>
    <div v-if="activeSection === 'ads' && saved" class="notice success-notice">
      <i class="fa-solid fa-circle-check"></i>广告配置已保存
    </div>
    <div v-if="activeSection === 'friends' && friendLinksError" class="notice error-notice">
      <i class="fa-solid fa-circle-exclamation"></i>{{ friendLinksError }}
    </div>
    <div v-if="activeSection === 'friends' && friendLinksSaved" class="notice success-notice">
      <i class="fa-solid fa-circle-check"></i>友情链接已保存
    </div>
    <div v-if="activeSection === 'notice' && noticeError" class="notice error-notice">
      <i class="fa-solid fa-circle-exclamation"></i>{{ noticeError }}
    </div>
    <div v-if="activeSection === 'notice' && noticeSaved" class="notice success-notice">
      <i class="fa-solid fa-circle-check"></i>顶栏公告已保存
    </div>
    <div v-if="activeSection === 'cloud' && cloudError" class="notice error-notice">
      <i class="fa-solid fa-circle-exclamation"></i>{{ cloudError }}
    </div>
    <div v-if="activeSection === 'cloud' && cloudSaved" class="notice success-notice">
      <i class="fa-solid fa-circle-check"></i>首页云图配置已保存
    </div>

    <div v-if="activeSection === 'ads' && loading" class="loading-state">正在加载广告配置...</div>
    <main v-else-if="activeSection === 'ads'" class="ads-layout">
      <section class="ads-editor-panel">
        <div class="section-heading">
          <div>
            <h2>轮播内容</h2>
            <p>直接在卡片内编辑，顺序就是首页的播放顺序。</p>
          </div>
          <button class="add-button" :disabled="!canAdd" @click="addAd">
            <i class="fa-solid fa-plus"></i> 添加广告
          </button>
        </div>

        <div v-if="ads.length" class="ad-list">
          <article
            v-for="(ad, index) in ads"
            :key="index"
            class="ad-edit-card"
            :class="{ selected: previewIndex === index }"
            @click="previewIndex = index"
          >
            <div class="card-index">{{ String(index + 1).padStart(2, '0') }}</div>
            <div class="card-preview">
              <img :src="ad.image || DEFAULT_IMAGE" alt="广告预览" @error="previewImage">
            </div>
            <div class="card-fields">
              <label>
                <span>图片地址</span>
                <input v-model="ad.image" type="text" placeholder="https://... 或 /uploads/banner.png" @click.stop>
              </label>
              <label>
                <span>跳转链接</span>
                <input v-model="ad.link" type="text" placeholder="/contest/1 或 https://..." @click.stop>
              </label>
            </div>
            <div class="card-actions" @click.stop>
              <button title="上移" :disabled="index === 0" @click="moveAd(index, -1)"><i class="fa-solid fa-chevron-up"></i></button>
              <button title="下移" :disabled="index === ads.length - 1" @click="moveAd(index, 1)"><i class="fa-solid fa-chevron-down"></i></button>
              <button class="delete-action" title="删除" @click="removeAd(index)"><i class="fa-solid fa-trash"></i></button>
            </div>
          </article>
        </div>
        <div v-else class="empty-editor">
          <i class="fa-regular fa-images"></i>
          <strong>还没有广告</strong>
          <span>添加一张图片，首页就会拥有第一帧内容。</span>
          <button class="add-button" @click="addAd"><i class="fa-solid fa-plus"></i> 添加第一张</button>
        </div>
      </section>

      <aside class="ads-preview-panel">
        <div class="section-heading compact-heading">
          <div>
            <h2>实时预览</h2>
            <p>点击左侧卡片切换预览</p>
          </div>
          <span class="live-badge"><span></span> LIVE</span>
        </div>
        <div class="preview-stage">
          <div v-if="previewAd" class="preview-frame">
            <img :src="previewAd.image || DEFAULT_IMAGE" alt="当前广告" @error="previewImage">
            <div class="preview-overlay">
              <span>第 {{ previewIndex + 1 }} / {{ ads.length }} 张</span>
              <span>{{ previewAd.link || '尚未设置链接' }}</span>
            </div>
          </div>
          <div v-else class="preview-empty">添加广告后查看预览</div>
        </div>
        <p class="preview-note"><i class="fa-solid fa-circle-info"></i> 首页会以 320px 高度展示，并自动平滑切换。</p>
      </aside>
    </main>

    <div v-else-if="activeSection === 'friends' && friendLinksLoading" class="loading-state">正在加载友情链接...</div>
    <main v-else-if="activeSection === 'friends'" class="ads-layout">
      <section class="ads-editor-panel">
        <div class="section-heading">
          <div>
            <h2>友情链接</h2>
            <p>图标和名称会以网格显示在首页，顺序可调整，最多 40 个。</p>
          </div>
          <button class="add-button" :disabled="friendLinks.length >= 40" @click="addFriendLink">
            <i class="fa-solid fa-plus"></i> 添加友链
          </button>
        </div>

        <div v-if="friendLinks.length" class="ad-list">
          <article v-for="(item, index) in friendLinks" :key="index" class="friend-edit-card">
            <div class="card-index">{{ String(index + 1).padStart(2, '0') }}</div>
            <div class="friend-icon-preview">
              <img v-if="item.icon" :src="item.icon" :alt="item.title" @error="previewFriendIcon">
              <i v-else class="fa-solid fa-image"></i>
              <span>{{ item.title || '名称预览' }}</span>
            </div>
            <div class="card-fields">
              <label><span>名称</span><input v-model="item.title" maxlength="80" placeholder="例如：OI Wiki" @input="friendLinksSaved = false"></label>
              <label><span>图标地址</span><input v-model="item.icon" maxlength="500" placeholder="https://... 或 /uploads/logo.png" @input="friendLinksSaved = false"></label>
              <label><span>跳转地址</span><input v-model="item.url" maxlength="500" placeholder="https://example.com" @input="friendLinksSaved = false"></label>
            </div>
            <div class="card-actions">
              <button title="上移" :disabled="index === 0" @click="moveFriendLink(index, -1)"><i class="fa-solid fa-chevron-up"></i></button>
              <button title="下移" :disabled="index === friendLinks.length - 1" @click="moveFriendLink(index, 1)"><i class="fa-solid fa-chevron-down"></i></button>
              <button class="delete-action" title="删除" @click="removeFriendLink(index)"><i class="fa-solid fa-trash"></i></button>
            </div>
          </article>
        </div>
        <div v-else class="empty-editor">
          <i class="fa-solid fa-link"></i>
          <strong>还没有友情链接</strong>
          <span>添加站点后，首页会按图标在上、标题在下的格式展示。</span>
          <button class="add-button" @click="addFriendLink"><i class="fa-solid fa-plus"></i> 添加第一个友链</button>
        </div>
      </section>

      <aside class="ads-preview-panel">
        <div class="section-heading compact-heading">
          <div><h2>首页预览</h2><p>图标在上，标题在下</p></div>
          <span class="live-badge"><span></span> LIVE</span>
        </div>
        <div v-if="previewFriends.length" class="friend-preview-grid">
          <a v-for="(item, index) in previewFriends" :key="index" :href="item.url" class="friend-preview-item" @click.prevent>
            <img :src="item.icon" :alt="item.title" @error="previewFriendIcon">
            <span>{{ item.title }}</span>
          </a>
        </div>
        <div v-else class="preview-empty friend-preview-empty">添加完整的名称和图标后预览</div>
        <p class="preview-note"><i class="fa-solid fa-circle-info"></i> 点击首页友链将在新标签页打开。</p>
      </aside>
    </main>

    <!-- ===== 顶栏公告 ===== -->
    <div v-else-if="activeSection === 'notice' && noticeLoading" class="loading-state">正在加载公告配置...</div>
    <main v-else-if="activeSection === 'notice'" class="ads-layout">
      <section class="ads-editor-panel">
        <div class="section-heading">
          <div>
            <h2>顶栏公告</h2>
            <p>显示在顶栏 Logo 与头像之间，多条时垂直轮播，每条停留数秒，最多 10 条。</p>
          </div>
          <div class="heading-tools">
            <label class="toggle-row">
              <input v-model="noticeEnabled" type="checkbox">
              <span>启用</span>
            </label>
            <button class="add-button" :disabled="notice.length >= 10" @click="addNotice">
              <i class="fa-solid fa-plus"></i> 添加公告
            </button>
          </div>
        </div>

        <div v-if="notice.length" class="ad-list">
          <article v-for="(item, index) in notice" :key="index" class="friend-edit-card notice-card">
            <div class="card-index">{{ String(index + 1).padStart(2, '0') }}</div>
            <div class="card-fields">
              <label><span>公告内容</span><input v-model="item.text" maxlength="200" placeholder="例如：今晚 20:00 比赛开始" @input="noticeSaved = false"></label>
              <label><span>跳转链接（可空）</span><input v-model="item.link" maxlength="500" placeholder="/contests 或 https://..." @input="noticeSaved = false"></label>
            </div>
            <div class="card-actions">
              <button title="上移" :disabled="index === 0" @click="moveNotice(index, -1)"><i class="fa-solid fa-chevron-up"></i></button>
              <button title="下移" :disabled="index === notice.length - 1" @click="moveNotice(index, 1)"><i class="fa-solid fa-chevron-down"></i></button>
              <button class="delete-action" title="删除" @click="removeNotice(index)"><i class="fa-solid fa-trash"></i></button>
            </div>
          </article>
        </div>
        <div v-else class="empty-editor">
          <i class="fa-regular fa-bell"></i>
          <strong>还没有公告</strong>
          <span>添加一条公告，顶栏中央就会出现滚动播报位。</span>
          <button class="add-button" @click="addNotice"><i class="fa-solid fa-plus"></i> 添加第一条</button>
        </div>
      </section>

      <aside class="ads-preview-panel">
        <div class="section-heading compact-heading">
          <div><h2>顶栏预览</h2><p>Logo 与头像之间的胶囊位</p></div>
          <span class="live-badge"><span></span> LIVE</span>
        </div>
        <div class="topbar-preview">
          <span class="topbar-preview-logo">NLNOJ</span>
          <span v-if="noticeEnabled && notice.length && notice[0].text" class="topbar-preview-notice">
            <i class="fa-solid fa-bullhorn"></i>{{ notice[0].text }}
          </span>
          <span v-else class="topbar-preview-notice placeholder">未启用 / 无内容时不占位</span>
          <span class="topbar-preview-avatar"></span>
        </div>
        <div class="preview-list">
          <div v-for="(item, index) in notice" :key="index" class="preview-list-row">
            <span class="preview-list-index">{{ index + 1 }}</span>
            <span class="preview-list-text">{{ item.text || '（空）' }}</span>
            <span class="preview-list-link">{{ item.link || '不可点击' }}</span>
          </div>
          <div v-if="!notice.length" class="preview-empty">添加公告后查看预览</div>
        </div>
        <p class="preview-note"><i class="fa-solid fa-circle-info"></i> 未启用时顶栏不显示公告位，也不占空间。</p>
      </aside>
    </main>

    <!-- ===== 首页云图 ===== -->
    <div v-else-if="activeSection === 'cloud' && cloudLoading" class="loading-state">正在加载云图配置...</div>
    <main v-else-if="activeSection === 'cloud'" class="ads-layout">
      <section class="ads-editor-panel">
        <div class="section-heading">
          <div>
            <h2>首页云图栏目</h2>
            <p>固定三张随机卡自动展示、不可修改；再配两张可修改卡（各最多 4 条），没内容的卡自动隐藏。</p>
          </div>
          <div class="heading-tools">
            <label class="toggle-row">
              <input v-model="cloudEnabled" type="checkbox">
              <span>启用云图</span>
            </label>
          </div>
        </div>

        <!-- 固定卡：启用云图就展示，站点管理不可修改 -->
        <div class="cloud-fixed-note">
          <span class="cloud-fixed-label"><i class="fa-solid fa-lock"></i> 固定卡</span>
          <span v-for="c in CLOUD_FIXED" :key="c.name" class="cloud-fixed-chip">
            <i :class="c.icon"></i>{{ c.name }} · 随机 3~4 条
          </span>
        </div>

        <div class="ad-list">
          <!-- 可修改卡 1：精选题目 -->
          <article class="cloud-edit-card">
            <div class="card-index"><i class="fa-solid fa-code"></i></div>
            <div class="card-fields">
              <label class="toggle-row slot-toggle">
                <input v-model="cloudFeatured.enabled" type="checkbox" @change="cloudSaved = false">
                <span>展示这张卡</span>
              </label>
              <label><span>标题（可空，默认「精选题目」）</span><input v-model="cloudFeatured.title" maxlength="30" placeholder="精选题目" @input="cloudSaved = false"></label>
              <label>
                <span>搜索题目（已选 {{ cloudFeatured.ids.length }} / {{ CLOUD_SLOT_MAX }}）</span>
                <span class="search-row">
                  <input
                    v-model="cloudSearch.featured"
                    type="text"
                    placeholder="输入题号或标题关键词，回车搜索"
                    @keyup.enter="searchCloudSlot('featured')"
                  >
                  <button type="button" class="search-button" :disabled="cloudSearching.featured" @click="searchCloudSlot('featured')">
                    <i class="fa-solid fa-magnifying-glass"></i>{{ cloudSearching.featured ? '搜索中' : '搜索' }}
                  </button>
                </span>
              </label>
              <div v-if="cloudFeatured.ids.length" class="picked-list">
                <span v-for="qid in cloudFeatured.ids" :key="qid" class="picked-chip" @click="toggleCloudSlotItem('featured', qid)">
                  {{ cloudFeatured.labels[qid] || `#${qid}` }} <i class="fa-solid fa-xmark"></i>
                </span>
              </div>
              <div v-if="cloudResults.featured.length" class="search-results">
                <button
                  v-for="p in cloudResults.featured"
                  :key="p.id"
                  type="button"
                  :class="{ picked: cloudFeatured.ids.includes(p.id) }"
                  :disabled="!cloudFeatured.ids.includes(p.id) && cloudFeatured.ids.length >= CLOUD_SLOT_MAX"
                  @click="toggleCloudSlotItem('featured', p.id)"
                >
                  <span>{{ p.problem_number }} {{ p.title }}</span>
                  <small>{{ p.difficulty }}</small>
                </button>
              </div>
            </div>
          </article>

          <!-- 可修改卡 2：置顶讨论 -->
          <article class="cloud-edit-card">
            <div class="card-index"><i class="fa-solid fa-message"></i></div>
            <div class="card-fields">
              <label class="toggle-row slot-toggle">
                <input v-model="cloudPinned.enabled" type="checkbox" @change="cloudSaved = false">
                <span>展示这张卡</span>
              </label>
              <label><span>标题（可空，默认「置顶讨论」）</span><input v-model="cloudPinned.title" maxlength="30" placeholder="置顶讨论" @input="cloudSaved = false"></label>
              <label>
                <span>搜索帖子（已选 {{ cloudPinned.ids.length }} / {{ CLOUD_SLOT_MAX }}）</span>
                <span class="search-row">
                  <input
                    v-model="cloudSearch.pinned"
                    type="text"
                    placeholder="输入标题或正文关键词，回车搜索"
                    @keyup.enter="searchCloudSlot('pinned')"
                  >
                  <button type="button" class="search-button" :disabled="cloudSearching.pinned" @click="searchCloudSlot('pinned')">
                    <i class="fa-solid fa-magnifying-glass"></i>{{ cloudSearching.pinned ? '搜索中' : '搜索' }}
                  </button>
                </span>
              </label>
              <div v-if="cloudPinned.ids.length" class="picked-list">
                <span v-for="pid in cloudPinned.ids" :key="pid" class="picked-chip" @click="toggleCloudSlotItem('pinned', pid)">
                  {{ cloudPinned.labels[pid] || `#${pid}` }} <i class="fa-solid fa-xmark"></i>
                </span>
              </div>
              <div v-if="cloudResults.pinned.length" class="search-results">
                <button
                  v-for="p in cloudResults.pinned"
                  :key="p.id"
                  type="button"
                  :class="{ picked: cloudPinned.ids.includes(p.id) }"
                  :disabled="!cloudPinned.ids.includes(p.id) && cloudPinned.ids.length >= CLOUD_SLOT_MAX"
                  @click="toggleCloudSlotItem('pinned', p.id)"
                >
                  <span>{{ p.title }}</span>
                  <small>{{ p.author?.username }} · {{ p.forum_name }}</small>
                </button>
              </div>
            </div>
          </article>
        </div>
      </section>

      <aside class="ads-preview-panel">
        <div class="section-heading compact-heading">
          <div><h2>云图预览</h2><p>中央固定，四周固定 3 张 + 可配 2 张</p></div>
          <span class="live-badge"><span></span> LIVE</span>
        </div>
        <div class="cloud-preview">
          <div class="cloud-preview-center">
            <i class="fa-solid fa-user-astronaut"></i>
            <span>头像 + 运势</span>
          </div>
          <div
            v-for="(node, index) in cloudPreviewNodes"
            :key="index"
            class="cloud-preview-node"
            :class="{ dim: !cloudEnabled || !node.active }"
            :style="cloudPreviewStyle(index, cloudPreviewNodes.length)"
          >
            <i :class="node.icon"></i>
            <span>{{ node.name }}</span>
            <small>{{ node.sub }}</small>
          </div>
        </div>
        <p class="preview-note"><i class="fa-solid fa-circle-info"></i> 首屏不展示广告；三张固定卡每次进首页随机换内容（各 3~4 条）；首页小卡位置每次进入自动随机散布并做避让（不压中央面板），带入场 / 浮动动画；窄屏（≤768px 或放不下）自动降级为纵排、不画连接线。</p>
      </aside>
    </main>
  </div>
</template>

<style scoped>
.ads-page {
  min-height: 100vh;
  padding: 34px clamp(18px, 4vw, 64px) 60px;
  color: var(--text-strong);
}

.ads-header {
  max-width: 1320px;
  margin: 0 auto 26px;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 24px;
}

.ads-header > div:first-child {
  display: flex;
  gap: 16px;
}

.back-button,
.card-actions button {
  border: 1px solid #dce3ee;
  background: var(--surface-plain);
  color: var(--text-sub);
  cursor: pointer;
}

.back-button {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  font-size: 16px;
}

.back-button:hover,
.card-actions button:hover:not(:disabled) {
  color: var(--primary);
  border-color: var(--primary);
}

.eyebrow {
  margin: 0 0 6px;
  color: var(--primary);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 1.5px;
}

.ads-heading h1 {
  margin: 0;
  color: var(--text-strong);
  font-size: 30px;
  line-height: 1.2;
}

.ads-subtitle,
.section-heading p {
  margin: 7px 0 0;
  color: var(--text-sub);
  font-size: 13px;
}

.ads-header-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}

.site-tabs {
  max-width: 1320px;
  margin: 0 auto 16px;
  display: flex;
  gap: 6px;
  border-bottom: 1px solid #dce3ee;
}

.site-tabs button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--text-sub);
  font: inherit;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.site-tabs button.active {
  border-bottom-color: var(--primary);
  color: var(--primary);
}

.ads-count {
  color: var(--text-sub);
  font-size: 13px;
  font-weight: 700;
}

.save-button,
.add-button {
  border: 0;
  border-radius: 10px;
  background: var(--primary);
  color: #fff;
  cursor: pointer;
  font: inherit;
  font-weight: 700;
}

.save-button {
  padding: 11px 18px;
}

.add-button {
  padding: 9px 14px;
  font-size: 13px;
}

.save-button:hover,
.add-button:hover:not(:disabled) {
  filter: brightness(1.08);
}

.save-button:disabled,
.add-button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.notice,
.loading-state {
  max-width: 1320px;
  margin: 0 auto 16px;
  padding: 12px 16px;
  border-radius: 10px;
  font-size: 13px;
}

.notice i {
  margin-right: 8px;
}

.error-notice {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
color: var(--danger-text);
}

.success-notice {
  background: color-mix(in srgb, var(--success) 10%, transparent);
color: var(--success-text);
}

.loading-state {
  background: var(--surface-plain);
  color: var(--text-sub);
  text-align: center;
}

.ads-layout {
  max-width: 1320px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(320px, 0.8fr);
  gap: 20px;
  align-items: start;
}

.ads-editor-panel,
.ads-preview-panel {
  padding: 22px;
  border: 1px solid #e5eaf2;
  border-radius: 16px;
  background: var(--surface-plain);
  box-shadow: 0 8px 24px rgba(42, 58, 83, 0.05);
}

.section-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 18px;
}

.section-heading h2 {
  margin: 0;
  color: var(--text-strong);
  font-size: 17px;
}

.ad-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ad-edit-card {
  display: grid;
  grid-template-columns: 34px 128px minmax(0, 1fr) auto;
  align-items: center;
  gap: 14px;
  padding: 12px;
  border: 1px solid #e7ecf3;
  border-radius: 12px;
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s, transform 0.2s;
}

.ad-edit-card:hover,
.ad-edit-card.selected {
  border-color: #aebaf4;
  box-shadow: 0 5px 16px rgba(80, 91, 190, 0.1);
}

.ad-edit-card.selected {
  transform: translateX(2px);
}

.friend-edit-card {
  display: grid;
  grid-template-columns: 34px 116px minmax(0, 1fr) auto;
  align-items: center;
  gap: 14px;
  padding: 12px;
  border: 1px solid #e7ecf3;
  border-radius: 12px;
}

.friend-icon-preview,
.friend-preview-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-width: 0;
  color: var(--text-strong);
  text-align: center;
}

.friend-icon-preview {
  width: 116px;
  min-height: 90px;
  padding: 8px;
  border-radius: 8px;
  background: var(--bg-subtle);
  font-size: 11px;
  overflow: hidden;
}

.friend-icon-preview img,
.friend-preview-item img {
  width: 42px;
  height: 42px;
  object-fit: contain;
}

.friend-icon-preview i {
  color: #9aa6b8;
  font-size: 25px;
}

.friend-icon-preview span,
.friend-preview-item span {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.friend-preview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(86px, 1fr));
  gap: 8px;
  padding: 12px;
  border-radius: 10px;
  background: var(--surface-plain);
}

.friend-preview-item {
  min-height: 92px;
  padding: 8px 5px;
  border-radius: 8px;
  background: var(--surface-plain);
  text-decoration: none;
  font-size: 11px;
}

.friend-preview-empty {
  min-height: 150px;
}

.card-index {
  color: var(--primary);
  font-size: 12px;
  font-weight: 800;
}

.card-preview {
  width: 128px;
  height: 72px;
  overflow: hidden;
  border-radius: 8px;
  background: var(--bg-subtle);
}

.card-preview img,
.preview-frame img {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: cover;
}

.card-fields {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.card-fields label {
  display: grid;
  grid-template-columns: 68px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
}

.card-fields label span,
.ad-field span {
  color: var(--text-sub);
  font-size: 11px;
}

.card-fields input {
  min-width: 0;
  width: 100%;
  padding: 7px 9px;
  border: 1px solid #dbe3ef;
  border-radius: 7px;
  color: var(--text-strong);
  font: inherit;
  font-size: 12px;
  box-sizing: border-box;
}

.card-fields input:focus {
  outline: 2px solid rgba(92, 101, 207, 0.16);
  border-color: var(--primary);
}

.card-actions {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.card-actions button {
  width: 28px;
  height: 26px;
  border-radius: 6px;
  font-size: 11px;
}

.card-actions button:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.card-actions .delete-action {
  color: #c0392b;
}

/* ---------- 顶栏公告 / 首页云图 新面板 ---------- */
.heading-tools {
  display: flex;
  align-items: center;
  gap: 14px;
}

.toggle-row {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  color: var(--text-sub);
  cursor: pointer;
  user-select: none;
}

.toggle-row input {
  width: 16px;
  height: 16px;
  accent-color: var(--primary);
  cursor: pointer;
}

.notice-card {
  grid-template-columns: 34px minmax(0, 1fr) auto;
}

/* 云图栏目编辑卡：没有缩略图列，字段独占中间 */
.cloud-edit-card {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  align-items: start;
  gap: 14px;
  padding: 12px;
  border: 1px solid #e7ecf3;
  border-radius: 12px;
}

.cloud-edit-card .card-fields label,
.notice-card .card-fields label {
  grid-template-columns: minmax(0, 180px) minmax(0, 1fr);
}

.search-row {
  display: flex !important;
  gap: 8px;
}

.search-button {
  flex: none;
  padding: 7px 12px;
  border: 1px solid var(--primary);
  border-radius: 7px;
  background: var(--primary);
  color: #fff;
  font-size: 12px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.search-button:disabled {
  opacity: 0.6;
  cursor: wait;
}

.picked-list,
.search-results {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.picked-list {
  grid-column: 1 / -1;
  margin-top: 2px;
}

.picked-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 240px;
  padding: 3px 9px;
  border: 1px solid color-mix(in srgb, var(--primary) 45%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--primary) 9%, transparent);
  color: var(--text-strong);
  font-size: 11.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}

.picked-chip i {
  color: var(--text-sub);
  font-size: 10px;
}

.picked-chip:hover {
  border-color: #c0392b;
}

.search-results {
  grid-column: 1 / -1;
}

.search-results button {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  max-width: 230px;
  padding: 6px 10px;
  border: 1px solid #e3e9f2;
  border-radius: 8px;
  background: var(--surface-plain);
  cursor: pointer;
  text-align: left;
}

.search-results button span {
  font-size: 12px;
  color: var(--text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.search-results button small {
  font-size: 11px;
  color: var(--text-sub);
}

.search-results button:hover:not(:disabled) {
  border-color: var(--primary);
}

.search-results button.picked {
  border-color: var(--primary);
  background: color-mix(in srgb, var(--primary) 8%, transparent);
}

.search-results button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* 顶栏预览条 */
.topbar-preview {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid #e7ecf3;
  border-radius: 12px;
  background: var(--surface-plain);
}

.topbar-preview-logo {
  flex: none;
  font-size: 15px;
  font-weight: 800;
  color: var(--primary);
}

.topbar-preview-notice {
  flex: 1;
  min-width: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 5px 12px;
  border: 1px solid color-mix(in srgb, var(--primary) 25%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--primary) 7%, transparent);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.topbar-preview-notice i {
  color: var(--primary);
  font-size: 11px;
}

.topbar-preview-notice.placeholder {
  border-style: dashed;
  color: var(--text-sub);
  font-weight: 400;
}

.topbar-preview-avatar {
  flex: none;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--primary), var(--grad-violet));
}

.preview-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.preview-list-row {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 7px 10px;
  border: 1px solid #e7ecf3;
  border-radius: 8px;
  font-size: 12px;
}

.preview-list-index {
  flex: none;
  width: 20px;
  height: 20px;
  border-radius: 6px;
  background: color-mix(in srgb, var(--primary) 12%, transparent);
  color: var(--primary);
  font-size: 11px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.preview-list-text {
  flex: 1;
  min-width: 0;
  color: var(--text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-list-link {
  flex: none;
  color: var(--text-sub);
  font-size: 11px;
  max-width: 40%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 云图布局预览 */
.cloud-preview {
  position: relative;
  height: 300px;
  border: 1px solid #e7ecf3;
  border-radius: 12px;
  background:
    radial-gradient(circle at 50% 50%, color-mix(in srgb, var(--primary) 6%, transparent), transparent 60%),
    var(--surface-plain);
}

.cloud-preview-center {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  width: 96px;
  padding: 12px 8px;
  border: 1px solid color-mix(in srgb, var(--primary) 40%, transparent);
  border-radius: 12px;
  background: var(--surface-strong);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-sub);
  text-align: center;
  z-index: 1;
}

.cloud-preview-center i {
  font-size: 22px;
  color: var(--primary);
}

.cloud-preview-node {
  position: absolute;
  transform: translate(-50%, -50%);
  width: 88px;
  padding: 7px 6px;
  border: 1px solid #e7ecf3;
  border-radius: 9px;
  background: var(--surface-plain);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  font-size: 11px;
  color: var(--text-strong);
  text-align: center;
  box-shadow: 0 3px 10px rgba(80, 91, 190, 0.08);
}

.cloud-preview-node i {
  color: var(--primary);
  font-size: 11px;
}

.cloud-preview-node span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.cloud-preview-node small {
  color: var(--text-sub);
  font-size: 10px;
}

/* 预览里未启用 / 没内容的可修改卡置灰 */
.cloud-preview-node.dim {
  opacity: 0.45;
  filter: grayscale(0.6);
}

/* 固定卡说明条：三张不可修改的随机卡 */
.cloud-fixed-note {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  padding: 10px 12px;
  border: 1px dashed #d8e0ea;
  border-radius: 10px;
  background: var(--bg-subtle);
}

.cloud-fixed-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-sub);
}

.cloud-fixed-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid #e7ecf3;
  border-radius: 999px;
  background: var(--surface-plain);
  font-size: 12px;
  color: var(--text-strong);
}

.cloud-fixed-chip i {
  color: var(--primary);
}

/* 可修改卡的「展示这张卡」开关行：不按常规标签的两列栅格排 */
.cloud-edit-card .card-fields label.slot-toggle {
  display: inline-flex;
  grid-template-columns: none;
  gap: 7px;
}

.cloud-edit-card .card-fields label.slot-toggle span {
  font-size: 13px;
  color: var(--text-sub);
}

.cloud-preview-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-sub);
  font-size: 13px;
}

.empty-editor {
  display: flex;
  min-height: 260px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 9px;
  border: 1px dashed #d5deeb;
  border-radius: 12px;
  color: var(--text-sub);
  font-size: 13px;
}

.empty-editor i {
  color: #b4bfd0;
  font-size: 30px;
}

.empty-editor strong {
  color: var(--text-sub);
}

.empty-editor .add-button {
  margin-top: 8px;
}

.compact-heading {
  align-items: flex-start;
}

.live-badge {
color: light-dark(#24a36a, #34d399);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 1px;
}

.live-badge span {
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-right: 5px;
  border-radius: 50%;
  background: #2bb673;
  vertical-align: 1px;
}

.preview-stage {
  padding: 10px;
  border-radius: 12px;
  background: var(--bg-subtle);
}

.preview-frame {
  width: 100%;
  aspect-ratio: 16 / 7;
  overflow: hidden;
  position: relative;
  border-radius: 9px;
  background: #dfe6f2;
}

.preview-overlay {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 10px;
  background: linear-gradient(transparent, rgba(20, 29, 44, 0.78));
  color: #fff;
  font-size: 11px;
}

.preview-overlay span:last-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-empty {
  display: grid;
  min-height: 180px;
  place-items: center;
  color: var(--text-sub);
  font-size: 13px;
}

.preview-note {
  margin: 14px 2px 0;
  color: var(--text-sub);
  font-size: 12px;
  line-height: 1.5;
}

.preview-note i {
  margin-right: 6px;
  color: var(--primary);
}

@media (max-width: 900px) {
  .ads-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 620px) {
  .ads-page {
    padding: 22px 12px 40px;
  }

  .ads-header {
    flex-direction: column;
  }

  .ads-header-actions {
    width: 100%;
    justify-content: space-between;
  }

  .ad-edit-card {
    grid-template-columns: 26px 88px minmax(0, 1fr) auto;
    gap: 9px;
    padding: 9px;
  }

  .friend-edit-card {
    grid-template-columns: 26px minmax(0, 1fr) auto;
    gap: 9px;
    padding: 9px;
  }

  .friend-edit-card .friend-icon-preview {
    grid-column: 2;
    grid-row: 1;
    width: auto;
    min-height: 76px;
  }

  .friend-edit-card .card-fields {
    grid-column: 1 / -1;
    grid-row: 2;
  }

  .friend-edit-card .card-actions {
    grid-column: 3;
    grid-row: 1;
    flex-direction: row;
  }

  .card-preview {
    width: 88px;
    height: 58px;
  }

  .card-fields label {
    display: block;
  }

  .site-tabs button {
    flex: 1;
    justify-content: center;
    padding-inline: 8px;
  }

  .card-fields label span {
    display: block;
    margin-bottom: 3px;
  }
}
</style>
