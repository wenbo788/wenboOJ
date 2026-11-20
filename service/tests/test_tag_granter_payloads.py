"""Tag 卡「授予人」eager load 的回归测试。

背景（线上事故）：``UserTagCard.granter`` 为了修私信 500 改成了
``lazy="raise"``（见 models/tag_card.py 的注释），于是规则变成硬约束 ——

    凡是响应里带 ``tag_cards`` 的接口（UserOut / SelfUserOut / PublicUserOut /
    UserAdminResponse），查询时必须显式 eager load ``granter``，漏一处就
    100% 500：``InvalidRequestError: 'UserTagCard.granter' is not available
    due to lazy='raise'``。

当时只补了公开主页那几条链，漏掉了管理后台和 ``/users/me``：

- ``GET /admin/users``：列表接口（前端一次拉 limit=1000），只要**任意一个**
  用户戴着管理员授予的卡，整个请求就 500 → 后台用户管理一页数据都出不来
- ``GET /admin/users/{user_number}``、``PUT /admin/users/{user_number}``
- ``GET /users/me``、``PUT /users/me/profile``（戴卡用户自己的资料页）

本文件把这些路径逐个钉住。注意：只有 ``granter_id`` 非空的卡（管理员授予的）
才会触发；商店购买的卡（``granter_id`` 为空）本来就不会去读授予人。
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.tag_card import UserTagCard
from app.models.user import User

PWD = "supersecret1"
# 固定到高位编号：allocate_user_number 从 1 开始分配，测试库里前面用例已经占了很多
# 低位号，撞上 PROTECTED_UIDS / SUPER_ADMIN_UIDS（0,1,3,4,68,165,210）会让
# 「超管能不能改这个用户」这类判断变味。
_BASE_NUMBER = 880001


async def _register(ac: AsyncClient, tag: str) -> tuple[str, int]:
    """注册用户并返回 (用户名, 用户编号)。"""
    uname = f"tg_{tag}_{uuid.uuid4().hex[:8]}"
    r = await ac.post("/users", json={
        "username": uname, "email": f"{uname}@example.com", "password": PWD})
    assert r.status_code == 201, r.text
    async with AsyncSessionLocal() as db:
        u = (await db.execute(
            select(User).where(User.username == uname))).scalar_one()
        return uname, u.user_number


async def _pin_number(username: str, wanted: int) -> None:
    """把用户编号改成 wanted；编号被占用时先把占用者挪到高位空闲编号。"""
    async with AsyncSessionLocal() as db:
        holder = (await db.execute(
            select(User).where(User.user_number == wanted))).scalar_one_or_none()
        if holder is not None and holder.username != username:
            used = set((await db.execute(select(User.user_number))).scalars())
            spare = 990000
            while spare in used:
                spare += 1
            holder.user_number = spare
        u = (await db.execute(
            select(User).where(User.username == username))).scalar_one()
        u.user_number = wanted
        await db.commit()


async def _set_fields(username: str, **fields) -> None:
    async with AsyncSessionLocal() as db:
        u = (await db.execute(
            select(User).where(User.username == username))).scalar_one()
        for k, v in fields.items():
            setattr(u, k, v)
        await db.commit()


async def _grant_card(holder: str, granter: str, name: str = "金牌") -> None:
    """给 holder 戴上一张由 granter 授予的卡（granter_id 非空才会读授予人）。"""
    async with AsyncSessionLocal() as db:
        h = (await db.execute(
            select(User).where(User.username == holder))).scalar_one()
        g = (await db.execute(
            select(User).where(User.username == granter))).scalar_one()
        db.add(UserTagCard(user_id=h.id, name=name, enabled=True, granter_id=g.id))
        await db.commit()


async def _login(ac: AsyncClient, username: str) -> dict:
    r = await ac.post("/tokens", data={"username": username, "password": PWD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.asyncio
async def test_admin_user_endpoints_serialize_tag_granter():
    """后台用户列表 / 详情 / 保存：库里只要有一个戴卡用户就必须全部 200。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        op, _ = await _register(ac, "op")          # 操作者
        granter, _ = await _register(ac, "granter")  # 授予人
        holder, _ = await _register(ac, "holder")    # 戴卡的目标用户

        await _pin_number(op, _BASE_NUMBER)
        await _pin_number(granter, _BASE_NUMBER + 1)
        await _pin_number(holder, _BASE_NUMBER + 2)
        # 超管身份才够得着 can_modify_user（白名单不方便在测试里造）
        await _set_fields(op, is_super_admin=True)
        await _grant_card(holder, granter)

        h = await _login(ac, op)

        # 列表：limit=1000 —— 后台首页就是这么拉的，一个戴卡用户都不能把整页打挂
        r = await ac.get("/admin/users?limit=1000", headers=h)
        assert r.status_code == 200, r.text
        row = next((u for u in r.json() if u["username"] == holder), None)
        assert row is not None, "戴卡用户没出现在列表里"
        assert row["tag_cards"], "tag_cards 没下发"
        assert row["tag_cards"][0]["granter_name"] == granter, row["tag_cards"]
        assert row["display_tag"] == "金牌"

        # 详情
        r = await ac.get(f"/admin/users/{_BASE_NUMBER + 2}", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["tag_cards"][0]["granter_name"] == granter

        # 保存（响应同样是 UserAdminResponse；漏 eager load 时库已提交但接口 500）
        r = await ac.put(f"/admin/users/{_BASE_NUMBER + 2}?reason=回归测试",
                         json={"bio": "hello"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["tag_cards"][0]["granter_name"] == granter

        async with AsyncSessionLocal() as db:
            bio = (await db.execute(
                select(User.bio).where(User.username == holder))).scalar_one()
        assert bio == "hello"


@pytest.mark.asyncio
async def test_users_me_and_profile_update_serialize_tag_granter():
    """戴卡用户自己的 /users/me 与 PUT /users/me/profile（个人资料页用的就是这两条）。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        granter, _ = await _register(ac, "granter")
        holder, _ = await _register(ac, "holder")
        await _pin_number(granter, _BASE_NUMBER + 3)
        await _pin_number(holder, _BASE_NUMBER + 4)
        await _grant_card(holder, granter)

        h = await _login(ac, holder)

        r = await ac.get("/users/me", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["tag_cards"][0]["granter_name"] == granter

        r = await ac.put("/users/me/profile", json={"bio": "我的简介"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["tag_cards"][0]["granter_name"] == granter


@pytest.mark.asyncio
async def test_shop_card_without_granter_is_fine():
    """商店买的卡（granter_id 为空）不该因为读不到授予人而报错。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        holder, _ = await _register(ac, "holder")
        await _pin_number(holder, _BASE_NUMBER + 5)
        async with AsyncSessionLocal() as db:
            h = (await db.execute(
                select(User).where(User.username == holder))).scalar_one()
            db.add(UserTagCard(user_id=h.id, name="商店卡", enabled=True, granter_id=None))
            await db.commit()

        h = await _login(ac, holder)
        r = await ac.get("/users/me", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["tag_cards"][0]["granter_name"] is None
