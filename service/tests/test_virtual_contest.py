"""虚拟参赛（virtual contest）的回归测试。

要钉住的几条：
1. 只有**已结束的个人赛**能开虚拟赛；进行中/组队赛拒绝；
2. 开局给一个人的计时窗（remaining_seconds > 0），重复开局返回同一个；
3. 虚拟赛窗口内的提交**允许**（即使原比赛已结束、即使没报名），且带
   `virtual_contest_id`；结束后再交就被挡回去；
4. 真实排行榜、等级分结算都**排除**虚拟提交 —— 否则个人练习会污染真实成绩。
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
from app.models.contest import Contest, ContestParticipant, ContestProblem
from app.models.problem import Problem, REVIEW_APPROVED
from app.models.submission import Submission, TestCase as CaseRow
from app.models.user import User
from app.models.virtual_contest import VirtualContest

PWD = "supersecret1"


async def _make_user(tag: str, **fields) -> str:
    uname = f"vc_{tag}_{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        used = set((await db.execute(select(User.user_number))).scalars())
        num = 886000
        while num in used:
            num += 1
        db.add(User(user_number=num, username=uname, email=f"{uname}@example.com",
                    hashed_password=hash_password(PWD), is_active=True, **fields))
        await db.commit()
    return uname


async def _uid(db, username: str) -> User:
    return (await db.execute(select(User).where(User.username == username))).scalar_one()


async def _login(ac: AsyncClient, username: str) -> dict:
    r = await ac.post("/tokens", data={"username": username, "password": PWD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _seed_contest(owner: str, *, ended: bool = True,
                        is_team_contest: bool = False,
                        real_players: list[str] | None = None) -> tuple[int, int]:
    """一题一赛（含测试点），返回 (contest_id, problem_id)。"""
    async with AsyncSessionLocal() as db:
        ov = await _uid(db, owner)
        problem = Problem(title="虚拟赛题目", description="",
                          is_public=True, review_status=REVIEW_APPROVED)
        db.add(problem)
        await db.flush()
        db.add(CaseRow(problem_id=problem.id, input_data="1", expected_output="1"))

        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=5)
        end = now - timedelta(hours=1) if ended else now + timedelta(hours=1)
        contest = Contest(title="虚拟赛源比赛", start_time=start, end_time=end,
                          owner_id=ov.id, is_team_contest=is_team_contest)
        db.add(contest)
        await db.flush()
        db.add(ContestProblem(contest_id=contest.id, problem_id=problem.id, sort_order=0))
        for name in (real_players or []):
            u = await _uid(db, name)
            db.add(ContestParticipant(contest_id=contest.id, user_id=u.id))
            db.add(Submission(problem_id=problem.id, user_id=u.id,
                              code="int main(){}", language="cpp",
                              contest_id=contest.id, status="accepted",
                              created_at=start + timedelta(minutes=30)))
        await db.commit()
        return contest.id, problem.id


@pytest.fixture
def no_judge(monkeypatch):
    """提交会走背景判题任务：测试里把它换成空实现，别真去连 go-judge。"""
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("app.api.submissions.judge_submission", _noop)
    monkeypatch.setattr("app.api.submissions.judge_submissions", _noop)


@pytest.mark.asyncio
async def test_virtual_start_guardrails():
    owner = await _make_user("owner")
    player = await _make_user("player")
    running_cid, _ = await _seed_contest(owner, ended=False)
    team_cid, _ = await _seed_contest(owner, is_team_contest=True)
    ended_cid, _ = await _seed_contest(owner)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _login(ac, player)

        r = await ac.post(f"/contests/{running_cid}/virtual/start", headers=h)
        assert r.status_code == 400 and "还没结束" in r.json()["detail"], r.text

        r = await ac.post(f"/contests/{team_cid}/virtual/start", headers=h)
        assert r.status_code == 400 and "组队赛" in r.json()["detail"], r.text

        r = await ac.post(f"/contests/{ended_cid}/virtual/start", headers=h)
        assert r.status_code == 200, r.text
        vc = r.json()["virtual"]
        assert vc["active"] is True and vc["remaining_seconds"] > 0
        assert vc["ends_at"] and vc["started_at"]

        # 重复开局：返回同一个（不会叠出第二份计时）
        r2 = await ac.post(f"/contests/{ended_cid}/virtual/start", headers=h)
        assert r2.json()["virtual"]["id"] == vc["id"]

        # me 接口
        r = await ac.get(f"/contests/{ended_cid}/virtual/me", headers=h)
        assert r.status_code == 200 and r.json()["active"] is True
        assert r.json()["virtual"]["id"] == vc["id"]


@pytest.mark.asyncio
async def test_submit_inside_virtual_window_is_tagged_and_excluded_from_rank(no_judge):
    owner = await _make_user("owner")
    player = await _make_user("player")      # 没报名原比赛
    real = await _make_user("real")          # 原比赛的真实参赛者
    cid, pid = await _seed_contest(owner, real_players=[real])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _login(ac, player)
        assert (await ac.post(f"/contests/{cid}/virtual/start", headers=h)).status_code == 200

        # 原比赛已结束 + 没报名，但虚拟赛窗口内 → 允许提交
        r = await ac.post(f"/problems/{pid}/submissions", headers=h,
                          json={"code": "int main(){return 0;}", "language": "cpp",
                                "contest_id": cid})
        assert r.status_code in (200, 201), r.text
        sub_id = r.json().get("id") or r.json().get("submission_id")

        async with AsyncSessionLocal() as db:
            sub = (await db.execute(
                select(Submission).where(Submission.id == sub_id))).scalar_one()
            assert sub.virtual_contest_id is not None, "虚拟赛提交没打上标记"
            # 关键：虚拟提交**不挂 contest_id** —— 原赛榜/等级分结算/查重扫描全都
            # 只认 contest_id，于是「不污染真实成绩」是结构上成立的，不靠各处过滤。
            assert sub.contest_id is None, "虚拟提交不该挂到原比赛上"
            vc_id = sub.virtual_contest_id
            vc = (await db.execute(
                select(VirtualContest).where(VirtualContest.id == vc_id))).scalar_one()
        assert vc.user_id is not None

        # 自己的成绩里能看到这次提交
        r = await ac.get(f"/contests/{cid}/virtual/me", headers=h)
        res = r.json()["results"][0]
        assert res["attempts"] == 1, res

        # 真实排行榜不能出现虚拟提交：真实参赛者只有 1 份提交
        r = await ac.get(f"/contests/{cid}/rank")
        rows = r.json()["rows"]
        assert len(rows) == 1, rows
        assert rows[0]["user"]["username"] == real

        # 提前结束后，再交就被挡（走回真实比赛那套校验）
        r = await ac.post(f"/contests/{cid}/virtual/finish", headers=h)
        assert r.status_code == 200 and r.json()["virtual"]["active"] is False
        r = await ac.post(f"/problems/{pid}/submissions", headers=h,
                          json={"code": "int main(){return 0;}", "language": "cpp",
                                "contest_id": cid})
        assert r.status_code == 400 and "已结束" in r.json()["detail"], r.text

        # 结束后允许再开一次（新 id）
        r = await ac.post(f"/contests/{cid}/virtual/start", headers=h)
        assert r.status_code == 200
        assert r.json()["virtual"]["id"] != vc_id


@pytest.mark.asyncio
async def test_real_submissions_keep_contest_id(no_judge):
    """对照组：真实比赛提交仍然挂 contest_id —— 证明上面的「置空」只针对虚拟赛。"""
    owner = await _make_user("owner")
    real = await _make_user("real")
    # 真实比赛还在进行中（虚拟赛才有「源比赛已结束」这个前提）
    cid, pid = await _seed_contest(owner, real_players=[], ended=False)

    async with AsyncSessionLocal() as db:
        ru = await _uid(db, real)
        db.add(ContestParticipant(contest_id=cid, user_id=ru.id))
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _login(ac, real)
        r = await ac.post(f"/problems/{pid}/submissions", headers=h,
                          json={"code": "int main(){return 0;}", "language": "cpp",
                                "contest_id": cid})
        assert r.status_code in (200, 201), r.text
        sub_id = r.json()["id"]
        async with AsyncSessionLocal() as db:
            sub = (await db.execute(
                select(Submission).where(Submission.id == sub_id))).scalar_one()
        assert sub.contest_id == cid and sub.virtual_contest_id is None


@pytest.mark.asyncio
async def test_second_round_does_not_inherit_previous_results(no_judge):
    """提前结束 → 再开一轮：新一轮的成绩必须从 0 开始（不能继承上一轮）。"""
    owner = await _make_user("owner")
    player = await _make_user("player")
    cid, pid = await _seed_contest(owner)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _login(ac, player)
        assert (await ac.post(f"/contests/{cid}/virtual/start", headers=h)).status_code == 200
        r = await ac.post(f"/problems/{pid}/submissions", headers=h,
                          json={"code": "int main(){return 0;}", "language": "cpp",
                                "contest_id": cid})
        assert r.status_code in (200, 201), r.text

        r = await ac.get(f"/contests/{cid}/virtual/me", headers=h)
        assert r.json()["results"][0]["attempts"] == 1

        assert (await ac.post(f"/contests/{cid}/virtual/finish", headers=h)).status_code == 200

        # 新一轮
        assert (await ac.post(f"/contests/{cid}/virtual/start", headers=h)).status_code == 200
        r = await ac.get(f"/contests/{cid}/virtual/me", headers=h)
        assert r.json()["results"][0]["attempts"] == 0, "新一轮继承了上一轮的成绩"


@pytest.mark.asyncio
async def test_private_contest_cannot_be_virtualized():
    """私有/团队比赛不能开虚拟赛 —— 否则等于绕过报名提交私有赛题。"""
    owner = await _make_user("owner")
    player = await _make_user("player")
    cid, pid = await _seed_contest(owner)

    async with AsyncSessionLocal() as db:
        from app.models.contest import Contest as C
        c = (await db.execute(select(C).where(C.id == cid))).scalar_one()
        c.visibility = "private"
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _login(ac, player)
        r = await ac.post(f"/contests/{cid}/virtual/start", headers=h)
        assert r.status_code == 400 and "公开" in r.json()["detail"], r.text


@pytest.mark.asyncio
async def test_get_me_does_not_write_and_unique_active_index_holds():
    """GET /virtual/me 不该写库；活动行由数据库部分唯一索引兜底。"""
    from datetime import datetime as dt, timedelta as td, timezone as tz
    from sqlalchemy.exc import IntegrityError as IE

    owner = await _make_user("owner")
    player = await _make_user("player")
    cid, _ = await _seed_contest(owner)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _login(ac, player)
        assert (await ac.post(f"/contests/{cid}/virtual/start", headers=h)).status_code == 200

    # 手工把结束时间改到过去，模拟「到点」（只找这个玩家这场比赛的，别串到别的用例）
    async with AsyncSessionLocal() as db:
        pu = await _uid(db, player)
        vc = (await db.execute(
            select(VirtualContest)
            .where(VirtualContest.user_id == pu.id,
                   VirtualContest.source_contest_id == cid)
            .order_by(VirtualContest.id.desc())
        )).scalars().first()
        vc.ends_at = dt.now(tz.utc) - td(minutes=1)
        await db.commit()
        vc_id = vc.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _login(ac, player)
        r = await ac.get(f"/contests/{cid}/virtual/me", headers=h)
        assert r.status_code == 200 and r.json()["active"] is False

    # 只读接口没有回写 finished_at
    async with AsyncSessionLocal() as db:
        vc = (await db.execute(
            select(VirtualContest).where(VirtualContest.id == vc_id))).scalar_one()
        assert vc.finished_at is None, "GET 接口不该写库"

    # 写路径（start）会把到期的旧行收尾，并开出新一轮
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _login(ac, player)
        r = await ac.post(f"/contests/{cid}/virtual/start", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["virtual"]["id"] != vc_id

    async with AsyncSessionLocal() as db:
        old = (await db.execute(
            select(VirtualContest).where(VirtualContest.id == vc_id))).scalar_one()
        assert old.finished_at is not None, "start 应该把到期的旧行收尾"

        # 部分唯一索引：直接插第二条「进行中」必须被数据库挡住
        from app.models.user import User as U
        u = (await db.execute(select(U).where(U.username == player))).scalar_one()
        db.add(VirtualContest(user_id=u.id, source_contest_id=cid,
                              started_at=dt.now(tz.utc),
                              ends_at=dt.now(tz.utc) + td(hours=1)))
        try:
            await db.commit()
            raise AssertionError("同一场比赛不该允许两条进行中的虚拟赛")
        except IE:
            await db.rollback()


@pytest.mark.asyncio
async def test_virtual_ac_does_not_pollute_stats_or_experience():
    """虚拟赛里的 AC 不能抬题目提交/通过数，也不能送经验；之后真 AC 才算首次。"""
    from app.services.judge import XP_BY_DIFFICULTY, apply_submission_stats

    owner = await _make_user("owner")
    player = await _make_user("player")
    cid, pid = await _seed_contest(owner)

    async with AsyncSessionLocal() as db:
        pu = await _uid(db, player)
        problem = (await db.execute(select(Problem).where(Problem.id == pid))).scalar_one()
        problem.difficulty = "普及/提高-"
        vc = VirtualContest(user_id=pu.id, source_contest_id=cid,
                            started_at=datetime.now(timezone.utc),
                            ends_at=datetime.now(timezone.utc) + timedelta(hours=1))
        db.add(vc)
        await db.flush()
        sub = Submission(problem_id=pid, user_id=pu.id, code="int main(){}",
                         language="cpp", status="accepted", virtual_contest_id=vc.id)
        db.add(sub)
        await db.commit()

        before_submit = problem.submit_count or 0
        before_solved = problem.solved_count or 0
        before_xp = pu.experience or 0

        # 虚拟提交：整段跳过
        await apply_submission_stats(db, sub, problem)
        await db.commit()
        await db.refresh(problem)
        await db.refresh(pu)
        assert (problem.submit_count or 0) == before_submit
        assert (problem.solved_count or 0) == before_solved
        assert (pu.experience or 0) == before_xp

        # 之后真实提交一次 AC：才算首次 AC，正常 +1/+1/加经验
        real = Submission(problem_id=pid, user_id=pu.id, code="int main(){}",
                          language="cpp", status="accepted")
        db.add(real)
        await db.commit()
        await apply_submission_stats(db, real, problem)
        await db.commit()
        await db.refresh(problem)
        await db.refresh(pu)
        assert (problem.submit_count or 0) == before_submit + 1
        assert (problem.solved_count or 0) == before_solved + 1
        assert (pu.experience or 0) == before_xp + XP_BY_DIFFICULTY.get(problem.difficulty, 0)


@pytest.mark.asyncio
async def test_virtual_submit_works_when_problem_is_also_in_running_contest(no_judge):
    """同一个题既在「虚拟赛源比赛（已结束）」里、又在另一场进行中的比赛里时，
    虚拟赛提交也要能过 —— 这正是不该就地改写 `contest_id` 的原因：
    改写了就会掉进「比赛题守卫」被误判成题库提交而拒绝。"""
    owner = await _make_user("owner")
    player = await _make_user("player")
    cid, pid = await _seed_contest(owner)      # 已结束，作为虚拟赛源

    # 同一道题再挂到一场进行中的比赛
    async with AsyncSessionLocal() as db:
        ov = await _uid(db, owner)
        now = datetime.now(timezone.utc)
        running = Contest(title="进行中的比赛", start_time=now - timedelta(hours=1),
                          end_time=now + timedelta(hours=1), owner_id=ov.id)
        db.add(running)
        await db.flush()
        db.add(ContestProblem(contest_id=running.id, problem_id=pid, sort_order=0))
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _login(ac, player)
        assert (await ac.post(f"/contests/{cid}/virtual/start", headers=h)).status_code == 200
        r = await ac.post(f"/problems/{pid}/submissions", headers=h,
                          json={"code": "int main(){return 0;}", "language": "cpp",
                                "contest_id": cid})
        assert r.status_code in (200, 201), r.text
        async with AsyncSessionLocal() as db:
            sub = (await db.execute(
                select(Submission).where(Submission.id == r.json()["id"]))).scalar_one()
        assert sub.virtual_contest_id is not None and sub.contest_id is None
