"""群聊业务服务。

会话（群组/私聊）创建、成员管理、消息收发与撤回删除。
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, ConversationMember, Message
from app.models.user import User

ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"


async def _membership(
    db: AsyncSession, conversation_id: int, user_id: int
) -> ConversationMember | None:
    row = await db.execute(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id,
            ConversationMember.left_at.is_(None),
        )
    )
    return row.scalar_one_or_none()


async def _member_count(db: AsyncSession, conversation_id: int) -> int:
    row = await db.execute(
        select(func.count())
        .select_from(ConversationMember)
        .where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.left_at.is_(None),
        )
    )
    return int(row.scalar() or 0)


async def _require_member(
    db: AsyncSession, conversation_id: int, user_id: int
) -> ConversationMember:
    conv = (await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )).scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    member = await _membership(db, conversation_id, user_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="你不是该会话成员")
    return member


async def create_conversation(
    db: AsyncSession,
    *,
    creator_id: int,
    type_: str,
    title: str | None,
    member_ids: list[int],
) -> Conversation:
    if type_ not in ("group", "private"):
        raise HTTPException(status_code=400, detail="会话类型非法")
    if type_ == "group" and not (title and title.strip()):
        raise HTTPException(status_code=400, detail="群组名称不能为空")

    conv = Conversation(
        type=type_,
        title=title.strip() if (type_ == "group" and title) else None,
        is_private=(type_ == "private"),
        owner_id=creator_id,
    )
    db.add(conv)
    await db.flush()

    db.add(ConversationMember(conversation_id=conv.id, user_id=creator_id, role=ROLE_OWNER))
    seen = {creator_id}
    for uid in member_ids:
        # member_ids 是用户编号（UID）：按 user_number 列解析出主键再落关系表
        target_id = (
            await db.execute(select(User.id).where(User.user_number == uid))
        ).scalar_one_or_none()
        if target_id is None or target_id in seen:
            continue
        seen.add(target_id)
        db.add(ConversationMember(conversation_id=conv.id, user_id=target_id, role=ROLE_MEMBER))
    await db.commit()
    await db.refresh(conv)
    return conv


async def list_conversations(db: AsyncSession, *, user_id: int) -> list[dict]:
    memberships = (await db.execute(
        select(ConversationMember).where(
            ConversationMember.user_id == user_id,
            ConversationMember.left_at.is_(None),
        )
    )).scalars().all()
    if not memberships:
        return []
    read_map = {m.conversation_id: (m.last_read_message_id or 0) for m in memberships}
    conv_ids = list(read_map.keys())

    convs = (await db.execute(
        select(Conversation)
        .where(Conversation.id.in_(conv_ids))
        .order_by(Conversation.last_message_at.desc().nullslast(), Conversation.id.desc())
    )).scalars().all()

    items: list[dict] = []
    for c in convs:
        last = (await db.execute(
            select(Message)
            .where(
                Message.conversation_id == c.id,
                Message.deleted_for_recipient.is_(False),
            )
            .order_by(Message.id.desc())
            .limit(1)
        )).scalar_one_or_none()
        unread = (await db.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id == c.id,
                Message.sender_id != user_id,
                Message.deleted_for_recipient.is_(False),
                Message.id > read_map.get(c.id, 0),
            )
        )).scalar() or 0
        items.append({
            "id": c.id,
            "type": c.type,
            "title": c.title,
            "avatar_url": c.avatar_url,
            "is_private": c.is_private,
            "owner_id": c.owner_id,
            "dissolved": bool(c.dissolved),
            "member_count": await _member_count(db, c.id),
            "last_message_at": last.created_at if last else None,
            "last_message_content": (
                "（消息已撤回）" if (last and last.is_recalled) else (last.content if last else None)
            ),
            "unread": int(unread),
            "created_at": c.created_at,
        })
    return items


async def get_conversation_detail(
    db: AsyncSession, *, conversation_id: int, user_id: int
) -> dict:
    await _require_member(db, conversation_id, user_id)
    conv = (await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )).scalar_one()

    rows = (await db.execute(
        select(ConversationMember, User)
        .join(User, ConversationMember.user_id == User.id)
        .where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.left_at.is_(None),
        )
        .order_by(ConversationMember.id)
    )).all()
    members = [
        {
            "user_id": u.id,
            "username": u.username,
            "role": m.role,
            "joined_at": m.joined_at,
        }
        for m, u in rows
    ]
    return {
        "id": conv.id,
        "type": conv.type,
        "title": conv.title,
        "avatar_url": conv.avatar_url,
        "is_private": conv.is_private,
        "owner_id": conv.owner_id,
        "dissolved": bool(conv.dissolved),
        "member_count": len(members),
        "members": members,
        "created_at": conv.created_at,
    }


async def update_conversation(
    db: AsyncSession, *, conversation_id: int, user_id: int, fields: dict
) -> None:
    member = await _require_member(db, conversation_id, user_id)
    if member.role not in (ROLE_OWNER, ROLE_ADMIN):
        raise HTTPException(status_code=403, detail="只有群主或群管理员可以修改群信息")
    conv = (await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )).scalar_one()
    if "title" in fields:
        title = fields["title"]
        if not (title and title.strip()):
            raise HTTPException(status_code=400, detail="群组名称不能为空")
        conv.title = title.strip()
    if "avatar_url" in fields:
        url = (fields["avatar_url"] or "").strip()
        conv.avatar_url = url[:500] or None
    await db.commit()


async def add_members(
    db: AsyncSession, *, conversation_id: int, user_id: int, member_ids: list[int]
) -> int:
    member = await _require_member(db, conversation_id, user_id)
    if member.role not in (ROLE_OWNER, ROLE_ADMIN):
        raise HTTPException(status_code=403, detail="只有群主或群管理员可以邀请成员")

    added = 0
    for uid in member_ids:
        # member_ids 是用户编号（UID）：按 user_number 列解析出主键
        target_id = (
            await db.execute(select(User.id).where(User.user_number == uid))
        ).scalar_one_or_none()
        if target_id is None:
            continue
        existing = (await db.execute(
            select(ConversationMember).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == target_id,
            )
        )).scalar_one_or_none()
        if existing is not None:
            if existing.left_at is not None:
                existing.left_at = None
                added += 1
            continue
        db.add(ConversationMember(conversation_id=conversation_id, user_id=target_id, role=ROLE_MEMBER))
        added += 1
    await db.commit()
    return added


async def remove_member(
    db: AsyncSession, *, conversation_id: int, user_id: int, target_id: int
) -> None:
    """移除成员或成员自退：写一条系统消息，样式与解散提示一致。

    - 自己退出（target_id == user_id）：「{username} 退出了群聊」
    - 被移除：「{operator} 将 {target} 移出了群聊」
    """
    actor = await _require_member(db, conversation_id, user_id)
    if target_id != user_id and actor.role not in (ROLE_OWNER, ROLE_ADMIN):
        raise HTTPException(status_code=403, detail="只有群主或群管理员可以移除成员")

    target = await _membership(db, conversation_id, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="该成员不在群内")
    if target.role == ROLE_OWNER:
        raise HTTPException(status_code=400, detail="群主不能退出群聊，只能解散")
    if actor.role == ROLE_ADMIN and target.role == ROLE_ADMIN and target_id != user_id:
        raise HTTPException(status_code=403, detail="群管理员不能移除其他管理员")

    async def _uname(uid: int) -> str:
        return (await db.execute(
            select(User.username).where(User.id == uid)
        )).scalar_one_or_none() or "已注销用户"

    conv = (await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )).scalar_one()
    now = datetime.now(timezone.utc)
    if target_id == user_id:
        content = f"{await _uname(target_id)} 退出了群聊"
    else:
        content = f"{await _uname(user_id)} 将 {await _uname(target_id)} 移出了群聊"

    target.left_at = now
    db.add(Message(conversation_id=conversation_id, sender_id=None, content=content))
    conv.last_message_at = now
    await db.commit()


async def set_member_role(
    db: AsyncSession, *, conversation_id: int, user_id: int, target_id: int, role: str
) -> None:
    if role not in (ROLE_ADMIN, ROLE_MEMBER):
        raise HTTPException(status_code=400, detail="只能设置为 admin 或 member")
    actor = await _require_member(db, conversation_id, user_id)
    if actor.role != ROLE_OWNER:
        raise HTTPException(status_code=403, detail="只有群主可以设置管理员")

    target = await _membership(db, conversation_id, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="该成员不在群内")
    if target.role == ROLE_OWNER:
        raise HTTPException(status_code=400, detail="不能修改群主角色")
    target.role = role
    await db.commit()


async def dissolve_conversation(
    db: AsyncSession, *, conversation_id: int, user_id: int
) -> None:
    """群主解散群聊：不可逆，不删成员与历史消息，仅禁止再发送。

    解散瞬间插入一条系统消息（sender_id 为空）：
    「群主 {username} 解散了群聊」，前端渲染为居中系统提示。
    """
    conv = (await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )).scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conv.type != "group":
        raise HTTPException(status_code=400, detail="只有群聊可以解散")
    if conv.dissolved:
        raise HTTPException(status_code=400, detail="群聊已解散")
    member = await _require_member(db, conversation_id, user_id)
    if member.role != ROLE_OWNER:
        raise HTTPException(status_code=403, detail="只有群主可以解散群聊")

    owner_name = (await db.execute(
        select(User.username).where(User.id == user_id)
    )).scalar_one_or_none() or "群主"

    conv.dissolved = True
    conv.dissolved_at = datetime.now(timezone.utc)
    db.add(Message(
        conversation_id=conversation_id,
        sender_id=None,
        content=f"群主 {owner_name} 解散了群聊",
    ))
    conv.last_message_at = datetime.now(timezone.utc)
    await db.commit()


async def send_message(
    db: AsyncSession, *, conversation_id: int, sender_id: int, content: str,
    reply_to_id: int | None = None,
) -> Message:
    await _require_member(db, conversation_id, sender_id)
    conv = (await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )).scalar_one()
    if conv.dissolved:
        raise HTTPException(status_code=403, detail="群聊已解散，无法发送消息")
    text = content.strip()
    if not text:
        raise HTTPException(status_code=400, detail="消息内容不能为空")
    if reply_to_id is not None:
        target = (await db.execute(
            select(Message).where(
                Message.id == reply_to_id,
                Message.conversation_id == conversation_id,
            )
        )).scalar_one_or_none()
        if target is None:
            raise HTTPException(status_code=400, detail="被引用的消息不存在")

    msg = Message(
        conversation_id=conversation_id,
        sender_id=sender_id,
        content=text,
        reply_to_id=reply_to_id,
    )
    db.add(msg)
    await db.flush()
    conv.last_message_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(msg)
    return msg


async def list_messages(
    db: AsyncSession, *, conversation_id: int, user_id: int
) -> list[dict]:
    await _require_member(db, conversation_id, user_id)
    rows = (await db.execute(
        select(Message, User)
        .outerjoin(User, Message.sender_id == User.id)
        .where(
            Message.conversation_id == conversation_id,
            Message.deleted_for_recipient.is_(False),
        )
        .order_by(Message.id.asc())
    )).all()

    # 引用快照：一次批量补齐，无 N+1（与私信同套路）
    reply_ids = {m.reply_to_id for m, _ in rows if m.reply_to_id}
    replies: dict[int, dict] = {}
    if reply_ids:
        rrows = (await db.execute(
            select(Message, User)
            .outerjoin(User, Message.sender_id == User.id)
            .where(Message.id.in_(reply_ids))
        )).all()
        for rm, ru in rrows:
            replies[rm.id] = {
                "id": rm.id,
                "sender_id": rm.sender_id,
                "sender_username": ru.username if ru else "已注销用户",
                "content": "" if rm.is_recalled else rm.content,
                "is_recalled": rm.is_recalled,
            }

    return [
        {
            "id": m.id,
            "sender_id": m.sender_id,
            "sender_username": u.username if u else "已注销用户",
            "content": "" if m.is_recalled else m.content,
            "is_recalled": m.is_recalled,
            "reply_to_id": m.reply_to_id,
            "reply_to": replies.get(m.reply_to_id) if m.reply_to_id else None,
            "created_at": m.created_at,
        }
        for m, u in rows
    ]


async def recall_message(
    db: AsyncSession, *, conversation_id: int, message_id: int, user_id: int
) -> Message:
    msg = (await db.execute(
        select(Message).where(
            Message.id == message_id,
            Message.conversation_id == conversation_id,
        )
    )).scalar_one_or_none()
    if msg is None:
        raise HTTPException(status_code=404, detail="消息不存在")

    actor = await _require_member(db, conversation_id, user_id)
    if msg.sender_id != user_id and actor.role not in (ROLE_OWNER, ROLE_ADMIN):
        raise HTTPException(status_code=403, detail="只能撤回自己的消息")
    if msg.is_recalled:
        raise HTTPException(status_code=400, detail="消息已撤回")

    msg.is_recalled = True
    await db.commit()
    await db.refresh(msg)
    return msg


async def delete_message(
    db: AsyncSession, *, conversation_id: int, message_id: int, user_id: int
) -> None:
    msg = (await db.execute(
        select(Message).where(
            Message.id == message_id,
            Message.conversation_id == conversation_id,
        )
    )).scalar_one_or_none()
    if msg is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    if msg.sender_id != user_id:
        raise HTTPException(status_code=403, detail="只能删除自己的消息")
    msg.deleted_for_recipient = True
    msg.deleted_for_sender = True
    await db.commit()


async def mark_read(db: AsyncSession, *, conversation_id: int, user_id: int) -> None:
    """把当前成员的已读位点推进到该会话最新消息（群聊未读清零）。"""
    member = await _membership(db, conversation_id, user_id)
    if member is None:
        return
    max_id = (await db.execute(
        select(func.max(Message.id)).where(Message.conversation_id == conversation_id)
    )).scalar()
    if max_id is None:
        return
    if (member.last_read_message_id or 0) < int(max_id):
        member.last_read_message_id = int(max_id)
        await db.commit()


async def group_unread_total(db: AsyncSession, *, user_id: int) -> int:
    """用户在所有群会话里的未读总数（供顶栏信封角标汇总）。"""
    memberships = (await db.execute(
        select(ConversationMember).where(
            ConversationMember.user_id == user_id,
            ConversationMember.left_at.is_(None),
        )
    )).scalars().all()
    total = 0
    for m in memberships:
        n = (await db.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id == m.conversation_id,
                Message.sender_id != user_id,
                Message.deleted_for_recipient.is_(False),
                Message.id > (m.last_read_message_id or 0),
            )
        )).scalar() or 0
        total += int(n)
    return total
