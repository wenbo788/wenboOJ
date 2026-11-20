"""Comprehensive tests for training list system (题单系统)."""

import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.core.database import AsyncSessionLocal
from app.models.problem import Problem
from app.models.user import User


async def _register_and_login(
    ac: AsyncClient, prefix: str, is_admin: bool = False
) -> tuple[dict, str, int]:
    suffix = uuid.uuid4().hex[:8]
    username = f"{prefix}_{suffix}"
    r = await ac.post(
        "/users",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "supersecret1",
        },
    )
    assert r.status_code == 201, r.text

    if is_admin:
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            user = (await db.execute(select(User).where(User.username == username))).scalar_one()
            user.is_admin = True
            await db.commit()

    r = await ac.post(
        "/tokens", data={"username": username, "password": "supersecret1"}
    )
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await ac.get("/auth/me", headers=headers)).json()
    return headers, username, me["id"]


@pytest.mark.asyncio
async def test_training_lifecycle():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        headers_user, user_name, user_id = await _register_and_login(ac, "usr")
        headers_admin, admin_name, admin_id = await _register_and_login(ac, "adm", is_admin=True)

        # 创建公开测试题目
        async with AsyncSessionLocal() as db:
            p = Problem(
                title="两数之和",
                description="计算 A + B",
                time_limit=1000,
                memory_limit=256,
                difficulty="普及-",
                is_public=True,
                author_id=admin_id,
            )
            db.add(p)
            await db.commit()
            await db.refresh(p)
            problem_id = p.id

        # 1. 普通用户在「我的」创建题单
        create_resp = await ac.post(
            "/trainings",
            headers=headers_user,
            json={
                "title": "动态规划入门",
                "description": "基础 DP 题单",
                "is_public": True,
                "problem_codes": [f"P{1000 + problem_id}"],
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        training_data = create_resp.json()
        training_id = training_data["id"]
        assert training_data["title"] == "动态规划入门"
        assert training_data["problem_count"] == 1
        assert training_data["is_featured"] is False

        # 2. 详情页可查看，并验证智能题号加题
        # 测试输入纯数字格式加题查重（已存在该题）
        dup_resp = await ac.post(
            f"/trainings/{training_id}/problems",
            headers=headers_user,
            json={"problem_code": str(1000 + problem_id)},
        )
        assert dup_resp.status_code == 400
        assert "已在题单中" in dup_resp.json()["detail"]

        # 3. 普通用户尝试加精选推荐 -> 403
        feat_fail = await ac.put(
            f"/trainings/{training_id}/feature",
            headers=headers_user,
            json={"is_featured": True},
        )
        assert feat_fail.status_code == 403

        # 4. 管理员设置推荐 -> 成功
        feat_succ = await ac.put(
            f"/trainings/{training_id}/feature",
            headers=headers_admin,
            json={"is_featured": True},
        )
        assert feat_succ.status_code == 200
        assert feat_succ.json()["is_featured"] is True

        # 5. 首页精选查询 featured_only=true
        feat_list = await ac.get("/trainings?featured_only=true")
        assert feat_list.status_code == 200
        items = feat_list.json()["items"]
        assert any(item["id"] == training_id for item in items)

        # 6. 「我的」题单筛选
        my_list = await ac.get(f"/trainings?owner_id={user_id}")
        assert my_list.status_code == 200
        assert any(item["id"] == training_id for item in my_list.json()["items"])

        # 7. 别名路由 /training 兼容性测试
        alias_detail = await ac.get(f"/training/{training_id}")
        assert alias_detail.status_code == 200
        assert alias_detail.json()["id"] == training_id

        # 8. 移除题目与删除题单
        rm_prob = await ac.delete(
            f"/trainings/{training_id}/problems/{problem_id}",
            headers=headers_user,
        )
        assert rm_prob.status_code == 200

        del_resp = await ac.delete(
            f"/trainings/{training_id}",
            headers=headers_user,
        )
        assert del_resp.status_code == 200


@pytest.mark.asyncio
async def test_training_scope_is_official_and_rejects_invalid():
    """官方/用户题单归属应在创建时落库，不随作者权限变化漂移；非法 scope 返回 400。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        admin_h, _, _ = await _register_and_login(ac, "scope_admin", is_admin=True)
        user_h, _, _ = await _register_and_login(ac, "scope_user")

        r = await ac.post(
            "/trainings",
            json={"title": "官方题单", "is_public": True},
            headers=admin_h,
        )
        assert r.status_code == 201, r.text
        official_id = r.json()["id"]
        assert r.json()["is_official"] is True
        assert r.json()["scope"] == "official"

        r = await ac.post(
            "/trainings",
            json={"title": "个人题单", "is_public": True},
            headers=user_h,
        )
        assert r.status_code == 201, r.text
        user_plan_id = r.json()["id"]
        assert r.json()["is_official"] is False

        official = (await ac.get("/trainings", params={"scope": "official"})).json()
        official_ids = {i["id"] for i in official["items"]}
        assert official_id in official_ids
        assert user_plan_id not in official_ids

        user_scope = (await ac.get("/trainings", params={"scope": "user"})).json()
        user_ids = {i["id"] for i in user_scope["items"]}
        assert user_plan_id in user_ids
        assert official_id not in user_ids

        # 管理员被撤权后，历史题单仍应留在 official（不漂移到 user）
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            admin_row = (await db.execute(
                select(User).where(User.username.like("scope_admin%"))
            )).scalars().first()
            assert admin_row is not None
            admin_row.is_admin = False
            await db.commit()

        after = (await ac.get("/trainings", params={"scope": "official"})).json()
        assert official_id in {i["id"] for i in after["items"]}
        after_user = (await ac.get("/trainings", params={"scope": "user"})).json()
        assert official_id not in {i["id"] for i in after_user["items"]}

        # 非法 scope 必须 400，不能静默返回全量
        bad = await ac.get("/trainings", params={"scope": "featured"})
        assert bad.status_code == 400, bad.text

        # 清理
        await ac.delete(f"/trainings/{official_id}", headers=admin_h)
        await ac.delete(f"/trainings/{user_plan_id}", headers=user_h)
