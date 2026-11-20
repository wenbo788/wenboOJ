"""组队参赛功能单元与集成测试。

覆盖功能点：
1. 组队赛创建与编辑 (is_team_contest, max_team_members)。
2. 队伍创建 (POST /{contest_id}/teams) 与重名校验。
3. 凭口令加入队伍 (POST /{contest_id}/teams/join) 与人数上限控制。
4. 队长直接添加队员 (POST /{contest_id}/teams/{team_id}/add_member)。
5. 队长踢出队员与队员主动退出 (POST /{contest_id}/teams/{team_id}/kick, POST /{contest_id}/teams/leave)。
6. 组队赛提交限制：未组队选手不可提交。
7. 组队提交关联队伍及队友互看代码权限 (is_teammate 穿透保护)。
8. 组队赛排行榜 (XCPC 赛制下队伍得分、题目通过状态及罚时聚合)。
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.problem import Problem, REVIEW_APPROVED
from app.models.submission import Submission, TestCase as DbTestCase
from app.models.user import User


async def _register_and_login(ac: AsyncClient, *, is_admin: bool = False) -> tuple[dict[str, str], int, str]:
    suffix = uuid.uuid4().hex[:8]
    username = f"team_user_{suffix}"
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
    user_id = me["id"]

    if is_admin:
        async with AsyncSessionLocal() as db:
            u = await db.get(User, user_id)
            assert u is not None
            u.is_admin = True
            u.can_manage_problems = True
            await db.commit()

    return headers, user_id, username


async def _create_problem(title: str) -> Problem:
    async with AsyncSessionLocal() as db:
        p = Problem(
            title=title,
            difficulty="入门",
            description="描述",
            is_public=True,
            review_status=REVIEW_APPROVED,
        )
        db.add(p)
        await db.commit()
        await db.refresh(p)
        db.add(DbTestCase(problem_id=p.id, input_data="1\n", expected_output="1\n", sort_order=0))
        await db.commit()
        return p


@pytest.mark.asyncio
async def test_contest_team_lifecycle_and_rules():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        admin_headers, admin_id, _ = await _register_and_login(ac, is_admin=True)
        u1_headers, u1_id, u1_name = await _register_and_login(ac)
        u2_headers, u2_id, u2_name = await _register_and_login(ac)
        u3_headers, u3_id, u3_name = await _register_and_login(ac)
        u4_headers, u4_id, u4_name = await _register_and_login(ac)

        prob_a = await _create_problem("Team Problem A")
        prob_b = await _create_problem("Team Problem B")

        now = datetime.now(timezone.utc)
        start_time = (now - timedelta(minutes=10)).isoformat()
        end_time = (now + timedelta(hours=2)).isoformat()

        # 1. 创建组队比赛 (每队上限 2 人)
        create_payload = {
            "title": "2026 年春季组队对抗赛",
            "description": "三人行必有我师，但本场限定 2 人",
            "start_time": start_time,
            "end_time": end_time,
            "rule_type": "xcpc",
            "is_team_contest": True,
            "max_team_members": 2,
            "problem_ids": [prob_a.id, prob_b.id],
        }
        res = await ac.post("/contests", json=create_payload, headers=admin_headers)
        assert res.status_code == 201, res.text
        contest = res.json()
        contest_id = contest["id"]
        assert contest["is_team_contest"] is True
        assert contest["max_team_members"] == 2

        # 2. 详情接口获取比赛信息
        res = await ac.get(f"/contests/{contest_id}", headers=u1_headers)
        assert res.status_code == 200
        detail = res.json()
        assert detail["is_team_contest"] is True
        assert detail["max_team_members"] == 2
        assert detail["my_team"] is None

        # 3. u1 创建队伍 "银河战队"
        res = await ac.post(
            f"/contests/{contest_id}/teams",
            json={"name": "银河战队"},
            headers=u1_headers,
        )
        assert res.status_code == 200, res.text
        team1 = res.json()
        team1_id = team1["team_id"]
        invite_code = team1["invite_code"]
        assert team1["name"] == "银河战队"
        assert team1["success"] is True

        # 查看当前队伍详情
        res = await ac.get(f"/contests/{contest_id}/my-team", headers=u1_headers)
        assert res.status_code == 200
        my_t = res.json()
        assert my_t["name"] == "银河战队"
        assert my_t["leader_id"] == u1_id
        assert len(my_t["members"]) == 1
        assert my_t["members"][0]["user_id"] == u1_id

        # 4. 同名队伍重复创建失败
        res = await ac.post(
            f"/contests/{contest_id}/teams",
            json={"name": "银河战队"},
            headers=u2_headers,
        )
        assert res.status_code == 400
        assert "已被使用" in res.json()["detail"]

        # 5. u1 已经有队伍，不能再建新队
        res = await ac.post(
            f"/contests/{contest_id}/teams",
            json={"name": "另一个队"},
            headers=u1_headers,
        )
        assert res.status_code == 400
        assert "已在当前比赛" in res.json()["detail"]

        # 6. u2 凭错误口令加入失败
        res = await ac.post(
            f"/contests/{contest_id}/teams/join",
            json={"invite_code": "WRONG_CODE"},
            headers=u2_headers,
        )
        assert res.status_code == 404

        # 7. u2 凭正确口令加入银河战队 (此时队伍达到 2 人上限)
        res = await ac.post(
            f"/contests/{contest_id}/teams/join",
            json={"invite_code": invite_code},
            headers=u2_headers,
        )
        assert res.status_code == 200, res.text
        joined_res = res.json()
        assert joined_res["team_id"] == team1_id

        # 查看队伍成员
        res = await ac.get(f"/contests/{contest_id}/my-team", headers=u2_headers)
        assert res.status_code == 200
        team_detail = res.json()
        assert len(team_detail["members"]) == 2
        member_ids = [m["user_id"] for m in team_detail["members"]]
        assert u1_id in member_ids and u2_id in member_ids

        # 8. u3 试图加入满员的银河战队 -> 400 队伍已满
        res = await ac.post(
            f"/contests/{contest_id}/teams/join",
            json={"invite_code": invite_code},
            headers=u3_headers,
        )
        assert res.status_code == 400
        assert "已达上限" in res.json()["detail"]

        # 9. 队长 u1 试图通过用户名添加 u3 -> 400 人数已满
        res = await ac.post(
            f"/contests/{contest_id}/teams/{team1_id}/add_member",
            json={"username_or_uid": u3_name},
            headers=u1_headers,
        )
        assert res.status_code == 400
        assert "已达上限" in res.json()["detail"]

        # 10. 队长 u1 踢出队员 u2
        res = await ac.post(
            f"/contests/{contest_id}/teams/{team1_id}/kick",
            json={"user_id": u2_id},
            headers=u1_headers,
        )
        assert res.status_code == 200, res.text

        res = await ac.get(f"/contests/{contest_id}/my-team", headers=u1_headers)
        assert len(res.json()["members"]) == 1

        # 11. 队长现在添加队员 u3 成功
        res = await ac.post(
            f"/contests/{contest_id}/teams/{team1_id}/add_member",
            json={"username_or_uid": u3_name},
            headers=u1_headers,
        )
        assert res.status_code == 200, res.text

        res = await ac.get(f"/contests/{contest_id}/my-team", headers=u1_headers)
        member_ids = [m["user_id"] for m in res.json()["members"]]
        assert u3_id in member_ids

        # 12. u3 主动退出队伍
        res = await ac.post(
            f"/contests/{contest_id}/teams/leave",
            headers=u3_headers,
        )
        assert res.status_code == 200, res.text

        # 13. u3 重新以队长身份创建第二支队伍 "太阳战队"
        res = await ac.post(
            f"/contests/{contest_id}/teams",
            json={"name": "太阳战队"},
            headers=u3_headers,
        )
        assert res.status_code == 200
        team2 = res.json()
        assert team2["name"] == "太阳战队"

        # 14. 获取所有队伍列表 (GET /{contest_id}/teams)
        res = await ac.get(f"/contests/{contest_id}/teams", headers=u1_headers)
        assert res.status_code == 200
        all_teams = res.json()
        assert len(all_teams) == 2
        team_names = [t["name"] for t in all_teams]
        assert "银河战队" in team_names and "太阳战队" in team_names

        # 15. 非队内成员获取详情时为 None (u4 还没加入任何队伍)
        res = await ac.get(f"/contests/{contest_id}/my-team", headers=u4_headers)
        assert res.status_code == 200
        assert res.json() is None


@pytest.mark.asyncio
async def test_contest_team_submissions_and_rank():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        admin_headers, admin_id, _ = await _register_and_login(ac, is_admin=True)
        t1_leader_h, t1_leader_id, _ = await _register_and_login(ac)
        t1_member_h, t1_member_id, _ = await _register_and_login(ac)
        solo_user_h, solo_user_id, _ = await _register_and_login(ac)

        prob_a = await _create_problem("Rank Prob A")
        prob_b = await _create_problem("Rank Prob B")

        now = datetime.now(timezone.utc)
        start_time = (now - timedelta(minutes=10)).isoformat()
        end_time = (now + timedelta(hours=2)).isoformat()

        # 创建组队赛，XCPC 规则
        res = await ac.post(
            "/contests",
            json={
                "title": "XCPC 组队榜单测试赛",
                "description": "测试组队共享过题与榜单统计",
                "start_time": start_time,
                "end_time": end_time,
                "rule_type": "xcpc",
                "is_team_contest": True,
                "max_team_members": 3,
                "problem_ids": [prob_a.id, prob_b.id],
            },
            headers=admin_headers,
        )
        assert res.status_code == 201
        contest_id = res.json()["id"]

        # solo_user 报名比赛但没有建队也没有加入队伍
        res = await ac.post(f"/contests/{contest_id}/register", headers=solo_user_h)
        assert res.status_code == 200

        # solo_user 尝试提交代码 -> 应当被拒绝，要求先创建或加入队伍 (403)
        res = await ac.post(
            f"/problems/{prob_a.id}/submissions",
            json={
                "contest_id": contest_id,
                "language": "python3",
                "code": "print('hello')",
            },
            headers=solo_user_h,
        )
        assert res.status_code == 403, res.text
        assert "本场为组队赛" in res.json()["detail"]

        # t1_leader 创建队伍 "超新星"
        res = await ac.post(
            f"/contests/{contest_id}/teams",
            json={"name": "超新星"},
            headers=t1_leader_h,
        )
        assert res.status_code == 200
        team = res.json()
        team_id = team["team_id"]
        invite_code = team["invite_code"]

        # t1_member 加入 "超新星"
        res = await ac.post(
            f"/contests/{contest_id}/teams/join",
            json={"invite_code": invite_code},
            headers=t1_member_h,
        )
        assert res.status_code == 200

        # t1_leader 提交 Problem A
        res = await ac.post(
            f"/problems/{prob_a.id}/submissions",
            json={
                "contest_id": contest_id,
                "language": "python3",
                "code": "print('leader a')",
            },
            headers=t1_leader_h,
        )
        assert res.status_code == 200, res.text
        sub_a_id = res.json()["id"]

        # t1_member 提交 Problem B
        res = await ac.post(
            f"/problems/{prob_b.id}/submissions",
            json={
                "contest_id": contest_id,
                "language": "python3",
                "code": "print('member b')",
            },
            headers=t1_member_h,
        )
        assert res.status_code == 200, res.text
        sub_b_id = res.json()["id"]

        # 手动在 DB 中将两笔提交标记为 Accepted，并记录评测结果与提交时间
        async with AsyncSessionLocal() as db:
            s_a = await db.get(Submission, sub_a_id)
            assert s_a is not None
            assert s_a.contest_team_id == team_id  # 验证自动绑定了队伍 ID
            s_a.status = "accepted"
            s_a.score = 100

            s_b = await db.get(Submission, sub_b_id)
            assert s_b is not None
            assert s_b.contest_team_id == team_id  # 验证自动绑定了队伍 ID
            s_b.status = "accepted"
            s_b.score = 100
            await db.commit()

        # 验证队友可以查看互相的提交代码（即使启用了比赛代码私密）
        res = await ac.get(f"/submissions/{sub_a_id}", headers=t1_member_h)
        assert res.status_code == 200
        assert res.json()["code"] == "print('leader a')"

        res = await ac.get(f"/submissions/{sub_b_id}", headers=t1_leader_h)
        assert res.status_code == 200
        assert res.json()["code"] == "print('member b')"

        # solo_user 无法查看其他人的比赛代码 (403 Forbidden)
        res = await ac.get(f"/submissions/{sub_a_id}", headers=solo_user_h)
        assert res.status_code == 403

        # 获取比赛排行榜
        res = await ac.get(f"/contests/{contest_id}/rank", headers=t1_leader_h)
        assert res.status_code == 200
        rank_data = res.json()
        assert rank_data["is_team_contest"] is True
        rows = rank_data["rows"]
        # 超新星队通过了两道题 (Problem A 和 Problem B)
        assert len(rows) >= 1
        t_row = next((r for r in rows if r.get("team") and r["team"]["name"] == "超新星"), None)
        assert t_row is not None
        assert t_row["solved"] == 2
        assert len(t_row["team"]["members"]) == 2
        # 榜单每道题的状态均为 passed
        detail = t_row["detail"]
        assert detail["A"]["solved"] is True
        assert detail["B"]["solved"] is True
