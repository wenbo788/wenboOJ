import { getAccessToken } from '@/utils/session'
import { apiUrl } from '@/utils/base'

export const USER_ONLINE_THRESHOLD_MS = 60_000

let lastPresencePingAt = 0
let heartbeatTimer: number | undefined
let visibilityHandler: (() => void) | undefined

export function isUserOnline(
  user?: { last_seen?: string | Date | null } | null,
  thresholdMs = USER_ONLINE_THRESHOLD_MS,
): boolean {
  if (!user?.last_seen) return false

  const timestamp = new Date(_asUtcIso(user.last_seen)).getTime()
  if (Number.isNaN(timestamp)) return false

  return Date.now() - timestamp <= thresholdMs
}

/**
 * 后端约定发带时区的 UTC ISO 串（`+00:00`），但有两处会变成「裸串」：
 * SQLite 部署（tzinfo 存不下来）与直接 isoformat 的接口。JS 遇到裸串会按
 * **本地时区**解析，北京时间下直接差 8 小时，结果所有人都被算成离线。
 * 裸串一律补 Z 当 UTC 处理。
 */
function _asUtcIso(value: string | Date): string | Date {
  if (value instanceof Date) return value
  const s = value.trim()
  if (!s.includes('T') || /([zZ]|[+-]\d{2}:?\d{2})$/.test(s)) return s
  return `${s}Z`
}

export async function pingUserPresence(): Promise<boolean> {
  const accessToken = getAccessToken()
  if (!accessToken) return false

  const now = Date.now()
  if (now - lastPresencePingAt < 30_000) return true
  lastPresencePingAt = now

  try {
    await fetch(apiUrl('/users/me/seen'), {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
      },
    })
    return true
  } catch {
    return false
  }
}

export function startPresenceHeartbeat(): void {
  if (heartbeatTimer) return

  void pingUserPresence()
  heartbeatTimer = window.setInterval(() => {
    if (document.visibilityState === 'visible') {
      void pingUserPresence()
    }
  }, 30_000)

  visibilityHandler = () => {
    if (!document.hidden) void pingUserPresence()
  }
  document.addEventListener('visibilitychange', visibilityHandler)
}

export function stopPresenceHeartbeat(): void {
  if (heartbeatTimer) {
    window.clearInterval(heartbeatTimer)
    heartbeatTimer = undefined
  }
  if (visibilityHandler) {
    document.removeEventListener('visibilitychange', visibilityHandler)
    visibilityHandler = undefined
  }
}
