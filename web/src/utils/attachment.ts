import type { AxiosRequestConfig } from 'axios'
import apiClient from '../api/client'

/**
 * 题目附件下载。
 *
 * 附件落盘在私有目录，后端只认 `Authorization: Bearer` 头，
 * 因此**不能**直接用 `<a href>` 导航——浏览器不会带自定义头，
 * 会得到 401 并被 axios 拦截器判成登出、清空 token 跳登录页。
 *
 * 正确做法：用带鉴权头的 axios 请求成 blob，再临时 objectURL 触发下载。
 */

/** 用带鉴权头的方式下载附件，落地为浏览器下载。 */
export async function downloadAttachmentFile(
  downloadUrl: string,
  fileName: string
): Promise<void> {
  // download_url 是后端给的相对路径（不含 /api 前缀），统一补齐前缀
  const url = downloadUrl.startsWith('/api/') || downloadUrl.startsWith('http')
    ? downloadUrl
    : `/api${downloadUrl.startsWith('/') ? '' : '/'}${downloadUrl}`

  const config: AxiosRequestConfig = { responseType: 'blob' }
  const resp = await apiClient.get(url, config).catch(async (e: any) => {
    // responseType 为 blob 时，错误响应体也是 Blob 而非对象，
    // 调用方读不到 err.response.data.detail，这里先解析成 JSON 再抛出
    const data = e?.response?.data
    if (data instanceof Blob) {
      try {
        const parsed = JSON.parse(await data.text())
        if (parsed?.detail) e.message = parsed.detail
      } catch {
        /* 非 JSON 错误体，保留原 message */
      }
    }
    throw e
  })
  const blob = resp.data as Blob
  const href = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = href
    a.download = fileName || 'attachment'
    a.rel = 'noopener'
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    // 立即 revoke 会让部分浏览器来不及触发下载，延迟释放
    setTimeout(() => URL.revokeObjectURL(href), 1000)
  }
}
