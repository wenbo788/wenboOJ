<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import apiClient from '@/api/client'
import { trainingsApi, type TrainingListItem } from '@/api/trainings'
import { userNameColor } from '@/utils/userColor'
import { getUserTagDisplay } from '@/utils/userTag'
import { useAcademicMode } from '@/utils/academicMode'
import UserAvatarStatus from '@/components/UserAvatarStatus.vue'
import BenbenMarkdownEditor from '@/components/BenbenMarkdownEditor.vue'
import { isUserOnline } from '@/utils/presence'

const router = useRouter()
const authStore = useAuthStore()

// 学术模式：开启后隐藏犇犇模块
const { academicMode } = useAcademicMode()

const isLoggedIn = computed(() => authStore.isAuthenticated)
const currentUser = computed(() => authStore.currentUser)
// 中央头像那个在线点：跟站内其它地方同一个判定口径（60 秒内有心跳算在线）
const isSelfOnline = computed(() => isUserOnline(currentUser.value))

// ==================== 首屏云图板块 ====================
// 5 张小卡 = 固定 3 张随机卡（友情链接 / 随机题目 / 随机讨论，后端每次
// 请求随机抽 3~4 条，不可修改）+ 2 张可修改卡（精选题目 / 置顶讨论）。
// GET /api/home/cloud 解析成内容；未启用 / 拉取失败时首屏回退成普通打卡卡
//（首屏不展示广告，广告配置暂时闲置）。

const cloudEnabled = ref(false)
const cloudCards = ref<any[]>([])

const cloudMode = computed(() => cloudEnabled.value && cloudCards.value.length > 0)
// 云图配置尚未返回期间先按云图布局渲染：否则慢网速下首帧是普通块布局
//（中央卡靠左），接口一回来加 .cloud-full 变成 grid 居中，运势面板会
//「从左边突然蹦到中间」。配置返回后若确实启用，布局类全程不变、零跳变。
const cloudPending = ref(true)

async function loadHomeCloud(): Promise<void> {
  try {
    const data: any = await apiClient.get('/api/home/cloud')
    cloudEnabled.value = !!data?.enabled
    cloudCards.value = Array.isArray(data?.cards) ? data.cards : []
  } catch {
    cloudEnabled.value = false
    cloudCards.value = []
  } finally {
    cloudPending.value = false
  }
  // 卡片就位 → 摆随机椭圆初值 → 实测避让布局 → 放行入场动画
  buildCloudNodes()
  await nextTick()
  layoutCloud()
  await nextTick()
  cloudReady.value = true
  observeCloud()
  // 字体 / 图片晚到会改变小卡高度，稍后再校一次位
  if (cloudSettleTimer) window.clearTimeout(cloudSettleTimer)
  cloudSettleTimer = window.setTimeout(() => layoutCloud(), 600)
}

// ===== 椭圆辐射布局：随机抖动 + 实测避让 =====
// 卡片中心先落在自顶点起均匀分布的椭圆上，每次进首页给角度 / 半径加随机抖动
// （分布不那么死板）；渲染后实测中央卡与各小卡的尺寸做松弛迭代——把压到
// 中央运势卡上的小卡沿最小穿透轴推开、小卡两两分开、再收回板块边界，
// 最终位置换算成百分比（SVG 虚线同坐标，卡片盖在线上）。
// 窄屏放不下「中央卡 + 两侧卡」时降级为纵排（.cloud-stack，与 ≤768px 同款）。
type CloudNode = {
  card: any
  x: number // 中心点相对板块的百分比
  y: number
  seedAngle: number // 本次加载的角度抖动（度），resize 时保持稳定
  seedRad: number // 本次加载的半径缩放
  fdur: number // 浮动动画周期
  fdelay: number // 浮动动画起始延迟（错开相位）
}

const cloudSectionEl = ref<HTMLElement | null>(null)
const cloudCenterEl = ref<HTMLElement | null>(null)
const cloudNodeEls = ref<HTMLElement[]>([])
const cloudNodes = ref<CloudNode[]>([])
const cloudReady = ref(false)
const cloudStack = ref(false)
const cloudCenterPt = ref({ x: 50, y: 50 })

let cloudResizeTimer: number | null = null
let cloudSettleTimer: number | null = null

const setCloudNodeEl = (el: unknown, i: number): void => {
  if (el) cloudNodeEls.value[i] = el as HTMLElement
}

// 生成卡片数据：随机化角度 / 半径 / 动画参数，并给一个无测量的初始椭圆位置
function buildCloudNodes(): void {
  const n = cloudCards.value.length
  const stepDeg = 360 / Math.max(n, 1)
  cloudNodes.value = cloudCards.value.map((card, i) => {
    const seedAngle = -90 + stepDeg * i + (Math.random() * 2 - 1) * (stepDeg / 5)
    const seedRad = 0.94 + Math.random() * 0.12
    const a = (seedAngle * Math.PI) / 180
    return {
      card,
      seedAngle,
      seedRad,
      fdur: 5.5 + Math.random() * 3,
      fdelay: Math.random() * 2,
      x: 50 + 36 * seedRad * Math.cos(a),
      y: 50 + 38 * seedRad * Math.sin(a),
    }
  })
}

// 实测避让布局：先按随机椭圆撒点，再搜索 / 松弛出最终位置
function layoutCloud(): void {
  const section = cloudSectionEl.value
  const center = cloudCenterEl.value
  const nodes = cloudNodes.value
  const n = nodes.length
  if (!cloudMode.value || !section || !center || !n) return
  // ≤768px 由 CSS 降级为纵排，绝对定位坐标不参与布局
  if (window.matchMedia('(max-width: 768px)').matches) return

  const W = section.clientWidth
  const H = section.clientHeight
  if (W < 200 || H < 200) return

  // 用 offset* 而不是 getBoundingClientRect：后者含 transform（入场动画的
  // translateY 会把量到的中心点带偏），坐标原点 = 板块 padding 盒（无边框），
  // 与 left: %、SVG inset:0 的解析基准一致
  const ccx = center.offsetLeft + center.offsetWidth / 2
  const ccy = center.offsetTop + center.offsetHeight / 2
  const halfCw = center.offsetWidth / 2
  const halfCh = center.offsetHeight / 2
  cloudCenterPt.value = { x: (ccx / W) * 100, y: (ccy / H) * 100 }

  const GAP = 18 // 小卡与中央卡 / 小卡相互的间距
  const EDGE = 10 // 与板块边缘的留白
  const NODE_W = 236 // 与 CSS .cloud-node 的 width 保持一致
  const CENTER_W = Math.min(440, W) // .cloud-center 是 min(440px, 100%)

  const sizes: { w: number; h: number }[] = []
  for (let i = 0; i < n; i++) {
    const el = cloudNodeEls.value[i]
    if (!el) return // 尚未渲染完，等下一帧
    sizes.push({ w: el.offsetWidth, h: el.offsetHeight })
  }

  // 横向放不下「中央卡 + 两侧卡」→ 降级纵排。
  // 条件只跟 W 有关（不依赖实测尺寸）：一旦切成纵排，实测宽度全变了，
  // 用实测值判断会在「纵排 ↔ 辐射」之间来回抖
  cloudStack.value = W < CENTER_W + 2 * NODE_W + 2 * (GAP + EDGE)
  if (cloudStack.value) return

  const hitCenter = (i: number, x: number, y: number): boolean => {
    const hw = sizes[i].w / 2 + GAP
    const hh = sizes[i].h / 2 + GAP
    return Math.abs(x - ccx) < halfCw + hw && Math.abs(y - ccy) < halfCh + hh
  }

  // 1) 初始点：随机椭圆撒点。顶 / 底方向的卡在竖直方向永远让不开中央卡，
  //    所以沿椭圆朝最近的方向拨角度，直到躲开中央卡（宽屏下横向一定躲得开）
  const offs: number[] = [0]
  for (let d = 5; d <= 180; d += 5) offs.push(d, -d)
  const pts: { x: number; y: number }[] = []
  for (let i = 0; i < n; i++) {
    const hw = sizes[i].w / 2
    const hh = sizes[i].h / 2
    const Rx = W / 2 - hw - EDGE // 横向不缩：躲开中央卡靠它
    const Ry = (H / 2 - hh - EDGE) * nodes[i].seedRad // 纵向带随机缩放，分布不齐
    let best: { x: number; y: number; pen: number } | null = null
    for (const off of offs) {
      const a = ((nodes[i].seedAngle + off) * Math.PI) / 180
      const x = Math.min(Math.max(ccx + Rx * Math.cos(a), hw + EDGE), W - hw - EDGE)
      const y = Math.min(Math.max(ccy + Ry * Math.sin(a), hh + EDGE), H - hh - EDGE)
      const pen =
        Math.max(halfCw + hw + GAP - Math.abs(x - ccx), 0) +
        Math.max(halfCh + hh + GAP - Math.abs(y - ccy), 0)
      if (!hitCenter(i, x, y)) {
        best = { x, y, pen: 0 }
        break // 已躲开中央卡
      }
      if (!best || pen < best.pen) best = { x, y, pen } // 兜底：留重叠最浅的那个
    }
    pts.push(best ? { x: best.x, y: best.y } : { x: ccx, y: ccy })
  }

  // 中央卡避让：沿穿透更浅的轴推开（节点已在卡内时必然两轴都穿透）
  const pushFromCenter = (i: number): void => {
    const p = pts[i]
    const hw = sizes[i].w / 2 + GAP
    const hh = sizes[i].h / 2 + GAP
    const dx = p.x - ccx
    const dy = p.y - ccy
    const penX = halfCw + hw - Math.abs(dx)
    const penY = halfCh + hh - Math.abs(dy)
    if (penX <= 0 || penY <= 0) return
    if (penX <= penY) {
      p.x = ccx + (dx < 0 ? -1 : 1) * (halfCw + hw)
    } else {
      p.y = ccy + (dy < 0 ? -1 : 1) * (halfCh + hh)
    }
  }

  // 小卡两两分离（最小穿透轴各让一半）
  const separate = (i: number, j: number): void => {
    const a = pts[i]
    const b = pts[j]
    const limX = (sizes[i].w + sizes[j].w) / 2 + GAP
    const limY = (sizes[i].h + sizes[j].h) / 2 + GAP
    const dx = b.x - a.x
    const dy = b.y - a.y
    const penX = limX - Math.abs(dx)
    const penY = limY - Math.abs(dy)
    if (penX <= 0 || penY <= 0) return
    if (penX <= penY) {
      const s = (dx < 0 ? -1 : 1) * (penX / 2)
      a.x -= s
      b.x += s
    } else {
      const s = (dy < 0 ? -1 : 1) * (penY / 2)
      a.y -= s
      b.y += s
    }
  }

  const clampPt = (i: number): void => {
    const p = pts[i]
    const hw = sizes[i].w / 2 + EDGE
    const hh = sizes[i].h / 2 + EDGE
    p.x = Math.min(Math.max(p.x, hw), W - hw)
    p.y = Math.min(Math.max(p.y, hh), H - hh)
  }

  // 2) 松弛迭代：先两两分开、再避让中央卡（硬约束放后面优先）、最后收回边界
  for (let iter = 0; iter < 60; iter++) {
    for (let i = 0; i < n; i++)
      for (let j = i + 1; j < n; j++) separate(i, j)
    for (let i = 0; i < n; i++) pushFromCenter(i)
    for (let i = 0; i < n; i++) clampPt(i)
  }
  // 收尾再让一次中央卡，确保运势面板绝不被压住
  for (let i = 0; i < n; i++) pushFromCenter(i)
  for (let i = 0; i < n; i++) clampPt(i)

  // 3) 写回百分比
  cloudNodes.value = nodes.map((nd, i) => ({
    ...nd,
    x: (pts[i].x / W) * 100,
    y: (pts[i].y / H) * 100,
  }))
}

