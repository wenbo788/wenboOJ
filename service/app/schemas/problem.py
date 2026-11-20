"""题目的 Pydantic 模型。"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# 难度等级（洛谷 8 级基础上自定义：「普及/提高-」并入「普及」，新增「提高」）
DIFFICULTIES = [
    "暂无评定",
    "入门",
    "普及-",
    "普及",
    "普及+/提高-",
    "提高",
    "提高+/省选-",
    "省选/NOI-",
    "NOI/NOI+/CTSC",
]
# re.escape：难度名里的 + / - 是正则元字符，不转义会导致这些难度永远校验失败
_DIFF = "|".join(re.escape(d) for d in DIFFICULTIES)


def normalize_difficulty_input(v: Any) -> Any:
    """写侧兜底：把旧档位名（如「普及+/提高」）先归一化到规范档位名。

    为什么需要：``DIFFICULTIES`` 里只剩新名，滚动发布窗口期（新代码已上、
    存量数据迁移未跑，或旧客户端仍在提交旧串）会让这些请求直接被 422 拒掉，
    而且一旦写进去就是查表查不到的「幽灵档位」。归一化后两种写法都能落地,
    且库里只会存规范名。
    """
    if isinstance(v, str):
        from app.services.problem_markdown import normalize_difficulty

        return normalize_difficulty(v) or v
    return v


class ProblemSample(BaseModel):
    input: str = Field(default="", max_length=20_000, description="样例输入")
    output: str = Field(default="", max_length=20_000, description="样例输出")


class SubtaskItem(BaseModel):
    id: int = Field(..., ge=1, description="子任务 ID")
    score: int = Field(default=0, ge=0, le=100, description="子任务分值")
    name: str | None = Field(None, max_length=50, description="子任务名称")


class ProblemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100, description="题目名称")
    difficulty: str = Field(
        default="暂无评定", pattern=f"^({_DIFF})$", description="难度"
    )

    # mode="before"：先归一化再做 pattern 校验，这样旧串也能通过（见 normalize_difficulty_input）
    @field_validator("difficulty", mode="before")
    @classmethod
    def _difficulty_alias(cls, v: Any) -> Any:
        return normalize_difficulty_input(v)

    source: str | None = Field(None, max_length=100, description="题目来源")
    tags: list[str] = Field(default_factory=list, max_length=10, description="算法标签")
    # 团队私有题：非空时题目归入该团队（需团队管理员权限），编号走 T 序列
    team_id: int | None = Field(None, description="归属团队（团队私有题）")
    description: str = Field(default="", max_length=100_000, description="题目描述（Markdown）")
    background: str = Field(default="", max_length=100_000, description="题目背景（Markdown）")
    input_format: str = Field(default="", max_length=100_000, description="输入格式（Markdown）")
    output_format: str = Field(default="", max_length=100_000, description="输出格式（Markdown）")
    hint: str = Field(default="", max_length=100_000, description="提示说明（Markdown）")
    samples: list[ProblemSample] = Field(default_factory=list, max_length=20, description="样例组")
    time_limit: int = Field(default=1000, ge=100, le=60_000, description="时间限制 (ms)")
    memory_limit: int = Field(default=128, ge=16, le=1024, description="内存限制 (MB)")
    is_public: bool = Field(default=True, description="是否公开（草稿为 false）")
    allow_solution_submission: bool = Field(default=True, description="是否允许提交题解（关闭后禁止普通用户提交）")
    is_spj: bool = Field(default=False)
    spj_language: str | None = Field(None, max_length=20)
    spj_code: str | None = Field(None, max_length=100_000)
    subtask_config: list[SubtaskItem] | None = Field(None, description="子任务配置")

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, v: list[str]) -> list[str]:
        """去空白、去引号（引号会破坏标签筛选的 LIKE 定界）、去重、限长。"""
        out: list[str] = []
        for t in v:
            t = t.strip().strip('"')[:20]
            if t and t not in out:
                out.append(t)
        return out


class ProblemUpdate(BaseModel):
    """全部 Optional；路由用 model_dump(exclude_unset=True) 做部分更新。"""

    title: str | None = Field(None, min_length=1, max_length=100, description="题目名称")
    difficulty: str | None = Field(None, pattern=f"^({_DIFF})$", description="难度")

    # 同 ProblemCreate：写侧先归一化旧档位名，再走 pattern 校验
    @field_validator("difficulty", mode="before")
    @classmethod
    def _difficulty_alias(cls, v: Any) -> Any:
        return normalize_difficulty_input(v)

    source: str | None = Field(None, max_length=100, description="题目来源")
    tags: list[str] | None = Field(None, max_length=10, description="算法标签")
    description: str | None = Field(None, max_length=100_000, description="题目描述（Markdown）")
    background: str | None = Field(None, max_length=100_000, description="题目背景（Markdown）")
    input_format: str | None = Field(None, max_length=100_000, description="输入格式（Markdown）")
    output_format: str | None = Field(None, max_length=100_000, description="输出格式（Markdown）")
    hint: str | None = Field(None, max_length=100_000, description="提示说明（Markdown）")
    samples: list[ProblemSample] | None = Field(None, max_length=20, description="样例组")
    time_limit: int | None = Field(None, ge=100, le=60_000, description="时间限制 (ms)")
    memory_limit: int | None = Field(None, ge=16, le=1024, description="内存限制 (MB)")
    is_public: bool | None = Field(None, description="是否公开（草稿为 false）")
    allow_solution_submission: bool | None = Field(None, description="是否允许提交题解")
    is_spj: bool | None = Field(None)
    spj_language: str | None = Field(None, max_length=20)
    spj_code: str | None = Field(None, max_length=100_000)
    subtask_config: list[SubtaskItem] | None = Field(None, description="子任务配置")
    # 指派出题人：用户名或 UID；置空字符串 = 清除出题人
    author: str | None = Field(None, max_length=50, description="出题人（用户名或 UID）")


    @field_validator("tags")
    @classmethod
    def clean_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        out: list[str] = []
        for t in v:
            t = t.strip().strip('"')[:20]
            if t and t not in out:
                out.append(t)
        return out


class ProblemReviewRequest(BaseModel):
    """后台题目审核：通过 / 驳回（驳回建议填写原因，便于作者修改）。"""

    action: Literal["approve", "reject"]
    reason: str | None = Field(None, max_length=500, description="驳回原因（驳回时必填）")

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class ProblemMarkdownParseRequest(BaseModel):
    """解析题目 Markdown 题面请求。"""

    content: str = Field(..., max_length=2_000_000, description="Markdown 文本内容")


class ProblemTryRunRequest(BaseModel):
    """题目页「自测环境」单次运行请求（大小在端点里手检，给出友好提示）。"""

    language: str = Field(..., description="语言标识：cpp / c / python3")
    code: str = Field(..., description="源代码")
    input: str = Field(default="", description="标准输入数据")


class ProblemToggleSolutionRequest(BaseModel):
    """切换题目题解提交通道请求。"""

    allow: bool | None = Field(None, description="是否允许提交题解，留空表示取反")


class ProblemMigrateRequest(BaseModel):
    """题目迁移请求：主题库 / 团队题 / 比赛赛题之间互搬。"""

    target: Literal["library", "team", "contest"] = Field(
        ..., description="目标归属：library 主题库 / team 团队题 / contest 比赛赛题"
    )
    team_id: int | None = Field(None, description="target=team 时的目标团队 ID")
    contest_id: int | None = Field(None, description="target=contest 时的目标比赛 ID")
    keep_in_library: bool = Field(
        False,
        description="target=contest 时是否仍保留在主题库（默认从主题库撤下，成为比赛独占题）",
    )


