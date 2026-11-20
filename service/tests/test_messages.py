"""NLNOC 私信：发送 / 会话聚合 / 已读 / 用户搜索。

规则要点：
  1. 发私信 → 201；给自己发 400；给不存在的人发 404；纯空白内容 400；未登录 401
  2. 会话列表按对方聚合：每个对方一条，带最后一条消息与未读数，按最新排序
  3. 打开会话 POST .../read 后，未读数与角标同步归零
  4. /users/search 返回与会话 peer 同形的字段、排除自己、支持按 UID 精确命中
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


async def _register_and_login(
    ac: AsyncClient, prefix: str
) -> tuple[dict, str, int, int]:
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
    return headers, username, me["id"], me["user_number"]


async def _send(
    ac: AsyncClient,
    headers: dict,
    recipient_id: int,
    content: str = "在吗？",
    reply_to_id: int | None = None,
):
    body: dict = {"recipient_id": recipient_id, "content": content}
    if reply_to_id is not None:
        body["reply_to_id"] = reply_to_id
    return await ac.post("/messages", headers=headers, json=body)


@pytest.mark.asyncio
async def test_send_conversation_and_read_flow():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h_alice, alice_name, alice_id, _ = await _register_and_login(ac, "dm")
        h_bob, bob_name, bob_id, _ = await _register_and_login(ac, "dm")

        # 1. 发送
        r = await _send(ac, h_alice, bob_id, "在吗？")
        assert r.status_code == 201, r.text
        msg = r.json()
        assert msg["content"] == "在吗？"
        assert msg["sender_id"] == alice_id
        assert msg["recipient_id"] == bob_id
        assert msg["is_read"] is False

        # 2. 未读数角标
        r = await ac.get("/messages/unread-count", headers=h_bob)
        assert r.status_code == 200 and r.json()["count"] == 1
        r = await ac.get("/messages/unread-count", headers=h_alice)
        assert r.json()["count"] == 0

        # 3. Bob 的会话列表：对方是 alice、未读 1、最后一条即刚发的消息
        r = await ac.get("/messages/conversations", headers=h_bob)
        assert r.status_code == 200, r.text
        convs = r.json()["conversations"]
        assert len(convs) == 1
        assert convs[0]["peer"]["id"] == alice_id
        assert convs[0]["peer"]["username"] == alice_name
        assert convs[0]["peer"]["user_number"] > 0
        assert convs[0]["unread"] == 1
        assert convs[0]["last_message"]["content"] == "在吗？"

        # 4. 打开会话：历史旧→新返回，随后标记已读
        r = await ac.get(f"/messages/{alice_id}", headers=h_bob)
        assert r.status_code == 200
        data = r.json()
        assert data["peer"]["id"] == alice_id
        assert [m["content"] for m in data["messages"]] == ["在吗？"]
        assert data["has_more"] is False

        r = await ac.post(f"/messages/{alice_id}/read", headers=h_bob)
        assert r.status_code == 200 and r.json()["updated"] == 1

        r = await ac.get("/messages/unread-count", headers=h_bob)
        assert r.json()["count"] == 0
        convs = (await ac.get("/messages/conversations", headers=h_bob)).json()["conversations"]
        assert convs[0]["unread"] == 0

        # 5. 双向：bob 回复后，双方各自的会话都更新到最新一条
        r = await _send(ac, h_bob, alice_id, "在的")
        assert r.status_code == 201, r.text

        convs_alice = (
            await ac.get("/messages/conversations", headers=h_alice)
        ).json()["conversations"]
        assert convs_alice[0]["peer"]["id"] == bob_id
        assert convs_alice[0]["peer"]["username"] == bob_name
        assert convs_alice[0]["last_message"]["content"] == "在的"
        assert convs_alice[0]["unread"] == 1

        # 6. 聊天记录双向可见，顺序为旧→新
        r = await ac.get(f"/messages/{bob_id}", headers=h_alice)
        assert [m["content"] for m in r.json()["messages"]] == ["在吗？", "在的"]

        # 7. 增量轮询：after_id 之后的新消息
        r = await ac.get(f"/messages/{alice_id}", headers=h_bob, params={"after_id": 0})
        assert [m["content"] for m in r.json()["messages"]] == ["在吗？", "在的"]
        last_id = r.json()["messages"][-1]["id"]
        r = await ac.get(f"/messages/{alice_id}", headers=h_bob, params={"after_id": last_id})
        assert r.json()["messages"] == []


@pytest.mark.asyncio
async def test_send_validation():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h_me, _, my_id, _ = await _register_and_login(ac, "dmv")

        # 不能给自己发
        r = await _send(ac, h_me, my_id)
        assert r.status_code == 400

        # 用户不存在
        r = await _send(ac, h_me, 99999999)
        assert r.status_code == 404

        # 纯空白内容
        r = await _send(ac, h_me, 1, "   ")
        assert r.status_code == 400

        # 未登录
        r = await ac.post("/messages", json={"recipient_id": 1, "content": "hi"})
        assert r.status_code == 401

        # 空历史会话：不存在的对方 → 404；自己 → 400
        r = await ac.get("/messages/99999999", headers=h_me)
        assert r.status_code == 404
        r = await ac.get(f"/messages/{my_id}", headers=h_me)
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_search_users():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h_a, name_a, id_a, _ = await _register_and_login(ac, "srch")
        _, name_b, id_b, num_b = await _register_and_login(ac, "srch")

        # 按完整用户名搜索：命中 bob、不含自己
        r = await ac.get("/users/search", headers=h_a, params={"q": name_b})
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert any(i["id"] == id_b for i in items), items
        assert all(i["id"] != id_a for i in items)

        # 与会话 peer 同形（NLNOC 前端拿到搜索结果可直接开聊）
        bob_item = next(i for i in items if i["id"] == id_b)
        for key in ("id", "username", "user_number", "avatar_url", "user_tag", "last_seen"):
            assert key in bob_item

        # 按 UID 精确搜索
        r = await ac.get("/users/search", headers=h_a, params={"q": str(num_b)})
        assert any(i["id"] == id_b for i in r.json()["items"])

        # 无命中
        r = await ac.get(
            "/users/search", headers=h_a, params={"q": "zzz_no_such_user_zzz"}
        )
        assert r.json()["items"] == []

        # 未登录 401
        r = await ac.get("/users/search", params={"q": "x"})
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_conversations_one_way_and_multi_peer():
    """会话列表的历史盲区（此前从未覆盖）：
    1) 我单向发出、对方从未回复——我的列表也必须有这个会话；
    2) 多会话各取最后一条、按最新一条的 id 排序；
    3) 未读只统计「我收到的」，我自己发出的不计。
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h_me, _, me_id, _ = await _register_and_login(ac, "oneway")
        _, _, bob_id, _ = await _register_and_login(ac, "oneway")
        h_carol, _, carol_id, _ = await _register_and_login(ac, "oneway")

        # 1) 只发不收：我的列表必须出现该会话
        r = await _send(ac, h_me, bob_id, "在吗")
        assert r.status_code == 201, r.text
        convs = (
            await ac.get("/messages/conversations", headers=h_me)
        ).json()["conversations"]
        assert len(convs) == 1, "我单向发出的会话必须出现在我的列表"
        assert convs[0]["peer"]["id"] == bob_id
        assert convs[0]["last_message"]["content"] == "在吗"
        assert convs[0]["unread"] == 0

        # 2) carol 给我发两条（我未读）
        assert (await _send(ac, h_carol, me_id, "第一条")).status_code == 201
        assert (await _send(ac, h_carol, me_id, "第二条")).status_code == 201

        convs = (
            await ac.get("/messages/conversations", headers=h_me)
        ).json()["conversations"]
        assert len(convs) == 2
        # carol 的消息更新（id 更大）→ carol 置顶；未读=2（只算收到的）
        assert convs[0]["peer"]["id"] == carol_id
        assert convs[0]["unread"] == 2
        assert convs[0]["last_message"]["content"] == "第二条"
        assert convs[1]["peer"]["id"] == bob_id
        assert convs[1]["unread"] == 0

        # 3) 我回 bob → bob 会话的最后一条更新并回到置顶
        r = await _send(ac, h_me, bob_id, "来了")
        assert r.status_code == 201
        convs = (
            await ac.get("/messages/conversations", headers=h_me)
        ).json()["conversations"]
        assert [c["peer"]["id"] for c in convs] == [bob_id, carol_id]
        assert convs[0]["last_message"]["content"] == "来了"
        assert convs[0]["unread"] == 0

        # carol 视角：我没回过她，她只有 1 个会话、未读为 0
        convs = (
            await ac.get("/messages/conversations", headers=h_carol)
        ).json()["conversations"]
        assert len(convs) == 1
        assert convs[0]["peer"]["id"] == me_id
        assert convs[0]["unread"] == 0


