"""Pydantic schemas for AI Shopping Assistant conversations and SSE chat."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    conversation_id: uuid.UUID | None = None


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str
    tool_calls: list[Any] | None
    tool_results: list[Any] | None
    model_name: str | None
    prompt_version: str | None
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost: Decimal | None
    latency_ms: int | None
    created_at: datetime


class ConversationSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetailResponse(BaseModel):
    id: uuid.UUID
    title: str
    messages: list[MessageResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
