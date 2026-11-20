"""群聊：建群 / 邀请 / 群主与群管理 / 消息收发 / 撤回删除。

规则要点：
  1. 建群 → 201；群名必填；创建者自动成为群主
  2. 非成员不能查看、发消息（403/404）
  3. 群主可设管理员、可移除成员；群管理员可邀请但不可移他人
  4. 只有发送者可撤回/删除自己的消息
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


async def _register_and_login(ac: AsyncClient, prefix: str) -> tuple[dict, int]:
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
    r = await ac.post(
        "/tokens", data={"username": username, "password": "supersecret1"}
    )
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await ac.get("/auth/me", headers=headers)).json()
    return headers, me["id"]


async def _uid(ac: AsyncClient, headers: dict) -> int:
    """取该用户的用户编号（UID）——member_ids 按 user_number 列解析。"""
    return (await ac.get("/auth/me", headers=headers)).json()["user_number"]


@pytest.mark.asyncio
async def test_create_group_and_membership():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        owner, owner_id = await _register_and_login(ac, "gc")
        member, member_id = await _register_and_login(ac, "gc")
        outsider, _ = await _register_and_login(ac, "gc")

        # 群名必填
        r = await ac.post("/conversations", headers=owner, json={"type": "group", "title": "  "})
        assert r.status_code == 400, r.text

        # 建群：创建者自动为 owner，member 被加入
        r = await ac.post(
            "/conversations",
            headers=owner,
            json={"type": "group", "title": "测试群", "member_ids": [await _uid(ac, member)]},
        )
        assert r.status_code == 201, r.text
        conv_id = r.json()["id"]

        # 成员列表
        r = await ac.get(f"/conversations/{conv_id}", headers=owner)
        assert r.status_code == 200, r.text
        detail = r.json()
        assert detail["title"] == "测试群"
        roles = {m["user_id"]: m["role"] for m in detail["members"]}
        assert roles[owner_id] == "owner"
        assert roles[member_id] == "member"
        assert detail["member_count"] == 2

        # 非成员无权访问
        r = await ac.get(f"/conversations/{conv_id}", headers=outsider)
        assert r.status_code in (403, 404), r.text

        # 会话列表
        r = await ac.get("/conversations", headers=member)
        assert r.status_code == 200, r.text
        assert any(c["id"] == conv_id for c in r.json()["items"])


@pytest.mark.asyncio
async def test_invite_roles_and_remove():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        owner, owner_id = await _register_and_login(ac, "gc")
        admin, admin_id = await _register_and_login(ac, "gc")
        member, member_id = await _register_and_login(ac, "gc")
        extra, extra_id = await _register_and_login(ac, "gc")

        r = await ac.post(
            "/conversations",
            headers=owner,
            json={
                "type": "group",
                "title": "管理群",
                "member_ids": [await _uid(ac, admin), await _uid(ac, member)],
            },
        )
        conv_id = r.json()["id"]

        # 群主设 admin_a 为管理员
        r = await ac.put(
            f"/conversations/{conv_id}/members/{admin_id}/role",
            headers=owner,
            json={"role": "admin"},
        )
        assert r.status_code == 200, r.text

        # 非群主不能设管理员
        r = await ac.put(
            f"/conversations/{conv_id}/members/{member_id}/role",
            headers=admin,
            json={"role": "admin"},
        )
        assert r.status_code == 403, r.text

        # 管理员可以邀请新成员
        r = await ac.post(
            f"/conversations/{conv_id}/members",
            headers=admin,
            json={"member_ids": [await _uid(ac, extra)]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["added"] == 1

        # 群主把 extra 也设为管理员
        r = await ac.put(
            f"/conversations/{conv_id}/members/{extra_id}/role",
            headers=owner,
            json={"role": "admin"},
        )
        assert r.status_code == 200, r.text

        # 管理员不能移除其他管理员
        r = await ac.delete(f"/conversations/{conv_id}/members/{extra_id}", headers=admin)
        assert r.status_code == 403, r.text

        # 群主可以移除成员
        r = await ac.delete(f"/conversations/{conv_id}/members/{member_id}", headers=owner)
        assert r.status_code == 200, r.text

        r = await ac.get(f"/conversations/{conv_id}", headers=owner)
        remaining = {m["user_id"] for m in r.json()["members"]}
        assert member_id not in remaining
        assert admin_id in remaining and extra_id in remaining


@pytest.mark.asyncio
async def test_messages_send_recall_delete():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        owner, owner_id = await _register_and_login(ac, "gc")
        member, member_id = await _register_and_login(ac, "gc")
        outsider, _ = await _register_and_login(ac, "gc")

        r = await ac.post(
            "/conversations",
            headers=owner,
            json={"type": "group", "title": "聊天群", "member_ids": [await _uid(ac, member)]},
        )
        conv_id = r.json()["id"]

        # 非成员不能发消息
        r = await ac.post(
            f"/conversations/{conv_id}/messages", headers=outsider, json={"content": "hi"}
        )
        assert r.status_code in (403, 404), r.text

        # 空内容 400
        r = await ac.post(
            f"/conversations/{conv_id}/messages", headers=owner, json={"content": "   "}
        )
        assert r.status_code == 422 or r.status_code == 400, r.text

        # 发送并读取
        r = await ac.post(
            f"/conversations/{conv_id}/messages", headers=owner, json={"content": "大家好啊"}
        )
        assert r.status_code == 201, r.text
        msg_id = r.json()["id"]

        r = await ac.get(f"/conversations/{conv_id}/messages", headers=member)
        assert r.status_code == 200, r.text
        msgs = r.json()["messages"]
        assert any(m["id"] == msg_id and m["content"] == "大家好啊" for m in msgs)

        # 非发送者不能撤回
        r = await ac.post(f"/conversations/{conv_id}/messages/{msg_id}/recall", headers=member)
        assert r.status_code == 403, r.text

        # 发送者撤回
        r = await ac.post(f"/conversations/{conv_id}/messages/{msg_id}/recall", headers=owner)
        assert r.status_code == 200, r.text
        assert r.json()["is_recalled"] is True

        r = await ac.get(f"/conversations/{conv_id}/messages", headers=owner)
        recalled = [m for m in r.json()["messages"] if m["id"] == msg_id][0]
        assert recalled["is_recalled"] is True
        assert recalled["content"] == ""

        # 发送者删除自己的消息后不再出现
        r = await ac.post(
            f"/conversations/{conv_id}/messages", headers=owner, json={"content": "删除我"}
        )
        del_id = r.json()["id"]
        r = await ac.delete(f"/conversations/{conv_id}/messages/{del_id}", headers=owner)
        assert r.status_code == 200, r.text
        r = await ac.get(f"/conversations/{conv_id}/messages", headers=owner)
        assert all(m["id"] != del_id for m in r.json()["messages"])


@pytest.mark.asyncio
async def test_group_avatar_and_reply():
    """群头像 URL（管理权限）+ 消息引用回复（快照、跨群拒绝、撤回联动）。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        owner, _ = await _register_and_login(ac, "gc")
        member, _ = await _register_and_login(ac, "gc")

        r = await ac.post(
            "/conversations",
            headers=owner,
            json={"type": "group", "title": "头像群", "member_ids": [await _uid(ac, member)]},
        )
        conv_id = r.json()["id"]

        # 普通成员不能改群设置
        r = await ac.put(
            f"/conversations/{conv_id}",
            headers=member,
            json={"title": "头像群", "avatar_url": "https://a.com/x.png"},
        )
        assert r.status_code == 403, r.text

        # 群主一次保存群名 + 头像
        r = await ac.put(
            f"/conversations/{conv_id}",
            headers=owner,
            json={"title": "新群名", "avatar_url": "https://a.com/x.png"},
        )
        assert r.status_code == 200, r.text

        r = await ac.get(f"/conversations/{conv_id}", headers=owner)
        detail = r.json()
        assert detail["title"] == "新群名"
        assert detail["avatar_url"] == "https://a.com/x.png"

        # 会话列表同样带出 avatar_url
        r = await ac.get("/conversations", headers=owner)
        item = [c for c in r.json()["items"] if c["id"] == conv_id][0]
        assert item["avatar_url"] == "https://a.com/x.png"

        # 只传 avatar_url：不动标题；空串清空头像
        r = await ac.put(
            f"/conversations/{conv_id}", headers=owner, json={"avatar_url": ""}
        )
        assert r.status_code == 200, r.text
        r = await ac.get(f"/conversations/{conv_id}", headers=owner)
        assert r.json()["avatar_url"] is None
        assert r.json()["title"] == "新群名"

        # ---- 引用回复 ----
        r = await ac.post(
            f"/conversations/{conv_id}/messages", headers=owner, json={"content": "第一楼"}
        )
        first_id = r.json()["id"]

        # 引用不存在的消息 → 400
        r = await ac.post(
            f"/conversations/{conv_id}/messages",
            headers=member,
            json={"content": "幽灵回复", "reply_to_id": 999999},
        )
        assert r.status_code == 400, r.text

        # 跨群引用别的会话的消息 → 400
        r = await ac.post(
            "/conversations", headers=owner, json={"type": "group", "title": "第二群"}
        )
        other_id = r.json()["id"]
        r = await ac.post(
            f"/conversations/{other_id}/messages", headers=owner, json={"content": "别群的消息"}
        )
        other_msg_id = r.json()["id"]
        r = await ac.post(
            f"/conversations/{conv_id}/messages",
            headers=member,
            json={"content": "偷窥", "reply_to_id": other_msg_id},
        )
        assert r.status_code == 400, r.text

        # 正常回复：POST 回包带 reply_to_id，列表带出引用快照
        r = await ac.post(
            f"/conversations/{conv_id}/messages",
            headers=member,
            json={"content": "收到！", "reply_to_id": first_id},
        )
        assert r.status_code == 201, r.text
        assert r.json()["reply_to_id"] == first_id
        reply_id = r.json()["id"]

        r = await ac.get(f"/conversations/{conv_id}/messages", headers=owner)
        msgs = {m["id"]: m for m in r.json()["messages"]}
        assert msgs[reply_id]["reply_to_id"] == first_id
        snap = msgs[reply_id]["reply_to"]
        assert snap["id"] == first_id
        assert snap["content"] == "第一楼"
        assert snap["sender_id"] is not None

        # 被引消息撤回后：快照标记撤回、内容清空（撤回联动）
        r = await ac.post(
            f"/conversations/{conv_id}/messages/{first_id}/recall", headers=owner
        )
        assert r.status_code == 200, r.text
        r = await ac.get(f"/conversations/{conv_id}/messages", headers=owner)
        msgs = {m["id"]: m for m in r.json()["messages"]}
        snap = msgs[reply_id]["reply_to"]
        assert snap["is_recalled"] is True
        assert snap["content"] == ""


