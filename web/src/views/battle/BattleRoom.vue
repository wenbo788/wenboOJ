<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { battleApi, type BattleRoomDetail, type BattlePlayer, type BattleTryRunResult } from '@/api/battle'
import { renderRichText } from '@/utils/markdown'
import { difficultyColor } from '@/utils/difficulty'
import { copyText } from '@/utils/codeCopy'
import { userNameColor } from '@/utils/userColor'
import { staticUrl } from '@/utils/base'
import CodeEditor from '@/components/CodeEditor.vue'
import Swal from 'sweetalert2'

const route = useRoute()
const router = useRouter()

const battleId = computed(() => parseInt(route.params.battleId as string, 10))

const room = ref<BattleRoomDetail | null>(null)
const loading = ref(true)
const submitting = ref(false)

// Editor code & language
const selectedLang = ref('cpp')
const code = ref(`#include <iostream>
using namespace std;

int main() {
  // Write your code here
  return 0;
}
`)

const templates: Record<string, string> = {
  cpp: `#include <iostream>
using namespace std;

int main() {
  ios::sync_with_stdio(false);
  cin.tie(nullptr);
  
  return 0;
}
`,
  c: `#include <stdio.h>

int main() {
  return 0;
}
`,
  python3: `import sys

def main():
  pass

if __name__ == '__main__':
  main()
`,
}

const onLanguageChange = () => {
  if (templates[selectedLang.value]) {
    code.value = templates[selectedLang.value]
  }
}

// ==================== 在线自测环境 (Online IDE / Test Bench) ====================
const showTestPanel = ref(false)
const testInput = ref('')
const testRunning = ref(false)
const testResult = ref<BattleTryRunResult | null>(null)
const testRunError = ref('')
const testActiveTab = ref<'input' | 'output'>('input')
const testPanelHeight = ref(240)
let isDraggingResizer = false
let startDragY = 0
let startPanelHeight = 240

// 选中的样例期望输出（用于自动 AC/WA 对比）
const sampleExpected = ref<string | null>(null)
const sampleMatchedIndex = ref<number | null>(null)

/** 与正式评测同口径：每行去行尾空白、去结尾空行（judge.normalize_output） */
const norm = (s: string) => {
  const lines = s.replace(/\r\n/g, '\n').split('\n').map((l) => l.replace(/[ \t]+$/, ''))
  while (lines.length && lines[lines.length - 1] === '') lines.pop()
  return lines.join('\n')
}

const isSampleVerdict = computed<'AC' | 'WA' | null>(() => {
  if (!testResult.value || testResult.value.status !== 'ok') return null
  if (sampleExpected.value === null) return null
  const out = norm(testResult.value.stdout || '')
  const exp = norm(sampleExpected.value)
  return out === exp ? 'AC' : 'WA'
})

const STATUS_LABELS: Record<string, string> = {
  ok: '运行成功',
  compile_error: '编译错误 (Compile Error)',
  runtime_error: '运行错误 (Runtime Error)',
  time_limit_exceeded: '超出时间限制 (Time Limit Exceeded)',
  memory_limit_exceeded: '超出内存限制 (Memory Limit Exceeded)',
  output_limit_exceeded: '输出超限 (Output Limit Exceeded)',
  system_error: '系统评测异常',
}

watch(testInput, (newVal) => {
  const samples = room.value?.problem.samples || []
  let found = false
  for (let i = 0; i < samples.length; i++) {
    if (samples[i].input === newVal) {
      sampleExpected.value = samples[i].output
      sampleMatchedIndex.value = i + 1
      found = true
      break
    }
  }
  if (!found) {
    sampleExpected.value = null
    sampleMatchedIndex.value = null
  }
})

const fillSample = (sample: { input: string; output: string }, idx: number) => {
  testInput.value = sample.input
  sampleExpected.value = sample.output
  sampleMatchedIndex.value = idx
  testActiveTab.value = 'input'
  showTestPanel.value = true
}

const runSelfTest = async () => {
  if (testRunning.value || !code.value.trim() || isFinished.value) return
  testRunning.value = true
  testRunError.value = ''
  testResult.value = null
  testActiveTab.value = 'output'
  showTestPanel.value = true

  try {
    const res = await battleApi.tryRun(battleId.value, {
      code: code.value,
      language: selectedLang.value,
      input: testInput.value,
    })
    testResult.value = res
  } catch (err: any) {
    testRunError.value = err?.response?.data?.detail || '自测运行失败：无法连接评测沙箱'
  } finally {
    testRunning.value = false
  }
}

const onResizerMouseDown = (e: MouseEvent) => {
  isDraggingResizer = true
  startDragY = e.clientY
  startPanelHeight = testPanelHeight.value
  document.addEventListener('mousemove', onResizerMouseMove)
  document.addEventListener('mouseup', onResizerMouseUp)
  e.preventDefault()
}

const onResizerMouseMove = (e: MouseEvent) => {
  if (!isDraggingResizer) return
  const deltaY = startDragY - e.clientY
  const newHeight = Math.max(140, Math.min(500, startPanelHeight + deltaY))
  testPanelHeight.value = newHeight
}

const onResizerMouseUp = () => {
  if (isDraggingResizer) {
    isDraggingResizer = false
    document.removeEventListener('mousemove', onResizerMouseMove)
    document.removeEventListener('mouseup', onResizerMouseUp)
  }
}


// Countdown timer
const remainingSeconds = ref(1800)
let timerInterval: ReturnType<typeof setInterval> | undefined
let pollInterval: ReturnType<typeof setInterval> | undefined

// Settlement modal
const showResultModal = ref(false)

const me = computed<BattlePlayer | null>(() => {
  if (!room.value) return null
  return room.value.user1.is_me ? room.value.user1 : room.value.user2
})

const opponent = computed<BattlePlayer | null>(() => {
  if (!room.value) return null
  return room.value.user1.is_me ? room.value.user2 : room.value.user1
})

const isFinished = computed(() => {
  return room.value?.status === 'finished'
})

const myResult = computed(() => {
  if (!room.value || room.value.status !== 'finished') return 'ongoing'
  if (room.value.winner_id === null) return 'draw'
  return room.value.winner_id === me.value?.id ? 'win' : 'loss'
})

const mySettlement = computed(() => {
  if (!room.value?.settlement) return null
  return room.value.user1.is_me ? room.value.settlement.user1 : room.value.settlement.user2
})

const tierIconMap: Record<string, string> = {
  bronze: 'fa-shield',
  silver: 'fa-shield-halved',
  gold: 'fa-award',
  platinum: 'fa-medal',
  diamond: 'fa-gem',
}

const tierColorMap: Record<string, string> = {
  bronze: '#cd7f32',
  silver: '#a0aec0',
  gold: '#d69e2e',
  platinum: '#38b2ac',
  diamond: '#3182ce',
}

const fetchRoomData = async () => {
  try {
    const data = await battleApi.getRoom(battleId.value)
    room.value = data
    remainingSeconds.value = data.remaining_seconds

    // 同步服务端权威切屏次数，避免重新加载界面重置显示
    if (typeof data.my_screen_switch_count === 'number') {
      screenSwitchCount.value = Math.max(screenSwitchCount.value, data.my_screen_switch_count)
    }

    if (data.problem?.samples && data.problem.samples.length > 0 && !testInput.value) {
      testInput.value = data.problem.samples[0].input
      sampleExpected.value = data.problem.samples[0].output
      sampleMatchedIndex.value = 1
    }

    if (data.status === 'finished' && !showResultModal.value) {
      showResultModal.value = true
      clearInterval(pollInterval)
      clearInterval(timerInterval)
      clearTimeout(screenLeaveTimer)
    }
  } catch (err) {
    console.error('Failed to load battle room:', err)
  } finally {
    loading.value = false
  }
}

