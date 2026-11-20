"""「我的题库」回归测试。

需求：U 题（草稿 / 待审核 / 被驳回，即未进主题库的题）归作者自己的「我的题库」，
不再出现在主题库列表里；作者可从我的题库一键提交进主题库（审核通过后转 P 编号）。
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.problem import Problem
from app.models.user import User


async def _register_and_login(ac: AsyncClient) -> tuple[str, dict, int]:
    suffix = uuid.uuid4().hex[:8]
    user, pwd = f"bank_{suffix}", "supersecret1"
    r = await ac.post("/users", json={
        "username": user, "email": f"{user}@example.com", "password": pwd})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    r = await ac.post("/tokens", data={"username": user, "password": pwd})
    assert r.status_code == 200, r.text
    return user, {"Authorization": f"Bearer {r.json()['access_token']}"}, uid


async def _patch_user(username: str, **fields) -> None:
    from sqlalchemy.exc import NoResultFound

    async with AsyncSessionLocal() as db:
        try:
            u = (await db.execute(select(User).where(User.username == username))).scalar_one()
        except NoResultFound:
            # 直接抛 SQLAlchemy 异常时失败信息很难定位，转成明确的测试数据错误
            raise ValueError(f"测试数据准备失败：数据库里找不到用户 {username!r}")
        for k, v in fields.items():
            setattr(u, k, v)
        await db.commit()


async def _create_problem(ac: AsyncClient, headers: dict, title: str, *, public: bool) -> dict:
    r = await ac.post("/problems", json={
        "title": title, "content": "题面", "difficulty": "普及", "is_public": public,
    }, headers=headers)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _titles(data: dict) -> set[str]:
    return {p["title"] for p in data.get("items", [])}


@pytest.mark.asyncio
async def test_library_list_has_no_u_problems_but_mine_does():
    """主题库列表（含题管视角）不再混入 U 题；它们只在「我的题库」里。"""
    sfx = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        author, ah, _ = await _register_and_login(ac)
        await _patch_user(author, can_manage_problems=True)
        # 题库列表需要登录：再用一个普通用户（非题管）看主题库默认视图
        _, viewer, _ = await _register_and_login(ac)

        draft_title = f"U草稿-{sfx}"   # is_public=False → 草稿（U 编号）
        pub_title = f"P已进库-{sfx}"   # 题管公开 → 直接 approved（P 编号）
        draft = await _create_problem(ac, ah, draft_title, public=False)
        pub = await _create_problem(ac, ah, pub_title, public=True)
        assert draft["problem_number"].startswith("U"), draft
        assert pub["problem_number"].startswith("P"), pub

        # 1) 主题库默认视图（普通用户）：只有 P
        data = (await ac.get("/problems", params={"keyword": sfx}, headers=viewer)).json()
        titles = _titles(data)
        assert pub_title in titles, data
        assert draft_title not in titles, "U 题不该出现在主题库列表"

        # 2) 题管 with all=true：仍然只有 P（U 题不再被混进来）
        data = (await ac.get("/problems", params={"keyword": sfx, "all": True}, headers=ah)).json()
        titles_all = _titles(data)
        assert pub_title in titles_all
        assert draft_title not in titles_all, "题管视角也不应把 U 题列进主题库"

        # 3) 审核队列（scope=review）：U 题在这边可见，供管理
        data = (await ac.get("/problems", params={"keyword": sfx, "scope": "review"}, headers=ah)).json()
        assert draft_title in _titles(data), "审核队列必须能看到未进库的题"

        # 4) 我的题库（scope=mine）：草稿与已进库的都在
        data = (await ac.get("/problems", params={"keyword": sfx, "scope": "mine"}, headers=ah)).json()
        mine_titles = _titles(data)
        assert {draft_title, pub_title} <= mine_titles


@pytest.mark.asyncio
async def test_submit_to_library_flow():
    """我的题库里的草稿 → 提交 → 待审核（仍是 U）→ 审核通过 → 进主题库（P）。"""
    sfx = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        author, ah, _ = await _register_and_login(ac)
        await _patch_user(author, can_manage_problems=True)

        prob = await _create_problem(ac, ah, f"待提交-{sfx}", public=False)
        pid = prob["id"]

        # 提交进主题库
        r = await ac.post(f"/problems/{pid}/submit-to-library", headers=ah)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["review_status"] == "pending"
        assert body["problem_number"].startswith("U"), "提交后仍在审核，编号还是 U"

        # 提交后仍不在主题库列表（未通过审核）
        data = (await ac.get("/problems", params={"keyword": sfx}, headers=ah)).json()
        assert f"待提交-{sfx}" not in _titles(data)

        # 重复提交 → 400（已在审核中）
        r = await ac.post(f"/problems/{pid}/submit-to-library", headers=ah)
        assert r.status_code == 400, r.text

        # 审核通过 → 进主题库（P）
        r = await ac.post(f"/problems/{pid}/review", json={"action": "approve"}, headers=ah)
        assert r.status_code == 200, r.text
        data = (await ac.get("/problems", params={"keyword": sfx}, headers=ah)).json()
        assert f"待提交-{sfx}" in _titles(data), "审核通过后应出现在主题库列表"

        # 已在主题库 → 再提交 400
        r = await ac.post(f"/problems/{pid}/submit-to-library", headers=ah)
        assert r.status_code == 400, r.text
        assert "主题库" in r.json()["detail"]


@pytest.mark.asyncio
async def test_submit_to_library_permission():
    """非作者不可提交（403）；未登录 401。"""
    sfx = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        author, ah, _ = await _register_and_login(ac)
        _, other, _ = await _register_and_login(ac)
        await _patch_user(author, can_manage_problems=True)

        prob = await _create_problem(ac, ah, f"权限提交-{sfx}", public=False)
        pid = prob["id"]

        r = await ac.post(f"/problems/{pid}/submit-to-library", headers=other)
        assert r.status_code == 403, r.text
        r = await ac.post(f"/problems/{pid}/submit-to-library")
        assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_submit_to_library_blocked_by_eligibility():
    """普通用户（无题目管理权限、AC 数不足 15）提交 → 被投题门槛拦下（403）。"""
    sfx = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        admin, ah, _ = await _register_and_login(ac)
        await _patch_user(admin, can_manage_problems=True)
        _, uh, uid = await _register_and_login(ac)

        # 普通用户建不了题（同样受门槛），先由题管建好草稿再把作者改成他
        prob = await _create_problem(ac, ah, f"门槛提交-{sfx}", public=False)
        async with AsyncSessionLocal() as db:
            p = (await db.execute(
                select(Problem).where(Problem.id == prob["id"]))).scalar_one()
            p.author_id = uid
            await db.commit()

        r = await ac.post(f"/problems/{prob['id']}/submit-to-library", headers=uh)
        assert r.status_code == 403, r.text
        detail = r.json()["detail"]
        assert ("投递" in detail) or ("通过" in detail), detail


@pytest.mark.asyncio
async def test_submit_to_library_rejects_changed_state():
    """读-改-写窗口期内题目已被审核通过时，条件 UPDATE 不会把它覆写回 pending。"""
    sfx = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        admin, ah, _ = await _register_and_login(ac)
        await _patch_user(admin, can_manage_problems=True)

        prob = await _create_problem(ac, ah, f"状态竞态-{sfx}", public=False)
        pid = prob["id"]

        # 模拟并发：提交请求到达前，管理员已把题审核通过（is_official=True）
        async with AsyncSessionLocal() as db:
            p = (await db.execute(select(Problem).where(Problem.id == pid))).scalar_one()
            p.is_official = True
            p.review_status = "approved"
            await db.commit()

        r = await ac.post(f"/problems/{pid}/submit-to-library", headers=ah)
        assert r.status_code == 400, r.text

        # 关键：状态没有被覆写成 pending
        async with AsyncSessionLocal() as db:
            p = (await db.execute(select(Problem).where(Problem.id == pid))).scalar_one()
            assert p.review_status == "approved", "已入库的题不该被覆写成待审核"
            assert p.is_official is True
