/** 投票页共用的小工具（列表页与详情页都用）。 */
import type { Poll } from '@/api/polls'

/** 时间显示：本地化，无值时给空串（null 别渲染成 "Invalid Date"） */
export function pollTimeText(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString('zh-CN', { hour12: false })
}

/**
 * 把接口错误翻译成人话。
 *
 * 后端 422 的 `detail` 是一个数组（Pydantic 的字段错误），直接丢给 Swal 会显示
 * `[object Object]`；这里统一取 `msg`。
 */
export function describePollError(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((x: any) => (typeof x === 'string' ? x : x?.msg))
      .filter((x: unknown) => typeof x === 'string' && x)
    if (msgs.length) return msgs.join('；')
  }
  if (e?.code === 'ECONNABORTED') return '请求超时，请刷新看看操作是否已经生效'
  if (!e?.response) return '网络异常，请刷新看看操作是否已经生效'
  const status = e.response.status
  if (status >= 500) return `服务端异常（${status}），请稍后再试`
  return fallback
}

/** 两次「我的选择」是否完全相同（用来判断失败后操作是否其实已生效） */
export function sameChoices(a: number[] | null | undefined, b: number[] | null | undefined): boolean {
  const x = [...(a || [])].sort((m, n) => m - n)
  const y = [...(b || [])].sort((m, n) => m - n)
  return x.length === y.length && x.every((v, i) => v === y[i])
}

/** 接口返回的 payload 是否像一个投票（防止把空响应当成成功去更新状态） */
export function looksLikePoll(v: unknown): v is Poll {
  return !!v && typeof v === 'object' && typeof (v as Poll).id === 'number'
    && Array.isArray((v as Poll).options)
}
