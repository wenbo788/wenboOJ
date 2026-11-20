"""测试 /teams/my 端点及 UID=4 白名单权限。"""

import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.user import User
from app.models.team import Team, TeamMember
from app.permissions import SUPER_ADMIN_UIDS, PROTECTED_UIDS, is_white_list, is_top_admin


async def _register(ac: AsyncClient, name: str, pwd: str) -> None:
    r = await ac.post("/users", json={
        "username": name, "email": f"{name}@example.com", "password": pwd})
    assert r.status_code == 201, r.text


async def _login(ac: AsyncClient, name: str, pwd: str) -> dict:
    r = await ac.post("/tokens", data={"username": name, "password": pwd})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_whitelist_uids_are_protected():
    """白名单 UID 都在「受保护账号」集合里，且真源判定认它们是白名单/最高层级。

    不写死具体编号：白名单会调整（{1, 3, 4, 68, 165, 210} → {1, 68, 210}），
    硬编码某个 UID 会让测试随配置变动而无谓失败。
    """
    assert SUPER_ADMIN_UIDS <= PROTECTED_UIDS

    uid = min(SUPER_ADMIN_UIDS)
    fake_user = User(user_number=uid, username="wl_probe", is_super_admin=False)
    assert is_white_list(fake_user) is True
    assert is_top_admin(fake_user) is True

    # 已移出白名单的 UID 不该再被当成白名单（但仍属受保护账号）
    for stale in {3, 4, 165} - SUPER_ADMIN_UIDS:
        assert is_white_list(User(user_number=stale, username="stale", is_super_admin=False)) is False
        assert stale in PROTECTED_UIDS


@pytest.mark.asyncio
async def test_teams_my_endpoint():
    suffix = uuid.uuid4().hex[:8]
    pwd = "supersecret1"
    user_a = f"usera_{suffix}"
    user_b = f"userb_{suffix}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        await _register(ac, user_a, pwd)
        await _register(ac, user_b, pwd)

        async with AsyncSessionLocal() as db:
            ua = (await db.execute(select(User).where(User.username == user_a))).scalar_one()
            ub = (await db.execute(select(User).where(User.username == user_b))).scalar_one()
            # 避开白名单 UID
            ua.user_number = 800000 + (uuid.UUID(uuid.uuid4().hex).int % 100000)
            ub.user_number = 800000 + (uuid.UUID(uuid.uuid4().hex).int % 100000)
            await db.commit()

        head_a = await _login(ac, user_a, pwd)
        head_b = await _login(ac, user_b, pwd)

        # 初始时 user_a 没有加入任何团队
        r = await ac.get("/teams/my", headers=head_a)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 0
        assert data["items"] == []

        # user_a 创建一个团队 A_team
        r = await ac.post("/teams", json={"name": f"TeamA_{suffix}", "description": "Desc A"}, headers=head_a)
        assert r.status_code == 201
        team_a_id = r.json()["id"]

        # user_b 创建一个团队 B_team
        r = await ac.post("/teams", json={"name": f"TeamB_{suffix}", "description": "Desc B"}, headers=head_b)
        assert r.status_code == 201
        team_b_id = r.json()["id"]

        # user_a 现在的 /teams/my 应该包含 TeamA，且 user_role == 'owner', is_owner == True
        r = await ac.get("/teams/my", headers=head_a)
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == team_a_id
        assert items[0]["user_role"] == "owner"
        assert items[0]["is_owner"] is True
        assert items[0]["is_member"] is True

        # 让 user_a 加入 TeamB（通过直接在数据库加 member 模拟已加入）
        async with AsyncSessionLocal() as db:
            ua_id = (await db.execute(select(User.id).where(User.username == user_a))).scalar_one()
            member = TeamMember(team_id=team_b_id, user_id=ua_id, role="member")
            db.add(member)
            await db.commit()

        # user_a 现在的 /teams/my 应该有 2 个团队：TeamA (owner) 和 TeamB (member)
        r = await ac.get("/teams/my", headers=head_a)
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 2
        id_to_role = {it["id"]: it["user_role"] for it in items}
        assert id_to_role[team_a_id] == "owner"
        assert id_to_role[team_b_id] == "member"
