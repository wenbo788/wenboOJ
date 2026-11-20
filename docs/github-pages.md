# 前端部署到 GitHub Pages

> 适用场景：把 `web/`（Vue 3 + Vite）作为纯静态前端放到 GitHub Pages，
> 后端 API 与评测机仍在自己的服务器上。Pages **不能**运行 FastAPI、数据库和
> judge，所谓“无评测版”只是前端不跑评测；“提交/评测”仍由远端后端完成。

## 已内置的改造

| 位置 | 改动 |
|------|------|
| [web/vite.config.ts](../web/vite.config.ts) | `base` 读取 `PAGES_BASE`，支持 `/<repo>/` 子路径 |
| [web/index.html](../web/index.html) | 官方域跳转脚本放行 `*.github.io` / 本地地址 |
| [web/src/utils/base.ts](../web/src/utils/base.ts) | `withBase()` 处理站内路径，`staticUrl()` 处理后端 `/static/...` 资源 |
| [web/src/api/client.ts](../web/src/api/client.ts) | 401 跳登录带上部署 base；接口返回的 `/static/...` 自动补 API origin |
| [web/src/utils/markdown.ts](../web/src/utils/markdown.ts) | 题面/文章中的 `/static/...` 图片、`@提及` 链接适配子路径 |
| 导航 / Logo / 图标 | `SideBar`、`TopBar`、登录注册页、备案图标等改为 base 感知 |
| [web/scripts/pages-postbuild.mjs](../web/scripts/pages-postbuild.mjs) | 构建后生成 `dist/404.html` 与 `.nojekyll` |
| [.github/workflows/pages.yml](../.github/workflows/pages.yml) | 构建并发布 `web/dist` |

## 一次性配置

### 0. 后端还没上线时

GitHub Pages 可以先部署，但页面里的数据、登录都来自 API；后端没起来之前，
首页会空白、登录会报错，这是正常现象。

**Supabase 不能直接当这个项目的后端**：它提供 Postgres / Auth / Storage /
Edge Functions（Deno），没有 Python 运行时，也跑不了 go-judge（需要特权
Linux 沙箱）。可行的组合是：

| 组件 | 放哪 |
|------|------|
| 数据库 | Supabase Postgres（用 Session Pooler 连接串，5432） |
| FastAPI | 一台 VPS（直接复用本仓库 `docker-compose.yml`），或 Render / Railway / Fly.io |
| 评测机 | 需要评测才部署 go-judge；“无评测”可以不部署，但要隐藏提交入口 |
| 前端 | GitHub Pages |

Supabase 连接串示例（`service/.env`，详见 [service/SUPABASE_SETUP.md](../service/SUPABASE_SETUP.md)）：

```env
DATABASE_URL=postgresql+asyncpg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
ENV=prod
JWT_SECRET=<随机长串>
FRONTEND_URL=https://wenbo788.github.io/wenboOJ
CORS_EXTRA_ORIGINS=https://wenbo788.github.io
```

> `ENV=prod` 会强制要求 PostgreSQL、`JWT_SECRET` 和真实 `FRONTEND_URL`，
> 否则后端启动直接报错。`service/Dockerfile` 启动时会自动 `alembic upgrade head`，
> 空库不需要手工建表；不要再拿旧的 `supabase_schema.sql`（只有 4 张表）建库。

### 1. 仓库变量（Actions → Variables）

**空壳阶段不用建变量**：工作流会留空 `VITE_API_BASE_URL` 并设置
`VITE_SHELL_MODE=1`，页面底部会显示“后端 API 尚未接入”的提示。

以后后端上线了再建：

| 变量 | 值 |
|------|----|
| `VITE_API_BASE_URL` | 后端 origin，例如 `https://api.example.com`。**不要带 `/api`，不要带尾斜杠** |

设置变量后，还要把 [.github/workflows/pages.yml](../.github/workflows/pages.yml)
里的 `VITE_SHELL_MODE: '1'` 删掉，否则提示条会一直显示。

### 2. 后端 CORS

在服务器 `service/.env` 中加：

```env
CORS_EXTRA_ORIGINS=https://wenbo788.github.io
```

只填 scheme + host（**不要**带 `/仓库名/`），多个用逗号分隔；改完重启后端：

```bash
docker compose up -d oj-service
```

> 若后端不是你能改的机器，Pages 前端无法登录/取数据，只能做纯静态页面。

### 3. 开启 Pages