const onCloudResize = (): void => {
  if (cloudResizeTimer) window.clearTimeout(cloudResizeTimer)
  cloudResizeTimer = window.setTimeout(() => layoutCloud(), 150)
}

// 中央卡 / 板块尺寸变化（打卡、运势展开、字体图片晚到）→ 防抖重排
let cloudRO: ResizeObserver | null = null
function observeCloud(): void {
  if (typeof ResizeObserver === 'undefined') return
  cloudRO?.disconnect()
  const ro = new ResizeObserver(() => {
    if (cloudResizeTimer) window.clearTimeout(cloudResizeTimer)
    cloudResizeTimer = window.setTimeout(() => layoutCloud(), 120)
  })
  if (cloudSectionEl.value) ro.observe(cloudSectionEl.value)
  if (cloudCenterEl.value) ro.observe(cloudCenterEl.value)
  cloudRO = ro
}

const CLOUD_TYPE_ICON: Record<string, string> = {
  posts: 'fa-solid fa-message',
  problems: 'fa-solid fa-code',
  friend_links: 'fa-solid fa-link',
}

// 难度徽标（云图题目小卡用的简化配色）
const difficultyClass = (d: string) => {
  if (['入门', '普及-', '普及'].includes(d)) return 'diff-easy'
  // 旧档位名「普及+/提高」一并保留：滚动发布窗口期（新前端已上线、存量数据
  // 迁移未执行）DB 仍可能返回旧串，缺了它会落进兜底分支被渲染成 diff-hard
  if (['普及+/提高-', '普及+/提高', '提高', '提高+/省选-'].includes(d)) return 'diff-mid'
  return 'diff-hard'
}

// 中央卡头像：登录用本人头像，游客用站点 logo
const centerAvatar = computed(() => {
  if (currentUser.value) {
    return currentUser.value.avatar_url || letterAvatar(currentUser.value.username || 'U')
  }
  return '/favicon.svg'
})

// ==================== 通用工具 ====================

const COLOR_RED = 'var(--primary)'
const COLOR_PURPLE = '#9C3DCF'
const COLOR_BROWN = '#AD8B00'

// 获取用户显示颜色
const getUserDisplayColor = (user: any) => userNameColor(user)


// 生成字母头像
const letterAvatar = (name: string) => {
  const ch = (name || 'U').trim().charAt(0).toUpperCase() || 'U'
  return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Crect width='40' height='40' fill='%23e74c3c'/%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' dy='.3em' fill='white' font-size='16' font-family='Arial'%3E${encodeURIComponent(ch)}%3C/text%3E%3C/svg%3E`
}

const getUserAvatar = (item: any) => {
  return item.avatar_url || letterAvatar(item.username)
}

// 富文本渲染（Markdown + LaTeX 公式）
import { renderRichText as renderMarkdown } from '@/utils/markdown'

// ==================== 打卡（服务端存储，跨设备一致） ====================

// 打卡状态来自后端（users 表），换设备 / 重装 / 清缓存不丢失
const checkinState = ref({ today_checked: false, streak: 0, total: 0 })

const loadCheckin = async () => {
  if (!isLoggedIn.value) return
  try {
    checkinState.value = await apiClient.get('/api/checkin')
  } catch {
    // 静默失败：保持当前状态，不影响页面其余模块
  }
}

// 随机种子（splitmix32）
function splitmix32(seed: number) {
  seed = seed >>> 0
  return function () {
    seed = (seed + 0x9E3779B9) >>> 0
    let z = seed
    z = ((z ^ (z >>> 16)) * 0x85EBCA6B) >>> 0
    z = ((z ^ (z >>> 13)) * 0xC2B2AE35) >>> 0
    z = (z ^ (z >>> 16)) >>> 0
    return (z >>> 0) / 4294967296
  }
}

function getDailySeed(userId: string) {
  const today = getTodayDateStr()
  const base = String(userId || 'anonymous')
  const salt = '✨NLNOJ🏮'
  const combined = base + today + salt
  let hash = 5381
  for (let i = 0; i < combined.length; i++) {
    hash = ((hash << 5) + hash) + combined.charCodeAt(i)
    hash |= 0
  }
  const dateNum = parseInt(today.replace(/-/g, ''))
  hash = ((hash >>> 0) ^ dateNum * 2654435761) >>> 0
  return Math.abs(hash) >>> 0
}

// 日期工具（时区为东八区）
function getTodayDateStr() {
  const now = new Date()
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).format(now)
}

const getChineseWeekday = (date: Date) => {
  const weekdays = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六']
  return weekdays[date.getDay()]
}

const getMonthSize = (date: Date) => {
  const year = date.getFullYear()
  const month = date.getMonth()
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  return daysInMonth >= 30 ? '大' : '小'
}

const getMonthChinese = (date: Date) => {
  const months = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十', '十一', '十二']
  return months[date.getMonth()] + '月'
}

const daysUntil = (targetDate: Date) => {
  const now = new Date()
  now.setHours(0, 0, 0, 0)
  const target = new Date(targetDate)
  target.setHours(0, 0, 0, 0)
  const diff = target.getTime() - now.getTime()
  return Math.ceil(diff / (1000 * 60 * 60 * 24))
}

// 当前时间（每分钟刷新一次，保证跨天正确）
const now = ref(new Date())
let clockTimer: number | null = null

const dayStr = computed(() => String(now.value.getDate()).padStart(2, '0'))
const weekday = computed(() => getChineseWeekday(now.value))
const monthChineseFull = computed(() => getMonthChinese(now.value) + getMonthSize(now.value))
const cspDays1 = computed(() => daysUntil(new Date(2026, 8, 19)))
const cspDays2 = computed(() => daysUntil(new Date(2026, 9, 30)))

// 倒计时文案：当天显示「就是今天」，过期显示「已结束」
const cspCountdownLabel = (days: number) => {
  if (days === 0) return '就是今天！'
  if (days < 0) return '已结束'
  return `还剩 ${days} 天`
}
const cspLabel1 = computed(() => cspCountdownLabel(cspDays1.value))
const cspLabel2 = computed(() => cspCountdownLabel(cspDays2.value))

// 今日是否已打卡 / 连续打卡天数（均为服务端状态）
const checkedInToday = computed(() => checkinState.value.today_checked)
const streakDays = computed(() => checkinState.value.streak)

