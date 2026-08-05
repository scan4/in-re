"""Pydantic 请求/响应模型"""
from pydantic import BaseModel, Field
from typing import Optional


class RecommendRequest(BaseModel):
    token: str = Field(..., description="JWT Token (前端从 URL 参数传入)")
    context_type: str = Field(..., pattern="^(browsing|search)$", description="上下文类型")
    context_text: str = Field(..., min_length=1, max_length=2000, description="当前浏览内容文本")
    limit: int = Field(default=8, ge=1, le=10)
    content_types: Optional[list[str]] = Field(default=None, description="按内容类型过滤 (如 ['skill','scale'])")


class RecommendItem(BaseModel):
    content_id: str
    content_type: str
    title: str
    reason: str
    score: float
    tags: list[str] = []


class RecommendData(BaseModel):
    trace_id: str
    fallback_used: bool
    recommendations: list[RecommendItem]


class RecommendResponse(BaseModel):
    code: int = 200
    data: RecommendData


class FeedbackRequest(BaseModel):
    user_id: str = Field(..., max_length=64)
    trace_id: str = Field(..., max_length=64)
    event_type: str = Field(..., pattern="^(exposure|click)$")
    content_id: str = Field(...)
    content_type: str = Field(default="")
    position: Optional[int] = None
