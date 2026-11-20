"""帖子列表的 exclude_forum：让「学术模式」能把灌水区整块屏蔽掉。

只藏 tab 是不够的——「全部」里照样会冒出灌水区的帖子，
所以过滤必须在服务端做（分页才不会被前端过滤弄出半页数据）。
这里守住：不传就照旧全给、传了就一条都不漏。
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


async def _register_and_login(ac: AsyncClient) -> dict:
    """注册并登录一个随机用户，返回认证头。

    注意每个用户 60 秒只能发一帖（服务端限流），所以两条帖子要用两个用户。
    """
    suffix = uuid.uuid4().hex[:8]
    user, pwd = f"forum_{suffix}", "supersecret1"
    r = await ac.post("/users", json={
        "username": user, "email": f"{user}@example.com", "password": pwd})
    assert r.status_code == 201, r.text
    r = await ac.post("/tokens", data={"username": user, "password": pwd})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.asyncio
async def test_list_posts_can_exclude_a_forum():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h1 = await _register_and_login(ac)
        h2 = await _register_and_login(ac)
        # 用同一个关键词把本用例的两条帖子和别的用例的数据区分开
        tag = uuid.uuid4().hex[:8]
        water_title = f"灌水贴-{tag}"
        normal_title = f"题目贴-{tag}"

        r = await ac.post("/forum/posts", json={
            "title": water_title, "content": "灌水区内容", "forum": "relevantaffairs",
        }, headers=h1)
        assert r.status_code == 201, r.text
        r = await ac.post("/forum/posts", json={
            "title": normal_title, "content": "题目总版内容", "forum": "problem",
        }, headers=h2)
        assert r.status_code == 201, r.text

        # 不传 exclude_forum：两条都在（行为不变）
        data = (await ac.get("/forum/posts", params={"keyword": tag})).json()
        titles = {p["title"] for p in data["posts"]}
        assert titles == {water_title, normal_title}, data
        assert data["total"] == 2, data

        # 传了 exclude_forum：灌水区那条一条都不出现，total 也跟着减
        data = (
            await ac.get(
                "/forum/posts",
                params={"keyword": tag, "exclude_forum": "relevantaffairs"},
            )
        ).json()
        titles = {p["title"] for p in data["posts"]}
        assert titles == {normal_title}, data
        assert data["total"] == 1, data

        # 单独选中被排除的版块 → 空（两个条件互不冲突）
        data = (
            await ac.get(
                "/forum/posts",
                params={
                    "keyword": tag,
                    "forum": "relevantaffairs",
                    "exclude_forum": "relevantaffairs",
                },
            )
        ).json()
        assert data["posts"] == [], data

        # exclude_forum=all 视为不过滤，别把整站帖子都排掉
        data = (
            await ac.get(
                "/forum/posts", params={"keyword": tag, "exclude_forum": "all"}
            )
        ).json()
        assert data["total"] == 2, data