// ===== 运势 =====
const ACTIVITIES = [
  { name: '写作文', good: '非常有文采', bad: '不知所云，离题千里' },
  { name: '写洛谷日报', good: '文思泉涌，下笔如有神', bad: '发现还差得远' },
  { name: '放假', good: '自由自在的一个假期', bad: '就放一天，全是作业' },
  { name: '玩网游', good: '犹如神助', bad: '匹配到一群猪队友' },
  { name: '考试', good: '学的全会，蒙的全对', bad: '作弊会被抓' },
  { name: '背诵课文', good: '看一遍就背下来了', bad: '记忆力只有 50 Byte' },
  { name: '交友', good: '友谊地久天长', bad: '交友不慎' },
  { name: '骗分', good: '"不可以，总司令"然后拿一半分', bad: '一分不得' },
  { name: '抽卡', good: '一发入魂', bad: '只有保底' },
  { name: '贴贴', good: '说不定擦出火花', bad: '一定会被拒绝' },
  { name: '出公开赛', good: 'rated，评价很高', bad: '出了原题裸题错题不可做题' },
  { name: '开电脑', good: '电脑的状态也很好', bad: '意外的死机故障不可避' },
  { name: '祭祀', good: '获得祖宗的庇护', bad: '未能得到祖宗保佑' },
  { name: '体育锻炼', good: '身体棒棒哒', bad: '消耗的能量全吃回来了' },
  { name: '网购', good: '买到历史最低价', bad: '正好错过促销' },
  { name: '摸鱼', good: '放松身心', bad: '被教练制裁' },
  { name: '请教问题', good: '获得大佬的解答', bad: '被当作 xxs' },
  { name: '抢最优解', good: '一发就是最优解', bad: '越卡常越慢' },
  { name: '洗澡', good: '洗香香', bad: '小心着凉' },
  { name: '唱歌', good: '成为歌神', bad: '别人唱歌要钱，你要命' },
  { name: '玩我的世界', good: '下界挖到远古遗骸', bad: '转角遇到苦力怕' },
  { name: '熬夜', good: '事情终究可以完成的', bad: '爆肝，通宵干不完' },
  { name: '写暴戾语言', good: '成功发泄', bad: '禁赛一年' },
  { name: '卷题', good: '水平显著提升', bad: '我咋啥都不会' },
  { name: '上洛谷', good: '全方位提升', bad: '你谷日爆' },
  { name: '出行', good: '一路顺风', bad: '路途也许坎坷' },
  { name: '点外卖', good: '及时送到', bad: '一直没有送到还不给退款' },
  { name: '写题解', good: '一遍通过审核', bad: '连续提交不符合要求' },
  { name: '学新算法', good: '看一遍就懂了', bad: '怎么也学不会' },
  { name: '重构代码', good: '代码质量明显提高', bad: '越改越乱' },
  { name: '继续完成 WA 的题', good: '下一次就 AC', bad: '然而变成了 TLE' },
  { name: '打线上公开赛', good: '涨很多 rating', bad: '掉大分' },
  { name: '参加模拟赛', good: '可以 AK 虐全场', bad: '注意爆零' },
  { name: '水讨论区', good: '看到有趣的事情', bad: '和其他人激情对线' },
  { name: '写作业', good: '都会写，写的全对', bad: '上课讲了这些了吗' },
  { name: '装弱', good: '谦虚最好了', bad: '被看穿' },
  { name: '看视频网站', good: '愉悦身心', bad: '会被教练看见' },
  { name: '刷题', good: '成为虐题狂魔', bad: '容易 WA' },
  { name: '装逼', good: '获得众人敬仰', bad: '被识破' },
  { name: '睡觉', good: '养足精力，明日再战', bad: '翻来覆去睡不着' },
  { name: '切水题', good: '通过数猛涨', bad: '被抓抄题解' },
  { name: '膜拜大神', good: '接受神犇光环照耀', bad: '被大神鄙视' },
  { name: '吃饭', good: '人是铁饭是钢', bad: '小心变胖啊' },
  { name: '上厕所', good: '想出了题目的解法', bad: '被机房惨案' },
  { name: '打东方', good: 'All clear！', bad: '满身疮痍' },
  { name: '造数据', good: '严谨数据，经久耐用', bad: '数据出锅，当众谢罪' },
  { name: '纳财', good: '要到好多 Money', bad: '然而今天并没有财运' },
  { name: '去食堂', good: '给了双倍的量', bad: '爱吃的菜刚被打完' },
  { name: '上课', good: '100% 消化', bad: '反正你听不懂' },
  { name: '发朋友圈', good: '分享是种美德', bad: '会被当做卖面膜的' },
  { name: '扶老奶奶过马路', good: '增加 RP', bad: '会被讹' },
  { name: '水工单', good: '与他人友好交流', bad: '这工单是人吗' },
  { name: '发工单', good: '被成功采纳', bad: '喜提禁言' },
  { name: '举报', good: '被举报的人遭受正义制裁', bad: '被管理驳回' },
  { name: '看电视', good: '有你最喜欢的节目', bad: '电视瘫痪' },
  { name: '猜猜犇', good: '都认识', bad: '都不认识' },
  { name: '打牌', good: '一手好牌，大获全胜', bad: '一手烂牌，一败涂地' },
  { name: '看医生', good: '医生治好了你的病', bad: '医生也看不出来你哪里有病' },
  { name: '上NLNOJ', good: '题目多多，做题愉快', bad: '评测机又双叒叕炸了' }
]

const FORTUNE_LEVELS = [
  { label: '大吉', cls: 'good' },
  { label: '中吉', cls: 'good' },
  { label: '小吉', cls: 'good' },
  { label: '中平', cls: 'bad' },
  { label: '凶', cls: 'terrible' },
  { label: '大凶', cls: 'terrible' }
]

// 特殊日运势：全员固定（键为 YYYY-MM-DD，当日人人一样）
// 2026-09-19：CSP-J/S 第一轮认证，全员大吉，宜 CSP RP++
const SPECIAL_FORTUNES: Record<string, { goodItems: { name: string; desc: string }[] }> = {
  '2026-09-19': { goodItems: [{ name: 'CSP', desc: 'RP++' }] }
}

// 计算今日运势（纯前端种子算法：同人同日恒定，无需持久化）
const dailyFortune = computed(() => {
  if (!checkedInToday.value || !isLoggedIn.value) return null
  // 特殊日优先：跳过随机，直接按预定的运势展示
  const d = now.value
  const special = SPECIAL_FORTUNES[
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  ]
  if (special) {
    return { label: '大吉', cls: 'good', goodItems: special.goodItems, badItems: [] }
  }
  const userIdSeed = String(currentUser.value?.user_number || '')
  const rand = splitmix32(getDailySeed(userIdSeed))
  const fortuneIdx = Math.floor(rand() * FORTUNE_LEVELS.length)
  const fortune = FORTUNE_LEVELS[fortuneIdx]
  const shuffled = [...ACTIVITIES]
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]]
  }
  const picked = shuffled.slice(0, 4)
  const goodItems = picked.slice(0, 2).map(a => ({ name: a.name, desc: a.good }))
  const badItems = picked.slice(2, 4).map(a => ({ name: a.name, desc: a.bad }))
  return { label: fortune.label, cls: fortune.cls, goodItems, badItems }
})

const fortuneLabel = computed(() => dailyFortune.value?.label || '')
const fortuneClass = computed(() => {
  const cls = dailyFortune.value?.cls
  if (cls === 'good') return 'lg-fg-red'
  if (cls === 'bad') return 'lg-fg-green'
  if (cls === 'terrible') return 'lg-fg-black'
  return 'lg-fg-green'
})
const fortuneColor = computed(() => {
  const cls = dailyFortune.value?.cls
  if (cls === 'good') return '#E74C3C'
  if (cls === 'bad') return '#5EB95E'
  if (cls === 'terrible') return '#000000'
  return '#5EB95E'
})
const fortuneGoodItems = computed(() =>
  dailyFortune.value?.label === '大凶' ? [] : (dailyFortune.value?.goodItems || [])
)
const fortuneBadItems = computed(() =>
  dailyFortune.value?.label === '大吉' ? [] : (dailyFortune.value?.badItems || [])
)

// 点击打卡（服务端幂等：当日重复打卡直接返回现状）
const doPunch = async () => {
  if (!isLoggedIn.value) {
    router.push('/login')
    return
  }
  if (checkinState.value.today_checked) return
  try {
    checkinState.value = await apiClient.post('/api/checkin')
  } catch (error: any) {
    alert('打卡失败：' + (error.response?.data?.detail || error.message || '未知错误'))
  }
}

// 当前用户的展示信息
const meColor = computed(() => getUserDisplayColor(currentUser.value))
const meTag = computed(() => getUserTagDisplay(currentUser.value))

// ==================== 近期讨论 ====================
const recentPosts = ref<any[]>([])
const recentLoading = ref(false)
const friendLinks = ref<any[]>([])
const friendLinksLoading = ref(false)

const loadFriendLinks = async () => {
  friendLinksLoading.value = true
  try {
    const data: any = await apiClient.get('/api/friend-links')
    friendLinks.value = Array.isArray(data?.links) ? data.links : []
  } catch {
    friendLinks.value = []
  } finally {
    friendLinksLoading.value = false
  }
}

const relTime = (iso: string) => {
  if (!iso) return ''
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  if (diff < 172800000) return `${Math.floor(diff / 86400)} 天前`
  return new Date(iso).toLocaleDateString('zh-CN')
}

const loadRecentPosts = async () => {
  recentLoading.value = true
  try {
    const data: any = await apiClient.get('/api/forum/recent?limit=10')
    recentPosts.value = Array.isArray(data) ? data : []
  } catch {
    recentPosts.value = []
  } finally {
    recentLoading.value = false
  }
}

// ==================== 犇犇模块 ====================

const MAX_LENGTH = 454 // 普通用户最大字数限制（原 227 翻倍）

const benbenContent = ref('')
const benbenList = ref<any[]>([])
const feedMode = ref<'all' | 'my'>('all')
const isLoading = ref(false)
const hasMore = ref(true)
const lastId = ref<number | null>(null)
const currentReplyingId = ref<number | null>(null)
const currentReplyUsername = ref<string | null>(null)

// 加载状态文案（对应原站 loadingSentinel）
const sentinelText = ref('')
const sentinelVisible = ref(true)

const benbenTextareaRef = ref<InstanceType<typeof BenbenMarkdownEditor> | null>(null)
const loadingSentinelRef = ref<HTMLElement | null>(null)

// 是否被禁言
const cannotSpeak = computed(() => currentUser.value?.can_speak === false)

// 更新加载指示文案
const updateSentinel = () => {
  // 列表为空时：空状态由 benben-empty 呈现，sentinel 仅在出错时显示错误信息
  if (benbenList.value.length === 0) {
    sentinelVisible.value = sentinelText.value === '加载出错，请刷新'
    return
  }
  if (!hasMore.value) {
    sentinelText.value = '没有更多动态了'
    sentinelVisible.value = true
  } else if (isLoading.value) {
    sentinelText.value = '加载中...'
    sentinelVisible.value = true
  } else {
    sentinelText.value = '点击加载更多'
    sentinelVisible.value = true
  }
}

// 时间格式化（与原站一致的完整时间）
const formatTime = (dateStr: string) => {
  return new Date(dateStr).toLocaleString('zh-CN')
}

// 切换犇犇标签页
const switchTab = (mode: 'all' | 'my') => {
  feedMode.value = mode
  currentReplyingId.value = null
  currentReplyUsername.value = null
  // 换列表了，攒着的新动态提示作废
  pendingBenben.value = []
  loadBenbenList(true)
}

// 发布犇犇（乐观更新：点击后立即上屏，失败回滚）
const posting = ref(false)

