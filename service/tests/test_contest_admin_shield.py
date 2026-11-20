"""测试比赛管理员防偷窥/参赛保护功能（hide_submissions_from_admin）。

功能要点：
1. 比赛开启 hide_submissions_from_admin 后：
   - 平台管理员（非举办方）不能在提交列表中看到其他选手的提交记录
   - 平台管理员（非举办方）不能查看其他选手的提交详情与源码（403）
   - 平台管理员（非举办方）在赛中不能重测或取消他人成绩（403）
   - OI 赛制进行中，平台管理员（非举办方）的评测结果和排行榜被隐藏（与普通选手一致）
2. 举办个人（比赛创建者）：
   - 可看全场所有选手的提交记录与源码
   - 可看 OI 赛制赛中的实时评测结果与榜单
3. 举办团队的所有人（包含团主与全部团队成员）：
   - 均能看到比赛题目的全部提交记录与源码
   - 均能管理比赛提交与查看实时结果
"""

import random
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


async def _register_and_login(
    ac: AsyncClient,
    *,
    is_admin: bool = False,
    is_super_admin: bool = False,
    can_manage_problems: bool = False,
) -> tuple[dict[str, str], int]:
    suffix = uuid.uuid4().hex[:8]
    username = f"usr_{suffix}"
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
    uid = me["id"]

    if is_admin or is_super_admin or can_manage_problems:
        from app.core.database import AsyncSessionLocal
        from app.models.user import User

        async with AsyncSessionLocal() as db:
            user = await db.get(User, uid)
            if is_admin:
                user.is_admin = True
            if is_super_admin:
                user.is_super_admin = True
            if can_manage_problems:
                user.can_manage_problems = True
            await db.commit()

    return headers, uid


