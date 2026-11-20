"""NLNOC 私信 API（站内直聊）。

设计：
  - 不建会话表，两个人之间的消息集就是一个会话；
    会话列表用两条聚合 SQL（每会话最后一条 + 未读数）现场算。
  - 「全服犇犇」不是私信：它就是首页的犇犇流，前端固定排在会话列表第一位，
    数据直接走 /benben 系列端点，与首页同源。
  - 撤回：仅发送者可撤回，撤回后正文在任何接口都不再下发；
    引用回复：落库存 reply_to_id，出参附被引消息快照（一次批量补齐，无 N+1）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps import get_current_user
from app.models.direct_message import DirectMessage
from app.models.user import User
from app.services import group_chat as group_chat_svc
from app.utils.ratelimit import check

router = APIRouter(prefix="/messages", tags=["messages"])


class MessageCreate(BaseModel):
    """发送私信的请求体。"""

    recipient_id: int = Field(description="收件人用户 ID")
    content: str = Field(min_length=1, max_length=1000, description="消息正文")
    reply_to_id: int | None = Field(None, description="引用回复的消息 ID（可选）")


def user_brief(user: User) -> dict:
    """列表/会话里展示用户所需的最小字段（不含邮箱、手机号等隐私）。

    会话列表与 /users/search 共用同一份形状，前端才能把搜索结果直接
    当成会话里的 peer 用。
    """
    return {
        "id": user.id,
        "username": user.username,
        "user_number": user.user_number,
        "avatar_url": user.avatar_url,
        "is_admin": user.is_admin,
        "is_super_admin": user.is_super_admin,
        "is_banned": user.is_banned,
        "is_cheater": user.is_cheater,
        # 供前端 userNameColor() 复算全站统一的用户名配色
        "can_manage_users": user.can_manage_users,
        "can_manage_posts": user.can_manage_posts,
        "can_manage_problems": user.can_manage_problems,
        "username_color": user.username_color,
        "color_tier": user.color_tier or "gray",
        "name_color": user.name_color,
        # 全站统一称号（Tag 卡 > 管理员设置 > 管理员/作弊者默认），与犇犇/工单同源
        "user_tag": user.display_tag,
        "last_seen": user.last_seen,
    }


def _message_out(m: DirectMessage, reply: DirectMessage | None = None) -> dict:
    """单条消息的下发形状。

    撤回后 content 一律遮蔽为空串（前端按 is_recalled 渲染文案），
    被引用的消息同样遮蔽——撤回的正文不再通过任何接口下发。
    """
    out: dict = {
        "id": m.id,
        "sender_id": m.sender_id,
        "recipient_id": m.recipient_id,
        "content": "" if m.is_recalled else m.content,
        "is_read": m.is_read,
        "is_recalled": m.is_recalled,
        "reply_to_id": m.reply_to_id,
        "reply_to": None,
        "created_at": m.created_at,
    }
    if reply is not None:
        out["reply_to"] = {
            "id": reply.id,
            "sender_id": reply.sender_id,
            "content": "" if reply.is_recalled else reply.content,
            "is_recalled": reply.is_recalled,
        }
    return out


async def _hydrate(db: AsyncSession, rows: list[DirectMessage]) -> list[dict]:
    """消息行 → 下发形状：一次 in 查询批量补齐引用快照，避免 N+1。"""
    reply_ids = {m.reply_to_id for m in rows if m.reply_to_id}
    replies: dict[int, DirectMessage] = {}
    if reply_ids:
        replies = {
            r.id: r
            for r in (
                await db.execute(
                    select(DirectMessage).where(DirectMessage.id.in_(reply_ids))
                )
            ).scalars()
        }
    return [
        _message_out(m, replies.get(m.reply_to_id) if m.reply_to_id else None)
        for m in rows
    ]


def _both_ways(me: int, peer: int):
    """「我与某人之间的全部消息」的查询条件。"""
    return or_(
        (DirectMessage.sender_id == me) & (DirectMessage.recipient_id == peer),
        (DirectMessage.sender_id == peer) & (DirectMessage.recipient_id == me),
    )


@router.get("/conversations", summary="会话列表")
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """我的私信会话：每个对方一条，带最后一条消息与未读数，按最新排序。

    刻意拆成两条最朴素的查询，不搞 GROUP BY 嵌套子查询：
      1) (对方, max(id)) —— CASE 表达式既作 SELECT 列又作 GROUP BY 表达式（标准 SQL）；
      2) 未读数直接 GROUP BY 发件人 —— 「我收到的未读」对方必是发件人，无需 CASE。
    Python 侧只做字典拼装，任何数据库方言下语义一致。
    """
    me = current_user.id
    # 会话的「对方」：我发出去的算收件人，我收到的算发件人
    peer_expr = case(
        (DirectMessage.sender_id == me, DirectMessage.recipient_id),
        else_=DirectMessage.sender_id,
    )

    last_pairs = (
        await db.execute(
            select(peer_expr.label("peer_id"), func.max(DirectMessage.id))
            .where(or_(DirectMessage.sender_id == me, DirectMessage.recipient_id == me))
            .group_by(peer_expr)
        )
    ).all()
    if not last_pairs:
        return {"conversations": []}

    last_ids = [mid for _, mid in last_pairs]
    peer_ids = [pid for pid, _ in last_pairs]

    last_msgs = {
        m.id: m
        for m in (
            await db.execute(
                select(DirectMessage).where(DirectMessage.id.in_(last_ids))
            )
        ).scalars().all()
    }

    unread_rows = (
        await db.execute(
            select(DirectMessage.sender_id, func.count(DirectMessage.id))
            .where(
                DirectMessage.recipient_id == me,
                DirectMessage.is_read.is_(False),
            )
            .group_by(DirectMessage.sender_id)
        )
    ).all()
    unread_map = {pid: cnt for pid, cnt in unread_rows}

    users: dict[int, User] = {}
    for u in (
        await db.execute(select(User).where(User.id.in_(peer_ids)))
    ).scalars():
        users[u.id] = u

    conversations = []
    for pid, mid in sorted(last_pairs, key=lambda x: x[1], reverse=True):
        u = users.get(pid)
        m = last_msgs.get(mid)
        if not u or not m:
            continue
        conversations.append({
            "peer": user_brief(u),
            "last_message": _message_out(m),
            "unread": unread_map.get(pid, 0),
        })
    return {"conversations": conversations}


@router.get("/unread-count", summary="未读总数（私信 + 群聊）")
async def unread_count(
    exclude_peer_id: int | None = Query(
        None, description="排除该用户发来的未读（正与其对话，不点亮角标）"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """顶栏信封角标用的未读总数：私信 + 群聊。

    exclude_peer_id：正在与该用户对话时，他发来的未读不计入角标
    （否则会话开着角标一直亮，用户以为还有新消息）。
    """
    stmt = select(func.count(DirectMessage.id)).where(
        DirectMessage.recipient_id == current_user.id,
        DirectMessage.is_read.is_(False),
    )
    if exclude_peer_id is not None:
        stmt = stmt.where(DirectMessage.sender_id != exclude_peer_id)
    n = (await db.execute(stmt)).scalar() or 0
    group_n = await group_chat_svc.group_unread_total(db, user_id=current_user.id)
    return {"count": int(n) + int(group_n)}


@router.post("", status_code=status.HTTP_201_CREATED, summary="发送私信")
async def send_message(
    payload: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """给某位用户发一条私信（可选引用回复）。"""
    if not current_user.can_speak:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁言，无法发送私信",
        )
    content = payload.content.strip()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="消息内容不能为空",
        )
    if payload.recipient_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能给自己发私信",
        )
    peer = await db.get(User, payload.recipient_id)
    if not peer or not peer.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    # 引用回复：目标必须存在且属于这段会话（放在限流前，坏请求不占额度）
    reply_target: DirectMessage | None = None
    if payload.reply_to_id is not None:
        reply_target = await db.get(DirectMessage, payload.reply_to_id)
        belongs = reply_target is not None and (
            (
                reply_target.sender_id == current_user.id
                and reply_target.recipient_id == payload.recipient_id
            )
            or (
                reply_target.sender_id == payload.recipient_id
                and reply_target.recipient_id == current_user.id
            )
        )
        if not belongs:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="被引用的消息不存在或不属于这段会话",
            )

    # 防刷屏：同一用户 10 秒内最多 10 条
    ok, wait = check(f"dm:{current_user.id}", 10, 10)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"发得太快了，请 {wait} 秒后再试",
        )

    msg = DirectMessage(
        sender_id=current_user.id,
        recipient_id=payload.recipient_id,
        content=content,
        reply_to_id=payload.reply_to_id,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return _message_out(msg, reply_target)


@router.post("/{message_id}/recall", summary="撤回自己的消息")
async def recall_message(
    message_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """仅发送者可撤回；撤回后正文立即停止下发（幂等，重复撤回返回当前状态）。"""
    msg = await db.get(DirectMessage, message_id)
    if not msg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="消息不存在",
        )
    if msg.sender_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只能撤回自己发送的消息",
        )
    if not msg.is_recalled:
        msg.is_recalled = True
        await db.commit()
        await db.refresh(msg)
    return _message_out(msg)


@router.get("/{peer_id}", summary="与某用户的聊天记录")
async def get_messages(
    peer_id: int,
    before_id: int | None = Query(None, description="只取该 ID 之前的历史消息"),
    after_id: int | None = Query(None, description="只取该 ID 之后的新消息（轮询增量）"),
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """打开与某人的会话：默认取最近 N 条（旧→新），支持向前翻页与增量轮询。"""
    me = current_user.id
    if peer_id == me:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能和自己聊天",
        )
    peer = await db.get(User, peer_id)
    if not peer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    stmt = select(DirectMessage).where(_both_ways(me, peer_id))
    recalled_ids: list[int] = []
    if after_id is not None:
        # 增量：只要比我最后一条新的，正序返回
        rows = list(
            (
                await db.execute(
                    stmt.where(DirectMessage.id > after_id)
                    .order_by(DirectMessage.id.asc())
                    .limit(limit)
                )
            ).scalars().all()
        )
        has_more = False
        # 撤回不同步走增量（旧消息的撤回不在 after_id 之后）：每轮附带会话内
        # 最近的撤回 id（封顶 200），轮询端据此把本地旧消息置为已撤回
        recalled_ids = list(
            (
                await db.execute(
                    select(DirectMessage.id)
                    .where(
                        _both_ways(me, peer_id),
                        DirectMessage.is_recalled.is_(True),
                    )
                    .order_by(DirectMessage.id.desc())
                    .limit(200)
                )
            ).scalars()
        )
    else:
        if before_id is not None:
            stmt = stmt.where(DirectMessage.id < before_id)
        rows = list(
            reversed(
                (
                    await db.execute(
                        stmt.order_by(DirectMessage.id.desc()).limit(limit)
                    )
                ).scalars().all()
            )
        )
        has_more = len(rows) == limit

    return {
        "peer": user_brief(peer),
        "messages": await _hydrate(db, rows),
        "has_more": has_more,
        "recalled_ids": recalled_ids,
    }


@router.post("/{peer_id}/read", summary="把对方发来的消息标记为已读")
async def mark_read(
    peer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """打开会话即调用；角标随后按未读数重算。"""
    result = await db.execute(
        update(DirectMessage)
        .where(
            DirectMessage.sender_id == peer_id,
            DirectMessage.recipient_id == current_user.id,
            DirectMessage.is_read.is_(False),
        )
        .values(is_read=True)
    )
    await db.commit()
    return {"success": True, "updated": int(result.rowcount or 0)}
