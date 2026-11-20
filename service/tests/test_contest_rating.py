"""比赛等级分（rating）的回归测试。

两层：
1. 纯算法：K 系数衰减、爆冷加分比「应该赢」多、同分中间名次不动；
2. 结算接口：名次复用 /rank、只结算提交过的人、幂等、各种拒绝条件、权限。
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
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.user import User
from app.services.contest_rating import START_RATING, k_factor, rating_deltas

PWD = "supersecret1"


# ---------------- 纯算法 ----------------

def test_k_factor_decays_with_experience():
    assert k_factor(0) == 40 and k_factor(4) == 40
    assert k_factor(5) == 30 and k_factor(9) == 30
    assert k_factor(10) == 20 and k_factor(100) == 20


def test_upset_gains_more_than_a_favourite_winning():
    fav_wins = rating_deltas([2000, 1500], [1, 2], [10, 10])
    upset = rating_deltas([2000, 1500], [2, 1], [10, 10])
    assert fav_wins[0] > 0 and fav_wins[1] < 0
    assert upset[1] > fav_wins[0], "低分者爆冷赢，加分必须比高分者赢更多"
    assert upset[0] < fav_wins[1]


def test_equal_ratings_middle_player_is_neutral():
    deltas = rating_deltas([1500, 1500, 1500], [1, 2, 3], [0, 0, 0])
    assert deltas[0] > 0 and deltas[2] < 0
    assert deltas[1] == 0, deltas


# ---------------- 结算接口 ----------------

async def _make_user(tag: str, **fields) -> str:
    uname = f"cr_{tag}_{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        used = set((await db.execute(select(User.user_number))).scalars())
        num = 884000
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


async def _uid(db, username: str) -> User:
    return (await db.execute(select(User).where(User.username == username))).scalar_one()


async def _seed_contest(reviewer: str, players: list[str], *,
                        is_rated: bool = True, ended: bool = True,
                        is_team_contest: bool = False) -> int:
    """造一题一赛 + 每人一份提交（第一个人 AC、其余 WA），返回 contest_id。"""
    async with AsyncSessionLocal() as db:
        rv = await _uid(db, reviewer)
        problem = Problem(title="rating 测试题", description="")
        db.add(problem)
        await db.flush()
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=2)
        end = now - timedelta(days=1) if ended else now + timedelta(hours=1)
        contest = Contest(title="rating 测试赛", start_time=start, end_time=end,
                          owner_id=rv.id, is_rated=is_rated,
                          is_team_contest=is_team_contest)
        db.add(contest)
        await db.flush()
        db.add(ContestProblem(contest_id=contest.id, problem_id=problem.id, sort_order=0))
        for i, name in enumerate(players):
            u = await _uid(db, name)
            db.add(ContestParticipant(contest_id=contest.id, user_id=u.id))
            db.add(Submission(problem_id=problem.id, user_id=u.id, code="int main(){}",
                              language="cpp", contest_id=contest.id,
                              status="accepted" if i == 0 else "wrong_answer",
                              created_at=start + timedelta(minutes=10 + i)))
        await db.commit()
        return contest.id


@pytest.mark.asyncio
async def test_settle_end_to_end_and_idempotent():
    reviewer = await _make_user("reviewer", can_manage_problems=True)
    a = await _make_user("a")
    b = await _make_user("b")
    no_show = await _make_user("noshow")   # 报名但一次没交
    plain = await _make_user("plain")
    cid = await _seed_contest(reviewer, [a, b])

    # 追加一个只报名、没提交的参与者（不该被结算）
    async with AsyncSessionLocal() as db:
        ns = await _uid(db, no_show)
        db.add(ContestParticipant(contest_id=cid, user_id=ns.id))
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _login(ac, reviewer)

        # 权限：普通用户不能结算
        hp = await _login(ac, plain)
        assert (await ac.post(f"/contests/{cid}/rating/settle", headers=hp)).status_code == 403

        r = await ac.post(f"/contests/{cid}/rating/settle", headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["settled"] == 2, body        # no_show 不参与
        assert body["already_settled"] is False

        items = body["items"]
        assert [i["rank"] for i in items] == [1, 2]
        assert items[0]["username"] == a and items[0]["delta"] > 0
        assert items[1]["username"] == b and items[1]["delta"] < 0
        assert items[0]["rating_before"] == START_RATING
        assert items[0]["rating_after"] == START_RATING + items[0]["delta"]

        # 榜单接口
        r = await ac.get(f"/contests/{cid}/rating")
        assert r.status_code == 200, r.text
        pub = r.json()
        assert pub["is_rated"] is True and pub["settled"] is True
        assert len(pub["items"]) == 2

        # 幂等：再结算一次，数字不变
        r = await ac.post(f"/contests/{cid}/rating/settle", headers=h)
        assert r.status_code == 200 and r.json()["already_settled"] is True
        assert r.json()["items"] == items

        # users 上的当前分/最高分/场次都更新了，没提交的人没被扣分
        async with AsyncSessionLocal() as db:
            ua = await _uid(db, a)
            ub = await _uid(db, b)
            un = await _uid(db, no_show)
            assert ua.rating == items[0]["rating_after"] and ua.rated_contests == 1
            assert ua.max_rating >= ua.rating
            assert ub.rating == items[1]["rating_after"]
            assert un.rating == START_RATING and un.rated_contests == 0

        # 结算名次与 /rank 的名次顺序一致
        r = await ac.get(f"/contests/{cid}/rank")
        assert r.status_code == 200, r.text
        rank_order = [row["user"]["username"] for row in r.json()["rows"]]
        assert rank_order[:2] == [a, b]


@pytest.mark.asyncio
async def test_settle_rejects_unrated_team_and_running_contests():
    reviewer = await _make_user("reviewer", can_manage_problems=True)
    a = await _make_user("a")
    b = await _make_user("b")

    unrated = await _seed_contest(reviewer, [a, b], is_rated=False)
    team = await _seed_contest(reviewer, [a, b], is_team_contest=True)
    running = await _seed_contest(reviewer, [a, b], ended=False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _login(ac, reviewer)
        for cid, keyword in ((unrated, "等级分"), (team, "组队赛"), (running, "还没结束")):
            r = await ac.post(f"/contests/{cid}/rating/settle", headers=h)
            assert r.status_code == 400, r.text
            assert keyword in r.json()["detail"], r.text


@pytest.mark.asyncio
async def test_settle_rejected_while_submissions_still_judging():
    """还有提交在 pending/judging 时不许结算：结算幂等，写进去就改不回来了。"""
    reviewer = await _make_user("reviewer", can_manage_problems=True)
    a = await _make_user("a")
    b = await _make_user("b")
    cid = await _seed_contest(reviewer, [a, b])
    async with AsyncSessionLocal() as db:
        ua = await _uid(db, a)
        p = (await db.execute(select(ContestProblem).where(
            ContestProblem.contest_id == cid))).scalars().first()
        db.add(Submission(problem_id=p.problem_id, user_id=ua.id,
                          code="int main(){}", language="cpp", contest_id=cid,
                          status="judging"))
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _login(ac, reviewer)
        r = await ac.post(f"/contests/{cid}/rating/settle", headers=h)
        assert r.status_code == 400 and "评测中" in r.json()["detail"], r.text


@pytest.mark.asyncio
async def test_contest_owner_can_settle_without_problem_permission():
    """比赛举办者（没有任何管理身份）也能结算自己这场比赛 —— 前端按钮给的
    就是 can_edit（owner 或管理员），后端必须同口径，不能按钮能点、接口 403。"""
    owner = await _make_user("owner")          # 普通用户，只有举办者身份
    a = await _make_user("a")
    b = await _make_user("b")
    cid = await _seed_contest(owner, [a, b])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _login(ac, owner)
        r = await ac.post(f"/contests/{cid}/rating/settle", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["settled"] == 2


@pytest.mark.asyncio
async def test_rating_shows_up_in_leaderboard_and_profile():
    """结算之后：等级分榜能看到、个人主页也能看到（否则这个分数等于没落地）。"""
    reviewer = await _make_user("reviewer", can_manage_problems=True)
    a = await _make_user("a")
    b = await _make_user("b")
    cid = await _seed_contest(reviewer, [a, b])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _login(ac, reviewer)
        r = await ac.post(f"/contests/{cid}/rating/settle", headers=h)
        assert r.status_code == 200, r.text
        winner = r.json()["items"][0]

        # 等级分榜：第一名就是刚才那场的冠军
        r = await ac.get("/ranking/rating")
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        # 别的用例也可能结算过比赛（分更高），所以只在榜里找到这个人，别断言他第一
        row = next((x for x in items if x["username"] == a), None)
        assert row is not None, items
        assert row["rating"] == winner["rating_after"]
        assert row["rated_contests"] == 1
        assert row["rank"] >= 1

        # 个人主页：带等级分，且不泄露密码
        async with AsyncSessionLocal() as db:
            ua = await _uid(db, a)
            una = ua.user_number
        r = await ac.get(f"/users/number/{una}")
        assert r.status_code == 200, r.text
        prof = r.json()
        assert prof["rating"] == winner["rating_after"], prof
        assert prof["max_rating"] >= prof["rating"]
        assert prof["rated_contests"] == 1
        assert "hashed_password" not in prof


@pytest.mark.asyncio
async def test_private_contest_rating_board_requires_membership():
    """私密比赛的等级分明细不对路人公开（评审改进项）。"""
    reviewer = await _make_user("pv_reviewer", can_manage_problems=True)
    a = await _make_user("pv_a")
    b = await _make_user("pv_b")
    outsider = await _make_user("pv_out")
    cid = await _seed_contest(reviewer, [a, b])

    async with AsyncSessionLocal() as db:
        contest = (await db.execute(select(Contest).where(Contest.id == cid))).scalar_one()
        contest.visibility = "private"
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        hm = await _login(ac, reviewer)
        assert (await ac.post(f"/contests/{cid}/rating/settle", headers=hm)).status_code == 200

        # 路人 403
        ho = await _login(ac, outsider)
        assert (await ac.get(f"/contests/{cid}/rating", headers=ho)).status_code == 403
        # 未登录也 403
        assert (await ac.get(f"/contests/{cid}/rating")).status_code == 403
        # 参赛者 / 举办者能看
        ha = await _login(ac, a)
        r = await ac.get(f"/contests/{cid}/rating", headers=ha)
        assert r.status_code == 200 and r.json()["items"], r.text
        assert (await ac.get(f"/contests/{cid}/rating", headers=hm)).status_code == 200


@pytest.mark.asyncio
async def test_rank_tiebreak_is_deterministic_for_identical_rows():
    """完全并列时名次按 user_id 固定 —— 否则等级分结算不可复现（评审阻断项）。"""
    from app.services.contest_rank import build_rank_rows

    reviewer = await _make_user("tb_reviewer", can_manage_problems=True)
    a = await _make_user("tb_a")
    b = await _make_user("tb_b")

    async with AsyncSessionLocal() as db:
        rv = await _uid(db, reviewer)
        problem = Problem(title="并列题", description="")
        db.add(problem)
        await db.flush()
        now = datetime.now(timezone.utc)
        contest = Contest(title="并列赛", start_time=now - timedelta(days=2),
                          end_time=now - timedelta(days=1), owner_id=rv.id)
        db.add(contest)
        await db.flush()
        db.add(ContestProblem(contest_id=contest.id, problem_id=problem.id, sort_order=0))
        ua, ub = await _uid(db, a), await _uid(db, b)
        same = now - timedelta(days=2) + timedelta(minutes=30)
        for u in (ua, ub):
            db.add(ContestParticipant(contest_id=contest.id, user_id=u.id))
            db.add(Submission(problem_id=problem.id, user_id=u.id, code="int main(){}",
                              language="cpp", contest_id=contest.id,
                              status="accepted", created_at=same))
        await db.commit()
        cid = contest.id

    async with AsyncSessionLocal() as db:
        contest = (await db.execute(select(Contest).where(Contest.id == cid))).scalar_one()
        first = (await build_rank_rows(db, contest))["rows"]
        second = (await build_rank_rows(db, contest))["rows"]

    assert [r["user"]["username"] for r in first] == [r["user"]["username"] for r in second]
    # 同分同罚同时间 → 按 user_id 升序（a 先注册，编号更小）
    assert [r["user"]["user_id"] for r in first] == sorted(
        r["user"]["user_id"] for r in first), first


@pytest.mark.asyncio
async def test_leaderboard_paginates_in_sql_and_reports_my_rank():
    """等级分榜分页 + 我的排名（评审改进项：不能把全站用户拉进内存）。"""
    reviewer = await _make_user("lb_reviewer", can_manage_problems=True)
    a = await _make_user("lb_a")
    b = await _make_user("lb_b")
    cid = await _seed_contest(reviewer, [a, b])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        hm = await _login(ac, reviewer)
        assert (await ac.post(f"/contests/{cid}/rating/settle", headers=hm)).status_code == 200

        r = await ac.get("/ranking/rating?page=1&page_size=1")
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["items"]) == 1
        assert body["total"] >= 2
        assert body["total_pages"] >= 1
        assert body["items"][0]["rank"] == 1
        assert body["items"][0]["rated_contests"] >= 1

        # 第一页第一名 ≥ 第二页第一名（分降序）
        r2 = await ac.get("/ranking/rating?page=2&page_size=1")
        assert r2.json()["items"][0]["rating"] <= body["items"][0]["rating"]

        # 我的排名：打过 rated 赛的人能拿到
        ha = await _login(ac, a)
        r3 = await ac.get("/ranking/rating?page_size=50", headers=ha)
        mine = r3.json()["my_rank"]
        assert mine and mine["username"] == a and mine["rank"] >= 1
        # 没打过的人 my_rank 为空
        plain = await _make_user("lb_plain")
        hp = await _login(ac, plain)
        assert (await ac.get("/ranking/rating", headers=hp)).json()["my_rank"] is None