const pasteAttempts = ref(0)
const onBattlePasteBlocked = (_payload: { reason: string }) => {
  pasteAttempts.value += 1
}

// ===== 防切屏作弊机制与全屏模式 =====
// 规则：切屏第 1 次警告，第 2 次直接判负；若第 1 次切屏离开超过 15 秒也直接判负
const battleRoomRef = ref<HTMLDivElement | null>(null)
const screenSwitchCount = ref(0)
const isAwayFromScreen = ref(false)
const leaveStartTime = ref<number | null>(null)
let screenLeaveTimer: ReturnType<typeof setTimeout> | undefined
const isHandlingForfeit = ref(false)
const isShowingWarningDialog = ref(false)
let isProcessingScreenEvent = false

// 全屏状态与过渡保护机制
const isFullscreen = ref(false)
let isFullscreenTransitioning = false
let fullscreenTransitionTimer: ReturnType<typeof setTimeout> | undefined
let pendingLeaveTimer: ReturnType<typeof setTimeout> | undefined
let pendingLeaveStartTimestamp: number | null = null

// 离开缓冲期：2000毫秒
// 规避全屏切换动画（macOS Space/Windows F11）、系统菜单栏与 Dock 呼出、Select 下拉框点击等瞬时焦点丢失误判
const LEAVE_DEBOUNCE_MS = 2000

const checkIsFullscreen = (): boolean => {
  const doc = document as any
  const isDocFs = !!(
    doc.fullscreenElement ||
    doc.webkitFullscreenElement ||
    doc.mozFullScreenElement ||
    doc.msFullscreenElement
  )
  if (isDocFs) return true

  // 检测窗口级全屏（如 F11 / macOS 绿色全屏按钮）
  return (
    Math.abs(window.innerHeight - window.screen.height) <= 6 &&
    Math.abs(window.innerWidth - window.screen.width) <= 6
  )
}

const markFullscreenTransition = () => {
  isFullscreenTransitioning = true

  // 全屏过渡期间立即清空挂起的切屏计时器，防止误判
  if (pendingLeaveTimer) {
    clearTimeout(pendingLeaveTimer)
    pendingLeaveTimer = undefined
    pendingLeaveStartTimestamp = null
  }

  // 若处于全屏过渡中却碰巧已被置为离开，立即挽回状态
  if (isAwayFromScreen.value) {
    isAwayFromScreen.value = false
    clearTimeout(screenLeaveTimer)
    battleApi.reportScreenSwitch(battleId.value, 'return').catch(() => {})
  }

  clearTimeout(fullscreenTransitionTimer)
  fullscreenTransitionTimer = setTimeout(() => {
    isFullscreenTransitioning = false
  }, 3500) // 3.5秒保护期，充分覆盖各类系统的全屏动画耗时
}

const updateFullscreenState = () => {
  const currentFs = checkIsFullscreen()
  if (isFullscreen.value !== currentFs) {
    isFullscreen.value = currentFs
    markFullscreenTransition()
  }
}

const toggleFullscreen = async () => {
  markFullscreenTransition()
  try {
    const doc = document as any
    const isCurrentlyFs = checkIsFullscreen()

    if (isCurrentlyFs) {
      if (doc.exitFullscreen) {
        await doc.exitFullscreen()
      } else if (doc.webkitExitFullscreen) {
        await doc.webkitExitFullscreen()
      } else if (doc.mozCancelFullScreen) {
        await doc.mozCancelFullScreen()
      } else if (doc.msExitFullscreen) {
        await doc.msExitFullscreen()
      }
    } else {
      const docEl = document.documentElement as any
      if (docEl.requestFullscreen) {
        await docEl.requestFullscreen()
      } else if (docEl.webkitRequestFullscreen) {
        await docEl.webkitRequestFullscreen()
      } else if (docEl.mozRequestFullScreen) {
        await docEl.mozRequestFullScreen()
      } else if (docEl.msRequestFullscreen) {
        await docEl.msRequestFullscreen()
      }
    }
  } catch (err) {
    console.warn('全屏切换失败或未授权:', err)
  } finally {
    setTimeout(() => {
      updateFullscreenState()
    }, 100)
  }
}

const triggerScreenSwitchForfeit = async (reason: 'screen_switch_timeout' | 'screen_switch_second') => {
  if (isHandlingForfeit.value || isFinished.value) return
  isHandlingForfeit.value = true
  clearTimeout(screenLeaveTimer)
  if (pendingLeaveTimer) {
    clearTimeout(pendingLeaveTimer)
    pendingLeaveTimer = undefined
  }

  try {
    await battleApi.surrender(battleId.value, reason)
    await fetchRoomData()
  } catch (err) {
    console.error('Failed to forfeit due to screen switch:', err)
  } finally {
    const isTimeout = reason === 'screen_switch_timeout'
    Swal.fire({
      icon: 'error',
      title: isTimeout ? '切屏超时，判定战败！' : '二次切屏违规，直接判负！',
      html: isTimeout
        ? '你在对战过程中切离页面<strong>超过 15 秒</strong>，触发防作弊规则，本局已被直接判定战败并扣除胜点！'
        : '你在对战过程中<strong>累计切屏达到 2 次</strong>，触发防作弊规则，本局已被直接判定战败并扣除胜点！',
      confirmButtonText: '查看结算',
      confirmButtonColor: '#ef4444',
      allowOutsideClick: false,
    })
  }
}

const handleUserLeftScreen = async (actualLeaveTime = Date.now()) => {
  if (isProcessingScreenEvent) return
  // 仅在对战进行中、且未结算、且未在系统对话框中、且未处于全屏过渡动画中检测
  if (isFinished.value || !room.value || room.value.status !== 'ongoing') return
  if (isHandlingForfeit.value || isShowingWarningDialog.value || isFullscreenTransitioning) return
  if (isAwayFromScreen.value) return

  isProcessingScreenEvent = true
  try {
    isAwayFromScreen.value = true
    leaveStartTime.value = actualLeaveTime
    screenSwitchCount.value += 1

    // 上报切屏离开事件给后端，同步违规状态
    const reportRes = await battleApi.reportScreenSwitch(battleId.value, 'leave').catch(() => null)
    if (reportRes && typeof reportRes.leave_count === 'number') {
      screenSwitchCount.value = Math.max(screenSwitchCount.value, reportRes.leave_count)
    }

    if (screenSwitchCount.value >= 2) {
      // 第二次切屏：直接判负！
      await triggerScreenSwitchForfeit('screen_switch_second')
      return
    }

    // 第一次切屏：启动 15 秒定时器（扣除缓冲期已流逝时间）
    const elapsedMs = Date.now() - actualLeaveTime
    const remainingForfeitMs = Math.max(1000, 15000 - elapsedMs)

    clearTimeout(screenLeaveTimer)
    screenLeaveTimer = setTimeout(async () => {
      if (isAwayFromScreen.value && !isFinished.value && !isHandlingForfeit.value) {
        await triggerScreenSwitchForfeit('screen_switch_timeout')
      }
    }, remainingForfeitMs)
  } finally {
    isProcessingScreenEvent = false
  }
}

