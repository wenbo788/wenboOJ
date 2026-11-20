"""全站防滥用 / 过载保护（ASGI 中间件）。

为什么需要它：线上是「单 uvicorn 进程 + PostgreSQL」，一旦被打（扫描器、
爬虫、CC），请求会在 uvicorn 的事件循环和数据库连接池里**排队**——每个请求
都还在等资源，Cloudflare 等不到响应就报 522（源站连接/响应超时），而且排队
会把本来正常的用户一起拖死。

这里的策略是**快速放弃**而不是排队：

1. 扫描路径（``.php`` / ``.env`` / ``wp-*`` …）直接 404，不碰数据库；
2. 按客户端 IP 限速（滑动窗口 + 短时突发窗口），超了返回 **502**（默认；
   见 ``GUARD_RATE_STATUS``）—— 对外装成「上游挂了」，而不是用 429 明说
   「你被限流了、隔几秒再来」。429 会教会爬虫退避后继续来，还会暴露限流器
   的存在与阈值；502 只让人以为站点坏了。真实原因只写服务端日志；
3. 全站并发上限（信号量），满了立刻 503，绝不排队等——让 CF/浏览器马上
   拿到一个明确的错误，而不是把源站拖到超时；
4. 单 IP 并发上限，防止一个来源把整个并发额度吃光。

IP 取值统一走 ``app.utils.ip.get_client_ip``（宝塔覆盖式注入的 X-Real-IP），
不能用 X-Forwarded-For，那个客户端可以伪造。

计数在进程内存里（``app.utils.ratelimit`` 同款实现），与当前「生产单进程
部署」的约定一致；将来上多 worker 需要换成 Redis 计数。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Callable

from app.utils.ip import get_client_ip_from_scope
from app.utils.ratelimit import check as rate_check

logger = logging.getLogger(__name__)

# 扫描器 / 探测路径：命中直接 404，不进路由、不查库。
# 分两类规则（这个站是 Python/Vue，根本不提供 PHP/CGI 动态页面）：
#   ① 前缀类：版本控制目录、配置泄漏、常见后台；
#   ② 后缀类：任何服务端脚本 / 备份 / 配置后缀。用后缀而不是枚举文件名，
#      是为了连「随便起个名字的 .php」一起挡掉，同时不误伤正常业务路径
#      （上传的附件走 /static/ 前缀，已豁免）。
_SCANNER_PREFIX_RE = re.compile(
    r"(?i)^/(?:"
    r"\.(?:env|git|svn|hg|aws|ssh|htaccess|htpasswd|DS_Store)"
    r"|wp-(?:admin|content|includes|login|json|xmlrpc)"
    r"|phpmyadmin|pma|adminer|myadmin|xmlrpc"
    r"|vendor/|node_modules/|cgi-bin/"
    r")"
)
_SCANNER_SUFFIX_RE = re.compile(
    r"(?i)\.(?:php\d?|phtml|asp|aspx|jsp|jspx|cgi|pl"
    r"|sql|bak|old|orig|save|swp|swo|env|ini|log|lock|sqlite|db)$"
)


def is_scanner_path(path: str) -> bool:
    """是不是扫描器/探测路径（命中就直接 404）。"""
    return bool(_SCANNER_PREFIX_RE.match(path) or _SCANNER_SUFFIX_RE.search(path))


# 不需要防护的路径：健康检查、静态资源、接口文档（nginx 正常也会直接吐静态，
# 这里只是让「直连后端」的场景不被误伤）。
_EXEMPT_PREFIXES = ("/static/", "/assets/", "/favicon", "/docs", "/openapi.json")

# 429/503 的提示：给用户看的话，也给 CF/监控看的状态码
_TOO_MANY = "请求过于频繁，请稍后再试"
_BUSY = "服务器繁忙，请稍后重试"
# 502 时用的响应体：不确定对方是谁，就别透露限流这回事（见模块说明第 2 条）
_BAD_GATEWAY = "Bad Gateway"


def _rate_limited_body(status: int) -> str:
    """限流响应体跟着状态码走：429 才说「请求过于频繁」，其余一律装网关错误。"""
    return _TOO_MANY if status == 429 else _BAD_GATEWAY


class AbuseGuardMiddleware:
    """按 IP 限流 + 并发保护 + 扫描路径拦截。

    ``settings.GUARD_ENABLED`` 为 None 时**只在 ENV=prod 生效**：本地开发与
    测试套件不会被限流打断（测试里直接构造并显式打开来验证行为）。
    """

    def __init__(self, app: Any, settings: Any) -> None:
        self.app = app
        self.settings = settings
        # 并发计数：全站与单 IP 的「检查 + 占位」必须在同一把锁内完成。
        # 不用 asyncio.Semaphore 的原因：``sem.locked()`` 检查与 ``async with sem``
        # 获取之间存在 await 点，极端并发下会在信号量上排队——而本模块的整个
        # 设计意图就是「绝不排队，立刻 503」。
        self._total_inflight = 0
        self._inflight: dict[str, int] = {}
        self._lock = asyncio.Lock()
        # 被限流/拒绝的日志按 IP 去重，避免刷爆日志本身
        self._last_log: dict[str, float] = {}

    # ---------------- 内部工具 ----------------

    @property
    def enabled(self) -> bool:
        flag = getattr(self.settings, "GUARD_ENABLED", None)
        if flag is not None:
            return bool(flag)
        return getattr(self.settings, "ENV", "dev") == "prod"

    def _log_once(self, key: str, level: int, msg: str, *args: Any) -> None:
        now = time.monotonic()
        if now - self._last_log.get(key, 0.0) < 30:
            return
        self._last_log[key] = now
        if len(self._last_log) > 10_000:  # 防 IP 池撑爆内存
            cutoff = now - 300
            for k in [k for k, t in self._last_log.items() if t < cutoff]:
                del self._last_log[k]
        logger.log(level, msg, *args)

    async def _send_json(
        self, send: Callable, status: int, detail: str, retry_after: int | None = None
    ) -> None:
        """直接吐一个 JSON 错误响应。

        ``retry_after`` 为 None 时不带 ``Retry-After`` —— 限流默认伪装成 502
        网关错误，一个真的坏掉的上游不会告诉对方「几秒后再来」（那等于承认
        是自己主动把请求挡回去的）。
        """
        body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
        headers = [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(body)).encode()),
            (b"cache-control", b"no-store"),
        ]
        if retry_after is not None:
            headers.append((b"retry-after", str(retry_after).encode()))
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": headers,
        })
        await send({"type": "http.response.body", "body": body})

    # ---------------- 入口 ----------------

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http" or not self.enabled:
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "/")
        method: str = scope.get("method", "GET")

        if path.startswith(_EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return

        # CORS 预检不消耗额度（浏览器自动发，量大且无成本）
        if method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        if is_scanner_path(path):
            self._log_once(f"scan:{path}", logging.INFO, "拦截扫描路径: %s", path)
            await self._send_json(send, 404, "Not Found", 3600)
            return

        request_ip = get_client_ip_from_scope(scope)

        # ① 按 IP 限速：常规窗口 + 短时突发窗口。
        # 上限配成 0 / 负数表示**关掉这一项**：学校、机房常共用出口 IP，
        # 按 IP 限速太紧会连正常用户一起挡；此时只靠下面的并发保护兜底。
        rate_max = int(getattr(self.settings, "GUARD_RATE_MAX", 600))
        burst_max = int(getattr(self.settings, "GUARD_BURST_MAX", 120))
        ok, wait = (True, 0)
        if rate_max > 0:
            ok, wait = rate_check(
                f"guard:{request_ip}", rate_max,
                int(getattr(self.settings, "GUARD_RATE_WINDOW", 60)),
            )
        if ok and burst_max > 0:
            ok, wait = rate_check(
                f"guard-burst:{request_ip}", burst_max,
                int(getattr(self.settings, "GUARD_BURST_WINDOW", 5)),
            )
        if not ok:
            # 对外状态码默认 502（伪装成上游挂了，见模块说明第 2 条）：
            # 只有配成 429 时才带 Retry-After —— 那是在明说「就是限流」。
            status = int(getattr(self.settings, "GUARD_RATE_STATUS", 502))
            self._log_once(
                f"rate:{request_ip}", logging.WARNING,
                "限流触发 ip=%s path=%s（%ss 后重试，对外返回 %s）",
                request_ip, path, wait, status,
            )
            await self._send_json(
                send, status, _rate_limited_body(status),
                wait if status == 429 else None,
            )
            return

        # ② + ③ 并发准入：全站上限与单 IP 上限在**同一次持锁**内检查并占位，
        # 满了直接 503 走人——不存在「先放行再排队」，也不会有检查/占位的竞态。
        max_concurrency = int(getattr(self.settings, "GUARD_MAX_CONCURRENCY", 64))
        per_ip_limit = int(getattr(self.settings, "GUARD_MAX_PER_IP_CONCURRENCY", 48))
        reason = ""
        async with self._lock:
            if 0 < max_concurrency <= self._total_inflight:
                reason = "total"
            elif 0 < per_ip_limit <= self._inflight.get(request_ip, 0):
                reason = "ip"
            else:
                # 占位成功：这两个计数在 finally 里一定要还回去
                self._total_inflight += 1
                if per_ip_limit > 0:
                    self._inflight[request_ip] = self._inflight.get(request_ip, 0) + 1
        if reason == "ip":
            self._log_once(
                f"ipconc:{request_ip}", logging.WARNING,
                "单 IP 并发超限 ip=%s（%s）path=%s", request_ip, per_ip_limit, path,
            )
            await self._send_json(send, 503, _BUSY, 2)
            return
        if reason:
            self._log_once(
                "concurrency", logging.WARNING,
                "并发已达上限（%s），快速拒绝 path=%s", max_concurrency, path,
            )
            await self._send_json(send, 503, _BUSY, 2)
            return

        try:
            await self.app(scope, receive, send)
        finally:
            async with self._lock:
                self._total_inflight -= 1
                left = self._inflight.get(request_ip, 0) - 1
                if left > 0:
                    self._inflight[request_ip] = left
                else:
                    self._inflight.pop(request_ip, None)
