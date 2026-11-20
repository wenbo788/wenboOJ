/** 通用格式化工具（跨页面共用，避免同一数据在不同页面显示不一致）。 */

/**
 * 字节数转可读体积。
 *
 * 单一实现：0 输出 `0 B`；B 整数；KB/MB 保留一位小数。
 * ProblemEdit / ProblemDetail 等页面统一引用本函数。
 */
export function formatBytes(bytes?: number | null): string {
  const n = typeof bytes === 'number' && Number.isFinite(bytes) ? bytes : 0
  if (n <= 0) return '0 B'
  if (n < 1024) return `${Math.round(n)} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(2)} MB`
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`
}
