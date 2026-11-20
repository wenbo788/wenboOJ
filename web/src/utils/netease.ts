/**
 * 网易云音乐：识别 + 生成外链播放器。
 *
 * 与 utils/bilibili.ts 同一机制：站内 Markdown 白名单禁止 iframe
 * （见 utils/markdown.ts 的 USER_HTML_CONFIG），用户直接贴网易云「嵌入代码」
 * 会被消毒器整段剥掉，表现是「贴了音乐什么都不显示」。
 *
 * 做法：把「独立一行的网易云链接 / 分享 iframe」识别出来，先换成占位符，
 * 等消毒完成**之后**再用我们自己拼的 outchain/player iframe 还原 ——
 * 用户可控的 HTML 依旧进不了 iframe，只有我们构造的 music.163.com 播放器会出现。
 *
 * 支持的写法（单曲 / 歌单 / 专辑）：
 *   https://music.163.com/#/song?id=186016      （站内复制的 hash 路由链接）
 *   https://music.163.com/song?id=186016
 *   https://music.163.com/song/186016
 *   https://m.music.163.com/#/song?id=186016
 *   https://music.163.com/playlist?id=24381616
 *   https://music.163.com/album?id=32311
 *   <iframe src="//music.163.com/outchain/player?type=2&id=186016&auto=0&height=66"></iframe>
 *
 * 不支持裸编号：网易云资源 id 是纯数字，没有 BV 号那样的特征前缀，
 * 单独一行的「186016」无法与题号 / 楼号区分，误伤成本大于收益。
 * 暂不支持 163cn.tv 短链：与 b23.tv 同理，跟随跳转是异步的而渲染管线同步；
 * 短链保持普通链接，不误伤。
 *
 * 实测（2026-10）三种 type 的外链端点均返回播放器页面：
 *   type=2 单曲（height=66 紧凑播放条） / type=0 歌单 / type=1 专辑
 */

export interface NeteaseRef {
  /** 资源类型，与 outchain/player 的 type 参数一致：2=单曲 0=歌单 1=专辑 */
  type: 0 | 1 | 2
  id: number
}

const TYPE_PLAYLIST = 0
const TYPE_ALBUM = 1
const TYPE_SONG = 2

const KIND_LABEL: Record<number, string> = {
  [TYPE_SONG]: '单曲',
  [TYPE_PLAYLIST]: '歌单',
  [TYPE_ALBUM]: '专辑',
}

/** 我们认的 host（避免把伪装链接也变成播放器） */
function isAllowedHost(h: string): boolean {
  return h === 'music.163.com' || h.endsWith('.music.163.com')
}

/** 从 URL 提取资源引用（host 白名单 + id/type 提取） */
function refFromUrl(raw: string): NeteaseRef | null {
  // 协议相对（//music.163.com/...）补成 https
  const s = raw.startsWith('//') ? `https:${raw}` : raw
  let url: URL
  try {
    url = new URL(s)
  } catch {
    return null
  }
  if (!isAllowedHost(url.hostname.toLowerCase())) return null

  // 站内分享是 hash 路由（#/song?id=186016），id 藏在 hash 里；
  // 普通链接在 query 或 path（/song/186016）。拼一起统一挖。
  const hay = `${url.pathname}${url.search}${url.hash}`
  const idm =
    hay.match(/[?&]id=(\d{1,12})/) ||
    hay.match(/\/(?:song|playlist|album)\/(\d{1,12})(?:\D|$)/)
  if (!idm) return null
  const id = Number(idm[1])
  if (!Number.isSafeInteger(id) || id <= 0) return null

  // 类型：outchain 直链看 type= 参数；分享链接看路径里的资源词
  let type: number
  if (/\/outchain\/player/i.test(url.pathname)) {
    const tm = hay.match(/[?&]type=(\d)/)
    if (!tm) return null
    type = Number(tm[1])
    if (type !== TYPE_SONG && type !== TYPE_PLAYLIST && type !== TYPE_ALBUM) return null
  } else if (/song/i.test(hay)) {
    type = TYPE_SONG
  } else if (/playlist/i.test(hay)) {
    type = TYPE_PLAYLIST
  } else if (/album/i.test(hay)) {
    type = TYPE_ALBUM
  } else {
    return null
  }

  return { type: type as 0 | 1 | 2, id }
}

/** 识别一行内容是不是网易云引用（分享代码 / 独立一行的链接） */
export function parseNeteaseRef(line: string): NeteaseRef | null {
  const trimmed = line.trim()

  // 1) 分享代码：<iframe src="//music.163.com/outchain/player?...">
  if (/^<iframe\b/i.test(trimmed)) {
    const src = trimmed.match(/\bsrc\s*=\s*["']([^"']+)["']/i)?.[1]
    return src ? refFromUrl(src) : null
  }

  // 2) 整行就是一个链接
  if (/^(?:https?:)?\/\/\S+$/i.test(trimmed)) {
    return refFromUrl(trimmed)
  }

  return null
}

/** 拼外链播放器地址（autoplay 关掉，别吓人） */
export function buildNeteasePlayerUrl(ref: NeteaseRef): string {
  const q = new URLSearchParams()
  q.set('type', String(ref.type))
  q.set('id', String(ref.id))
  q.set('auto', '0')
  // 单曲外链官方带 height（66=紧凑播放条）；歌单/专辑列表页由内容自适应
  if (ref.type === TYPE_SONG) q.set('height', '66')
  return `https://music.163.com/outchain/player?${q.toString()}`
}

/** 生成嵌进正文的 HTML（iframe 是我们自己拼的，不经过用户输入） */
export function renderNeteaseEmbed(ref: NeteaseRef): string {
  const src = buildNeteasePlayerUrl(ref)
  const kind = KIND_LABEL[ref.type]
  const label = `${kind} #${ref.id}`
  // caption 回链到资源页（hash 路由是站内分享同款，最通用）
  const pageType =
    ref.type === TYPE_SONG ? 'song' : ref.type === TYPE_PLAYLIST ? 'playlist' : 'album'
  const pageUrl = `https://music.163.com/#/${pageType}?id=${ref.id}`
  // 单曲是 66px 播放条；歌单/专辑是可滚动列表
  const cls = ref.type === TYPE_SONG ? 'netease-embed type-song' : 'netease-embed type-list'
  return (
    `<div class="${cls}">` +
    `<iframe src="${src}" title="网易云音乐 ${label}"` +
    ' frameborder="0" scrolling="no"' +
    ' loading="lazy" referrerpolicy="no-referrer"></iframe>' +
    `<div class="netease-embed-caption"><a href="${pageUrl}" target="_blank" rel="noopener noreferrer">${label}</a></div>` +
    '</div>'
  )
}
