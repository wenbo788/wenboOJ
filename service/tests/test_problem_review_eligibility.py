"""题目审核体系：投题人 AC 题数门槛测试。

规则：
- 投递者在主题库通过的大于等于投递难度的题目需 >= 15 道才允许投递公开审核。
- 0 AC 用户投递公开题拦截（403），但允许保存为草稿（is_public=False）。
- 达标用户允许投递公开题，进入 pending 状态等待审核。
- 管理员具备题目管理权限，免检直接 approved。
- 管理员在审核后台审批（action=approve）时，校验出题人是否达到该难度的 15 题门槛。
"""

import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.user import User


async def _make_user(ac: AsyncClient, prefix: str, can_manage_problems: bool = False) -> tuple[str, dict]:
    uid = uuid.uuid4().hex[:6]
    name = f"{prefix}_{uid}"
    pwd = "password123"
    r = await ac.post("/users", json={"username": name, "email": f"{name}@ex.com", "password": pwd})
    assert r.status_code == 201

    if can_manage_problems:
        async with AsyncSessionLocal() as db:
            u = (await db.execute(select(User).where(User.username == name))).scalar_one()
            u.can_manage_problems = True
            await db.commit()

    r = await ac.post("/tokens", data={"username": name, "password": pwd})
    token = r.json()["access_token"]
    return name, {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_problem_review_eligibility_flow():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        normal_name, normal_h = await _make_user(ac, "author_norm")
        admin_name, admin_h = await _make_user(ac, "admin_mgr", can_manage_problems=True)

        # 1. 查询当前用户投题资格
        r = await ac.get("/problems/submit-eligibility", headers=normal_h)
        assert r.status_code == 200, r.text
        elig = r.json()
        assert elig["can_bypass"] is False
        assert elig["threshold"] == 15
        assert elig["stats"]["入门"]["qualified"] is False
        assert elig["stats"]["普及"]["qualified"] is False

        # 管理员查询免检
        r = await ac.get("/problems/submit-eligibility", headers=admin_h)
        assert r.status_code == 200
        assert r.json()["can_bypass"] is True

        # 2. 0 AC 普通用户尝试创建公开题目 -> 403 拦截
        r = await ac.post("/problems", json={
            "title": "未达标入门题",
            "difficulty": "入门",
            "is_public": True,
        }, headers=normal_h)
        assert r.status_code == 403, r.text
        assert "需在主题库通过至少 15 道" in r.json()["detail"]

        # 3. 0 AC 普通用户创建隐藏草稿题 -> 成功
        r = await ac.post("/problems", json={
            "title": "草稿入门题",
            "difficulty": "入门",
            "is_public": False,
        }, headers=normal_h)
        assert r.status_code in (200, 201), r.text
        pid = r.json()["id"]
        assert r.json()["review_status"] == "draft"

        # 4. 0 AC 普通用户尝试将草稿修改为公开 -> 403 拦截
        r = await ac.put(f"/problems/{pid}", json={
            "is_public": True,
        }, headers=normal_h)
        assert r.status_code == 403, r.text
        assert "需在主题库通过至少 15 道" in r.json()["detail"]

        # 5. 管理员 0 AC 投递黑题 -> 免检直接 approved
        r = await ac.post("/problems", json={
            "title": "管理员免检黑题",
            "difficulty": "NOI/NOI+/CTSC",
            "is_public": True,
        }, headers=admin_h)
        assert r.status_code in (200, 201), r.text
        assert r.json()["review_status"] == "approved"

        # 6. 为普通用户注入 15 道「普及」（黄）题目并 AC
        async with AsyncSessionLocal() as db:
            u = (await db.execute(select(User).where(User.username == normal_name))).scalar_one()
            user_id = u.id
            for i in range(15):
                prob = Problem(
                    title=f"测试普及题_{i}_{uuid.uuid4().hex[:4]}",
                    difficulty="普及",
                    is_public=True,
                    review_status="approved",
                )
                db.add(prob)
                await db.flush()
                sub = Submission(
                    problem_id=prob.id,
                    user_id=user_id,
                    code="int main(){}",
                    language="cpp",
                    status="accepted",
                    score=100,
                )
                db.add(sub)
            await db.commit()

        # 7. 再次查询达标状态：普及、普及-、入门均已达标；普及+/提高- 未达标
        r = await ac.get("/problems/submit-eligibility", headers=normal_h)
        assert r.status_code == 200
        stats = r.json()["stats"]
        assert stats["入门"]["qualified"] is True
        assert stats["普及-"]["qualified"] is True
        assert stats["普及"]["qualified"] is True
        assert stats["普及+/提高-"]["qualified"] is False

        # 8. 试图投递「普及+/提高-」（绿）：被拦截（403）
        r = await ac.post("/problems", json={
            "title": "尝试投递绿题",
            "difficulty": "普及+/提高-",
            "is_public": True,
        }, headers=normal_h)
        assert r.status_code == 403
        assert "普及+/提高-" in r.json()["detail"]

        # 9. 投递「普及」（黄）：成功进入 pending 状态
        r = await ac.post("/problems", json={
            "title": "达标投递普及题",
            "difficulty": "普及",
            "is_public": True,
        }, headers=normal_h)
        assert r.status_code in (200, 201), r.text
        yellow_pid = r.json()["id"]
        assert r.json()["review_status"] == "pending"

        # 10. 管理员在后台审核该达标题目 -> approve 成功
        r = await ac.post(f"/problems/{yellow_pid}/review", json={
            "action": "approve"
        }, headers=admin_h)
        assert r.status_code == 200, r.text
        assert r.json()["review_status"] == "approved"
        assert r.json()["is_public"] is True

        # 11. 模拟一个出题人未达标的待审核题目：管理员审核时应当被 400 拦截
        another_norm_name, _ = await _make_user(ac, "author_zero")
        async with AsyncSessionLocal() as db:
            u_zero = (await db.execute(select(User).where(User.username == another_norm_name))).scalar_one()
            zero_pid_obj = Problem(
                title="未达标强行pending题",
                difficulty="提高",
                is_public=False,
                review_status="pending",
                author_id=u_zero.id,
            )
            db.add(zero_pid_obj)
            await db.commit()
            await db.refresh(zero_pid_obj)
            zero_pid = zero_pid_obj.id

        r = await ac.post(f"/problems/{zero_pid}/review", json={
            "action": "approve"
        }, headers=admin_h)
        assert r.status_code == 400
        assert "未达到投题门槛" in r.json()["detail"]
