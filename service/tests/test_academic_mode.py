"""学术模式开关：默认关闭、开关持久化、类型校验、未登录不可改、他人不可见。

学术模式是用户的自律偏好，服务端只负责存与取，不据此拒绝任何请求
（犇犇/灌水区/难度的隐藏都在前端）。这里守住五件事：
默认值是关、开关能持久化、传非布尔值要被拦下、没登录改不了、
以及别人的公开主页看不到你这个字段。
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


async def _register_and_login(ac: AsyncClient) -> tuple[dict, str]:
    """注册并登录一个随机用户，返回 (认证头, 用户名)。"""
    suffix = uuid.uuid4().hex[:8]
    user, pwd = f"acad_{suffix}", "supersecret1"
    r = await ac.post("/users", json={
        "username": user, "email": f"{user}@example.com", "password": pwd})
    assert r.status_code == 201, r.text
    r = await ac.post("/tokens", data={"username": user, "password": pwd})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, user


@pytest.mark.asyncio
async def test_academic_mode_defaults_off_and_persists():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h, _ = await _register_and_login(ac)

        # 注册后默认关闭（存量用户也一样，因此行为不变）
        me = (await ac.get("/auth/me", headers=h)).json()
        assert me["academic_mode"] is False

        # 开启 → 响应回显 + /auth/me 持久化
        r = await ac.put("/users/me/prefs", json={"academic_mode": True}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["academic_mode"] is True
        assert (await ac.get("/auth/me", headers=h)).json()["academic_mode"] is True

        # 关闭 → 同样持久化
        r = await ac.put("/users/me/prefs", json={"academic_mode": False}, headers=h)
        assert r.status_code == 200, r.text
        assert (await ac.get("/auth/me", headers=h)).json()["academic_mode"] is False


@pytest.mark.asyncio
async def test_academic_mode_rejects_non_boolean():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h, _ = await _register_and_login(ac)

        # 字符串 / 数字都不认（True 是 bool 的子类，这里用 "true" 与 1 探边界）
        for bad in ("true", 1):
            r = await ac.put("/users/me/prefs", json={"academic_mode": bad}, headers=h)
            assert r.status_code == 400, f"{bad!r} 应被拒绝：{r.text}"

        # 被拒后不应把值改脏
        assert (await ac.get("/auth/me", headers=h)).json()["academic_mode"] is False


@pytest.mark.asyncio
async def test_academic_mode_requires_auth():
    """没带 token 改不了偏好 —— 这条靠 get_current_user 依赖兜着，顺手锁住别被放宽。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.put("/users/me/prefs", json={"academic_mode": True})
        assert r.status_code in (401, 403), r.text

        # 乱塞的 token 同样不行
        r = await ac.put(
            "/users/me/prefs",
            json={"academic_mode": True},
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert r.status_code in (401, 403), r.text


@pytest.mark.asyncio
async def test_academic_mode_not_exposed_to_others():
    """这个字段只在本人响应里：公开主页（他人 / 匿名可见）不许带出去。

    字段放在 ``SelfUserOut`` 而不是共享的 ``UserOut``，就是靠这条锁住——
    谁哪天把它挪回 ``UserOut``，这里会直接红。
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h, user = await _register_and_login(ac)
        r = await ac.put("/users/me/prefs", json={"academic_mode": True}, headers=h)
        assert r.status_code == 200, r.text

        # 本人：两个「自己」的端点都要回显
        assert (await ac.get("/auth/me", headers=h)).json()["academic_mode"] is True
        assert (await ac.get("/users/me", headers=h)).json()["academic_mode"] is True

        # 他人 / 匿名：公开主页不含该字段
        pub = await ac.get(f"/users/by-username/{user}")
        assert pub.status_code == 200, pub.text
        assert "academic_mode" not in pub.json(), "学术模式泄露到公开主页了"
