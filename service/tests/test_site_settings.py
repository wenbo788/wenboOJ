"""站点配置：顶栏公告与首页云图栏目的读写权限与解析。"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionLocal
from app.main import app


async def _register(ac: AsyncClient, prefix: str, *, admin: bool = False) -> tuple[dict[str, str], str]:
    username = f"{prefix}_{uuid.uuid4().hex[:8]}"
    r = await ac.post(
        "/users",
        json={"username": username, "email": f"{username}@example.com", "password": "supersecret1"},
    )
    assert r.status_code == 201, r.text
    if admin:
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            from app.models.user import User
            user = (await db.execute(select(User).where(User.username == username))).scalar_one()
            user.is_admin = True
            await db.commit()
    r = await ac.post("/tokens", data={"username": username, "password": "supersecret1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, username


@pytest.mark.asyncio
async def test_announcement_default_public_put_admin_only():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        user, user_name = await _register(ac, "ss_user")
        admin, admin_name = await _register(ac, "ss_admin", admin=True)

        # 公开可读默认值
        got = await ac.get("/site-settings/announcement")
        assert got.status_code == 200
        assert got.json()["enabled"] is False

        # 普通用户 403
        denied = await ac.put(
            "/site-settings/announcement",
            headers=user,
            json={"enabled": True, "items": [{"text": "hello"}]},
        )
        assert denied.status_code == 403

        # 管理员保存后公开读得到
        saved = await ac.put(
            "/site-settings/announcement",
            headers=admin,
            json={"enabled": True, "items": [{"text": "今晚 20:00 比赛", "link": "/contests"}]},
        )
        assert saved.status_code == 200, saved.text

        pub = await ac.get("/site-settings/announcement")
        assert pub.json() == {
            "enabled": True,
            "items": [{"text": "今晚 20:00 比赛", "link": "/contests"}],
        }

        # 启用但一条内容都没有 → 400
        empty = await ac.put(
            "/site-settings/announcement", headers=admin, json={"enabled": True, "items": []}
        )
        assert empty.status_code == 400

        # javascript: 协议链接 → 422
        bad = await ac.put(
            "/site-settings/announcement",
            headers=admin,
            json={"enabled": True, "items": [{"text": "x", "link": "javascript:alert(1)"}]},
        )
        assert bad.status_code == 422


async def _seed_cloud_pool(admin_name: str) -> tuple[int, int]:
    """造一道公开审核通过的题 + 一条帖子 + 一条友链，返回 (problem_id, post_id)。"""
    from sqlalchemy import select

    from app.models.friend_link import FriendLink
    from app.models.problem import Problem
    from app.models.user import User
    from app.services.forum import ForumService

    async with AsyncSessionLocal() as db:
        author = (
            await db.execute(select(User).where(User.username == admin_name))
        ).scalar_one()
        problem = Problem(
            title="云图推荐题",
            difficulty="普及-",
            description="题面",
            author_id=author.id,
            is_public=True,
            review_status="approved",
        )
        db.add(problem)
        await db.flush()
        post = await ForumService.create_post(
            db, author, "云图指定帖", "正文内容", "siteaffairs"
        )
        db.add(
            FriendLink(
                title="云图友链",
                icon="/favicon.svg",
                url="https://example.org",
                sort_order=0,
                is_active=True,
            )
        )
        problem_id, post_id = problem.id, post.id
        await db.commit()
    return problem_id, post_id


@pytest.mark.asyncio
async def test_home_cloud_admin_config_and_public_parse():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        user, user_name = await _register(ac, "sc_user")
        admin, admin_name = await _register(ac, "sc_admin", admin=True)

        # 原始配置读取需管理员
        assert (await ac.get("/site-settings/home-cloud")).status_code == 401
        assert (await ac.get("/site-settings/home-cloud", headers=user)).status_code == 403

        problem_id, post_id = await _seed_cloud_pool(admin_name)

        # 普通用户不能写
        denied = await ac.put(
            "/site-settings/home-cloud",
            headers=user,
            json={
                "enabled": True,
                "featured_problems": {"enabled": False, "problem_ids": []},
                "pinned_posts": {"enabled": False, "post_ids": []},
            },
        )
        assert denied.status_code == 403

        # 管理员配置两张可修改卡（置顶讨论标题留空 → 用默认叫法）
        saved = await ac.put(
            "/site-settings/home-cloud",
            headers=admin,
            json={
                "enabled": True,
                "featured_problems": {
                    "enabled": True,
                    "title": "每日一题",
                    "problem_ids": [problem_id],
                },
                "pinned_posts": {"enabled": True, "title": "", "post_ids": [post_id]},
            },
        )
        assert saved.status_code == 200, saved.text

        # 管理员读回新结构
        got = await ac.get("/site-settings/home-cloud", headers=admin)
        assert got.json() == {
            "enabled": True,
            "featured_problems": {
                "enabled": True,
                "title": "每日一题",
                "problem_ids": [problem_id],
            },
            "pinned_posts": {"enabled": True, "title": "", "post_ids": [post_id]},
        }

        # 公开解析：固定 3 张（顺序固定）+ 可修改 2 张
        parsed = await ac.get("/home/cloud")
        assert parsed.status_code == 200
        data = parsed.json()
        assert data["enabled"] is True
        kinds = [(c["type"], c["title"]) for c in data["cards"]]
        assert kinds == [
            ("friend_links", "友情链接"),
            ("problems", "随机题目"),
            ("posts", "随机讨论"),
            ("problems", "每日一题"),
            ("posts", "置顶讨论"),
        ]
        # 固定卡每次随机抽 3~4 条（池子不足时按池子大小显示）
        for card in data["cards"][:3]:
            assert 1 <= len(card["items"]) <= 4
        # 可修改卡内容由配置决定
        assert data["cards"][3]["items"][0]["id"] == problem_id
        assert data["cards"][3]["items"][0]["title"] == "云图推荐题"
        assert data["cards"][4]["items"][0]["title"] == "云图指定帖"

        # 关闭板块后公开解析返回未启用
        await ac.put(
            "/site-settings/home-cloud",
            headers=admin,
            json={
                "enabled": False,
                "featured_problems": {
                    "enabled": True,
                    "title": "每日一题",
                    "problem_ids": [problem_id],
                },
                "pinned_posts": {"enabled": True, "title": "", "post_ids": [post_id]},
            },
        )
        assert (await ac.get("/home/cloud")).json() == {"enabled": False, "cards": []}


@pytest.mark.asyncio
async def test_home_cloud_validation():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        admin, admin_name = await _register(ac, "sc_admin3", admin=True)
        await _seed_cloud_pool(admin_name)

        # 可修改卡 id 超过 4 条 → 422
        too_many = await ac.put(
            "/site-settings/home-cloud",
            headers=admin,
            json={
                "enabled": True,
                "featured_problems": {"enabled": True, "problem_ids": [1, 2, 3, 4, 5]},
                "pinned_posts": {"enabled": False, "post_ids": []},
            },
        )
        assert too_many.status_code == 422
        too_many_posts = await ac.put(
            "/site-settings/home-cloud",
            headers=admin,
            json={
                "enabled": True,
                "featured_problems": {"enabled": False, "problem_ids": []},
                "pinned_posts": {"enabled": True, "post_ids": [1, 2, 3, 4, 5]},
            },
        )
        assert too_many_posts.status_code == 422

        # 启用可修改卡但一条没选 → 400
        empty_featured = await ac.put(
            "/site-settings/home-cloud",
            headers=admin,
            json={
                "enabled": True,
                "featured_problems": {"enabled": True, "problem_ids": []},
                "pinned_posts": {"enabled": False, "post_ids": []},
            },
        )
        assert empty_featured.status_code == 400
        empty_pinned = await ac.put(
            "/site-settings/home-cloud",
            headers=admin,
            json={
                "enabled": True,
                "featured_problems": {"enabled": False, "problem_ids": []},
                "pinned_posts": {"enabled": True, "post_ids": []},
            },
        )
        assert empty_pinned.status_code == 400

        # 只启用板块、两张可修改卡都关 → 保存成功，公开解析只剩固定 3 张
        ok = await ac.put(
            "/site-settings/home-cloud",
            headers=admin,
            json={
                "enabled": True,
                "featured_problems": {"enabled": False, "problem_ids": []},
                "pinned_posts": {"enabled": False, "post_ids": []},
            },
        )
        assert ok.status_code == 200, ok.text
        data = (await ac.get("/home/cloud")).json()
        assert data["enabled"] is True
        assert [c["title"] for c in data["cards"]] == ["友情链接", "随机题目", "随机讨论"]


@pytest.mark.asyncio
async def test_home_cloud_legacy_cards_compat():
    """旧版「自由卡片列表」落库值自动映射成两张可修改卡，老配置不丢。"""
    from sqlalchemy import select

    from app.models.site_setting import SiteSetting

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        admin, admin_name = await _register(ac, "sc_admin4", admin=True)
        problem_id, post_id = await _seed_cloud_pool(admin_name)

        legacy_value = {
            "enabled": True,
            "cards": [
                {"type": "posts", "title": "热门讨论", "post_ids": [post_id]},
                {"type": "problems", "title": "推荐题目", "problem_ids": [problem_id]},
                {"type": "friend_links", "title": "友情链接", "limit": 8},
            ],
        }
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(select(SiteSetting).where(SiteSetting.key == "home_cloud"))
            ).scalar_one_or_none()
            if row is None:
                from app.models.user import User

                author = (
                    await db.execute(select(User).where(User.username == admin_name))
                ).scalar_one()
                db.add(
                    SiteSetting(
                        key="home_cloud",
                        value=legacy_value,
                        updated_by_id=author.id,
                        note="旧格式",
                    )
                )
            else:
                row.value = legacy_value
            await db.commit()

        # 管理员读 → 映射成新结构，旧默认标题换成新叫法
        got = await ac.get("/site-settings/home-cloud", headers=admin)
        assert got.json() == {
            "enabled": True,
            "featured_problems": {
                "enabled": True,
                "title": "精选题目",
                "problem_ids": [problem_id],
            },
            "pinned_posts": {"enabled": True, "title": "置顶讨论", "post_ids": [post_id]},
        }

        # 公开解析照常：固定 3 张 + 可修改 2 张
        data = (await ac.get("/home/cloud")).json()
        assert [c["title"] for c in data["cards"]] == [
            "友情链接",
            "随机题目",
            "随机讨论",
            "精选题目",
            "置顶讨论",
        ]


@pytest.mark.asyncio
async def test_forum_list_posts_keyword_filter():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        admin, admin_name = await _register(ac, "kw_admin", admin=True)
        from app.services.forum import ForumService
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import select
        from app.models.user import User

        async with AsyncSessionLocal() as db:
            author = (
                await db.execute(select(User).where(User.username == admin_name))
            ).scalar_one()
            await ForumService.create_post(db, author, "独特关键词斑马", "x", "siteaffairs")
            await ForumService.create_post(db, author, "普通标题", "y", "siteaffairs")
            await db.commit()

        all_posts = await ac.get("/forum/posts")
        assert all_posts.status_code == 200
        assert all_posts.json()["total"] >= 2

        filtered = await ac.get("/forum/posts", params={"keyword": "斑马"})
        assert filtered.status_code == 200
        titles = [p["title"] for p in filtered.json()["posts"]]
        assert titles == ["独特关键词斑马"]
