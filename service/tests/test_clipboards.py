"""云剪贴板接口回归测试。"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


async def _reg_login(ac: AsyncClient, name: str):
    # conftest 是 session 级建库、用例间不清表，用户名必须带随机后缀，
    # 否则第二次 `pytest tests/`（-k 重跑 / CI 重试）会因用户名已存在返回 409 而全挂。
    name = f"{name}_{uuid.uuid4().hex[:8]}"
    r = await ac.post(
        "/users",
        json={
            "username": name,
            "email": f"{name}@example.com",
            "password": "supersecret1",
        },
    )
    assert r.status_code == 201, r.text
    r = await ac.post("/tokens", data={"username": name, "password": "supersecret1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.asyncio
async def test_create_and_list_text():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _reg_login(ac, "clip_text")

        r = await ac.post(
            "/clipboards",
            json={"kind": "text", "title": "备注", "content": "hello world"},
            headers=h,
        )
        assert r.status_code == 201, r.text
        item = r.json()
        assert item["kind"] == "text"
        assert item["title"] == "备注"
        assert item["content"] == "hello world"

        r = await ac.get("/clipboards", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["total"] >= 1


@pytest.mark.asyncio
async def test_code_item_with_language():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _reg_login(ac, "clip_code")

        r = await ac.post(
            "/clipboards",
            json={
                "kind": "code",
                "language": "cpp",
                "content": "#include<iostream>\nint main(){return 0;}",
            },
            headers=h,
        )
        assert r.status_code == 201, r.text
        item = r.json()
        assert item["kind"] == "code"
        assert item["language"] == "cpp"


@pytest.mark.asyncio
async def test_code_without_language_forbidden():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _reg_login(ac, "clip_bad")

        r = await ac.post(
            "/clipboards",
            json={"kind": "text", "language": "python", "content": "abc"},
            headers=h,
        )
        assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_oversized_content_rejected():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _reg_login(ac, "clip_big")

        # 从配置取上限 +1，不要硬编码 20001：
        # CLIPBOARD_MAX_TEXT_LEN 是可配置项，生产调大后硬编码会假失败。
        from app.core.config import settings
        over_limit = "x" * (settings.CLIPBOARD_MAX_TEXT_LEN + 1)

        r = await ac.post(
            "/clipboards",
            json={"content": over_limit},
            headers=h,
        )
        assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_blank_content_rejected():
    """纯空白内容必须拒绝：Schema min_length=1 只拦空串，挡不住 " "。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _reg_login(ac, "clip_blank")

        r = await ac.post("/clipboards", json={"content": "   \n\t "}, headers=h)
        assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_response_does_not_expose_user_id():
    """响应体不应暴露 user_id（对外结构白名单）。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _reg_login(ac, "clip_nouid")

        r = await ac.post("/clipboards", json={"content": "hello"}, headers=h)
        assert r.status_code == 201, r.text
        assert "user_id" not in r.json()

        r = await ac.get("/clipboards", headers=h)
        assert r.status_code == 200, r.text
        for item in r.json()["items"]:
            assert "user_id" not in item


@pytest.mark.asyncio
async def test_other_user_cannot_access():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h1 = await _reg_login(ac, "clip_o1")
        h2 = await _reg_login(ac, "clip_o2")

        r = await ac.post("/clipboards", json={"content": "mine"}, headers=h1)
        assert r.status_code == 201
        iid = r.json()["id"]

        r = await ac.get(f"/clipboards/{iid}", headers=h2)
        assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_update_and_delete():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _reg_login(ac, "clip_md")

        r = await ac.post("/clipboards", json={"content": "v1"}, headers=h)
        assert r.status_code == 201
        iid = r.json()["id"]

        r = await ac.patch(
            f"/clipboards/{iid}",
            json={"title": "new", "content": "v2"},
            headers=h,
        )
        assert r.status_code == 200, r.text
        assert r.json()["content"] == "v2"
        assert r.json()["title"] == "new"

        r = await ac.delete(f"/clipboards/{iid}", headers=h)
        assert r.status_code == 200, r.text

        r = await ac.get(f"/clipboards/{iid}", headers=h)
        assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_unauthorized_forbidden():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/clipboards")
        assert r.status_code == 401
