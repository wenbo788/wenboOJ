"""题目迁移（主题库 / 团队题 / 比赛赛题互搬）回归测试。

覆盖四个方向 + 权限拒绝 + 编号变化（P/U/T 体系由 team_id/is_official 决定）。
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.contest import Contest
from app.models.problem import REVIEW_APPROVED, REVIEW_DRAFT, Problem
from app.models.user import User


async def _register_and_login(ac: AsyncClient) -> tuple[str, dict, int]:
    suffix = uuid.uuid4().hex[:8]
    user, pwd = f"mig_{suffix}", "supersecret1"
    r = await ac.post("/users", json={
        "username": user, "email": f"{user}@example.com", "password": pwd})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    r = await ac.post("/tokens", data={"username": user, "password": pwd})
    assert r.status_code == 200, r.text
    return user, {"Authorization": f"Bearer {r.json()['access_token']}"}, uid


async def _patch_user(username: str, **fields) -> None:
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.username == username))).scalar_one()
        for k, v in fields.items():
            setattr(u, k, v)
        await db.commit()


async def _make_team(ac: AsyncClient, headers: dict, name: str) -> int:
    r = await ac.post("/teams", json={"name": name, "description": "迁移测试团队"}, headers=headers)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def _make_problem(ac: AsyncClient, headers: dict, title: str, **extra) -> dict:
    payload = {"title": title, "content": "题面内容", "difficulty": "普及", **extra}
    r = await ac.post("/problems", json=payload, headers=headers)
    assert r.status_code in (200, 201), r.text
    return r.json()


async def _get(problem_id: int) -> Problem:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(Problem).where(Problem.id == problem_id))).scalar_one()


@pytest.mark.asyncio
async def test_migrate_library_to_team_and_back():
    """主题库题 → 团队题（T 编号、退出主题库）→ 再搬回主题库（P 编号、正式公开）。"""
    sfx = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        author, ah, _ = await _register_and_login(ac)
        # 让作者成为题目管理（可建团队、可迁移）
        await _patch_user(author, can_manage_problems=True)

        team_id = await _make_team(ac, ah, f"迁移队-{sfx}")
        prob = await _make_problem(ac, ah, f"迁移题-{sfx}")
        pid = prob["id"]

        # 主题库题：team_id 为空
        p = await _get(pid)
        assert p.team_id is None

        # → 团队题
        r = await ac.post(f"/problems/{pid}/migrate",
                          json={"target": "team", "team_id": team_id}, headers=ah)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["team_id"] == team_id
        assert body["is_official"] is False
        assert body["problem_number"].startswith("T"), body

        p = await _get(pid)
        assert p.team_id == team_id and p.t_no is not None
        assert p.is_official is False

        # → 搬回主题库
        r = await ac.post(f"/problems/{pid}/migrate", json={"target": "library"}, headers=ah)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["team_id"] is None
        assert body["is_official"] is True
        assert body["problem_number"].startswith("P"), body

        p = await _get(pid)
        assert p.team_id is None and p.t_no is None and p.is_official is True


@pytest.mark.asyncio
async def test_migrate_library_to_contest_and_detach():
    """主题库题 → 比赛赛题（默认从主题库撤下）→ keep_in_library=true 时保留。"""
    sfx = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        author, ah, _ = await _register_and_login(ac)
        await _patch_user(author, can_manage_problems=True)

        # 比赛创建要求至少一道题：先建一道锚题
        anchor = await _make_problem(ac, ah, f"锚题-{sfx}")
        r = await ac.post("/contests", json={
            "title": f"迁移赛-{sfx}", "description": "迁移测试",
            "start_time": "2026-01-01T00:00:00", "end_time": "2036-01-01T00:00:00",
            "rule_type": "xcpc", "visibility": "public",
            "problem_ids": [anchor["id"]],
        }, headers=ah)
        assert r.status_code in (200, 201), r.text
        contest_id = r.json()["id"]

        prob = await _make_problem(ac, ah, f"赛事迁移题-{sfx}")
        pid = prob["id"]

        # 搬入比赛（默认撤出主题库）
        r = await ac.post(f"/problems/{pid}/migrate",
                          json={"target": "contest", "contest_id": contest_id}, headers=ah)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["is_official"] is False, "搬入比赛后默认应从主题库撤下"
        assert body["problem_number"].startswith("U"), body

        # 已在比赛里 → 再指定 keep_in_library=true 应保留在主题库且不重复挂载
        r = await ac.post(f"/problems/{pid}/migrate",
                          json={"target": "contest", "contest_id": contest_id,
                                "keep_in_library": True}, headers=ah)
        assert r.status_code == 200, r.text
        assert r.json()["is_official"] is True


@pytest.mark.asyncio
async def test_migrate_blocked_by_active_contest_shield():
    """进行中且开启「管理员参赛保护」的比赛里的题：非举办方的题管也不能迁走。"""
    sfx = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        organizer, oh, _ = await _register_and_login(ac)
        other_admin, xh, _ = await _register_and_login(ac)
        await _patch_user(organizer, can_manage_problems=True)
        await _patch_user(other_admin, can_manage_problems=True)

        prob = await _make_problem(ac, oh, f"受保护赛题-{sfx}")
        pid = prob["id"]
        r = await ac.post("/contests", json={
            "title": f"保护赛-{sfx}", "description": "保护测试",
            "start_time": "2026-01-01T00:00:00", "end_time": "2036-01-01T00:00:00",
            "rule_type": "xcpc", "visibility": "public", "problem_ids": [pid],
        }, headers=oh)
        assert r.status_code in (200, 201), r.text
        contest_id = r.json()["id"]

        # 开启「管理员参赛保护」
        async with AsyncSessionLocal() as db:
            c = (await db.execute(select(Contest).where(Contest.id == contest_id))).scalar_one()
            c.hide_submissions_from_admin = True
            await db.commit()

        # 非举办方的题管迁移 → 403（保护中）
        r = await ac.post(f"/problems/{pid}/migrate", json={"target": "library"}, headers=xh)
        assert r.status_code == 403, r.text
        assert "比赛" in r.json()["detail"]

        # 举办方本人不受该保护限制
        r = await ac.post(f"/problems/{pid}/migrate", json={"target": "library"}, headers=oh)
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_migrate_out_of_foreign_team_requires_source_team_manage():
    """作者不是当前所属团队的管理员时，不能把题从该团队单方面搬走。"""
    sfx = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        team_owner, toh, _ = await _register_and_login(ac)
        author, ah, author_id = await _register_and_login(ac)
        # 团队 owner 需要建题权限来造一道「挂在他团队下的题」
        await _patch_user(team_owner, can_manage_problems=True)

        team_id = await _make_team(ac, toh, f"源团队-{sfx}")

        # 造一道「作者是普通用户、却挂在别人团队下」的题
        owner_problem = await _make_problem(ac, toh, f"占位-{sfx}")
        async with AsyncSessionLocal() as db:
            p = (await db.execute(
                select(Problem).where(Problem.id == owner_problem["id"]))).scalar_one()
            p.team_id = team_id
            p.t_no = 990000 + (int(sfx, 16) % 9000)
            p.is_official = False
            p.author_id = author_id
            await db.commit()
        pid = owner_problem["id"]

        # 作者本人（非该团队管理员）→ 403 需要源团队管理权
        r = await ac.post(f"/problems/{pid}/migrate", json={"target": "library"}, headers=ah)
        assert r.status_code == 403, r.text
        assert "团队" in r.json()["detail"]


@pytest.mark.asyncio
async def test_migrate_permission_denied_for_stranger():
    """非作者且无题目管理权限 → 403；参数缺失 → 400。"""
    sfx = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        author, ah, _ = await _register_and_login(ac)
        _, other, _ = await _register_and_login(ac)
        # 作者需有题目管理权限才能建题（投题门槛）
        await _patch_user(author, can_manage_problems=True)

        prob = await _make_problem(ac, ah, f"权限迁移题-{sfx}")
        pid = prob["id"]

        # 路人：403
        r = await ac.post(f"/problems/{pid}/migrate", json={"target": "library"}, headers=other)
        assert r.status_code == 403, r.text

        # 未登录：401
        r = await ac.post(f"/problems/{pid}/migrate", json={"target": "library"})
        assert r.status_code == 401, r.text

        # 缺参数：400（作者本人）
        r = await ac.post(f"/problems/{pid}/migrate", json={"target": "team"}, headers=ah)
        assert r.status_code == 400, r.text
        r = await ac.post(f"/problems/{pid}/migrate", json={"target": "contest"}, headers=ah)
        assert r.status_code == 400, r.text

        # 目标不存在：404
        r = await ac.post(f"/problems/{pid}/migrate",
                          json={"target": "team", "team_id": 99999999}, headers=ah)
        assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_migrate_to_library_requires_approved_for_non_admin():
    """非题管把未过审的题迁入主题库 -> 400；过审后 -> 放行。

    守住的绕过：迁移会直接把 is_official 置真，若不做审核卡口，
    作者可拿草稿/被驳回的团队题绕过「提交进主题库」的审核流程直接公开。
    """
    sfx = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        author, ah, _ = await _register_and_login(ac)
        # 建题需要题目管理权限；建完再摘掉，回到「普通作者 + 团队 owner」
        await _patch_user(author, can_manage_problems=True)
        team_id = await _make_team(ac, ah, f"未审团队-{sfx}")
        prob = await _make_problem(ac, ah, f"未审团队题-{sfx}")
        pid = prob["id"]

        r = await ac.post(f"/problems/{pid}/migrate",
                          json={"target": "team", "team_id": team_id}, headers=ah)
        assert r.status_code == 200, r.text

        # 此时是团队题，作者仍是团队 owner，但不再是题目管理员
        await _patch_user(author, can_manage_problems=False)
        # 建题时作者是题管，题直接 approved；这里改回未过审，模拟草稿/被驳回的团队题
        async with AsyncSessionLocal() as db:
            p = (await db.execute(select(Problem).where(Problem.id == pid))).scalar_one()
            p.review_status = REVIEW_DRAFT
            p.is_public = False
            await db.commit()
        p = await _get(pid)
        assert p.team_id == team_id and p.is_official is False
        assert p.review_status != REVIEW_APPROVED, p.review_status

        # 未过审 -> 400，且归属未变
        r = await ac.post(f"/problems/{pid}/migrate", json={"target": "library"}, headers=ah)
        assert r.status_code == 400, r.text
        assert "审核" in r.json()["detail"]
        assert (await _get(pid)).team_id == team_id

        # 过审后（模拟审核通过）-> 200
        async with AsyncSessionLocal() as db:
            p = (await db.execute(select(Problem).where(Problem.id == pid))).scalar_one()
            p.review_status = "approved"
            p.is_public = True
            await db.commit()
        r = await ac.post(f"/problems/{pid}/migrate", json={"target": "library"}, headers=ah)
        assert r.status_code == 200, r.text
        assert r.json()["is_official"] is True
        assert r.json()["team_id"] is None


@pytest.mark.asyncio
async def test_keep_in_library_cannot_bypass_review():
    """非题管不能借 keep_in_library 把未公开的题塞进主题库。

    守住的绕过：target=contest 分支原先把 is_official 直接赋成 keep_in_library，
    绕过了 target=library 分支的审核卡口 —— 未过审的题挂进比赛时勾选
    「保留在主题库」就等于直接公开（若比赛还没开始，还会提前泄题）。
    """
    sfx = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        author, ah, _ = await _register_and_login(ac)
        await _patch_user(author, can_manage_problems=True)

        anchor = await _make_problem(ac, ah, f"保留锚题-{sfx}")
        r = await ac.post("/contests", json={
            "title": f"保留赛-{sfx}", "description": "keep_in_library 测试",
            "start_time": "2026-01-01T00:00:00", "end_time": "2036-01-01T00:00:00",
            "rule_type": "xcpc", "visibility": "public",
            "problem_ids": [anchor["id"]],
        }, headers=ah)
        assert r.status_code in (200, 201), r.text
        contest_id = r.json()["id"]

        prob = await _make_problem(ac, ah, f"保留测试题-{sfx}")
        pid = prob["id"]

        # 造一道「未公开/未过审」的题（草稿状态），并降级成普通作者
        async with AsyncSessionLocal() as db:
            p = (await db.execute(select(Problem).where(Problem.id == pid))).scalar_one()
            p.is_official = False
            p.is_public = False
            p.review_status = REVIEW_DRAFT
            await db.commit()
        await _patch_user(author, can_manage_problems=False)

        # 未过审 + keep_in_library -> 400，且题目没有因此变公开
        r = await ac.post(f"/problems/{pid}/migrate",
                          json={"target": "contest", "contest_id": contest_id,
                                "keep_in_library": True}, headers=ah)
        assert r.status_code == 400, r.text
        assert "保留在主题库" in r.json()["detail"]
        assert (await _get(pid)).is_official is False

        # 不勾 keep_in_library 则允许（只挂比赛，不进主题库）
        r = await ac.post(f"/problems/{pid}/migrate",
                          json={"target": "contest", "contest_id": contest_id}, headers=ah)
        assert r.status_code == 200, r.text
        assert r.json()["is_official"] is False

        # 题目本来就是主题库题（is_official + approved）时，保留才被允许
        async with AsyncSessionLocal() as db:
            p = (await db.execute(select(Problem).where(Problem.id == pid))).scalar_one()
            p.is_official = True
            p.is_public = True
            p.review_status = REVIEW_APPROVED
            await db.commit()
        r = await ac.post(f"/problems/{pid}/migrate",
                          json={"target": "contest", "contest_id": contest_id,
                                "keep_in_library": True}, headers=ah)
        assert r.status_code == 200, r.text
        assert r.json()["is_official"] is True
