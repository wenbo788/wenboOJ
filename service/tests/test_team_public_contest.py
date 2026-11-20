"""公开比赛中挂载团队公开题及全站开放访问的测试。

验证规则：
1. 团队公开题（is_public=True, team_id 不为空）：
   - 全站用户及未登录访客均可通过 /problems/{id} 与 /problems/by-code/{code} 访问题面；
   - 非团队成员访问 /teams/{team_id}/problems 时，能看到团队公开题，看不到团队私有题；
   - 非团队成员可正常提交或进行自测。
2. 比赛挂载与联动：
   - 创建或编辑公开比赛（visibility='public' 或 'team_public'）时，所选团队题自动被设为 is_public=True；
   - 参赛者在比赛中通过比赛上下文提交团队题目，正常判题，不被团队成员限制拦截。
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.contest import Contest, ContestProblem, ContestParticipant
from app.models.problem import Problem
from app.models.submission import TestCase as DbTestCase
from app.models.team import Team
from app.models.user import User
from app.services import judge
from sqlalchemy import func


async def _next_t_no(db) -> int:
    m = (await db.execute(select(func.max(Problem.t_no)))).scalar() or 0
    return m + 1


async def _make_user(ac: AsyncClient, name_prefix: str, **kwargs) -> tuple[dict[str, str], int]:
    uname = f"{name_prefix}_{uuid.uuid4().hex[:8]}"
    pwd = "supersecret1"
    r = await ac.post("/users", json={"username": uname, "email": f"{uname}@example.com", "password": pwd})
    assert r.status_code == 201, r.text
    r = await ac.post("/tokens", data={"username": uname, "password": pwd})
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await ac.get("/auth/me", headers=headers)).json()
    uid = me["id"]
    if kwargs:
        async with AsyncSessionLocal() as db:
            u = await db.get(User, uid)
            for k, v in kwargs.items():
                setattr(u, k, v)
            await db.commit()
    return headers, uid


@pytest.mark.asyncio
async def test_team_public_problem_direct_access(monkeypatch):
    """验证团队公开题对站内普通用户及非团队成员直接可见。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        owner_hdrs, owner_id = await _make_user(ac, "owner")
        guest_hdrs, guest_id = await _make_user(ac, "guest")

        async with AsyncSessionLocal() as db:
            team = Team(name=f"团队_{uuid.uuid4().hex[:6]}", owner_id=owner_id)
            db.add(team)
            await db.flush()

            t1 = await _next_t_no(db)
            # 公开团队题
            prob_pub = Problem(
                title="团队公开题-A",
                difficulty="入门",
                description="公开题描述",
                team_id=team.id,
                t_no=t1,
                is_public=True,
                author_id=owner_id,
            )
            # 私有团队题
            prob_priv = Problem(
                title="团队私有题-B",
                difficulty="普及",
                description="私有题描述",
                team_id=team.id,
                t_no=t1 + 1,
                is_public=False,
                author_id=owner_id,
            )
            db.add_all([prob_pub, prob_priv])
            await db.commit()
            await db.refresh(prob_pub)
            await db.refresh(prob_priv)
            pub_id = prob_pub.id
            pub_code = prob_pub.problem_number
            priv_id = prob_priv.id
            team_id = team.id

        # 1. 非团队成员访问团队公开题 -> 200 成功
        r_pub = await ac.get(f"/problems/{pub_id}", headers=guest_hdrs)
        assert r_pub.status_code == 200, r_pub.text
        data = r_pub.json()
        assert data["title"] == "团队公开题-A"
        assert data["is_public"] is True
        assert data["team_id"] == team_id

        # 2. 通过 by-code 访问 -> 200 成功
        r_code = await ac.get(f"/problems/by-code/{pub_code}", headers=guest_hdrs)
        assert r_code.status_code == 200, r_code.text
        assert r_code.json()["id"] == pub_id

        # 3. 非团队成员访问团队私有题 -> 404
        r_priv = await ac.get(f"/problems/{priv_id}", headers=guest_hdrs)
        assert r_priv.status_code == 404

        # 4. 非团队成员查看团队题库列表 -> 仅返回公开题
        r_list = await ac.get(f"/teams/{team_id}/problems", headers=guest_hdrs)
        assert r_list.status_code == 200, r_list.text
        list_data = r_list.json()
        assert len(list_data) == 1
        assert list_data[0]["id"] == pub_id


