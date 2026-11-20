"""团队概览编辑回归测试：权限边界 + 校验 + 封禁拦截。"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.team import Team, TeamMember
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
    """把 UID 挪到高位：单文件跑时新库前几个用户会撞白名单 UID（1/68/210）。"""
    async with AsyncSessionLocal() as db:
        u = (await db.execute(
            select(User).where(User.username == username))).scalar_one()
        u.user_number = 900000 + (uuid.UUID(uuid.uuid4().hex).int % 100000)
        await db.commit()


async def _uid(username: str) -> int:
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(User.id).where(User.username == username))).scalar_one()


async def _add_member(team_id: int, username: str, role: str) -> None:
    async with AsyncSessionLocal() as db:
        db.add(TeamMember(team_id=team_id, user_id=await _uid(username), role=role))
        await db.commit()


async def _set_banned(team_id: int, banned: bool) -> None:
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one()
        t.is_banned = banned
        await db.commit()


async def _team_desc(team_id: int) -> str | None:
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(Team.description).where(Team.id == team_id))).scalar_one()


@pytest.mark.asyncio
async def test_team_overview_edit_permissions_and_persist():
    """团主与团队管理员可编辑概览；普通成员 / 非成员不可；结果可回读。"""
    sfx = uuid.uuid4().hex[:8]
    pwd = "supersecret1"
    owner, tadmin, member, outsider = (
        f"ov_owner_{sfx}", f"ov_admin_{sfx}", f"ov_member_{sfx}", f"ov_out_{sfx}")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        for n in (owner, tadmin, member, outsider):
            await _register(ac, n, pwd)
            await _move_uid_high(n)
        oh = await _login(ac, owner, pwd)
        ah = await _login(ac, tadmin, pwd)
        mh = await _login(ac, member, pwd)
        uh = await _login(ac, outsider, pwd)

        r = await ac.post("/teams", json={"name": f"团队{sfx}", "description": "初始简介"}, headers=oh)
        assert r.status_code == 201, r.text
        tid = r.json()["id"]
        await _add_member(tid, tadmin, "admin")
        await _add_member(tid, member, "member")

        # 1) 团主可编辑（名称 + 简介）
        r = await ac.put(f"/teams/{tid}",
                         json={"name": f"改名{sfx}", "description": "新简介"}, headers=oh)
        assert r.status_code == 200, r.text
        assert r.json()["name"] == f"改名{sfx}"
        assert r.json()["description"] == "新简介"
        assert await _team_desc(tid) == "新简介"

        # 2) 团队管理员可编辑
        r = await ac.put(f"/teams/{tid}",
                         json={"description": "管理员改的"}, headers=ah)
        assert r.status_code == 200, r.text
        assert r.json()["description"] == "管理员改的"
        assert await _team_desc(tid) == "管理员改的"

        # 3) 普通成员 403
        r = await ac.put(f"/teams/{tid}",
                         json={"description": "成员偷改"}, headers=mh)
        assert r.status_code == 403, r.text
        assert await _team_desc(tid) == "管理员改的"

        # 4) 非成员 403
        r = await ac.put(f"/teams/{tid}",
                         json={"description": "外人偷改"}, headers=uh)
        assert r.status_code == 403, r.text
        assert await _team_desc(tid) == "管理员改的"

        # 5) 未登录 401
        r = await ac.put(f"/teams/{tid}", json={"description": "匿名"})
        assert r.status_code == 401, r.text

        # 6) 详情端点回读一致
        d = (await ac.get(f"/teams/{tid}", headers=oh)).json()
        assert d["description"] == "管理员改的"
        assert d["name"] == f"改名{sfx}"


@pytest.mark.asyncio
async def test_team_overview_edit_validation():
    """名称空 / 超长、简介超长需 400；部分更新不误伤其他字段。"""
    sfx = uuid.uuid4().hex[:8]
    pwd = "supersecret1"
    owner = f"ov_val_{sfx}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        await _register(ac, owner, pwd)
        await _move_uid_high(owner)
        oh = await _login(ac, owner, pwd)

        r = await ac.post("/teams", json={"name": f"校验{sfx}"}, headers=oh)
        assert r.status_code == 201, r.text
        tid = r.json()["id"]
        original_name = r.json()["name"]

        # 空名称
        r = await ac.put(f"/teams/{tid}", json={"name": "   "}, headers=oh)
        assert r.status_code == 400, r.text
        # 名称超长
        r = await ac.put(f"/teams/{tid}", json={"name": "x" * 51}, headers=oh)
        assert r.status_code == 400, r.text
        # 简介超长
        r = await ac.put(f"/teams/{tid}", json={"description": "y" * 501}, headers=oh)
        assert r.status_code == 400, r.text

        # 仅传 description：不应改动 name
        r = await ac.put(f"/teams/{tid}", json={"description": "只改简介"}, headers=oh)
        assert r.status_code == 200, r.text
        assert r.json()["name"] == original_name
        assert r.json()["description"] == "只改简介"

        # 简介清空：转成 None，详情回读为空串
        r = await ac.put(f"/teams/{tid}", json={"description": ""}, headers=oh)
        assert r.status_code == 200, r.text
        assert await _team_desc(tid) is None

        # 不存在的团队 404
        r = await ac.put("/teams/99999999", json={"description": "x"}, headers=oh)
        assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_team_overview_edit_blocked_when_banned():
    """被封禁团队禁止编辑概览。"""
    sfx = uuid.uuid4().hex[:8]
    pwd = "supersecret1"
    owner = f"ov_ban_{sfx}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        await _register(ac, owner, pwd)
        await _move_uid_high(owner)
        oh = await _login(ac, owner, pwd)

        r = await ac.post("/teams", json={"name": f"封禁{sfx}", "description": "原简介"}, headers=oh)
        assert r.status_code == 201, r.text
        tid = r.json()["id"]

        await _set_banned(tid, True)
        r = await ac.put(f"/teams/{tid}", json={"description": "封禁后改"}, headers=oh)
        assert r.status_code == 403, r.text
        assert await _team_desc(tid) == "原简介"

        # 解封后可正常编辑
        await _set_banned(tid, False)
        r = await ac.put(f"/teams/{tid}", json={"description": "解封后改"}, headers=oh)
        assert r.status_code == 200, r.text
        assert await _team_desc(tid) == "解封后改"
