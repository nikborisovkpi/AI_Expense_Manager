"""API routes for AI Shopping Assistant (/api/v1/agent/*)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.shopping_agent import AgentModelRunner, stream_agent_chat_sse
from app.api.deps import get_app_settings, get_current_profile, get_current_user_id
from app.core.config import Settings
from app.db.session import get_db_session
from app.models.agent import Conversation, Message
from app.models.profile import Profile
from app.repositories.base import BaseRepository
from app.schemas.agent import (
    AgentChatRequest,
    ConversationDetailResponse,
    ConversationSummaryResponse,
    MessageResponse,
)
from app.services.agent_action_service import (
    AgentActionDecisionRequest,
    AgentActionResponse,
    decide_agent_action,
    get_agent_action,
)

router = APIRouter(prefix="/agent", tags=["ai-assistant"])


@router.post("/chat")
async def post_agent_chat(
    payload: AgentChatRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    profile: Profile = Depends(get_current_profile),
    settings: Settings = Depends(get_app_settings),
) -> StreamingResponse:
    runner: AgentModelRunner | None = getattr(request.app.state, "agent_runner", None)
    generator = stream_agent_chat_sse(
        session=session,
        profile=profile,
        settings=settings,
        user_message=payload.message,
        conversation_id=payload.conversation_id,
        runner=runner,
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations", response_model=list[ConversationSummaryResponse])
async def get_conversations(
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[ConversationSummaryResponse]:
    repo = BaseRepository(session, user_id, Conversation)
    rows = await repo.list_matching(repo.scoped_select().order_by(Conversation.updated_at.desc()))
    return [ConversationSummaryResponse.model_validate(r) for r in rows]


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
)
async def get_conversation(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ConversationDetailResponse:
    repo = BaseRepository(session, user_id, Conversation)
    conv = await repo.get_by_id_or_raise(conversation_id)
    msgs = list(
        (
            await session.scalars(
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(Message.created_at.asc())
            )
        ).all()
    )
    return ConversationDetailResponse(
        id=conv.id,
        title=conv.title,
        messages=[MessageResponse.model_validate(m) for m in msgs],
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_conversation(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> Response:
    repo = BaseRepository(session, user_id, Conversation)
    await repo.delete(conversation_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/actions/{action_id}", response_model=AgentActionResponse)
async def read_agent_action(
    action_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> AgentActionResponse:
    return await get_agent_action(session, user_id, action_id)


@router.post("/actions/{action_id}/approve", response_model=AgentActionResponse)
async def post_approve_action(
    action_id: uuid.UUID,
    payload: AgentActionDecisionRequest,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> AgentActionResponse:
    return await decide_agent_action(
        session,
        user_id,
        action_id,
        decision="approve",
        idempotency_key=payload.idempotency_key,
    )


@router.post("/actions/{action_id}/reject", response_model=AgentActionResponse)
async def post_reject_action(
    action_id: uuid.UUID,
    payload: AgentActionDecisionRequest,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> AgentActionResponse:
    return await decide_agent_action(
        session,
        user_id,
        action_id,
        decision="reject",
        idempotency_key=payload.idempotency_key,
    )
