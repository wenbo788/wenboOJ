"""文章题解分类关联题号与全站推荐审核流程测试。

测试流程：
1. 普通用户发布「题解」分类文章必须指定题号；
2. 题解发布后默认未推荐（is_recommended=False）；
3. 题目题解接口（GET /articles?problem_id=X）在审核通过前，普通访客不可见，作者可见；
4. 作者申请全站推荐（POST /articles/{id}/apply-recommend）；
5. 管理员查看待审核推荐列表（GET /articles/recommend/pending）；
6. 管理员审核通过推荐（POST /articles/{id}/review-recommend, action=approve）；
7. 审核通过后，文章广场默认可见，题目题解接口可见（全站推荐生效）；
8. 管理员驳回推荐（POST /articles/{id}/review-recommend, action=reject）。
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.problem import Problem, REVIEW_APPROVED
from app.models.user import User


async def _register_and_login(ac: AsyncClient, *, is_admin: bool = False) -> tuple[dict[str, str], int, str]:
    suffix = uuid.uuid4().hex[:8]
    username = f"sol_{suffix}"
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
            await db.commit()

    return headers, user_id, username


async def _create_problem(title: str) -> Problem:
    async with AsyncSessionLocal() as db:
        p = Problem(
            title=title,
            difficulty="入门",
            description="描述内容",
            is_public=True,
            review_status=REVIEW_APPROVED,
        )
        db.add(p)
        await db.commit()
        await db.refresh(p)
        return p


@pytest.mark.asyncio
async def test_solution_article_and_recommendation_flow():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        admin_headers, admin_id, admin_name = await _register_and_login(ac, is_admin=True)
        user_headers, user_id, user_name = await _register_and_login(ac, is_admin=False)
        visitor_headers, visitor_id, _ = await _register_and_login(ac, is_admin=False)

        problem = await _create_problem("A+B Problem (测试题)")
        p_code = problem.problem_number
        p_id = problem.id

        # 1. 尝试不带题号发布「题解」分类文章，应拦截报错 400
        r_fail = await ac.post("/articles", headers=user_headers, json={
            "title": "非法题解没有题号",
            "content": "解题思路内容...",
            "category": "题解",
        })
        assert r_fail.status_code == 400
        assert "必须指定关联题号" in r_fail.json()["detail"]

        # 2. 正常发布题解文章，带上题号，并勾选申请全站推荐
        r_create = await ac.post("/articles", headers=user_headers, json={
            "title": f"题解：{problem.title}",
            "content": "这是一篇高质量题解，使用模拟算法复杂度 O(1)。",
            "category": "题解",
            "problem_code": p_code,
            "apply_recommend": True,
            "recommend_reason": "排版工整，包含复杂度分析与多语言代码",
        })
        assert r_create.status_code == 201, r_create.text
        art = r_create.json()
        art_id = art["id"]
        assert art["category"] == "题解"
        assert art["problem_id"] == p_id
        assert art["problem_code"] == p_code
        assert art["problem_title"] == "A+B Problem (测试题)"
        assert art["is_recommended"] is False
        assert art["recommend_status"] == "pending"
        assert art["recommend_reason"] == "排版工整，包含复杂度分析与多语言代码"

        # 3. 此时查看题目题解列表：
        # - 未登录访客或普通用户（非作者）查看，因为尚未通过全站推荐，查不到该题解
        r_vis_list = await ac.get(f"/articles?problem_id={p_id}", headers=visitor_headers)
        assert r_vis_list.status_code == 200
        assert len(r_vis_list.json()["items"]) == 0

        # - 作者本人查看题目的题解，可以看到自己处于 pending 状态的题解稿件
        r_author_list = await ac.get(f"/articles?problem_code={p_code}", headers=user_headers)
        assert r_author_list.status_code == 200
        assert len(r_author_list.json()["items"]) == 1
        assert r_author_list.json()["items"][0]["id"] == art_id
        assert r_author_list.json()["items"][0]["recommend_status"] == "pending"

        # 4. 管理员查看待审核推荐申请列表
        r_pending = await ac.get("/articles/recommend/pending", headers=admin_headers)
        assert r_pending.status_code == 200
        pending_items = r_pending.json()["items"]
        assert any(item["id"] == art_id for item in pending_items)

        # 5. 普通用户尝试直接调用审核接口，应报 403
        r_deny = await ac.post(f"/articles/{art_id}/review-recommend", headers=user_headers, json={
            "action": "approve"
        })
        assert r_deny.status_code == 403

        # 6. 管理员审核通过该题解的全站推荐
        r_approve = await ac.post(f"/articles/{art_id}/review-recommend", headers=admin_headers, json={
            "action": "approve",
            "reason": "格式规范，论述清晰，准予全站推荐",
        })
        assert r_approve.status_code == 200, r_approve.text
        approved_art = r_approve.json()
        assert approved_art["is_recommended"] is True
        assert approved_art["recommend_status"] == "approved"
        assert approved_art["reviewer_username"] == admin_name

        # 6.1 验证作者获得了全站推荐奖励贡献值（20 点）
        async with AsyncSessionLocal() as db:
            author_u = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
            assert author_u.contribution == 20

        # 7. 审核通过后验证：
        # 7.1 文章广场公共流中出现该题解
        r_plaza = await ac.get("/articles?is_recommended=true")
        assert r_plaza.status_code == 200
        assert any(item["id"] == art_id for item in r_plaza.json()["items"])

        # 7.2 其他普通用户访问题目题解区，可以看到该题解
        r_vis_approved = await ac.get(f"/articles?problem_id={p_id}", headers=visitor_headers)
        assert r_vis_approved.status_code == 200
        assert len(r_vis_approved.json()["items"]) == 1
        assert r_vis_approved.json()["items"][0]["id"] == art_id
        assert r_vis_approved.json()["items"][0]["is_recommended"] is True

        # 8. 管理员取消推荐测试：贡献值应相应扣除
        r_cancel = await ac.post(f"/articles/{art_id}/review-recommend", headers=admin_headers, json={
            "action": "cancel",
        })
        assert r_cancel.status_code == 200
        assert r_cancel.json()["is_recommended"] is False
        async with AsyncSessionLocal() as db:
            author_u = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
            assert author_u.contribution == 0

        # 8.1 再次通过推荐，贡献值恢复
        r_approve2 = await ac.post(f"/articles/{art_id}/review-recommend", headers=admin_headers, json={
            "action": "approve",
        })
        assert r_approve2.status_code == 200
        async with AsyncSessionLocal() as db:
            author_u = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
            assert author_u.contribution == 20

        # 8.2 删除已推荐文章：贡献值扣回
        r_del = await ac.delete(f"/articles/{art_id}", headers=admin_headers)
        assert r_del.status_code == 200
        async with AsyncSessionLocal() as db:
            author_u = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
            assert author_u.contribution == 0

        # 9. 管理员驳回测试：再发布一篇并测试驳回
        r_create2 = await ac.post("/articles", headers=user_headers, json={
            "title": f"题解2：{problem.title}",
            "content": "就一行代码代码看不懂算了",
            "category": "题解",
            "problem_id": p_id,
        })
        assert r_create2.status_code == 201
        art2_id = r_create2.json()["id"]

        # 作者申请全站推荐
        r_apply = await ac.post(f"/articles/{art2_id}/apply-recommend", headers=user_headers, json={
            "reason": "求推荐"
        })
        assert r_apply.status_code == 200
        assert r_apply.json()["recommend_status"] == "pending"

        # 管理员驳回
        r_reject = await ac.post(f"/articles/{art2_id}/review-recommend", headers=admin_headers, json={
            "action": "reject",
            "reason": "内容过简，缺少解题思路与复杂度分析说明",
        })
        assert r_reject.status_code == 200
        assert r_reject.json()["is_recommended"] is False
        assert r_reject.json()["recommend_status"] == "rejected"
        assert r_reject.json()["recommend_reason"] == "内容过简，缺少解题思路与复杂度分析说明"
