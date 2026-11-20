"""比赛编辑功能与团队公开赛测试。

测试点：
1. 团队公开赛（team_public）：支持创建、查看、免邀请码自由报名、展示「团队公开赛」
2. 编辑比赛（PUT /contests/{id}）：
   - 修改比赛标题、描述、起止时间、赛制
   - 添加、删除、修改题目及调整顺序（A/B/C/D）
   - 切换举办方：个人赛 ↔ 团队赛，修改公开程度（公开赛 / 团队公开赛 / 团队内部赛等）
3. 权限控制：非管理员且非创建者无权编辑
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.problem import Problem, REVIEW_APPROVED
from app.models.team import Team, TeamMember
from app.models.user import User


async def _register_and_login(ac: AsyncClient, *, is_admin: bool = False) -> tuple[dict[str, str], int]:
    suffix = uuid.uuid4().hex[:8]
    username = f"ce_{suffix}"
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

    return headers, user_id


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
        return p


async def _create_team(owner_id: int, name: str) -> int:
    async with AsyncSessionLocal() as db:
        t = Team(name=name, description="团队说明", owner_id=owner_id)
        db.add(t)
        await db.flush()
        db.add(TeamMember(team_id=t.id, user_id=owner_id, role="owner"))
        await db.commit()
        return t.id


@pytest.mark.asyncio
async def test_team_public_contest_and_edit_flow():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        admin_headers, admin_id = await _register_and_login(ac, is_admin=True)
        user_headers, user_id = await _register_and_login(ac, is_admin=False)

        # 准备两道题
        p1 = await _create_problem("题1")
        p2 = await _create_problem("题2")
        p3 = await _create_problem("题3")

        # 管理员创建一个团队
        team_id = await _create_team(admin_id, "星轨开发组")

        now = datetime.now(timezone.utc)
        start = (now + timedelta(hours=1)).isoformat()
        end = (now + timedelta(hours=4)).isoformat()

        # 1. 创建团队公开赛 (team_public)
        r = await ac.post("/contests", headers=admin_headers, json={
            "title": "NLNOI R1 团队公开赛",
            "description": "初始描述：欢迎参赛",
            "start_time": start,
            "end_time": end,
            "team_id": team_id,
            "visibility": "team_public",
            "rule_type": "ioi",
            "problem_codes": [p1.problem_number, p2.problem_number],
        })
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        assert r.json()["visibility"] == "team_public"
        assert r.json()["type_label"] == "团队公开赛"
        assert r.json()["team_name"] == "星轨开发组"
        assert len(r.json()["problems"]) == 2
        assert r.json()["problems"][0]["problem_number"] == p1.problem_number
        assert r.json()["problems"][1]["problem_number"] == p2.problem_number

        # 2. 普通用户查看比赛详情与自由报名（无需邀请码且无需加入团队）
        detail = (await ac.get(f"/contests/{cid}", headers=user_headers)).json()
        assert detail["type_label"] == "团队公开赛"
        assert detail["team_name"] == "星轨开发组"
        assert detail["can_edit"] is False

        # 报名成功
        r_reg = await ac.post(f"/contests/{cid}/register", headers=user_headers)
        assert r_reg.status_code == 200, r_reg.text

        # 3. 编辑比赛：修改描述、添加新题并重排（P3, P1）、改变举办方为个人赛
        new_start = (now + timedelta(hours=2)).isoformat()
        new_end = (now + timedelta(hours=5)).isoformat()
        r_edit = await ac.put(f"/contests/{cid}", headers=admin_headers, json={
            "title": "NLNOI R1 (改名为官方公开赛)",
            "description": "修改后的题面说明：支持 IOI 赛制！",
            "start_time": new_start,
            "end_time": new_end,
            "team_id": None,
            "visibility": "public",
            "rule_type": "xcpc",
            "problem_codes": [p3.problem_number, p1.problem_number],
        })
        assert r_edit.status_code == 200, r_edit.text
        updated = r_edit.json()
        assert updated["title"] == "NLNOI R1 (改名为官方公开赛)"
        assert updated["description"] == "修改后的题面说明：支持 IOI 赛制！"
        assert updated["team_id"] is None
        assert updated["team_name"] is None
        assert updated["type_label"] == "公开赛"
        assert updated["rule_type"] == "xcpc"
        assert len(updated["problems"]) == 2
        assert updated["problems"][0]["alias"] == "A"
        assert updated["problems"][0]["problem_number"] == p3.problem_number
        assert updated["problems"][1]["alias"] == "B"
        assert updated["problems"][1]["problem_number"] == p1.problem_number

        # 4. 再次编辑：切换回团队内部赛并测试仅团队成员可报
        team2_id = await _create_team(admin_id, "内部测试组")
        r_edit2 = await ac.put(f"/contests/{cid}", headers=admin_headers, json={
            "team_id": team2_id,
            "visibility": "team",
            "problem_codes": [p2.problem_number],
        })
        assert r_edit2.status_code == 200, r_edit2.text
        assert r_edit2.json()["team_id"] == team2_id
        assert r_edit2.json()["type_label"] == "团队内部赛"
        assert len(r_edit2.json()["problems"]) == 1

        # 5. 权限验证：普通用户尝试编辑返回 403
        r_denied = await ac.put(f"/contests/{cid}", headers=user_headers, json={
            "title": "非法篡改",
        })
        assert r_denied.status_code == 403


@pytest.mark.asyncio
async def test_contest_edit_edge_cases():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        admin_headers, admin_id = await _register_and_login(ac, is_admin=True)
        user_headers, user_id = await _register_and_login(ac, is_admin=False)

        p1 = await _create_problem("题1")
        team1 = await _create_team(admin_id, "团队1")
        team2 = await _create_team(user_id, "用户团队")

        now = datetime.now(timezone.utc)
        start = (now + timedelta(hours=1)).isoformat()
        end = (now + timedelta(hours=4)).isoformat()

        # 1. 个人赛切换为团队赛
        r1 = await ac.post("/contests", headers=admin_headers, json={
            "title": "站方公开赛",
            "start_time": start,
            "end_time": end,
            "visibility": "public",
            "problem_codes": [p1.problem_number],
        })
        assert r1.status_code == 201
        cid = r1.json()["id"]

        # 管理员将站方公开赛改为团队公开赛
        r_change = await ac.put(f"/contests/{cid}", headers=admin_headers, json={
            "title": "改后的团队赛",
            "start_time": start,
            "end_time": end,
            "team_id": team1,
            "visibility": "team_public",
            "problem_codes": [p1.problem_number],
            "rule_type": "xcpc",
        })
        print("Change to team contest status:", r_change.status_code, r_change.text)
        assert r_change.status_code == 200, r_change.text
        assert r_change.json()["team_id"] == team1
        assert r_change.json()["visibility"] == "team_public"

        # 2. 如果 team_id 传入了字符串类型的数字（前端已容错）
        r_str_team = await ac.put(f"/contests/{cid}", headers=admin_headers, json={
            "team_id": str(team1),
            "visibility": "team_public",
        })
        assert r_str_team.status_code == 200, r_str_team.text
        assert r_str_team.json()["team_id"] == team1

        # 3. 如果想保存为团队公开赛，但 team_id 为 None 或未传
        r_none_team = await ac.put(f"/contests/{cid}", headers=admin_headers, json={
            "team_id": None,
            "visibility": "team_public",
        })
        assert r_none_team.status_code == 400
        assert "举办团队比赛需指定举办团队" in r_none_team.json()["detail"]

        # 4. 普通用户尝试切换到一个自己不是管理员的团队
        user_team_contest = await ac.post("/contests", headers=user_headers, json={
            "title": "用户自己的团队赛",
            "start_time": start,
            "end_time": end,
            "team_id": team2,
            "visibility": "team_public",
            "problem_codes": [p1.problem_number],
        })
        assert user_team_contest.status_code == 201
        ucid = user_team_contest.json()["id"]

        r_no_perm = await ac.put(f"/contests/{ucid}", headers=user_headers, json={
            "team_id": team1,  # user_id 不是 team1 的管理员
            "visibility": "team_public",
        })
        assert r_no_perm.status_code == 403
        assert "需要目标团队的管理权限" in r_no_perm.json()["detail"]

        # 5. 团队题在比赛中的解析与编辑保存测试
        async with AsyncSessionLocal() as db:
            tp = Problem(
                title="团队题1",
                difficulty="普及-",
                description="题面",
                is_public=False,
                team_id=team2,
                t_no=None,  # 某些情况下可能为 None
            )
            db.add(tp)
            await db.commit()
            await db.refresh(tp)
            tp_id = tp.id
            tp_num = tp.problem_number

        assert tp_num == f"T{tp_id}"
        # 尝试将包含这道团队题的比赛保存
        r_team_prob = await ac.put(f"/contests/{ucid}", headers=user_headers, json={
            "team_id": team2,
            "visibility": "team_public",
            "problem_codes": [tp_num],
        })
        assert r_team_prob.status_code == 200, r_team_prob.text

        # 如果题目有 t_no=5，但按 T{id} 传参：
        async with AsyncSessionLocal() as db:
            tp2 = Problem(
                title="团队题2",
                difficulty="普及-",
                description="题面",
                is_public=False,
                team_id=team2,
                t_no=5,
            )
            db.add(tp2)
            await db.commit()
            await db.refresh(tp2)
            tp2_id = tp2.id

        r_team_prob_id = await ac.put(f"/contests/{ucid}", headers=user_headers, json={
            "team_id": team2,
            "visibility": "team_public",
            "problem_codes": [f"T{tp2_id}"],  # 支持按题目 id 兜底查找
        })
        assert r_team_prob_id.status_code == 200, r_team_prob_id.text