仓库 **Settings → Pages → Build and deployment → Source** 选 **GitHub Actions**。
私有仓库需要 GitHub Pro/Team/Enterprise 才能启用 Pages。

### 4. 部署路径

工作流默认按项目页处理：`https://wenbo788.github.io/wenboOJ/` → `PAGES_BASE=/wenboOJ/`。
仓库名不需要手动填，工作流会读 `github.event.repository.name`；下面示例统一用 `wenboOJ`。

- 仓库名是 `<user>.github.io`，或绑定了自定义域 → 构建环境变量改成 `PAGES_BASE=/`
- 自定义域还需把域名加入 [web/index.html](../web/index.html) 的放行列表，
  并把 `CORS_EXTRA_ORIGINS` 换成该域名的 origin

## 本地构建验证

```bash
cd web
npm ci

# Windows PowerShell（把 /wenboOJ/ 换成你的仓库名）
$env:VITE_API_BASE_URL="https://<后端域名>"
$env:PAGES_BASE="/wenboOJ/"
npm run build:pages

# Linux / macOS / Git Bash
VITE_API_BASE_URL=https://<后端域名> PAGES_BASE=/wenboOJ/ npm run build:pages
```

检查 `dist/index.html` 中的 `<script src>`、`<link href>` 是否都带 `/wenboOJ/` 前缀；
`dist/` 下应有 `index.html`、`404.html`、`.nojekyll`、`assets/`。

## 上线自检

```bash
curl -sI https://wenbo788.github.io/wenboOJ/ | head
curl -s https://wenbo788.github.io/wenboOJ/problems | head -c 200   # 404 状态但正文是 index.html 才算对
curl -si -X OPTIONS https://<后端域名>/api/problems \
  -H 'Origin: https://wenbo788.github.io' \
  -H 'Access-Control-Request-Method: GET' | grep -i '^access-control'
```

最后一条要出现 `access-control-allow-origin: https://wenbo788.github.io`。

## 常见问题

| 现象 | 原因 / 处理 |
|------|-------------|
| 打开 Pages 立刻跳到官方域名 | 自定义域未加入 [web/index.html](../web/index.html) 的放行列表 |
| 白屏，Console 报 MIME 为 `text/html` | `PAGES_BASE` 与 Pages 路径不一致，JS 404 后被 `404.html` 兜底 |
| 刷新 `/problems/1` 变 404 页面 | 没有生成 `dist/404.html`，确认用了 `npm run build:pages` |
| 登录后点登录按钮跳 `github.io/login` 404 | 旧构建产物；重新构建（本次已改为 base 感知） |
| 页面能开但全是空列表 / 登录失败 | 后端还没启动或 `VITE_API_BASE_URL` 指错；先在浏览器 Network 看接口请求地址 |
| 接口请求打到 `github.io/api/...` | 构建时没设 `VITE_API_BASE_URL`；环境变量是构建期注入，改完必须重新构建 |
| 接口变成 `/api/api/...` | `VITE_API_BASE_URL` 误填成 `https://host/api` |
| CORS 报错 / 预检 403 | `CORS_EXTRA_ORIGINS` 没加 Pages origin，或没重启后端 |
| 图片、头像裂开 | 后端返回 `/static/...`；确认前端构建产物包含本次 `staticUrl` 改造 |
| 登录 401 / 验证码不显示 | 若线上启用了 ESA 验证码，需要在 ESA 控制台给 Pages 域名加白名单 |
| 部署成功但页面还是旧版 | Pages 缓存约 10 分钟；强刷或等缓存过期 |
| Actions 报 `Get Pages site failed` | 未在 Settings → Pages 里把 Source 设为 GitHub Actions |
| 构建卡在 `vue-tsc` | `npm run dev` 不做类型检查；本地先跑一次 `npm run build` 修类型 |

## 已知限制

- Pages 只支持静态文件：没有 SSR、没有自定义响应头/重定向，深链依赖 `404.html`
  （返回 404 状态码属正常）。
- 不部署 go-judge 时没有评测：提交会失败或一直 pending，需要在页面上隐藏提交入口；
  Pages 本身无法承担评测。
- Supabase 只能提供数据库 / Auth / Storage，不能运行 `service/` 的 FastAPI
  和 judge；后端仍要另找一台机器。
- 跨域后登录态按域隔离：官方站已登录的用户在 Pages 站需要重新登录。
- `github.io` 在中国大陆访问不稳定，且无法备案；正式对外仍建议用自有域名。
