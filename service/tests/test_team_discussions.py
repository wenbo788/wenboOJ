import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.notification import Notification
from app.models.user import User


async def _register_and_login(ac: AsyncClient) -> tuple[dict[str, str], int, str]:
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
    return headers, me["id"], username


@pytest.mark.asyncio
async def test_team_discussion_full_flow():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        owner_h, owner_id, owner_name = await _register_and_login(ac)
        member_h, member_id, member_name = await _register_and_login(ac)
        stranger_h, stranger_id, stranger_name = await _register_and_login(ac)

        # 1. 团主建团队
        r = await ac.post("/teams", json={"name": f"Team_{uuid.uuid4().hex[:6]}"}, headers=owner_h)
        assert r.status_code == 201
        team_id = r.json()["id"]

        # 2. 成员加入团队
        r = await ac.post(f"/teams/{team_id}/join", headers=member_h)
        assert r.status_code == 200
        # 团主通过审核
        r = await ac.post(f"/teams/{team_id}/requests/{member_id}/approve", headers=owner_h)
        assert r.status_code == 200

        # 3. 局外人看帖子列表 -> 403
        r = await ac.get(f"/teams/{team_id}/posts", headers=stranger_h)
        assert r.status_code == 403

        # 4. 成员发帖
        r = await ac.post(
            f"/teams/{team_id}/posts",
            json={"title": "团队第一条讨论", "content": "欢迎大家交流讨论！"},
            headers=member_h,
        )
        assert r.status_code == 200
        post_id = r.json()["id"]
        assert r.json()["title"] == "团队第一条讨论"
        assert r.json()["author"]["username"] == member_name

        # 5. 团主也发一条置顶公告
        r = await ac.post(
            f"/teams/{team_id}/posts",
            json={"title": "【公告】入队必读", "content": "请大家文明讨论遵守规则。"},
            headers=owner_h,
        )
        assert r.status_code == 200
        notice_id = r.json()["id"]

        # 团主置顶公告
        r = await ac.post(f"/teams/{team_id}/posts/{notice_id}/pin", headers=owner_h)
        assert r.status_code == 200
        assert r.json()["is_pinned"] is True

        # 普通成员尝试置顶 -> 403
        r = await ac.post(f"/teams/{team_id}/posts/{post_id}/pin", headers=member_h)
        assert r.status_code == 403

        # 6. 查看讨论列表（验证置顶优先排在前头）
        r = await ac.get(f"/teams/{team_id}/posts", headers=member_h)
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 2
        assert items[0]["id"] == notice_id
        assert items[0]["is_pinned"] is True
        assert items[1]["id"] == post_id
        assert items[1]["is_pinned"] is False

        # 7. 团主回复成员的讨论
        r = await ac.post(
            f"/teams/{team_id}/posts/{post_id}/comments",
            json={"content": "支持！"},
            headers=owner_h,
        )
        assert r.status_code == 200
        comment_id = r.json()["id"]

        # 检查成员是否收到了 reply 通知
        async with AsyncSessionLocal() as db:
            notifs = (await db.execute(
                select(Notification).where(Notification.user_id == member_id, Notification.type == "reply")
            )).scalars().all()
            assert any(f"@{owner_name} 回复了你" in n.content for n in notifs)

        # 8. 查看帖子详情（成员可看，局外人不可看，秩序管理员若非团队成员亦不可看）
        r = await ac.get(f"/teams/{team_id}/posts/{post_id}", headers=member_h)
        assert r.status_code == 200
        detail = r.json()
        assert detail["reply_count"] == 1
        assert len(detail["comments"]) == 1
        assert detail["comments"][0]["content"] == "支持！"

        # 局外人通过 post_id 直接访问详情 -> 403
        r = await ac.get(f"/teams/{team_id}/posts/{post_id}", headers=stranger_h)
        assert r.status_code == 403

        # 秩序管理员（非该团队成员）访问 -> 403
        async with AsyncSessionLocal() as db:
            from sqlalchemy import update
            await db.execute(update(User).where(User.id == stranger_id).values(can_manage_posts=True))
            await db.commit()
        r = await ac.get(f"/teams/{team_id}/posts/{post_id}", headers=stranger_h)
        assert r.status_code == 403

        # 9. 团主锁定帖子后，普通成员不可再回复
        r = await ac.post(f"/teams/{team_id}/posts/{post_id}/lock", headers=owner_h)
        assert r.status_code == 200
        assert r.json()["is_locked"] is True

        r = await ac.post(
            f"/teams/{team_id}/posts/{post_id}/comments",
            json={"content": "试图在锁定后回复"},
            headers=member_h,
        )
        assert r.status_code == 403
        assert "锁定" in r.json()["detail"]

        # 团主（管理员）仍可在锁定状态下回复
        r = await ac.post(
            f"/teams/{team_id}/posts/{post_id}/comments",
            json={"content": "管理员在锁定后留言"},
            headers=owner_h,
        )
        assert r.status_code == 200

        # 10. 删除评论与删除帖子
        r = await ac.delete(f"/teams/{team_id}/posts/{post_id}/comments/{comment_id}", headers=owner_h)
        assert r.status_code == 200

        r = await ac.delete(f"/teams/{team_id}/posts/{post_id}", headers=member_h)
        assert r.status_code == 200

        r = await ac.get(f"/teams/{team_id}/posts/{post_id}", headers=member_h)
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_team_discussion_bell_broadcast():
    """有人在团队创建讨论时，应向其余成员（含团主）推送「新讨论」铃铛。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        owner_h, owner_id, _ = await _register_and_login(ac)
        member_h, member_id, member_name = await _register_and_login(ac)

        r = await ac.post("/teams", json={"name": f"Bell_{uuid.uuid4().hex[:6]}"}, headers=owner_h)
        assert r.status_code == 201
        team_id = r.json()["id"]

        r = await ac.post(f"/teams/{team_id}/join", headers=member_h)
        assert r.status_code == 200
        r = await ac.post(f"/teams/{team_id}/requests/{member_id}/approve", headers=owner_h)
        assert r.status_code == 200

        # 成员发帖
        r = await ac.post(
            f"/teams/{team_id}/posts",
            json={"title": "新人报到", "content": "大家好"},
            headers=member_h,
        )
        assert r.status_code == 200

        async with AsyncSessionLocal() as db:
            owner_notifs = (await db.execute(
                select(Notification).where(
                    Notification.user_id == owner_id,
                    Notification.type == "team",
                )
            )).scalars().all()
            # 团主应收到「新讨论」铃铛
            assert any(
                "发起了新讨论" in n.content and "新人报到" in n.content
                for n in owner_notifs
            ), [n.content for n in owner_notifs]

            # 作者本人不应收到自己发的铃铛
            author_notifs = (await db.execute(
                select(Notification).where(
                    Notification.user_id == member_id,
                    Notification.type == "team",
                )
            )).scalars().all()
            assert not any(
                "发起了新讨论" in n.content and f"@{member_name}" in n.content
                for n in author_notifs
            )
