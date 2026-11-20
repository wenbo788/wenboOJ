"""全站防滥用中间件（app/core/guard.py）的行为测试。

这里用一个可控的「假后端」包在中间件里，直接验证线上要的行为：

1. 扫描路径（.php/.env/wp-*）直接 404，**不进入后端**（省掉一次查库）
2. 单 IP 超速 → 502（伪装成上游挂了，不带 Retry-After）；突发窗口同样生效
3. 并发到上限 → **立刻** 503（不排队；排队就是 Cloudflare 522 的成因）
4. 单 IP 并发上限：一个来源吃不满整个站点的额度
5. X-Real-IP 是分 IP 记账的依据（不同 IP 互不影响）
6. 预检 OPTIONS / 静态资源放行
7. 默认只在 ENV=prod 开启 —— 本地开发与测试套件不会被误伤
"""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.guard import AbuseGuardMiddleware
from app.utils import ratelimit


class FakeBackend:
    """假后端：记录被调用次数，可配置处理耗时。"""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.calls = 0
        self.inflight = 0
        self.max_inflight = 0

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        self.calls += 1
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            body = b'{"ok":true}'
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({"type": "http.response.body", "body": body})
        finally:
            self.inflight -= 1


def _settings(**over: Any) -> SimpleNamespace:
    base = dict(
        ENV="prod",
        GUARD_ENABLED=True,
        GUARD_RATE_MAX=100,
        GUARD_RATE_WINDOW=60,
        GUARD_BURST_MAX=100,
        GUARD_BURST_WINDOW=5,
        GUARD_MAX_CONCURRENCY=64,
        GUARD_MAX_PER_IP_CONCURRENCY=12,
        GUARD_RATE_STATUS=502,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _client(backend: FakeBackend, **over: Any) -> AsyncClient:
    app = AbuseGuardMiddleware(backend, settings=_settings(**over))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.fixture(autouse=True)
def _clean_limits():
    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.mark.asyncio
async def test_scanner_paths_are_rejected_without_touching_backend():
    backend = FakeBackend()
    async with _client(backend) as ac:
        for path in ("/wp-login.php", "/.env", "/.git/config", "/phpmyadmin/index.php",
                     "/admin.php", "/backup.sql", "/vendor/autoload.php"):
            r = await ac.get(path)
            assert r.status_code == 404, f"{path} → {r.status_code}"
        # 正常业务路径不拦
        r = await ac.get("/problems")
        assert r.status_code == 200
    assert backend.calls == 1, "扫描路径不应该进入后端"


@pytest.mark.asyncio
async def test_rate_limit_returns_502_like_broken_gateway():
    """被限流时对外是 502 + 泛化的网关错误体，**不带** Retry-After。

    这是刻意的：429 + Retry-After 等于明说「这里有限流，隔几秒再来」，会教会
    爬虫退避后继续来，也暴露限流器的存在与阈值；502 只让人以为站点挂了。
    """
    backend = FakeBackend()
    async with _client(backend, GUARD_RATE_MAX=3, GUARD_BURST_MAX=100) as ac:
        for _ in range(3):
            assert (await ac.get("/problems")).status_code == 200
        r = await ac.get("/problems")
        assert r.status_code == 502, r.text
        assert "retry-after" not in {k.lower() for k in r.headers}
        assert r.json()["detail"] == "Bad Gateway"
        assert "频繁" not in r.text, "502 不该承认自己被限流了"

    # 突发窗口：常规额度还够，但 5 秒内连打太多也要挡
    # （同一进程的计数桶是共享的，换客户端前先清账，避免上一段把这段打满）
    ratelimit.reset()
    backend2 = FakeBackend()
    async with _client(backend2, GUARD_RATE_MAX=1000, GUARD_BURST_MAX=2) as ac:
        assert (await ac.get("/problems")).status_code == 200
        assert (await ac.get("/problems")).status_code == 200
        assert (await ac.get("/problems")).status_code == 502
    assert backend2.calls == 2


@pytest.mark.asyncio
async def test_rate_limit_status_is_configurable_back_to_429():
    """想按 RFC 6585 明说「你被限流了」时，GUARD_RATE_STATUS=429 就回到旧行为。"""
    backend = FakeBackend()
    async with _client(backend, GUARD_RATE_MAX=1, GUARD_BURST_MAX=100,
                       GUARD_RATE_STATUS=429) as ac:
        assert (await ac.get("/problems")).status_code == 200
        r = await ac.get("/problems")
        assert r.status_code == 429, r.text
        assert int(r.headers["retry-after"]) >= 1
        assert "频繁" in r.json()["detail"]


@pytest.mark.asyncio
async def test_concurrency_cap_sheds_load_fast_instead_of_queueing():
    """并发满了要立刻 503：绝不排队（排队 → CF 522）。"""
    backend = FakeBackend(delay=0.4)
    async with _client(
        backend, GUARD_MAX_CONCURRENCY=2, GUARD_MAX_PER_IP_CONCURRENCY=64
    ) as ac:
        started = time.monotonic()
        results = await asyncio.gather(
            *[ac.get("/problems", headers={"X-Real-IP": f"10.0.0.{i}"}) for i in range(8)]
        )
        elapsed = time.monotonic() - started
        codes = sorted(r.status_code for r in results)

    assert codes.count(503) >= 1, f"应有一批被快速拒绝: {codes}"
    assert codes.count(200) == 2, f"只应该放行并发额度内的请求: {codes}"
    for r in results:
        if r.status_code == 503:
            assert r.headers["retry-after"] == "2"
    # 被拒的请求必须是「立刻」返回：整体耗时不该排队成 8×0.4s
    assert elapsed < 1.0, f"拒绝请求不该排队等待：{elapsed:.2f}s"
    assert backend.max_inflight <= 2


@pytest.mark.asyncio
async def test_per_ip_concurrency_limits_one_source():
    backend = FakeBackend(delay=0.3)
    async with _client(
        backend, GUARD_MAX_CONCURRENCY=8, GUARD_MAX_PER_IP_CONCURRENCY=1
    ) as ac:
        same_ip = [ac.get("/problems", headers={"X-Real-IP": "1.2.3.4"}) for _ in range(4)]
        other_ip = ac.get("/problems", headers={"X-Real-IP": "5.6.7.8"})
        results = await asyncio.gather(*same_ip, other_ip)
        codes = [r.status_code for r in results]

    assert codes.count(200) == 2, f"同一 IP 只放 1 个，另一个 IP 不受影响: {codes}"
    assert codes.count(503) == 3
    assert backend.max_inflight <= 2


@pytest.mark.asyncio
async def test_limits_are_counted_per_real_ip():
    """X-Real-IP 才是记账依据：宝塔覆盖式注入，客户端伪造无效。"""
    backend = FakeBackend()
    async with _client(backend, GUARD_RATE_MAX=2, GUARD_BURST_MAX=100) as ac:
        for _ in range(2):
            assert (await ac.get("/problems", headers={"X-Real-IP": "9.9.9.9"})).status_code == 200
        assert (await ac.get("/problems", headers={"X-Real-IP": "9.9.9.9"})).status_code == 502
        # 换一个 IP 不受影响
        assert (await ac.get("/problems", headers={"X-Real-IP": "8.8.8.8"})).status_code == 200


@pytest.mark.asyncio
async def test_preflight_and_static_are_exempt():
    backend = FakeBackend()
    async with _client(backend, GUARD_RATE_MAX=1, GUARD_BURST_MAX=100) as ac:
        assert (await ac.get("/problems")).status_code == 200
        # 常规额度已用完，但预检与静态资源不受限
        assert (await ac.options("/problems")).status_code == 200
        assert (await ac.get("/static/uploads/avatars/x.png")).status_code == 200
        assert (await ac.get("/problems")).status_code == 502


@pytest.mark.asyncio
async def test_disabled_in_dev_by_default():
    """默认（GUARD_ENABLED=None，ENV=dev）不启用：本地开发/测试套件不被误伤。"""
    backend = FakeBackend()
    app = AbuseGuardMiddleware(backend, settings=SimpleNamespace(
        ENV="dev", GUARD_ENABLED=None, GUARD_RATE_MAX=1, GUARD_RATE_WINDOW=60,
        GUARD_BURST_MAX=1, GUARD_BURST_WINDOW=5,
        GUARD_MAX_CONCURRENCY=1, GUARD_MAX_PER_IP_CONCURRENCY=1,
    ))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        for _ in range(5):
            assert (await ac.get("/problems")).status_code == 200
        # 扫描路径也不拦（开发环境要在意的是可调试性）
        assert (await ac.get("/wp-login.php")).status_code == 200


@pytest.mark.asyncio
async def test_real_app_blocks_scanner_paths_when_enabled(monkeypatch):
    """接到真 app 上也要生效（中间件注册顺序/开关接线正确）。"""
    from app.core.config import settings as real_settings
    from app.main import app

    monkeypatch.setattr(real_settings, "GUARD_ENABLED", True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/wp-login.php")
        assert r.status_code == 404
        assert r.json()["detail"] == "Not Found"


@pytest.mark.asyncio
async def test_db_pool_timeout_maps_to_503():
    """连接池排满 → 503 + Retry-After（而不是挂到 CF 超时）。"""
    from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

    from app.main import _db_pool_timeout_handler

    class _Req:
        method = "GET"

        class url:  # noqa: N801
            path = "/problems"

    resp = await _db_pool_timeout_handler(_Req(), SQLAlchemyTimeoutError("pool full"))
    assert resp.status_code == 503
    assert resp.headers["retry-after"] == "3"
    assert "繁忙" in resp.body.decode()


@pytest.mark.asyncio
async def test_inflight_counters_are_released_even_when_backend_raises():
    """并发计数必须还回去：漏了的话站点会被永久判定「已满」而全站 503。"""
    class Boom(FakeBackend):
        async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
            raise RuntimeError("后端炸了")

    guard = AbuseGuardMiddleware(Boom(), settings=_settings(GUARD_MAX_CONCURRENCY=4))
    async with AsyncClient(transport=ASGITransport(app=guard, raise_app_exceptions=False),
                           base_url="http://t") as ac:
        for _ in range(3):
            await ac.get("/problems", headers={"X-Real-IP": "7.7.7.7"})
    assert guard._total_inflight == 0, "全站并发计数泄漏"
    assert guard._inflight == {}, "单 IP 并发计数泄漏"

    # 计数正常归还后仍能继续服务
    ok = AbuseGuardMiddleware(FakeBackend(), settings=_settings(GUARD_MAX_CONCURRENCY=1))
    async with AsyncClient(transport=ASGITransport(app=ok), base_url="http://t") as ac:
        assert (await ac.get("/problems")).status_code == 200
        assert (await ac.get("/problems")).status_code == 200
    assert ok._total_inflight == 0


@pytest.mark.asyncio
async def test_send_json_escapes_detail():
    """响应体走 json.dumps 序列化：引号/反斜杠/中文都不能拼坏 JSON。"""
    guard = AbuseGuardMiddleware(FakeBackend(), settings=_settings())
    sent: list[dict] = []

    async def send(msg: dict) -> None:
        sent.append(msg)

    tricky = '有"引号"、反斜杠\\ 与中文'
    await guard._send_json(send, 429, tricky, 3)
    assert sent[0]["status"] == 429
    assert json.loads(sent[1]["body"])["detail"] == tricky
    assert int(dict(sent[0]["headers"])[b"retry-after"]) == 3
