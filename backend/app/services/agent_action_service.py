"""Approval-gated agent action proposals and deterministic domain execution (Section 8.3)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError, ConflictError
from app.db.base import utcnow
from app.models.agent import AgentAction, Message
from app.repositories.base import BaseRepository
from app.schemas.budget import BudgetCreateRequest
from app.schemas.shopping_list import (
    ShoppingListCreateRequest,
    ShoppingListItemCreateRequest,
)
from app.services.budget_service import create_budget
from app.services.shopping_list_service import (
    add_shopping_list_item,
    create_shopping_list,
)

ALLOWED_WRITE_TOOLS = frozenset({"create_budget", "create_shopping_list", "add_shopping_list_item"})
ACTION_EXPIRY_MINUTES = 30

WRITE_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_budget",
            "description": (
                "Propose creating a shopping budget (requires user approval before saving)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "category_id": {"type": "string"},
                    "store_id": {"type": "string"},
                    "amount": {"type": "string"},
                    "currency": {"type": "string", "enum": ["RON", "UAH", "EUR", "USD"]},
                    "period": {"type": "string", "enum": ["monthly", "custom"]},
                    "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "required": ["amount", "currency", "start_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_shopping_list",
            "description": "Propose creating a new shopping list (requires user approval).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "store_id": {"type": "string"},
                    "currency": {"type": "string", "enum": ["RON", "UAH", "EUR", "USD"]},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_shopping_list_item",
            "description": "Propose adding an item to a shopping list (requires user approval).",
            "parameters": {
                "type": "object",
                "properties": {
                    "shopping_list_id": {"type": "string"},
                    "product_id": {"type": "string"},
                    "product_name": {"type": "string"},
                    "quantity": {"type": "string"},
                    "unit": {
                        "type": "string",
                        "enum": ["piece", "pack", "pair", "g", "kg", "ml", "l"],
                    },
                    "estimated_price": {"type": "string"},
                },
                "required": ["shopping_list_id", "product_name"],
            },
        },
    },
]


class AgentActionDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=128)


class AgentActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID | None
    action_type: str
    arguments: dict[str, Any]
    arguments_hash: str
    status: str
    expires_at: datetime
    approved_at: datetime | None
    executed_at: datetime | None
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime


def compute_canonical_arguments_hash(action_type: str, arguments: dict[str, Any]) -> str:
    canonical_json = json.dumps(
        {"action_type": action_type, "arguments": arguments},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _validate_proposal_payload(action_type: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate proposal arguments strictly before persisting pending action."""
    if action_type == "create_budget":
        parsed = BudgetCreateRequest.model_validate(arguments)
        return parsed.model_dump(mode="json")
    if action_type == "create_shopping_list":
        parsed_list = ShoppingListCreateRequest.model_validate(arguments)
        return parsed_list.model_dump(mode="json")
    if action_type == "add_shopping_list_item":
        list_id = str(arguments.get("shopping_list_id") or "")
        uuid.UUID(list_id)
        item_args = {k: v for k, v in arguments.items() if k != "shopping_list_id"}
        parsed_item = ShoppingListItemCreateRequest.model_validate(item_args)
        return {"shopping_list_id": list_id, **parsed_item.model_dump(mode="json")}
    raise BadRequestError(f"Unsupported agent write action: {action_type!r}")


async def create_pending_agent_action(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    conversation_id: uuid.UUID | None,
    action_type: str,
    raw_arguments: dict[str, Any],
) -> AgentAction:
    if action_type not in ALLOWED_WRITE_TOOLS:
        raise BadRequestError(f"Unauthorized write tool proposal: {action_type!r}")

    normalized_args = _validate_proposal_payload(action_type, raw_arguments)
    arg_hash = compute_canonical_arguments_hash(action_type, normalized_args)
    repo = BaseRepository(session, user_id, AgentAction)
    action = await repo.create(
        conversation_id=conversation_id,
        action_type=action_type,
        arguments=normalized_args,
        arguments_hash=arg_hash,
        status="pending",
        expires_at=utcnow() + timedelta(minutes=ACTION_EXPIRY_MINUTES),
    )
    await session.flush()
    return action


