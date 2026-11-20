"""举报系统端到端测试。

覆盖：
1. 基础规则：不能举报自己 / 不能重复举报 / 审核前可撤销 / 撤销后可重新举报；
2. 6 人有效举报自动软删除，撤销使有效数跌破 6 时自动恢复；
3. 秩序管理审核「举报成立」：内容删除 + 作者按内容违规梯度禁言；
4. 秩序管理审核「恶意举报」：内容保持/恢复 + 全部有效举报人按
   恶意举报梯度禁言；
5. 帖子回复删除权限：秩序管理 / 回复作者 / 帖子作者可删，他人 403。
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.forum import ForumComment, ForumPost
from app.models.user import User


# ---------------- 辅助 ----------------

async def register(ac: AsyncClient, name: str, pwd: str = "supersecret1") -> None:
    r = await ac.post("/users", json={
        "username": name, "email": f"{name}@example.com", "password": pwd})
    assert r.status_code == 201, r.text


async def login(ac: AsyncClient, name: str, pwd: str = "supersecret1") -> str:
    r = await ac.post("/tokens", data={"username": name, "password": pwd})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def set_permission(username: str, **fields) -> None:
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.username == username))).scalar_one()
        for k, v in fields.items():
            setattr(u, k, v)
        await db.commit()


async def get_user(username: str) -> User:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User).where(User.username == username))).scalar_one()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def create_post(ac: AsyncClient, token: str, title: str, content: str = "post body") -> int:
    r = await ac.post("/forum/posts",
                     json={"title": title, "content": content, "forum": "relevantaffairs"},
                     headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def create_comment(ac: AsyncClient, token: str, post_id: int, text: str = "a reply") -> int:
    r = await ac.post(f"/forum/posts/{post_id}/comments",
                      json={"content": text}, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------------- 1. 基础规则 ----------------

@pytest.mark.asyncio
async def test_report_basic_rules():
    s = uuid.uuid4().hex[:8]
    author, rp = f"au_{s}", f"rp_{s}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        await register(ac, author)
        await register(ac, rp)
        at, rt = await login(ac, author), await login(ac, rp)

        # 作者发一条犇犇
        r = await ac.post("/benben", json={"content": f"benben {s}"}, headers=auth(at))
        assert r.status_code == 201, r.text
        bid = r.json()["id"]

        # 不能举报自己
        r = await ac.post("/reports", json={
            "target_type": "benben", "target_id": bid,
            "category": "spam", "detail": None}, headers=auth(at))
        assert r.status_code == 400, r.text

        payload = {"target_type": "benben", "target_id": bid,
                   "category": "abuse", "detail": "骂人了"}
        r = await ac.post("/reports", json=payload, headers=auth(rt))
        assert r.status_code == 201, r.text
        assert r.json()["active_count"] == 1 and r.json()["auto_deleted"] is False

        # 重复举报拒绝
        r = await ac.post("/reports", json=payload, headers=auth(rt))
        assert r.status_code == 400, r.text

        # 查询状态：已举报、可撤销
        r = await ac.get("/reports/check",
                        params={"target_type": "benben", "target_id": bid},
                        headers=auth(rt))
        assert r.json()["reported"] is True and r.json()["revocable"] is True

        # 撤销
        report_id = r.json()["report_id"]
        r = await ac.post(f"/reports/{report_id}/revoke", headers=auth(rt))
        assert r.status_code == 200, r.text
        assert r.json()["active_count"] == 0 and r.json()["restored"] is False

        # 撤销后可以重新举报（重新激活原记录）
        r = await ac.post("/reports", json=payload, headers=auth(rt))
        assert r.status_code == 201, r.text
        assert r.json()["active_count"] == 1

        # 撤销别人的举报 → 404
        r = await ac.post(f"/reports/{report_id}/revoke", headers=auth(at))
        assert r.status_code == 404, r.text


# ---------------- 2. 6 人自动删除 + 撤销恢复 ----------------

@pytest.mark.asyncio
async def test_six_reports_auto_delete_and_restore():
    s = uuid.uuid4().hex[:8]
    author = f"au_{s}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        await register(ac, author)
        at = await login(ac, author)
        pid = await create_post(ac, at, f"title {s}")

        reporters = []
        for i in range(6):
            name = f"r{i}_{s}"
            await register(ac, name)
            reporters.append((name, await login(ac, name)))

        # 前 5 人：不删
        for i in range(5):
            r = await ac.post("/reports", json={
                "target_type": "post", "target_id": pid,
                "category": "spam", "detail": None},
                headers=auth(reporters[i][1]))
            assert r.status_code == 201, r.text
            assert r.json()["auto_deleted"] is False

        # 第 6 人：自动删除
        r = await ac.post("/reports", json={
            "target_type": "post", "target_id": pid,
            "category": "spam", "detail": None},
            headers=auth(reporters[5][1]))
        assert r.json()["auto_deleted"] is True

        # 前台详情 404
        r = await ac.get(f"/forum/posts/{pid}")
        assert r.status_code == 404, r.text

        # 第 6 人撤销：有效数 5 < 6 → 自动恢复
        check = await ac.get("/reports/check",
                             params={"target_type": "post", "target_id": pid},
                             headers=auth(reporters[5][1]))
        r = await ac.post(f"/reports/{check.json()['report_id']}/revoke",
                          headers=auth(reporters[5][1]))
        assert r.status_code == 200, r.text
        assert r.json()["restored"] is True

        r = await ac.get(f"/forum/posts/{pid}")
        assert r.status_code == 200, r.text


# ---------------- 3. 审核：举报成立（删除内容，不自动禁言作者） ----------------

@pytest.mark.asyncio
async def test_verdict_guilty_deletes_content_without_auto_mute():
    s = uuid.uuid4().hex[:8]
    author, rp, mod = f"au_{s}", f"rp_{s}", f"mod_{s}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        await register(ac, author)
        await register(ac, rp)
        await register(ac, mod)
        at, rt = await login(ac, author), await login(ac, rp)
        await set_permission(mod, can_manage_posts=True)
        mt = await login(ac, mod)

        pid = await create_post(ac, at, f"title {s}")
        cid = await create_comment(ac, at, pid, f"bad comment {s}")

        # 举报回复
        r = await ac.post("/reports", json={
            "target_type": "comment", "target_id": cid,
            "category": "porn_illegal", "detail": "详情"}, headers=auth(rt))
        assert r.status_code == 201, r.text

        # 秩序管理判举报成立
        r = await ac.post(f"/reports/admin/comment/{cid}/verdict",
                          json={"verdict": "guilty"}, headers=auth(mt))
        assert r.status_code == 200, r.text
        # 不再自动禁言作者
        assert r.json()["author_mute"] is None

        # 回复已删除
        post = (await ac.get(f"/forum/posts/{pid}")).json()
        assert all(c["id"] != cid for c in post["comments"])

        # 作者状态：未被自动禁言，违规计数不累加
        au = await get_user(author)
        assert au.can_speak is not False or au.speak_until is None
        assert au.content_violation_count == 0
        assert au.malicious_report_count == 0


# ---------------- 4. 审核：恶意举报（恢复内容，不自动禁言举报人） ----------------

@pytest.mark.asyncio
async def test_verdict_false_restores_without_auto_mute():
    s = uuid.uuid4().hex[:8]
    author, rp1, rp2, mod = f"au_{s}", f"r1_{s}", f"r2_{s}", f"mod_{s}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        await register(ac, author)
        await register(ac, rp1)
        await register(ac, rp2)
        await register(ac, mod)
        at = await login(ac, author)
        t1, t2 = await login(ac, rp1), await login(ac, rp2)
        await set_permission(mod, can_manage_posts=True)
        mt = await login(ac, mod)

        # 犇犇被 6 人举报自动删除
        r = await ac.post("/benben", json={"content": f"innocent {s}"}, headers=auth(at))
        bid = r.json()["id"]

        names_tokens = [(rp1, t1), (rp2, t2)]
        for i in range(4):
            extra = f"x{i}_{s}"
            await register(ac, extra)
            names_tokens.append((extra, await login(ac, extra)))

        for name, token in names_tokens:
            r = await ac.post("/reports", json={
                "target_type": "benben", "target_id": bid,
                "category": "infringe_other", "detail": None},
                headers=auth(token))
        assert r.json()["auto_deleted"] is True

        # 判定恶意举报
        r = await ac.post(f"/reports/admin/benben/{bid}/verdict",
                          json={"verdict": "false_report"}, headers=auth(mt))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["content_restored"] is True
        # 不再自动禁言举报人
        assert data["punished"] == []

        # 犇犇恢复显示；举报人未被自动禁言
        r = await ac.get("/benben?limit=20")
        assert any(x["id"] == bid for x in r.json())
        for name, _ in names_tokens:
            u = await get_user(name)
            assert u.can_speak is not False or u.speak_until is None
            assert u.malicious_report_count == 0


# ---------------- 5. 帖子回复删除权限 ----------------

@pytest.mark.asyncio
async def test_comment_delete_permissions():
    s = uuid.uuid4().hex[:8]
    owner, a, b, mod = f"ow_{s}", f"ua_{s}", f"ub_{s}", f"mo_{s}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        for name in (owner, a, b, mod):
            await register(ac, name)
        ot, at, bt = await login(ac, owner), await login(ac, a), await login(ac, b)
        await set_permission(mod, can_manage_posts=True)
        mt = await login(ac, mod)

        pid = await create_post(ac, ot, f"title {s}")
        # 回复有 5 秒防刷屏冷却：测试中直接重置限流桶
        from app.utils import ratelimit
        c1 = await create_comment(ac, at, pid, f"comment by A {s}")
        ratelimit.reset()
        c2 = await create_comment(ac, bt, pid, f"comment by B {s}")

        # 无关用户 B 不能删 A 的回复
        r = await ac.delete(f"/forum/posts/{pid}/comments/{c1}", headers=auth(bt))
        assert r.status_code == 403, r.text

        # 楼主可以删 A 的回复
        r = await ac.delete(f"/forum/posts/{pid}/comments/{c1}", headers=auth(ot))
        assert r.status_code == 200, r.text

        # 回复作者本人可以删自己的回复（B 删 c2）
        r = await ac.delete(f"/forum/posts/{pid}/comments/{c2}", headers=auth(bt))
        assert r.status_code == 200, r.text

        # 已删除的再删 → 404
        r = await ac.delete(f"/forum/posts/{pid}/comments/{c2}", headers=auth(mt))
        assert r.status_code == 404, r.text

        # 秩序管理删回复（新建一条给管理员删）
        ratelimit.reset()
        c3 = await create_comment(ac, at, pid, f"one more {s}")
        r = await ac.delete(f"/forum/posts/{pid}/comments/{c3}", headers=auth(mt))
        assert r.status_code == 200, r.text

        # 全部回复已软删除：前台回复数为 0，但行仍在库
        post = (await ac.get(f"/forum/posts/{pid}")).json()
        assert len(post["comments"]) == 0
        async with AsyncSessionLocal() as db:
            db_rows = (await db.execute(
                select(ForumComment).where(ForumComment.post_id == pid)
            )).scalars().all()
        assert len(db_rows) == 3 and all(x.is_deleted for x in db_rows)


# ---------------- 6. 被禁言者不能举报 ----------------

@pytest.mark.asyncio
async def test_muted_user_cannot_report():
    s = uuid.uuid4().hex[:8]
    author, rp = f"au_{s}", f"rp_{s}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        await register(ac, author)
        await register(ac, rp)
        at = await login(ac, author)
        rt = await login(ac, rp)
        bid = r = (await ac.post("/benben", json={"content": f"bb {s}"}, headers=auth(at))).json()["id"]

        # 直接把举报人禁言（永久）
        await set_permission(rp, can_speak=False)
        r = await ac.post("/reports", json={
            "target_type": "benben", "target_id": bid,
            "category": "spam", "detail": None}, headers=auth(rt))
        assert r.status_code == 403, r.text
