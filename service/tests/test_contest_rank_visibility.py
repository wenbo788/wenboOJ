"""比赛排行榜可见性回归测试。

规则（与比赛题目可见性一致）：
  - 未开始 → 任何人不可看（防赛前偷看）
  - 进行中 → 仅报名者 / 团主 / 团队管理员 / 比赛管理员可看
  - 已结束 → 对全站公开（含未报名者与未登录用户）

这里专门覆盖「比赛结束后」，防止把已结束比赛的排行榜误锁。
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.user import User


async def _reg_login(ac: AsyncClient) -> tuple[dict, int]:
    s = uuid.uuid4().hex[:8]
    u = f"rk_{s}"
    p = "supersecret1"
    r = await ac.post("/users", json={
        "username": u, "email": f"{u}@example.com", "password": p})
    assert r.status_code == 201, r.text
    r = await ac.post("/tokens", data={"username": u, "password": p})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await ac.get("/auth/me", headers=h)).json()
    return h, me["id"]


async def _seed_contest(owner_id: int, window: str) -> int:
    from app.models.contest import Contest, ContestProblem
    from app.models.problem import Problem

    now = datetime.now(timezone.utc)
    spans = {
        "pending": (now + timedelta(hours=1), now + timedelta(hours=3)),
        "running": (now - timedelta(hours=1), now + timedelta(hours=3)),
        "ended": (now - timedelta(days=2), now - timedelta(days=1)),
    }
    start, end = spans[window]
    async with AsyncSessionLocal() as db:
        prob = Problem(title="A+B", difficulty="入门", description="求和", is_public=True)
        db.add(prob)
        await db.flush()
        contest = Contest(title=f"rank-{window}", visibility="public",
                          start_time=start, end_time=end, owner_id=owner_id)
        db.add(contest)
        await db.flush()
        db.add(ContestProblem(contest_id=contest.id, problem_id=prob.id, sort_order=0))
        await db.commit()
        return contest.id


@pytest.mark.asyncio
async def test_ended_rank_is_public_to_everyone():
    """比赛结束后：未报名者、未登录用户都能查看排行榜。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        owner_h, owner_id = await _reg_login(ac)
        outsider_h, _ = await _reg_login(ac)
        cid = await _seed_contest(owner_id, "ended")

        # 未报名者
        r = await ac.get(f"/contests/{cid}/rank", headers=outsider_h)
        assert r.status_code == 200, r.text
        assert r.json()["rows"] == []

        # 未登录用户
        r = await ac.get(f"/contests/{cid}/rank")
        assert r.status_code == 200, r.text

        # 详情页也标记为可查看题目/排行榜
        d = (await ac.get(f"/contests/{cid}", headers=outsider_h)).json()
        assert d["status"] == "ended"
        assert d["can_view_problems"] is True


@pytest.mark.asyncio
async def test_running_rank_only_for_participants_and_pending_hidden():
    """进行中：未报名者 403、报名者 200；未开始：一律 403。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        owner_h, owner_id = await _reg_login(ac)
        outsider_h, _ = await _reg_login(ac)

        run_id = await _seed_contest(owner_id, "running")
        assert (await ac.get(f"/contests/{run_id}/rank", headers=outsider_h)).status_code == 403

        r = await ac.post(f"/contests/{run_id}/register", headers=outsider_h, json={})
        assert r.status_code == 200, r.text
        assert (await ac.get(f"/contests/{run_id}/rank", headers=outsider_h)).status_code == 200

        pend_id = await _seed_contest(owner_id, "pending")
        assert (await ac.get(f"/contests/{pend_id}/rank", headers=outsider_h)).status_code == 403