const handleUserReturnedScreen = async () => {
  if (isProcessingScreenEvent) return
  if (!isAwayFromScreen.value) return

  isProcessingScreenEvent = true
  try {
    isAwayFromScreen.value = false
    clearTimeout(screenLeaveTimer)

    // 上报切屏返回事件给后端，记录本次离开耗时
    const returnRes = await battleApi.reportScreenSwitch(battleId.value, 'return').catch(() => null)
    if (returnRes && typeof returnRes.leave_count === 'number') {
      screenSwitchCount.value = Math.max(screenSwitchCount.value, returnRes.leave_count)
    }

    if (isFinished.value || isHandlingForfeit.value) return

    const leaveMs = leaveStartTime.value ? Date.now() - leaveStartTime.value : 0
    const leaveSec = Math.max(1, Math.round(leaveMs / 1000))

    // 如果第 1 次离开超过 15 秒，也直接判负
    if (leaveMs >= 15000) {
      await triggerScreenSwitchForfeit('screen_switch_timeout')
      return
    }

    // 第一次切屏在 15 秒内返回：弹出严正警告
    if (screenSwitchCount.value === 1) {
      isShowingWarningDialog.value = true
      try {
        await Swal.fire({
          icon: 'warning',
          title: '⚠️ 切屏违规警告（第 1/2 次）',
          html: `
            <div style="text-align: left; font-size: 14px; line-height: 1.7;">
              <p style="color: #ef4444; font-weight: bold; margin-bottom: 8px;">
                检测到你已切离对战页面（本次离开约 ${leaveSec} 秒）！
              </p>
              <p style="margin-bottom: 6px; color: #374151;">为保证 1v1 对战的竞技公平性，请注意以下规则：</p>
              <ul style="padding-left: 20px; margin: 0 0 10px 0; color: #4b5563;">
                <li><strong style="color: #dc2626;">再次切屏（第 2 次）将直接被判定战败并扣除胜点！</strong></li>
                <li><strong style="color: #dc2626;">单次切屏离开超过 15 秒将直接判定战败！</strong></li>
              </ul>
              <p style="color: #6b7280; font-size: 12px; margin: 0;">提示：可使用顶部的「全屏对战」按钮获得最佳沉浸体验，全屏切换不会判定切屏。</p>
            </div>
          `,
          confirmButtonText: '我知道了，继续比赛',
          confirmButtonColor: '#d97706',
          allowOutsideClick: false,
        })
      } finally {
        isShowingWarningDialog.value = false
      }
    }
  } finally {
    isProcessingScreenEvent = false
  }
}

const scheduleLeaveCheck = () => {
  // 全屏过渡中、正在弹窗或对决已结束，完全不计离开
  if (isFullscreenTransitioning || isShowingWarningDialog.value || isFinished.value) {
    return
  }
  // 已经处于离开状态，无需重复触发
  if (isAwayFromScreen.value) {
    return
  }

  if (!pendingLeaveStartTimestamp) {
    pendingLeaveStartTimestamp = Date.now()
  }

  if (!pendingLeaveTimer) {
    pendingLeaveTimer = setTimeout(() => {
      pendingLeaveTimer = undefined
      const leaveTime = pendingLeaveStartTimestamp || Date.now()
      pendingLeaveStartTimestamp = null

      // 缓冲时间到期后再次严格复查：用户是否确实不在当前页面
      if (
        !isFullscreenTransitioning &&
        !isShowingWarningDialog.value &&
        !isFinished.value &&
        (document.hidden || !document.hasFocus())
      ) {
        handleUserLeftScreen(leaveTime)
      }
    }, LEAVE_DEBOUNCE_MS)
  }
}

const cancelLeaveCheckOrHandleReturn = () => {
  // 缓冲期内回焦（例如快捷全屏切换、系统顶栏收起、下拉菜单点击等瞬时事件），直接取消离开判定
  if (pendingLeaveTimer) {
    clearTimeout(pendingLeaveTimer)
    pendingLeaveTimer = undefined
    pendingLeaveStartTimestamp = null
  }

  // 如果此前已经确认为真实切离（超过缓冲期），则按正常返回流程处理
  if (isAwayFromScreen.value) {
    handleUserReturnedScreen()
  }
}

const onVisibilityChange = () => {
  if (document.hidden) {
    scheduleLeaveCheck()
  } else {
    cancelLeaveCheckOrHandleReturn()
  }
}

const onWindowBlur = () => {
  scheduleLeaveCheck()
}

const onWindowFocus = () => {
  cancelLeaveCheckOrHandleReturn()
}

const onFullscreenChange = () => {
  updateFullscreenState()
  markFullscreenTransition()
}

const onResize = () => {
  updateFullscreenState()
}

const onKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'F11' || (e.key === 'Escape' && isFullscreen.value)) {
    markFullscreenTransition()
  }
  // Ctrl+Enter or Cmd+Enter: 快捷自测运行
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault()
    runSelfTest()
  }
}

const submitCode = async () => {
  if (!code.value.trim() || submitting.value || isFinished.value) return
  submitting.value = true

  try {
    await battleApi.submitCode(battleId.value, code.value, selectedLang.value)
    // Fast refresh
    await fetchRoomData()
  } catch (err: any) {
    alert(err?.response?.data?.detail || '提交失败，请重试')
  } finally {
    submitting.value = false
  }
}

const surrender = async () => {
  if (isFinished.value) return
  isShowingWarningDialog.value = true
  const res = await Swal.fire({
    title: '确认认输？',
    text: '认输后此局将被直接判定失败并结算！',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonText: '确定认输',
    cancelButtonText: '继续比赛',
    confirmButtonColor: '#ef4444',
  })
  isShowingWarningDialog.value = false
  if (!res.isConfirmed) return

  try {
    await battleApi.surrender(battleId.value, 'surrender')
    await fetchRoomData()
  } catch (err: any) {
    alert(err?.response?.data?.detail || '操作失败')
  }
}

const formatTimer = (sec: number) => {
  const m = Math.floor(sec / 60).toString().padStart(2, '0')
  const s = (sec % 60).toString().padStart(2, '0')
  return `${m}:${s}`
}

onMounted(async () => {
  await fetchRoomData()

  // 绑定切屏防作弊与全屏保护监听器
  document.addEventListener('visibilitychange', onVisibilityChange)
  window.addEventListener('blur', onWindowBlur)
  window.addEventListener('focus', onWindowFocus)
  document.addEventListener('fullscreenchange', onFullscreenChange)
  document.addEventListener('webkitfullscreenchange', onFullscreenChange)
  document.addEventListener('mozfullscreenchange', onFullscreenChange)
  window.addEventListener('resize', onResize)
  window.addEventListener('keydown', onKeyDown)
  updateFullscreenState()

  // Local second countdown
  timerInterval = setInterval(() => {
    if (remainingSeconds.value > 0) {
      remainingSeconds.value -= 1
      if (remainingSeconds.value === 0) {
        fetchRoomData()
      }
    }
  }, 1000)

  // Poll state every 1.5 seconds
  pollInterval = setInterval(() => {
    fetchRoomData()
  }, 1500)
})

onBeforeUnmount(() => {
  clearInterval(timerInterval)
  clearInterval(pollInterval)
  clearTimeout(screenLeaveTimer)
  clearTimeout(pendingLeaveTimer)
  clearTimeout(fullscreenTransitionTimer)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  window.removeEventListener('blur', onWindowBlur)
  window.removeEventListener('focus', onWindowFocus)
  document.removeEventListener('fullscreenchange', onFullscreenChange)
  document.removeEventListener('webkitfullscreenchange', onFullscreenChange)
  document.removeEventListener('mozfullscreenchange', onFullscreenChange)
  window.removeEventListener('resize', onResize)
  window.removeEventListener('keydown', onKeyDown)
  document.removeEventListener('mousemove', onResizerMouseMove)
  document.removeEventListener('mouseup', onResizerMouseUp)

  if (checkIsFullscreen()) {
    try {
      const doc = document as any
      if (doc.exitFullscreen) doc.exitFullscreen()
      else if (doc.webkitExitFullscreen) doc.webkitExitFullscreen()
    } catch {}
  }
})
</script>

