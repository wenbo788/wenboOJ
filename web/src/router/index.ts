import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import * as session from '@/utils/session'
import {
  isAnyAdmin,
  isSuperAdmin,
  isTopAdmin,
  canManageProblems,
  canManageCommunity,
  canReviewArticles,
  canManageTeams,
} from '@/utils/permissions'

// ================================================================
// 权限判定统一走 @/utils/permissions，本文件不再内联实现
// ================================================================

const routes = [
  {
    path: '/test',
    name: 'Test',
    component: () => import('@/views/Test.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/',
    name: 'Home',
    component: () => import('@/views/Home.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/auth/Login.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/auth/Register.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/forgot-password',
    name: 'ForgotPassword',
    component: () => import('@/views/auth/ForgotPassword.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/reset-password',
    name: 'ResetPassword',
    component: () => import('@/views/auth/ResetPassword.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/profile',
    name: 'Profile',
    component: () => import('@/views/UserProfile.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/preferences',
    name: 'Preferences',
    component: () => import('@/views/Preferences.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/user/:id',
    name: 'UserDetail',
    component: () => import('@/views/UserDetail.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/judgement',
    name: 'Judgement',
    component: () => import('@/views/Judgement.vue'),
    meta: { requiresAuth: false, title: '陶片放逐' }
  },
  {
    // 管理名单：公示用户管理/秩序管理持有者
    path: '/judgement/admins',
    name: 'JudgementAdmins',
    component: () => import('@/views/JudgementAdmins.vue'),
    meta: { requiresAuth: false, title: '管理名单' }
  },
  {
    path: '/discuss',
    name: 'Discuss',
    component: () => import('@/views/discuss/Discuss.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/discuss/new',
    name: 'DiscussNew',
    component: () => import('@/views/discuss/DiscussNew.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/discuss/:id',
    name: 'DiscussPost',
    component: () => import('@/views/discuss/DiscussPost.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/teams',
    name: 'TeamList',
    component: () => import('@/views/teams/TeamList.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/teams/:id(\\d+)',
    alias: '/team/:id(\\d+)',
    name: 'TeamDetail',
    component: () => import('@/views/teams/TeamDetail.vue'),
    meta: { requiresAuth: false }
  },
  {
    // 我所在团队的全部题目
    path: '/team/problems',
    name: 'TeamProblemsAll',
    component: () => import('@/views/teams/TeamProblems.vue'),
    meta: { requiresAuth: true }
  },
  {
    // 1v1 对战竞技场
    path: '/arena',
    name: 'BattleArena',
    component: () => import('@/views/battle/BattleArena.vue'),
    meta: { requiresAuth: true, title: '1v1 对战竞技场' }
  },
  {
    // 1v1 对战房间
    path: '/arena/room/:battleId(\\d+)',
    name: 'BattleRoom',
    component: () => import('@/views/battle/BattleRoom.vue'),
    meta: { requiresAuth: true, title: '对决中 - 1v1 对战' }
  },
  {
    // 经验商店
    path: '/shop',
    name: 'Shop',
    component: () => import('@/views/shop/Shop.vue'),
    meta: { requiresAuth: true }
  },
  {
    // 贡献商店
    path: '/shop/contribution',
    name: 'ContributionShop',
    component: () => import('@/views/shop/Shop.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/user/notification',
    name: 'Notifications',
    component: () => import('@/views/Notifications.vue'),
    meta: { requiresAuth: true }
  },
  {
    // 主题商店
    path: '/themes',
    name: 'ThemeShop',
    component: () => import('@/views/themes/ThemeShop.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/tickets',
    name: 'Tickets',
    component: () => import('@/views/tickets/Tickets.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/tickets/all',
    name: 'TicketsAll',
    component: () => import('@/views/tickets/Tickets.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/tickets/assigned',
    name: 'TicketsAssigned',
    component: () => import('@/views/tickets/Tickets.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/tickets/unassigned',
    name: 'TicketsUnassigned',
    component: () => import('@/views/tickets/Tickets.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/tickets/new',
    name: 'TicketCreate',
    component: () => import('@/views/tickets/TicketCreate.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/tickets/:id',
    name: 'TicketDetail',
    component: () => import('@/views/tickets/TicketDetail.vue'),
    meta: { requiresAuth: true }
  },
  {
    // 用户管理（超管及以上）
    path: '/admin/user',
    name: 'Admin',
    component: () => import('@/views/Admin.vue'),
    meta: { requiresAuth: true, requiresSuperAdmin: true }
  },
  {
    // 站点管理（超管及以上）
    path: '/admin/site',
    name: 'SiteAdmin',
    component: () => import('@/views/AdminAds.vue'),
    meta: { requiresAuth: true, requiresSuperAdmin: true }
  },
  {
    path: '/admin/ads',
    redirect: '/admin/site'
  },
  {
    path: '/admin',
    redirect: '/admin/user'
  },
  {
    // 陶片放逐日志（超管/白名单）
    path: '/admin/logs',
    name: 'AdminLogs',
    component: () => import('@/views/AdminLogs.vue'),
    meta: { requiresAuth: true, requiresSuperAdmin: true}
  },
  {
    // 奖项认证审核（超管/白名单）
    path: '/admin/award-cert',
    name: 'AdminAwardCert',
    component: () => import('@/views/AdminAwardCert.vue'),
    meta: { requiresAuth: true, requiresSuperAdmin: true}
  },
  {
    // 团队管理（大管及以上）
    path: '/admin/teams',
    name: 'AdminTeams',
    component: () => import('@/views/admin/Teams.vue'),
    meta: { requiresAuth: true, requiresTeamManage: true }
  },
  {
    path: '/test-admin',
    name: 'TestAdmin',
    component: () => import('@/views/admin/Test.vue'),
    meta: { requiresAuth: true, requiresSuperAdmin: true }
  },
  {
    path: '/admin-test',
    name: 'AdminTest',
    component: () => import('@/views/AdminTest.vue'),
    meta: { requiresAuth: true, requiresSuperAdmin: true }
  },
  {
    path: '/problems',
    name: 'ProblemList',
    component: () => import('@/views/problems/ProblemList.vue'),
    meta: { requiresAuth: true }
  },
  {
    // 训练题单：所有用户可访问
    path: '/training',
    name: 'TrainingList',
    component: () => import('@/views/training/TrainingList.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/training/new',
    name: 'TrainingCreate',
    component: () => import('@/views/training/TrainingEdit.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/training/:id(\\d+)',
    name: 'TrainingDetail',
    component: () => import('@/views/training/TrainingDetail.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/training/:id(\\d+)/edit',
    name: 'TrainingEdit',
    component: () => import('@/views/training/TrainingEdit.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/column/:id(\\d+)',
    name: 'ColumnDetail',
    component: () => import('@/views/columns/ColumnDetail.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/column/:id(\\d+)/article/:articleId(\\d+)',
    name: 'ColumnArticleDetail',
    component: () => import('@/views/columns/ArticleDetail.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/article/:articleId(\\d+)',
    name: 'ArticleDetail',
    component: () => import('@/views/columns/ArticleDetail.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/columns',
    redirect: '/articles'
  },
  {
    path: '/articles',
    name: 'ArticlePlaza',
    component: () => import('@/views/columns/ArticlePlaza.vue'),
    meta: { requiresAuth: false, title: '文章广场' }
  },
  {
    // 站内投票：管理员发起，登录用户一人一票
    path: '/polls',
    name: 'Polls',
    component: () => import('@/views/Polls.vue'),
    meta: { requiresAuth: true, title: '站内投票' }
  },
  {
    // 单个投票：每个投票一个独立页面（/polls/1、/polls/2…）
    path: '/polls/:id(\\d+)',
    name: 'PollDetail',
    component: () => import('@/views/PollDetail.vue'),
    meta: { requiresAuth: true, title: '投票详情' }
  },
  {
    // 题目管理（题管及以上）
    path: '/admin/problems',
    name: 'AdminProblems',
    component: () => import('@/views/AdminProblems.vue'),
    meta: { requiresAuth: true, requiresProblemManage: true }
  },
  {
    // 提交查重（疑似抄袭榜）：与后端 can_manage_problems 同口径，题管及以上
    path: '/admin/plagiarism',
    name: 'AdminPlagiarism',
    component: () => import('@/views/AdminPlagiarism.vue'),
    meta: { requiresAuth: true, requiresProblemManage: true, title: '提交查重' }
  },
  {
    // 题解与文章推荐审核（任意管理角色）
    path: '/admin/articles',
    name: 'AdminArticles',
    component: () => import('@/views/AdminArticles.vue'),
    meta: { requiresAuth: true, requiresArticleReview: true, title: '题解与文章推荐审核' }
  },
  {
    // 举报审核（社管及以上）
    path: '/admin/reports',
    name: 'AdminReports',
    component: () => import('@/views/AdminReports.vue'),
    meta: { requiresAuth: true, requiresOrderManage: true }
  },
  {
    // 独立举报页
    path: '/report/:type(benben|post|comment)/:id(\\d+)',
    name: 'ReportCreate',
    component: () => import('@/views/ReportCreate.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/problems/new',
    name: 'ProblemCreate',
    component: () => import('@/views/problems/ProblemEdit.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/problems/:id(\\d+)/edit',
    name: 'ProblemEdit',
    component: () => import('@/views/problems/ProblemEdit.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/problems/:id(\\d+)/solutions',
    name: 'ProblemSolutionsById',
    component: () => import('@/views/problems/ProblemSolutions.vue'),
    meta: { requiresAuth: true, title: '题目题解' }
  },
  {
    path: '/problem/:code/solutions',
    name: 'ProblemSolutions',
    component: () => import('@/views/problems/ProblemSolutions.vue'),
    meta: { requiresAuth: true, title: '题目题解' }
  },
  {
    path: '/problems/:id(\\d+)',
    name: 'ProblemDetail',
    component: () => import('@/views/problems/ProblemDetail.vue'),
    meta: { requiresAuth: true }
  },
  {
    // 统一题号入口：/problem/P1001（主题库）/ U1001（用户题库）/ T10（团队题）
    path: '/problem/:code',
    name: 'ProblemByCode',
    component: () => import('@/views/problems/ProblemDetail.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/problems/:id(\\d+)/submit',
    name: 'ProblemSubmit',
    component: () => import('@/views/problems/ProblemSubmit.vue'),
    meta: { requiresAuth: true }
  },
  {
    // 沉浸式做题页：隐藏全站导航，左题面 + 右编辑器/自测，就地评测不跳转
    path: '/problems/:id(\\d+)/immersive',
    name: 'ProblemImmersive',
    component: () => import('@/views/problems/ProblemImmersive.vue'),
    meta: { requiresAuth: true, title: '沉浸做题' }
  },
  {
    path: '/submissions',
    name: 'SubmissionList',
    component: () => import('@/views/SubmissionList.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/submissions/:id(\\d+)',
    name: 'SubmissionDetail',
    component: () => import('@/views/problems/SubmissionDetail.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/contests',
    name: 'ContestList',
    component: () => import('@/views/contests/ContestList.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/contests/new',
    name: 'ContestCreate',
    component: () => import('@/views/contests/ContestCreate.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/contest/:id(\\d+)',
    name: 'ContestDetail',
    component: () => import('@/views/contests/ContestDetail.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/contest/:id(\\d+)/edit',
    name: 'ContestEdit',
    component: () => import('@/views/contests/ContestEdit.vue'),
    meta: { requiresAuth: true }
  },
  {
    // 兼容旧复数链接
    path: '/contests/:id(\\d+)',
    redirect: (to: any) => ({ path: `/contest/${to.params.id}`, hash: to.hash })
  },
  {
    path: '/image',
    name: 'ImageHost',
    component: () => import('@/views/ImageHost.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/clipboard',
    name: 'Clipboard',
    component: () => import('@/views/ClipboardView.vue'),
    meta: { requiresAuth: true, title: '云剪贴板' }
  },
  {
    path: '/help',
    name: 'Help',
    component: () => import('@/views/SiteDoc.vue'),
    meta: { requiresAuth: false, docKey: 'help', docTitle: '帮助中心' }
  },
  {
    path: '/rules',
    name: 'Rules',
    component: () => import('@/views/SiteDoc.vue'),
    meta: { requiresAuth: false, docKey: 'rules', docTitle: '社区规则' }
  },
  {
    path: '/ranking',
    name: 'Ranking',
    component: () => import('@/views/Ranking.vue'),
    meta: { requiresAuth: false, title: '经验排行榜' }
  },
  {
    path: '/group-chat/:conversationId(\\d+)?',
    name: 'GroupChat',
    component: () => import('@/views/GroupChat.vue'),
    meta: { requiresAuth: true, title: '群组' }
  }
]

// ===== 未开放页面：统一指向「本功能暂未开放」 =====
const comingSoonPaths = [
  '/courses',       // 网校
  '/contact',       // 联系我们
]

comingSoonPaths.forEach((p) => {
  routes.push({
    path: p,
    name: 'ComingSoon_' + p.replace(/\//g, '_'),
    component: () => import('@/views/ComingSoon.vue'),
    meta: { requiresAuth: false }
  })
})

// 无权访问提示页
routes.push({
  path: '/no-access',
  name: 'NoAccess',
  component: () => import('@/views/NoAccess.vue'),
  meta: { requiresAuth: false }
})

// 兜底：未知路径同样显示「本功能暂未开放」
routes.push({
  path: '/:pathMatch(.*)*',
  name: 'ComingSoon_CatchAll',
  component: () => import('@/views/ComingSoon.vue'),
  meta: { requiresAuth: false }
})

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

// 每次整页加载（F5 / 首次进入）只静默同步一次用户信息
let userSyncedThisLoad = false

// 路由守卫
router.beforeEach(async (to) => {
  const authStore = useAuthStore()

  // 恢复认证状态
  if (!authStore.accessToken && session.hasSession()) {
    authStore.restoreState()
  }

  const requiresAuth = to.meta.requiresAuth || false
  const requiresAdmin = to.meta.requiresAdmin || false

  // 有令牌但本地没有用户资料：先补拉一次再判定
  if (!authStore.currentUser && authStore.accessToken) {
    await authStore.fetchCurrentUser()
  }

  // 检查是否需要认证
  if (requiresAuth && !authStore.isAuthenticated) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }

  // 本地有缓存的用户信息：整页加载后静默同步一次最新权限
  if (authStore.isAuthenticated && !userSyncedThisLoad) {
    userSyncedThisLoad = true
    await authStore.syncCurrentUser()
  }

  const user = authStore.currentUser

  // 检查是否需要管理员权限：任意管理角色
  if (requiresAdmin) {
    if (!isAnyAdmin(user)) {
      return { path: '/no-access', query: { from: to.fullPath } }
    }
  }

  // 检查是否需要用户管理权限（管理日志/奖项认证）：白名单/超管
  if (to.meta.requiresSuperAdmin) {
    if (!isTopAdmin(user)) {
      return { path: '/no-access', query: { from: to.fullPath } }
    }
  }

  // 检查是否需要题目管理权限（建题/编辑页）：白名单/超管/题管
  // 团队私有题模式（带 team_id）放行，由后端校验团队管理权限
  if (to.meta.requiresProblemManage) {
    const hasTeamId = !!(to.query.team_id && parseInt(to.query.team_id as string, 10) > 0)
    if (!hasTeamId && !canManageProblems(user)) {
      return { path: '/no-access', query: { from: to.fullPath } }
    }
  }

  // 检查是否需要题解审核权限（题管/社管/更高）
  if (to.meta.requiresArticleReview) {
    if (!canReviewArticles(user)) {
      return { path: '/no-access', query: { from: to.fullPath } }
    }
  }

  // 检查是否需要秩序管理权限（举报审核页）：白名单/超管/社管
  if (to.meta.requiresOrderManage) {
    if (!canManageCommunity(user)) {
      return { path: '/no-access', query: { from: to.fullPath } }
    }
  }

  // 检查是否需要团队管理权限（团队管理页）：白名单/超管/大管
  if (to.meta.requiresTeamManage) {
    if (!canManageTeams(user)) {
      return { path: '/no-access', query: { from: to.fullPath } }
    }
  }

  return true
})

export default router