@pytest.mark.asyncio
async def test_contest_auto_publishes_team_problem_and_allows_contest_submissions(monkeypatch):
    """验证公开比赛挂载团队题时自动设为公开，且参赛者可正常提交。"""
    async def fake_cmd(client: Any, cmd: dict[str, Any]) -> dict[str, Any]:
        return {"status": "Accepted", "files": {"stdout": "1\n"}}

    async def fake_del(client: Any, fid: str) -> None:
        pass

    monkeypatch.setattr(judge, "_run_cmd", fake_cmd)
    monkeypatch.setattr(judge, "_delete_file", fake_del)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        owner_hdrs, owner_id = await _make_user(ac, "cowner")
        player_hdrs, player_id = await _make_user(ac, "player")

        async with AsyncSessionLocal() as db:
            team = Team(name=f"团队_{uuid.uuid4().hex[:6]}", owner_id=owner_id)
            db.add(team)
            await db.flush()

            t_num = await _next_t_no(db)
            # 初始为私有团队题
            prob = Problem(
                title="比赛用团队题",
                difficulty="提高",
                description="比赛题描述",
                team_id=team.id,
                t_no=t_num,
                is_public=False,
                author_id=owner_id,
            )
            db.add(prob)
            await db.flush()

            tc = DbTestCase(problem_id=prob.id, sort_order=1, input_data="1\n", expected_output="1\n")
            db.add(tc)
            await db.commit()
            await db.refresh(prob)
            prob_id = prob.id
            prob_code = prob.problem_number

        # 1. 团队所有者创建团队公开比赛，挂载该题目
        now = datetime.now(timezone.utc)
        payload = {
            "title": f"团队公开赛_{uuid.uuid4().hex[:4]}",
            "description": "赛题测试",
            "start_time": (now - timedelta(minutes=10)).isoformat(),
            "end_time": (now + timedelta(hours=2)).isoformat(),
            "rule_type": "ioi",
            "team_id": team.id,
            "visibility": "team_public",
            "problem_ids": [prob_id],
        }
        r_create = await ac.post("/contests", json=payload, headers=owner_hdrs)
        assert r_create.status_code == 201, r_create.text
        cid = r_create.json()["id"]

        # 2. 检查题目的 is_public 是否被联动更新为 True
        async with AsyncSessionLocal() as db:
            p_refreshed = await db.get(Problem, prob_id)
            assert p_refreshed.is_public is True, "公开赛挂载的团队题应被自动更新为公开题"

        # 3. 参赛者报名比赛
        r_reg = await ac.post(f"/contests/{cid}/register", headers=player_hdrs)
        assert r_reg.status_code == 200, r_reg.text

        # 4. 参赛者在比赛中提交代码
        sub_payload = {
            "code": "print(1)",
            "language": "python3",
            "contest_id": cid,
        }
        r_sub = await ac.post(f"/problems/{prob_id}/submissions", json=sub_payload, headers=player_hdrs)
        assert r_sub.status_code == 200, r_sub.text
        sub_id = r_sub.json()["id"]

        # 5. 判题执行并检查结果
        await judge.judge_submission(sub_id)

        # 6. 参赛者可正常查询自己的提交详情
        r_detail = await ac.get(f"/submissions/{sub_id}", headers=player_hdrs)
        assert r_detail.status_code == 200, r_detail.text
        assert r_detail.json()["status"] == "accepted"