async def get_agent_action(
    session: AsyncSession,
    user_id: uuid.UUID,
    action_id: uuid.UUID,
) -> AgentActionResponse:
    repo = BaseRepository(session, user_id, AgentAction)
    act = await repo.get_by_id_or_raise(action_id)
    return AgentActionResponse.model_validate(act)


async def decide_agent_action(
    session: AsyncSession,
    user_id: uuid.UUID,
    action_id: uuid.UUID,
    *,
    decision: Literal["approve", "reject"],
    idempotency_key: str,
) -> AgentActionResponse:
    repo = BaseRepository(session, user_id, AgentAction)
    act = await repo.get_by_id_or_raise(action_id)

    # Idempotent replay if already processed with the exact same idempotency_key
    if act.idempotency_key == idempotency_key and act.status in ("executed", "rejected"):
        return AgentActionResponse.model_validate(act)

    if act.status != "pending":
        raise ConflictError(
            f"Agent action is in status '{act.status}' and cannot be modified.",
            details={"status": act.status},
        )

    now = utcnow()
    exp = act.expires_at if act.expires_at.tzinfo else act.expires_at.replace(tzinfo=now.tzinfo)
    if exp <= now:
        act.status = "expired"
        await session.commit()
        raise ConflictError("Agent action proposal has expired.")

    expected_hash = compute_canonical_arguments_hash(act.action_type, act.arguments)
    if act.arguments_hash != expected_hash:
        raise ConflictError("Agent action arguments hash integrity check failed.")

    if decision == "reject":
        act.status = "rejected"
        act.idempotency_key = idempotency_key
        if act.conversation_id is not None:
            session.add(
                Message(
                    conversation_id=act.conversation_id,
                    role="assistant",
                    content=f"Action `{act.action_type}` was declined by the user.",
                )
            )
        await session.commit()
        await session.refresh(act)
        return AgentActionResponse.model_validate(act)

    # Execute domain service deterministically (NO extra LLM call)
    act.approved_at = now
    act.status = "approved"
    result_data: dict[str, Any]
    summary_text: str

    if act.action_type == "create_budget":
        b_req = BudgetCreateRequest.model_validate(act.arguments)
        created_budget = await create_budget(session, user_id, b_req)
        result_data = {
            "budget_id": str(created_budget.id),
            "amount": str(Decimal(created_budget.amount)),
            "currency": created_budget.currency,
        }
        summary_text = (
            f"Confirmed and created budget ({created_budget.amount} {created_budget.currency})."
        )
    elif act.action_type == "create_shopping_list":
        sl_req = ShoppingListCreateRequest.model_validate(act.arguments)
        created_list = await create_shopping_list(session, user_id, sl_req)
        result_data = {
            "shopping_list_id": str(created_list.id),
            "name": created_list.name,
        }
        summary_text = f"Confirmed and created shopping list '{created_list.name}'."
    elif act.action_type == "add_shopping_list_item":
        sl_id = uuid.UUID(str(act.arguments["shopping_list_id"]))
        item_args = {k: v for k, v in act.arguments.items() if k != "shopping_list_id"}
        item_req = ShoppingListItemCreateRequest.model_validate(item_args)
        created_item = await add_shopping_list_item(session, user_id, sl_id, item_req)
        result_data = {
            "shopping_list_item_id": str(created_item.id),
            "product_name": created_item.product_name,
        }
        summary_text = f"Added '{created_item.product_name}' to your shopping list."
    else:
        raise BadRequestError(f"Unsupported action_type {act.action_type!r}")

    # Reload action in current session state & finalize status='executed'
    act_refreshed = await repo.get_by_id_or_raise(action_id)
    act_refreshed.status = "executed"
    act_refreshed.approved_at = now
    act_refreshed.executed_at = utcnow()
    act_refreshed.idempotency_key = idempotency_key
    act_refreshed.result = result_data

    if act_refreshed.conversation_id is not None:
        session.add(
            Message(
                conversation_id=act_refreshed.conversation_id,
                role="assistant",
                content=summary_text,
            )
        )

    await session.commit()
    await session.refresh(act_refreshed)
    return AgentActionResponse.model_validate(act_refreshed)
