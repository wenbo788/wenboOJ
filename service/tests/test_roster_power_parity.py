"""「管理名单」公示的权限 == 实际能干的事（名单纯源 vs 动作判定）。

背景：名单是**算**出来的 —— ``api/judgement.py`` 的四列分别调用
``app.permissions.can_manage_users / can_manage_community / can_manage_problems /
can_manage_tags``（真源：白名单/超管/大管天然具备，或持有对应裸字段）。

麻烦在于**动作**是各写各的：不少入口直接读裸字段（``user.can_manage_posts``、
``user.is_super_admin``……）或自己拼一套逻辑。于是每加一个身份/字段，就会有某个
动作跟名单对不上，线上表现就是「名单上写着某某管理，点进去全是 403」——
这一类已经复发过好几次（陶片删除、批量改权限、称号链、单用户资料……）。

本文件把「那一列被勾上 → 对应动作必须能过」这件事钉住：

- 用户管理列：改单用户资料（``can_modify_user``）、改头像（``admin_upload``）
- 秩序管理列：举报审核（``services/moderation.is_order_admin``）
"""

from types import SimpleNamespace
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app import permissions as perm
from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.user import User
from app.services.moderation import is_order_admin

PWD = "supersecret1"
_BASE = 881001


def _stub(user_number: int, **flags) -> SimpleNamespace:
    """权限函数只读属性，用轻量对象跑身份矩阵，免得测试库编号互相抢。"""
    base = dict(
        is_super_admin=False, is_big_admin=False, is_admin=False,
        can_manage_users=False, can_manage_posts=False,
        can_manage_problems=False, can_manage_tags=False,
    )
    base.update(flags)
    return SimpleNamespace(user_number=user_number, **base)


def test_identity_matrix_matches_roster_columns():
    """身份矩阵：谁被名单勾上，谁就必须过对应的动作判定。"""
    plain = _stub(500001)
    user_mgr = _stub(500002, can_manage_users=True)
    order_mgr = _stub(500003, can_manage_posts=True)
    tag_mgr = _stub(500004, can_manage_tags=True)
    big = _stub(500005, is_big_admin=True)
    super_adm = _stub(500006, is_super_admin=True)
    whitelist = _stub(210)          # 白名单 UID：raw 字段全是 false
    legacy_admin = _stub(500007, is_admin=True)
    super_target = _stub(500008, is_super_admin=True)
    uid2_target = _stub(2, is_super_admin=True)
    plain_target = _stub(500009)

    # 名单四列（judgement.py 用的就是这几个真源函数）
    assert perm.can_manage_users(user_mgr) and perm.can_manage_users(big)
    assert perm.can_manage_community(order_mgr) and perm.can_manage_community(big)
    assert perm.can_manage_tags(tag_mgr) and perm.can_manage_tags(big)
    assert perm.can_manage_users(whitelist) and perm.can_manage_community(whitelist)

    # 用户管理列 → 能改单用户资料
    assert perm.can_modify_user(user_mgr, plain_target)
    assert perm.can_modify_user(whitelist, plain_target)
    assert perm.can_modify_user(big, plain_target)
    # 但改不动其他超管（UID 2 是历史遗留例外），普通用户/泛管理员也改不动
    assert not perm.can_modify_user(user_mgr, super_target)
    assert perm.can_modify_user(user_mgr, uid2_target)
    assert not perm.can_modify_user(plain, plain_target)
    assert not perm.can_modify_user(legacy_admin, plain_target)

    # 秩序管理列 → 能进举报审核
    assert is_order_admin(order_mgr)
    assert is_order_admin(big)
    assert is_order_admin(whitelist)
    assert is_order_admin(super_adm)
    # 泛管理员保留放行：名单只承诺「上了名单就有权限」，不承诺「没上就没有」
    assert is_order_admin(legacy_admin)
    assert not is_order_admin(plain)


async def _register(ac: AsyncClient, tag: str) -> str:
    uname = f"rp_{tag}_{uuid.uuid4().hex[:8]}"
    r = await ac.post("/users", json={
        "username": uname, "email": f"{uname}@example.com", "password": PWD})
    assert r.status_code == 201, r.text
    return uname


async def _pin_number(username: str, wanted: int) -> None:
    """钉编号；挪走占用者后立刻 flush（user_number 有唯一约束）。"""
    async with AsyncSessionLocal() as db:
        holder = (await db.execute(
            select(User).where(User.user_number == wanted))).scalar_one_or_none()
        if holder is not None and holder.username != username:
            used = set((await db.execute(select(User.user_number))).scalars())
            spare = 992000
            while spare in used:
                spare += 1
            holder.user_number = spare
            await db.flush()
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


