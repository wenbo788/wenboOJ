/**
 * 偏好设置可选的等宽字体。
 * key 与后端 user_profile.py 的 _ALLOWED_PREF_FONTS 一一对应，改一处必须同步另一处。
 * css 为完整 font-family 值：首选指定字体，兜底链与默认（JetBrains Mono）保持一致。
 */
export interface CodeFont {
  key: string
  label: string
  css: string
}

/** 与 style.css 的 --font-mono 默认值一致 */
export const DEFAULT_CODE_FONT_KEY = 'jetbrains-mono'

const FALLBACK = '"Fira Code", Consolas, Monaco, monospace'

export const CODE_FONTS: CodeFont[] = [
  { key: 'jetbrains-mono', label: 'JetBrains Mono', css: `"JetBrains Mono", ${FALLBACK}` },
  { key: 'roboto-mono', label: 'Roboto Mono', css: `"Roboto Mono", ${FALLBACK}` },
  { key: 'source-code-pro', label: 'Source Code Pro', css: `"Source Code Pro", ${FALLBACK}` },
  { key: 'ibm-plex-mono', label: 'IBM Plex Mono', css: `"IBM Plex Mono", ${FALLBACK}` },
  { key: 'space-mono', label: 'Space Mono', css: `"Space Mono", ${FALLBACK}` },
  { key: 'courier-prime', label: 'Courier Prime', css: `"Courier Prime", ${FALLBACK}` },
]

/** key → font-family 值；未知 key 回默认字体 */
export function codeFontCss(key: string | null | undefined): string {
  return CODE_FONTS.find((f) => f.key === key)?.css ?? CODE_FONTS[0].css
}
