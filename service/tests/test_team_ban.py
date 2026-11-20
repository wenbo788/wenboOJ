"""团队封禁功能回归测试：管理接口 + 被封禁团队的操作拦截。"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.user import User


async def _register(ac: AsyncClient, name: str, pwd: str) -> None:
    r = await ac.post("/users", json={
        "username": name, "email": f"{name}@example.com", "password": pwd})
    assert r.status_code == 201, r.text


async def _login(ac: AsyncClient, name: str, pwd: str) -> dict:
    r = await ac.post("/tokens", data={"username": name, "password": pwd})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _move_uid_high(username: str) -> None:
    """把用户 UID 挪到高位：单文件跑时新库前几个用户 user_number
    会撞白名单 UID（1/68/210），导致权限判定失真。"""
    async with AsyncSessionLocal() as db:
        u = (await db.execute(
            select(User).where(User.username == username))).scalar_one()
        u.user_number = 900000 + (uuid.UUID(uuid.uuid4().hex).int % 100000)
        await db.commit()


async def _grant_user_manage(name: str) -> None:
    async with AsyncSessionLocal() as db:
        u = (await db.execute(
            select(User).where(User.username == name))).scalar_one()
        u.can_manage_users = True
        await db.commit()


@pytest.mark.asyncio
async def test_team_ban_flow():
    suffix = uuid.uuid4().hex[:8]
    pwd = "supersecret1"
    owner = f"owner_{suffix}"
    admin = f"admin_{suffix}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        await _register(ac, owner, pwd)
        await _register(ac, admin, pwd)
        await _move_uid_high(owner)
        await _move_uid_high(admin)
        await _grant_user_manage(admin)

        owner_h = await _login(ac, owner, pwd)
        admin_h = await _login(ac, admin, pwd)

        # 普通用户无权访问团队管理接口
        r = await ac.get("/admin/teams", headers=owner_h)
        assert r.status_code == 403, r.text

        # 团主创建团队
        r = await ac.post("/teams", json={"name": f"T_{suffix}"}, headers=owner_h)
        assert r.status_code == 201, r.text
        team_id = r.json()["id"]
        assert r.json()["is_banned"] is False

        # 管理员可列出团队并看到封禁状态
        r = await ac.get("/admin/teams", headers=admin_h)
        assert r.status_code == 200, r.text
        row = next(t for t in r.json()["items"] if t["id"] == team_id)
        assert row["is_banned"] is False

        # 封禁团队
        r = await ac.patch(
            f"/admin/teams/{team_id}/ban", json={"is_banned": True}, headers=admin_h)
        assert r.status_code == 200 and r.json()["is_banned"] is True

        # 封禁后团主无法发帖
        r = await ac.post(
            f"/teams/{team_id}/posts",
            json={"title": "t", "content": "c"}, headers=owner_h)
        assert r.status_code == 403, r.text

        # 列表接口也反映封禁状态
        r = await ac.get(f"/teams/{team_id}")
        assert r.status_code == 200 and r.json()["is_banned"] is True

        # 解封后恢复正常
        r = await ac.patch(
            f"/admin/teams/{team_id}/ban", json={"is_banned": False}, headers=admin_h)
        assert r.status_code == 200 and r.json()["is_banned"] is False

        r = await ac.post(
            f"/teams/{team_id}/posts",
            json={"title": "t", "content": "c"}, headers=owner_h)
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_team_ban_rejects_invalid_payload():
    suffix = uuid.uuid4().hex[:8]
    pwd = "supersecret1"
    admin = f"adm_{suffix}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        await _register(ac, admin, pwd)
        await _move_uid_high(admin)
        await _grant_user_manage(admin)
        admin_h = await _login(ac, admin, pwd)

        # 不存在的团队 → 404
        r = await ac.patch(
            "/admin/teams/999999/ban", json={"is_banned": True}, headers=admin_h)
        assert r.status_code == 404, r.text

        # 团队存在但 is_banned 类型不合法 → 400
        r = await ac.post("/teams", json={"name": f"T_{suffix}"}, headers=admin_h)
        assert r.status_code == 201, r.text
        team_id = r.json()["id"]

        r = await ac.patch(
            f"/admin/teams/{team_id}/ban", json={"is_banned": "yes"}, headers=admin_h)
        assert r.status_code == 400, r.text
