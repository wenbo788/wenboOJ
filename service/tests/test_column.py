"""Tests for Column and Column Article system (专栏功能测试)."""

import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.core.database import AsyncSessionLocal
from app.models.user import User


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _register_and_login(
    ac: AsyncClient, prefix: str, is_admin: bool = False
) -> tuple[dict, str, int]:
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

    if is_admin:
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            user = (await db.execute(select(User).where(User.username == username))).scalar_one()
            user.is_admin = True
            await db.commit()

    r = await ac.post(
        "/tokens", data={"username": username, "password": "supersecret1"}
    )
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await ac.get("/auth/me", headers=headers)).json()
    return headers, username, me["id"]


@pytest.mark.asyncio
async def test_column_lifecycle():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        headers_user, user_name, user_id = await _register_and_login(ac, "usr_col")
        headers_admin, admin_name, admin_id = await _register_and_login(ac, "adm_col", is_admin=True)

        # 1. 普通用户创建专栏
        create_res = await ac.post(
            "/columns",
            headers=headers_user,
            json={
                "title": "算法进阶笔记",
                "description": "记录动态规划与图论高阶技巧",
                "cover_url": "https://example.com/cover.png",
                "category": "算法理论",
            },
        )
        assert create_res.status_code == 201, create_res.text
        col_data = create_res.json()
        col_id = col_data["id"]
        assert col_data["title"] == "算法进阶笔记"
        assert col_data["category"] == "算法理论"
        assert col_data["author_id"] == user_id
        assert col_data["is_recommended"] is False

        # 2. 查看专栏详情
        detail_res = await ac.get(f"/columns/{col_id}", headers=headers_user)
        assert detail_res.status_code == 200
        assert detail_res.json()["category"] == "算法理论"
        assert detail_res.json()["article_count"] == 0
        assert detail_res.json()["like_count"] == 0
        assert detail_res.json()["star_count"] == 0
        assert detail_res.json()["comment_count"] == 0
        assert detail_res.json()["is_liked"] is False
        assert detail_res.json()["is_starred"] is False
        assert len(detail_res.json()["articles"]) == 0

        # 未被全站推荐的专栏不显示在文章广场公共列表
        plaza_col_before = await ac.get("/columns")
        assert plaza_col_before.status_code == 200
        assert not any(c["id"] == col_id for c in plaza_col_before.json()["items"])

        # 管理员可通过 is_recommended=false 查询待审核未推荐专栏
        admin_pending_cols = await ac.get("/columns?is_recommended=false", headers=headers_admin)
        assert admin_pending_cols.status_code == 200
        assert any(c["id"] == col_id for c in admin_pending_cols.json()["items"])

        # 作者可通过指定 author_id 查看自己的未推荐专栏
        author_cols = await ac.get(f"/columns?author_id={user_id}&category=算法理论")
        assert author_cols.status_code == 200
        assert any(c["id"] == col_id for c in author_cols.json()["items"])

        cat_other = await ac.get("/columns?category=娱乐")
        assert cat_other.status_code == 200
        assert not any(c["id"] == col_id for c in cat_other.json()["items"])

        # 3. 发布文章到专栏
        art_res = await ac.post(
            f"/columns/{col_id}/articles",
            headers=headers_user,
            json={
                "title": "分组背包详解与模板分析",
                "content": "本文介绍分组背包模型的转移方程与倒序遍历技巧，时间复杂度为 $O(VN)$。",
            },
        )
        assert art_res.status_code == 201, art_res.text
        art_data = art_res.json()
        art_id = art_data["id"]
        assert art_data["title"] == "分组背包详解与模板分析"
        assert art_data["view_count"] == 0

        # 4. 点赞测试
        like_res = await ac.post(f"/columns/{col_id}/like", headers=headers_admin)
        assert like_res.status_code == 200
        assert like_res.json()["liked"] is True
        assert like_res.json()["like_count"] == 1

        # 验证详情中显示已点赞
        detail_after_like = await ac.get(f"/columns/{col_id}", headers=headers_admin)
        assert detail_after_like.json()["is_liked"] is True
        assert detail_after_like.json()["like_count"] == 1

        # 再次点赞取消
        unlike_res = await ac.post(f"/columns/{col_id}/like", headers=headers_admin)
        assert unlike_res.status_code == 200
        assert unlike_res.json()["liked"] is False
        assert unlike_res.json()["like_count"] == 0

        # 5. 收藏测试
        star_res = await ac.post(f"/columns/{col_id}/star", headers=headers_admin)
        assert star_res.status_code == 200
        assert star_res.json()["starred"] is True
        assert star_res.json()["star_count"] == 1

        # 按收藏用户筛选专栏
        starred_cols = await ac.get(f"/columns?starred_by={admin_id}")
        assert starred_cols.status_code == 200
        assert any(c["id"] == col_id for c in starred_cols.json()["items"])

        # 7. 普通用户尝试设置全站推荐（应被拒绝 403）
        rec_fail = await ac.put(
            f"/columns/{col_id}/recommend",
            headers=headers_user,
            json={"is_recommended": True},
        )
        assert rec_fail.status_code == 403

        # 8. 管理员设置全站推荐（应成功）
        rec_ok = await ac.put(
            f"/columns/{col_id}/recommend",
            headers=headers_admin,
            json={"is_recommended": True},
        )
        assert rec_ok.status_code == 200
        assert rec_ok.json()["is_recommended"] is True

        # 9. 筛选推荐专栏（文章广场公共列表使用）
        rec_list = await ac.get("/columns")
        assert rec_list.status_code == 200
        items = rec_list.json()["items"]
        assert any(item["id"] == col_id for item in items)

        cat_rec_list = await ac.get("/columns?category=算法理论")
        assert cat_rec_list.status_code == 200
        assert any(item["id"] == col_id for item in cat_rec_list.json()["items"])

        # 10. 删除文章与专栏
        del_art = await ac.delete(
            f"/columns/{col_id}/articles/{art_id}",
            headers=headers_user,
        )
        assert del_art.status_code == 200

        del_col = await ac.delete(
            f"/columns/{col_id}",
            headers=headers_user,
        )
        assert del_col.status_code == 200

        # 11. 测试包含文章、点赞、评论时直接删除专栏
        col2_res = await ac.post(
            "/columns",
            headers=headers_user,
            json={"title": "级联删除测试专栏", "description": "测试", "category": "算法理论"},
        )
        assert col2_res.status_code == 201
        col2_id = col2_res.json()["id"]

        await ac.post(f"/columns/{col2_id}/articles", headers=headers_user, json={"title": "文章", "content": "内容"})
        await ac.post(f"/columns/{col2_id}/like", headers=headers_admin)
        await ac.post(f"/columns/{col2_id}/star", headers=headers_admin)
        await ac.post(f"/columns/{col2_id}/comments", headers=headers_admin, json={"content": "评论"})

        # 直接删除整个专栏
        del_col2 = await ac.delete(f"/columns/{col2_id}", headers=headers_user)
        assert del_col2.status_code == 200
        assert del_col2.json()["id"] == col2_id

        # 确认已查不到
        assert (await ac.get(f"/columns/{col2_id}")).status_code == 404

        # 12. 独立文章与单篇文章推荐测试
        # 发布独立文章（无需专栏）
        art_stand = await ac.post(
            "/articles",
            headers=headers_user,
            json={
                "title": "深入理解红黑树性质与平衡旋转",
                "content": "红黑树是一种二叉平衡查找树...",
                "category": "算法理论",
            },
        )
        assert art_stand.status_code == 201, art_stand.text
        art_stand_data = art_stand.json()
        assert art_stand_data["column_id"] is None
        assert art_stand_data["category"] == "算法理论"
        assert art_stand_data["is_recommended"] is False
        s_id = art_stand_data["id"]

        # 获取单篇文章详情（自动加阅读量）
        art_get = await ac.get(f"/articles/{s_id}")
        assert art_get.status_code == 200
        assert art_get.json()["view_count"] == 1

        # 未被全站推荐的文章不显示在文章广场
        plaza_before_rec = await ac.get("/articles")
        assert plaza_before_rec.status_code == 200
        assert not any(item["id"] == s_id for item in plaza_before_rec.json()["items"])

        # 管理员可通过 is_recommended=false 查询待审核未推荐文章
        plaza_admin_pending = await ac.get("/articles?is_recommended=false", headers=headers_admin)
        assert plaza_admin_pending.status_code == 200
        assert any(item["id"] == s_id for item in plaza_admin_pending.json()["items"])

        # 管理员单独设置文章推荐
        rec_art = await ac.put(
            f"/articles/{s_id}/recommend",
            headers=headers_admin,
            json={"is_recommended": True},
        )
        assert rec_art.status_code == 200
        assert rec_art.json()["is_recommended"] is True

        # 文章广场现在应包含已推荐的文章
        plaza_rec = await ac.get("/articles")
        assert plaza_rec.status_code == 200
        assert any(item["id"] == s_id for item in plaza_rec.json()["items"])

        # 文章点赞测试
        art_like = await ac.post(f"/articles/{s_id}/like", headers=headers_admin)
        assert art_like.status_code == 200
        assert art_like.json()["liked"] is True
        assert art_like.json()["like_count"] == 1

        # 文章取消点赞
        art_unlike = await ac.post(f"/articles/{s_id}/like", headers=headers_admin)
        assert art_unlike.status_code == 200
        assert art_unlike.json()["liked"] is False
        assert art_unlike.json()["like_count"] == 0

        # 重新点赞以供后续测试
        await ac.post(f"/articles/{s_id}/like", headers=headers_admin)

        # 文章收藏测试
        art_star = await ac.post(f"/articles/{s_id}/star", headers=headers_admin)
        assert art_star.status_code == 200
        assert art_star.json()["starred"] is True
        assert art_star.json()["star_count"] == 1

        # 文章评论测试（支持 Markdown / KaTeX）
        art_cmt_content = "非常受用的题解！复杂度 $O(N \\log N)$，感谢分享。\n\n```cpp\nint x = 1;\n```"
        art_cmt = await ac.post(
            f"/articles/{s_id}/comments",
            headers=headers_admin,
            json={"content": art_cmt_content},
        )
        assert art_cmt.status_code == 201
        cmt_id = art_cmt.json()["id"]

        # 文章详情中验证 counts 与 is_liked, is_starred
        detail_with_interactions = await ac.get(f"/articles/{s_id}", headers=headers_admin)
        assert detail_with_interactions.status_code == 200
        assert detail_with_interactions.json()["like_count"] == 1
        assert detail_with_interactions.json()["star_count"] == 1
        assert detail_with_interactions.json()["comment_count"] == 1
        assert detail_with_interactions.json()["is_liked"] is True
        assert detail_with_interactions.json()["is_starred"] is True

        # 删除文章评论
        del_cmt = await ac.delete(f"/articles/{s_id}/comments/{cmt_id}", headers=headers_admin)
        assert del_cmt.status_code == 200

        # 创建专栏并获取我的专栏列表
        my_col = await ac.post(
            "/columns",
            headers=headers_user,
            json={"title": "高级数据结构进阶专题", "category": "算法理论"},
        )
        assert my_col.status_code == 201
        m_col_id = my_col.json()["id"]

        my_cols_res = await ac.get("/columns/my", headers=headers_user)
        assert my_cols_res.status_code == 200
        assert any(c["id"] == m_col_id for c in my_cols_res.json())

        # 将独立文章归入专栏
        bind_res = await ac.put(
            f"/articles/{s_id}",
            headers=headers_user,
            json={"column_id": m_col_id},
        )
        assert bind_res.status_code == 200
        assert bind_res.json()["column_id"] == m_col_id
        assert bind_res.json()["column_title"] == "高级数据结构进阶专题"

        # 将文章脱离专栏变回独立文章
        detach_res = await ac.put(
            f"/articles/{s_id}",
            headers=headers_user,
            json={"detach_column": True},
        )
        assert detach_res.status_code == 200
        assert detach_res.json()["column_id"] is None

        # 删除单篇文章
        del_art_res = await ac.delete(f"/articles/{s_id}", headers=headers_user)
        assert del_art_res.status_code == 200
        assert (await ac.get(f"/articles/{s_id}")).status_code == 404


