/**
 * B 站视频：识别 + 生成播放器。
 *
 * 为什么需要它：站内的 Markdown 白名单**禁止 iframe/video/embed**
 * （见 utils/markdown.ts 的 USER_HTML_CONFIG），所以用户直接贴 B 站分享代码
 * 会被消毒器整段剥掉，表现是「贴了视频什么都不显示」。
 *
 * 做法：把「独立一行的 B 站链接 / 分享 iframe / 裸 BV·av 号」识别出来，
 * 先换成占位符，等消毒完成**之后**再用我们自己拼的 iframe 还原 —— 这样
 * 用户可控的 HTML 依旧进不了 iframe，只有我们构造的 player.bilibili.com 播放器
 * 会出现。
 *
 * 支持的写法：
 *   https://www.bilibili.com/video/BV1xx411c7mD?p=2
 *   https://m.bilibili.com/video/av170001
 *   https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&page=2
 *   <iframe src="//player.bilibili.com/player.html?bvid=BV1xx411c7mD"></iframe>
 *   BV1xx411c7mD  /  av170001        （单独成行时）
 *
 * 暂不支持 b23.tv 短链：它得靠服务端跟随跳转才能拿到 BV，纯前端（渲染是同步的）
 * 做不到；这种链接保持普通链接，不误伤。
 */

export interface BilibiliRef {
  bvid?: string
  aid?: number
  /** 分 P，默认 1 */
  page: number
}

/** BV 号：BV + 1 位 + 9 位（B 站的固定长度编码） */
const BV_RE = /(BV1[1-9A-HJ-NP-Za-km-z]{9})/
const AV_RE = /av(\d{1,12})/i

/** 我们认的 host（避免把伪装链接也变成播放器） */
const ALLOWED_HOSTS = new Set([
  'bilibili.com',
  'www.bilibili.com',
  'm.bilibili.com',
  'player.bilibili.com',
])

function isAllowedHost(host: string): boolean {
  const h = host.toLowerCase()
  return ALLOWED_HOSTS.has(h) || h.endsWith('.bilibili.com')
}

function toRef(bvid?: string | null, aid?: number | null, page?: number | null): BilibiliRef | null {
  const ref: BilibiliRef = {
    bvid: bvid || undefined,
    aid: aid && aid > 0 ? aid : undefined,
    page: page && page > 0 ? page : 1,
  }
  if (!ref.bvid && !ref.aid) return null
  return ref
}

/** 从一段 URL 里取 BV/av/分 P；不是 B 站就返回 null */
function refFromUrl(raw: string): BilibiliRef | null {
  let url: URL
  try {
    // 协议相对（//player.bilibili.com/...）补成 https
    url = new URL(/^\/\//.test(raw) ? `https:${raw}` : raw)
  } catch {
    return null
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null
  if (!isAllowedHost(url.hostname)) return null

  const text = url.toString()
  const bv = (url.pathname.match(BV_RE) || text.match(BV_RE) || [])[1]
  const avRaw = (url.pathname.match(AV_RE) || [])[1] || url.searchParams.get('aid') || url.searchParams.get('avid')
  const pageRaw = url.searchParams.get('p') || url.searchParams.get('page')
  const av = avRaw && Number(avRaw) ? Number(avRaw) : undefined
  const page = pageRaw && Number(pageRaw) ? Number(pageRaw) : 1
  return toRef(bv, av, page)
}

/**
 * 把「独立一行」的 B 站视频引用解析出来。
 *
 * 只认独立成行的形式：正文里顺带提到的 B 站链接保持普通链接，不然一段文字
 * 中间冒出个播放器会很怪。
 */
export function parseBilibiliRef(line: string): BilibiliRef | null {
  const trimmed = line.trim()
  if (!trimmed) return null

  // 1) 分享代码：<iframe src="//player.bilibili.com/player.html?bvid=...">
  if (/^<iframe\b/i.test(trimmed)) {
    const src = trimmed.match(/\bsrc\s*=\s*["']([^"']+)["']/i)?.[1]
    return src ? refFromUrl(src) : null
  }

  // 2) 整行就是一个链接
  if (/^(?:https?:)?\/\/\S+$/i.test(trimmed)) {
    return refFromUrl(trimmed)
  }

  // 3) 整行就是一个裸编号（可选带 -p2 / ?p=2 这种后缀）
  const bare = trimmed.match(/^(BV1[1-9A-HJ-NP-Za-km-z]{9}|av\d{1,12})(?:[?#&]|[\s-]|$)/i)
  if (bare) {
    const token = bare[1]
    const bv = token.match(BV_RE)?.[1]
    const av = token.match(AV_RE)?.[1]
    const page = trimmed.match(/[?&#-]p(?:age)?=?(\d+)/i)?.[1]
    return toRef(bv, av ? Number(av) : undefined, page ? Number(page) : 1)
  }

  return null
}

/** 拼播放器地址（isOutside=true 是站外嵌入必须的；autoplay 关掉，别吓人） */
export function buildBilibiliPlayerUrl(ref: BilibiliRef): string {
  const q = new URLSearchParams()
  q.set('isOutside', 'true')
  if (ref.bvid) q.set('bvid', ref.bvid)
  else if (ref.aid) q.set('aid', String(ref.aid))
  q.set('page', String(ref.page || 1))
  q.set('autoplay', '0')
  q.set('danmaku', '1')
  return `https://player.bilibili.com/player.html?${q.toString()}`
}

/** 生成嵌进正文的 HTML（iframe 是我们自己拼的，不经过用户输入） */
export function renderBilibiliEmbed(ref: BilibiliRef): string {
  const src = buildBilibiliPlayerUrl(ref)
  const label = ref.bvid || `av${ref.aid}`
  return (
    '<div class="bili-embed">' +
    `<iframe src="${src}" title="B 站视频 ${label}"` +
    ' frameborder="0" scrolling="no" allowfullscreen' +
    ' loading="lazy" referrerpolicy="no-referrer"></iframe>' +
    `<div class="bili-embed-caption"><a href="https://www.bilibili.com/video/${label}" target="_blank" rel="noopener noreferrer">${label}</a></div>` +
    '</div>'
  )
}
