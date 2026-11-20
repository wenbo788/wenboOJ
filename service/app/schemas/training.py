"""Schemas for Training Lists (题单系统)."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class TrainingListCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100, description="题单标题")
    description: str = Field(default="", description="题单描述 (Markdown)")
    is_public: bool = Field(default=True, description="是否公开")
    problem_codes: Optional[list[str]] = Field(default=None, description="初始题目代码列表")


class TrainingListUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = None
    is_public: Optional[bool] = None
    problem_codes: Optional[list[str]] = None


class TrainingListProblemAdd(BaseModel):
    problem_code: str = Field(..., min_length=1, description="题号，如 P1001, T1001, 1001")


class TrainingFeatureUpdate(BaseModel):
    is_featured: bool = Field(..., description="是否推荐")


# Aliases for compatibility
TrainingCreate = TrainingListCreate
TrainingUpdate = TrainingListUpdate
TrainingProblemAdd = TrainingListProblemAdd