<template>
  <div ref="battleRoomRef" class="battle-room-wrapper" :class="{ 'is-fullscreen': isFullscreen }">
    <!-- 顶部对决仪表条 (VS Bar) -->
    <header class="vs-bar">
      <!-- 我方选手信息 -->
      <div class="player-panel me-panel">
        <img :src="me?.avatar_url || staticUrl('/static/uploads/avatars/default.png')" class="vs-avatar" alt="avatar" />
        <div class="vs-info">
          <div class="vs-name">
            <router-link v-if="me?.user_number" :to="`/user/${me.user_number}`" class="vs-name-link" :style="{ color: userNameColor(me) }">{{ me?.username }}</router-link>
            <span v-else :style="{ color: userNameColor(me) }">{{ me?.username }}</span>
            (我)
          </div>
          <div class="vs-tier" :style="{ color: tierColorMap[me?.tier || 'bronze'] }">
            <i :class="['fa-solid', tierIconMap[me?.tier || 'bronze']]"></i>
            {{ me?.tier_name }} {{ me?.sub_tier_roman }}
          </div>
        </div>
        <div class="vs-status" :class="me?.status">
          <span v-if="me?.status === 'accepted'" class="status-badge status-ac">
            <i class="fa-solid fa-circle-check"></i> 已通过 AC
          </span>
          <span v-else-if="me?.status === 'submitted'" class="status-badge status-sub">
            <i class="fa-solid fa-spinner fa-spin"></i> 评测中
          </span>
          <span v-else-if="me?.status === 'surrendered'" class="status-badge status-surr">
            <i class="fa-solid fa-flag"></i> 已认输
          </span>
          <span v-else class="status-badge status-coding">
            <i class="fa-solid fa-code"></i> 编写中
          </span>
        </div>
      </div>

      <!-- 中间 VS 与倒计时 -->
      <div class="vs-center">
        <div class="vs-title-tag">
          {{ room?.mode === 'ranked' ? '排位天梯 1v1' : '自由对战 1v1' }}
        </div>
        <div class="vs-clock" :class="{ 'clock-warning': remainingSeconds <= 300 }">
          <i class="fa-solid fa-stopwatch"></i>
          {{ formatTimer(remainingSeconds) }}
        </div>
        <div class="vs-actions">
          <button
            type="button"
            class="btn-fullscreen-toggle"
            :title="isFullscreen ? '退出全屏 (Esc)' : '全屏专注对战 (防干扰)'"
            @click="toggleFullscreen"
          >
            <i class="fa-solid" :class="isFullscreen ? 'fa-compress' : 'fa-expand'"></i>
            {{ isFullscreen ? '退出全屏' : '全屏对战' }}
          </button>
          <button
            v-if="!isFinished"
            type="button"
            class="btn-surrender"
            title="认输放弃"
            @click="surrender"
          >
            <i class="fa-solid fa-flag"></i> 认输
          </button>
        </div>
      </div>

      <!-- 对手选手信息 -->
      <div class="player-panel opp-panel">
        <div class="vs-status" :class="opponent?.status">
          <span v-if="opponent?.status === 'accepted'" class="status-badge status-ac">
            <i class="fa-solid fa-circle-check"></i> 已通过 AC
          </span>
          <span v-else-if="opponent?.status === 'submitted'" class="status-badge status-sub">
            <i class="fa-solid fa-spinner fa-spin"></i> 评测中
          </span>
          <span v-else-if="opponent?.status === 'surrendered'" class="status-badge status-surr">
            <i class="fa-solid fa-flag"></i> 已认输
          </span>
          <span v-else class="status-badge status-coding">
            <i class="fa-solid fa-code"></i> 编写中
          </span>
        </div>
        <div class="vs-info" style="text-align: right;">
          <div class="vs-name">
            <router-link v-if="opponent?.user_number" :to="`/user/${opponent.user_number}`" class="vs-name-link" :style="{ color: userNameColor(opponent) }">{{ opponent?.username }}</router-link>
            <span v-else :style="{ color: userNameColor(opponent) }">{{ opponent?.username }}</span>
          </div>
          <div class="vs-tier" :style="{ color: tierColorMap[opponent?.tier || 'bronze'] }">
            <i :class="['fa-solid', tierIconMap[opponent?.tier || 'bronze']]"></i>
            {{ opponent?.tier_name }} {{ opponent?.sub_tier_roman }}
          </div>
        </div>
        <img :src="opponent?.avatar_url || staticUrl('/static/uploads/avatars/default.png')" class="vs-avatar" alt="avatar" />
      </div>
    </header>

    <!-- 主体左右分栏 -->
    <main class="battle-main-layout">
      <!-- 左栏：题目详情 -->
      <section class="problem-pane">
        <div class="problem-header">
          <div class="problem-title-row">
            <h2>{{ room?.problem.code }} {{ room?.problem.title }}</h2>
            <span
              class="diff-tag"
              :style="{ backgroundColor: `${difficultyColor(room?.problem.difficulty || '')}22`, color: difficultyColor(room?.problem.difficulty || '') }"
            >
              {{ room?.problem.difficulty }}
            </span>
          </div>

          <div class="problem-limits">
            <span><i class="fa-solid fa-clock"></i> 时间限制：{{ room?.problem.time_limit }} ms</span>
            <span><i class="fa-solid fa-memory"></i> 内存限制：{{ room?.problem.memory_limit }} MB</span>
          </div>
        </div>

        <div class="problem-body">
          <div v-if="room?.problem.background" class="content-block">
            <h3>题目背景</h3>
            <div class="md-content" v-html="renderRichText(room?.problem.background)"></div>
          </div>

          <div class="content-block">
            <h3>题目描述</h3>
            <div class="md-content" v-html="renderRichText(room?.problem.description || '')"></div>
          </div>

          <div v-if="room?.problem.input_format" class="content-block">
            <h3>输入格式</h3>
            <div class="md-content" v-html="renderRichText(room?.problem.input_format)"></div>
          </div>

          <div v-if="room?.problem.output_format" class="content-block">
            <h3>输出格式</h3>
            <div class="md-content" v-html="renderRichText(room?.problem.output_format)"></div>
          </div>

          <!-- 样例 -->
          <div v-if="room?.problem.samples && room.problem.samples.length > 0" class="samples-section">
            <h3>输入输出样例</h3>
            <div v-for="(sample, idx) in room.problem.samples" :key="idx" class="sample-box">
              <div class="sample-col">
                <div class="sample-label">
                  <span>样例输入 #{{ idx + 1 }}</span>
                  <div class="sample-actions">
                    <button
                      type="button"
                      class="btn-sample-fill"
                      title="填入自测输入并打开控制台"
                      @click="fillSample(sample, idx + 1)"
                    >
                      <i class="fa-solid fa-arrow-right-to-bracket"></i> 填入自测
                    </button>
                    <button type="button" class="copy-btn" @click="copyText(sample.input)">复制</button>
                  </div>
                </div>
                <pre class="sample-code">{{ sample.input }}</pre>
              </div>
              <div class="sample-col">
                <div class="sample-label">
                  <span>样例输出 #{{ idx + 1 }}</span>
                  <button type="button" class="copy-btn" @click="copyText(sample.output)">复制</button>
                </div>
                <pre class="sample-code">{{ sample.output }}</pre>
              </div>
            </div>
          </div>

          <div v-if="room?.problem.hint" class="content-block">
            <h3>说明/提示</h3>
            <div class="md-content" v-html="renderRichText(room?.problem.hint)"></div>
          </div>
        </div>
      </section>

      <!-- 右栏：代码编辑与提交评测 -->
      <section class="editor-pane">
        <div class="editor-toolbar">
          <div class="lang-selector">
            <label for="lang-select">编程语言：</label>
            <select id="lang-select" v-model="selectedLang" @change="onLanguageChange">
              <option value="cpp">C++ (G++ 11)</option>
              <option value="c">C (GCC 11)</option>
              <option value="python3">Python 3</option>
            </select>
          </div>

          <div class="rule-hint">
            <span class="rule-item rule-ac">
              <i class="fa-solid fa-bolt"></i> 谁先 AC 谁获胜！
            </span>
            <span class="rule-item rule-no-paste" title="本模式禁止直接粘贴代码，请手动输入！">
              <i class="fa-solid fa-ban"></i> 禁止粘贴
            </span>
            <span
              class="rule-item"
              :class="screenSwitchCount === 0 ? 'rule-screen-safe' : 'rule-screen-warn'"
              :title="screenSwitchCount === 0 ? '防切屏检测已开启：第1次警告，第2次或离开超15秒直接判负' : '已切屏违规1次！再次切屏或单次离开超15秒直接判负！'"
            >
              <i class="fa-solid" :class="screenSwitchCount === 0 ? 'fa-eye' : 'fa-triangle-exclamation'"></i>
              切屏检测: {{ screenSwitchCount }}/2{{ screenSwitchCount === 1 ? ' (再切直接输)' : '' }}
            </span>
            <button
              type="button"
              class="btn-editor-fullscreen"
              :title="isFullscreen ? '退出全屏 (Esc)' : '进入全屏专注对战'"
              @click="toggleFullscreen"
            >
              <i class="fa-solid" :class="isFullscreen ? 'fa-compress' : 'fa-expand'"></i>
              <span>{{ isFullscreen ? '退出全屏' : '全屏模式' }}</span>
            </button>
          </div>
        </div>

        <div class="editor-container">
          <CodeEditor
            v-model="code"
            :language="selectedLang === 'python3' ? 'python' : selectedLang"
            height="100%"
            :disable-paste="true"
            paste-blocked-message="本模式禁止直接粘贴代码，请手动输入！"
            @paste-blocked="onBattlePasteBlocked"
          />
        </div>

        <!-- 在线自测控制台 (Online IDE Console) -->
        <div
          v-show="showTestPanel"
          class="test-console-panel"
          :style="{ height: `${testPanelHeight}px` }"
        >
          <!-- 拖拽调节高度条 -->
          <div
            class="test-console-resizer"
            title="拖拽调节自测面板高度"
            @mousedown="onResizerMouseDown"
          >
            <div class="resizer-bar"></div>
          </div>

          <!-- 控制台顶栏 -->
          <div class="test-console-header">
            <div class="test-console-tabs">
              <button
                type="button"
                class="test-tab-btn"
                :class="{ active: testActiveTab === 'input' }"
                @click="testActiveTab = 'input'"
              >
                <i class="fa-solid fa-keyboard"></i>
                <span>自测输入</span>
                <span v-if="sampleMatchedIndex" class="sample-pill">
                  样例 #{{ sampleMatchedIndex }}
                </span>
              </button>
              <button
                type="button"
                class="test-tab-btn"
                :class="{ active: testActiveTab === 'output' }"
                @click="testActiveTab = 'output'"
              >
                <i class="fa-solid fa-terminal"></i>
                <span>运行结果</span>
                <span
                  v-if="testResult"
                  class="result-indicator-dot"
                  :class="testResult.status === 'ok' ? (isSampleVerdict === 'WA' ? 'dot-wa' : 'dot-ok') : 'dot-err'"
                ></span>
              </button>
            </div>

            <div class="test-console-actions">
              <!-- 快速填充样例 -->
              <div v-if="room?.problem.samples && room.problem.samples.length > 0" class="quick-samples">
                <span class="quick-label">填入样例:</span>
                <button
                  v-for="(s, sIdx) in room.problem.samples"
                  :key="sIdx"
                  type="button"
                  class="btn-quick-sample"
                  :class="{ selected: sampleMatchedIndex === sIdx + 1 }"
                  :title="`填入样例 #${sIdx + 1}`"
                  @click="fillSample(s, sIdx + 1)"
                >
                  #{{ sIdx + 1 }}
                </button>
              </div>

              <button
                v-if="testActiveTab === 'input' && testInput"
                type="button"
                class="btn-console-clear"
                title="清空自测输入"
                @click="testInput = ''"
              >
                <i class="fa-solid fa-trash-can"></i> 清空
              </button>

              <button
                type="button"
                class="btn-console-close"
                title="收起控制台"
                @click="showTestPanel = false"
              >
                <i class="fa-solid fa-xmark"></i>
              </button>
            </div>
          </div>

          <!-- 控制台主体 -->
          <div class="test-console-body">
            <!-- 输入 Tab -->
            <div v-show="testActiveTab === 'input'" class="test-tab-content content-input">
              <textarea
                v-model="testInput"
                class="test-input-textarea"
                placeholder="在此输入自测数据（按回车换行，或点击上方样例编号一键填充）..."
                spellcheck="false"
              ></textarea>
            </div>

            <!-- 运行结果 Tab -->
            <div v-show="testActiveTab === 'output'" class="test-tab-content content-output">
              <div v-if="testRunning" class="test-loading-state">
                <i class="fa-solid fa-spinner fa-spin test-spinner"></i>
                <span>正在评测沙箱中编译并执行代码...</span>
              </div>

              <div v-else-if="testRunError" class="test-error-banner">
                <i class="fa-solid fa-circle-exclamation"></i>
                <span>{{ testRunError }}</span>
              </div>

              <div v-else-if="testResult" class="test-result-view">
                <!-- 状态与耗时/内存指标 -->
                <div class="test-result-meta">
                  <div class="test-verdict-badge" :class="`badge-${testResult.status}`">
                    <template v-if="testResult.status === 'ok'">
                      <span v-if="isSampleVerdict === 'AC'" class="text-sample-ac">
                        <i class="fa-solid fa-circle-check"></i> 样例对比: AC (答案正确)
                      </span>
                      <span v-else-if="isSampleVerdict === 'WA'" class="text-sample-wa">
                        <i class="fa-solid fa-circle-xmark"></i> 样例对比: WA (与样例输出不符)
                      </span>
                      <span v-else class="text-sample-ok">
                        <i class="fa-solid fa-circle-check"></i> 运行成功
                      </span>
                    </template>
                    <template v-else-if="testResult.status === 'compile_error'">
                      <i class="fa-solid fa-triangle-exclamation"></i> 编译错误 Compile Error
                    </template>
                    <template v-else>
                      <i class="fa-solid fa-circle-xmark"></i> {{ STATUS_LABELS[testResult.status] || testResult.status }}
                    </template>
                  </div>

                  <div class="test-metrics">
                    <span v-if="testResult.time_ms !== null && testResult.time_ms !== undefined">
                      <i class="fa-regular fa-clock"></i> 耗时: <strong>{{ testResult.time_ms }} ms</strong>
                    </span>
                    <span v-if="testResult.memory_kb !== null && testResult.memory_kb !== undefined">
                      <i class="fa-solid fa-memory"></i> 内存: <strong>{{ Math.round((testResult.memory_kb / 1024) * 10) / 10 }} MB</strong>
                    </span>
                  </div>
                </div>

                <!-- 输出区域 -->
                <div class="test-output-scroll">
                  <!-- 编译报错 -->
                  <div v-if="testResult.status === 'compile_error'" class="ce-box">
                    <div class="output-sub-title">编译器输出:</div>
                    <pre class="output-pre text-ce">{{ testResult.stderr || '编译失败' }}</pre>
                  </div>

                  <div v-else>
                    <!-- WA 时的输出对比 -->
                    <div v-if="isSampleVerdict === 'WA' && sampleExpected !== null" class="comparison-block">
                      <div class="comp-col actual-col">
                        <div class="comp-title">程序实际输出:</div>
                        <pre class="output-pre actual-pre">{{ testResult.stdout || '（无输出）' }}</pre>
                      </div>
                      <div class="comp-col expected-col">
                        <div class="comp-title">样例期望输出:</div>
                        <pre class="output-pre expected-pre">{{ sampleExpected }}</pre>
                      </div>
                    </div>

                    <!-- 正常标准输出 -->
                    <div v-else class="stdout-box">
                      <div class="output-sub-title">标准输出 (stdout):</div>
                      <pre class="output-pre">{{ testResult.stdout || '（无输出）' }}</pre>
                    </div>

                    <!-- 运行时 stderr -->
                    <div v-if="testResult.stderr" class="stderr-box">
                      <div class="output-sub-title">错误与警告 (stderr):</div>
                      <pre class="output-pre text-stderr">{{ testResult.stderr }}</pre>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 尚未自测空状态 -->
              <div v-else class="test-empty-state">
                <i class="fa-solid fa-flask"></i>
                <span>尚未执行自测。在「自测输入」填入数据后，点击右下方「运行自测」按钮（或快捷键 Ctrl+Enter）查看运行结果。</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 提交与控制栏 -->
        <div class="editor-action-bar">
          <div class="sub-status-info">
            <button
              type="button"
              class="btn-toggle-console"
              :class="{ active: showTestPanel }"
              title="展开/收起在线自测控制台"
              @click="showTestPanel = !showTestPanel"
            >
              <i class="fa-solid fa-terminal"></i>
              <span>自测控制台</span>
              <span
                v-if="testResult"
                class="console-status-dot"
                :class="testResult.status === 'ok' ? (isSampleVerdict === 'WA' ? 'dot-wa' : 'dot-ok') : 'dot-err'"
              ></span>
              <i class="fa-solid" :class="showTestPanel ? 'fa-chevron-down' : 'fa-chevron-up'"></i>
            </button>

            <span v-if="room?.my_submission" class="my-sub-info">
              最新提交：
              <strong :class="`text-${room.my_submission.status}`">
                {{ room.my_submission.status.toUpperCase() }}
              </strong>
              <span v-if="room.my_submission.time_used"> ({{ room.my_submission.time_used }} ms)</span>
            </span>
            <span v-if="pasteAttempts > 0" class="paste-blocked-tag">
              <i class="fa-solid fa-shield-halved"></i> 已拦截 {{ pasteAttempts }} 次粘贴
            </span>
          </div>

          <div class="action-buttons-group">
            <button
              type="button"
              class="btn-test-run"
              :disabled="testRunning || !code.trim() || isFinished"
              title="在评测沙箱中运行当前代码与自测输入（快捷键 Ctrl+Enter）"
              @click="runSelfTest"
            >
              <i v-if="testRunning" class="fa-solid fa-spinner fa-spin"></i>
              <i v-else class="fa-solid fa-play"></i>
              <span>{{ testRunning ? '自测运行中...' : '运行自测' }}</span>
              <span class="btn-shortcut-hint">Ctrl+↵</span>
            </button>

            <button
              type="button"
              class="btn-submit"
              :disabled="submitting || isFinished"
              @click="submitCode"
            >
              <i v-if="submitting" class="fa-solid fa-spinner fa-spin"></i>
              <i v-else class="fa-solid fa-paper-plane"></i>
              {{ submitting ? '评测中...' : '提交代码并抢 AC' }}
            </button>
          </div>
        </div>
      </section>
    </main>

    <!-- 结算弹窗 (Victory / Defeat / Draw) -->
    <div v-if="showResultModal" class="result-modal-overlay">
      <div class="result-modal-card" :class="[`result-card-${myResult}`]">
        <div class="result-icon-wrap">
          <i v-if="myResult === 'win'" class="fa-solid fa-trophy modal-icon-win"></i>
          <i v-else-if="myResult === 'loss'" class="fa-solid fa-heart-crack modal-icon-loss"></i>
          <i v-else class="fa-solid fa-handshake modal-icon-draw"></i>
        </div>

        <div class="result-title">
          <span v-if="myResult === 'win'">胜利 VICTORY</span>
          <span v-else-if="myResult === 'loss'">战败 DEFEAT</span>
          <span v-else>平局 DRAW</span>
        </div>

        <div class="result-subtitle">
          <span v-if="room?.settlement?.finish_reason === 'screen_switch_timeout'">
            {{ myResult === 'win' ? '对手因切屏离开超过 15 秒被直接判定战败，恭喜你获得胜利！' : '由于在对战中切屏离开超过 15 秒，触发防作弊规则被直接判定战败！' }}
          </span>
          <span v-else-if="room?.settlement?.finish_reason === 'screen_switch_second'">
            {{ myResult === 'win' ? '对手因累计切屏达到 2 次被直接判定战败，恭喜你获得胜利！' : '由于在对战中累计切屏达到 2 次，触发防作弊规则被直接判定战败！' }}
          </span>
          <span v-else-if="room?.settlement?.finish_reason === 'surrender'">
            {{ myResult === 'win' ? '对手主动认输投降，恭喜你获得胜利！' : '你已主动认输，本局判定战败。' }}
          </span>
          <span v-else-if="myResult === 'win'">你在速度与严密性上胜出一筹，率先 AC 通过了题目！</span>
          <span v-else-if="myResult === 'loss'">对手率先攻克了题目，再接再厉，总结经验下把赢回来！</span>
          <span v-else>对决时间已到，双方势均力敌，握手言和！</span>
        </div>

        <!-- 奖励与积分变动详情 -->
        <div class="settlement-details" v-if="mySettlement">
          <div class="settle-item">
            <span class="s-label">经验值奖励</span>
            <span class="s-val text-exp">+{{ mySettlement.xp_gain }} EXP</span>
          </div>

          <div v-if="room?.mode === 'ranked' && mySettlement.rank" class="settle-item">
            <span class="s-label">天梯胜点</span>
            <span
              class="s-val"
              :class="{ 'text-win': mySettlement.rank.points_delta > 0, 'text-loss': mySettlement.rank.points_delta < 0 }"
            >
              {{ mySettlement.rank.points_delta > 0 ? `+${mySettlement.rank.points_delta}` : mySettlement.rank.points_delta }} LP
            </span>
          </div>

          <div v-if="mySettlement.rank?.promoted" class="promotion-alert">
            <i class="fa-solid fa-crown"></i> 恭喜晋级！当前段位：{{ mySettlement.rank.new_tier }} {{ mySettlement.rank.new_sub_tier }}
          </div>
        </div>

        <div class="modal-buttons">
          <button type="button" class="btn-primary" @click="router.push('/arena')">
            <i class="fa-solid fa-rotate-left"></i> 返回对战大厅
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.battle-room-wrapper {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 64px);
  overflow: hidden;
  background: var(--surface-plain);
}

