"""权限口径一致性：管理名单公示的必须就是实际能干的。

背景：`can_manage_users` / `can_manage_tags` 这两个字段曾经只有「管理名单」
公示页认，权限真源（permissions.py）、前端判定、部分接口各用各的口径，
于是出现「名单里有他，换个入口就干不了」，或者「白名单/大管反而被拒」。

现在统一为：**字段算真权限**（高层级天然也具备），公示按真实能力列人。
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app import permissions as perm
from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.user import User


def _user(user_number: int, **flags) -> User:
    """构造一个不入库的 User，只用来跑权限判定。"""
    u = User(id=user_number, username=f"u{user_number}", user_number=user_number)
    u.tag_cards = []  # 不设的话 display_tag 里读关系属性会拿到 None
    for k, v in flags.items():
        setattr(u, k, v)
    return u


# 白名单 UID 从真源常量取，别硬编码具体编号：
# 白名单是会变的（{1, 3, 4, 68, 165, 210} → {1, 68, 210}），写死会让测试莫名失败
WHITE_LIST_UID = min(perm.SUPER_ADMIN_UIDS)
PLAIN_UID = 500


def test_plain_user_has_nothing():
    u = _user(PLAIN_UID)
    assert not perm.can_manage_users(u)
    assert not perm.can_manage_tags(u)
    assert not perm.can_manage_problems(u)
    assert not perm.can_manage_community(u)
    assert not perm.is_any_admin(u)


def test_flag_grants_capability_and_admin_area_access():
    """被授予字段的人：能力成立，而且能进后台（否则名单公示了却进不去）。"""
    u = _user(PLAIN_UID, can_manage_tags=True)
    assert perm.can_manage_tags(u)
    assert perm.is_any_admin(u)
    # 只给了 Tag，别的不该跟着有
    assert not perm.can_manage_problems(u)
    assert not perm.can_manage_users(u)

    v = _user(PLAIN_UID, can_manage_users=True)
    assert perm.can_manage_users(v)
    assert perm.is_any_admin(v)
    assert not perm.can_manage_tags(v)


def test_white_list_and_top_roles_hold_every_column():
    """白名单/超管/大管：四列全都有（他们本来就能干这些事）。"""
    for u in (
        _user(WHITE_LIST_UID),
        _user(PLAIN_UID, is_super_admin=True),
        _user(PLAIN_UID, is_big_admin=True),
    ):
        assert perm.can_manage_users(u), u
        assert perm.can_manage_tags(u), u
        assert perm.can_manage_problems(u), u
        assert perm.can_manage_community(u), u


def test_super_admin_beats_white_list_check():
    """白名单优先于 is_super_admin 字段：白名单用户不会被算成「超管」。"""
    u = _user(WHITE_LIST_UID, is_super_admin=True)
    assert perm.is_white_list(u)
    assert not perm.is_super_admin(u)


def test_display_tag_covers_all_roster_columns():
    """称号链必须覆盖「管理名单」公示的四列。

    少了 can_manage_users / can_manage_tags，被单独授予这两项的人会在名单页上
    「有位置、没称号」——名单里有他，名字旁边却什么都没有。
    """
    assert _user(PLAIN_UID, can_manage_tags=True).display_tag == "Tag 管理"
    assert _user(PLAIN_UID, can_manage_users=True).display_tag == "用户管理"
    # 高层级优先，不能被这两项盖掉
    assert _user(PLAIN_UID, can_manage_problems=True, can_manage_tags=True).display_tag == "题管"
    assert _user(PLAIN_UID, can_manage_posts=True, can_manage_users=True).display_tag == "社管"
    assert _user(PLAIN_UID, is_big_admin=True, can_manage_tags=True).display_tag == "大管"
    assert _user(WHITE_LIST_UID, can_manage_tags=True).display_tag == "UID 白名单"
    # 没有管理权限的普通用户：不该被冠上管理称号
    assert _user(PLAIN_UID).display_tag == ""


@pytest.mark.asyncio
async def test_batch_endpoint_blocks_privilege_escalation():
    """批量改用户接口：能进这个接口 ≠ 能改角色字段。

    入口放行的是「谁算用户管理员」（白名单/超管/大管/持有 can_manage_users
    字段的人），真正拦住提权的是函数内部**逐字段**的 can_grant_role /
    can_revoke_role 校验。这里把这条防线钉住：大管和字段持有者都进得来，
    但谁也给自己或别人加不了管理角色。
    """
    suffix = uuid.uuid4().hex[:8]
    names = {
        "big": f"big_{suffix}",          # 大管
        "holder": f"holder_{suffix}",    # 只持有 can_manage_users 字段
        "su": f"su_{suffix}",            # 超管
        "target": f"target_{suffix}",    # 被操作对象
    }
    pwd = "supersecret1"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        for name in names.values():
            r = await ac.post("/users", json={
                "username": name, "email": f"{name}@example.com", "password": pwd})
            assert r.status_code == 201, r.text

        heads: dict[str, dict] = {}
        numbers: dict[str, int] = {}
        for key, name in names.items():
            r = await ac.post("/tokens", data={"username": name, "password": pwd})
            heads[key] = {"Authorization": f"Bearer {r.json()['access_token']}"}
            numbers[key] = (await ac.get("/auth/me", headers=heads[key])).json()["user_number"]

        # 角色只能用 DB 直接设（is_super_admin 不可通过接口授予）。
        # user_number 必须避开白名单 {1,3,68,165,210}：测试库自增编号很容易
        # 撞上它们，那样谁都算白名单，用例就失去意义了。
        async with AsyncSessionLocal() as db:
            big = (await db.execute(select(User).where(User.username == names["big"]))).scalar_one()
            big.user_number = 911
            big.is_big_admin = True
            holder = (await db.execute(select(User).where(User.username == names["holder"]))).scalar_one()
            holder.user_number = 912
            holder.can_manage_users = True
            su = (await db.execute(select(User).where(User.username == names["su"]))).scalar_one()
            su.user_number = 913
            su.is_super_admin = True
            target = (await db.execute(select(User).where(User.username == names["target"]))).scalar_one()
            target.user_number = 914
            await db.commit()

        # 认证头是在改编号之前拿的，但 JWT 里带的是 user id，不受影响；
        # 目标用户按 user_number 匹配，所以要重新取一次编号
        numbers["target"] = 914

        target = [numbers["target"]]
        reason = {"reason": "权限一致性回归测试"}

        async def batch(head: dict, updates: dict) -> int:
            r = await ac.post("/admin/users/batch", json={
                "user_numbers": target, "updates": updates, **reason}, headers=head)
            return r.status_code

        # ① 大管：进得来，但授予任何管理角色都被挡
        for field in ("can_manage_users", "can_manage_tags", "can_manage_problems", "is_big_admin"):
            assert await batch(heads["big"], {field: True}) == 403, f"大管不该能授予 {field}"

        # ② 只持有 can_manage_users 字段的人：同样授不了权
        assert await batch(heads["holder"], {"can_manage_users": True}) == 403
        assert await batch(heads["holder"], {"can_manage_tags": True}) == 403

        # ③ 超管：能授 admin 类角色（admin / 用户管理 / Tag 管理）、题管/社管、大管
        #    （与前端 canGrantRole 的可授角色列表一致）；只有超管字段本身谁都不能改
        assert await batch(heads["su"], {"can_manage_tags": True}) == 200
        assert await batch(heads["su"], {"can_manage_users": True}) == 200
        assert await batch(heads["su"], {"can_manage_problems": True}) == 200
        assert await batch(heads["su"], {"is_big_admin": True}) == 200
        r = await ac.post("/admin/users/batch", json={
            "user_numbers": target, "updates": {"is_super_admin": True},
            "reason": "权限一致性回归测试"}, headers=heads["su"])
        assert r.status_code == 400, "超管字段是固定身份，不该被任何批量操作改动"

        # ④ 大管改普通权限（禁言）是他本来就有的能力，不该被误伤
        assert await batch(heads["big"], {"can_speak": False}) == 200


@pytest.mark.asyncio
async def test_admin_roster_lists_real_capabilities():
    """公示名单：有字段的人在，白名单/超管也在，且四列是「能不能干」而不是原始字段。"""
    suffix = uuid.uuid4().hex[:8]
    tag_name = f"tagadm_{suffix}"
    super_name = f"superadm_{suffix}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        for name in (tag_name, super_name):
            r = await ac.post("/users", json={
                "username": name, "email": f"{name}@example.com", "password": "supersecret1"})
            assert r.status_code == 201, r.text

        # 直接改库：一个只给 can_manage_tags，一个是超管（超管字段不可通过接口授予）
        async with AsyncSessionLocal() as db:
            tagger = (await db.execute(
                select(User).where(User.username == tag_name))).scalar_one()
            tagger.user_number = 901
            tagger.can_manage_tags = True
            tagger.can_manage_problems = False
            tagger.can_manage_posts = False
            tagger.can_manage_users = False
            tagger.is_admin = False

            su = (await db.execute(
                select(User).where(User.username == super_name))).scalar_one()
            su.user_number = 902
            su.is_super_admin = True
            su.can_manage_tags = False
            su.can_manage_problems = False
            await db.commit()

        r = await ac.get("/judgement/admins")  # 公示页无需登录
        assert r.status_code == 200, r.text
        rows = {u["username"]: u for u in r.json()["admins"]}

        assert tag_name in rows, f"只被授予 Tag 管理的人应当出现在公示里：{rows.keys()}"
        tagger_row = rows[tag_name]
        assert tagger_row["can_manage_tags"] is True
        # 「用户/秩序/题目」三列必须诚实：他只有 Tag
        assert tagger_row["can_manage_users"] is False
        assert tagger_row["can_manage_posts"] is False
        assert tagger_row["can_manage_problems"] is False

        assert super_name in rows, f"超管即使没有这些字段也应当在公示里：{rows.keys()}"
        su_row = rows[super_name]
        assert su_row["can_manage_users"] is True
        assert su_row["can_manage_posts"] is True
        assert su_row["can_manage_problems"] is True
        assert su_row["can_manage_tags"] is True
