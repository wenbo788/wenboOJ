"""测试改名与 Tag 变更历史留痕功能。"""

import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.user import User
from app.models.tag_card import UserTagCard
from app.models.user_history import UsernameHistory, UserTagHistory


async def _make_user(ac: AsyncClient, prefix: str, **perms) -> tuple[str, int, int]:
    uname = f"{prefix}_{uuid.uuid4().hex[:6]}"
    r = await ac.post("/users", json={
        "username": uname, "email": f"{uname}@example.com", "password": "supersecret1"
    })
    assert r.status_code == 201, r.text
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.username == uname))).scalar_one()
        for k, v in perms.items():
            setattr(u, k, v)
        await db.commit()
        await db.refresh(u)
        return uname, u.id, u.user_number


async def _login(ac: AsyncClient, username: str) -> dict:
    r = await ac.post("/tokens", data={"username": username, "password": "supersecret1"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.asyncio
async def test_username_and_tag_history_tracking():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 创建超级管理员（具有用户管理与 Tag 管理权限）与普通用户
        admin_name, admin_id, admin_un = await _make_user(
            ac, "adm", is_super_admin=True, can_manage_users=True, can_manage_tags=True
        )
        user_name, user_id, user_un = await _make_user(ac, "usr")

        admin_headers = await _login(ac, admin_name)
        user_headers = await _login(ac, user_name)

        # 1. 普通用户自行改名留痕
        new_name_1 = f"u1_{uuid.uuid4().hex[:6]}"
        r = await ac.put("/users/me/profile", json={"username": new_name_1}, headers=user_headers)
        assert r.status_code == 200, r.text

        # 查看改名记录
        r = await ac.get(f"/users/{user_id}/username-history", headers=user_headers)
        assert r.status_code == 200
        history = r.json()
        assert len(history) == 1
        assert history[0]["old_username"] == user_name
        assert history[0]["new_username"] == new_name_1
        assert history[0]["is_self"] is True
        assert history[0]["operator_id"] == user_id

        # 2. 管理员在后台修改用户名留痕
        new_name_2 = f"u2_{uuid.uuid4().hex[:6]}"
        r = await ac.put(f"/admin/users/{user_un}", json={"username": new_name_2}, headers=admin_headers)
        assert r.status_code == 200, r.text

        r = await ac.get(f"/users/{user_id}/username-history", headers=admin_headers)
        assert r.status_code == 200
        history = r.json()
        assert len(history) == 2
        # 最新一条排在前面
        assert history[0]["old_username"] == new_name_1
        assert history[0]["new_username"] == new_name_2
        assert history[0]["is_self"] is False
        assert history[0]["operator_id"] == admin_id
        assert history[0]["operator_name"] == admin_name

        # 3. 管理员授予 Tag 卡留痕
        tag_name = "金牌选手"
        r = await ac.post(f"/users/{user_id}/tag-cards", json={"name": tag_name}, headers=admin_headers)
        assert r.status_code == 201, r.text
        card_data = r.json()
        card_id = card_data["id"]
        assert card_data["granter_id"] == admin_id
        assert card_data["granter_name"] == admin_name

        # 查看 Tag 历史
        r = await ac.get(f"/users/{user_id}/tag-history", headers=user_headers)
        assert r.status_code == 200
        tag_hist = r.json()
        assert len(tag_hist) == 1
        assert tag_hist[0]["action"] == "grant"
        assert tag_hist[0]["tag_name"] == tag_name
        assert tag_hist[0]["operator_name"] == admin_name

        # 4. 管理员删除 Tag 卡留痕
        r = await ac.delete(f"/users/{user_id}/tag-cards/{card_id}", headers=admin_headers)
        assert r.status_code == 204

        r = await ac.get(f"/users/{user_id}/tag-history", headers=admin_headers)
        assert r.status_code == 200
        tag_hist = r.json()
        assert len(tag_hist) == 2
        assert tag_hist[0]["action"] == "revoke"
        assert tag_hist[0]["tag_name"] == tag_name
        assert tag_hist[0]["operator_name"] == admin_name

        # 5. 管理员在后台修改 user_tag 留痕
        custom_tag = "特邀教练"
        r = await ac.put(f"/admin/users/{user_un}", json={"user_tag": custom_tag}, headers=admin_headers)
        assert r.status_code == 200

        r = await ac.get(f"/users/{user_id}/tag-history", headers=admin_headers)
        assert r.status_code == 200
        tag_hist = r.json()
        assert len(tag_hist) == 3
        assert tag_hist[0]["action"] == "custom_tag"
        assert tag_hist[0]["tag_name"] == custom_tag
        assert tag_hist[0]["operator_name"] == admin_name
