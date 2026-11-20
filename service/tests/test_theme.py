"""主题商店回归测试：上传/预设/开关/清除与权限边界。"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.mark.asyncio
async def test_theme_upload_preset_toggle_and_clear():
    suffix = uuid.uuid4().hex[:8]
    user, pwd = f"th_{suffix}", "supersecret1"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/users", json={
            "username": user, "email": f"{user}@example.com", "password": pwd})
        assert r.status_code == 201, r.text
        r = await ac.post("/tokens", data={"username": user, "password": pwd})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # 上传背景 → 自动启用
        r = await ac.post("/users/me/theme/background",
                          files={"file": (f"bg_{suffix}.png", PNG_BYTES, "image/png")},
                          headers=h)
        assert r.status_code == 200, r.text
        bg = r.json()["theme_background"]
        assert bg.startswith("/static/uploads/themes/") and bg.endswith(".png")
        assert r.json()["theme_enabled"] is True

        # /auth/me 能拿到主题状态
        r = await ac.get("/auth/me", headers=h)
        assert r.json()["theme_background"] == bg
        assert r.json()["theme_enabled"] is True

        # 切到内置渐变
        r = await ac.put("/users/me/theme", json={"background": "preset:dusk"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["theme_background"] == "preset:dusk"

        # 未知预设 → 400
        r = await ac.put("/users/me/theme", json={"background": "preset:nope"}, headers=h)
        assert r.status_code == 400, r.text

        # 允许外部图片 URL（http/https）
        r = await ac.put("/users/me/theme",
                         json={"background": "https://example.com/bg.png"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["theme_background"] == "https://example.com/bg.png"

        # 非法路径（非 static 目录、非外部 URL、非预设）→ 400
        r = await ac.put("/users/me/theme",
                         json={"background": "javascript:alert(1)"}, headers=h)
        assert r.status_code == 400, r.text

        # 切回内置渐变
        r = await ac.put("/users/me/theme", json={"background": "preset:dusk"}, headers=h)
        assert r.status_code == 200, r.text

        # 停用（保留选择）
        r = await ac.put("/users/me/theme", json={"enabled": False}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["theme_enabled"] is False
        assert r.json()["theme_background"] == "preset:dusk"

        # 清除（恢复默认 + 停用）
        r = await ac.put("/users/me/theme", json={"background": None}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["theme_background"] is None
        assert r.json()["theme_enabled"] is False

        # 清空状态下启用 → 400
        r = await ac.put("/users/me/theme", json={"enabled": True}, headers=h)
        assert r.status_code == 400, r.text

        # 非图片类型 → 400
        r = await ac.post("/users/me/theme/background",
                          files={"file": ("a.txt", b"hello", "text/plain")},
                          headers=h)
        assert r.status_code == 400, r.text

        # 未登录 → 401
        r = await ac.put("/users/me/theme", json={"enabled": True})
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_theme_hue_adjust():
    """色相调整：默认 0、写入/持久化、范围与类型校验、与背景开关独立。"""
    suffix = uuid.uuid4().hex[:8]
    user, pwd = f"hue_{suffix}", "supersecret1"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/users", json={
            "username": user, "email": f"{user}@example.com", "password": pwd})
        assert r.status_code == 201, r.text
        r = await ac.post("/tokens", data={"username": user, "password": pwd})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # 注册后默认 0，/auth/me 同步
        r = await ac.get("/auth/me", headers=h)
        assert r.json()["theme_hue"] == 0

        # 写入合法值 → 返回并持久化（与 theme_enabled 独立：背景未启用也能调）
        r = await ac.put("/users/me/theme", json={"hue": 120}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["theme_hue"] == 120
        assert r.json()["theme_enabled"] is False
        r = await ac.get("/auth/me", headers=h)
        assert r.json()["theme_hue"] == 120

        # 边界值合法
        for v in (-180, 180, 0):
            r = await ac.put("/users/me/theme", json={"hue": v}, headers=h)
            assert r.status_code == 200, r.text
            assert r.json()["theme_hue"] == v

        # 超范围 → 400
        for v in (181, -181, 9999):
            r = await ac.put("/users/me/theme", json={"hue": v}, headers=h)
            assert r.status_code == 400, v

        # 非整数（含 bool）→ 400
        for v in ("120", 12.5, True, None):
            r = await ac.put("/users/me/theme", json={"hue": v}, headers=h)
            assert r.status_code == 400, v
