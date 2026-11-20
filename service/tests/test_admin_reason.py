"""权限操作强制填写理由的回归测试。"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.user import User


async def _make_user(ac: AsyncClient, tag: str, **perms):
    uname = f"rs_{tag}_{uuid.uuid4().hex[:6]}"
    un = None
    r = await ac.post("/users", json={
        "username": uname, "email": f"{uname}@example.com", "password": "supersecret1"})
    assert r.status_code == 201, r.text
    async with AsyncSessionLocal() as db:
        u = (await db.execute(
            select(User).where(User.username == uname))).scalar_one()
        for k, v in perms.items():
            setattr(u, k, v)
        await db.commit()
        un = u.user_number
    return uname, un


async def _login(ac: AsyncClient, username: str):
    r = await ac.post("/tokens", data={"username": username, "password": "supersecret1"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _force_user_number(username: str, new_un: int):
    """测试专用：把指定用户的 UID 改成 new_un；若编号已被占用，先把占用者挪到高位空闲编号。"""
    async with AsyncSessionLocal() as db:
        holder = (await db.execute(
            select(User).where(User.user_number == new_un)
        )).scalar_one_or_none()
        if holder is not None and holder.username != username:
            used = set((await db.execute(select(User.user_number))).scalars())
            spare = 900000
            while spare in used:
                spare += 1
            holder.user_number = spare
        u = (await db.execute(
            select(User).where(User.username == username)
        )).scalar_one()
        u.user_number = new_un
        await db.commit()


@pytest.mark.asyncio
async def test_permission_change_requires_reason():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        # 操作者仅有 can_manage_users（用户管理权限）也可修改用户
        admin, admin_un = await _make_user(ac, "a", can_manage_users=True)
        target, target_un = await _make_user(ac, "t")
        h = await _login(ac, admin)

        # 无理由 → 400（三个端点）
        r = await ac.post(f"/admin/users/{target_un}/permissions",
                          json={"changes": {"can_speak": False}}, headers=h)
        assert r.status_code == 400 and "理由" in r.json()["detail"], r.text

        r = await ac.put(f"/admin/users/{target_un}",
                         json={"can_speak": False}, headers=h)
        assert r.status_code == 400 and "理由" in r.json()["detail"], r.text

        r = await ac.post(f"/admin/users/{target_un}/permissions", headers=h)
        assert r.status_code in (400, 422), r.text  # 无 body 被 FastAPI 422 拦下

        r = await ac.post("/admin/users/batch",
                          json={"user_numbers": [target_un], "updates": {"is_banned": True}},
                          headers=h)
        assert r.status_code == 400 and "理由" in r.json()["detail"], r.text

        # 带理由 → 成功
        r = await ac.post(f"/admin/users/{target_un}/permissions",
                          json={"changes": {"can_speak": False}, "reason": "测试禁言"},
                          headers=h)
        assert r.status_code == 200, r.text

        # 资料类更新（非权限字段）不需要理由
        r = await ac.put(f"/admin/users/{target_un}",
                         json={"bio": "更新简介"}, headers=h)
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_super_admin_only_modifiable_by_super_admin():
    """超级管理员（UID=2 除外）：非超管不可修改，超管可以修改。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        # 普通用户管理权限操作者（非超管）
        operator, _ = await _make_user(ac, "op", can_manage_users=True)
        # ⚠️ 测试库是新建的，第一个注册用户会拿到 UID 1，而 1 在 UID 白名单
        # {1, 68, 210} 里 —— 白名单本来就能改超管，会让本用例「非超管不可改」
        # 的前提失效。统一挪到普通号段，确保操作者确实不是白名单。
        await _force_user_number(operator, 901001)
        # 超级管理员操作者（同时具备用户管理权限，通过端点的 can_manage_users 门槛）
        super_op, _ = await _make_user(
            ac, "sop", is_super_admin=True, can_manage_users=True)
        # 同理挪走：落到 UID 1 会被白名单层级盖掉，is_super_admin 反而不成立
        await _force_user_number(super_op, 901002)
        # 目标：超级管理员，强制 UID 为高位编号（!= 2）
        target, _ = await _make_user(ac, "st", is_super_admin=True)
        target_un = 910011
        await _force_user_number(target, target_un)

        h = await _login(ac, operator)

        # 非超管：POST 改权限 → 403
        r = await ac.post(f"/admin/users/{target_un}/permissions",
                          json={"changes": {"is_admin": True}, "reason": "测试"},
                          headers=h)
        assert r.status_code == 403 and "超级管理员" in r.json()["detail"], r.text

        # 非超管：PUT 改资料 → 403
        r = await ac.put(f"/admin/users/{target_un}",
                         json={"bio": "更新简介"}, headers=h)
        assert r.status_code == 403, r.text

        # 非超管：批量操作目标被跳过（updated_count=0）
        r = await ac.post("/admin/users/batch",
                          json={"user_numbers": [target_un],
                                "updates": {"is_banned": True}, "reason": "测试"},
                          headers=h)
        assert r.status_code == 200 and r.json()["updated_count"] == 0, r.text

        # 超管操作者（非白名单）：按 B 方案口径，can_grant_role 允许超管授予
        # admin / 题管 / 社管 / 大管，故此处授予 is_admin 应成功。
        # （旧断言写 403，是「仅白名单可授」的重构前口径，已随 cd4d75a 变更）
        sh = await _login(ac, super_op)
        r = await ac.post(f"/admin/users/{target_un}/permissions",
                          json={"changes": {"is_admin": True}, "reason": "超管操作"},
                          headers=sh)
        assert r.status_code == 200, r.text

        # 但 is_super_admin 是固定身份，不在可授予角色内：超管也不能通过该接口授超管
        r = await ac.post(f"/admin/users/{target_un}/permissions",
                          json={"changes": {"is_super_admin": True}, "reason": "试图授超管"},
                          headers=sh)
        assert r.status_code in (400, 403), r.text


@pytest.mark.asyncio
async def test_uid2_super_admin_exception():
    """UID=2 的超级管理员例外：非超管仍可修改，但 is_super_admin 字段本身依旧不可改。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        operator, _ = await _make_user(ac, "op2", can_manage_users=True)
        target, _ = await _make_user(ac, "st2", is_super_admin=True)
        await _force_user_number(target, 2)

        h = await _login(ac, operator)

        # UID=2 例外：不受「超管目标仅白名单可改」限制，
        # 但授予 is_admin 仍仅白名单可做（!72 重构语义）→ 403
        r = await ac.post("/admin/users/2/permissions",
                          json={"changes": {"is_admin": True}, "reason": "测试例外"},
                          headers=h)
        assert r.status_code == 403, r.text

        # 非权限字段也可以改
        r = await ac.put("/admin/users/2", json={"bio": "更新简介"}, headers=h)
        assert r.status_code == 200, r.text

        # 但 is_super_admin 字段本身依旧不可修改
        r = await ac.post("/admin/users/2/permissions",
                          json={"changes": {"is_super_admin": False}, "reason": "测试"},
                          headers=h)
        assert r.status_code == 400, r.text
