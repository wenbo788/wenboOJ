"""主题商店「洛谷风格主页」开关（users.home_style）。

规则：
  - PUT /users/me/theme 接受 home_style: cloud | luogu，其他值 400
  - 保存后 /auth/me 与 UserOut 系接口回传 home_style（前端据此把首页
    分发到 HomeCloud / HomeLuogu 两套布局）
  - 默认 cloud：没动过开关的用户看新版云图首页，行为零变化
  - 独立于 theme_mode / theme_enabled：切风格不带动深色主题
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


async def _register(ac: AsyncClient) -> tuple[dict[str, str], dict]:
    suffix = uuid.uuid4().hex[:8]
    username = f"hs_{suffix}"
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
async def test_home_style_toggle_and_persist():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h, me = await _register(ac)

        # 默认 cloud（新版云图首页）
        assert me.get("home_style") == "cloud", me

        # 切洛谷风格：接口返回 + /auth/me 持久回读
        r = await ac.put("/users/me/theme", json={"home_style": "luogu"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["home_style"] == "luogu"
        me = (await ac.get("/auth/me", headers=h)).json()
        assert me["home_style"] == "luogu"

        # UserOut 系接口同样回传
        r = await ac.get(f"/users/{me['id']}", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["home_style"] == "luogu"

        # 独立于深色主题：没动过 mode 的用户仍是 light
        assert me["theme_mode"] == "light"

        # 切回云图首页
        r = await ac.put("/users/me/theme", json={"home_style": "cloud"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["home_style"] == "cloud"


@pytest.mark.asyncio
async def test_home_style_invalid_value_rejected():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h, _me = await _register(ac)
        r = await ac.put(
            "/users/me/theme", json={"home_style": "classic"}, headers=h
        )
        assert r.status_code == 400, r.text
        assert "cloud" in r.json()["detail"]