@pytest.mark.asyncio
async def test_recall_and_quote_reply():
    """撤回（仅本人）与引用回复的全链路。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h_a, _, alice_id, _ = await _register_and_login(ac, "recall")
        h_b, _, bob_id, _ = await _register_and_login(ac, "recall")
        h_c, _, carol_id, _ = await _register_and_login(ac, "recall")

        # 1. 引用回复：落库并携带被引快照
        m1 = (await _send(ac, h_a, bob_id, "第一条")).json()
        m2 = (
            await _send(ac, h_a, bob_id, "答你的问题", reply_to_id=m1["id"])
        ).json()
        assert m2["reply_to_id"] == m1["id"]
        assert m2["reply_to"]["id"] == m1["id"]
        assert m2["reply_to"]["content"] == "第一条"
        assert m2["reply_to"]["is_recalled"] is False

        # 对方引用同一会话里的消息 → 允许
        m3 = (
            await _send(ac, h_b, alice_id, "回你", reply_to_id=m1["id"])
        ).json()
        assert m3["reply_to"]["content"] == "第一条"

        # 2. 引用不存在的消息 / 跨会话引用 → 400
        r = await _send(ac, h_a, bob_id, "x", reply_to_id=99999999)
        assert r.status_code == 400
        r = await _send(ac, h_a, carol_id, "跨会话", reply_to_id=m1["id"])
        assert r.status_code == 400

        # 3. 撤回：非发送者 403、不存在 404
        r = await ac.post(f"/messages/{m1['id']}/recall", headers=h_b)
        assert r.status_code == 403
        r = await ac.post("/messages/99999999/recall", headers=h_a)
        assert r.status_code == 404

        # 4. 发送者撤回 → 200，正文遮蔽；幂等
        r = await ac.post(f"/messages/{m1['id']}/recall", headers=h_a)
        assert r.status_code == 200
        got = r.json()
        assert got["is_recalled"] is True
        assert got["content"] == ""
        r = await ac.post(f"/messages/{m1['id']}/recall", headers=h_a)
        assert r.status_code == 200 and r.json()["is_recalled"] is True

        # 5. 消息流：撤回遮蔽 + 被引快照同步遮蔽 + recalled_ids 同步通道
        data = (await ac.get(f"/messages/{bob_id}", headers=h_a)).json()
        by_id = {m["id"]: m for m in data["messages"]}
        assert by_id[m1["id"]]["is_recalled"] is True
        assert by_id[m1["id"]]["content"] == ""
        assert by_id[m2["id"]]["reply_to"]["is_recalled"] is True
        assert by_id[m2["id"]]["reply_to"]["content"] == ""
        assert by_id[m3["id"]]["reply_to"]["content"] == ""

        poll = (
            await ac.get(
                f"/messages/{bob_id}", headers=h_a, params={"after_id": m3["id"]}
            )
        ).json()
        assert m1["id"] in poll["recalled_ids"]

        # 6. 会话列表预览：最后一条被撤回 → 带撤回标记
        last_id = (await _send(ac, h_b, alice_id, "最后一条")).json()["id"]
        r = await ac.post(f"/messages/{last_id}/recall", headers=h_b)
        assert r.status_code == 200
        convs = (
            await ac.get("/messages/conversations", headers=h_a)
        ).json()["conversations"]
        bob_conv = next(c for c in convs if c["peer"]["id"] == bob_id)
        assert bob_conv["last_message"]["is_recalled"] is True
        assert bob_conv["last_message"]["content"] == ""


@pytest.mark.asyncio
async def test_unread_count_excludes_active_peer():
    """unread-count?exclude_peer_id=：正与某人对话时，他发来的未读不计入角标。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        me, _, my_id, _ = await _register_and_login(ac, "uc")
        a, _, a_id, _ = await _register_and_login(ac, "uc")
        c, _, c_id, _ = await _register_and_login(ac, "uc")

        assert (await _send(ac, a, my_id, "a1")).status_code == 201
        assert (await _send(ac, a, my_id, "a2")).status_code == 201
        assert (await _send(ac, c, my_id, "c1")).status_code == 201

        r = await ac.get("/messages/unread-count", headers=me)
        assert r.status_code == 200, r.text
        assert r.json()["count"] == 3

        # 正在与 C 对话：C 发来的不计，A 的照常计
        r = await ac.get(
            "/messages/unread-count", headers=me, params={"exclude_peer_id": c_id}
        )
        assert r.json()["count"] == 2, r.text

        # 正在与 A 对话：只剩 C 的那条
        r = await ac.get(
            "/messages/unread-count", headers=me, params={"exclude_peer_id": a_id}
        )
        assert r.json()["count"] == 1, r.text

        # 退出对话后恢复全量
        r = await ac.get("/messages/unread-count", headers=me)
        assert r.json()["count"] == 3





