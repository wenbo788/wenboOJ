import { ref } from 'vue'

/** 沉浸做题草稿：退出或切换页面后再回来，代码与输入原样保留 */
export interface TestDraft {
  code: string
  language: string
  input: string
  /** 样例填充记下的样例：input = 填入的输入，expected = 样例输出（输入被改动后比较失效） */
  fill: { input: string; expected: string } | null
}

export const testDrafts = new Map<number, TestDraft>()

/** 样例填充信号：沉浸页已挂载时收到即同步最新草稿（跳转进页的场景靠 onMounted 兜底） */
export const fillSignal = ref(0)

export function getTestDraft(problemId: number): TestDraft {
  let d = testDrafts.get(problemId)
  if (!d) {
    d = { code: '', language: 'cpp', input: '', fill: null }
    testDrafts.set(problemId, d)
  }
  return d
}

/** 样例填充：写入样例输入与期望输出，并广播给已挂载的沉浸页 */
export function fillSampleToTest(problemId: number, input: string, expected: string): void {
  const d = getTestDraft(problemId)
  d.input = input
  d.fill = { input, expected }
  fillSignal.value++
}
