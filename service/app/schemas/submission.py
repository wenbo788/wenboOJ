"""提交的 Pydantic 模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# 支持的语言（评测沙箱依赖宿主机安装 g++ / gcc / python3）
LANGUAGES = ["cpp", "c", "python3"]
_LANG = "|".join(LANGUAGES)


class SubmissionCreate(BaseModel):
    code: str = Field(min_length=1, max_length=100_000, description="源代码")
    language: str = Field(pattern=f"^({_LANG})$", description="语言：cpp / c / python3")
    # 比赛内提交：非空时按比赛规则校验（进行中 + 已报名 + 题目在比赛中）
    contest_id: int | None = Field(None, description="归属比赛（比赛内提交）")


class SubmissionRejudgeRequest(BaseModel):
    score: Literal[0, 100] | None = None


class SubmissionCancelScoreRequest(BaseModel):
    score: Literal[0, 100] | None = None


class TestCaseCreate(BaseModel):
    # 直接导入文本文件时，单个输入/输出文件通常可能达到 ~10MB；
    # 允许更大上限，避免因为 Pydantic 过早截断导致测试点丢失。
    input_data: str = Field(default="", max_length=20_000_000, description="测试点输入")
    expected_output: str = Field(default="", max_length=20_000_000, description="期望输出")
    subtask_id: int | None = Field(None, description="所属子任务 ID")
    subtask_score: int | None = Field(None, description="子任务分值")


class TestCaseUpdate(BaseModel):
    input_data: str | None = Field(None, max_length=20_000_000, description="测试点输入")
    expected_output: str | None = Field(None, max_length=20_000_000, description="期望输出")
    subtask_id: int | None = Field(None, description="所属子任务 ID")
    subtask_score: int | None = Field(None, description="子任务分值")
    sort_order: int | None = None


class SubtaskConfigItem(BaseModel):
    id: int = Field(..., ge=1, description="子任务 ID")
    score: int = Field(default=0, ge=0, le=100, description="子任务分值")
    name: str | None = Field(None, max_length=50, description="子任务名称")


class ProblemSubtasksUpdateRequest(BaseModel):
    subtask_config: list[SubtaskConfigItem] = Field(default_factory=list)
    case_subtasks: dict[int, int | None] | None = None  # {case_id: subtask_id}


class TestCaseBatchDeleteRequest(BaseModel):
    case_ids: list[int] = Field(..., min_length=1, description="待删除的测试点 ID 列表")

