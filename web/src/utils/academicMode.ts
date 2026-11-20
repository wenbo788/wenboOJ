// 学术模式（个人设置里的自律开关）。
//
// 开启后：隐藏犇犇与灌水区，题目难度默认隐藏（可按题手动翻开，刷新即隐藏）。
//
// 这是用户自己的偏好，**不是权限**——服务端不据此拒绝任何请求，
// 所以各处只读这里一个口径，别各自去翻 authStore 字段，免得漏改一处
// 就出现「犇犇藏了但浮窗还在」这类半吊子状态。
import { computed, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'

export function useAcademicMode() {
  const authStore = useAuthStore()
  const academicMode = computed(() => authStore.currentUser?.academic_mode === true)
  return { academicMode }
}

// 「手动展开难度」：学术模式下难度默认收起，点一下只翻开**当前这道题**。
//
// 三点是有意为之，别顺手改回去：
//   1. 按题记账，没有「一键全部展开」——想按难度挑题就得一道一道点，
//      这恰好是学术模式要挡的事；
//   2. 只活在当前页面里，不写 localStorage——刷新即恢复隐藏。
//      记住展开等于给自己留个「以后都看得见」的后门，开关就白设了；
//   3. Set 是**每个调用方各自一份**，不是模块级单例：题库里翻开的那道题，
//      点进题面页不会继承（要跨页面记住就得提升成单例或塞进 store，
//      那等于把第 2 条的自律约束又拆了）。别把它改成共享状态。
export function useDifficultyReveal() {
  const { academicMode } = useAcademicMode()
  // 本组件自己的已翻开题号（题库列表按题目 id，题单按 problem_id）。刷新即清空。
  const revealedProblemIds = ref(new Set<number>())

  /** 这道题的难度此刻是否可见：没开学术模式则恒可见 */
  const isDifficultyVisible = (problemId: number) =>
    !academicMode.value || revealedProblemIds.value.has(problemId)

  /** 只翻开这一道题，不动别的题 */
  const revealDifficulty = (problemId: number) => {
    revealedProblemIds.value.add(problemId)
  }

  return { isDifficultyVisible, revealDifficulty }
}