async def _login(ac: AsyncClient, username: str) -> dict:
    r = await ac.post("/tokens", data={"username": username, "password": PWD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.asyncio
async def test_user_manage_column_holder_can_edit_single_user():
    """只有 can_manage_users 的人（名单「用户管理」列）必须能改单用户资料。

    修复前：PUT /admin/users/{n} 走 can_modify_user，那里只认白名单/超管/大管，
    裸字段持有者一律 403 —— 而同一个后台的「改权限」「批量」都放行他。
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        op = await _register(ac, "op")
        target = await _register(ac, "target")
        super_target = await _register(ac, "super")
        await _pin_number(op, _BASE)
        await _pin_number(target, _BASE + 1)
        await _pin_number(super_target, _BASE + 2)
        await _set_fields(op, can_manage_users=True)
        await _set_fields(super_target, is_super_admin=True)

        h = await _login(ac, op)

        # 名单里确实把他勾在「用户管理」列
        admins = {a["username"]: a for a in (await ac.get("/judgement/admins")).json()["admins"]}
        assert admins[op]["can_manage_users"] is True

        # 资料修改（原本 403 的就是这一条）
        r = await ac.put(f"/admin/users/{_BASE + 1}?reason=回归", json={"bio": "hi"}, headers=h)
        assert r.status_code == 200, r.text
        # 同一列的其它入口保持放行
        r = await ac.post(f"/admin/users/{_BASE + 1}/permissions",
                          json={"changes": {"can_speak": False}, "reason": "回归"}, headers=h)
        assert r.status_code == 200, r.text
        r = await ac.post("/admin/users/batch",
                          json={"user_numbers": [_BASE + 1], "updates": {"can_speak": True},
                                "reason": "回归"}, headers=h)
        assert r.status_code == 200, r.text

        # 超管目标（UID 2 除外）依旧不可动
        r = await ac.put(f"/admin/users/{_BASE + 2}?reason=回归", json={"bio": "x"}, headers=h)
        assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_user_manage_column_covers_admin_avatar_upload():
    """大管（raw can_manage_users=False，但名单勾了用户管理）必须能传用户头像。

    修复前 admin_upload.py 读裸字段 → 白名单/超管/大管全被 403。
    这里用 .txt 触发「扩展名不支持」的 400，恰好证明权限门槛已过（不是 403），
    也避免往仓库里写测试图片。
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        big = await _register(ac, "big")
        plain = await _register(ac, "plain")
        target = await _register(ac, "target")
        await _pin_number(big, _BASE + 3)
        await _pin_number(plain, _BASE + 4)
        await _pin_number(target, _BASE + 5)
        await _set_fields(big, is_big_admin=True)

        files = {"file": ("probe.txt", b"not-an-image", "text/plain")}
        h = await _login(ac, big)
        r = await ac.post(f"/admin/users/{_BASE + 5}/avatar", files=files, headers=h)
        assert r.status_code == 400 and "图片" in r.json()["detail"], r.text

        h = await _login(ac, plain)
        r = await ac.post(f"/admin/users/{_BASE + 5}/avatar", files=files, headers=h)
        assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_order_manage_column_covers_report_review():
    """大管（raw can_manage_posts=False，但名单勾了秩序管理）必须能进举报审核。

    前端菜单/路由守卫用的就是 canManageCommunity（真源），修复前后端
    is_order_admin 读裸字段 → 能点进页面、每个请求 403。
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        big = await _register(ac, "big")
        legacy = await _register(ac, "legacy")
        plain = await _register(ac, "plain")
        await _pin_number(big, _BASE + 6)
        await _pin_number(legacy, _BASE + 7)
        await _pin_number(plain, _BASE + 8)
        await _set_fields(big, is_big_admin=True)
        await _set_fields(legacy, is_admin=True)

        admins = {a["username"]: a for a in (await ac.get("/judgement/admins")).json()["admins"]}
        assert admins[big]["can_manage_posts"] is True

        h = await _login(ac, big)
        assert (await ac.get("/reports/admin", headers=h)).status_code == 200

        # 泛管理员保留原行为（只加权限、不收紧）
        h = await _login(ac, legacy)
        assert (await ac.get("/reports/admin", headers=h)).status_code == 200

        h = await _login(ac, plain)
        assert (await ac.get("/reports/admin", headers=h)).status_code == 403


@pytest.mark.asyncio
async def test_problem_manage_column_holder_can_use_review_and_create_contest():
    """「题目管理」列勾上的人（白名单/超管/大管/题管）必须真的能管题。

    修复前 `_can_manage_problems` 只认裸字段 can_manage_problems，白名单/超管/大管
    进审核后台与建赛都是 403 —— 名单上却写着题目管理。
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac0:
        reviewer = await _register(ac0, "pm_reviewer")   # 只有 can_manage_problems
        plain = await _register(ac0, "pm_plain")
    await _pin_number(reviewer, _BASE + 20)
    await _pin_number(plain, _BASE + 21)
    await _set_fields(reviewer, can_manage_problems=True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _login(ac, reviewer)
        # 名单里确实勾在题目管理列
        admins = {a["username"]: a for a in (await ac.get("/judgement/admins")).json()["admins"]}
        assert admins[reviewer]["can_manage_problems"] is True

        # 审核后台（scope=review 走 _require_problem_manage）
        r = await ac.get("/problems?scope=review", headers=h)
        assert r.status_code == 200, r.text

        # 建赛（_can_manage_contest 与题目管理同口径）：先建一道题，比赛要求至少一题
        r = await ac.post("/problems", headers=h, json={
            "title": "题目管理列建的题", "description": "t", "is_public": True})
        assert r.status_code in (200, 201), r.text
        pid = r.json().get("id") or r.json().get("problem_id")
        assert pid

        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        r = await ac.post("/contests", headers=h, json={
            "title": "题目管理列建赛", "visibility": "public", "rule_type": "xcpc",
            "start_time": (now + timedelta(hours=1)).isoformat(),
            "end_time": (now + timedelta(hours=2)).isoformat(),
            "problem_codes": [str(pid)],
        })
        assert r.status_code in (200, 201), r.text

        # 普通用户两样都不行
        hp = await _login(ac, plain)
        assert (await ac.get("/problems?scope=review", headers=hp)).status_code == 403
        r = await ac.post("/contests", headers=hp, json={
            "title": "普通用户无权建赛", "visibility": "public", "rule_type": "xcpc",
            "start_time": (now + timedelta(hours=1)).isoformat(),
            "end_time": (now + timedelta(hours=2)).isoformat(),
            "problem_codes": [str(pid)]})
        assert r.status_code == 403, r.text
