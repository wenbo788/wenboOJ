"""用户题（U）与主题库题（P）测试。

规则：
- 普通用户创建的草稿/待审核/被驳回题 → 用户题 U{1000+id}；
- 审核通过正式公开 → 进入主题库，编号变为 P{1000+id}；
- 题目管理员建公开题 → 直接 P；
- 统一题号入口 P/U 不得串号。
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.user import User


async def register(ac: AsyncClient, name: str, pwd: str = "supersecret1") -> None:
    r = await ac.post("/users", json={
        "username": name, "email": f"{name}@example.com", "password": pwd})
    assert r.status_code == 201, r.text


async def login(ac: AsyncClient, name: str, pwd: str = "supersecret1") -> str:
    r = await ac.post("/tokens", data={"username": name, "password": pwd})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def grant_submit_eligibility(username: str, count: int = 15) -> None:
    """出题门槛（PROBLEM_SUBMIT_THRESHOLD=15）：普通用户投公开题前需在
    主题库通过 >=15 道该难度及以上的题。直接插 count 道入门题 +
    accepted 提交（统计口径：team_id IS NULL 且 difficulty >= 入门，
    即任意非团队题），绕过真实判题流程。"""
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.username == username))).scalar_one()
        for i in range(count):
            p = Problem(
                title=f"gate-{username}-{i}-{uuid.uuid4().hex[:4]}",
                difficulty="入门",
                is_public=True,
                review_status="approved",
            )
            db.add(p)
            await db.flush()
            db.add(Submission(
                problem_id=p.id, user_id=u.id,
                code="# ac", language="python",
                status="accepted", score=100,
            ))
        await db.commit()


@pytest.mark.asyncio
async def test_user_problem_gets_u_prefix():
    s = uuid.uuid4().hex[:8]
    normal, staff, other = f"n_{s}", f"s_{s}", f"o_{s}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        for name in (normal, staff, other):
            await register(ac, name)
        nt = await login(ac, normal)
        ot = await login(ac, other)

        # 出题门槛：给普通用户预置 15 道主题库 AC，满足投递资格
        await grant_submit_eligibility(normal)

        # 给 staff 题目管理权限后登录
        async with AsyncSessionLocal() as db:
            u = (await db.execute(select(User).where(User.username == staff))).scalar_one()
            u.can_manage_problems = True
            await db.commit()
        st = await login(ac, staff)

        # 普通用户建公开题：U 编号 + 待审核
        r = await ac.post("/problems", json={
            "title": f"u title {s}", "is_public": True}, headers=auth(nt))
        assert r.status_code == 200, r.text
        up = r.json()
        assert up["problem_number"] == f"U{1000 + up['id']}"
        assert up["review_status"] == "pending"

        # 草稿也是 U
        r = await ac.post("/problems", json={
            "title": f"draft {s}", "is_public": False}, headers=auth(nt))
        draft = r.json()
        assert draft["problem_number"] == f"U{1000 + draft['id']}"
        assert draft["review_status"] == "draft"

        # 题目管理员建公开题：P 编号 + 直接通过
        r = await ac.post("/problems", json={
            "title": f"p title {s}", "is_public": True}, headers=auth(st))
        pp = r.json()
        assert pp["problem_number"] == f"P{1000 + pp['id']}"
        assert pp["review_status"] == "approved"

        # 题目管理员审核通过普通用户的 pending 题：U → P
        r = await ac.post(f"/problems/{up['id']}/review",
                          json={"action": "approve"}, headers=auth(st))
        assert r.status_code == 200, r.text
        assert r.json()["problem_number"] == f"P{1000 + up['id']}"
        assert r.json()["review_status"] == "approved"

        # 公开后旧 U 编号失效，P 编号生效
        r = await ac.get(f"/problems/by-code/U{1000 + up['id']}", headers=auth(nt))
        assert r.status_code == 404, r.text
        r = await ac.get(f"/problems/by-code/P{1000 + up['id']}", headers=auth(nt))
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_by_code_u_prefix_routing_and_review():
    s = uuid.uuid4().hex[:8]
    normal, staff = f"n_{s}", f"s_{s}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        for name in (normal, staff):
            await register(ac, name)
        nt = await login(ac, normal)
        # 出题门槛：给普通用户预置 15 道主题库 AC，满足投递资格
        await grant_submit_eligibility(normal)
        async with AsyncSessionLocal() as db:
            u = (await db.execute(select(User).where(User.username == staff))).scalar_one()
            u.can_manage_problems = True
            await db.commit()
        st = await login(ac, staff)

        # 普通用户建题 → pending，得到 U 编号
        r = await ac.post("/problems", json={
            "title": f"title {s}", "is_public": True}, headers=auth(nt))
        pid = r.json()["id"]
        u_code, p_code = f"U{1000 + pid}", f"P{1000 + pid}"

        # 作者本人 U 号可访问
        r = await ac.get(f"/problems/by-code/{u_code}", headers=auth(nt))
        assert r.status_code == 200, r.text

        # P 号访问 U 题 → 404（不得串号）
        r = await ac.get(f"/problems/by-code/{p_code}", headers=auth(nt))
        assert r.status_code == 404, r.text

        # 再建一道官方 P 题验证反向串号
        r = await ac.post("/problems", json={
            "title": f"official {s}", "is_public": True}, headers=auth(st))
        off_id = r.json()["id"]
        r = await ac.get(f"/problems/by-code/U{1000 + off_id}", headers=auth(st))
        assert r.status_code == 404, r.text
        r = await ac.get(f"/problems/by-code/P{1000 + off_id}", headers=auth(st))
        assert r.status_code == 200, r.text

        # 题目管理员驳回 U 题：编号仍是 U
        r = await ac.post(f"/problems/{pid}/review",
                          json={"action": "reject", "reason": "题面不完整"},
                          headers=auth(st))
        assert r.status_code == 200, r.text
        assert r.json()["problem_number"] == f"U{1000 + pid}"
        assert r.json()["review_status"] == "rejected"

        # 再次提交并审核通过：U → P，旧 U 号随即失效
        r = await ac.post(f"/problems/{pid}/review",
                          json={"action": "approve"}, headers=auth(st))
        assert r.status_code == 200, r.text
        assert r.json()["problem_number"] == f"P{1000 + pid}"
        r = await ac.get(f"/problems/by-code/U{1000 + pid}", headers=auth(nt))
        assert r.status_code == 404, r.text
        r = await ac.get(f"/problems/by-code/P{1000 + pid}", headers=auth(nt))
        assert r.status_code == 200, r.text
