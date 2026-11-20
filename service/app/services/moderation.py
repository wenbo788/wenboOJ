"""秩序管理业务：软删除/恢复、梯度禁言。

举报规则：
- 有效举报达到 6 人（第 6 人提交时）自动软删除内容；
- 禁言时长按「该用户同类违规的历史次数」走梯度：
  第 1 次 1 天 / 第 2 次 7 天 / 第 3 次 14 天 / 第 4 次起永久；
- 恶意举报（举报不成立）与内容违规（举报成立）的次数分别计数。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.benben import Benben
from app.models.forum import ForumComment, ForumPost
from app.models.judgement import JudgementLog
from app.models.report import (
    REPORT_BENBEN,
    REPORT_COMMENT,
    REPORT_POST,
    TARGET_TYPES,
)
from app.models.user import User
from app import permissions as perm

# ---- 举报分类 ----
CATEGORY_ABUSE = "abuse"                 # 辱骂攻击/人肉
CATEGORY_SPAM = "spam"                   # 广告刷屏
CATEGORY_PORN_ILLEGAL = "porn_illegal"   # 色情违法
CATEGORY_INFRINGE_OTHER = "infringe_other"  # 侵权抄袭/其他
REPORT_CATEGORIES = (
    CATEGORY_ABUSE,
    CATEGORY_SPAM,
    CATEGORY_PORN_ILLEGAL,
    CATEGORY_INFRINGE_OTHER,
)
CATEGORY_NAMES = {
    CATEGORY_ABUSE: "辱骂攻击/人肉",
    CATEGORY_SPAM: "广告刷屏",
    CATEGORY_PORN_ILLEGAL: "色情违法",
    CATEGORY_INFRINGE_OTHER: "侵权抄袭/其他",
}

# 第 N 次（从 1 开始）→ 禁言时长，None = 永久
# 索引 0=第1次 … 3=第4次及以后
MUTE_LADDER: list[tuple[Optional[int], str]] = [
    (1, "1天"),
    (7, "7天"),
    (14, "14天"),
    (None, "永久"),
]

# 触发自动删除的有效举报数
AUTO_DELETE_THRESHOLD = 6

# 删除原因
REASON_MULTI = "multi_report"       # 多人举报自动删除
REASON_MODERATOR = "moderator"      # 秩序管理删除
REASON_SELF = "self"                # 作者自删
REASON_GUILTY = "report_guilty"     # 举报成立后删除

TARGET_NAMES = {
    REPORT_BENBEN: "犇犇",
    REPORT_POST: "帖子",
    REPORT_COMMENT: "帖子回复",
}


def is_order_admin(user: Optional[User]) -> bool:
    """秩序管理：与「管理名单 → 秩序管理」那一列同口径（``can_manage_community``）。

    真源 = 白名单/超管/大管，或持有 ``can_manage_posts`` 字段的人。这里原先读裸
    字段（``can_manage_posts or is_admin or is_super_admin``），后果是**白名单和
    大管被挡在外面**：前端菜单/路由守卫用的是 ``canManageCommunity``（真源），
    于是他们能点进举报审核页，进去之后每个请求都 403 —— 又是「名单上有、活干不了」。

    ``is_admin``（泛管理员）保留放行：名单只承诺「上了名单就有权限」，不承诺
    「没上名单就没权限」，所以这里只加权限、不收权限（后台其它入口同样认
    ``is_admin``）。
    """
    return bool(user and (perm.can_manage_community(user) or user.is_admin))


def mute_for_count(count: int) -> tuple[Optional[int], str]:
    """历史次数（违规前）→ (天数 None=永久, 展示文案)。"""
    return MUTE_LADDER[min(count, len(MUTE_LADDER) - 1)]


async def apply_mute(
    db: AsyncSession,
    user: User,
    *,
    kind: str,
    admin: User,
    reason: str,
    extra: Optional[dict] = None,
) -> dict[str, Any]:
    """按梯度禁言并写入 judgement_logs。

    kind=malicious_report 时累加恶意举报次数；
    kind=content_violation 时累加内容违规次数。
    禁言操作人记录为当前管理员（即使触发源是举报流程）。
    """
    if kind == "malicious_report":
        count = user.malicious_report_count
        user.malicious_report_count = count + 1
    else:
        count = user.content_violation_count
        user.content_violation_count = count + 1

    days, label = mute_for_count(count)
    now = datetime.now(timezone.utc)
    until = now + timedelta(days=days) if days is not None else None

    user.can_speak = False
    user.speak_until = until

    detail: dict[str, Any] = {
        "mute_label": label,
        "mute_until": until.isoformat() if until else None,
        "history_count": count + 1,
    }
    if extra:
        detail.update(extra)
    db.add(JudgementLog(
        admin_id=admin.id,
        target_user_id=user.id,
        action_type=kind,
        action_detail=detail,
        reason=reason,
    ))
    await db.commit()
    return {"label": label, "until": until, "count": count + 1}


async def load_target(
    db: AsyncSession,
    target_type: str,
    target_id: int,
    *,
    include_deleted: bool = False,
) -> Optional[Any]:
    """加载被举报目标。默认不返回已删除目标。"""
    if target_type not in TARGET_TYPES:
        return None
    if target_type == REPORT_BENBEN:
        result = await db.execute(
            select(Benben)
            .options(selectinload(Benben.user))
            .where(Benben.id == target_id)
        )
    elif target_type == REPORT_POST:
        result = await db.execute(
            select(ForumPost)
            .options(selectinload(ForumPost.author))
            .where(ForumPost.id == target_id)
        )
    else:
        result = await db.execute(
            select(ForumComment)
            .options(
                selectinload(ForumComment.author),
                selectinload(ForumComment.post),
            )
            .where(ForumComment.id == target_id)
        )
    obj = result.scalar_one_or_none()
    if obj is None:
        return None
    if not include_deleted and obj.is_deleted:
        return None
    return obj


def target_author(target_type: str, obj: Any) -> Optional[User]:
    """被举报目标的作者（User 实例）。"""
    if target_type == REPORT_BENBEN:
        return obj.user
    return obj.author


def target_author_id(target_type: str, obj: Any) -> Optional[int]:
    if target_type == REPORT_BENBEN:
        return obj.user.id if obj.user else None
    return obj.author_id


def target_link(target_type: str, obj: Any) -> str:
    if target_type == REPORT_BENBEN:
        return "/"
    if target_type == REPORT_POST:
        return f"/discuss/{obj.id}"
    return f"/discuss/{obj.post_id}"


async def _collect_benben_descendants(db: AsyncSession, root_id: int) -> list[int]:
    """BFS 收集所有直接/间接回复某条犇犇的 id（被删的行也参与遍历）。"""
    collected: list[int] = []
    frontier = [root_id]
    while frontier:
        rows = (await db.execute(
            select(Benben.id).where(Benben.reply_to.in_(frontier))
        )).scalars().all()
        rows = [r for r in rows if r not in collected]
        if not rows:
            break
        collected.extend(rows)
        frontier = list(rows)
    return collected


async def soft_delete_target(
    db: AsyncSession,
    target_type: str,
    obj: Any,
    *,
    reason: str,
    admin_id: Optional[int],
) -> None:
    """软删除。犇犇连带未删除的回复一起删。"""
    now = datetime.now(timezone.utc)
    if target_type == REPORT_BENBEN:
        descendants = await _collect_benben_descendants(db, obj.id)
        # 级联只删当时还活着的回复；已独立删除的保留其原有原因
        await db.execute(
            update(Benben)
            .where(
                Benben.id.in_([obj.id, *descendants]),
                Benben.is_deleted.is_(False),
            )
            .values(
                is_deleted=True,
                deleted_at=now,
                deleted_by_id=admin_id,
                delete_reason=reason,
            )
        )
        await db.commit()
        return

    obj.is_deleted = True
    obj.deleted_at = now
    obj.deleted_by_id = admin_id
    obj.delete_reason = reason
    await db.commit()


async def restore_target(
    db: AsyncSession,
    target_type: str,
    obj: Any,
) -> bool:
    """恢复被删内容（举报不成立）。作者自删的不恢复，返回 False。

    犇犇会连带恢复「同一批次被级联删除」的回复，
    独立删除的回复不受影响。
    """
    if not obj.is_deleted:
        return True
    if obj.delete_reason == REASON_SELF:
        return False

    if target_type == REPORT_BENBEN:
        reason = obj.delete_reason
        descendants = await _collect_benben_descendants(db, obj.id)
        await db.execute(
            update(Benben)
            .where(
                Benben.id.in_([obj.id, *descendants]),
                Benben.delete_reason == reason,
            )
            .values(
                is_deleted=False,
                deleted_at=None,
                deleted_by_id=None,
                delete_reason=None,
            )
        )
        await db.commit()
        return True

    obj.is_deleted = False
    obj.deleted_at = None
    obj.deleted_by_id = None
    obj.delete_reason = None
    await db.commit()
    return True
