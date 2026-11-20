"""犇犇业务逻辑服务。"""

from __future__ import annotations

from typing import Optional
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.benben import Benben
from app.models.user import User
from app.schemas.benben import BenbenCreate, BenbenResponse
from app.models.report import REPORT_BENBEN
from app.services import moderation
from app.services.moderation import REASON_MODERATOR, REASON_SELF
from app.services.notification import notify_mentions


class BenbenService:
    """犇犇业务服务"""

    MAX_LENGTH_NORMAL = 1000  # 普通用户最大字数（原 500 翻倍）
    MAX_LENGTH_ADMIN = 10000  # 管理员最大字数（原 5000 翻倍）

    @staticmethod
    async def create_benben(
        db: AsyncSession,
        user_number: int,
        content: str,
        reply_to: Optional[int] = None,
        is_admin: bool = False
    ) -> Benben:
        """创建新的犇犇"""
        # 检查用户权限
        user = await db.execute(
            select(User).where(User.user_number == user_number)
        )
        user_obj = user.scalar_one_or_none()

        if not user_obj:
            raise ValueError("用户不存在")

        if user_obj.can_speak is False:
            raise PermissionError("你已被禁言，无法发布动态")

        # 字数限制
        max_length = BenbenService.MAX_LENGTH_ADMIN if is_admin else BenbenService.MAX_LENGTH_NORMAL
        if len(content) > max_length:
            content = content[:max_length]

        # 如果是回复，检查原犇犇是否存在
        if reply_to:
            original = await db.execute(
                select(Benben).where(Benben.id == reply_to)
            )
            if not original.scalar_one_or_none():
                raise ValueError("回复的犇犇不存在")

        # 创建犇犇
        benben = Benben(
            user_number=user_number,
            content=content,
            reply_to=reply_to
        )
        db.add(benben)
        await db.flush()
        # 正文里的 @ → 提及通知。回复别人的犇犇时，前端也是往正文里插 @，
        # 所以这里一并覆盖了「回复犇犇」的场景
        await notify_mentions(
            db, benben.content, actor=user_obj, link="/", where="犇犇",
        )
        await db.commit()
        await db.refresh(benben)

        return benben

    @staticmethod
    async def get_benben_list(
        db: AsyncSession,
        limit: int = 20,
        before_id: Optional[int] = None,
        after_id: Optional[int] = None,
        mode: str = "all",
        user_number: Optional[int] = None,
        author_number: Optional[int] = None
    ) -> list[Benben]:
        """获取犇犇列表。

        ``before_id`` 向下翻页（加载更多），``after_id`` 向上增量拉取
        （前端自动刷新用：没新动态时返回空数组，很轻）。
        ``user_number`` 是当前登录用户（只给 mode="my" 用）；
        ``author_number`` 是「只看这个作者的」（用户主页的动态标签页用）。
        """
        query = select(Benben).options(selectinload(Benben.user)).order_by(desc(Benben.created_at))
        # 软删除的不在前台展示
        query = query.where(Benben.is_deleted.is_(False))

        # 分页查询
        if before_id:
            query = query.where(Benben.id < before_id)

        # 增量拉取：只要比这个 id 新的
        if after_id is not None:
            query = query.where(Benben.id > after_id)

        # 指定作者的动态（用户主页）
        if author_number is not None:
            query = query.where(Benben.user_number == author_number)
        # 只看自己的动态
        elif mode == "my" and user_number:
            query = query.where(Benben.user_number == user_number)

        query = query.limit(limit)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def delete_benben(
        db: AsyncSession,
        benben_id: int,
        operator: User
    ) -> bool:
        """删除犇犇（软删除，连带回复一起删）。

        作者本人可删自己的；秩序管理（can_manage_posts / 管理员 / 超管）
        可删任何人的。内容保留在数据库，供举报后台查看。
        """
        result = await db.execute(
            select(Benben).where(Benben.id == benben_id)
        )
        benben = result.scalar_one_or_none()

        if not benben or benben.is_deleted:
            raise ValueError("犇犇不存在")

        is_self = benben.user_number == operator.user_number
        if not is_self and not moderation.is_order_admin(operator):
            raise PermissionError("你无权删除这条动态")

        await moderation.soft_delete_target(
            db,
            REPORT_BENBEN,
            benben,
            reason=REASON_SELF if is_self else REASON_MODERATOR,
            admin_id=operator.id,
        )
        return True

    @staticmethod
    def enrich_benben_with_user_info(benben_list: list[Benben], current_user_number: Optional[int] = None) -> list[dict]:
        """为犇犇添加用户信息"""
        result = []
        for benben in benben_list:
            # 获取用户信息
            user = benben.user
            username = user.username if user else '未知用户'

            # 构建响应数据
            benben_dict = {
                "id": benben.id,
                "user_number": benben.user_number,
                "content": benben.content,
                "reply_to": benben.reply_to,
                "created_at": benben.created_at,
                "username": username,
                "avatar_url": user.avatar_url if user else None,
                "is_admin": user.is_admin if user else False,
                "is_super_admin": user.is_super_admin if user else False,
                "is_big_admin": getattr(user, "is_big_admin", False) if user else False,
                "is_banned": user.is_banned if user else False,
                "is_cheater": user.is_cheater if user else False,
                "can_manage_users": user.can_manage_users if user else False,
                "can_manage_posts": user.can_manage_posts if user else False,
                "can_manage_problems": user.can_manage_problems if user else False,
                "username_color": user.username_color if user else None,
                "color_tier": user.color_tier if user else "gray",
                "name_color": user.name_color if user else "",
                "user_tag": user.display_tag if user else None,
                "is_owner": current_user_number == benben.user_number if current_user_number else False,
                "last_seen": user.last_seen.isoformat() if user and user.last_seen else None,
            }

            # 添加回复信息
            if benben.reply_to:
                # 这里可以查询被回复的犇犇信息，暂时设为None
                benben_dict["reply_to_username"] = None

            result.append(benben_dict)

        return result


# 服务实例
benben_service = BenbenService()