async def _seed_contest(
    owner_id: int,
    *,
    rule_type: str = "xcpc",
    hide_submissions_from_admin: bool = True,
    team_id: int | None = None,
    participants: list[int] | None = None,
) -> tuple[int, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.contest import Contest, ContestParticipant, ContestProblem
    from app.models.problem import Problem
    from app.models.submission import TestCase

    now = datetime.now(timezone.utc)
    start, end = now - timedelta(hours=1), now + timedelta(hours=3)

    async with AsyncSessionLocal() as db:
        prob = Problem(title="A+B Problem", difficulty="入门", description="求两数之和", is_public=True)
        db.add(prob)
        await db.flush()
        db.add(TestCase(problem_id=prob.id, input_data="1 2\n", expected_output="3\n", sort_order=0))

        contest = Contest(
            title="测试保护赛",
            visibility="team_public" if team_id else "public",
            rule_type=rule_type,
            hide_submissions_from_admin=hide_submissions_from_admin,
            team_id=team_id,
            start_time=start,
            end_time=end,
            owner_id=owner_id,
        )
        db.add(contest)
        await db.flush()
        db.add(ContestProblem(contest_id=contest.id, problem_id=prob.id, sort_order=0))

        for uid in (participants or []):
            db.add(ContestParticipant(contest_id=contest.id, user_id=uid))

        await db.commit()
        return prob.id, contest.id


async def _add_sub(user_id: int, problem_id: int, contest_id: int, *, score: int = 100, status: str = "accepted") -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.submission import Submission

    async with AsyncSessionLocal() as db:
        sub = Submission(
            problem_id=problem_id,
            user_id=user_id,
            code="#include <iostream>\nint main() { return 0; }",
            language="cpp",
            status=status,
            score=score,
            contest_id=contest_id,
        )
        db.add(sub)
        await db.commit()
        await db.refresh(sub)
        return sub.id


@pytest.mark.asyncio
async def test_admin_cannot_see_others_submissions_when_shield_enabled():
    """开启管理员参赛保护时，非举办方管理员无法看他人提交列表、详情与代码，无法篡改成绩。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        host_h, host_id = await _register_and_login(ac)
        admin_h, admin_id = await _register_and_login(ac, is_admin=True, can_manage_problems=True)
        player_h, player_id = await _register_and_login(ac)

        pid, cid = await _seed_contest(
            host_id,
            hide_submissions_from_admin=True,
            participants=[admin_id, player_id],
        )

        p_sub = await _add_sub(player_id, pid, cid)
        a_sub = await _add_sub(admin_id, pid, cid)

        # 1. 管理员请求题目提交列表：只能看到自己的提交记录，看不到普通选手 p_sub
        r = await ac.get(f"/problems/{pid}/submissions", headers=admin_h)
        assert r.status_code == 200, r.text
        data = r.json()
        ids = [item["id"] for item in data["items"]]
        assert a_sub in ids
        assert p_sub not in ids
        assert data["total"] == 1

        # 2. 管理员直接访问其他选手的提交详情接口：403 禁止
        r_detail = await ac.get(f"/submissions/{p_sub}", headers=admin_h)
        assert r_detail.status_code == 403
        assert "比赛进行中" in r_detail.json()["detail"]

        # 3. 管理员访问自己的提交详情：正常可见且代码可见
        r_own = await ac.get(f"/submissions/{a_sub}", headers=admin_h)
        assert r_own.status_code == 200
        assert r_own.json()["code_visible"] is True

        # 4. 管理员尝试在赛中重测/修改提交成绩：403 禁止
        r_rejudge = await ac.post(f"/submissions/{p_sub}/rejudge", headers=admin_h)
        assert r_rejudge.status_code == 403
        r_cancel = await ac.post(f"/submissions/{p_sub}/cancel-score", headers=admin_h)
        assert r_cancel.status_code == 403

        # 5. 举办个人（创建者本人）查看列表：全场所有选手的提交全可见
        r_host = await ac.get(f"/problems/{pid}/submissions", headers=host_h)
        assert r_host.status_code == 200
        host_ids = [item["id"] for item in r_host.json()["items"]]
        assert p_sub in host_ids
        assert a_sub in host_ids
        assert r_host.json()["total"] == 2

        # 6. 举办个人查看他人提交详情与代码：正常完全可见
        r_host_detail = await ac.get(f"/submissions/{p_sub}", headers=host_h)
        assert r_host_detail.status_code == 200
        assert r_host_detail.json()["code_visible"] is True
        assert "include <iostream>" in r_host_detail.json()["code"]


@pytest.mark.asyncio
async def test_hosting_team_all_members_can_see_all_submissions():
    """举办团队的所有人（包含团主与普通团队成员）均能查看比赛题目全部提交。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        owner_h, owner_id = await _register_and_login(ac)
        member_h, member_id = await _register_and_login(ac)
        contestant_h, contestant_id = await _register_and_login(ac)

        # 创建团队并将 member_id 加入为普通成员（role='member'）
        from app.core.database import AsyncSessionLocal
        from app.models.team import Team, TeamMember

        async with AsyncSessionLocal() as db:
            team = Team(name="出题组团队", owner_id=owner_id)
            db.add(team)
            await db.flush()
            db.add(TeamMember(team_id=team.id, user_id=member_id, role="member"))
            await db.commit()
            tid = team.id

        pid, cid = await _seed_contest(
            owner_id,
            hide_submissions_from_admin=True,
            team_id=tid,
            participants=[contestant_id],
        )

        sub_id = await _add_sub(contestant_id, pid, cid)

        # 1. 团队团主可以查看提交列表与代码
        r_owner = await ac.get(f"/problems/{pid}/submissions", headers=owner_h)
        assert r_owner.status_code == 200
        assert sub_id in [i["id"] for i in r_owner.json()["items"]]

        r_owner_detail = await ac.get(f"/submissions/{sub_id}", headers=owner_h)
        assert r_owner_detail.status_code == 200
        assert r_owner_detail.json()["code_visible"] is True

        # 2. 团队普通成员（所有人）同样可以查看提交列表与代码
        r_member = await ac.get(f"/problems/{pid}/submissions", headers=member_h)
        assert r_member.status_code == 200
        assert sub_id in [i["id"] for i in r_member.json()["items"]]

        r_member_detail = await ac.get(f"/submissions/{sub_id}", headers=member_h)
        assert r_member_detail.status_code == 200
        assert r_member_detail.json()["code_visible"] is True


@pytest.mark.asyncio
async def test_oi_results_hidden_from_admin_when_shield_enabled():
    """OI 赛制开启保护时，管理员参赛同样被隐藏评测结果与封榜，举办方可见。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        host_h, host_id = await _register_and_login(ac)
        admin_h, admin_id = await _register_and_login(ac, is_super_admin=True)

        pid, cid = await _seed_contest(
            host_id,
            rule_type="oi",
            hide_submissions_from_admin=True,
            participants=[admin_id],
        )

        admin_sub = await _add_sub(admin_id, pid, cid, score=80, status="accepted")

        # 1. 管理员查自己的提交：OI 赛中结果被遮蔽
        r = await ac.get(f"/submissions/{admin_sub}", headers=admin_h)
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "submitted"
        assert d["score"] == 0
        assert d["result_hidden"] is True

        # 2. 管理员查排行榜：显示封榜提示
        r_rank = await ac.get(f"/contests/{cid}/rank", headers=admin_h)
        assert r_rank.status_code == 200
        assert r_rank.json()["is_frozen"] is True

        # 3. 举办个人查看该提交：真实结果可见
        r_host_sub = await ac.get(f"/submissions/{admin_sub}", headers=host_h)
        assert r_host_sub.status_code == 200
        d_host = r_host_sub.json()
        assert d_host["score"] == 80
        assert d_host["status"] == "accepted"
        assert d_host["result_hidden"] is False

        # 4. 举办个人查排行榜：未被封榜，实时可见
        r_host_rank = await ac.get(f"/contests/{cid}/rank", headers=host_h)
        assert r_host_rank.status_code == 200
        assert not r_host_rank.json().get("is_frozen")


@pytest.mark.asyncio
async def test_create_and_update_contest_shield_option():
    """测试通过比赛 API 创建与修改管理员保护开关。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        admin_h, admin_id = await _register_and_login(ac, is_admin=True, can_manage_problems=True)

        from app.core.database import AsyncSessionLocal
        from app.models.problem import Problem, REVIEW_APPROVED

        async with AsyncSessionLocal() as db:
            p = Problem(title="保护测试题", difficulty="入门", description="描述", is_public=True, review_status=REVIEW_APPROVED)
            db.add(p)
            await db.commit()
            p_code = f"P{1000 + p.id}"

        now = datetime.now(timezone.utc)
        st = (now + timedelta(days=1)).isoformat()
        en = (now + timedelta(days=2)).isoformat()

        # 1. 创建比赛默认开启 hide_submissions_from_admin
        r = await ac.post(
            "/contests",
            headers=admin_h,
            json={
                "title": "默认开启保护的比赛",
                "start_time": st,
                "end_time": en,
                "problem_codes": [p_code],
            },
        )
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        assert r.json()["hide_submissions_from_admin"] is True

        # 2. 详情读取
        detail = (await ac.get(f"/contests/{cid}", headers=admin_h)).json()
        assert detail["hide_submissions_from_admin"] is True

        # 3. 更新为关闭
        r_up = await ac.put(
            f"/contests/{cid}",
            headers=admin_h,
            json={"hide_submissions_from_admin": False},
        )
        assert r_up.status_code == 200
        assert r_up.json()["hide_submissions_from_admin"] is False

        detail2 = (await ac.get(f"/contests/{cid}", headers=admin_h)).json()
        assert detail2["hide_submissions_from_admin"] is False


@pytest.mark.asyncio
async def test_admin_cannot_leak_team_problems_and_testcases():
    """测试管理员无法借由团队页面、测试点管理接口或普通提交通道窥探/泄露比赛题目。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        owner_h, owner_id = await _register_and_login(ac)
        admin_h, admin_id = await _register_and_login(ac, is_super_admin=True, can_manage_problems=True)

        from app.core.database import AsyncSessionLocal
        from app.models.team import Team
        from app.models.problem import Problem
        from app.models.submission import TestCase
        from app.models.contest import Contest, ContestProblem

        now = datetime.now(timezone.utc)
        # 建立团队
        async with AsyncSessionLocal() as db:
            team = Team(name="筹办团队", owner_id=owner_id)
            db.add(team)
            await db.flush()

            # 团队私有赛题
            prob = Problem(
                title="团队秘密赛题",
                difficulty="提高",
                description="机密比赛题面",
                team_id=team.id,
                t_no=random.randint(100000, 999999),
                is_public=False,
                author_id=owner_id,
            )
            db.add(prob)
            await db.flush()
            db.add(TestCase(problem_id=prob.id, input_data="secret_in", expected_output="secret_out", sort_order=0))

            # 建立未开始的比赛（1小时后开始），开启管理员参赛保护
            contest = Contest(
                title="受保护的团队赛",
                visibility="team",
                rule_type="oi",
                hide_submissions_from_admin=True,
                team_id=team.id,
                start_time=now + timedelta(hours=1),
                end_time=now + timedelta(hours=3),
                owner_id=owner_id,
            )
            db.add(contest)
            await db.flush()
            db.add(ContestProblem(contest_id=contest.id, problem_id=prob.id, sort_order=0))
            await db.commit()
            tid = team.id
            pid = prob.id
            cid = contest.id

        # 1. 非团队成员的管理员点进团队题目列表：看不到该未开赛/私有赛题
        r_admin_team_probs = await ac.get(f"/teams/{tid}/problems", headers=admin_h)
        assert r_admin_team_probs.status_code == 200
        prob_ids = [p["id"] for p in r_admin_team_probs.json()]
        assert pid not in prob_ids

        # 2. 团队团主（举办方）点进团队题目列表：正常可见
        r_owner_team_probs = await ac.get(f"/teams/{tid}/problems", headers=owner_h)
        assert r_owner_team_probs.status_code == 200
        owner_prob_ids = [p["id"] for p in r_owner_team_probs.json()]
        assert pid in owner_prob_ids

        # 3. 管理员赛前尝试按题号直接访问题目详情：403 / 404 拦截（防探测）
        r_prob = await ac.get(f"/problems/{pid}", headers=admin_h)
        assert r_prob.status_code in (403, 404)

        # 4. 管理员尝试调用测试点管理接口偷看测试数据：403 拦截
        r_tc = await ac.get(f"/problems/{pid}/test-cases", headers=admin_h)
        assert r_tc.status_code == 403
        assert "测试点" in r_tc.json()["detail"]

        # 5. 管理员尝试修改该赛题：403 拦截
        r_update = await ac.put(f"/problems/{pid}", headers=admin_h, json={"title": "篡改标题"})
        assert r_update.status_code == 403
        assert "不可修改题目" in r_update.json()["detail"]

        # 6. 管理员尝试绕过比赛直接向题库提交代码测试：400 拦截
        r_sub = await ac.post(f"/problems/{pid}/submissions", headers=admin_h, json={
            "code": "print(1)",
            "language": "python3",
        })
        assert r_sub.status_code == 400
        assert "比赛开始后才能提交" in r_sub.json()["detail"]

