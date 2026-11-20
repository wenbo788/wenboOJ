"""题库列表可见性回归测试。

主题库列表只含「已进主题库」的题（is_official=True / P 编号）。
未公开题（U 题：草稿 / 待审核 / 被驳回）归作者自己的「我的题库」，
题目管理员通过审核队列（scope=review）查看，普通人一律看不到。

注：本文件旧约定是「题管默认在题库列表可见未公开题」，随「我的题库」需求
调整为「未公开题不再混进主题库列表」。
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.user import User


@pytest.mark.asyncio
async def test_unpublished_problem_out_of_library_but_visible_in_queue():
    """未公开题（U 题）不进主题库列表；审核队列与作者「我的题库」里可见。"""
    suffix = uuid.uuid4().hex[:8]
    admin, normal, pwd = f"pa_{suffix}", "pn_" + suffix, "supersecret1"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        for name in (admin, normal):
            r = await ac.post("/users", json={
                "username": name, "email": f"{name}@example.com", "password": pwd})
            assert r.status_code == 201, r.text
        async with AsyncSessionLocal() as db:
            u = (await db.execute(
                select(User).where(User.username == admin))).scalar_one()
            u.can_manage_problems = True
            await db.commit()

        r = await ac.post("/tokens", data={"username": admin, "password": pwd})
        admin_h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await ac.post("/tokens", data={"username": normal, "password": pwd})
        normal_h = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # 管理员建一道未公开题（默认 is_public=false）
        hidden_title = f"隐藏题_{suffix}"
        r = await ac.post("/problems", json={
            "title": hidden_title, "difficulty": "入门", "is_public": False,
        }, headers=admin_h)
        assert r.status_code in (200, 201), r.text
        pid = r.json()["id"]

        # 必须用 keyword 精确定位：题目列表按 id.asc() 排序且 page_size 上限 100，
        # 全量跑时前面测试造的题会把新建题挤出首页，直接取列表必然漏掉它。
        # 1) 主题库列表（题管视角也一视同仁）不再包含未公开题
        r = await ac.get(f"/problems?keyword={hidden_title}", headers=admin_h)
        assert r.status_code == 200, r.text
        assert all(p["id"] != pid for p in r.json()["items"]), \
            "未公开题（U 题）不该出现在主题库列表里"

        # 2) 审核队列（scope=review）里能看到，供管理
        r = await ac.get(f"/problems?keyword={hidden_title}&scope=review", headers=admin_h)
        assert r.status_code == 200, r.text
        queue = [p for p in r.json()["items"] if p["id"] == pid]
        assert len(queue) == 1, "审核队列必须能看到未公开题"

        # 3) 作者自己的「我的题库」里能看到（含未公开状态）
        r = await ac.get(f"/problems?keyword={hidden_title}&scope=mine", headers=admin_h)
        assert r.status_code == 200, r.text
        bank = [p for p in r.json()["items"] if p["id"] == pid]
        assert len(bank) == 1 and bank[0]["is_public"] is False

        # 4) 普通用户列表看不到
        r = await ac.get(f"/problems?keyword={hidden_title}", headers=normal_h)
        assert r.status_code == 200, r.text
        assert all(p["id"] != pid for p in r.json()["items"])
