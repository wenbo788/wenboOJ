"""工单增强回归测试：改标题、附件上传/删除与权限边界。"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.ticket import Ticket
from app.models.user import User

TXT = b"attachment content"


async def _make_user(ac: AsyncClient, tag: str, **perms) -> str:
    uname = f"tk_{tag}_{uuid.uuid4().hex[:6]}"
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


async def _login(ac: AsyncClient, username: str):
    r = await ac.post("/tokens", data={"username": username, "password": "supersecret1"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.asyncio
async def test_ticket_title_edit_and_attachments():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        creator = await _make_user(ac, "c")
        staff = await _make_user(ac, "s", can_manage_posts=True)
        other = await _make_user(ac, "o")
        ch = await _login(ac, creator)
        sh = await _login(ac, staff)
        oh = await _login(ac, other)

        # 创建工单
        r = await ac.post("/tickets", json={
            "title": "原始标题哦", "category": "consult", "content": "问题描述内容"}, headers=ch)
        assert r.status_code in (200, 201), r.text
        tid = r.json()["id"]

        # 旁观者不能改标题
        r = await ac.put(f"/tickets/{tid}/title", json={"title": "路人改标题"}, headers=oh)
        assert r.status_code == 403, r.text

        # 创建者改标题
        r = await ac.put(f"/tickets/{tid}/title", json={"title": "创建者改的新标题"}, headers=ch)
        assert r.status_code == 200, r.text

        # 标题过短 → 400
        r = await ac.put(f"/tickets/{tid}/title", json={"title": "短"}, headers=ch)
        assert r.status_code == 400, r.text

        # 标题与内容修改要留下动作记录（时间线横幅）
        r = await ac.put(f"/tickets/{tid}/description", json={"content": "更新后的问题描述"}, headers=ch)
        assert r.status_code == 200, r.text
        r = await ac.get(f"/tickets/{tid}", headers=ch)
        actions = [x["action_text"] for x in r.json()["replies"] if x["action_text"]]
        assert any(t.startswith("将标题从「原始标题哦」修改为") for t in actions), actions
        assert "修改了工单内容" in actions, actions

        # 描述附件（缺省挂到首条回复）
        r = await ac.post(f"/tickets/{tid}/attachments",
                          files={"file": (f"desc_{uuid.uuid4().hex[:4]}.txt", TXT, "text/plain")},
                          headers=ch)
        assert r.status_code == 200, r.text

        # 回复并挂附件
        r = await ac.post(f"/tickets/{tid}/replies", json={"content": "补充回复"}, headers=ch)
        assert r.status_code == 200, r.text
        reply_id = r.json()["reply_id"]
        r = await ac.post(f"/tickets/{tid}/attachments?reply_id={reply_id}",
                          files={"file": (f"reply_{uuid.uuid4().hex[:4]}.txt", TXT, "text/plain")},
                          headers=ch)
        assert r.status_code == 200, r.text
        att_id = r.json()["attachment"]["id"]

        # 禁传可执行文件
        r = await ac.post(f"/tickets/{tid}/attachments",
                          files={"file": ("evil.exe", b"MZ", "application/x-msdownload")},
                          headers=ch)
        assert r.status_code == 400, r.text

        # 详情里附件齐全
        r = await ac.get(f"/tickets/{tid}", headers=oh)
        assert r.status_code == 200, r.text
        detail = r.json()
        assert len(detail["description_attachments"]) == 1
        assert detail["replies"][0]["attachments"]
        target = next(x for x in detail["replies"] if x["id"] == reply_id)
        assert len(target["attachments"]) == 1

        # 旁观者不能删附件；管理员可以
        r = await ac.delete(f"/tickets/{tid}/attachments/{att_id}", headers=oh)
        assert r.status_code == 403, r.text
        r = await ac.delete(f"/tickets/{tid}/attachments/{att_id}", headers=sh)
        assert r.status_code == 200, r.text

        # 详情中该附件消失
        r = await ac.get(f"/tickets/{tid}", headers=oh)
        target = next(x for x in r.json()["replies"] if x["id"] == reply_id)
        assert all(a["id"] != att_id for a in target["attachments"])


@pytest.mark.asyncio
async def test_academic_ticket_flow():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        user = await _make_user(ac, "acad")
        h = await _login(ac, user)

        # 1. 创建学术建议工单
        r = await ac.post("/tickets", json={
            "title": "关于题目P1001数据范围的学术建议",
            "category": "academic",
            "content": "建议将P1001数据范围由1e9扩展至1e18，并说明高精度实现要求。",
        }, headers=h)
        assert r.status_code in (200, 201), r.text
        ticket = r.json()
        assert ticket["category"] == "academic"
        assert ticket["is_public"] is True
        tid = ticket["id"]

        # 2. 详情展示
        r = await ac.get(f"/tickets/{tid}", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["category"] == "academic"

        # 3. 按学术建议类别筛选
        r = await ac.get("/tickets?scope=all&category=academic", headers=h)
        assert r.status_code == 200, r.text
        items = r.json()["tickets"]
        assert any(t["id"] == tid and t["category"] == "academic" for t in items)

        # 4. 创建题目投递工单已被移除，直接返回 422 校验失败
        r = await ac.post("/tickets", json={
            "title": "新题投递申请：A+B Problem 强化版",
            "category": "problem_submit",
            "content": "附带时空限制与标程测试数据，申请投递公开题库审核。",
        }, headers=h)
        assert r.status_code in (403, 422), r.text

        # 5. 创建题目内容工单
        r = await ac.post("/tickets", json={
            "title": "P1002 样例题面描述修正",
            "category": "problem_content",
            "content": "题目描述中样例输入的格式缺少换行符，请核对修正。",
        }, headers=h)
        assert r.status_code in (200, 201), r.text
        assert r.json()["category"] == "problem_content"


@pytest.mark.asyncio
async def test_problem_submit_ticket_deprecated():
    """验证题目投递工单板块已被删除并下线。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        user_name = await _make_user(ac, "pst_dep")
        h = await _login(ac, user_name)

        # 1. 尝试访问已下线的投题门槛查询接口 -> 404 / 422（路由不存在或无法匹配到整型 ticket_id）
        r = await ac.get("/tickets/problem-submit-eligibility", headers=h)
        assert r.status_code in (404, 422)

        # 2. 尝试提交题目投递工单 -> 422 或 403 被拒绝
        r = await ac.post("/tickets", json={
            "title": "尝试投递入门题",
            "category": "problem_submit",
            "content": "题面内容描述超过五个字符",
        }, headers=h)
        assert r.status_code in (403, 422)


