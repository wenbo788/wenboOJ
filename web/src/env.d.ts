/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string
  /** '1' = 空壳/演示模式：后端未接入，页面顶部显示提示 */
  readonly VITE_SHELL_MODE?: string
  readonly VITE_ESA_CAPTCHA_PREFIX: string
  readonly VITE_ESA_CAPTCHA_SCENE_ID_AUTH: string
  readonly VITE_ESA_CAPTCHA_SCENE_ID_TOKENS: string
  /** @deprecated Use VITE_ESA_CAPTCHA_SCENE_ID_AUTH. */
  readonly VITE_ESA_CAPTCHA_SCENE_ID?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}