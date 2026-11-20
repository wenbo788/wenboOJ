"""讨论区业务逻辑。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, or_, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import permissions as perm
from app.models.forum import ForumComment, ForumPost
from app.models.user import User
from app.services.moderation import (
    REASON_MODERATOR,
    REASON_SELF,
)
from app.services.notification import (
    TITLE_MAX,
    add_notification,
    clip,
    notify_mentions,
)

VALID_FORUMS = ("siteaffairs", "problem", "academics", "relevantaffairs")
FORUM_NAMES = {
    "siteaffairs": "站务版",
    "problem": "题目总版",
    "academics": "学术版",
    "relevantaffairs": "灌水区",
}


class ForumService:
    @staticmethod
    def _user_brief(user: User | None) -> dict[str, Any]:
        if user is None:
            return {
                "user_id": None,
                "username": "已删除用户",
                "user_tag": "",
                "is_admin": False,
                "is_super_admin": False,
                "is_banned": False,
                "is_cheater": False,
                "can_manage_users": False,
                "can_manage_posts": False,
                "can_manage_problems": False,
                "color_tier": "gray",
                "name_color": "",
                "user_number": None,
                "avatar_url": "",
                "last_seen": None,
            }
        return {
            "user_id": user.id,
            "username": user.username,
            "user_tag": user.display_tag,
            "is_admin": bool(user.is_admin),
            "is_super_admin": bool(user.is_super_admin),
            "is_banned": bool(user.is_banned),
            "is_cheater": bool(user.is_cheater),
            "can_manage_users": bool(user.can_manage_users),
            "can_manage_posts": bool(user.can_manage_posts),
            "can_manage_problems": bool(user.can_manage_problems),
            "color_tier": user.color_tier or "gray",
            "name_color": user.name_color,
            "user_number": user.user_number,
            "avatar_url": user.avatar_url or "",
            "last_seen": user.last_seen.isoformat() if user.last_seen else None,
        }

    @staticmethod
    def _problem_brief(problem) -> dict[str, Any] | None:
        if problem is None:
            return None
        return {
            "id": problem.id,
            "problem_number": problem.problem_number,
            "title": problem.title,
            "difficulty": problem.difficulty,
        }

    @staticmethod
    def _post_dict(post: ForumPost, reply_count: int = 0) -> dict[str, Any]:
        return {
            "id": post.id,
            "title": post.title,
            "content": post.content,
            "forum": post.forum,
            "forum_name": FORUM_NAMES.get(post.forum, post.forum),
            "is_pinned": bool(post.is_pinned),
            "is_locked": bool(post.is_locked),
            "problem_id": post.problem_id,
            "problem": ForumService._problem_brief(post.problem),
            "created_at": post.created_at.isoformat() if post.created_at else None,
            "author": ForumService._user_brief(post.author),
            "reply_count": reply_count,
        }

    @staticmethod
    def _comment_dict(comment: ForumComment) -> dict[str, Any]:
        return {
            "id": comment.id,
            "post_id": comment.post_id,
            "content": comment.content,
            "is_pinned": bool(comment.is_pinned),
            "created_at": comment.created_at.isoformat() if comment.created_at else None,
            "author": ForumService._user_brief(comment.author),
        }

    @staticmethod
    async def list_posts(
        db: AsyncSession,
        *,
        forum: Optional[str] = None,
        exclude_forum: Optional[str] = None,
        page: int = 0,
        page_size: int = 30,
        keyword: Optional[str] = None,
    ) -> dict[str, Any]:
        """帖子列表（倒序分页，附带回复数与作者信息）。

        keyword 供管理端「选帖子」搜索用（标题/正文模糊匹配）。
        exclude_forum 用来整块屏蔽某个版块（学术模式屏蔽灌水区），
        和 forum 同时给时互不冲突：先选中一个版块，再看要不要排掉另一个。
        """
        query = select(ForumPost).options(
            selectinload(ForumPost.author),
            selectinload(ForumPost.problem),
        )
        # 软删除的帖子不在前台展示
        query = query.where(ForumPost.is_deleted.is_(False))
        if forum and forum != "all":
            query = query.where(ForumPost.forum == forum)
        if exclude_forum and exclude_forum != "all":
            query = query.where(ForumPost.forum != exclude_forum)
        if keyword and keyword.strip():
            like = f"%{keyword.strip()}%"
            query = query.where(
                or_(ForumPost.title.ilike(like), ForumPost.content.ilike(like))
            )

        count_q = select(sa_func.count()).select_from(query.subquery())
        total = (await db.execute(count_q)).scalar() or 0

        result = await db.execute(
            query.order_by(
                ForumPost.is_pinned.desc(),
                ForumPost.created_at.desc(),
                ForumPost.id.desc(),
            )
            .offset(page * page_size)
            .limit(page_size)
        )
        posts = result.scalars().unique().all()

        # 批量统计回复数
        counts: dict[int, int] = {}
        if posts:
            ids = [p.id for p in posts]
            rows = await db.execute(
                select(ForumComment.post_id, sa_func.count())
                .where(
                    ForumComment.post_id.in_(ids),
                    ForumComment.is_deleted.is_(False),
                )
                .group_by(ForumComment.post_id)
            )
            counts = {pid: n for pid, n in rows.all()}

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "posts": [ForumService._post_dict(p, counts.get(p.id, 0)) for p in posts],
        }

    @staticmethod
    async def recent_posts(db: AsyncSession, limit: int = 10) -> list[dict[str, Any]]:
        """主页「近期讨论」。"""
        data = await ForumService.list_posts(db, page=0, page_size=limit)
        return data["posts"]

    @staticmethod
    async def get_post(db: AsyncSession, post_id: int) -> Optional[ForumPost]:
        result = await db.execute(
            select(ForumPost)
            .options(
                selectinload(ForumPost.author),
                selectinload(ForumPost.problem),
                selectinload(ForumPost.comments).selectinload(ForumComment.author),
            )
            .where(ForumPost.id == post_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_post(
        db: AsyncSession, author: User, title: str, content: str, forum: str,
        problem_id: int | None = None,
    ) -> ForumPost:
        if forum not in VALID_FORUMS:
            raise ValueError("无效的版块")
        post = ForumPost(
            title=title.strip(),
            content=content.strip(),
            forum=forum,
            author_id=author.id,
            problem_id=problem_id,
        )
        db.add(post)
        await db.flush()
        # 正文里的 @ → 提及通知（发帖时就要发，否则得等别人点开才看得到）
        await notify_mentions(
            db, post.content, actor=author, link=f"/discuss/{post.id}",
            where=f"帖子「{clip(post.title, TITLE_MAX)}」",
        )
        await db.commit()
        await db.refresh(post)
        return post

    @staticmethod
    async def update_post(
        db: AsyncSession, post: ForumPost, title: str, content: str,
        problem_id: int | None = None,
    ) -> ForumPost:
        """编辑已发布帖子的标题与正文（仅秩序管理，由 API 层校验）。"""
        post.title = title.strip()
        post.content = content.strip()
        post.problem_id = problem_id
        await db.commit()
        await db.refresh(post)
        return post

    @staticmethod
    async def add_comment(db: AsyncSession, post: ForumPost, author: User, content: str) -> ForumComment:
        comment = ForumComment(
            post_id=post.id,
            author_id=author.id,
            content=content.strip(),
        )
        db.add(comment)
        await db.flush()

        link = f"/discuss/{post.id}"
        title = clip(post.title, TITLE_MAX)
        # 回复楼主 → 「回复」通知（原来帖子被回复是完全没有消息的）
        add_notification(
            db,
            user_id=post.author_id,
            ntype="reply",
            actor_id=author.id,
            link=link,
            content=f"@{author.username} 回复了你的帖子「{title}」，快来看看吧",
        )
        # 正文里的 @ → 「提及」通知。被 @ 不代表被回复，所以单开一类；
        # 回复某条回复时前端只帮作者 @ 一下对方，靠的就是这里
        await notify_mentions(
            db, comment.content, actor=author, link=link,
            where=f"帖子「{title}」",
        )
        await db.commit()
        await db.refresh(comment)
        return comment

    @staticmethod
    async def delete_post(db: AsyncSession, post: ForumPost, operator: User) -> None:
        """作者本人或秩序管理可删除（软删除，内容保留供举报后台查看）。"""
        is_self = post.author_id == operator.id
        if not is_self and not (
            operator.can_manage_posts or operator.is_admin or operator.is_super_admin
        ):
            raise PermissionError("无权删除该帖子")
        post.is_deleted = True
        post.deleted_at = datetime.now(timezone.utc)
        post.deleted_by_id = operator.id
        post.delete_reason = REASON_SELF if is_self else REASON_MODERATOR
        await db.commit()

    @staticmethod
    async def delete_comment(
        db: AsyncSession, comment: ForumComment, post: ForumPost, operator: User
    ) -> None:
        """删除帖子回复（软删除）。

        仅秩序管理、回复发送者本人、帖子发送者本人可删除。
        """
        allowed = (
            comment.author_id == operator.id
            or post.author_id == operator.id
            or operator.can_manage_posts
            or operator.is_admin
            or operator.is_super_admin
        )
        if not allowed:
            raise PermissionError("无权删除该回复")
        is_moderator = (
            operator.can_manage_posts
            or operator.is_admin
            or operator.is_super_admin
        ) and comment.author_id != operator.id
        comment.is_deleted = True
        comment.deleted_at = datetime.now(timezone.utc)
        comment.deleted_by_id = operator.id
        comment.delete_reason = (
            REASON_MODERATOR if is_moderator else REASON_SELF
        )
        await db.commit()

    @staticmethod
    async def can_manage(user: Optional[User]) -> bool:
        """能否管理讨论区（置顶/锁定帖子、置顶/删除回复）。

        走权限真源（``permissions.can_manage_community``）：白名单 / 超管 /
        大管 / 持有 can_manage_posts 的社管均可，与站内其他社区管理入口一致。
        此前用的是裸字段 ``can_manage_posts or is_admin or is_super_admin``，
        会把白名单与大管挡在外面。
        """
        return bool(user and perm.can_manage_community(user))
