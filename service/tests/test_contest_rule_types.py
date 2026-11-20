"""比赛赛制测试（XCPC、OI、IOI）。

验证：
1. 赛制创建与兼容校验（xcpc / acm / oi / ioi）；
2. XCPC 赛制：AC 即满分、罚时计算（仅首 AC 计入、CE 不计罚次、AC 后的提交忽略）、全场首杀（first_solved）；
3. OI 赛制：以最后一次提交为准、赛中盲交评测结果隐藏、赛中普通选手锁榜、赛后全解封；
4. IOI 赛制：以历史最高提交分为准、赛中实时反馈与榜单公开。
"""

from datetime import datetime, timedelta, timezone
from typing import Any
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.contest import Contest, ContestParticipant, ContestProblem
from app.models.problem import Problem
from app.models.submission import Submission, TestCase
from app.models.user import User


async def _make_user(ac: AsyncClient, name_prefix: str, **kwargs: Any) -> tuple[dict[str, str], int]:
    uname = f"{name_prefix}_{uuid.uuid4().hex[:6]}"
    r = await ac.post("/users", json={"username": uname, "email": f"{uname}@example.com", "password": "supersecret1"})
    assert r.status_code == 201, r.text
    if kwargs:
        async with AsyncSessionLocal() as db:
            u = (await db.execute(select(User).where(User.username == uname))).scalar_one()
            for k, v in kwargs.items():
                setattr(u, k, v)
            await db.commit()
    r = await ac.post("/tokens", data={"username": uname, "password": "supersecret1"})
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await ac.get("/auth/me", headers=headers)).json()
    return headers, me["id"]


async def _create_prob(title: str) -> int:
    async with AsyncSessionLocal() as db:
        p = Problem(title=title, difficulty="普及-", description="测试题", is_public=True)
        db.add(p)
        await db.flush()
        db.add(TestCase(problem_id=p.id, input_data="1\n", expected_output="1\n", sort_order=0))
        await db.commit()
        return p.id


