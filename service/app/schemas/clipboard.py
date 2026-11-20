"""云剪贴板 Pydantic 模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ClipboardKind = Literal["text", "code"]


class ClipboardItem(BaseModel):
    """剪贴板条目对外结构。

    刻意不暴露 user_id：所有接口都按当前用户过滤，返回所属者没有意义，
    且一旦将来出现共享/管理端视图会放大信息泄露面。
    ORM 模型仍保留 user_id 列，不受影响。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: ClipboardKind
    title: str | None = None
    language: str | None = None
    content: str
    created_at: datetime
    updated_at: datetime


class ClipboardListResponse(BaseModel):
    items: list[ClipboardItem]
    total: int
    page: int
    page_size: int


class ClipboardCreate(BaseModel):
    kind: ClipboardKind = "text"
    title: str | None = Field(default=None, max_length=120)
    language: str | None = Field(default=None, max_length=32)
    content: str = Field(..., min_length=1)


class ClipboardUpdate(BaseModel):
    kind: ClipboardKind | None = None
    title: str | None = Field(default=None, max_length=120)
    language: str | None = Field(default=None, max_length=32)
    content: str | None = Field(default=None, min_length=1)