const postBenben = async () => {
  const content = benbenContent.value.trim()
  if (!content) {
    alert('内容不能为空')
    return
  }

  if (!currentUser.value) {
    router.push('/login')
    return
  }

  if (cannotSpeak.value) {
    alert('你已被禁言，无法发布犇犇')
    return
  }

  // 校验回复前缀，决定 reply_to
  let finalReplyToId: number | null = null
  let replyToName: string | null = null
  if (currentReplyingId.value && currentReplyUsername.value) {
    const trimmed = content.trimStart()
    const prefix = `|| @${currentReplyUsername.value} :`
    if (trimmed.startsWith(prefix)) {
      finalReplyToId = currentReplyingId.value
      replyToName = currentReplyUsername.value
    } else {
      currentReplyingId.value = null
      currentReplyUsername.value = null
    }
  }

  const finalContent = currentUser.value.is_admin ? content : content.substring(0, MAX_LENGTH)

  posting.value = true

  // 乐观插入的临时对象（服务器返回后替换为正式数据）
  const u = currentUser.value
  const optimisticId = -Date.now()
  const optimistic = {
    id: optimisticId,
    user_number: u.user_number,
    username: u.username,
    avatar_url: u.avatar_url,
    is_admin: u.is_admin,
    is_cheater: u.is_cheater,
    user_tag: u.user_tag,
    content: finalContent,
    reply_to: finalReplyToId,
    reply_to_username: replyToName,
    created_at: new Date().toISOString(),
    // 在线点（UserAvatarStatus）读的是 last_seen：临时项漏了它，
    // 刚发出去的这条会在自己名字旁边显示成「离线」，和其它条目自相矛盾
    last_seen: u.last_seen ?? new Date().toISOString(),
  }
  benbenList.value = [optimistic, ...benbenList.value]

  try {
    const res: any = await apiClient.post('/benben', {
      content: finalContent,
      ...(finalReplyToId ? { reply_to: finalReplyToId } : {})
    })
    // 用服务器返回的正式数据替换乐观项
    const idx = benbenList.value.findIndex(x => x.id === optimisticId)
    if (idx !== -1 && res?.id) benbenList.value.splice(idx, 1, res)
    // 成功后才清空输入框和回复上下文；限流失败时保留以便重发
    benbenContent.value = ''
    currentReplyingId.value = null
    currentReplyUsername.value = null
  } catch (error: any) {
    console.error('发布失败:', error)
    // 回滚乐观项
    const idx = benbenList.value.findIndex(x => x.id === optimisticId)
    if (idx !== -1) benbenList.value.splice(idx, 1)
    const errorMessage = error.response?.data?.detail || error.message || '未知错误'
    alert('发布失败：' + errorMessage)
  } finally {
    posting.value = false
  }
}

// 删除犇犇
const deleteBenben = async (id: number) => {
  try {
    await apiClient.delete(`/benben/${id}`)
    await loadBenbenList(true)
  } catch (error: any) {
    console.error(error)
    alert('删除失败：' + (error.response?.data?.detail || error.message || '未知错误'))
  }
}

// 回复犇犇
const replyToBenben = (item: any) => {
  currentReplyingId.value = item.id
  currentReplyUsername.value = item.username
  const replyText = ` || @${item.username} : ${item.content}`
  benbenContent.value = replyText

  nextTick(() => {
    benbenTextareaRef.value?.setCaretToStart()
  })
}

// 举报犇犇：跳转独立举报页（返回时页面重建会自动刷新列表）
const openReport = (item: any) => {
  router.push(`/report/benben/${item.id}`)
}

// 加载犇犇列表
const loadBenbenList = async (reset = true) => {
  if (isLoading.value) return

  // 未登录用户不加载动态列表
  if (!isLoggedIn.value) {
    isLoading.value = false
    hasMore.value = false
    updateSentinel()
    return
  }

  if (reset) {
    hasMore.value = true
    lastId.value = null
    benbenList.value = []
    sentinelText.value = '加载中...'
    sentinelVisible.value = true
  }

  if (!hasMore.value) {
    updateSentinel()
    return
  }

  isLoading.value = true
  sentinelText.value = '加载中...'
  sentinelVisible.value = true

  try {
    let url = `/benben?limit=20`
    if (lastId.value) url += `&before_id=${lastId.value}`
    if (feedMode.value === 'my') url += '&mode=my'

    // 响应拦截器已解包 response.data
    const data = (await apiClient.get(url)) as any[]

    if (data && data.length > 0) {
      benbenList.value = reset ? data : [...benbenList.value, ...data]
      lastId.value = data[data.length - 1].id

      if (data.length < 20) {
        hasMore.value = false
        sentinelText.value = '没有更多动态了'
      } else {
        hasMore.value = true
        sentinelText.value = '点击加载更多'
      }
    } else {
      hasMore.value = false
      if (reset) benbenList.value = []
      sentinelText.value = '没有更多动态了'
    }
  } catch (error) {
    console.error(error)
    sentinelText.value = '加载出错，请刷新'
  } finally {
    isLoading.value = false
    updateSentinel()
  }
}

// ==================== 犇犇自动刷新 ====================
// 不做「定时全量重拉」，而是拿列表里最新一条的 id 做 after_id 增量拉，
// 没新动态时后端只返回空数组（一个索引区间查询），所以可以刷得勤一点。
// 成本：5 秒一轮 ≈ 单用户每分钟 12 次请求，页面隐藏时直接跳过不刷。
const REFRESH_INTERVAL = 5000

const pendingBenben = ref<any[]>([])
const flashIds = ref<Set<number>>(new Set())
const benbenListRef = ref<HTMLElement | null>(null)
let refreshTimer: number | undefined
let flashTimer: number | undefined

// 最新一条「真实」犇犇的 id（乐观插入的临时项 id 是负数，必须排除）
const newestRealId = computed(() => {
  let max = 0
  for (const item of benbenList.value) {
    if (typeof item.id === 'number' && item.id > max) max = item.id
  }
  return max
})

// 是否直接插入列表最前面。
// 只有「用户已经滚进列表内部、正在看旧帖子」时才改用浮动提示 —— 那种情况下
// 插入新内容会把正在读的帖子顶下去。列表还在视野下方（没滚到）或者页面顶部时
// 插入根本看不出变化，直接插就行。
const shouldInsertInline = () => {
  const el = benbenListRef.value
  if (!el) return true
  return el.getBoundingClientRect().top > -24
}

// 插到列表最前面，并短暂高亮
const prependBenben = (items: any[]) => {
  const known = new Set(benbenList.value.map((x) => x.id))
  const fresh = items.filter((x) => !known.has(x.id))
  pendingBenben.value = []
  if (fresh.length === 0) return

  benbenList.value = [...fresh, ...benbenList.value]
  flashIds.value = new Set(fresh.map((x) => x.id))
  clearTimeout(flashTimer)
  flashTimer = setTimeout(() => {
    flashIds.value = new Set()
  }, 2600)
}

/**
 * 核对列表里的犇犇是否还在，把被删掉的摘掉。
 *
 * 增量刷新只按 after_id 拉「新的」，所以别人删掉一条之后前端根本收不到任何信号，
 * 那条就一直挂在页面上，非得手动刷新才消失。
 * 这里每个周期再问一次后端「这些 id 还有几条活着」，只回 id，代价很小。
 * 乐观插入的临时项 id 是负数，永远保留（它还等着服务端返回真 id）。
 */
const dropDeletedBenben = async () => {
  const ids = [...benbenList.value, ...pendingBenben.value]
    .map((x) => x.id)
    .filter((id) => typeof id === 'number' && id > 0)
  if (ids.length === 0) return

  const data = (await apiClient.get(`/benben/existing?ids=${ids.join(',')}`)) as any
  const alive = new Set<number>(Array.isArray(data?.ids) ? data.ids : [])
  const keep = (x: any) => typeof x.id !== 'number' || x.id < 0 || alive.has(x.id)

  benbenList.value = benbenList.value.filter(keep)
  pendingBenben.value = pendingBenben.value.filter(keep)
}

const refreshBenben = async () => {
  if (document.hidden || isLoading.value || posting.value || !isLoggedIn.value) return
  const topId = newestRealId.value

  try {
    // 列表空的时候没有 after_id 可用（用了就永远拉不到东西），退化成拉最新一页。
    // 删空 / 本来就一条都没有时全靠这条兜底，否则自动刷新会就此停摆。
    let url = topId ? `/benben?limit=50&after_id=${topId}` : '/benben?limit=50'
    if (feedMode.value === 'my') url += '&mode=my'

    const data = (await apiClient.get(url)) as any[]
    const fresh = data ?? []

    // 先摘掉被删的，再插入新的，免得刚插进来的又被误判
    await dropDeletedBenben()

    if (fresh.length === 0) {
      pendingBenben.value = []
      return
    }

    if (shouldInsertInline()) {
      prependBenben(fresh)
    } else {
      // 用户正在下边看别的，先攒着。after_id 固定不变，所以每次拉到的
      // 都是「比当前已显示的最新一条还新」的全集，直接覆盖即可。
      pendingBenben.value = fresh
    }
  } catch (error) {
    // 自动刷新失败不打扰用户，静默跳过，下个周期再试
    console.error('犇犇自动刷新失败:', error)
  }
}

// 点「N 条新动态」：插入并滚到列表顶部
const showPendingBenben = () => {
  prependBenben(pendingBenben.value)
  const el = benbenListRef.value
  if (!el) return
  // 减掉吸顶导航栏的高度，别把第一条又藏在它后面
  const y = el.getBoundingClientRect().top + window.pageYOffset - 76
  window.scrollTo({ top: Math.max(0, y), behavior: 'smooth' })
}

// 切回标签页时立刻刷一次 —— 这往往正是用户想要的时机
const handleVisibility = () => {
  if (!document.hidden) void refreshBenben()
}

// 回到顶部
const showBackTop = ref(false)