@pytest.mark.asyncio
async def test_contest_rule_type_validation_and_creation():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        admin_h, admin_id = await _make_user(ac, "adm", is_super_admin=True)
        pid = await _create_prob("RuleTypeTest")

        now = datetime.now(timezone.utc)
        base_payload = {
            "title": "赛制测试",
            "start_time": (now - timedelta(hours=1)).isoformat(),
            "end_time": (now + timedelta(hours=2)).isoformat(),
            "problem_codes": [f"P{1000 + pid}"],
            "visibility": "public",
        }

        # 1. 默认与指定 xcpc
        r = await ac.post("/contests", headers=admin_h, json={**base_payload, "rule_type": "xcpc"})
        assert r.status_code == 201, r.text
        assert r.json()["rule_type"] == "xcpc"
        assert r.json()["rule_type_label"] == "XCPC 赛制"

        # 2. 兼容历史 acm
        r = await ac.post("/contests", headers=admin_h, json={**base_payload, "rule_type": "acm"})
        assert r.status_code == 201, r.text
        assert r.json()["rule_type"] == "xcpc"

        # 3. oi 赛制
        r = await ac.post("/contests", headers=admin_h, json={**base_payload, "rule_type": "oi"})
        assert r.status_code == 201, r.text
        assert r.json()["rule_type"] == "oi"
        assert r.json()["rule_type_label"] == "OI 赛制"

        # 4. ioi 赛制
        r = await ac.post("/contests", headers=admin_h, json={**base_payload, "rule_type": "ioi"})
        assert r.status_code == 201, r.text
        assert r.json()["rule_type"] == "ioi"
        assert r.json()["rule_type_label"] == "IOI 赛制"

        # 5. 非法赛制
        r = await ac.post("/contests", headers=admin_h, json={**base_payload, "rule_type": "invalid_type"})
        assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_xcpc_rank_and_fb():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        admin_h, admin_id = await _make_user(ac, "xcpc_adm", is_super_admin=True)
        u1_h, u1_id = await _make_user(ac, "xcpc_u1")
        u2_h, u2_id = await _make_user(ac, "xcpc_u2")

        p1_id = await _create_prob("XCPC_P1")
        p2_id = await _create_prob("XCPC_P2")

        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=60)
        end = now + timedelta(minutes=120)

        async with AsyncSessionLocal() as db:
            contest = Contest(
                title="XCPC精算赛",
                visibility="public",
                rule_type="xcpc",
                start_time=start,
                end_time=end,
                owner_id=admin_id,
            )
            db.add(contest)
            await db.flush()
            cid = contest.id
            db.add(ContestProblem(contest_id=cid, problem_id=p1_id, sort_order=0))
            db.add(ContestProblem(contest_id=cid, problem_id=p2_id, sort_order=1))
            db.add(ContestParticipant(contest_id=cid, user_id=u1_id))
            db.add(ContestParticipant(contest_id=cid, user_id=u2_id))

            # u1 对 P1：
            # 1. 5分钟时 WA
            db.add(Submission(contest_id=cid, user_id=u1_id, problem_id=p1_id, code="x", language="cpp",
                              status="wrong_answer", score=0, created_at=start + timedelta(minutes=5)))
            # 2. 10分钟时 CE（XCPC 中 CE 不计入罚次）
            db.add(Submission(contest_id=cid, user_id=u1_id, problem_id=p1_id, code="x", language="cpp",
                              status="compile_error", score=0, created_at=start + timedelta(minutes=10)))
            # 3. 15分钟时 AC（全场首次 AC P1 -> first_solved）
            db.add(Submission(contest_id=cid, user_id=u1_id, problem_id=p1_id, code="x", language="cpp",
                              status="accepted", score=100, created_at=start + timedelta(minutes=15)))
            # 4. 20分钟时再次提交 WA（AC 后提交不增加罚时）
            db.add(Submission(contest_id=cid, user_id=u1_id, problem_id=p1_id, code="x", language="cpp",
                              status="wrong_answer", score=0, created_at=start + timedelta(minutes=20)))

            # u2 对 P1：
            # 25分钟时 AC（1次通过，罚时 25）
            db.add(Submission(contest_id=cid, user_id=u2_id, problem_id=p1_id, code="x", language="cpp",
                              status="accepted", score=100, created_at=start + timedelta(minutes=25)))
            # u2 对 P2：
            # 30分钟时 WA（未通过，尝试1次，不计入罚时）
            db.add(Submission(contest_id=cid, user_id=u2_id, problem_id=p2_id, code="x", language="cpp",
                              status="wrong_answer", score=0, created_at=start + timedelta(minutes=30)))
            await db.commit()

        # 查询排行榜
        r = await ac.get(f"/contests/{cid}/rank", headers=u1_h)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["rule_type"] == "xcpc"
        assert data["is_frozen"] is False
        rows = data["rows"]
        assert len(rows) == 2

        # u2: solved=1, penalty=25. u1: solved=1, penalty=15 + 20*1 = 35.
        # 所以 Rank 1 是 u2，Rank 2 是 u1
        assert rows[0]["user"]["user_id"] == u2_id
        assert rows[0]["solved"] == 1
        assert rows[0]["penalty"] == 25
        assert rows[0]["detail"]["A"]["solved"] is True
        assert rows[0]["detail"]["A"]["first_solved"] is False
        assert rows[0]["detail"]["B"]["solved"] is False
        assert rows[0]["detail"]["B"]["tries"] == 1

        assert rows[1]["user"]["user_id"] == u1_id
        assert rows[1]["solved"] == 1
        assert rows[1]["penalty"] == 35  # 15 + 1次非CE错误*20
        assert rows[1]["detail"]["A"]["solved"] is True
        assert rows[1]["detail"]["A"]["tries"] == 1
        assert rows[1]["detail"]["A"]["first_solved"] is True


