"""站内投票的回归测试。

要钉住的：
1. 发起：只有管理员能建；标题/选项数量/重复/截止时间都有校验；
2. 投票：登录用户一人一票；单选只能一个；多选可多个；**改票**会替换旧选择；
3. 结束：截止时间过了 / 手动关闭后不能再投；
4. 结果可见性：关掉「结束前公开票数」时普通用户看不到票数，发起者/管理员能看；
5. 匿名投票不返回投票人名单。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.main import app
from app.models.user import User

PWD = "supersecret1"


async def _make_user(tag: str, **fields) -> str:
    uname = f"po_{tag}_{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        used = set((await db.execute(select(User.user_number))).scalars())
        num = 889000
        while num in used:
            num += 1
        db.add(User(user_number=num, username=uname, email=f"{uname}@example.com",
                    hashed_password=hash_password(PWD), is_active=True, **fields))
        await db.commit()
    return uname


async def _login(ac: AsyncClient, username: str) -> dict:
    r = await ac.post("/tokens", data={"username": username, "password": PWD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _create_poll(ac, h, **over):
    payload = {"title": "晚饭吃什么", "options": ["面条", "米饭", "火锅"], **over}
    return await ac.post("/polls", headers=h, json=payload)


@pytest.mark.asyncio
async def test_admin_can_create_and_plain_user_cannot():
    admin = await _make_user("admin", can_manage_users=True)
    plain = await _make_user("plain")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        ha = await _login(ac, admin)
        r = await _create_poll(ac, ha)
        assert r.status_code == 201, r.text
        body = r.json()
        assert len(body["options"]) == 3 and body["open"] is True
        assert body["total_votes"] == 0

        hp = await _login(ac, plain)
        assert (await _create_poll(ac, hp)).status_code == 403

        # 参数校验
        for bad, keyword in (
            ({"title": ""}, "标题"),
            ({"options": ["只有一个"]}, "至少"),
            ({"options": ["a", "a"]}, "重复"),
            ({"options": [f"o{i}" for i in range(11)]}, "最多"),
            ({"ends_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}, "截止"),
        ):
            r = await _create_poll(ac, ha, **bad)
            assert r.status_code == 400, (bad, r.text)
            assert keyword in r.json()["detail"], (bad, r.text)


@pytest.mark.asyncio
async def test_single_choice_vote_and_change_vote():
    admin = await _make_user("admin", can_manage_users=True)
    voter = await _make_user("voter")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        ha = await _login(ac, admin)
        poll = (await _create_poll(ac, ha)).json()
        oids = [o["id"] for o in poll["options"]]

        hv = await _login(ac, voter)
        # 单选不能勾两个
        r = await ac.post(f"/polls/{poll['id']}/vote",
                          json={"option_ids": [oids[0], oids[1]]}, headers=hv)
        assert r.status_code == 400 and "单选" in r.json()["detail"], r.text

        # 投一票
        r = await ac.post(f"/polls/{poll['id']}/vote", json={"option_ids": [oids[0]]}, headers=hv)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["my_votes"] == [oids[0]]
        assert body["options"][0]["votes"] == 1
        assert body["total_votes"] == 1 and body["voter_count"] == 1

        # 改票：旧选择被替换，总数不变
        r = await ac.post(f"/polls/{poll['id']}/vote", json={"option_ids": [oids[2]]}, headers=hv)
        body = r.json()
        assert body["my_votes"] == [oids[2]]
        assert body["options"][0]["votes"] == 0 and body["options"][2]["votes"] == 1
        assert body["total_votes"] == 1

        # 选项不属于这个投票
        r = await ac.post(f"/polls/{poll['id']}/vote", json={"option_ids": [999999]}, headers=hv)
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_multi_choice_and_close_blocks_voting():
    admin = await _make_user("admin", can_manage_users=True)
    voter = await _make_user("voter")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        ha = await _login(ac, admin)
        poll = (await _create_poll(ac, ha, allow_multiple=True)).json()
        oids = [o["id"] for o in poll["options"]]

        hv = await _login(ac, voter)
        r = await ac.post(f"/polls/{poll['id']}/vote",
                          json={"option_ids": [oids[0], oids[2]]}, headers=hv)
        assert r.status_code == 200, r.text
        body = r.json()
        assert sorted(body["my_votes"]) == sorted([oids[0], oids[2]])
        assert body["total_votes"] == 2

        # 发起者关闭后不能再投
        r = await ac.post(f"/polls/{poll['id']}/close", headers=ha)
        assert r.status_code == 200 and r.json()["open"] is False
        r = await ac.post(f"/polls/{poll['id']}/vote", json={"option_ids": [oids[1]]}, headers=hv)
        assert r.status_code == 400 and "结束" in r.json()["detail"]


@pytest.mark.asyncio
async def test_results_hidden_before_end_and_anonymous_hides_voters():
    admin = await _make_user("admin", can_manage_users=True)
    voter = await _make_user("voter")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        ha = await _login(ac, admin)
        poll = (await _create_poll(
            ac, ha, show_results_before_end=False, anonymous=True)).json()
        oids = [o["id"] for o in poll["options"]]

        hv = await _login(ac, voter)
        await ac.post(f"/polls/{poll['id']}/vote", json={"option_ids": [oids[0]]}, headers=hv)

        # 普通用户：结束前看不到票数
        r = await ac.get(f"/polls/{poll['id']}", headers=hv)
        body = r.json()
        assert body["results_visible"] is False
        assert all(o["votes"] is None for o in body["options"])
        assert body["total_votes"] is None

        # 发起者能看，且因为匿名不返回投票人名单
        r = await ac.get(f"/polls/{poll['id']}", headers=ha)
        boss = r.json()
        assert boss["results_visible"] is True
        assert boss["options"][0]["votes"] == 1
        assert boss["voters"] == []

        # 结束后普通用户也能看
        await ac.post(f"/polls/{poll['id']}/close", headers=ha)
        r = await ac.get(f"/polls/{poll['id']}", headers=hv)
        assert r.json()["results_visible"] is True


@pytest.mark.asyncio
async def test_list_filters_open_and_closed():
    admin = await _make_user("admin", can_manage_users=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        ha = await _login(ac, admin)
        p1 = (await _create_poll(ac, ha, title="进行中的投票")).json()
        p2 = (await _create_poll(ac, ha, title="已结束的投票")).json()
        await ac.post(f"/polls/{p2['id']}/close", headers=ha)

        r = await ac.get("/polls?status=open&page_size=50", headers=ha)
        titles = [x["title"] for x in r.json()["items"]]
        assert "进行中的投票" in titles and "已结束的投票" not in titles

        r = await ac.get("/polls?status=closed&page_size=50", headers=ha)
        titles = [x["title"] for x in r.json()["items"]]
        assert "已结束的投票" in titles and "进行中的投票" not in titles


@pytest.mark.asyncio
async def test_list_paginates_in_sql_and_bad_option_id_is_friendly():
    """列表分页/状态过滤走 SQL；非法选项 ID 给友好错误（评审 2 阻断）。"""
    admin = await _make_user("admin", can_manage_users=True)
    voter = await _make_user("voter")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        ha = await _login(ac, admin)
        # 造 5 个投票：3 个进行中、2 个已结束
        ids = []
        for i in range(5):
            r = await _create_poll(ac, ha, title=f"分页投票 {i}")
            assert r.status_code == 201, r.text
            ids.append(r.json()["id"])
        for pid in ids[3:]:
            assert (await ac.post(f"/polls/{pid}/close", headers=ha)).status_code == 200

        # 状态过滤在 SQL 里。别的用例也建过投票，所以只做「相对」断言
        r = await ac.get("/polls?status=open&page=0&page_size=2", headers=ha)
        body = r.json()
        assert body["total"] >= 3, body
        assert len(body["items"]) == 2
        assert all("已结束" != x["title"] for x in body["items"])
        # 第二页拿到剩下的，且不与第一页重复
        r2 = await ac.get("/polls?status=open&page=1&page_size=2", headers=ha)
        assert len(r2.json()["items"]) == min(2, body["total"] - 2)
        first_ids = {x["id"] for x in body["items"]}
        second_ids = {x["id"] for x in r2.json()["items"]}
        assert not (first_ids & second_ids)
        # 我建的三个进行中投票都在 open 列表里
        all_open = {x["id"] for x in body["items"]} | second_ids
        assert set(ids[:3]) <= all_open

        r = await ac.get("/polls?status=closed&page=0&page_size=10", headers=ha)
        assert r.json()["total"] >= 2
        assert {x["id"] for x in r.json()["items"]} >= set(ids[3:])

        # 非法选项 ID：400 + 友好提示，不暴露 Python 异常
        hv = await _login(ac, voter)
        r = await ac.post(f"/polls/{ids[0]}/vote", json={"option_ids": ["not-a-number"]}, headers=hv)
        assert r.status_code == 400, r.text
        assert "格式不正确" in r.json()["detail"], r.text
        assert "invalid literal" not in r.json()["detail"]
