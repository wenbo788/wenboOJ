import type { ProblemReviewStatus } from '@/types'

// 题目审核状态 → 中文文案 / 徽章底色 / 字色（题库列表、我的题目、详情页共用）
export const PROBLEM_REVIEW_META: Record<
  ProblemReviewStatus,
  { text: string; bg: string; color: string }
> = {
  draft: { text: '草稿', bg: '#f4f4f5', color: '#909399' },
  pending: { text: '待审核', bg: '#fff7e6', color: '#d48806' },
  approved: { text: '已通过', bg: '#f0f9eb', color: '#67c23a' },
  rejected: { text: '已驳回', bg: '#fef0f0', color: '#f56c6c' },
}

export function problemReviewMeta(status?: string | null) {
  return PROBLEM_REVIEW_META[(status as ProblemReviewStatus)] ?? PROBLEM_REVIEW_META.draft
}
