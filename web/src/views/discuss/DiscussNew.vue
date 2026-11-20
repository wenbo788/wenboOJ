<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import apiClient from '@/api/client'
import MarkdownSplitEditor from '@/components/MarkdownSplitEditor.vue'
import { canManageCommunity } from '@/utils/permissions'
import { useAcademicMode } from '@/utils/academicMode'

const router = useRouter()
const authStore = useAuthStore()
const isMuted = computed(() => authStore.currentUser?.can_speak === false)
const canManagePosts = computed(() => canManageCommunity(authStore.currentUser))

// 站务版仅秩序管理可发帖
const isForumDisabled = (key: string) => key === 'siteaffairs' && !canManagePosts.value

const { academicMode } = useAcademicMode()

const ALL_FORUMS = [
  { key: 'siteaffairs', name: '站务版', desc: '站点事务与公告讨论' },
  { key: 'problem', name: '题目总版', desc: '题目相关讨论' },
  { key: 'academics', name: '学术版', desc: '算法与学术交流' },
  { key: 'relevantaffairs', name: '灌水区', desc: '轻松闲聊' },
]

// 学术模式下灌水区不出现。注意：**只有模板在用它**（v-for 会自动解包，
// 不需要也不该写 .value）；脚本里要按 key 找版块请用 ALL_FORUMS，
// 那是「全部版块」的原始清单，不受开关影响。
const FORUMS = computed(() =>
  ALL_FORUMS.filter((f) => !(academicMode.value && f.key === 'relevantaffairs')),
)

const forum = ref('')
const title = ref('')
const content = ref('')
const submitting = ref(false)
const error = ref('')

// 关联题目：可选，关联后无需在标题里写题号
const problemKeyword = ref('')
const problemResults = ref<any[]>([])
const problemSearching = ref(false)
const selectedProblem = ref<any | null>(null)
let searchTimer: any = null

const searchProblems = () => {
  if (searchTimer) clearTimeout(searchTimer)
  if (!problemKeyword.value.trim()) {
    problemResults.value = []
    return
  }
  searchTimer = setTimeout(async () => {
    problemSearching.value = true
    try {
      const data: any = await apiClient.get('/api/problems', {
        params: { keyword: problemKeyword.value.trim(), page: 0, page_size: 10 }
      })
      problemResults.value = Array.isArray(data?.problems) ? data.problems : []
    } catch {
      problemResults.value = []
    } finally {
      problemSearching.value = false
    }
  }, 250)
}

const pickProblem = (p: any) => {
  selectedProblem.value = p
  problemKeyword.value = ''
  problemResults.value = []
}

const clearProblem = () => {
  selectedProblem.value = null
  problemKeyword.value = ''
  problemResults.value = []
}

const submit = async () => {
  error.value = ''
  if (isMuted.value) {
    error.value = '你已被禁言，无法发布帖子'
    return
  }
  if (isForumDisabled(forum.value)) {
    error.value = '站务版仅秩序管理可发帖'
    return
  }
  if (!forum.value) {
    error.value = '请选择版块'
    return
  }
  if (title.value.trim().length < 3) {
    error.value = '标题至少 3 个字符'
    return
  }
  if (!content.value.trim()) {
    error.value = '请填写正文内容'
    return
  }

  submitting.value = true
  try {
    const data: any = await apiClient.post('/api/forum/posts', {
      title: title.value.trim(),
      content: content.value.trim(),
      forum: forum.value,
      problem_id: selectedProblem.value?.id || null
    })
    router.push(`/discuss/${data.id}`)
  } catch (err: any) {
    error.value = err.response?.data?.detail || err.message || '发布失败'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="post-new-page">
    <div class="new-container">
      <h2 class="page-title">发布帖子</h2>
      <div v-if="isMuted" class="mute-tip"><i class="fa-solid fa-ban"></i> 你已被禁言，无法发布帖子，如有疑问请通过工单联系我们。</div>

      <div class="section-label">选择版块 <span class="required">*</span></div>
      <div class="forum-grid">
        <div
          v-for="f in FORUMS"
          :key="f.key"
          class="forum-card"
          :class="{ selected: forum === f.key, disabled: isForumDisabled(f.key) }"
          @click="!isForumDisabled(f.key) && (forum = f.key)"
        >
          <div class="forum-name">{{ f.name }}</div>
          <div class="forum-desc">{{ f.desc }}</div>
          <div v-if="isForumDisabled(f.key)" class="forum-lock"><i class="fa-solid fa-lock"></i> 仅秩序管理</div>
        </div>
      </div>

      <div class="section-label">
        关联题目
        <span class="hint-text">（可选）关联后无需在标题里写题号</span>
      </div>
      <div v-if="!selectedProblem" class="problem-search-wrap">
        <input
          v-model="problemKeyword"
          class="problem-search-input"
          placeholder="按题号或标题搜索题目，例如 P1001 或 数位 DP"
          @input="searchProblems"
        >
        <span v-if="problemSearching" class="search-hint">搜索中...</span>
        <div v-if="problemResults.length" class="problem-results">
          <div
            v-for="p in problemResults"
            :key="p.id"
            class="problem-item"
            @click="pickProblem(p)"
          >
            <span class="problem-num">{{ p.problem_number }}</span>
            <span class="problem-title">{{ p.title }}</span>
            <span v-if="p.difficulty" class="problem-diff">{{ p.difficulty }}</span>
          </div>
        </div>
      </div>
      <div v-else class="problem-selected">
        <span class="problem-num">{{ selectedProblem.problem_number }}</span>
        <span class="problem-title">{{ selectedProblem.title }}</span>
        <button type="button" class="clear-btn" @click="clearProblem">
          <i class="fa-solid fa-xmark"></i> 移除
        </button>
      </div>

      <div class="section-label">标题 <span class="required">*</span></div>
      <input
        v-model="title"
        class="title-input"
        placeholder="简要概括帖子主题（3-100 字）"
        maxlength="100"
      >

      <div class="section-label">正文 <span class="required">*</span></div>
      <MarkdownSplitEditor
        v-model="content"
        height="360px"
        placeholder="支持 Markdown：**粗体**、*斜体*、```代码块```、@提及 等"
      />

      <div v-if="error" class="error-tip">❌ {{ error }}</div>

      <div class="submit-bar">
        <button class="btn-submit" :disabled="submitting || isMuted" @click="submit">
          {{ submitting ? '发布中...' : '发布帖子' }}
        </button>
        <button class="btn-cancel" :disabled="submitting" @click="router.back()">取消</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.post-new-page {
  min-height: 100vh;
  line-height: 1.6;
}

.new-container {
  max-width: 760px;
  margin: 0 auto;
}

.page-title {
  font-size: 1.3rem;
  font-weight: 700;
  color: var(--text-strong);
  margin-bottom: 16px;
}

.section-label {
  font-weight: 700;
  font-size: 14px;
  color: var(--text-strong);
  margin: 18px 0 8px;
}

.required {
  color: var(--primary);
}

.hint-text {
  font-weight: 400;
  font-size: 12px;
  color: var(--text-sub);
  margin-left: 6px;
}

.problem-search-wrap {
  position: relative;
}

.problem-search-input {
  width: 100%;
  padding: 11px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  font-size: 14px;
  outline: none;
  box-sizing: border-box;
  transition: border-color 0.2s;
}

.problem-search-input:focus {
  border-color: var(--primary);
}

.search-hint {
  position: absolute;
  right: 14px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 12px;
  color: #a0aec0;
}

.problem-results {
  margin-top: 6px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: var(--surface-plain);
  max-height: 260px;
  overflow-y: auto;
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.06);
}

.problem-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  cursor: pointer;
  border-bottom: 1px solid #f1f1f4;
  transition: background 0.15s;
}

