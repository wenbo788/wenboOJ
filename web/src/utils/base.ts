/**
 * 站点部署路径 / 后端静态资源地址的统一处理。
 *
 * 线上通常部署在域名根路径（base = '/'），但 GitHub Pages 的项目页会部署在
 * `/<仓库名>/` 子路径下；模板里写死的 `href="/problems"`、`src="/logo.png"`
 * 在子路径下会指到根域，导致跳转 404 或图片裂开。所有站内绝对路径都应经过
 * `withBase()`，后端返回的 `/static/...` 图片应经过 `staticUrl()`。
 */

/** Vite 注入的部署根路径，始终以 '/' 结尾（根路径为 '/'，项目页为 '/repo/'）。 */
export const SITE_BASE: string = import.meta.env.BASE_URL || '/'

/** 把站内路径（'/problems'、'login'、'/user/1'）拼到部署 base 下。 */
export function withBase(path: string): string {
  if (!path) return SITE_BASE
  // 外链、协议相对地址、锚点原样返回
  if (/^(?:[a-z][a-z0-9+.-]*:)?\/\//i.test(path) || path.startsWith('#')) return path

  const base = SITE_BASE.endsWith('/') ? SITE_BASE : SITE_BASE + '/'
  const rest = path.replace(/^\/+/, '')
  return rest ? base + rest : base
}

/** 后端 origin（VITE_API_BASE_URL）。未配置或同源时返回空串。 */
export function apiOrigin(): string {
  const raw = (import.meta.env.VITE_API_BASE_URL || '').trim()
  if (!raw) return ''
  try {
    const fallback = typeof window !== 'undefined' ? window.location.origin : 'http://localhost'
    return new URL(raw, fallback).origin
  } catch {
    return ''
  }
}

/**
 * 拼接后端接口地址（用于绕过 axios 的裸 fetch）。
 * 跨域部署（GitHub Pages）时补 API origin；同源时保持相对路径。
 */
export function apiUrl(path: string): string {
  const origin = apiOrigin()
  if (!origin) return path
  if (typeof window !== 'undefined' && origin === window.location.origin) return path
  return origin + (path.startsWith('/') ? path : '/' + path)
}

/**
 * 后端返回的静态资源路径（头像、题面图片等）补上 API origin。
 *
 * 后端存的是 `/static/uploads/...` 这种根相对路径，跨域部署到 Pages 后
 * 浏览器会去 Pages 域找图，必须显式指向 API 域。同源部署原样返回。
 */
export function staticUrl(path: string): string {
  if (!path || !path.startsWith('/static/')) return path

  const origin = apiOrigin()
  if (!origin) return path
  if (typeof window !== 'undefined' && origin === window.location.origin) return path

  return origin + path
}
