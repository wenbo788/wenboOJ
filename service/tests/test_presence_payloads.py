"""在线状态（last_seen）在各处下发形状里的一致性。

前端的在线点（UserAvatarStatus）只认 last_seen：哪个接口漏了这个字段，
那个位置的人就永远显示离线。几处最容易漏的地方在这里钉住：

- 发布犇犇的响应（前端拿它替换乐观插入的临时项，漏了会自己显示成离线）
- 犇犇列表（作为对照，两边口径必须一致）
- 专栏作者 / 文章评论作者（AuthorBrief）
- 题解 / 出题人（ProblemService._user_brief）
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.columns import _author_to_brief
from app.main import app
from app.models.user import User
from app.services.problem import _user_brief as problem_user_brief


async def _register_and_login(ac: AsyncClient) -> dict:
    suffix = uuid.uuid4().hex[:8]
    user, pwd = f"presence_{suffix}", "supersecret1"
    r = await ac.post("/users", json={
        "username": user, "email": f"{user}@example.com", "password": pwd})
    assert r.status_code == 201, r.text
    r = await ac.post("/tokens", data={"username": user, "password": pwd})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.asyncio
async def test_create_benben_response_carries_last_seen():
    """发犇犇的响应必须带 last_seen，且和列表里同一条一致。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _register_and_login(ac)

        # 先来一次心跳，把 last_seen 落下（真实用户是前端 30 秒一次）
        r = await ac.post("/users/me/seen", headers=h)
        assert r.status_code == 200, r.text

        r = await ac.post("/benben", json={"content": "在线点自测"}, headers=h)
        assert r.status_code == 201, r.text
        created = r.json()
        assert created.get("last_seen"), f"发布响应缺少 last_seen：{created}"

        listed = (await ac.get("/benben", params={"limit": 5})).json()
        same = [x for x in listed if x["id"] == created["id"]]
        assert same, listed
        assert same[0].get("last_seen"), f"列表里同一条却没有 last_seen：{same[0]}"


def _fake_user(**overrides) -> User:
    """够 _author_to_brief / _user_brief 用即可，不需要落库。"""
    user = User(id=1, username="zhaoyh", user_number=7)
    user.last_seen = datetime.now(timezone.utc)
    for k, v in overrides.items():
        setattr(user, k, v)
    return user


def test_column_author_brief_carries_last_seen():
    """专栏作者/评论者：漏了 last_seen，头像上的在线点永远是离线。"""
    brief = _author_to_brief(_fake_user())
    assert brief is not None
    assert brief.last_seen is not None, brief


def test_column_author_brief_handles_missing_last_seen():
    """没登录过的用户 last_seen 是 None，序列化不能炸。"""
    brief = _author_to_brief(_fake_user(last_seen=None))
    assert brief is not None and brief.last_seen is None, brief


def test_problem_user_brief_carries_last_seen():
    """题解 / 出题人：同样要带 last_seen。"""
    brief = problem_user_brief(_fake_user())
    assert brief is not None
    assert brief.get("last_seen"), brief

    # 从没上过线的用户：字段在，值是 None（前端按离线渲染）
    offline = problem_user_brief(_fake_user(last_seen=None))
    assert offline is not None and "last_seen" in offline and offline["last_seen"] is None
