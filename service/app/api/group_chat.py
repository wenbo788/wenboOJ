"""群聊 API。

支持：创建群组/私聊、会话列表、群详情与成员、邀请/移除成员、
设置群管理、发送/接收消息、消息撤回删除。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.schemas.group_chat import (
    AddMembersRequest,
    CreateConversationRequest,
    MessageCreateRequest,
    SetRoleRequest,
    UpdateConversationRequest,
)
from app.services import group_chat as svc

router = APIRouter(prefix="/conversations", tags=["group-chat"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: CreateConversationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    conv = await svc.create_conversation(
        db,
        creator_id=current_user.id,
        type_=payload.type,
        title=payload.title,
        member_ids=payload.member_ids,
    )
    return {"id": conv.id, "type": conv.type, "title": conv.title}


@router.get("")
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    items = await svc.list_conversations(db, user_id=current_user.id)
    return {"items": items, "total": len(items)}


@router.post("/{conversation_id}/read")
async def mark_conversation_read(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """把该会话的已读位点推进到最新消息（用于清群聊未读）。"""
    await svc.mark_read(db, conversation_id=conversation_id, user_id=current_user.id)
    return {"ok": True}


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return await svc.get_conversation_detail(
        db, conversation_id=conversation_id, user_id=current_user.id
    )


@router.put("/{conversation_id}")
async def update_conversation(
    conversation_id: int,
    payload: UpdateConversationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    await svc.update_conversation(
        db,
        conversation_id=conversation_id,
        user_id=current_user.id,
        fields=payload.model_dump(exclude_unset=True),
    )
    return {"ok": True}


@router.post("/{conversation_id}/members")
async def add_members(
    conversation_id: int,
    payload: AddMembersRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    added = await svc.add_members(
        db,
        conversation_id=conversation_id,
        user_id=current_user.id,
        member_ids=payload.member_ids,
    )
    return {"added": added}


@router.delete("/{conversation_id}/members/{target_id}")
async def remove_member(
    conversation_id: int,
    target_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    await svc.remove_member(
        db,
        conversation_id=conversation_id,
        user_id=current_user.id,
        target_id=target_id,
    )
    return {"ok": True}


@router.put("/{conversation_id}/members/{target_id}/role")
async def set_member_role(
    conversation_id: int,
    target_id: int,
    payload: SetRoleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    await svc.set_member_role(
        db,
        conversation_id=conversation_id,
        user_id=current_user.id,
        target_id=target_id,
        role=payload.role,
    )
    return {"ok": True}


@router.get("/{conversation_id}/messages")
async def list_messages(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    messages = await svc.list_messages(
        db, conversation_id=conversation_id, user_id=current_user.id
    )
    return {"messages": messages}


@router.post("/{conversation_id}/messages", status_code=status.HTTP_201_CREATED)
async def send_message(
    conversation_id: int,
    payload: MessageCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    msg = await svc.send_message(
        db,
        conversation_id=conversation_id,
        sender_id=current_user.id,
        content=payload.content,
        reply_to_id=payload.reply_to_id,
    )
    return {
        "id": msg.id,
        "content": msg.content,
        "reply_to_id": msg.reply_to_id,
        "created_at": msg.created_at,
    }


@router.post("/{conversation_id}/dissolve")
async def dissolve_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """群主解散群聊（不可逆）：成员保留、历史可读，但禁止再发送。"""
    await svc.dissolve_conversation(
        db, conversation_id=conversation_id, user_id=current_user.id
    )
    return {"ok": True}


@router.post("/{conversation_id}/messages/{message_id}/recall")
async def recall_message(
    conversation_id: int,
    message_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    msg = await svc.recall_message(
        db,
        conversation_id=conversation_id,
        message_id=message_id,
        user_id=current_user.id,
    )
    return {"id": msg.id, "is_recalled": msg.is_recalled}


@router.delete("/{conversation_id}/messages/{message_id}")
async def delete_message(
    conversation_id: int,
    message_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    await svc.delete_message(
        db,
        conversation_id=conversation_id,
        message_id=message_id,
        user_id=current_user.id,
    )
    return {"ok": True}