const handleScroll = () => {
  showBackTop.value = window.pageYOffset > 300
}
const backToTop = () => {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

// ==================== 推荐训练题单 ====================
const featuredTrainingLists = ref<TrainingListItem[]>([])
const featuredTrainingLoading = ref(false)

const loadFeaturedTraining = async () => {
  featuredTrainingLoading.value = true
  try {
    const res = await trainingsApi.list({ featured_only: true, page: 1, page_size: 6 })
    featuredTrainingLists.value = res.items
  } catch (e) {
    console.error('Failed to load featured training lists:', e)
  } finally {
    featuredTrainingLoading.value = false
  }
}

// 生命周期
onMounted(async () => {
  window.addEventListener('scroll', handleScroll, { passive: true })
  window.addEventListener('resize', onCloudResize)
  let lastDayStr = getTodayDateStr()
  clockTimer = window.setInterval(() => {
    now.value = new Date()
    // 跨天：重新拉取打卡状态（零点后未打卡状态要立即恢复可打卡）
    const today = getTodayDateStr()
    if (today !== lastDayStr) {
      lastDayStr = today
      loadCheckin()
    }
  }, 60000)
  loadRecentPosts()
  void loadFriendLinks()
  loadCheckin()
  void loadFeaturedTraining()
  void loadHomeCloud()

  if (isLoggedIn.value) {
    await loadBenbenList(true)

    // 犇犇自动刷新（切回标签页也会立刻刷一次）
    refreshTimer = window.setInterval(() => {
      // 后台标签页不刷：没人看的时候不必打源站（犇犇面板/顶栏角标都是这个口径）
      if (document.visibilityState !== 'visible') return
      void refreshBenben()
    }, REFRESH_INTERVAL)
    document.addEventListener('visibilitychange', handleVisibility)
  } else {
    updateSentinel()
  }
})

onUnmounted(() => {
  window.removeEventListener('scroll', handleScroll)
  window.removeEventListener('resize', onCloudResize)
  if (cloudResizeTimer) window.clearTimeout(cloudResizeTimer)
  if (cloudSettleTimer) window.clearTimeout(cloudSettleTimer)
  cloudRO?.disconnect()
  if (clockTimer) clearInterval(clockTimer)
  if (refreshTimer) clearInterval(refreshTimer)
  clearTimeout(flashTimer)
  document.removeEventListener('visibilitychange', handleVisibility)
})
</script>

<template>
  <div class="home-page">
    <div class="home-container">
      <!-- ===== 首屏：云图板块（站点管理配置了栏目才辐射展开；否则为普通打卡卡，均不展示广告） ===== -->
      <section
        ref="cloudSectionEl"
        class="cloud-section"
        :class="{ 'cloud-full': cloudPending || cloudMode, 'cloud-stack': cloudStack, 'cloud-ready': cloudReady }"
      >
        <!-- 中心 → 各小卡的细虚线（viewBox 用百分比坐标，卡片自身盖在线上） -->
        <svg
          v-if="cloudMode"
          class="cloud-lines"
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <line
            v-for="(node, i) in cloudNodes"
            :key="i"
            :x1="cloudCenterPt.x"
            :y1="cloudCenterPt.y"
            :x2="node.x"
            :y2="node.y"
            :style="{ '--i': String(i) }"
          />
        </svg>

        <!-- 中央：头像 + 打卡 / 运势 -->
        <div ref="cloudCenterEl" class="card cloud-center">
          <div class="cloud-avatar-wrap">
            <img
              class="cloud-avatar"
              :src="centerAvatar"
              alt=""
              @error="($event.target as HTMLImageElement).src = letterAvatar(currentUser?.username || 'NLNOJ')"
            >
            <!-- 在线点按真实 last_seen 走：原来写死 title="在线"，
                 自己掉线时这里还是绿的，和犇犇列表里的红点自相矛盾 -->
            <span
              v-if="isLoggedIn"
              class="cloud-avatar-status"
              :class="{ online: isSelfOnline }"
              :title="isSelfOnline ? '在线' : '离线'"
            ></span>
          </div>

          <!-- 打卡/运势面板 -->
          <div class="fortune-col">
            <template v-if="!checkedInToday">
              <p v-if="isLoggedIn" class="welcome-line">
                欢迎回来，<router-link
                  :to="`/user/${currentUser?.user_number}`"
                  class="benben-username"
                  :style="{ color: meColor }"
                >{{ currentUser?.username }}</router-link><span
                  v-if="meTag"
                  class="user-tag-display"
                  :style="{ backgroundColor: meColor }"
                >{{ meTag }}</span>
              </p>

              <div class="lg-index-calendar">
                <div class="lg-punch-left">
                  <span v-for="(ch, i) in monthChineseFull.split('')" :key="'m' + i">{{ ch }}</span>
                </div>
                <span class="lg-punch-big">{{ dayStr }}</span>
                <div class="lg-punch-right">
                  <span v-for="(ch, i) in weekday.split('')" :key="'w' + i">{{ ch }}</span>
                </div>
              </div>

              <div class="lg-small">
                距 <strong>CSP-J/S 2026 第一轮</strong> <strong>{{ cspLabel1 }}</strong><br>
                距 <strong>CSP-J/S 2026 第二轮</strong> <strong>{{ cspLabel2 }}</strong><br>
                <button v-if="isLoggedIn" class="am-btn am-btn-warning" @click.stop="doPunch">点击打卡</button>
              </div>
            </template>

            <template v-else>
              <h2 class="fortune-title">
                <router-link
                  :to="`/user/${currentUser?.user_number}`"
                  class="benben-username"
                  :style="{ color: meColor }"
                >{{ currentUser?.username }}</router-link><span
                  v-if="meTag"
                  class="user-tag-display"
                  :style="{ backgroundColor: meColor }"
                >{{ meTag }}</span> <span class="fortune-title-suffix">的运势</span>
              </h2>

              <div class="fortune-result-wrap">
                <span class="lg-punch-result" :class="fortuneClass" :style="{ color: fortuneColor }">§ {{ fortuneLabel }} §</span>
              </div>

              <!-- 大吉：万事皆宜 -->
              <div v-if="fortuneLabel === '大吉'" class="fortune-grid">
                <div class="fortune-col-item">
                  <div v-for="item in fortuneGoodItems" :key="item.name" class="fortune-entry">
                    <span class="lg-bold fortune-good-label">宜：{{ item.name }}</span><br>
                    <span class="lg-small fortune-desc">{{ item.desc }}</span>
                  </div>
                </div>
                <div class="fortune-col-item">
                  <span class="lg-bold fortune-nothing">万事皆宜</span>
                </div>
              </div>

              <!-- 大凶：诸事不宜 -->
              <div v-else-if="fortuneLabel === '大凶'" class="fortune-grid">
                <div class="fortune-col-item">
                  <span class="lg-bold fortune-nothing-red">诸事不宜</span>
                </div>
                <div class="fortune-col-item">
                  <div v-for="item in fortuneBadItems" :key="item.name" class="fortune-entry">
                    <span class="lg-bold fortune-bad-strong">忌：</span>
                    <span class="fortune-bad-name">{{ item.name }}</span><br>
                    <span class="lg-small fortune-desc">{{ item.desc }}</span>
                  </div>
                </div>
              </div>

              <!-- 其他：宜忌并排 -->
              <div v-else class="fortune-grid">
                <div class="fortune-col-item">
                  <div v-for="item in fortuneGoodItems" :key="item.name" class="fortune-entry">
                    <span class="lg-bold fortune-good-label">宜：{{ item.name }}</span><br>
                    <span class="lg-small fortune-desc">{{ item.desc }}</span>
                  </div>
                </div>
                <div class="fortune-col-item">
                  <div v-for="item in fortuneBadItems" :key="item.name" class="fortune-entry">
                    <span class="lg-bold fortune-bad-name">忌：{{ item.name }}</span><br>
                    <span class="lg-small fortune-desc">{{ item.desc }}</span>
                  </div>
                </div>
              </div>

              <div class="lg-small fortune-days">
                你已经在 <span class="brand-highlight"> NLNOJ </span> 连续打卡了 <strong>{{ streakDays }}</strong> 天
              </div>
            </template>
          </div>
        </div>

        <!-- 四周辐射小卡：指定帖子 / 推荐题目 / 友链 -->
        <template v-if="cloudMode">
          <article
            v-for="(node, i) in cloudNodes"
            :key="i"
            :ref="(el) => setCloudNodeEl(el, i)"
            class="card cloud-node"
            :class="`node-${node.card.type}`"
            :style="{
              left: node.x + '%',
              top: node.y + '%',
              '--i': String(i),
              '--fdur': node.fdur + 's',
              '--fdelay': node.fdelay + 's',
            }"
          >
            <header class="cloud-node-head">
              <i :class="CLOUD_TYPE_ICON[node.card.type]"></i>
              <span>{{ node.card.title }}</span>
            </header>

            <!-- 指定帖子：标题一行 + 作者 · 版块一行 -->
            <div v-if="node.card.type === 'posts'" class="cloud-node-list">
              <a
                v-for="p in node.card.items"
                :key="p.id"
                class="cloud-line-row"
                :href="`/discuss/${p.id}`"
                @click.prevent="$router.push(`/discuss/${p.id}`)"
              >
                <span class="cloud-line-title">{{ p.title }}</span>
                <span class="cloud-line-sub">{{ p.author?.username }} · {{ p.forum_name }}</span>
              </a>
            </div>

            <!-- 推荐题目：题号 + 标题 + 难度徽标 -->
            <div v-else-if="node.card.type === 'problems'" class="cloud-node-list">
              <a
                v-for="p in node.card.items"
                :key="p.id"
                class="cloud-line-row"
                :href="`/problems/${p.id}`"
                @click.prevent="$router.push(`/problems/${p.id}`)"
              >
                <span class="cloud-line-title">
                  <code class="cloud-pno">{{ p.problem_number }}</code> {{ p.title }}
                </span>
                <span class="cloud-line-sub">
                  <span class="cloud-diff" :class="difficultyClass(p.difficulty)">{{ p.difficulty }}</span>
                </span>
              </a>
            </div>

            <!-- 友链小卡：图标 + 名称的迷你网格 -->
            <div v-else class="cloud-friend-grid">
              <a
                v-for="fl in node.card.items"
                :key="fl.id"
                class="cloud-friend"
                :href="fl.url"
                target="_blank"
                rel="noopener noreferrer"
                :title="fl.title"
              >
                <img :src="fl.icon" :alt="fl.title" loading="lazy" @error="($event.target as HTMLImageElement).style.display='none'">
                <span>{{ fl.title }}</span>
              </a>
            </div>
          </article>
        </template>
      </section>

      <!-- ===== 友情链接：一排小胶囊（横条，不占大篇幅） ===== -->
      <div class="card strip-card friend-links-strip">
        <div class="strip-head">
          <span class="strip-title"><i class="fa-solid fa-link"></i> 友情链接</span>
          <span v-if="!friendLinksLoading && friendLinks.length" class="strip-count">{{ friendLinks.length }}</span>
        </div>
        <div v-if="friendLinksLoading" class="empty-state">加载中...</div>
        <div v-else-if="friendLinks.length === 0" class="empty-state">暂无友情链接</div>
        <div v-else class="friend-pill-row">
          <a
            v-for="link in friendLinks"
            :key="link.id"
            class="friend-pill"
            :href="link.url"
            target="_blank"
            rel="noopener noreferrer"
            :title="link.title"
          >
            <img :src="link.icon" :alt="link.title" loading="lazy" @error="($event.target as HTMLImageElement).style.display='none'">
            <span>{{ link.title }}</span>
          </a>
        </div>
      </div>

      <!-- ===== 近期讨论：标题 + 作者压成一行的细横条 ===== -->
      <div class="card strip-card recent-posts-card">
        <div class="strip-head">
          <span class="strip-title"><i class="fa-solid fa-comments"></i> 近期讨论</span>
          <router-link to="/discuss" class="more-link">
            全部讨论 <i class="fa-solid fa-angle-right"></i>
          </router-link>
        </div>
        <div v-if="recentLoading" class="empty-state">加载中...</div>
        <div v-else-if="recentPosts.length === 0" class="empty-state">没有更多讨论了</div>
        <div v-else class="strip-rows">
          <a
            v-for="p in recentPosts"
            :key="p.id"
            class="strip-row"
            :href="`/discuss/${p.id}`"
            @click.prevent="$router.push(`/discuss/${p.id}`)"
          >
            <span v-if="p.is_pinned" class="pin-badge">置顶</span>
            <span class="strip-row-title">{{ p.title }}</span>
            <span class="strip-row-meta">
              <router-link
                :to="p.author?.user_number ? `/user/${p.author.user_number}` : '#'"
                class="benben-username strip-row-author"
                :style="{ color: getUserDisplayColor(p.author) }"
                @click.stop
              >{{ p.author?.username }}</router-link>
              <span class="strip-row-dot">·</span>
              <span>{{ p.forum_name }}</span>
              <span class="strip-row-dot">·</span>
              <span>{{ relTime(p.created_at) }} {{ p.reply_count }}回复</span>
            </span>
          </a>
        </div>
      </div>

      <!-- ===== 训练题单：标题 + 数量一行 ===== -->
      <div class="card strip-card home-training-section">
        <div class="strip-head">
          <span class="strip-title"><i class="fa-solid fa-clipboard-list"></i> 训练题单</span>
          <router-link to="/training" class="more-link">
            全部题单 <i class="fa-solid fa-angle-right"></i>
          </router-link>
        </div>

        <div v-if="featuredTrainingLoading" class="empty-state">加载中...</div>
        <div v-else-if="featuredTrainingLists.length === 0" class="empty-state">
          暂无推荐题单
        </div>
        <div v-else class="strip-rows">
          <a
            v-for="item in featuredTrainingLists"
            :key="item.id"
            class="strip-row"
            :href="`/training/${item.id}`"
            @click.prevent="router.push(`/training/${item.id}`)"
          >
            <span class="badge-featured-sm"><i class="fa-solid fa-star"></i> 精选</span>
            <span class="strip-row-title">{{ item.title }}</span>
            <span class="strip-row-meta">
              <span>{{ item.problem_count }} 题</span>
              <template v-if="item.owner">
                <span class="strip-row-dot">·</span>
                <span>{{ item.owner.username }}</span>
              </template>
              <template v-if="item.problem_count > 0 && isLoggedIn">
                <span class="strip-row-dot">·</span>
                <span>{{ item.solved_count }}/{{ item.problem_count }}</span>
              </template>
            </span>
          </a>
        </div>
      </div>

      <!-- ===== 犇犇模块（学术模式下隐藏） ===== -->
      <div v-if="isLoggedIn && !academicMode" class="card benben-module">
        <div class="benben-header">有什么新鲜事告诉大家</div>

        <div class="benben-editor">
          <BenbenMarkdownEditor
            ref="benbenTextareaRef"
            v-model="benbenContent"
            :rows="3"
            :maxlength="currentUser?.is_admin ? 10000 : MAX_LENGTH"
            :disabled="cannotSpeak"
            placeholder="有什么新鲜事告诉大家…（支持 Markdown，可换行、贴链接、写公式）"
          />
          <div class="benben-submit-btn">
            <button
              class="auth-btn"
              :disabled="cannotSpeak || posting"
              @click="postBenben"
            >
              {{ posting ? '发射中...' : '发射犇犇！' }}
            </button>
          </div>
        </div>

        <div class="benben-nav">
          <div class="benben-tab" :class="{ active: feedMode === 'all' }" @click="switchTab('all')">全部</div>
          <div class="benben-tab" :class="{ active: feedMode === 'my' }" @click="switchTab('my')">我的</div>
        </div>

        <div class="benben-list" ref="benbenListRef">
          <div v-if="benbenList.length === 0 && !isLoading" class="benben-empty">
            {{ sentinelText === '加载出错，请刷新' ? sentinelText : '没有更多动态了' }}
          </div>

          <div v-for="item in benbenList" :key="item.id" class="benben-item" :data-id="item.id">
            <div class="benben-avatar">
              <UserAvatarStatus :user="item" :size="8">
                <router-link :to="`/user/${item.user_number}`">
                  <img
                    :src="getUserAvatar(item)"
                    :alt="item.username"
                    @error="($event.target as HTMLImageElement).src = letterAvatar(item.username)"
                  >
                </router-link>
              </UserAvatarStatus>
            </div>

            <div class="benben-content" :class="{ 'is-new': flashIds.has(item.id) }">
              <div class="benben-item-header">
                <div class="post-author">
                  <span class="benben-user">
                    <router-link
                      :to="`/user/${item.user_number}`"
                      class="benben-username"
                      :style="{ color: getUserDisplayColor(item) }"
                    >{{ item.username }}</router-link><span
                      v-if="getUserTagDisplay(item)"
                      class="user-tag-display"
                      :style="{ backgroundColor: getUserDisplayColor(item) }"
                    >{{ getUserTagDisplay(item) }}</span>
                  </span>
                  <span class="benben-time">{{ formatTime(item.created_at) }}</span>
                </div>

                <div class="benben-actions">
                  <button
                    v-if="currentUser?.user_number !== item.user_number && currentUser?.can_speak"
                    class="benben-report-btn"
                    @click="openReport(item)"
                  >举报</button>
                  <button class="benben-reply-btn" @click="replyToBenben(item)">回复</button>
                  <button
                    v-if="currentUser?.user_number === item.user_number"
                    class="benben-delete"
                    @click="deleteBenben(item.id)"
                  >删除</button>
                </div>
              </div>

              <div class="benben-text prose" v-html="renderMarkdown(item.content)"></div>

              <div v-if="item.reply_to_username" class="benben-reply-hint">
                <i class="fa-solid fa-reply"></i> 回复了 @{{ item.reply_to_username }}
              </div>
            </div>
          </div>

          <div v-show="sentinelVisible" ref="loadingSentinelRef" class="loading-sentinel">
            <button
              v-if="hasMore && !isLoading && sentinelText !== '加载出错，请刷新'"
              type="button"
              class="load-more-btn"
              @click="loadBenbenList(false)"
            >
              {{ sentinelText }}
            </button>
            <span v-else>{{ sentinelText }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 回到顶部 -->
    <button v-show="showBackTop" class="back-to-top" title="回到顶部" @click="backToTop"><i class='fa-solid fa-arrow-up'></i></button>

    <!-- 有新动态但用户不在列表顶部时的提示（固定在底部居中，不挡内容） -->
    <Transition name="benben-pill">
      <button v-if="pendingBenben.length" class="benben-new-pill" @click="showPendingBenben">
        <i class='fa-solid fa-arrow-up'></i> {{ pendingBenben.length }} 条新动态
      </button>
    </Transition>
  </div>

</template>

<style scoped>
/* ========== 页面容器 ========== */
.home-page {
  min-height: 100vh;
  line-height: 1.5;
}

.home-container {
  max-width: 1400px;
  margin: 0 auto;
}

/* ========== 卡片 ========== */
/* 背景/圆角/边框/阴影由全局 .card 基类统一提供（亚克力），这里只管布局 */
.card {
  padding: 20px 24px;
  margin-bottom: 24px;
}

.card-header {
  font-size: 1.25rem;
  font-weight: 600;
  border-left: 4px solid var(--primary);
  padding-left: 12px;
  margin-bottom: 20px;
}

/* ========== 下方板块：紧凑横条 ========== */
.strip-card {
  margin-bottom: 16px;
  padding: 14px 18px;
}

.strip-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.strip-title {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 15px;
  font-weight: 700;
  color: var(--text-strong);
}

.strip-title i {
  color: var(--primary);
  font-size: 13px;
}

.strip-count {
  font-size: 12px;
  color: var(--text-sub);
  background: var(--surface-strong);
  border: 1px solid var(--border-color);
  border-radius: 999px;
  padding: 1px 9px;
}

/* 友链：一排小胶囊 */
.friend-pill-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.friend-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  max-width: 100%;
  padding: 5px 13px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: var(--surface);
  color: var(--text-primary);
  text-decoration: none;
  font-size: 13px;
  line-height: 1.4;
  transition: border-color 0.15s, background 0.15s, transform 0.15s;
}