.battle-room-wrapper.is-fullscreen {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  width: 100vw;
  height: 100vh;
  z-index: 999;
  background: var(--surface-plain);
}

/* VS 仪表条 */
.vs-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 24px;
  background: var(--surface-plain);
  border-bottom: 2px solid var(--border-color);
  box-shadow: var(--shadow-card);
  flex-shrink: 0;
}

.player-panel {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 320px;
}

.opp-panel {
  justify-content: flex-end;
}

.vs-avatar {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid var(--border-color);
}

.vs-info {
  display: flex;
  flex-direction: column;
}

.vs-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-strong);
}

.vs-name-link {
  text-decoration: none;
}

.vs-name-link:hover {
  text-decoration: underline;
}

.vs-tier {
  font-size: 12px;
  font-weight: 600;
  margin-top: 2px;
}

.status-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 12px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.status-coding {
  background: var(--bg-subtle);
  color: var(--text-sub);
}

.status-sub {
  background: #feebc8;
  color: #c05621;
}

.status-ac {
  background: #c6f6d5;
  color: #22543d;
}

.status-surr {
  background: #fed7d7;
  color: #9b2c2c;
}

.vs-center {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.vs-title-tag {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.5px;
  color: var(--text-sub);
  text-transform: uppercase;
  margin-bottom: 2px;
}

.vs-clock {
  font-size: 24px;
  font-weight: 800;
  color: #2b6cb0;
  font-family: monospace;
  display: flex;
  align-items: center;
  gap: 6px;
}

.clock-warning {
  color: #e53e3e;
  animation: blink 1s infinite;
}

@keyframes blink {
  50% { opacity: 0.5; }
}

.vs-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 4px;
}

