"""关闭题目题解提交通道功能测试。

测试覆盖：
1. 题目默认允许提交题解（allow_solution_submission=True）；
2. 管理员可切换/指定题解通道开关（toggle-solution-submission 与 PUT /problems/{id}）；
3. 普通用户不可切换题解通道；
4. 题解通道关闭后：
   - 普通用户提交「题解」分类关联该题被拒绝（400，提示“因为题目做法足够充分或题目过于简单已关闭题解通道。”）；
   - 普通用户发布其他分类文章不受影响；
   - 普通用户修改文章为「题解」关联该题被拒绝；
   - 普通用户对该题题解申请全站推荐被拒绝；
   - 管理员/题目管理员不受限制，可正常提交与处理题解；
5. 题解通道重新开启后，普通用户恢复正常提交。
"""

import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.problem import Problem, REVIEW_APPROVED
from app.models.user import User


async def _register_and_login(ac: AsyncClient, *, is_admin: bool = False, can_manage_problems: bool = False) -> tuple[dict[str, str], int, str]:
    suffix = uuid.uuid4().hex[:8]
    username = f"user_{suffix}"
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

    if is_admin or can_manage_problems:
        async with AsyncSessionLocal() as db:
            u = await db.get(User, user_id)
            assert u is not None
            if is_admin:
                u.is_admin = True
                u.can_manage_problems = True
            if can_manage_problems:
                u.can_manage_problems = True
            await db.commit()

    return headers, user_id, username


async def _create_problem(title: str, allow_solution_submission: bool = True) -> Problem:
    async with AsyncSessionLocal() as db:
        p = Problem(
            title=title,
            difficulty="入门",
            description="题目测试描述",
            is_public=True,
            review_status=REVIEW_APPROVED,
            allow_solution_submission=allow_solution_submission,
        )
        db.add(p)
        await db.commit()
        await db.refresh(p)
        return p


@pytest.mark.asyncio
async def test_problem_solution_submission_toggle_and_restriction():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        admin_headers, admin_id, _ = await _register_and_login(ac, is_admin=True)
        user_headers, user_id, _ = await _register_and_login(ac, is_admin=False)

        problem = await _create_problem("经典入门题 A+B")
        p_id = problem.id
        p_code = problem.problem_number

        # 1. 验证获取题目详情，默认 allow_solution_submission 为 True
        r_get = await ac.get(f"/problems/{p_id}", headers=user_headers)
        assert r_get.status_code == 200
        assert r_get.json()["allow_solution_submission"] is True

        # 2. 普通用户尝试切换通道，应返回 403 Forbidden
        r_toggle_user = await ac.post(f"/problems/{p_id}/toggle-solution-submission", headers=user_headers)
        assert r_toggle_user.status_code == 403

        # 3. 管理员切换通道关闭
        r_toggle_admin = await ac.post(f"/problems/{p_id}/toggle-solution-submission", headers=admin_headers, json={"allow": False})
        assert r_toggle_admin.status_code == 200
        assert r_toggle_admin.json()["allow_solution_submission"] is False

        # 验证详情中已为 False
        r_get2 = await ac.get(f"/problems/{p_id}", headers=user_headers)
        assert r_get2.json()["allow_solution_submission"] is False

        # 4. 普通用户提交该题的题解，应被拦截（400），且提示明确原因
        r_sol_fail = await ac.post("/articles", headers=user_headers, json={
            "title": "我的思路题解",
            "content": "直接使用 print(a+b) 即可通过...",
            "category": "题解",
            "problem_code": p_code,
        })
        assert r_sol_fail.status_code == 400
        assert "因为题目做法足够充分或题目过于简单已关闭题解通道。" in r_sol_fail.json()["detail"]

        # 5. 普通用户提交非题解分类（如“算法理论”），即使关联该题也不受阻拦
        r_algo_ok = await ac.post("/articles", headers=user_headers, json={
            "title": "关于加法器的原理解析",
            "content": "深入解析加法器的硬件逻辑...",
            "category": "算法理论",
            "problem_code": p_code,
        })
        assert r_algo_ok.status_code == 201
        article_id = r_algo_ok.json()["id"]

        # 6. 普通用户试图将该文章修改为“题解”分类，应被拦截
        r_update_fail = await ac.put(f"/articles/{article_id}", headers=user_headers, json={
            "category": "题解",
            "apply_recommend": True,
        })
        assert r_update_fail.status_code == 400
        assert "因为题目做法足够充分或题目过于简单已关闭题解通道。" in r_update_fail.json()["detail"]

        # 7. 管理员提交该题题解，可以正常绕过限制
        r_admin_sol = await ac.post("/articles", headers=admin_headers, json={
            "title": "官方题解：A+B Problem",
            "content": "管理员编写的权威标程与题解...",
            "category": "题解",
            "problem_code": p_code,
            "apply_recommend": True,
        })
        assert r_admin_sol.status_code == 201
        admin_art_id = r_admin_sol.json()["id"]
        assert r_admin_sol.json()["problem_id"] == p_id

        # 8. 管理员重新打开题解提交通道
        r_toggle_reopen = await ac.post(f"/problems/{p_id}/toggle-solution-submission", headers=admin_headers)
        assert r_toggle_reopen.status_code == 200
        assert r_toggle_reopen.json()["allow_solution_submission"] is True

        # 9. 通道开启后，普通用户再次提交题解，成功
        r_user_sol_ok = await ac.post("/articles", headers=user_headers, json={
            "title": "普通用户题解通过",
            "content": "通道已重开，顺利提交题解...",
            "category": "题解",
            "problem_code": p_code,
            "apply_recommend": False,
        })
        assert r_user_sol_ok.status_code == 201
        user_sol_id = r_user_sol_ok.json()["id"]

        # 10. 管理员通过 PUT /problems/{p_id} 关闭题解通道
        r_put_admin = await ac.put(f"/problems/{p_id}", headers=admin_headers, json={
            "allow_solution_submission": False,
        })
        assert r_put_admin.status_code == 200
        assert r_put_admin.json()["allow_solution_submission"] is False

        # 普通用户（非出题人）尝试通过 PUT /problems/{p_id} 修改，防探测返回 404
        r_put_user = await ac.put(f"/problems/{p_id}", headers=user_headers, json={
            "allow_solution_submission": True,
        })
        assert r_put_user.status_code == 404

        # 11. 在通道关闭时，普通用户对其已创建的题解调用 apply-recommend 应被拦截
        r_apply_fail = await ac.post(f"/articles/{user_sol_id}/apply-recommend", headers=user_headers, json={
            "reason": "优质题解申请推荐",
        })
        assert r_apply_fail.status_code == 400
        assert "因为题目做法足够充分或题目过于简单已关闭题解通道。" in r_apply_fail.json()["detail"]