.problem-item:last-child {
  border-bottom: none;
}

.problem-item:hover {
  background: var(--surface-plain);
}

.problem-selected {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: color-mix(in srgb, var(--primary) 7%, transparent);
  border: 1px solid color-mix(in srgb, var(--primary) 35%, transparent);
  border-radius: 10px;
}

.problem-num {
  font-weight: 700;
  color: var(--primary);
  font-size: 14px;
  flex-shrink: 0;
}

.problem-title {
  flex: 1;
  min-width: 0;
  color: var(--text-strong);
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.problem-diff {
  font-size: 12px;
  color: var(--text-sub);
  flex-shrink: 0;
}

.clear-btn {
  background: none;
  border: none;
  color: #c0c8d0;
  font-size: 12px;
  cursor: pointer;
  flex-shrink: 0;
}

.clear-btn:hover {
  color: var(--primary);
}

.forum-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
}

.forum-card {
  background: var(--surface-plain);
  border: 2px solid #e2e8f0;
  border-radius: 12px;
  padding: 14px 12px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
}

.forum-card.disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.forum-lock {
  font-size: 11px;
color: light-dark(#b91c1c, #f87171);
  margin-top: 2px;
}

.forum-card:hover {
  border-color: var(--primary);
}

.forum-card.selected {
  border-color: var(--primary);
  background: color-mix(in srgb, var(--danger) 10%, transparent);
}

.forum-name {
  font-weight: 700;
  font-size: 14px;
  color: var(--text-strong);
  margin-bottom: 4px;
}

.forum-desc {
  font-size: 12px;
  color: var(--text-sub);
}

.title-input {
  width: 100%;
  padding: 11px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  font-size: 14px;
  outline: none;
  box-sizing: border-box;
  transition: border-color 0.2s;
}

.title-input:focus {
  border-color: var(--primary);
}

.content-input {
  width: 100%;
  padding: 12px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  font-size: 14px;
  font-family: inherit;
  resize: vertical;
  outline: none;
  box-sizing: border-box;
  transition: border-color 0.2s;
}

.content-input:focus {
  border-color: var(--primary);
}

.error-tip {
  margin-top: 14px;
  color: var(--primary);
  font-size: 13px;
}

.mute-tip {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border: 1px solid #fecaca;
color: var(--danger-text);
  border-radius: 10px;
  padding: 12px 16px;
  font-size: 13px;
  margin-bottom: 16px;
}

.submit-bar {
  display: flex;
  gap: 12px;
  margin-top: 20px;
}

.btn-submit {
  padding: 10px 34px;
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: 24px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.btn-submit:hover:not(:disabled) {
  background: var(--primary-hover);
}

.btn-submit:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-cancel {
  padding: 10px 28px;
  background: var(--bg-subtle);
  color: var(--text-sub);
  border: none;
  border-radius: 24px;
  font-size: 14px;
  cursor: pointer;
}

/* ===== 手机端：原本无任何媒体查询 ===== */
@media (max-width: 600px) {
  .forum-card {
    padding: 12px 10px;
  }

  .mute-tip {
    padding: 10px 12px;
  }
}
</style>