.friend-pill:hover {
  border-color: var(--primary);
  background: var(--surface-strong);
  transform: translateY(-1px);
}

.friend-pill img {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  object-fit: contain;
  flex: none;
}

.friend-pill span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 细横条列表（讨论 / 题单共用） */
.strip-rows {
  display: flex;
  flex-direction: column;
}

.strip-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 8px 6px;
  border-radius: 9px;
  text-decoration: none;
  color: var(--text-primary);
  transition: background 0.15s;
}

.strip-row + .strip-row {
  border-top: 1px dashed var(--border-color);
}

.strip-row:hover {
  background: color-mix(in srgb, var(--primary) 7%, transparent);
}

.strip-row-title {
  flex: 1;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.strip-row-meta {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-sub);
  max-width: 55%;
  overflow: hidden;
  white-space: nowrap;
}

.strip-row-meta > span,
.strip-row-meta > a {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.strip-row-author {
  font-weight: 600;
}

.strip-row-dot {
  color: var(--border-color);
}

/* ========== 首屏云图板块 ========== */
/* 未启用云图时：普通卡片流（.cloud-section 什么都不做） */
.cloud-section {
  position: relative;
  margin-bottom: 24px;
}

/* 未启用 / 拉取失败回退态也保持水平居中：与云图态同轴心，回退时不再横移 */
.cloud-section:not(.cloud-full) .cloud-center {
  margin-inline: auto;
}

/* 云图启用：占满一屏高，中央卡居中，四周小卡绝对定位辐射 */
.cloud-section.cloud-full {
  min-height: calc(100vh - 120px);
  display: grid;
  place-items: center;
  padding: 28px 0 40px;
}

/* 中心 → 各卡的细虚线（百分比坐标系，卡片自身盖在线上） */
.cloud-lines {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 0;
}

.cloud-lines line {
  stroke: color-mix(in srgb, var(--primary) 38%, transparent);
  stroke-width: 0.18;
  stroke-dasharray: 1.2 1.6;
}

/* 实测布局完成前先藏起来（椭圆初值可能压着中央卡），.cloud-ready 后放行入场 */
.cloud-section.cloud-full:not(.cloud-ready) .cloud-node,
.cloud-section.cloud-full:not(.cloud-ready) .cloud-lines {
  opacity: 0;
}

/* 连线：错峰淡入 + 虚线缓慢流动（dash 周期 1.2+1.6=2.8，位移一个周期无缝循环） */
.cloud-full.cloud-ready .cloud-lines line {
  animation:
    cloud-line-in 0.6s ease backwards calc(var(--i, 0) * 70ms + 260ms),
    cloud-line-flow 9s linear calc(var(--i, 0) * 70ms + 260ms) infinite;
}

@keyframes cloud-line-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@keyframes cloud-line-flow {
  to {
    stroke-dashoffset: -2.8;
  }
}

/* 中央头像 + 运势卡 */
.cloud-center {
  position: relative;
  z-index: 1;
  width: min(440px, 100%);
  text-align: center;
  padding: 26px 26px 24px;
}

.cloud-avatar-wrap {
  position: relative;
  display: inline-block;
  margin-bottom: 10px;
}

.cloud-avatar {
  width: 88px;
  height: 88px;
  border-radius: 50%;
  object-fit: cover;
  border: 3px solid color-mix(in srgb, var(--primary) 45%, transparent);
  box-shadow: 0 6px 18px color-mix(in srgb, var(--primary) 25%, transparent);
  background: var(--surface-strong);
}

.cloud-avatar-status {
  position: absolute;
  right: 4px;
  bottom: 4px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  /* 默认离线红；真在线才绿（与 UserAvatarStatus 的配色一致） */
  background: #ef4444;
  border: 3px solid var(--surface-strong);
}

.cloud-avatar-status.online {
  background: #22c55e;
}

.cloud-center .fortune-col {
  display: flex;
  flex-direction: column;
  justify-content: center;
}

/* 四周辐射小卡 */
.cloud-node {
  position: absolute;
  z-index: 1;
  /* 居中用独立的 translate 属性，把 transform 留给入场 / 浮动动画；
     hover 放大也用独立 scale 属性，待机动画不会吞掉悬停反馈 */
  translate: -50% -50%;
  width: 236px;
  padding: 12px 14px;
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 46%;
  overflow: hidden;
  transition: scale 0.18s ease, box-shadow 0.18s ease;
}

/* 入场（透明度+缩放，逐张错峰）＋待机上下浮动（随机周期/相位）；
   入场用 scale、浮动用 transform，两条动画属性互不打架 */
.cloud-full.cloud-ready .cloud-node {
  animation:
    cloud-node-in 0.55s cubic-bezier(0.22, 1, 0.36, 1) backwards calc(var(--i, 0) * 70ms),
    cloud-float var(--fdur, 7s) ease-in-out infinite
      calc(var(--i, 0) * 70ms + 0.7s + var(--fdelay, 0s));
}

.cloud-node:hover {
  scale: 1.03;
  /* 悬停提到最前：盖过相邻小卡、中央卡与连接线（z-index 即时生效，不参与过渡） */
  z-index: 10;
}

@keyframes cloud-node-in {
  from {
    opacity: 0;
    scale: 0.86;
  }
  to {
    opacity: 1;
    scale: 1;
  }
}

@keyframes cloud-float {
  0%,
  100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-7px);
  }
}