@pytest.mark.asyncio
async def test_oi_last_submission_and_privacy():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        admin_h, admin_id = await _make_user(ac, "oi_adm", is_super_admin=True)
        u1_h, u1_id = await _make_user(ac, "oi_u1")
        u2_h, u2_id = await _make_user(ac, "oi_u2")

        p1_id = await _create_prob("OI_P1")
        p2_id = await _create_prob("OI_P2")

        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=30)
        end = now + timedelta(minutes=90)  # 进行中

        async with AsyncSessionLocal() as db:
            contest = Contest(
                title="OI模拟赛",
                visibility="public",
                rule_type="oi",
                start_time=start,
                end_time=end,
                owner_id=admin_id,
            )
            db.add(contest)
            await db.flush()
            cid = contest.id
            db.add(ContestProblem(contest_id=cid, problem_id=p1_id, sort_order=0))
            db.add(ContestProblem(contest_id=cid, problem_id=p2_id, sort_order=1))
            db.add(ContestParticipant(contest_id=cid, user_id=u1_id))
            db.add(ContestParticipant(contest_id=cid, user_id=u2_id))

            # u1 对 P1：先得 100 分，后来改错最后一次提交得 40 分（OI 必须以 40 分为准！）
            sub_u1_1 = Submission(contest_id=cid, user_id=u1_id, problem_id=p1_id, code="c1", language="cpp",
                                  status="accepted", score=100, created_at=start + timedelta(minutes=5))
            db.add(sub_u1_1)
            await db.flush()
            sub_u1_1_id = sub_u1_1.id

            sub_u1_2 = Submission(contest_id=cid, user_id=u1_id, problem_id=p1_id, code="c2", language="cpp",
                                  status="wrong_answer", score=40, created_at=start + timedelta(minutes=15))
            db.add(sub_u1_2)

            # u2 对 P1：提交得 80 分
            sub_u2_1 = Submission(contest_id=cid, user_id=u2_id, problem_id=p1_id, code="c3", language="cpp",
                                  status="wrong_answer", score=80, created_at=start + timedelta(minutes=20))
            db.add(sub_u2_1)
            await db.commit()

        # 1. 赛中普通参赛者查看提交详情：评测结果隐藏
        r = await ac.get(f"/submissions/{sub_u1_1_id}", headers=u1_h)
        assert r.status_code == 200, r.text
        sub_d = r.json()
        assert sub_d["result_hidden"] is True
        assert sub_d["status"] == "submitted"
        assert sub_d["score"] == 0

        # 2. 赛中管理员查看提交详情：正常可见真实分数
        r = await ac.get(f"/submissions/{sub_u1_1_id}", headers=admin_h)
        assert r.status_code == 200, r.text
        sub_adm_d = r.json()
        assert sub_adm_d["result_hidden"] is False
        assert sub_adm_d["score"] == 100

        # 3. 赛中普通参赛者访问排行榜：is_frozen=True，榜单隐藏
        r = await ac.get(f"/contests/{cid}/rank", headers=u1_h)
        assert r.status_code == 200, r.text
        rank_data = r.json()
        assert rank_data["is_frozen"] is True
        assert len(rank_data["rows"]) == 0

        # 4. 赛中管理员访问排行榜：正常查看榜单
        r = await ac.get(f"/contests/{cid}/rank", headers=admin_h)
        assert r.status_code == 200, r.text
        adm_rank = r.json()
        assert adm_rank["is_frozen"] is False
        assert len(adm_rank["rows"]) == 2
        # u2 总分 80，u1 最终得分 40，u2 领先
        assert adm_rank["rows"][0]["user"]["user_id"] == u2_id
        assert adm_rank["rows"][0]["total_score"] == 80
        assert adm_rank["rows"][1]["user"]["user_id"] == u1_id
        assert adm_rank["rows"][1]["total_score"] == 40

        # 5. 赛后（结束时间调整到过去）：普通选手可见真实排行榜
        async with AsyncSessionLocal() as db:
            c = await db.get(Contest, cid)
            c.end_time = now - timedelta(minutes=5)
            await db.commit()

        r = await ac.get(f"/contests/{cid}/rank", headers=u1_h)
        assert r.status_code == 200, r.text
        ended_rank = r.json()
        assert ended_rank["is_frozen"] is False
        assert len(ended_rank["rows"]) == 2
        assert ended_rank["rows"][0]["user"]["user_id"] == u2_id
        assert ended_rank["rows"][0]["total_score"] == 80
        assert ended_rank["rows"][1]["user"]["user_id"] == u1_id
        assert ended_rank["rows"][1]["total_score"] == 40


@pytest.mark.asyncio
async def test_ioi_best_submission_and_live_rank():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        admin_h, admin_id = await _make_user(ac, "ioi_adm", is_super_admin=True)
        u1_h, u1_id = await _make_user(ac, "ioi_u1")

        pid = await _create_prob("IOI_P1")

        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=30)
        end = now + timedelta(minutes=90)

        async with AsyncSessionLocal() as db:
            contest = Contest(
                title="IOI实时赛",
                visibility="public",
                rule_type="ioi",
                start_time=start,
                end_time=end,
                owner_id=admin_id,
            )
            db.add(contest)
            await db.flush()
            cid = contest.id
            db.add(ContestProblem(contest_id=cid, problem_id=pid, sort_order=0))
            db.add(ContestParticipant(contest_id=cid, user_id=u1_id))

            # u1 提交 3 次：30分 -> 90分 -> 50分（IOI 必须取历史最高 90 分！）
            db.add(Submission(contest_id=cid, user_id=u1_id, problem_id=pid, code="c1", language="cpp",
                              status="wrong_answer", score=30, created_at=start + timedelta(minutes=5)))
            db.add(Submission(contest_id=cid, user_id=u1_id, problem_id=pid, code="c2", language="cpp",
                              status="wrong_answer", score=90, created_at=start + timedelta(minutes=10)))
            db.add(Submission(contest_id=cid, user_id=u1_id, problem_id=pid, code="c3", language="cpp",
                              status="wrong_answer", score=50, created_at=start + timedelta(minutes=15)))
            await db.commit()

        # IOI 赛中榜单实时公开且取最高分 90
        r = await ac.get(f"/contests/{cid}/rank", headers=u1_h)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["rule_type"] == "ioi"
        assert data["is_frozen"] is False
        assert len(data["rows"]) == 1
        assert data["rows"][0]["total_score"] == 90
        assert data["rows"][0]["detail"]["A"]["score"] == 90
        assert data["rows"][0]["detail"]["A"]["tries"] == 3
