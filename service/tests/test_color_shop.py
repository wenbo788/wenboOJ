"""用户名颜色购买系统的回归测试。

规则（工单 #1028）：
- 灰 → 蓝（AC≥5，500 经验/100 贡献）→ 绿（AC≥10，1500/500）
  → 橙（主题库 AC≥1，5000/2500）→ 红（主题库 AC≥3，10000/5000）
- 只能逐级购买；用经验购买的花费计入排行榜总经验，用贡献购买的不计。
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.team import Team
from app.models.user import User


async def _make_user(ac: AsyncClient, tag: str):
    uname = f"cs_{tag}_{uuid.uuid4().hex[:6]}"
    r = await ac.post("/users", json={
        "username": uname, "email": f"{uname}@example.com",
        "password": "supersecret1"})
    assert r.status_code == 201, r.text
    return uname


async def _login(ac: AsyncClient, username: str):
    r = await ac.post("/tokens",
                      data={"username": username, "password": "supersecret1"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _user_number(username: str) -> int:
    async with AsyncSessionLocal() as db:
        u = (await db.execute(
            select(User).where(User.username == username))).scalar_one()
        return u.user_number


async def _set_balances(username: str, **kw):
    async with AsyncSessionLocal() as db:
        u = (await db.execute(
            select(User).where(User.username == username))).scalar_one()
        for k, v in kw.items():
            setattr(u, k, v)
        await db.commit()


async def _seed_accepts(
    username: str, n: int, *,
    official: bool = True, team: bool = False, non_official: bool = False,
):
    """为用户造 n 道题的去重 AC：每题独立 Problem + 一条 accepted Submission。"""
    async with AsyncSessionLocal() as db:
        u = (await db.execute(
            select(User).where(User.username == username))).scalar_one()
        # 团队题需要真实团队（外键约束），以该用户为 owner 建一个
        team_id = None
        if team:
            t = Team(name=f"团_{uuid.uuid4().hex[:8]}", owner_id=u.id)
            db.add(t)
            await db.flush()
            team_id = t.id
        for _ in range(n):
            p = Problem(
                title=f"题_{uuid.uuid4().hex[:8]}",
                description="x",
                team_id=team_id,
                is_official=False if non_official else official,
                review_status="approved", is_public=True,
            )
            db.add(p)
            await db.flush()
            db.add(Submission(
                problem_id=p.id, user_id=u.id, code="x", language="cpp",
                status="accepted", score=100,
            ))
        await db.commit()


async def _seed_authored(username: str, n: int):
    """为用户创建 n 道已审核通过的主题库题目（author_id=u.id, is_official=True, review_status='approved'）。"""
    async with AsyncSessionLocal() as db:
        u = (await db.execute(
            select(User).where(User.username == username))).scalar_one()
        for _ in range(n):
            p = Problem(
                title=f"自出题_{uuid.uuid4().hex[:8]}",
                description="x",
                author_id=u.id,
                team_id=None,
                is_official=True,
                is_public=True,
                review_status="approved",
            )
            db.add(p)
        await db.commit()


async def _my_ranking_row(ac: AsyncClient, h: dict, un: int) -> dict:
    data = await ac.get("/ranking", headers=h)
    assert data.status_code == 200, data.text
    for row in data.json()["items"]:
        if row["user_number"] == un:
            return row
    raise AssertionError("排行榜中未找到该用户")


@pytest.mark.asyncio
async def test_blue_purchase_with_experience_counts_in_ranking():
    """5 AC + 经验购买蓝名：color_exp_spent 加回排行榜总经验。"""
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://t") as ac:
        u = await _make_user(ac, "b")
        await _seed_accepts(u, 5)
        await _set_balances(u, experience=1000)
        h = await _login(ac, u)
        un = await _user_number(u)

        shop = (await ac.get("/shop/colors", headers=h)).json()
        blue = next(c for c in shop["colors"] if c["tier"] == "blue")
        assert blue["eligible"] and blue["can_buy_exp"]

        r = await ac.post("/shop/colors/purchase",
                          json={"tier": "blue", "currency": "experience"},
                          headers=h)
        assert r.status_code == 200, r.text
        shop = (await ac.get("/shop/colors", headers=h)).json()
        assert shop["current_tier"] == "blue"
        assert shop["color_exp_spent"] == 500

        row = await _my_ranking_row(ac, h, un)
        # 余额 500 + 颜色花费 500 = 总经验 1000
        assert row["experience"] == 500
        assert row["color_experience"] == 500
        assert row["total_experience"] == 1000


@pytest.mark.asyncio
async def test_requirement_and_step_gate():
    """未达门槛/跳级/灰名/非法档位与货币 → 400/404。"""
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://t") as ac:
        u = await _make_user(ac, "g")
        await _set_balances(u, experience=99999, contribution=99999)
        h = await _login(ac, u)

        # 0 AC：蓝名资格不足
        r = await ac.post("/shop/colors/purchase",
                          json={"tier": "blue", "currency": "experience"},
                          headers=h)
        assert r.status_code == 400 and "5" in r.json()["detail"], r.text

        # 跳级买绿名（即使钱够）
        r = await ac.post("/shop/colors/purchase",
                          json={"tier": "green", "currency": "experience"},
                          headers=h)
        assert r.status_code == 400 and "蓝名" in r.json()["detail"], r.text

        # 灰名无需购买
        r = await ac.post("/shop/colors/purchase",
                          json={"tier": "gray", "currency": "experience"},
                          headers=h)
        assert r.status_code == 400, r.text

        # 非法档位 / 非法货币
        r = await ac.post("/shop/colors/purchase",
                          json={"tier": "pink", "currency": "experience"},
                          headers=h)
        assert r.status_code == 404, r.text
        r = await ac.post("/shop/colors/purchase",
                          json={"tier": "blue", "currency": "coin"},
                          headers=h)
        assert r.status_code == 400, r.text

        # 5 AC 达标但经验余额不足
        await _seed_accepts(u, 5)
        await _set_balances(u, experience=10)
        r = await ac.post("/shop/colors/purchase",
                          json={"tier": "blue", "currency": "experience"},
                          headers=h)
        assert r.status_code == 400 and "经验不足" in r.json()["detail"], r.text


@pytest.mark.asyncio
async def test_contrib_purchase_not_counted_in_ranking():
    """贡献购买蓝名：color_exp_spent=0，排行榜总经验不加。"""
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://t") as ac:
        u = await _make_user(ac, "c")
        await _seed_accepts(u, 5)
        await _set_balances(u, experience=100, contribution=100)
        h = await _login(ac, u)
        un = await _user_number(u)

        r = await ac.post("/shop/colors/purchase",
                          json={"tier": "blue", "currency": "contribution"},
                          headers=h)
        assert r.status_code == 200, r.text

        shop = (await ac.get("/shop/colors", headers=h)).json()
        assert shop["current_tier"] == "blue"
        assert shop["color_exp_spent"] == 0

        row = await _my_ranking_row(ac, h, un)
        assert row["color_experience"] == 0
        assert row["total_experience"] == 100  # 仅余额，不加颜色


@pytest.mark.asyncio
async def test_official_count_excludes_team_and_unofficial():
    """主题库口径：团队题、U 题（is_official=False）不计入主题库 AC。"""
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://t") as ac:
        u = await _make_user(ac, "o")
        await _seed_accepts(u, 3)                       # 3 道主题库 P 题
        await _seed_accepts(u, 2, team=True)           # 2 道团队题
        await _seed_accepts(u, 2, non_official=True)   # 2 道 U 题
        h = await _login(ac, u)

        shop = (await ac.get("/shop/colors", headers=h)).json()
        assert shop["solved"] == 7
        assert shop["official_solved"] == 3


@pytest.mark.asyncio
async def test_full_chain_mixed_currency():
    """灰→蓝(经验)→绿(贡献)→橙(经验)→红(经验)：逐档放行，花费累计正确。"""
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://t") as ac:
        u = await _make_user(ac, "f")
        await _seed_accepts(u, 10)   # 10 道主题库 AC：满足做题门槛
        await _seed_authored(u, 3)   # 3 道自出审核通过主题库题：满足出题门槛
        await _set_balances(u, experience=20000, contribution=500)
        h = await _login(ac, u)
        un = await _user_number(u)

        for tier, currency in [
            ("blue", "experience"),
            ("green", "contribution"),
            ("orange", "experience"),
            ("red", "experience"),
        ]:
            r = await ac.post("/shop/colors/purchase",
                              json={"tier": tier, "currency": currency},
                              headers=h)
            assert r.status_code == 200, r.text

        shop = (await ac.get("/shop/colors", headers=h)).json()
        assert shop["current_tier"] == "red"
        # 仅经验货币累计：500 + 5000 + 10000（绿名走贡献，不计）
        assert shop["color_exp_spent"] == 15500

        row = await _my_ranking_row(ac, h, un)
        # 经验余额 20000 - 15500 = 4500；总经验 = 4500 + 15500 = 20000
        assert row["experience"] == 4500
        assert row["total_experience"] == 20000
