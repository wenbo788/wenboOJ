"""主题商店「深色主题」开关（users.theme_mode）。

规则：
  - PUT /users/me/theme 接受 mode: light | dark，其他值 400
  - 保存后 /auth/me 与 UserOut 系接口回传 theme_mode（前端据此挂
    html[data-theme="dark"] 翻转设计令牌）
  - 默认 light：没动过开关的用户行为零变化
  - 独立于 theme_enabled：不启用背景主题也能用深色
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


async def _register(ac: AsyncClient) -> tuple[dict[str, str], dict]:
    suffix = uuid.uuid4().hex[:8]
    username = f"tm_{suffix}"
    password = "supersecret1"
    r = await ac.post(
        "/users",
        json={"username": username, "email": f"{username}@example.com", "password": password},
    )
    assert r.status_code == 201, r.text
    r = await ac.post("/tokens", data={"username": username, "password": password})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await ac.get("/auth/me", headers=h)).json()
    return h, me


@pytest.mark.asyncio
async def test_theme_mode_toggle_and_persist():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h, me = await _register(ac)

        # 默认 light
        assert me.get("theme_mode") == "light", me

        # 切深色：接口返回 + /auth/me 持久回读
        r = await ac.put("/users/me/theme", json={"mode": "dark"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["theme_mode"] == "dark"
        me = (await ac.get("/auth/me", headers=h)).json()
        assert me["theme_mode"] == "dark"

        # UserOut 系接口（前端拿用户资料的另一条路）同样回传
        r = await ac.get(f"/users/{me['id']}", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["theme_mode"] == "dark"

        # 独立于背景开关：没启用背景主题也保持 dark
        assert me["theme_enabled"] is False

        # 切回浅色
        r = await ac.put("/users/me/theme", json={"mode": "light"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["theme_mode"] == "light"


@pytest.mark.asyncio
async def test_theme_mode_invalid_value_rejected():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h, _me = await _register(ac)
        r = await ac.put("/users/me/theme", json={"mode": "blue"}, headers=h)
        assert r.status_code == 400, r.text
        assert "light" in r.json()["detail"]