@pytest.mark.asyncio
async def test_column_inclusion_requests_workflow():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        headers_a, name_a, uid_a = await _register_and_login(ac, "usr_a")
        headers_b, name_b, uid_b = await _register_and_login(ac, "usr_b")

        # 1. 用户 A 创建专栏 A
        col_res = await ac.post(
            "/columns",
            headers=headers_a,
            json={"title": "算法竞赛经典专栏", "description": "合集收录高质量题解", "category": "算法理论"},
        )
        assert col_res.status_code == 201, col_res.text
        col_a_id = col_res.json()["id"]

        # 2. 用户 B 创建独立文章 B1 和 B2
        art1_res = await ac.post(
            "/articles",
            headers=headers_b,
            json={"title": "平衡树 Treap 深度探究", "content": "本文介绍 Treap 的各种操作", "category": "算法理论"},
        )
        assert art1_res.status_code == 201, art1_res.text
        art1_id = art1_res.json()["id"]

        art2_res = await ac.post(
            "/articles",
            headers=headers_b,
            json={"title": "二分图最大匹配匈牙利算法", "content": "匈牙利算法交替路", "category": "算法理论"},
        )
        assert art2_res.status_code == 201, art2_res.text
        art2_id = art2_res.json()["id"]

        # 3. 用户 B 申请将文章 B1 收录至专栏 A
        req1_res = await ac.post(
            f"/columns/{col_a_id}/inclusion-requests",
            headers=headers_b,
            json={"article_id": art1_id, "message": "优质平衡树教程，请求收录"},
        )
        assert req1_res.status_code == 201, req1_res.text
        req1_data = req1_res.json()
        assert req1_data["status"] == "pending"
        assert req1_data["column_id"] == col_a_id
        assert req1_data["article_id"] == art1_id
        assert req1_data["applicant_id"] == uid_b
        req1_id = req1_data["id"]

        # 重复提交应被拦截
        dup_res = await ac.post(
            f"/columns/{col_a_id}/inclusion-requests",
            headers=headers_b,
            json={"article_id": art1_id, "message": "重复申请"},
        )
        assert dup_res.status_code == 400
        assert "已提交过收录申请" in dup_res.json()["detail"]

        # 4. 用户 A 查看专栏的申请列表
        reqs_res = await ac.get(f"/columns/{col_a_id}/inclusion-requests", headers=headers_a)
        assert reqs_res.status_code == 200, reqs_res.text
        reqs_list = reqs_res.json()
        assert len(reqs_list) == 1
        assert reqs_list[0]["id"] == req1_id
        assert reqs_list[0]["article"]["title"] == "平衡树 Treap 深度探究"

        # 非专栏作者无法查看该专栏的申请列表
        forbidden_res = await ac.get(f"/columns/{col_a_id}/inclusion-requests", headers=headers_b)
        assert forbidden_res.status_code == 403

        # 用户 B 可以查看自己文章关联的申请
        my_reqs_res = await ac.get(f"/articles/{art1_id}/inclusion-requests", headers=headers_b)
        assert my_reqs_res.status_code == 200
        assert len(my_reqs_res.json()) == 1

        # 5. 用户 A 审核同意收录文章 B1
        approve_res = await ac.post(
            f"/columns/{col_a_id}/inclusion-requests/{req1_id}/review",
            headers=headers_a,
            json={"action": "approve", "reply": "内容扎实，欢迎收录！"},
        )
        assert approve_res.status_code == 200, approve_res.text
        assert approve_res.json()["status"] == "approved"
        assert approve_res.json()["reply"] == "内容扎实，欢迎收录！"

        # 验证文章 B1 的 column_id 变为专栏 A
        art1_after = await ac.get(f"/articles/{art1_id}")
        assert art1_after.status_code == 200
        assert art1_after.json()["column_id"] == col_a_id

        # 验证专栏 A 详情中已包含文章 B1
        col_detail = await ac.get(f"/columns/{col_a_id}")
        assert col_detail.status_code == 200
        assert col_detail.json()["article_count"] == 1
        assert col_detail.json()["articles"][0]["id"] == art1_id
        assert col_detail.json()["articles"][0]["author"]["id"] == uid_b

        # 6. 用户 B 申请文章 B2 并由用户 A 拒绝
        req2_res = await ac.post(
            f"/columns/{col_a_id}/inclusion-requests",
            headers=headers_b,
            json={"article_id": art2_id, "message": "二分图教程"},
        )
        assert req2_res.status_code == 201
        req2_id = req2_res.json()["id"]

        reject_res = await ac.post(
            f"/columns/{col_a_id}/inclusion-requests/{req2_id}/review",
            headers=headers_a,
            json={"action": "reject", "reply": "当前合集暂只收录数据结构类文章"},
        )
        assert reject_res.status_code == 200
        assert reject_res.json()["status"] == "rejected"
        assert reject_res.json()["reply"] == "当前合集暂只收录数据结构类文章"

        # 文章 B2 仍为独立文章
        art2_after = await ac.get(f"/articles/{art2_id}")
        assert art2_after.json()["column_id"] is None

        # 7. 用户 A 将文章 B1 移出专栏（文章不删除）
        detach_res = await ac.post(
            f"/columns/{col_a_id}/articles/{art1_id}/detach",
            headers=headers_a,
        )
        assert detach_res.status_code == 200, detach_res.text
        assert (await ac.get(f"/articles/{art1_id}")).json()["column_id"] is None
        assert (await ac.get(f"/columns/{col_a_id}")).json()["article_count"] == 0
