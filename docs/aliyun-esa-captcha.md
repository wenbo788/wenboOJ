# 阿里云 ESA AI CAPTCHA 登录接入

## ESA 控制台规则

创建两条 `POST` 验签规则。**身份标 prefix 共用，SceneId 分开**：

| 规则 | 需验签接口（控制台「需验签的接口」字段格式） | 前端 SceneId 配置 |
| --- | --- | --- |
| NLNOJ 主登录 | `nlnoj.gr3yph4ntom.cn/auth/login` | `VITE_ESA_CAPTCHA_SCENE_ID_AUTH` |
| 兼容 OAuth 登录 | `nlnoj.gr3yph4ntom.cn/tokens` | `VITE_ESA_CAPTCHA_SCENE_ID_TOKENS` |

「需验签的接口」按官方格式填**域名+路径**（不带 `https://`），请求方法必须包含 `POST`。注意这是 API 路径，不是前端页面路由（登录页是 `/login`，接口是 `/auth/login`）——格式填错或填成页面路由，规则不会命中任何请求，表现为响应完全没有 `x-captcha-verify-code` 头。规则修改后需等几分钟边缘下发再验证。

主登录页面使用 AUTH 场景。`/tokens` 是旧 OAuth 密码登录入口；当前 NLNOJ 页面没有调用方，但服务器启用 ESA 强制模式后也会保护它，避免留下绕过入口。旧/外部客户端若继续使用 `/tokens`，须使用 TOKENS 场景接入 ESA。

项目请求将 `captcha_verify_param` 同时放在 URL query（ESA 规则验签）和 JSON body（源站强制开关检查）中。

## 前端构建配置

将 `web/.env.production.example` 配置为生产构建使用的 `web/.env.production`：

```dotenv
VITE_API_BASE_URL=
VITE_ESA_CAPTCHA_PREFIX=<共用的 ESA 身份标>
VITE_ESA_CAPTCHA_SCENE_ID_AUTH=<auth/login 场景 ID>
VITE_ESA_CAPTCHA_SCENE_ID_TOKENS=<tokens 场景 ID>
```

`VITE_API_BASE_URL` 留空，使登录请求走当前受 ESA 保护的同源域名。ESA SDK 按官方要求由浏览器动态加载，不要下载后自托管。

登录页只在共用 prefix 和 AUTH SceneId 均已填写时加载 ESA；配置不完整时继续用现有图形验证码。SDK 初始化后等待至少 2 秒才允许触发验证。旧变量 `VITE_ESA_CAPTCHA_SCENE_ID` 暂作 AUTH SceneId 的迁移回退，填入新配置后可删除旧变量。

验证组件以**嵌入式**（`mode: 'embed'`）渲染在登录表单内（密码框与登录按钮之间），不弹遮罩弹窗：「一点即过」等交互形态支持嵌入；**若在控制台把验证码类型改成「无痕验证」，前端必须把 mode 改回 `popup`**——官方规定无痕验证不支持嵌入式接入。窄屏由 `rem` 按容器宽度整体缩放。

票据流程两种顺序都支持：先点登录 → 表单内完成验证后自动续上登录；先完成验证 → 点登录直接用票。ESA 票据 90 秒有效且单次使用，前端 60 秒提前作废、提交即消费（防 F019 超时/F018 复用），每次业务请求后 `refresh()` 复位组件供重试。

## 启用步骤

1. 在 ESA 配置两条规则，共用 prefix、分别记录两个 SceneId。建规则时**走行内「接入引导」走完全部步骤**，并检查两项容易漏的状态：规则页顶部**站点归属**必须是承载流量的站点（多站点账号容易建错地方）；**「拦截空 Token」要开启**（开启后空票据探测会被拦回 `F002`，规则是否生效一测便知）。
2. 填写上述生产构建变量并构建部署前端。
3. **先确认流量真的经过 ESA**：`dig +short nlnoj.gr3yph4ntom.cn CNAME` 应显示 ESA 分配的专属 CNAME（形如 `<域名>.aN.inituu.com`，inituu.com 即 ESA 的 CNAME 网段）。若指向其他 CDN/代理，两条规则永远不会被触发，登录必挂在「ESA 安全验证未通过」。
4. 确认 `/auth/login` 经 ESA 后响应头包含 `X-Captcha-Verify-Code: T001`（测试通过码 `T005`、白名单通过码 `T006` 也接受）。可直接探测：

   ```bash
   curl -si -X POST '/auth/login?captcha_verify_param=x' \
     -H 'Content-Type: application/json' \
     -d '{"identifier":"nouser","password":"x","captcha_verify_param":"x"}' | grep -i x-captcha
   ```

   出现 `F` 开头的错误码也算正常——说明规则命中且在验签；**完全没有该头则规则未生效，不得进入下一步**。
5. 在 `service/.env` 设置 `ESA_CAPTCHA_REQUIRED=true` 并重启后端。此后 `/auth/login` 和 `/tokens` 都拒绝缺少验签参数的请求；`/tokens/refresh` 不需要验证码。
6. 限制源站只允许可信边缘/反代回源。ESA 在边缘完成验签，源站本身无法验证伪造的 query/body 值；若公网可以绕过 ESA 直连源站，不能启用强制模式。

回滚须两边同步：前端重新构建（清空 `VITE_ESA_CAPTCHA_*`）+ 后端开关改回 `false`。只关后端开关会得到「前端只发 ESA 参数、后端只收图形码」的双重拦截，谁都登不进。

ESA 强制开关关闭时，即使请求伪造 `captcha_verify_param`，仍必须通过现有图形验证码。开关开启后若 ESA 未生效会失败关闭，不会降级回图形码。

## 排障实录（2026-10-17）

**症状**：弹窗点选显示通过，登录页报「ESA 安全验证未通过」。

**三板斧定位**（外部即可完成，全程不动服务器）：

1. `dig +short <域名> CNAME`——指向 `<域名>.aN.inituu.com` 即在 ESA 上（inituu 就是 ESA 的 CNAME 网段，**别误判成第三方 CDN**；也见过 DNS 刚切换时本机缓存未过期、探测打到直连源站的假象）。
2. `curl -si -X POST ... | grep -i x-captcha`——响应**完全没有** `x-captcha-verify-code` 头 = 规则没介入；有 F 码 = 已命中在验签。
3. 控制台规则列表的**「24小时验证量」**——恒为 0 即边缘从未处理过任何请求（客户端弹窗走 SDK 直连 `captcha-esa-open.aliyuncs.com`，不会体现在这里）。

**根因**：URI/场景 ID 字段全对，但接入步骤未走完——按行内「接入引导」核查（含开启「拦截空 Token」、确认站点归属）后生效。字段正确 ≠ 规则生效，状态类问题表现与填错一模一样。

**修复后的健康特征**：空票据 `403 + F002`（`X-Tengine-Error: denied by http_captcha`）、伪造票据 `403 + F003`；真实登录拿 `T001` 放行。

**已知无关问题**：生产 nginx 对 `POST /tokens` 回 `301 Location: http://127.0.0.1/tokens/`，旧 OAuth 入口线上不可用（主登录不受影响，待修 nginx 反代）。