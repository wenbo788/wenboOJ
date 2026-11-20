# 服务器部署步骤（Linux 裸机 → Docker）

架构：**nginx 容器**（80 端口，托管前端 + 反代 API）→ **FastAPI 容器**（8000，仅内网）→ **Supabase**（云端数据库）

```
浏览器 ──> http://服务器IP/
              │ nginx (oj-web 容器)
              ├── /api/*        → oj-service:8000/*（去掉 /api 前缀）
              ├── /auth|users|benben|tokens/* → oj-service:8000（透传）
              └── 其余路径       → 前端静态文件（SPA 回退 index.html）
```

## 一、服务器初始化（一次性）

```bash
# 1. 安装 Docker（官方脚本，Ubuntu/Debian/CentOS 通用）
curl -fsSL https://get.docker.com | sh
sudo systemctl enable --now docker

# 2. 让当前用户免 sudo 用 docker（重新登录后生效）
sudo usermod -aG docker $USER

# 3. 防火墙放行 80 端口（按需）
sudo ufw allow 80/tcp    # Ubuntu
```

## 二、上传代码

方式任选其一：

```bash
# 方式A：git（推荐）
git clone <你的仓库地址> /opt/oj && cd /opt/oj

# 方式B：本地打包上传（排除依赖目录）
# 本机执行：
tar --exclude=node_modules --exclude=.git --exclude=.venv --exclude=dist -czf oj.tar.gz .
scp oj.tar.gz user@服务器IP:/opt/ && ssh user@服务器IP "cd /opt && mkdir oj && tar xzf oj.tar.gz -C oj"
```

> ⚠️ `service/.env` 被 git 忽略，用 git 方式时服务器上不会有它 —— 按下面第三步创建。

## 三、配置环境变量

```bash
cd /opt/oj/service
cp .env.production .env
vi .env   # 确认三项：DATABASE_URL（Supabase）、JWT_SECRET（已填）、ENV=prod
```

前端 `web/.env.production` 已配置为同域反代（`VITE_API_BASE_URL=` 留空），无需修改。
构建时 Docker 会自动读取它。

## 四、启动

```bash
cd /opt/oj
docker compose up -d --build     # 首次构建约 3~5 分钟
docker compose ps                # 两个容器应为 running（healthy）
docker compose logs -f oj-service  # 看后端日志，确认 "Application startup complete"
```

## 五、验证

```bash
# 服务器本机
curl -s http://localhost/                       # 应返回 index.html
curl -s http://localhost/api/admin/users -o /dev/null -w "%{http_code}\n"   # 401/403 = 通了（未带token）
curl -s http://localhost/users/number/1 | head -c 200                        # 应返回用户 JSON

# 外部浏览器
# http://服务器IP/        → 主页（打卡卡片/犇犇/近期讨论）
# http://服务器IP/login   → 登录（用 Supabase 库里的账号）
# http://服务器IP/admin   → 管理后台
```

## 常见问题

| 现象 | 处理 |
|------|------|
| `oj-web` 起不来，报 nginx 配置错 | `docker compose logs oj-web`；多为 nginx.conf 语法问题 |
| 后端启动报 `ENV=prod requires JWT_SECRET` | `service/.env` 里 JWT_SECRET 没填 |
| 页面能开但接口 502 | `docker compose ps` 看 oj-service 是否 healthy；`docker compose restart oj-service` |
| Supabase 连接超时 | 服务器网络是否禁 IPv6/出网；改用 Session Pooler 连接串（5432） |
| 登录后 401 循环 | 服务器时间偏差过大导致 JWT 校验失败：`timedatectl` 检查并开启 NTP |
| 修改前端代码后更新 | `docker compose up -d --build oj-web`（只需重建前端容器） |

## 防攻击 / 抗 522（站点被打时按这个顺序做）

Cloudflare 报 **522** = 它连上了源站（或连不上），但源站迟迟不响应。
代码侧已经做了三层削峰（见下），但**最关键的杠杆在边缘**：源站 IP 一旦裸奔，
再多应用层限流也只能「少死一点」，挡不住洪水。

### 1️⃣ 把域名接回 Cloudflare（橙云），并只让 CF 回源 ★最重要

```bash
# 自查：域名是否直接解析到源站（说明 CF 没在前面对所有人生效）
dig +short nlnoj.gr3yph4ntom.cn          # 若返回源站 IP（如 47.109.90.19）＝ 灰云/仅 DNS
```

- DNS 记录改成 **Proxied（橙云）**；源站安全组/防火墙**只放行 Cloudflare 回源网段**
  （<https://www.cloudflare.com/ips/>），其余来源一律拒绝——否则攻击者拿到源站 IP
  就绕过了 CDN、WAF 和限流；
- 开启 **Bot Fight Mode**、按需用 **Rate limiting rules**（对 `/tokens`、`/auth`、
  `/api/messages` 这些口单独设）、被打期间直接开 **I'm Under Attack**；
- 回源证书用 **Authenticated Origin Pulls**，避免有人伪造 CF 头直连源站。

### 2️⃣ 源站侧（本仓库已内置，确认部署已生效）

| 层 | 措施 | 位置 |
|----|------|------|
| nginx | 按真实 IP `limit_req`（API 50r/s、鉴权 10r/s）+ `limit_conn` 64 | `web/nginx.conf` |
| nginx | 扫描路径（`*.php`、`.env`、`.git`、`wp-*`…）直接 `return 444`，不进后端也不返回 SPA | `web/nginx.conf` |
| nginx | 上游 `keepalive`；`proxy_connect_timeout 5s` 快速失败（别让 CF 干等） | `web/nginx.conf` |
| 应用 | 单 IP 限速 + 全站/单 IP 并发上限，**超限立刻 502/503 而不是排队**；限流对外装成 502（`GUARD_RATE_STATUS`），并发过载仍是 503 | `service/app/core/guard.py` |
| 应用 | 数据库连接池排满 → 快速 503（`pool_timeout 5s`） | `service/app/core/database.py` |
| 运行时 | uvicorn `--limit-concurrency 256 --backlog 2048 --timeout-keep-alive 15` | `service/Dockerfile` |

```bash
# 生效确认：洪泛时健康接口仍应秒回，洪泛请求拿到 502/503（而不是超时）
for i in $(seq 1 200); do curl -s -o /dev/null -w "%{http_code} " http://localhost/api/benben & done; wait; echo
ss -s                      # 连接数是否失控
docker stats --no-stream   # 容器 CPU/内存
```

### 3️⃣ 容量与应急

- 服务器开 **swap**（2G 起）：被打时内存抖动会导致 OOM/进程重启，表现也是 522；
- PostgreSQL `max_connections` 要 ≥ 连接池上限（10+20）并留余量；
- `ulimit -n`（nginx worker 的 `worker_connections`、uvicorn 的 FD）调大；
- 应急三招：CF 开 Under Attack → 把 `GUARD_MAX_PER_IP_CONCURRENCY` 临时调到 8~16
  （改 `service/.env` 后 `docker compose up -d oj-service`）→ 在安全组封掉攻击来源段；
- 长期：`fail2ban` 或 CF 的 WAF 规则拦扫描器；静态资源交给 CF 缓存（少回源）。

## 后续增强（可选）

- **HTTPS**：有域名后，在 oj-web 前面加一层 Caddy/Traefik 自动签证书，或用 certbot + 挂载证书到 nginx
- **日志轮转**：compose 中加 `logging: {driver: json-file, options: {max-size: "10m", max-file: "3"}}`
- **数据备份**：Supabase Dashboard 自带每日备份（付费版）；免费版可定期 pg_dump
