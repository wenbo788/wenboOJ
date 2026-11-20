import { useAuthStore } from '@/stores/auth'
import { DEFAULT_CODE } from '@/constants/languages'

/**
 * 代码编辑器的初始模板（提交页与沉浸做题共用）：
 * 偏好设置里存了该语言的模板就用它，否则回内置默认。
 * 空模板视为未设置（用户没必要存空串，兜底防清空编辑器）。
 */
export function getCodeTemplate(language: string): string {
  const tpl = useAuthStore().currentUser?.code_template
  const custom = tpl?.[language]
  if (typeof custom === 'string' && custom.length > 0) return custom
  return DEFAULT_CODE[language] ?? ''
}