@pytest.mark.asyncio
async def test_group_unread_and_read():
    """群聊未读：他人消息计入未读、顶栏总数汇总、打开（标记已读）后清零、自己消息不计未读。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        owner, _ = await _register_and_login(ac, "gu_o")
        member, _ = await _register_and_login(ac, "gu_m")

        r = await ac.post(
            "/conversations",
            headers=owner,
            json={"type": "group", "title": "未读测试群", "member_ids": [await _uid(ac, member)]},
        )
        assert r.status_code in (200, 201), r.text
        conv_id = r.json()["id"]

        # 群主发言：对成员是未读，对自己不是
        r = await ac.post(
            f"/conversations/{conv_id}/messages", headers=owner, json={"content": "大家好"}
        )
        assert r.status_code in (200, 201), r.text

        r = await ac.get("/conversations", headers=member)
        items = {it["id"]: it for it in r.json()["items"]}
        assert items[conv_id]["unread"] == 1, r.text

        r = await ac.get("/conversations", headers=owner)
        items = {it["id"]: it for it in r.json()["items"]}
        assert items[conv_id]["unread"] == 0, r.text

        # 顶栏未读总数包含群聊未读
        count = (await ac.get("/messages/unread-count", headers=member)).json()["count"]
        assert count >= 1

        # 标记已读后清零
        r = await ac.post(f"/conversations/{conv_id}/read", headers=member)
        assert r.status_code == 200, r.text
        r = await ac.get("/conversations", headers=member)
        items = {it["id"]: it for it in r.json()["items"]}
        assert items[conv_id]["unread"] == 0, r.text
