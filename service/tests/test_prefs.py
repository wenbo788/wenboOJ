"""个人偏好回归测试：代码模板 / 等宽字体的默认、持久化与校验边界。"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_user_prefs_template_and_font():
    """默认为空、写入/持久化、语言与字体白名单、长度与类型校验、恢复默认。"""
    suffix = uuid.uuid4().hex[:8]
    user, pwd = f"pref_{suffix}", "supersecret1"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/users", json={
            "username": user, "email": f"{user}@example.com", "password": pwd})
        assert r.status_code == 201, r.text
        r = await ac.post("/tokens", data={"username": user, "password": pwd})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # 注册后默认：模板与字体皆空（前端此时用内置默认）
        r = await ac.get("/auth/me", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["code_template"] is None
        assert r.json()["code_font"] is None

        # 保存模板 + 字体 → 返回并持久化
        r = await ac.put("/users/me/prefs", json={
            "code_template": {
                "cpp": "#include <bits/stdc++.h>\n// my template",
                "python3": "print('hi')",
            },
            "code_font": "ibm-plex-mono",
        }, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["code_template"]["cpp"].startswith("#include")
        assert body["code_font"] == "ibm-plex-mono"
        r = await ac.get("/auth/me", headers=h)
        assert r.json()["code_font"] == "ibm-plex-mono"
        assert r.json()["code_template"]["python3"] == "print('hi')"
        assert "c" not in r.json()["code_template"]  # 缺省语言 = 内置默认

        # 字体白名单：未知字体（含类型不对）→ 400
        for bad in ("comic-sans", "", True, 42):
            r = await ac.put("/users/me/prefs", json={"code_font": bad}, headers=h)
            assert r.status_code == 400, bad
        # 通过后回读仍是上一次合法值
        r = await ac.get("/auth/me", headers=h)
        assert r.json()["code_font"] == "ibm-plex-mono"

        # 语言白名单：未知语言 → 400
        r = await ac.put("/users/me/prefs",
                         json={"code_template": {"rust": "fn main() {}"}}, headers=h)
        assert r.status_code == 400, r.text

        # 模板类型与长度校验 → 400
        r = await ac.put("/users/me/prefs",
                         json={"code_template": {"cpp": 123}}, headers=h)
        assert r.status_code == 400, r.text
        r = await ac.put("/users/me/prefs",
                         json={"code_template": {"cpp": "x" * 50_001}}, headers=h)
        assert r.status_code == 400, r.text
        r = await ac.put("/users/me/prefs",
                         json={"code_template": ["cpp"]}, headers=h)
        assert r.status_code == 400, r.text

        # null = 恢复默认（两者都清空）
        r = await ac.put("/users/me/prefs",
                         json={"code_template": None, "code_font": None}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["code_template"] is None
        assert r.json()["code_font"] is None
        r = await ac.get("/auth/me", headers=h)
        assert r.json()["code_template"] is None
        assert r.json()["code_font"] is None


@pytest.mark.asyncio
async def test_user_prefs_independent_updates():
    """两个键互相独立：只传一个键时另一个保持不变。"""
    suffix = uuid.uuid4().hex[:8]
    user, pwd = f"pref2_{suffix}", "supersecret1"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/users", json={
            "username": user, "email": f"{user}@example.com", "password": pwd})
        assert r.status_code == 201, r.text
        r = await ac.post("/tokens", data={"username": user, "password": pwd})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}

        r = await ac.put("/users/me/prefs",
                         json={"code_font": "space-mono"}, headers=h)
        assert r.status_code == 200, r.text

        # 只改模板 → 字体不动
        r = await ac.put("/users/me/prefs",
                         json={"code_template": {"c": "// c template"}}, headers=h)
        assert r.status_code == 200, r.text
        r = await ac.get("/auth/me", headers=h)
        assert r.json()["code_font"] == "space-mono"
        assert r.json()["code_template"] == {"c": "// c template"}

        # 未登录 → 401
        r = await ac.put("/users/me/prefs", json={"code_font": None})
        assert r.status_code == 401, r.text
