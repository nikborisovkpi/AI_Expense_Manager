"""API routes for Budgets (/api/v1/budgets)."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_profile, get_current_user_id
from app.db.session import get_db_session
from app.models.profile import Profile
from app.schemas.budget import (
    BudgetCreateRequest,
    BudgetResponse,
    BudgetStatusResponse,
    BudgetUpdateRequest,
)
from app.services.budget_service import (
    create_budget,
    delete_budget,
    get_budgets_status,
    list_budgets,
    update_budget,
)

router = APIRouter(prefix="/budgets", tags=["budgets"])


@router.get("", response_model=list[BudgetResponse])
async def get_all_budgets(
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[BudgetResponse]:
    budgets = await list_budgets(session, user_id)
    return [BudgetResponse.model_validate(b) for b in budgets]


@router.post("", response_model=BudgetResponse, status_code=status.HTTP_201_CREATED)
async def post_budget(
    payload: BudgetCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> BudgetResponse:
    budget = await create_budget(session, user_id, payload)
    return BudgetResponse.model_validate(budget)


@router.get("/status", response_model=list[BudgetStatusResponse])
async def read_budgets_status(
    reference_date: date | None = None,
    session: AsyncSession = Depends(get_db_session),
    profile: Profile = Depends(get_current_profile),
) -> list[BudgetStatusResponse]:
    return await get_budgets_status(session, profile, reference_date=reference_date)


@router.patch("/{budget_id}", response_model=BudgetResponse)
async def patch_budget(
    budget_id: uuid.UUID,
    payload: BudgetUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> BudgetResponse:
    budget = await update_budget(session, user_id, budget_id, payload)
    return BudgetResponse.model_validate(budget)


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_budget(
    budget_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> Response:
    await delete_budget(session, user_id, budget_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