@pytest.mark.asyncio
async def test_history_when_peer_granted_my_tag_card():
    """对端恰好是我某张 Tag 卡的授予人时，打开与他的私信不能 500。

    回归：UserTagCard.granter 曾是 lazy="joined" 的**自引用**急切加载，
    会被 SQLAlchemy 的递归守卫截断，把「tag_cards 没加载」的半成品 User
    实例塞进身份映射；聊天记录接口用 db.get(User, peer_id) 命中该实例后
    读 display_tag（→ self.tag_cards）就触发同步懒加载，
    在 async 下直接 MissingGreenlet → 500。
    线上表现：只有「和自己某张卡的授予人」私信时才炸，与别人私信正常。
    """
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.tag_card import UserTagCard
    from app.models.user import User

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        a_h, a_name, a_id, a_num = await _register_and_login(ac, "granter_target")
        b_h, b_name, b_id, _ = await _register_and_login(ac, "granter")

        # 造出线上那种数据：A 的卡是 B 授予的
        async with AsyncSessionLocal() as db:
            db.add(UserTagCard(user_id=a_id, name="我不笨", enabled=True, granter_id=b_id))
            await db.commit()

        r = await _send(ac, b_h, a_id, "在吗")
        assert r.status_code == 201, r.text

        # A 打开与 B 的会话：不能 500，且对端的称号要正常下发
        r = await ac.get(f"/messages/{b_id}", headers=a_h)
        assert r.status_code == 200, r.text
        assert r.json()["peer"]["id"] == b_id
        assert len(r.json()["messages"]) == 1
        # 授予人自己看这段会话也不能炸
        r = await ac.get(f"/messages/{a_id}", headers=b_h)
        assert r.status_code == 200, r.text
        # 会话列表同样要能出（peer 走的是另一条加载路径）
        r = await ac.get("/messages/conversations", headers=a_h)
        assert r.status_code == 200, r.text

        # 公开资料要能带出授予人名字（granter 改为显式加载后必须覆盖所有三个公开端点）
        for endpoint in (f"/users/by-username/{a_name}", f"/users/{a_id}", f"/users/number/{a_num}"):
            r = await ac.get(endpoint)
            assert r.status_code == 200, f"{endpoint} 失败: {r.text}"
            cards = r.json()["tag_cards"]
            assert [c["granter_name"] for c in cards] == [b_name], f"{endpoint} 授予人信息错误: {r.text}"

        # 我自己的卡列表也要有授予人
        r = await ac.get("/users/me/tag-cards", headers=a_h)
        assert r.status_code == 200, r.text
        assert [c["granter_name"] for c in r.json()["items"]] == [b_name], r.text
