type AliyunCaptchaInstance = {
  refresh?: () => void
}

type AliyunCaptchaCallbacks = {
  onSuccess: (verifyParam: string) => void | Promise<void>
  onFailure: (message: string) => void
  onClose: () => void
}

type AliyunCaptchaOptions = {
  SceneId: string
  mode: 'popup' | 'embed'
  element: string
  button: string
  success: (verifyParam: string) => void
  fail?: (result: any) => void
  getInstance: (instance: AliyunCaptchaInstance) => void
  onError: (error: { code?: string; msg?: string }) => void
  onClose: () => void
  server: string[]
  language: 'cn'
  slideStyle?: { width: number; height: number }
  /** 验证码 UI 整体缩放系数（官方移动端方案），小于 1 时整体缩小。 */
  rem?: number
}

declare global {
  interface Window {
    AliyunCaptchaConfig?: { region: 'cn'; prefix: string }
    initAliyunCaptcha?: (options: AliyunCaptchaOptions) => void
  }
}

const SCRIPT_ID = 'nlnoj-aliyun-captcha-sdk'
const ELEMENT_ID = 'nlnoj-aliyun-captcha-element'
const BUTTON_ID = 'nlnoj-aliyun-captcha-trigger'
const SCRIPT_URL = 'https://o.alicdn.com/captcha-frontend/aliyunCaptcha/AliyunCaptcha.js'

let scriptPromise: Promise<void> | null = null
let initPromise: Promise<void> | null = null
let activeCallbacks: AliyunCaptchaCallbacks | null = null
let captchaInstance: AliyunCaptchaInstance | null = null
let readyAt = 0

const ensureMountNodes = () => {
  let element = document.getElementById(ELEMENT_ID)
  if (!element) {
    element = document.createElement('div')
    element.id = ELEMENT_ID
    document.body.appendChild(element)
  }

  let button = document.getElementById(BUTTON_ID) as HTMLButtonElement | null
  if (!button) {
    button = document.createElement('button')
    button.id = BUTTON_ID
    button.type = 'button'
    button.tabIndex = -1
    button.setAttribute('aria-hidden', 'true')
    Object.assign(button.style, {
      position: 'fixed',
      left: '-10000px',
      top: '0',
      width: '1px',
      height: '1px',
      opacity: '0',
    })
    document.body.appendChild(button)
  }
}

const loadScript = (): Promise<void> => {
  if (window.initAliyunCaptcha) return Promise.resolve()
  if (scriptPromise) return scriptPromise

  scriptPromise = new Promise<void>((resolve, reject) => {
    let script = document.getElementById(SCRIPT_ID) as HTMLScriptElement | null
    if (!script) {
      script = document.createElement('script')
      script.id = SCRIPT_ID
      script.src = SCRIPT_URL
      script.async = true
      document.head.appendChild(script)
    }

    const onLoad = () => {
      cleanup()
      if (window.initAliyunCaptcha) resolve()
      else reject(new Error('阿里云验证码 SDK 加载后未提供初始化接口'))
    }
    const onError = () => {
      cleanup()
      scriptPromise = null
      script?.remove()
      reject(new Error('阿里云验证码 SDK 加载失败，请检查网络后重试'))
    }
    const cleanup = () => {
      script?.removeEventListener('load', onLoad)
      script?.removeEventListener('error', onError)
    }

    script.addEventListener('load', onLoad, { once: true })
    script.addEventListener('error', onError, { once: true })
  })

  return scriptPromise
}

/** 动态加载并只初始化一次 ESA 验证码，遵守 SDK 的单次初始化约束。 */
export async function prepareAliyunCaptcha(
  prefix: string,
  sceneId: string,
  callbacks: AliyunCaptchaCallbacks,
): Promise<void> {
  activeCallbacks = callbacks
  if (initPromise) return initPromise

  initPromise = (async () => {
    ensureMountNodes()
    window.AliyunCaptchaConfig = { region: 'cn', prefix }
    await loadScript()

    await new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(() => reject(new Error('阿里云验证码初始化超时')), 15000)
      // 嵌入式按表单容器宽度整体缩放，避免窄屏溢出（官方移动端方案；
      // width 低于 320 会被 SDK 提到 320，所以用 rem 而不是缩 slideStyle）。
      const slotWidth = document.getElementById(ELEMENT_ID)?.clientWidth || 0
      const rem = slotWidth > 0 && slotWidth < 360 ? slotWidth / 360 : 0
      try {
        window.initAliyunCaptcha?.({
          SceneId: sceneId,
          // 嵌入式：验证组件直接渲染在表单内的 element 中，不弹遮罩弹窗。
          // 若控制台把验证码类型改成「无痕验证」，必须改回 'popup'
          //（官方规定无痕验证不支持嵌入式接入）。
          mode: 'embed',
          element: `#${ELEMENT_ID}`,
          button: `#${BUTTON_ID}`,
          success: verifyParam => {
            const handler = activeCallbacks?.onSuccess
            const run = handler ? handler(verifyParam) : Promise.resolve()
            // 官方示例在业务请求发出后调用 captcha.refresh() 复位实例，供下一次
            // 重新验证——不复位的话，重试登录可能复用旧票据被 ESA 判 F018（重复
            // 使用）。verifyParam 是已签出的字符串，与实例状态无关，先发请求再
            // 复位互不影响。refresh 是兼容方法名（V3 方法表未列），不存在时安全跳过。
            void Promise.resolve(run)
              .catch(() => {
                /* 登录失败的展示已由回调处理，这里只为复位兜底 */
              })
              .then(() => captchaInstance?.refresh?.())
          },
          fail: (result: any) => {
            activeCallbacks?.onFailure(result?.msg || '安全验证未通过，请重试')
          },
          getInstance: instance => {
            captchaInstance = instance
            readyAt = Date.now() + 2000
            window.clearTimeout(timeout)
            resolve()
          },
          onError: error => {
            window.clearTimeout(timeout)
            reject(new Error(error?.msg || error?.code || '阿里云验证码初始化失败'))
          },
          onClose: () => activeCallbacks?.onClose(),
          server: ['captcha-esa-open.aliyuncs.com', 'captcha-esa-open-b.aliyuncs.com'],
          language: 'cn',
          slideStyle: { width: 360, height: 40 },
          ...(rem ? { rem } : {}),
        })
      } catch (error) {
        window.clearTimeout(timeout)
        reject(error instanceof Error ? error : new Error('阿里云验证码初始化失败'))
      }
    })
  })().catch(error => {
    initPromise = null
    throw error
  })

  return initPromise
}

/** 在用户点击登录按钮的同一事件栈中触发 SDK 绑定的触发器（button 参数官方必传、可为隐藏元素；嵌入式下部分形态点击即激活内嵌验证，也可能为空操作，调用方失败可忽略）。 */
export async function triggerAliyunCaptcha(): Promise<void> {
  if (!captchaInstance) throw new Error('安全验证尚未准备好')
  const wait = readyAt - Date.now()
  if (wait > 0) throw new Error('安全验证正在准备，请稍后重试')
  const button = document.getElementById(BUTTON_ID) as HTMLButtonElement | null
  if (!button) throw new Error('安全验证触发器不存在')
  button.click()
}

export function isAliyunCaptchaReady(): boolean {
  return !!captchaInstance && Date.now() >= readyAt
}

export function clearAliyunCaptchaCallbacks(): void {
  activeCallbacks = null
}