.btn-fullscreen-toggle {
  background: var(--surface-plain);
  border: 1px solid var(--border-color);
  font-size: 11px;
  color: var(--text-main);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 4px;
  transition: all 0.2s;
  font-weight: 600;
}

.btn-fullscreen-toggle:hover {
  color: #2b6cb0;
  border-color: #bee3f8;
  background: #ebf8ff;
}

.btn-surrender {
  background: none;
  border: none;
  font-size: 11px;
  color: #e53e3e;
  cursor: pointer;
  text-decoration: underline;
  padding: 2px 4px;
}

/* 主体分栏 */
.battle-main-layout {
  display: grid;
  grid-template-columns: 1fr 1fr;
  flex: 1;
  overflow: hidden;
}

/* 左侧题目 */
.problem-pane {
  background: var(--surface-plain);
  border-right: 1px solid var(--border-color);
  overflow-y: auto;
  padding: 24px;
}

.problem-header {
  border-bottom: 1px solid var(--border-color);
  padding-bottom: 16px;
  margin-bottom: 20px;
}

.problem-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.problem-title-row h2 {
  font-size: 20px;
  margin: 0;
  color: var(--text-strong);
}

.diff-tag {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 700;
}

.problem-limits {
  display: flex;
  gap: 20px;
  color: var(--text-sub);
  font-size: 13px;
}

