"""比赛题的普通提交通道与提交记录列表守卫。

规则：
  1. 题目挂在未结束的比赛里 → 普通提交（不带 contest_id）一律拒绝：
     未开始 →「比赛开始后才能提交」；进行中 →「请从比赛页面提交」。
     否则赛前赛中都能拿真实测试数据反复调试（逐点结果/分数全可见），
     OI 赛制「赛中隐藏结果」也会被 contest_id=None 这条通道绕过。
     出题人 / 题目管理员 / 比赛创建者豁免（他们本来就能看到测试数据）。
  2. 比赛内提交（带 contest_id）沿用原有规则：开赛 + 报名 + 题目属于该比赛。
  3. 比赛结束后题目回归普通题库，普通提交恢复。
  4. 提交记录列表与题面同口径：未公开题 404（防遍历 id 探测标题/动态）；
     未结束比赛的题，未报名或未开赛 403。
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


async def _register_and_login(ac: AsyncClient) -> tuple[dict[str, str], int]:
    suffix = uuid.uuid4().hex[:8]
    username = f"sg_{suffix}"
    password = "supersecret1"
    r = await ac.post(
        "/users",
        json={"username": username, "email": f"{username}@example.com", "password": password},
    )
    assert r.status_code == 201, r.text
    r = await ac.post("/tokens", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await ac.get("/auth/me", headers=headers)).json()
    return headers, me["id"]


async def _seed(
    owner_id: int, *, window: str, participants: list[int] | None = None,
    is_public: bool = True,
) -> tuple[int, int | None]:
    """建一道带测试点的题（可选挂比赛），返回 (problem_id, contest_id|None)。

    window: "pending" / "running" / "ended" / "none"（不挂比赛）
    """
    from app.core.database import AsyncSessionLocal
    from app.models.contest import Contest, ContestParticipant, ContestProblem
    from app.models.problem import Problem
    from app.models.submission import TestCase

    now = datetime.now(timezone.utc)
    spans = {
        "pending": (now + timedelta(hours=1), now + timedelta(hours=4)),
        "running": (now - timedelta(hours=1), now + timedelta(hours=3)),
        "ended": (now - timedelta(days=2), now - timedelta(days=1)),
    }

    async with AsyncSessionLocal() as db:
        prob = Problem(title="A+B", difficulty="入门", description="求和",
                       is_public=is_public)
        db.add(prob)
        await db.flush()
        db.add(TestCase(problem_id=prob.id, input_data="1 2\n",
                        expected_output="3\n", sort_order=0))

        contest_id = None
        if window != "none":
            start, end = spans[window]
            contest = Contest(title=f"测试赛-{window}", visibility="public",
                              start_time=start, end_time=end, owner_id=owner_id)
            db.add(contest)
            await db.flush()
            db.add(ContestProblem(contest_id=contest.id, problem_id=prob.id,
                                  sort_order=0))
            for uid in participants or []:
                db.add(ContestParticipant(contest_id=contest.id, user_id=uid))
            contest_id = contest.id
        await db.commit()
        return prob.id, contest_id


def _payload(contest_id: int | None = None) -> dict:
    body = {"code": "int main() { return 0; }", "language": "cpp"}
    if contest_id is not None:
        body["contest_id"] = contest_id
    return body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "window,expect_detail",
    [("pending", "比赛开始后才能提交"), ("running", "正在进行比赛")],
)
async def test_plain_submission_to_contest_problem_blocked(window, expect_detail):
    """未结束的比赛题：普通通道对所有人关闭（含已报名者——防双通道作弊）。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        owner, owner_id = await _register_and_login(ac)
        player, player_id = await _register_and_login(ac)   # 已报名
        stranger, _ = await _register_and_login(ac)          # 未报名
        pid, cid = await _seed(owner_id, window=window,
                               participants=[player_id])

        for headers in (stranger, player):
            r = await ac.post(f"/problems/{pid}/submissions", headers=headers,
                              json=_payload())
            assert r.status_code == 400, r.text
            assert expect_detail in r.json()["detail"]


@pytest.mark.asyncio
async def test_owner_exempt_from_plain_submission_guard():
    """出题人 / 比赛创建者豁免：挂自己的题办比赛，赛前照常自测提交。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        owner, owner_id = await _register_and_login(ac)
        pid, _cid = await _seed(owner_id, window="pending")

        r = await ac.post(f"/problems/{pid}/submissions", headers=owner,
                          json=_payload())
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_contest_submission_path_unchanged():
    """带 contest_id 的路径维持原规则：未开赛 400、未报名 403、正常 200。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        owner, owner_id = await _register_and_login(ac)
        player, _ = await _register_and_login(ac)
        outsider, _ = await _register_and_login(ac)

        # 未开赛：400（原有时间窗校验）
        pid_p, cid_p = await _seed(owner_id, window="pending", participants=[])
        from app.core.database import AsyncSessionLocal
        from app.models.contest import ContestParticipant
        async with AsyncSessionLocal() as db:
            db.add(ContestParticipant(contest_id=cid_p, user_id=(await ac.get(
                "/auth/me", headers=player)).json()["id"]))
            await db.commit()
        r = await ac.post(f"/problems/{pid_p}/submissions", headers=player,
                          json=_payload(cid_p))
        assert r.status_code == 400, r.text
        assert "尚未开始" in r.json()["detail"]

        # 进行中 + 未报名：403
        pid_r, cid_r = await _seed(owner_id, window="running", participants=[])
        r = await ac.post(f"/problems/{pid_r}/submissions", headers=outsider,
                          json=_payload(cid_r))
        assert r.status_code == 403, r.text
        assert "报名" in r.json()["detail"]

        # 进行中 + 已报名：200（比赛内正常提交）
        async with AsyncSessionLocal() as db:
            db.add(ContestParticipant(contest_id=cid_r, user_id=(await ac.get(
                "/auth/me", headers=outsider)).json()["id"]))
            await db.commit()
        r = await ac.post(f"/problems/{pid_r}/submissions", headers=outsider,
                          json=_payload(cid_r))
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_plain_submission_allowed_after_contest_ends():
    """已结束：题目回归普通题库，普通提交恢复。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        owner, owner_id = await _register_and_login(ac)
        outsider, _ = await _register_and_login(ac)
        pid, _cid = await _seed(owner_id, window="ended")

        r = await ac.post(f"/problems/{pid}/submissions", headers=outsider,
                          json=_payload())
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_submission_list_guarded_like_problem_statement():
    """提交列表与题面同口径：未公开题 404；比赛题未报名 403、报名后 200。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        owner, owner_id = await _register_and_login(ac)
        outsider, _ = await _register_and_login(ac)

        # 未公开题：按不存在处理（之前遍历 id 就能看到标题和提交动态）
        hidden_id, _ = await _seed(owner_id, window="none", is_public=False)
        r = await ac.get(f"/problems/{hidden_id}/submissions", headers=outsider)
        assert r.status_code == 404, r.text

        # 比赛进行中：未报名者连提交列表都拿不到
        pid, cid = await _seed(owner_id, window="running")
        r = await ac.get(f"/problems/{pid}/submissions", headers=outsider)
        assert r.status_code == 403, r.text

        # 报名后放行
        assert (await ac.post(f"/contests/{cid}/register", headers=outsider,
                              json={})).status_code == 200
        r = await ac.get(f"/problems/{pid}/submissions", headers=outsider)
        assert r.status_code == 200, r.text

        # 比赛外的公开题不受影响
        free_id, _ = await _seed(owner_id, window="none")
        r = await ac.get(f"/problems/{free_id}/submissions", headers=outsider)
        assert r.status_code == 200, r.text
