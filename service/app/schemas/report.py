"""举报相关的 Pydantic 模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.report import (
    TARGET_TYPES,
    VERDICT_FALSE,
    VERDICT_GUILTY,
)
from app.services.moderation import REPORT_CATEGORIES


class ReportCreate(BaseModel):
    target_type: str = Field(
        description="举报对象类型",
        pattern=f"^({'|'.join(TARGET_TYPES)})$",
    )
    target_id: int = Field(gt=0, description="举报对象 ID")
    category: str = Field(
        description="举报分类",
        pattern=f"^({'|'.join(REPORT_CATEGORIES)})$",
    )
    detail: str | None = Field(
        None, max_length=500, description="补充说明（选填）"
    )


class VerdictPayload(BaseModel):
    verdict: str = Field(
        description="guilty 举报成立（内容违规） / false_report 举报不成立（恶意举报）",
        pattern=f"^({VERDICT_GUILTY}|{VERDICT_FALSE})$",
    )