@keyframes cloud-fade-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

/* 中央卡入场：它是布局锚点、始终可见，只做轻微上浮 */
.cloud-full.cloud-ready .cloud-center {
  animation: cloud-center-in 0.6s ease backwards;
}

@keyframes cloud-center-in {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 纵排降级（JS 判定放不下「中央卡 + 两侧卡」）：与 ≤768px 同款布局。
   入场 / 浮动动画照常可用——keyframes 只写 opacity、scale、transform，
   不碰定位用的 translate 属性 */
.cloud-section.cloud-full.cloud-stack {
  min-height: auto;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 14px;
  padding: 4px 0 20px;
}

.cloud-stack .cloud-lines {
  display: none;
}

.cloud-stack .cloud-center {
  width: 100%;
}

.cloud-stack .cloud-node {
  position: static;
  translate: none;
  width: 100%;
  max-height: none;
}

.cloud-stack .cloud-node:hover {
  scale: none;
}

.cloud-node-head {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  font-weight: 700;
  color: var(--text-strong);
  padding-bottom: 7px;
  border-bottom: 1px dashed var(--border-color);
}

.cloud-node-head i {
  color: var(--primary);
  font-size: 12px;
}

.cloud-node-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
  overflow-y: auto;
}

.cloud-line-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
  text-decoration: none;
  padding: 4px 6px;
  border-radius: 8px;
  transition: background 0.15s;
}

.cloud-line-row:hover {
  background: color-mix(in srgb, var(--primary) 8%, transparent);
}

.cloud-line-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-strong);
  line-height: 1.35;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.cloud-line-sub {
  font-size: 11.5px;
  color: var(--text-sub);
  display: flex;
  align-items: center;
  gap: 6px;
}

.cloud-pno {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  color: var(--primary);
  background: color-mix(in srgb, var(--primary) 10%, transparent);
  border-radius: 5px;
  padding: 1px 5px;
}

.cloud-diff {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 999px;
  font-weight: 600;
}

.diff-easy {
  color: #2f9e5f;
  background: color-mix(in srgb, #2f9e5f 14%, transparent);
}

.diff-mid {
  color: #d98212;
  background: color-mix(in srgb, #d98212 15%, transparent);
}

.diff-hard {
  color: #e05252;
  background: color-mix(in srgb, #e05252 15%, transparent);
}

/* 友链小卡：图标 + 名称的迷你网格 */
.cloud-friend-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(64px, 1fr));
  gap: 6px;
  overflow-y: auto;
}

.cloud-friend {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 6px 3px;
  border: 1px solid var(--border-color);
  border-radius: 9px;
  text-decoration: none;
  color: var(--text-primary);
  font-size: 11px;
  text-align: center;
  transition: border-color 0.15s, transform 0.15s;
}

.cloud-friend:hover {
  border-color: var(--primary);
  transform: translateY(-2px);
}

.cloud-friend img {
  width: 26px;
  height: 26px;
  object-fit: contain;
  border-radius: 6px;
}

.cloud-friend span {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.welcome-line {
  font-weight: 700;
  font-size: 1.2rem;
  margin-bottom: 8px;
}

.lg-index-calendar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 8px 0 12px;
  color: #396A42;
}

.lg-index-calendar .lg-punch-left,
.lg-index-calendar .lg-punch-right {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0;
  font-size: 0.95rem;
  font-weight: 400;
  color: #396A42;
  line-height: 1.3;
}

.lg-index-calendar .lg-punch-big {
  font-size: 5rem;
  font-weight: 700;
  color: #396A42;
  line-height: 1.1;
  letter-spacing: 2px;
}

.lg-small {
  font-size: 0.95rem;
  color: var(--text-sub);
  line-height: 1.8;
}

.lg-small strong {
  color: var(--text-strong);
  font-weight: 700;
}

.am-btn {
  display: inline-block;
  padding: 8px 16px;
  margin-top: 10px;
  font-size: 15px;
  font-weight: normal;
  border: none;
  border-radius: 40px;
  cursor: pointer;
  transition: background 0.2s, opacity 0.2s;
  text-decoration: none;
  color: #fff;
}

.am-btn-warning {
  background: #F37B1D;
}

.am-btn-warning:hover {
  background: #E0690C;
}

.fortune-title {
  margin-bottom: 0;
  font-size: 1.3rem;
  font-weight: 500;
  color: var(--text-strong);
  text-align: center;
}

.fortune-title-suffix {
  font-weight: bold;
}

.lg-bold {
  font-weight: bold;
}

.fortune-result-wrap {
  text-align: center;
}

.lg-punch-result {
  font-size: 4rem;
  font-weight: bold;
  letter-spacing: 4px;
  padding: 8px 32px;
  border-radius: 30px;
  display: inline-block;
  margin-bottom: 12px;
  line-height: 1.2;
}

.lg-fg-red {
  color: #E74C3C;
}

.lg-fg-green {
  color: #5EB95E;
}

.lg-fg-black {
  color: var(--text-strong);
}

.fortune-grid {
  display: flex;
  /* 宜 / 忌 必须水平并排：这里不能换行。
     中央云图卡宽约 440px，若允许 wrap，两块 200px 起步的栏目
     放不下就会上下堆叠，失去「宜忌并列」的观感。 */
  flex-wrap: nowrap;
  gap: 16px 20px;
  margin: 6px 0 10px;
}

.fortune-grid .fortune-col-item {
  /* 等宽两栏；min-width:0 必需，否则内容会把 flex 子项撑破并溢出容器 */
  flex: 1 1 0;
  min-width: 0;
  overflow-wrap: anywhere;
}

.fortune-entry {
  margin-bottom: 10px;
  line-height: 1.5;
}

.fortune-good-label {
  color: #E74C3C;
}

.fortune-desc {
  display: block;
  margin-top: 1px;
  padding-left: 2px;
}

.fortune-nothing {
  color: var(--text-strong);
  font-size: 1rem;
  line-height: 1.5;
}

.fortune-nothing-red {
  color: #E74C3C;
  font-size: 1rem;
  line-height: 1.5;
}

.fortune-bad-strong {
  color: var(--text-strong);
}

.fortune-bad-name {
  color: var(--text-strong);
}

.fortune-days {
  text-align: center;
  padding-top: 8px;
  margin-top: 4px;
}

.brand-highlight {
  color: var(--primary);
  font-weight: 700;
}

/* ========== 空状态 ========== */
.empty-state {
  text-align: center;
  padding: 24px 16px;
  color: var(--text-sub);
  font-size: 14px;
}

.pin-badge {
  flex: none;
  display: inline-block;
  background: var(--primary);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  padding: 1px 8px;
  border-radius: 4px;
  vertical-align: middle;
}

/* ========== 犇犇模块 ========== */
.benben-header {
  font-size: 1.15rem;
  font-weight: 700;
  border-left: 4px solid var(--primary);
  padding-left: 12px;
  margin-bottom: 16px;
}

.benben-editor {
  margin-bottom: 20px;
}

.benben-editor textarea {
  width: 100%;
  padding: 12px 14px;
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--surface-strong);
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-main);
  resize: vertical;
  font-family: inherit;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.benben-editor textarea:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 15%, transparent);
}

