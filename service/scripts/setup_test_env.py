#!/usr/bin/env python3
"""
快速搭建本地测试环境脚本

功能：
1. 创建 SQLite 测试数据库并初始化表结构
2. 插入 3 个测试用户（普通用户、管理员、超级管理员）
3. 插入若干测试帖子（讨论区）和评论
4. 插入若干测试犇犇（动态）及回复
5. 插入若干测试图床图片记录

使用方法：
    cd service/
    python -m scripts.setup_test_env

注意：此脚本仅用于本地开发测试，不会覆盖生产数据库。
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# 确保 service 目录在 Python 路径中
SERVICE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SERVICE_DIR))

from app.core.config import Settings  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.forum import ForumPost, ForumComment  # noqa: 402
from app.models.benben import Benben  # noqa: E402


# ==================== 常量 ====================

TEST_DB_PATH = SERVICE_DIR / "test_oj.db"
DATABASE_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"

# 密码统一为 test1234（bcrypt 哈希）
TEST_PASSWORD_HASH = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36HJffVXfYtpCC6zVOUuK5u"  # bcrypt hash of "test1234"


def print_step(title: str) -> None:
    """打印步骤标题"""
    print(f"\n{'='*60}")
    print(f"  📦 {title}")
    print(f"{'='*60}")


def print_success(msg: str) -> None:
    """打印成功信息"""
    print(f"  ✅ {msg}")


def print_info(msg: str) -> None:
    """打印普通信息"""
    print(f"  ℹ️  {msg}")


def print_error(msg: str) -> None:
    """打印错误信息"""
    print(f"  ❌ {msg}")


async def init_database(engine, settings: Settings | None = None):
    """创建所有表结构（SQLite 环境下等效于 Alembic upgrade）"""
    from app.models.base import Base

    # 导入所有模型以确保 registry 注册
    import app.models.refresh_token  # noqa: F401
    import app.models.tag_card  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print_success("数据库表结构已创建")


async def create_users(session: AsyncSession):
    """创建 3 个测试用户"""
    print_step("👥 创建测试用户")

    users_data = [
        {
            "username": "testuser01",
            "email": "test01@example.com",
            "phone": "13800138001",
            "hashed_password": TEST_PASSWORD_HASH,
            "user_number": 10001,
            "is_admin": False,
            "is_super_admin": False,
            "can_speak": True,
            "user_tag": "入门者",
            "experience": 100,
            "bio": "这是一个普通测试用户的简介",
        },
        {
            "username": "admin_test",
            "email": "admin@test.com",
            "phone": "13800138002",
            "hashed_password": TEST_PASSWORD_HASH,
            "user_number": 10002,
            "is_admin": True,
            "is_super_admin": False,
            "can_speak": True,
            "user_tag": "管理员",
            "experience": 5000,
            "bio": "这是管理员测试账号\n权限：全量管理",
        },
        {
            "username": "superadmin_test",
            "email": "superadmin@test.com",
            "phone": "13800138003",
            "hashed_password": TEST_PASSWORD_HASH,
            "user_number": 10003,
            "is_admin": True,
            "is_super_admin": True,
            "can_speak": True,
            "user_tag": "超级管理员",
            "experience": 10000,
            "bio": "这是超级管理员测试账号\n权限：最高权限，可执行所有操作",
        },
    ]

    created_users = []
    for data in users_data:
        user = User(**data)
        session.add(user)
        created_users.append(user)
        print_success(
            f"用户 #{data['user_number']} {data['username']} "
            f"(邮箱：{data['email']})"
        )

    await session.commit()
    return created_users


async def create_forum_posts(session: AsyncSession, users: list[User]):
    """创建测试帖子和评论"""
    print_step("📝 创建测试帖子与评论")

    posts_data = [
        {
            "title": "【新手指南】如何开始你的 OJ 之旅？",
            "content": (
                "# OJ 使用指南\n\n欢迎来到 NLNOJ！本指南将帮助你快速上手。\n\n## 1. 注册账号\n- 前往注册页面填写信息\n- 完成邮箱验证\n\n## 2. 熟悉界面\n- **题目列表**：查看所有可用题目\n- **评测记录**：查看你的提交历史\n- **讨论区**：与其他选手交流\n\n## 3. 开始做题\n建议从简单题开始，逐步挑战更难的问题。\n\n> 💡 提示：善用搜索功能和题解，但不要直接抄袭哦！\n\n祝你在算法之路上越走越远！🚀"
            ),
            "forum": "academics",
            "author_id": users[0].id,
            "is_pinned": True,
            "is_locked": False,
        },
        {
            "title": "关于最近比赛的一些说明",
            "content": (
                "## 比赛须知\n\n1. 请按时参赛\n2. 严禁作弊\n3. 如有问题请在工单系统反馈\n\n## 常见问题\n- **Q**: 可以组队吗？\n- **A**: 本次比赛支持单人赛，暂不支持组队。\n- **Q**: 成绩何时公布？\n- **A**: 赛后 24 小时内公布最终排名。"
            ),
            "forum": "siteaffairs",
            "author_id": users[1].id,
            "is_pinned": True,
            "is_locked": False,
        },
        {
            "title": "灌水专区：今天你刷题了吗？",
            "content": (
                "今天刷了几道题？来聊聊你的刷题日常吧！\n\n我今天是这样的：\n```python\ndef daily_checkin():\n    if AC_count > 0:\n        return \"今天也很努力呢！\"\n    else:\n        return \"明天继续加油\"\n```\n\n分享你的今日战绩~ 😄"
            ),
            "forum": "relevantaffairs",
            "author_id": users[2].id,
            "is_pinned": False,
            "is_locked": False,
        },
        {
            "title": "【讨论】Dijkstra 算法的优化思路",
            "content": (
                "最近在学习最短路算法，分享一下我的笔记：\n\n## Dijkstra 优化\n\n常用优化手段：\n1. **堆优化**：使用优先队列降低时间复杂度\n2. **剪枝**：提前结束不必要的计算\n3. **邻接表**：存储稀疏图更高效\n\n```cpp\npriority_queue<pair<int,int>, vector<pair<int,int>>, greater<pair<int,int>>> pq;\npq.push({0, start});\nwhile (!pq.empty()) {\n    auto [d, u] = pq.top();\n    pq.pop();\n    if (d > dist[u]) continue;\n    // ... 处理逻辑\n}\n```\n\n大家还有什么其他优化技巧吗？欢迎讨论！"
            ),
            "forum": "problem",
            "author_id": users[0].id,
            "is_pinned": False,
            "is_locked": False,
        },
    ]

    created_posts = []
    for data in posts_data:
        post = ForumPost(**data)
        session.add(post)
        created_posts.append(post)
        print_success(f"帖子：《{data['title']}》 ({data['forum']})")

    await session.commit()

    # 创建评论
    comments_data = [
        {"post_id": created_posts[0].id, "author_id": users[1].id, "content": "感谢分享！作为新人很有帮助 👍"},
        {"post_id": created_posts[0].id, "author_id": users[2].id, "content": "建议补充一些在线判题系统的对比内容"},
        {"post_id": created_posts[1].id, "author_id": users[0].id, "content": "明白了，已经仔细阅读了规则"},
        {"post_id": created_posts[2].id, "author_id": users[0].id, "content": "今天 AC 了一道蓝题！开心~"},
        {"post_id": created_posts[2].id, "author_id": users[1].id, "content": "我也来了，今天打算再刷两道中等题"},
        {"post_id": created_posts[3].id, "author_id": users[2].id, "content": "堆优化确实效果好，推荐一下 fib heap 也可以考虑"},
        {"post_id": created_posts[3].id, "author_id": users[1].id, "content": "还有 SPFA 算法在某些场景下更快"},
    ]

    for comment_data in comments_data:
        comment = ForumComment(**comment_data)
        session.add(comment)

    await session.commit()
    print_success(f"共创建 {len(comments_data)} 条评论")
    return created_posts


async def create_benbens(session: AsyncSession, users: list[User], posts: list[ForumPost]):
    """创建测试犇犇（动态）"""
    print_step("🐂 创建测试犇犇（动态）")

    benben_data = [
        {"user_number": users[0].user_number, "content": "终于 AC 了第一道紫题！感觉人生到达了巅峰 🎉", "reply_to": None},
        {"user_number": users[1].user_number, "content": "今天给大家发福利啦！关注 + 点赞，评论区抽三位送 OJ 会员！", "reply_to": None},
        {"user_number": users[2].user_number, "content": "刚更新了后台管理系统的新功能，欢迎大家体验反馈~", "reply_to": None},
        {"user_number": users[0].user_number, "content": "求教一道题：最长上升子序列的 O(n log n) 解法怎么写呀？", "reply_to": None},
        {"user_number": users[1].user_number, "content": "上面那位同学，可以用二分查找优化 DP 啊！", "reply_to": None},
        {"user_number": users[2].user_number, "content": "没错，维护一个单调递增序列即可。可以参考洛谷 P10207", "reply_to": None},
    ]

    created_benbens = []
    for data in benben_data:
        benben = Benben(
            user_number=data["user_number"],
            content=data["content"],
            reply_to=data["reply_to"],
        )
        session.add(benben)
        created_benbens.append(benben)
        print_success(f"犇犇 {data['content'][:30]}...")

    await session.commit()
    return created_benbens


async def create_image_records(session: AsyncSession):
    """创建测试图床图片记录"""
    print_step("🖼️  创建测试图床图片")

    image_urls = [
        "https://picsum.photos/seed/oj1/800/600",
        "https://picsum.photos/seed/oj2/1024/768",
        "https://picsum.photos/seed/oj3/500/300",
        "https://picsum.photos/seed/oj4/640/480",
        "https://picsum.photos/seed/oj5/1200/800",
    ]

    sample_filenames = ["test_bg.png", "test_avatar.jpg", "test_logo.gif", "test_banner.webp", "test_cover.jpeg"]

    created_images = []
    for i, url in enumerate(image_urls):
        # 这里只创建记录，实际文件需要手动放入 static/uploads/images/ 目录
        # 或者使用 HTTP 请求下载
        from app.models.image import ImageFile  # noqa: E402

        image = ImageFile(
            filename=sample_filenames[i],
            url=url,
            mimetype="image/png",
            size=1024 * 1024,  # 模拟 1MB
            uploader_id=1,
        )
        session.add(image)
        created_images.append(image)
        print_success(f"图片 {i+1}: {sample_filenames[i]}")

    await session.commit()
    print_success(f"共创建 {len(created_images)} 张图床图片记录")

    # 提示用户手动准备图片文件
    upload_dir = SERVICE_DIR / "static" / "uploads" / "images"
    upload_dir.mkdir(parents=True, exist_ok=True)
    print_info(f"图片上传目录已创建：{upload_dir}")
    print_info("请将真实图片文件放入该目录以完整测试图床功能")

    return created_images


async def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("  🚀 NLNOJ 本地测试环境快速搭建工具")
    print("=" * 60)

    # 如果数据库已存在，询问是否删除
    if TEST_DB_PATH.exists():
        print(f"\n⚠️  警告：数据库文件 {TEST_DB_PATH} 已存在")
        answer = input("是否删除并重建？[y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("已取消操作")
            return

    # 1. 创建引擎和会话
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        # 2. 初始化数据库表结构
        async with async_session() as session:
            await init_database(engine)

            # 3. 创建测试用户
            users = await create_users(session)

            # 4. 创建测试帖子和评论
            posts = await create_forum_posts(session, users)

            # 5. 创建测试犇犇
            benbens = await create_benbens(session, users, posts)

            # 6. 创建测试图床图片记录
            images = await create_image_records(session)

        # 7. 显示总结信息
        print("\n" + "=" * 60)
        print("  ✅ 测试环境搭建完成！")
        print("=" * 60)
        print(f"\n📊 数据统计：")
        print(f"  • 数据库文件：{TEST_DB_PATH}")
        print(f"  • 测试用户：3 个")
        print(f"  • 测试帖子：{len(posts)} 个（含 7 条评论）")
        print(f"  • 测试犇犇：{len(benbens)} 条")
        print(f"  • 图床图片：{len(images)} 条记录")
        print(f"\n👤 测试账号：")
        print(f"  • testuser01 / test1234 （普通用户）")
        print(f"  • admin_test / test1234 （管理员）")
        print(f"  • superadmin_test / test1234 （超级管理员）")
        print(f"\n🔧 启动后端服务：")
        print(f"  cd service/")
        print(f"  uv run fastapi dev --factory app.main:create_app")
        print(f"  # 或使用:")
        print(f"  python -m uvicorn app.main:create_app --reload")

    except Exception as e:
        print_error(f"发生错误：{e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