.content-block {
  margin-bottom: 24px;
}

.content-block h3, .samples-section h3 {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-strong);
  margin-bottom: 8px;
  border-left: 3px solid #3182ce;
  padding-left: 8px;
}

.sample-box {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}

.sample-col {
  background: var(--surface-plain);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  overflow: hidden;
}

.sample-label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 12px;
  background: var(--bg-subtle);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-main);
}

.copy-btn {
  background: none;
  border: none;
  color: #3182ce;
  font-size: 11px;
  cursor: pointer;
}

.sample-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-sample-fill {
  background: #ebf8ff;
  border: 1px solid #bee3f8;
  color: #2b6cb0;
  font-size: 11px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 4px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: all 0.15s ease;
}

.btn-sample-fill:hover {
  background: #bee3f8;
  color: #2c5282;
}

.sample-code {
  padding: 10px 12px;
  margin: 0;
  font-size: 13px;
  font-family: monospace;
  white-space: pre-wrap;
  word-break: break-all;
}

/* 右侧编辑器 */
.editor-pane {
  display: flex;
  flex-direction: column;
  background: #1e1e1e;
  overflow: hidden;
}

.editor-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  background: #252526;
  border-bottom: 1px solid #333333;
}

.lang-selector {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #cccccc;
  font-size: 13px;
}

.lang-selector select {
  background: #3c3c3c;
  color: #ffffff;
  border: 1px solid #555555;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 13px;
}

.rule-hint {
  display: flex;
  align-items: center;
  gap: 10px;
}

.rule-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 600;
}

.rule-ac {
  color: #d69e2e;
}

.rule-no-paste {
  color: #f87171;
  background: rgba(239, 68, 68, 0.14);
  border: 1px solid rgba(239, 68, 68, 0.35);
  padding: 3px 8px;
  border-radius: 4px;
}

.rule-screen-safe {
  color: #34d399;
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.3);
  padding: 3px 8px;
  border-radius: 4px;
}

.rule-screen-warn {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.2);
  border: 1px solid rgba(239, 68, 68, 0.5);
  padding: 3px 8px;
  border-radius: 4px;
  font-weight: 700;
  animation: pulse-warn 1.5s infinite;
}

@keyframes pulse-warn {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.65; }
}

.btn-editor-fullscreen {
  background: #374151;
  color: #e5e7eb;
  border: 1px solid #4b5563;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  transition: all 0.2s ease;
}

.btn-editor-fullscreen:hover {
  background: #4b5563;
  color: #ffffff;
  border-color: #6b7280;
}

.editor-container {
  flex: 1;
  overflow: hidden;
  position: relative;
}

.editor-action-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  background: #252526;
  border-top: 1px solid #333333;
}

.sub-status-info {
  display: flex;
  align-items: center;
  gap: 12px;
  color: #cccccc;
  font-size: 13px;
}

.paste-blocked-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 600;
  color: #fca5a5;
  background: rgba(239, 68, 68, 0.16);
  border: 1px solid rgba(239, 68, 68, 0.35);
  padding: 2px 9px;
  border-radius: 12px;
}

.text-accepted {
  color: #48bb78;
}

.text-wrong_answer, .text-runtime_error, .text-compile_error {
  color: #f56565;
}

.btn-submit {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 24px;
  background: #38a169;
  color: #ffffff;
  border: none;
  border-radius: 6px;
  font-weight: 700;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-submit:hover:not(:disabled) {
  background: #2f855a;
}

.btn-submit:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 自测控制台面板 (Online IDE Console) */
.test-console-panel {
  display: flex;
  flex-direction: column;
  background: #1e1e1e;
  border-top: 1px solid #333333;
  position: relative;
  flex-shrink: 0;
}

.test-console-resizer {
  height: 6px;
  cursor: ns-resize;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #252526;
  border-bottom: 1px solid #2d2d2d;
  user-select: none;
  transition: background 0.15s ease;
}

.test-console-resizer:hover {
  background: #3b82f6;
}

.resizer-bar {
  width: 36px;
  height: 2px;
  background: #555555;
  border-radius: 1px;
}

.test-console-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #252526;
  border-bottom: 1px solid #333333;
  padding: 0 12px;
  height: 38px;
  flex-shrink: 0;
}

.test-console-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  height: 100%;
}

.test-tab-btn {
  background: none;
  border: none;
  color: #8c8c8c;
  font-size: 12px;
  font-weight: 600;
  padding: 0 12px;
  height: 100%;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-bottom: 2px solid transparent;
  transition: all 0.15s;
}

.test-tab-btn:hover {
  color: #d4d4d4;
}

.test-tab-btn.active {
  color: #ffffff;
  border-bottom-color: #38bdf8;
  background: rgba(255, 255, 255, 0.04);
}

.sample-pill {
  font-size: 10px;
  background: #0284c7;
  color: #ffffff;
  padding: 1px 6px;
  border-radius: 10px;
  font-weight: 700;
}

.result-indicator-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  display: inline-block;
}

.result-indicator-dot.dot-ok {
  background: #48bb78;
  box-shadow: 0 0 6px rgba(72, 187, 120, 0.6);
}