.benben-submit-btn {
  margin-top: 10px;
  display: flex;
  justify-content: flex-end;
}

.auth-btn {
  background: var(--primary);
  color: white;
  border: none;
  border-radius: 999px;
  padding: 7px 22px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  text-decoration: none;
  display: inline-block;
  transition: background 0.15s ease, opacity 0.15s ease;
}

.auth-btn:hover:not(:disabled) {
  background: var(--primary-hover);
}

.auth-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 「全部 / 我的」：原来是一整条灰底 + 两个等宽分段，改成两颗轻量胶囊 */
.benben-nav {
  display: flex;
  gap: 8px;
  margin: 18px 0 0;
  padding: 0;
  list-style: none;
}

.benben-tab {
  flex: 0 0 auto;
  cursor: pointer;
  padding: 6px 18px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-sub);
  background: transparent;
  border: var(--border-width) solid transparent;
  border-radius: 999px;
  transition: color 0.18s ease, background-color 0.18s ease, border-color 0.18s ease;
}

.benben-tab:hover {
  color: var(--primary);
  background: color-mix(in srgb, var(--primary) 6%, transparent);
}

.benben-tab.active {
  color: var(--primary);
  background: color-mix(in srgb, var(--primary) 10%, transparent);
  border-color: color-mix(in srgb, var(--primary) 35%, transparent);
}

.benben-list {
  margin-top: 20px;
}

.benben-item {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  position: relative;
}

.benben-avatar {
  flex-shrink: 0;
  width: 40px;
  margin-top: 2px;
}

.benben-avatar a {
  display: block;
}

.benben-avatar img {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--bg-subtle);
}

.benben-content {
  flex: 1;
  background: var(--surface);
  -webkit-backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  backdrop-filter: blur(var(--surface-blur)) saturate(1.5);
  border: var(--border-width) solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 10px 16px 12px;
  position: relative;
  box-shadow: 0 1px 3px rgba(31, 41, 85, 0.05);
}

/* 原来这里有一对 ::before/::after 小三角（聊天气泡的“箭头”），
   颜色是写死的 #f0f2f5/#e9ecef，跟半透明气泡对不上，看着很脏，已去掉。 */

/* 作者行：原来是一条负 margin 出血的 #f0f2f5 灰头条，改成透明的一行，
   用户名/时间/操作直接坐在亚克力气泡上。 */
.benben-item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 12px;
  background: none;
  padding: 0;
  margin: 0 0 6px;
}

.post-author {
  display: flex;
  align-items: center;
  gap: 4px 8px;
  flex-wrap: wrap;
}

.benben-user {
  display: inline-flex;
  align-items: center;
  vertical-align: middle;
}

.benben-username {
  font-weight: 600;
  color: var(--text-main);
  text-decoration: none;
  font-size: 14px;
  vertical-align: middle;
}

.benben-username:hover {
  color: var(--primary);
}

.user-tag-display {
  display: inline-block;
  border-radius: 6px;
  padding: 1px 8px;
  color: #fff;
  font-size: 11.5px;
  font-weight: 600;
  margin: 0 0 0 6px;
  cursor: default;
  transition: filter 0.15s;
  vertical-align: middle;
}

.user-tag-display:hover {
  filter: brightness(0.9);
}

.benben-time {
  font-size: 12px;
  color: var(--text-sub);
}

.benben-time::before {
  content: '·';
  margin-right: 6px;
}

.benben-actions {
  display: flex;
  gap: 2px;
  align-items: center;
}

/* 操作按钮做成小胶囊：平时只有文字，悬停才浮出底色 */
.benben-report-btn,
.benben-reply-btn,
.benben-delete {
  background: transparent;
  border: none;
  color: var(--text-sub);
  font-size: 12px;
  cursor: pointer;
  padding: 3px 10px;
  border-radius: 999px;
  transition: color 0.15s ease, background-color 0.15s ease;
}

.benben-report-btn:hover,
.benben-reply-btn:hover {
color: var(--primary-text);
  background: color-mix(in srgb, var(--primary) 8%, transparent);
}

.benben-delete:hover {
  color: var(--danger);
  background: rgba(239, 68, 68, 0.1);
}

.benben-text {
  word-break: break-word;
}

/* 代码块/行内代码交给 assets/markdown.css 的 .prose 统一方案（深色 oneDark），
   旧的浅色 pre/code 覆盖会让深底上的浅字看不清 */
.benben-text :deep(a) {
  color: var(--primary);
  text-decoration: none;
}

.benben-text :deep(a:hover) {
  text-decoration: underline;
}

.benben-reply-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-sub);
}

.benben-empty,
.no-more-message {
  text-align: center;
  padding: 40px;
  color: var(--text-sub);
  font-size: 14px;
}

.loading-sentinel {
  text-align: center;
  padding: 20px;
  color: var(--text-sub);
  font-size: 13px;
}

/* ========== 犇犇新动态提示 ========== */
.benben-new-pill {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 998;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 20px;
  font-size: 13px;
  font-weight: 600;
  color: #fff;
  background: var(--primary);
  border: none;
  border-radius: 999px;
  cursor: pointer;
  box-shadow: 0 4px 16px color-mix(in srgb, var(--glow-blue) 40%, transparent);
  transition: background 0.15s, transform 0.15s;
}

.benben-new-pill:hover {
  background: var(--primary-hover);
  transform: translateX(-50%) translateY(-2px);
}

.benben-pill-enter-active,
.benben-pill-leave-active {
  transition: opacity 0.2s, transform 0.2s;
}

.benben-pill-enter-from,
.benben-pill-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(12px);
}

/* 自动刷新刚插进来的动态，短暂高亮一下就恢复。
   卡片本身是半透明亚克力，高亮也用半透明主色，避免闪成不透明白块。 */
.benben-content.is-new {
  animation: benben-flash 2.6s ease-out;
}

@keyframes benben-flash {
  0%,
  55% {
    background: color-mix(in srgb, var(--primary) 10%, transparent);
    border-color: color-mix(in srgb, var(--primary) 40%, transparent);
  }
  100% {
    background: var(--surface);
    border-color: var(--border-color);
  }
}

/* ========== 回到顶部 ========== */
.back-to-top {
  position: fixed;
  bottom: 30px;
  right: 30px;
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: 50%;
  width: 50px;
  height: 50px;
  font-size: 24px;
  cursor: pointer;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.2);
  z-index: 999;
  transition: opacity 0.3s, transform 0.3s;
}

.back-to-top:hover {
  background: var(--primary);
  transform: scale(1.1);
}

/* 移动端：右下角被 SideBar 的菜单悬浮按钮占据（≤768px 在 right/bottom 20px 放 52px 圆钮，
   ≤600px 是 16px/48px），回到顶部改为叠放在它正上方，留 12px 间距不再重叠。
   底部安全区跟随菜单按钮，保证刘海屏上间距一致 */
@media (max-width: 768px) {
  .back-to-top {
    right: 20px;
    bottom: calc(84px + env(safe-area-inset-bottom, 0px)); /* 20 + 52 + 12 */
  }
}

@media (max-width: 600px) {
  .back-to-top {
    right: 16px;
    bottom: calc(76px + env(safe-area-inset-bottom, 0px)); /* 16 + 48 + 12 */
    width: 44px;
    height: 44px;
    font-size: 22px;
  }
}

/* ========== 响应式 ========== */
@media (max-width: 768px) {
  /* 云图降级：中央卡在上，四周小卡改为纵排，不画连接线 */
  .cloud-section.cloud-full {
    min-height: auto;
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 14px;
    padding: 4px 0 20px;
  }

  .cloud-lines {
    display: none;
  }

  .cloud-center {
    width: 100%;
  }

  .cloud-node {
    position: static;
    translate: none;
    width: 100%;
    max-height: none;
  }

  .cloud-node:hover {
    scale: none;
  }
}

@media (max-width: 700px) {
  .lg-punch-result {
    font-size: 2.8rem;
  }

  /* 窄屏：横条行的元信息只留作者，其余省略，避免标题被挤没 */
  .strip-row {
    flex-wrap: wrap;
  }

  .strip-row-meta {
    max-width: 100%;
    flex-basis: 100%;
    padding-left: 0;
  }

  .strip-row-meta > span:nth-of-type(n + 3) {
    display: none;
  }
}

@media (max-width: 600px) {
  .card {
    padding: 14px;
  }

  /* 空状态盒子原本左右各 40px，手机上只剩 243px */
  .benben-empty {
    padding: 28px 16px;
  }

  .benben-item {
    gap: 10px;
  }

  .benben-avatar {
    width: 32px;
    margin-top: 2px;
  }

  .benben-avatar img {
    width: 32px;
    height: 32px;
  }

  .benben-content {
    padding: 8px 12px 10px;
  }

  .benben-item-header {
    padding: 0;
    margin: 0 0 6px;
    gap: 4px;
    flex-direction: column;
    align-items: flex-start;
  }

  .post-author {
    gap: 6px;
  }

  .benben-actions {
    gap: 8px;
  }

  .benben-text {
    font-size: 14px;
  }

  .lg-index-calendar .lg-punch-big {
    font-size: 2rem;
  }

  .lg-small {
    font-size: 0.88rem;
  }

  .am-btn {
    padding: 6px 20px;
    font-size: 14px;
  }

  .back-to-top {
    bottom: 20px;
    right: 20px;
    width: 40px;
    height: 40px;
    font-size: 20px;
  }
}

/* ========== 首页训练题单（横条行） ========== */
.more-link {
  font-size: 13px;
  color: var(--primary);
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: color 0.15s;
}

.more-link:hover {
  text-decoration: underline;
}

.badge-featured-sm {
  flex: none;
  background: color-mix(in srgb, var(--warning) 12%, transparent);
  color: var(--warning-text);
  border: 1px solid color-mix(in srgb, var(--warning) 45%, transparent);
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
</style>
