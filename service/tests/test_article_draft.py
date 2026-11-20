"""文章草稿功能回归测试。

覆盖：
- 草稿保存后**不出现在任何公开入口**（文章广场列表、他人详情、我的已发布列表）
- 草稿仅作者本人可见（他人按 404）
- 发布草稿后转入正常可见状态
- 草稿放宽的校验（题解可不填题号）在发布时补回
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


async def _register_and_login(ac: AsyncClient) -> tuple[str, dict, int]:
    """注册并登录，返回 (用户名, 认证头, 用户 id)。"""
    suffix = uuid.uuid4().hex[:8]
    user, pwd = f"draft_{suffix}", "supersecret1"
    r = await ac.post("/users", json={
        "username": user, "email": f"{user}@example.com", "password": pwd})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    r = await ac.post("/tokens", data={"username": user, "password": pwd})
    assert r.status_code == 200, r.text
    return user, {"Authorization": f"Bearer {r.json()['access_token']}"}, uid


async def _create(ac: AsyncClient, headers: dict, title: str, *, draft: bool = False,
                  category: str = "算法理论", problem_code: str | None = None) -> dict:
    payload = {"title": title, "content": "正文内容", "category": category}
    if draft:
        payload["is_draft"] = True
    if problem_code:
        payload["problem_code"] = problem_code
    r = await ac.post("/articles", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_draft_is_hidden_from_all_public_entries():
    """草稿不出现在公开列表/他人详情里；作者自己的「我的文章」也不含草稿。"""
    sfx = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        author, ah, author_id = await _register_and_login(ac)
        _, other, _ = await _register_and_login(ac)

        draft_title = f"草稿标题-{sfx}"
        pub_title = f"已发布标题-{sfx}"
        draft = await _create(ac, ah, draft_title, draft=True)
        assert draft["is_draft"] is True
        pub = await _create(ac, ah, pub_title)
        assert pub["is_draft"] is False

        # 1) 按作者查文章列表（这条路径不过滤推荐状态）不含草稿
        data = (await ac.get("/articles", params={"author_id": author_id})).json()
        titles = {a["title"] for a in data["items"]}
        assert draft_title not in titles, "草稿泄露到了文章列表"
        assert pub_title in titles, "已发布文章应正常出现在列表"

        # 2) 他人访问草稿详情 → 404（按不存在处理）
        r = await ac.get(f"/articles/{draft['id']}", headers=other)
        assert r.status_code == 404, r.text

        # 3) 未登录访问草稿详情 → 404
        r = await ac.get(f"/articles/{draft['id']}")
        assert r.status_code == 404, r.text

        # 4) 作者本人可访问（用于继续编辑）
        r = await ac.get(f"/articles/{draft['id']}", headers=ah)
        assert r.status_code == 200, r.text
        assert r.json()["is_draft"] is True

        # 5) 作者的「我的文章」= 已发布，不含草稿
        mine = (await ac.get("/articles/my", headers=ah)).json()
        mine_titles = {a["title"] for a in mine}
        assert pub_title in mine_titles
        assert draft_title not in mine_titles, "草稿不应混进「我的文章」"

        # 6) 「我的草稿」只有草稿
        drafts = (await ac.get("/articles/drafts", headers=ah)).json()
        draft_titles = {a["title"] for a in drafts}
        assert draft_title in draft_titles
        assert pub_title not in draft_titles


@pytest.mark.asyncio
async def test_draft_cannot_be_interacted_and_publish_flow():
    """草稿不可被他人点赞/评论；发布草稿后进入正常可见状态。"""
    sfx = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        author, ah, _ = await _register_and_login(ac)
        _, other, _ = await _register_and_login(ac)
        # 评论每用户 5 秒 1 条（且限流在可见性校验之前计数），
        # 故「发布后的评论」换一个用户来做
        _, commenter, _ = await _register_and_login(ac)

        draft = await _create(ac, ah, f"草稿互动-{sfx}", draft=True)

        # 他人对草稿点赞 / 评论 → 404（对无权者等同不存在）
        r = await ac.post(f"/articles/{draft['id']}/like", headers=other)
        assert r.status_code == 404, r.text
        r = await ac.post(f"/articles/{draft['id']}/comments",
                          json={"content": "偷偷评论"}, headers=other)
        assert r.status_code == 404, r.text

        # 发布草稿
        r = await ac.post(f"/articles/{draft['id']}/publish", headers=ah)
        assert r.status_code == 200, r.text
        assert r.json()["is_draft"] is False

        # 发布后：他人可见、可评论
        r = await ac.get(f"/articles/{draft['id']}", headers=other)
        assert r.status_code == 200, r.text
        r = await ac.post(f"/articles/{draft['id']}/comments",
                          json={"content": "现在可以评论了"}, headers=commenter)
        assert r.status_code == 201, r.text

        # 草稿列表里已没有它
        drafts = (await ac.get("/articles/drafts", headers=ah)).json()
        assert draft["id"] not in {a["id"] for a in drafts}

        # 重复发布会 400（已不是草稿）
        r = await ac.post(f"/articles/{draft['id']}/publish", headers=ah)
        assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_draft_blocked_from_inclusion_recommend_and_view_count():
    """草稿：不累加阅读量、不可申请全站推荐、不可申请专栏收录。

    收录申请那条尤其重要：作者能访问自己的草稿，若不拦，就能拿草稿去申请第三方
    专栏收录，并通过站内通知把**未发布的标题**泄露给专栏作者。
    """
    sfx = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        author, ah, _ = await _register_and_login(ac)
        other, oh, _ = await _register_and_login(ac)

        draft = await _create(ac, ah, f"草稿拦截-{sfx}", draft=True)

        # 1) 反复打开详情不累加阅读量（作者从「继续编辑」进来很频繁）
        for _ in range(3):
            r = await ac.get(f"/articles/{draft['id']}", headers=ah)
            assert r.status_code == 200, r.text
        assert r.json()["view_count"] == 0, "草稿不应累加阅读量"

        # 2) 不可申请全站推荐（作者本人也不行：会挂成 pending 却不在审核队列里）
        r = await ac.post(f"/articles/{draft['id']}/apply-recommend", json={}, headers=ah)
        assert r.status_code == 400, r.text
        assert "草稿" in r.json()["detail"]

        # 用别人的账号建一个专栏作为收录目标
        col = await ac.post("/columns", json={
            "title": f"收录目标专栏-{sfx}", "description": "测试", "category": "算法理论",
        }, headers=oh)
        assert col.status_code == 201, col.text
        col_id = col.json()["id"]

        # 3) 作者拿自己的草稿申请收录 → 400（拦住通知泄露路径）
        r = await ac.post(f"/columns/{col_id}/inclusion-requests",
                          json={"article_id": draft["id"]}, headers=ah)
        assert r.status_code == 400, r.text
        assert "草稿" in r.json()["detail"]

        # 4) 旁观者对草稿申请收录 → 404（草稿对无权者等同不存在）
        r = await ac.post(f"/columns/{col_id}/inclusion-requests",
                          json={"article_id": draft["id"]}, headers=oh)
        assert r.status_code == 404, r.text

        # 5) 发布后即可正常申请（回归确认没有被拦死）
        r = await ac.post(f"/articles/{draft['id']}/publish", headers=ah)
        assert r.status_code == 200, r.text
        r = await ac.post(f"/columns/{col_id}/inclusion-requests",
                          json={"article_id": draft["id"]}, headers=ah)
        assert r.status_code in (200, 201), r.text


@pytest.mark.asyncio
async def test_draft_relaxes_solution_rule_but_publish_enforces_it():
    """题解分类：草稿阶段可不填题号，发布时会被拦下。"""
    sfx = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        author, ah, _ = await _register_and_login(ac)

        # 草稿：题解分类 + 不填题号 → 允许保存
        draft = await _create(ac, ah, f"题解草稿-{sfx}", draft=True, category="题解")
        assert draft["is_draft"] is True

        # 发布：题解必须有题号 → 400
        r = await ac.post(f"/articles/{draft['id']}/publish", headers=ah)
        assert r.status_code == 400, r.text
        assert "题号" in r.json()["detail"]

        # 非草稿直接发题解且无题号 → 400（原行为不变）
        r = await ac.post("/articles", json={
            "title": f"题解直发-{sfx}", "content": "正文", "category": "题解"},
            headers=ah)
        assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_edit_solution_draft_is_allowed_but_publish_is_blocked():
    """题解类草稿：编辑保存必须放行（否则「先存草稿、发布时再校验」的闭环断裂），
    只有发布时才因缺题号被拦。"""
    sfx = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        author, ah, _ = await _register_and_login(ac)

        draft = await _create(ac, ah, f"题解草稿编辑-{sfx}", draft=True, category="题解")

        # 详情页点「保存更改」（不填空题号）→ 应 200，草稿仍是草稿
        r = await ac.put(f"/articles/{draft['id']}", json={"content": "改过的正文"}, headers=ah)
        assert r.status_code == 200, r.text
        assert r.json()["is_draft"] is True

        # 发布时才拦（题解必须关联题号）
        r = await ac.post(f"/articles/{draft['id']}/publish", headers=ah)
        assert r.status_code == 400, r.text
        assert "题号" in r.json()["detail"]


@pytest.mark.asyncio
async def test_edit_draft_cannot_apply_recommend():
    """编辑草稿时带 apply_recommend 应被拦下——否则草稿会挂成 pending 却
    不在审核队列里（僵尸状态），且与「草稿不进推荐流程」的约定冲突。"""
    sfx = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        author, ah, _ = await _register_and_login(ac)

        draft = await _create(ac, ah, f"草稿推荐-{sfx}", draft=True)

        r = await ac.put(f"/articles/{draft['id']}", json={"apply_recommend": True}, headers=ah)
        assert r.status_code == 400, r.text
        assert "草稿" in r.json()["detail"]

        # 普通编辑（不带推荐）仍然可以保存
        r = await ac.put(f"/articles/{draft['id']}", json={"content": "改一下"}, headers=ah)
        assert r.status_code == 200, r.text
        assert r.json()["recommend_status"] == "none"

        # 发布后再申请推荐 → 放行
        r = await ac.post(f"/articles/{draft['id']}/publish", headers=ah)
        assert r.status_code == 200, r.text
        r = await ac.post(f"/articles/{draft['id']}/apply-recommend", json={}, headers=ah)
        assert r.status_code == 200, r.text
        assert r.json()["recommend_status"] == "pending"


@pytest.mark.asyncio
async def test_publish_is_not_repeatable_and_drafts_are_paginated():
    """发布草稿只成功一次（重复发布 400）；草稿列表支持分页。"""
    sfx = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        _, ah, _ = await _register_and_login(ac)

        draft = await _create(ac, ah, f"重复发布-{sfx}", draft=True)
        aid = draft["id"]

        r = await ac.post(f"/articles/{aid}/publish", headers=ah)
        assert r.status_code == 200, r.text
        assert r.json()["is_draft"] is False

        # 再次发布：条件 UPDATE 命中 0 行 -> 400（而不是静默重复发布）
        r = await ac.post(f"/articles/{aid}/publish", headers=ah)
        assert r.status_code == 400, r.text

        # 分页参数生效：每页 1 条，第 1 页与第 2 页拿到不同的草稿
        for i in range(2):
            await _create(ac, ah, f"分页草稿{i}-{sfx}", draft=True)

        r = await ac.get("/articles/drafts", params={"page": 1, "page_size": 1}, headers=ah)
        assert r.status_code == 200, r.text
        page1 = r.json()
        assert len(page1) == 1
        r = await ac.get("/articles/drafts", params={"page": 2, "page_size": 1}, headers=ah)
        assert r.status_code == 200, r.text
        page2 = r.json()
        assert len(page2) == 1
        assert page1[0]["id"] != page2[0]["id"]

        # 越界页码 -> 空列表（不报错）
        r = await ac.get("/articles/drafts", params={"page": 999, "page_size": 50}, headers=ah)
        assert r.status_code == 200, r.text
        assert r.json() == []
