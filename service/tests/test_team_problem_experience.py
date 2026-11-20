"""团队私有题与主题库题目经验值隔离测试。

验证规则：
1. 主题库题目（team_id is None）：首次 AC 正常发放对应难度经验值；
2. 团队私有题（team_id is not None）：首次 AC 不发放经验值（防自建团刷分）；
3. 团队私有题难度变更或成绩取消：不调整/不扣回经验值；
4. 主题库题成绩取消时正常扣回经验值。
"""

from typing import Any
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.problem import Problem
from app.models.submission import Submission
import app.models.submission as sub_models
from app.models.team import Team
from app.models.user import User
from app.services import judge
from app.services.judge import adjust_experience_on_difficulty_change


async def _make_user(ac: AsyncClient, tag: str, **perms) -> str:
    uname = f"exp_{tag}_{uuid.uuid4().hex[:6]}"
    r = await ac.post("/users", json={
        "username": uname, "email": f"{uname}@example.com", "password": "supersecret1"})
    assert r.status_code == 201, r.text
    if perms:
        async with AsyncSessionLocal() as db:
            u = (await db.execute(
                select(User).where(User.username == uname))).scalar_one()
            for k, v in perms.items():
                setattr(u, k, v)
            await db.commit()
    return uname


@pytest.mark.asyncio
async def test_team_problem_does_not_award_experience(monkeypatch):
    async def fake_cmd(client: Any, cmd: dict[str, Any]) -> dict[str, Any]:
        return {"status": "Accepted", "files": {"stdout": "1\n"}}

    async def fake_del(client: Any, fid: str) -> None:
        pass

    monkeypatch.setattr(judge, "_run_cmd", fake_cmd)
    monkeypatch.setattr(judge, "_delete_file", fake_del)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        user_name = await _make_user(ac, "u")
        mgr_name = await _make_user(ac, "mgr", can_manage_users=True, can_manage_problems=True)
        mh_login = await ac.post("/tokens", data={"username": mgr_name, "password": "supersecret1"})
        mh = {"Authorization": f"Bearer {mh_login.json()['access_token']}"}

        async with AsyncSessionLocal() as db:
            u = (await db.execute(select(User).where(User.username == user_name))).scalar_one()
            uid = u.id
            assert u.experience == 0

            # 1. 创建团队及团队私有题目（提高难度，正常应得 200 经验）
            team = Team(name=f"团队_{uuid.uuid4().hex[:6]}", owner_id=uid)
            db.add(team)
            await db.flush()

            team_prob = Problem(
                title="团队私有提高题",
                difficulty="提高",
                team_id=team.id,
                is_public=False,
            )
            db.add(team_prob)
            await db.flush()

            tc1 = sub_models.TestCase(problem_id=team_prob.id, sort_order=1, input_data="1\n", expected_output="1\n")
            db.add(tc1)

            # 创建提交并触发评测
            sub1 = Submission(
                problem_id=team_prob.id,
                user_id=uid,
                code="print(input())",
                language="python3",
                status="pending",
            )
            db.add(sub1)
            await db.commit()
            team_prob_id = team_prob.id
            sub1_id = sub1.id

        # 评测团队私有题
        await judge.judge_submission(sub1_id)

        # 校验：状态为 accepted，但用户经验仍为 0
        async with AsyncSessionLocal() as db:
            u = await db.get(User, uid)
            sub1 = await db.get(Submission, sub1_id)
            assert sub1.status == "accepted"
            assert u.experience == 0, "团队私有题不应发放经验值"

            # 2. 修改团队私有题难度至 NOI/NOI+/CTSC，校验不加经验
            affected = await adjust_experience_on_difficulty_change(db, team_prob_id, "提高", "NOI/NOI+/CTSC")
            assert affected == 0, "团队题难度变更不应调整用户经验"
            await db.refresh(u)
            assert u.experience == 0

            # 3. 创建主题库题目（普及难度，应得 10 经验）
            pub_prob = Problem(
                title="主题库普及题",
                difficulty="普及",
                team_id=None,
                is_public=True,
            )
            db.add(pub_prob)
            await db.flush()

            tc2 = sub_models.TestCase(problem_id=pub_prob.id, sort_order=1, input_data="1\n", expected_output="1\n")
            db.add(tc2)

            sub2 = Submission(
                problem_id=pub_prob.id,
                user_id=uid,
                code="print(input())",
                language="python3",
                status="pending",
            )
            db.add(sub2)
            await db.commit()
            sub2_id = sub2.id

        # 评测主题库题
        await judge.judge_submission(sub2_id)

        # 校验：状态为 accepted，用户获得普及难度的 10 经验
        async with AsyncSessionLocal() as db:
            u = await db.get(User, uid)
            sub2 = await db.get(Submission, sub2_id)
            assert sub2.status == "accepted"
            assert u.experience == 10, "主题库题目首次 AC 应当增加 10 经验"

        # 4. 管理员取消团队题成绩：用户经验保持 10（不扣减）
        r = await ac.post(f"/submissions/{sub1_id}/cancel-score", headers=mh)
        assert r.status_code == 200, r.text
        async with AsyncSessionLocal() as db:
            u = await db.get(User, uid)
            assert u.experience == 10, "取消团队题不应扣回经验"

        # 5. 管理员取消主题库题成绩：用户经验扣回 10 -> 0
        r = await ac.post(f"/submissions/{sub2_id}/cancel-score", headers=mh)
        assert r.status_code == 200, r.text
        async with AsyncSessionLocal() as db:
            u = await db.get(User, uid)
            assert u.experience == 0, "取消主题库题成绩应正常扣回经验"