@pytest.mark.asyncio
async def test_ticket_assigned_and_unassigned_views():
    """工单「我负责的」「待认领」视图：仅管理员可见、按责任人与未完结状态过滤。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        creator = await _make_user(ac, "tc")
        staff = await _make_user(ac, "ts", can_manage_posts=True)
        ch = await _login(ac, creator)
        sh = await _login(ac, staff)
        staff_id = (await ac.get("/auth/me", headers=sh)).json()["id"]

        async def _new(title: str) -> int:
            r = await ac.post("/tickets", json={
                "title": title, "category": "consult", "content": "内容描述文本"}, headers=ch)
            assert r.status_code in (200, 201), r.text
            return r.json()["id"]

        assigned_tid = await _new("指派给自己的未完结工单")
        unassigned_tid = await _new("等待认领的未完结工单")
        resolved_tid = await _new("无责任人但已完结的工单")

        # 指派第一张给自己
        r = await ac.put(f"/tickets/{assigned_tid}/assign",
                         json={"assignee_id": staff_id}, headers=sh)
        assert r.status_code == 200, r.text

        # 第三张置为已完成
        r = await ac.put(f"/tickets/{resolved_tid}/status",
                         json={"status": "resolved"}, headers=sh)
        assert r.status_code == 200, r.text

        # 我负责的：包含指派给自己且未完结的，排除未指派与已完结
        r = await ac.get("/tickets?scope=assigned&page_size=100", headers=sh)
        assert r.status_code == 200, r.text
        ids = {t["id"] for t in r.json()["tickets"]}
        assert assigned_tid in ids
        assert unassigned_tid not in ids
        assert resolved_tid not in ids

        # 待认领：包含无责任人且未完结的，排除已指派与已完结
        r = await ac.get("/tickets?scope=unassigned&page_size=100", headers=sh)
        assert r.status_code == 200, r.text
        ids = {t["id"] for t in r.json()["tickets"]}
        assert unassigned_tid in ids
        assert assigned_tid not in ids
        assert resolved_tid not in ids

        # 非管理员访问两个新视图 → 403
        r = await ac.get("/tickets?scope=assigned", headers=ch)
        assert r.status_code == 403, r.text
        r = await ac.get("/tickets?scope=unassigned", headers=ch)
        assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_ticket_self_close():
    """测试创建者自关工单及权限边界（含已完成状态下自关）。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        creator = await _make_user(ac, "c_sc")
        staff = await _make_user(ac, "s_sc", can_manage_posts=True)
        other = await _make_user(ac, "o_sc")
        ch = await _login(ac, creator)
        sh = await _login(ac, staff)
        oh = await _login(ac, other)

        # 1. 创建者自关 pending 工单
        r = await ac.post("/tickets", json={
            "title": "待自关工单1", "category": "consult", "content": "问题详细描述内容1"}, headers=ch)
        tid1 = r.json()["id"]

        # 路人无法关闭
        r = await ac.put(f"/tickets/{tid1}/status", json={"status": "closed"}, headers=oh)
        assert r.status_code == 403

        # 创建者自关成功
        r = await ac.put(f"/tickets/{tid1}/status", json={"status": "closed"}, headers=ch)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "closed"

        # 验证回复中 is_staff 为 False
        r = await ac.get(f"/tickets/{tid1}", headers=ch)
        close_action = next(x for x in r.json()["replies"] if x["action_text"] == "已关闭")
        assert close_action["is_staff"] is False

        # 已经关闭的工单不可再次自关
        r = await ac.put(f"/tickets/{tid1}/status", json={"status": "closed"}, headers=ch)
        assert r.status_code == 403
        assert "工单已完结" in r.json()["detail"]

        # 2. 管理员将工单设为已完成（resolved），创建者仍可自关
        r = await ac.post("/tickets", json={
            "title": "待自关工单2", "category": "consult", "content": "问题详细描述内容2"}, headers=ch)
        tid2 = r.json()["id"]

        r = await ac.put(f"/tickets/{tid2}/status", json={"status": "resolved"}, headers=sh)
        assert r.status_code == 200

        # 创建者自关 resolved 工单成功
        r = await ac.put(f"/tickets/{tid2}/status", json={"status": "closed"}, headers=ch)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "closed"

        # 3. 管理员作为创建者自关自己的工单
        r = await ac.post("/tickets", json={
            "title": "管理员自己提的工单", "category": "bug", "content": "管理员提的工单内容测试"}, headers=sh)
        tid3 = r.json()["id"]
        r = await ac.put(f"/tickets/{tid3}/status", json={"status": "closed"}, headers=sh)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "closed"



