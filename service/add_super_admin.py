"""创建超级管理员用户脚本"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.core.security import hash_password
from app.models.user import User
from app.models.base import Base
from dotenv import load_dotenv
import os

async def create_super_admin(target_username: str, target_password: str):
    """创建或升级超级管理员用户"""

    # 加载环境变量
    load_dotenv()

    database_url = os.getenv("DATABASE_URL") or "sqlite+aiosqlite:///./oj.db"
    print(f"连接数据库: {database_url[:50]}...")

    # 创建数据库引擎
    engine = create_async_engine(database_url, echo=False)

    # 创建表（如果不存在）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 创建会话
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(User).where(User.username == target_username)
        )
        existing_user = result.scalar_one_or_none()

        if existing_user:
            print(f"用户 {target_username} 已存在，升级为超级管理员...")
            existing_user.is_super_admin = True
            existing_user.is_admin = True
            existing_user.is_banned = False
            existing_user.is_active = True
            existing_user.can_manage_users = True
            existing_user.can_manage_posts = True
            existing_user.can_manage_problems = True
            existing_user.can_assign_admin = True
            existing_user.can_manage_tags = True
            existing_user.can_speak = True

            await session.commit()
            print(f"用户 {target_username} (ID: {existing_user.id}) 已成功升级为超级管理员!")

        else:
            print(f"创建新的超级管理员用户 {target_username}...")

            # 获取下一个用户编号
            result = await session.execute(select(User.id))
            existing_users = result.scalars().all()
            user_number = len(existing_users) + 1

            super_admin = User(
                username=target_username,
                email=f"{target_username.lower().strip('_')}@admin.com",
                hashed_password=hash_password(target_password),
                user_number=user_number,
                phone=None,

                # 状态设置
                is_active=True,
                is_banned=False,
                is_cheater=False,

                # 管理员权限
                is_super_admin=True,
                is_admin=True,
                can_speak=True,
                can_manage_users=True,
                can_manage_posts=True,
                can_manage_problems=True,
                can_assign_admin=True,
                can_manage_tags=True,

                # 个性化信息
                avatar_url=None,
                user_tag="超级管理员",
                username_color="#FF0000",
                bio="系统超级管理员，拥有最高权限"
            )

            session.add(super_admin)
            await session.commit()
            await session.refresh(super_admin)

            print(f"超级管理员用户创建成功!")
            print(f"用户ID: {super_admin.id}")
            print(f"用户名: {super_admin.username}")
            print("请使用创建时指定的密码登录")
            print(f"邮箱: {super_admin.email}")
            print(f"用户编号: {super_admin.user_number}")
            print(f"超级管理员权限: {super_admin.is_super_admin}")

    await engine.dispose()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("错误: 必须提供用户名和密码参数")
        print("用法: python add_super_admin.py <username> <password>")
        sys.exit(1)

    uname = sys.argv[1]
    pwd = sys.argv[2]
    print(f"目标用户: {uname}")
    asyncio.run(create_super_admin(uname, pwd))