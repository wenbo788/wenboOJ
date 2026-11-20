"""群聊 Schemas。

对应数据库表：conversations / conversation_members / messages。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CreateConversationRequest(BaseModel):
    type: str = Field(default="group", description="会话类型：group 或 private")
    title: Optional[str] = Field(default=None, max_length=100, description="群组标题")
    member_ids: list[int] = Field(
        default_factory=list, description="初始成员用户编号（UID，即 user_number）列表"
    )


class UpdateConversationRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=100)
    avatar_url: Optional[str] = Field(
        default=None, max_length=500, description="群头像 URL（空串清空）"
    )


class AddMembersRequest(BaseModel):
    member_ids: list[int] = Field(
        default_factory=list, description="成员用户编号（UID，即 user_number）列表"
    )


class SetRoleRequest(BaseModel):
    role: str = Field(description="owner / admin / member")


class MessageCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    reply_to_id: Optional[int] = Field(None, description="引用回复的消息 ID（可选）")


class ConversationBrief(BaseModel):
    id: int
    type: str
    title: Optional[str] = None
    avatar_url: Optional[str] = None
    is_private: bool
    owner_id: Optional[int] = None
    member_count: int = 0
    last_message_at: Optional[datetime] = None
    last_message_content: Optional[str] = None
    created_at: datetime


class MemberBrief(BaseModel):
    user_id: int
    username: str
    role: str
    joined_at: datetime


class ConversationDetail(BaseModel):
    id: int
    type: str
    title: Optional[str] = None
    avatar_url: Optional[str] = None
    is_private: bool
    owner_id: Optional[int] = None
    member_count: int = 0
    members: list[MemberBrief] = Field(default_factory=list)
    created_at: datetime


class MessageBrief(BaseModel):
    id: int
    sender_id: Optional[int] = None
    sender_username: Optional[str] = None
    content: str
    is_recalled: bool
    reply_to_id: Optional[int] = None
    reply_to: Optional[dict] = None
    created_at: datetime