.result-indicator-dot.dot-wa,
.result-indicator-dot.dot-err {
  background: #f56565;
  box-shadow: 0 0 6px rgba(245, 101, 101, 0.6);
}

.test-console-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.quick-samples {
  display: flex;
  align-items: center;
  gap: 4px;
}

.quick-label {
  font-size: 11px;
  color: #8c8c8c;
  margin-right: 2px;
}

.btn-quick-sample {
  background: #333333;
  color: #cccccc;
  border: 1px solid #444444;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-quick-sample:hover {
  background: #444444;
  color: #ffffff;
  border-color: #666666;
}

.btn-quick-sample.selected {
  background: #0284c7;
  color: #ffffff;
  border-color: #38bdf8;
}

.btn-console-clear, .btn-console-close {
  background: none;
  border: none;
  color: #8c8c8c;
  font-size: 12px;
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: all 0.15s;
}

.btn-console-clear:hover, .btn-console-close:hover {
  color: #ffffff;
  background: #333333;
}

.test-console-body {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.test-tab-content {
  flex: 1;
  height: 100%;
  overflow: hidden;
}

.content-input {
  height: 100%;
}

.test-input-textarea {
  width: 100%;
  height: 100%;
  box-sizing: border-box;
  background: #1e1e1e;
  color: #e2e8f0;
  font-family: 'JetBrains Mono', 'Fira Code', Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
  line-height: 1.6;
  border: none;
  outline: none;
  padding: 10px 14px;
  resize: none;
}

.test-input-textarea::placeholder {
  color: #555555;
  font-style: italic;
}

.content-output {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  height: 100%;
}

.test-loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  height: 100%;
  color: #38bdf8;
  font-size: 13px;
  font-weight: 500;
}

.test-spinner {
  font-size: 18px;
}

.test-error-banner {
  padding: 12px 16px;
  background: rgba(239, 68, 68, 0.12);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #f87171;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 10px;
  border-radius: 6px;
}

.test-empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 8px;
  height: 100%;
  color: #666666;
  font-size: 12px;
  padding: 20px;
  text-align: center;
}

.test-empty-state i {
  font-size: 24px;
  color: #444444;
}

.test-result-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.test-result-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 14px;
  background: #252526;
  border-bottom: 1px solid #2d2d2d;
  font-size: 12px;
  flex-shrink: 0;
}

.test-verdict-badge {
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.badge-ok .text-sample-ac, .badge-ok .text-sample-ok {
  color: #48bb78;
}

.badge-ok .text-sample-wa {
  color: #f56565;
}

.badge-compile_error {
  color: #f56565;
}

.badge-runtime_error, .badge-time_limit_exceeded, .badge-memory_limit_exceeded {
  color: #ed8936;
}

.test-metrics {
  display: flex;
  align-items: center;
  gap: 14px;
  color: #999999;
  font-size: 11px;
}

.test-metrics strong {
  color: #e2e8f0;
}

.test-output-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 10px 14px;
}

.output-sub-title {
  font-size: 11px;
  font-weight: 600;
  color: #8c8c8c;
  margin-bottom: 4px;
}

.output-pre {
  margin: 0;
  font-family: 'JetBrains Mono', 'Fira Code', Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
  line-height: 1.5;
  color: #d4d4d4;
  white-space: pre-wrap;
  word-break: break-all;
  background: #141414;
  border: 1px solid #2a2a2a;
  border-radius: 4px;
  padding: 8px 10px;
}

.text-ce {
  color: #f87171;
  background: rgba(239, 68, 68, 0.06);
  border-color: rgba(239, 68, 68, 0.2);
}

.text-stderr {
  color: #fb923c;
  background: rgba(249, 115, 22, 0.06);
  border-color: rgba(249, 115, 22, 0.2);
  margin-top: 8px;
}

.comparison-block {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.actual-col .comp-title {
  color: #f87171;
  font-size: 11px;
  font-weight: 700;
  margin-bottom: 4px;
}

.expected-col .comp-title {
  color: #34d399;
  font-size: 11px;
  font-weight: 700;
  margin-bottom: 4px;
}

.actual-pre {
  border-color: rgba(239, 68, 68, 0.3);
  background: rgba(239, 68, 68, 0.04);
}

.expected-pre {
  border-color: rgba(16, 185, 129, 0.3);
  background: rgba(16, 185, 129, 0.04);
}

/* 控制栏中的按钮与状态 */
.btn-toggle-console {
  background: #333333;
  color: #d4d4d4;
  border: 1px solid #444444;
  font-size: 12px;
  font-weight: 600;
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: all 0.15s ease;
}

.btn-toggle-console:hover {
  background: #3c3c3c;
  color: #ffffff;
  border-color: #555555;
}

.btn-toggle-console.active {
  background: #1e3a5f;
  color: #38bdf8;
  border-color: #0284c7;
}

.console-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  display: inline-block;
}

.console-status-dot.dot-ok {
  background: #48bb78;
}

.console-status-dot.dot-wa,
.console-status-dot.dot-err {
  background: #f56565;
}

.my-sub-info {
  color: #cccccc;
  font-size: 13px;
}

.action-buttons-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.btn-test-run {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  background: #0284c7;
  color: #ffffff;
  border: none;
  border-radius: 6px;
  font-weight: 700;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-test-run:hover:not(:disabled) {
  background: #0369a1;
}

.btn-test-run:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-shortcut-hint {
  font-size: 11px;
  font-weight: 500;
  opacity: 0.75;
  background: rgba(0, 0, 0, 0.2);
  padding: 1px 5px;
  border-radius: 3px;
}

/* 结算弹窗 */
.result-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.result-modal-card {
  background: var(--surface-plain);
  border-radius: 16px;
  padding: 36px 48px;
  text-align: center;
  min-width: 380px;
  box-shadow: 0 24px 48px rgba(0, 0, 0, 0.3);
  animation: popIn 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
}

@keyframes popIn {
  from { transform: scale(0.8); opacity: 0; }
  to { transform: scale(1); opacity: 1; }
}

.result-icon-wrap {
  font-size: 64px;
  margin-bottom: 12px;
}

.modal-icon-win {
  color: #d69e2e;
  filter: drop-shadow(0 4px 12px rgba(214, 158, 46, 0.4));
}

.modal-icon-loss {
  color: #e53e3e;
}

.modal-icon-draw {
  color: var(--text-sub);
}

.result-title {
  font-size: 28px;
  font-weight: 900;
  letter-spacing: 1px;
  margin-bottom: 8px;
}

.result-card-win .result-title {
  color: #38a169;
}

.result-card-loss .result-title {
  color: #e53e3e;
}

.result-subtitle {
  font-size: 13px;
  color: var(--text-sub);
  margin-bottom: 24px;
}

.settlement-details {
  background: var(--surface-plain);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 24px;
}

.settle-item {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 14px;
}

.settle-item:last-child {
  margin-bottom: 0;
}

.s-label {
  color: var(--text-sub);
}

.s-val {
  font-weight: 700;
}

.text-exp {
  color: #805ad5;
}

.text-win {
  color: #38a169;
}

.text-loss {
  color: #e53e3e;
}

.promotion-alert {
  margin-top: 10px;
  padding: 8px;
  background: #fefcbf;
  color: #b7791f;
  font-weight: 700;
  border-radius: 6px;
  font-size: 13px;
}

.modal-buttons {
  display: flex;
  justify-content: center;
}

.btn-primary {
  padding: 10px 24px;
  background: #3182ce;
  color: #ffffff;
  border: none;
  border-radius: 6px;
  font-weight: 700;
  font-size: 14px;
  cursor: pointer;
}

.btn-primary:hover {
  background: #2b6cb0;
}
</style>
