"""Application configuration loaded from environment / ``.env``."""

from __future__ import annotations

import secrets
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Values are read from the environment / ``.env``."""

    # Database. Local dev defaults to a zero-config SQLite file; production must
    # override this with a PostgreSQL URL (postgresql+asyncpg://...).
    DATABASE_URL: str = "sqlite+aiosqlite:///./oj.db"

    # Auth
    JWT_SECRET: SecretStr | None = None
    JWT_ALGORITHM: str = "HS256"
    # access 令牌与 refresh 同寿命（30 天）：否则超过 2 小时就靠静默刷新续期，
    # 一旦刷新链路失败（换设备/离线后首次请求并发）就会被踢回登录页。
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30 * 24 * 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    BCRYPT_ROUNDS: int = 12
    # ESA AI CAPTCHA：先配置 ESA 规则、前端身份标/场景 ID，再于生产启用。
    # 开启后 /auth/login 和兼容入口 /tokens 均必须携带 ESA 验签参数。
    ESA_CAPTCHA_REQUIRED: bool = False
    # 令牌轮换宽限期（秒）：refresh 令牌一经使用即作废，但多标签页 / 并发请求
    # 会把同一个令牌几乎同时提交两次，输的一方拿到 401 就会被前端登出。
    # 宽限期内的重放视为同一次合法续期放行（受 /tokens/refresh 的 IP 限流约束）。
    REFRESH_ROTATION_GRACE_SECONDS: int = 60
    # 单用户最多保留的有效 refresh 行数。宽限期允许重放多签出几行，需设上限
    # 防止被循环重放撑爆；超出时撤销最早的行（正常多设备用量远低于此）。
    MAX_LIVE_REFRESH_TOKENS: int = 30

    # Runtime mode
    ENV: Literal["dev", "prod"] = "dev"

    # 额外允许的跨域来源（逗号分隔）。
    # 把 web/ 部署到 GitHub Pages 等静态托管时，需要把它的 origin 加进来，
    # 例如 CORS_EXTRA_ORIGINS=https://yourname.github.io（只填 scheme+host，
    # 不要带仓库子路径）。改完重启后端生效。
    CORS_EXTRA_ORIGINS: str = ""

    # ===== 防滥用 / 过载保护（见 app/core/guard.py）=====
    # 被扫描器/爬虫/CC 打的时候，源站不能把请求堆在队列里干等——Cloudflare
    # 等不到响应就是 522。这组开关让超限请求立刻拿到 502/503 而不是排队。
    # GUARD_ENABLED=None：只在 ENV=prod 生效（本地开发与测试套件不被限流打断）。
    GUARD_ENABLED: bool | None = None
    # 单 IP 限速：常规窗口 + 短时突发窗口（后者挡 CC）。
    # 数值刻意放宽——学校/机房大量用户共用出口 IP，按 IP 限太紧会误伤正常用户；
    # 真正兜底的是下面的并发保护。配成 0 / 负数 = 关掉这一项。
    GUARD_RATE_MAX: int = 600
    GUARD_RATE_WINDOW: int = 60
    GUARD_BURST_MAX: int = 120
    GUARD_BURST_WINDOW: int = 5
    # 限流后对外的状态码。默认 502 是**故意装成上游挂了**：
    #   429 等于明说「这里有限流，按 Retry-After 隔几秒再来」——爬虫/扫描器
    #   收到它就学会退避，然后接着来；502 看起来像站点/网关坏掉，更劝退，
    #   也不暴露限流器的存在与阈值。真实原因只写服务端日志。
    # 想恢复 RFC 6585 的语义（带 Retry-After 的 429）就把它改成 429。
    GUARD_RATE_STATUS: int = 502
    # 全站同时在处理的请求数上限（满了快速 503，不排队）；单 IP 并发上限防一个
    # 来源吃光全部额度。按「单 uvicorn 进程」估算，改大需同步确认数据库
    # max_connections 扛得住；被单来源攻击时可临时把后者调到 8~16。
    GUARD_MAX_CONCURRENCY: int = 64
    GUARD_MAX_PER_IP_CONCURRENCY: int = 48

    # 前端地址：邮件里的链接必须是绝对地址（密码重置等）。
    # 本地开发默认指向前端 dev server；**生产必须改成真实域名**，
    # 否则用户收到的重置链接会指向 localhost（启动时会直接报错拦下）。
    FRONTEND_URL: str = "http://localhost:5173"

    # go-judge 评测沙箱地址（宿主机 systemd 服务）
    GO_JUDGE_URL: str = "http://host.docker.internal:5050"

    # 备用评测机（逗号分隔，可配多台做故障切换）。
    # 只有在 GO_JUDGE_URL 这台连不上 / 返回 5xx 时才会启用，
    # 属于「故障转移」而非负载均衡：正常时全部流量仍走主用那台。
    # ⚠️ go-judge 没有鉴权，且它能执行任意选手代码，公网机器务必在安全组/防火墙
    #    上只放行 OJ 服务器的出口 IP（本项目生产环境主用那台就只走内网 5050）。
    GO_JUDGE_FALLBACK_URLS: str = ""

    # 某台评测机失败后的「冷却」秒数：期间优先使用其它评测机，
    # 避免主用挂了之后每条提交都要先白等一次连接超时。
    GO_JUDGE_FAILOVER_COOLDOWN_SECONDS: int = 60

    # 是否启用 GCC 禁止选手优化 pragma 插件（/usr/local/lib/oj/no_opt_pragma.so）
    # 默认关闭；开启时若沙箱环境未部署插件将自动安全降级为标准编译，避免因插件缺失导致全站 C/C++ CE
    ENABLE_NO_OPT_PRAGMA_PLUGIN: bool = False

    # 图床（/images）
    # 「高级空间」与「普通空间」双配额，规则参照洛谷：
    #   无水印 或 体积超过阈值的图 → 占用高级空间；带水印且不超阈值 → 普通空间
    IMAGE_PREMIUM_QUOTA_BYTES: int = 10 * 1024 * 1024   # 高级空间 10MB
    IMAGE_BASIC_QUOTA_BYTES: int = 50 * 1024 * 1024     # 普通空间 50MB
    IMAGE_PREMIUM_SIZE_THRESHOLD: int = 500 * 1024      # 超过 500KB 强制占用高级空间
    IMAGE_MAX_FILE_BYTES: int = 10 * 1024 * 1024        # 单张图片上限 10MB

    # 图床水印：在右下角盖一行站点名文字（参照洛谷，用站点名而不是 logo）
    IMAGE_WATERMARK_TEXT: str = "NLNOJ"
    IMAGE_WATERMARK_FONT: str | None = None             # 自定义字体路径，留空自动查找
    IMAGE_WATERMARK_OPACITY: int = 140                  # 水印不透明度 0-255

    # 云剪贴板（/clipboard）
    CLIPBOARD_MAX_ITEMS: int = 50                       # 单用户最多保留 50 条
    CLIPBOARD_MAX_TEXT_LEN: int = 20000                 # 单条最多 20000 字符
    CLIPBOARD_CODE_MAX_ITEMS: int = 10                  # 单用户保留 10 份代码片段（代码版）

    # 题目附件落盘根目录（私密存储，不挂在 /static 下）
    # 默认相对 service/ 的 ../storage/private/problem_attachments；
    # 生产环境用 ATTACHMENT_STORAGE_ROOT 指向与 volume 一致的绝对路径，
    # 避免因容器 working_dir 变化导致文件「读不到」却静默新建目录。
    ATTACHMENT_STORAGE_ROOT: str = "storage/private/problem_attachments"

    # 邮件发信限流（保护 SMTP 账号不被判定「异常发信」而封禁）
    # 注册开学高峰如果被卡，调大这两个值即可（改 .env 重启容器，不用改代码）
    EMAIL_SEND_GLOBAL_PER_HOUR: int = 100               # 全站每小时发信上限
    EMAIL_SEND_PER_EMAIL_DAY: int = 5                   # 同一邮箱每天上限

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @model_validator(mode="after")
    def _enforce_prod_config(self) -> "Settings":
        if self.ENV == "prod":
            # Prod must provide an explicit JWT secret and a non-SQLite database.
            if not (self.JWT_SECRET and self.JWT_SECRET.get_secret_value()):
                raise RuntimeError("JWT_SECRET must be set when ENV=prod")
            if self.DATABASE_URL.startswith("sqlite"):
                raise RuntimeError(
                    "DATABASE_URL must point to PostgreSQL when ENV=prod"
                )
            if "localhost" in self.FRONTEND_URL or "127.0.0.1" in self.FRONTEND_URL:
                raise RuntimeError(
                    "FRONTEND_URL must be the public site URL when ENV=prod, "
                    "otherwise password-reset emails point users at localhost. "
                    "e.g. FRONTEND_URL="
                )
            return self
        # dev: if no secret is provided, generate a stable per-process one
        # (cached once on the instance, NOT re-randomized on every read).
        if not (self.JWT_SECRET and self.JWT_SECRET.get_secret_value()):
            object.__setattr__(self, "JWT_SECRET", SecretStr(secrets.token_urlsafe(32)))
        return self

    @property
    def jwt_secret(self) -> str:
        """Plain-text JWT secret. Safe: the validator guarantees it is set."""
        assert self.JWT_SECRET is not None  # noqa: S101
        return self.JWT_SECRET.get_secret_value()

    @property
    def go_judge_endpoints(self) -> list[str]:
        """评测机列表：主用在前，备用在后（去重、去尾部斜杠、保持书写顺序）。

        ``GO_JUDGE_FALLBACK_URLS`` 用逗号分隔而不是声明成 list 字段——
        pydantic-settings 会把 list 类型的环境变量当 JSON 解析，
        让运维写成 ``a,b`` 必然报错，这里手工切分更不容易踩坑。
        """
        raw = [self.GO_JUDGE_URL, *self.GO_JUDGE_FALLBACK_URLS.split(",")]
        out: list[str] = []
        for item in raw:
            url = item.strip().rstrip("/")
            if url and url not in out:
                out.append(url)
        return out


settings = Settings()
