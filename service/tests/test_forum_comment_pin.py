"""讨论区「回复置顶」回归测试。

覆盖：
- 秩序管理可置顶/取消置顶回复，置顶回复在详情页排到最前（其余相对顺序不变）
- 权限走真源 ``permissions.can_manage_community``：持 can_manage_posts 的社管、
  以及无需任何字段的白名单账号都能置顶；普通用户 403、未登录 401
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.user import User


async def _register_and_login(ac: AsyncClient) -> tuple[str, dict]:
    suffix = uuid.uuid4().hex[:8]
    user, pwd = f"pin_{suffix}", "supersecret1"
    r = await ac.post("/users", json={
        "username": user, "email": f"{user}@example.com", "password": pwd})
    assert r.status_code == 201, r.text
    r = await ac.post("/tokens", data={"username": user, "password": pwd})
    assert r.status_code == 200, r.text
    return user, {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _patch(username: str, **fields) -> None:
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.username == username))).scalar_one()
        for k, v in fields.items():
            setattr(u, k, v)
        await db.commit()


async def _make_whitelist(username: str) -> None:
    """把用户提为白名单（SUPER_ADMIN_UIDS）并腾出目标号位。"""
    async with AsyncSessionLocal() as db:
        used = set((await db.execute(select(User.user_number))).scalars())
        spare = 900000
        while spare in used:
            spare += 1
        holder = (await db.execute(
            select(User).where(User.user_number == 1))).scalar_one_or_none()
        if holder is not None and holder.username != username:
            holder.user_number = spare
        u = (await db.execute(select(User).where(User.username == username))).scalar_one()
        u.user_number = 1
        await db.commit()


async def _new_post(ac: AsyncClient, headers: dict, title: str) -> int:
    r = await ac.post("/forum/posts", json={
        "title": title, "content": "正文内容", "forum": "problem"}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _reply(ac: AsyncClient, headers: dict, post_id: int, content: str) -> int:
    r = await ac.post(f"/forum/posts/{post_id}/comments",
                      json={"content": content}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _ids(data: dict) -> list[int]:
    return [c["id"] for c in data["comments"]]


@pytest.mark.asyncio
async def test_pin_comment_toggles_and_reorders():
    """社管置顶回复 → 排到最前；取消置顶 → 回到发布顺序。"""
    sfx = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        author, ah = await _register_and_login(ac)
        _, rh1 = await _register_and_login(ac)
        _, rh2 = await _register_and_login(ac)
        mod, mh = await _register_and_login(ac)
        await _patch(mod, can_manage_posts=True)

        pid = await _new_post(ac, ah, f"置顶测试-{sfx}")
        c1 = await _reply(ac, rh1, pid, "第一条回复")
        c2 = await _reply(ac, rh2, pid, "第二条回复")

        # 初始：按发布顺序
        d = (await ac.get(f"/forum/posts/{pid}")).json()
        assert _ids(d) == [c1, c2], d
        assert [c["is_pinned"] for c in d["comments"]] == [False, False]

        # 置顶第二条
        r = await ac.post(f"/forum/posts/{pid}/comments/{c2}/pin", headers=mh)
        assert r.status_code == 200, r.text
        assert r.json()["is_pinned"] is True

        d = (await ac.get(f"/forum/posts/{pid}")).json()
        assert _ids(d) == [c2, c1], "置顶回复应排在最前"
        assert d["comments"][0]["is_pinned"] is True

        # 再点一次 = 取消置顶，顺序恢复
        r = await ac.post(f"/forum/posts/{pid}/comments/{c2}/pin", headers=mh)
        assert r.status_code == 200, r.text
        assert r.json()["is_pinned"] is False

        d = (await ac.get(f"/forum/posts/{pid}")).json()
        assert _ids(d) == [c1, c2], "取消置顶后应回到发布顺序"


@pytest.mark.asyncio
async def test_pin_comment_permission_uses_permission_source():
    """普通用户不可置顶；白名单（无任何字段）可置顶——证明走的是权限真源。"""
    sfx = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        author, ah = await _register_and_login(ac)
        normal, nh = await _register_and_login(ac)
        wl_user, wh = await _register_and_login(ac)
        await _make_whitelist(wl_user)

        pid = await _new_post(ac, ah, f"置顶权限-{sfx}")
        cid = await _reply(ac, nh, pid, "一条回复")

        # 普通用户 403
        r = await ac.post(f"/forum/posts/{pid}/comments/{cid}/pin", headers=nh)
        assert r.status_code == 403, r.text

        # 未登录 401
        r = await ac.post(f"/forum/posts/{pid}/comments/{cid}/pin")
        assert r.status_code == 401, r.text

        # 白名单（can_manage_posts 仍为 False）：真源判定应放行
        r = await ac.post(f"/forum/posts/{pid}/comments/{cid}/pin", headers=wh)
        assert r.status_code == 200, r.text
        assert r.json()["is_pinned"] is True

        # 详情里 can_manage 对白名单也为 True（前端据此显示置顶按钮）
        d = (await ac.get(f"/forum/posts/{pid}", headers=wh)).json()
        assert d["can_manage"] is True
        d = (await ac.get(f"/forum/posts/{pid}", headers=nh)).json()
        assert d["can_manage"] is False
