"""Aggregate v1 API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.analytics import router as analytics_router
from app.api.v1.budgets import router as budgets_router
from app.api.v1.catalog import router as catalog_router
from app.api.v1.health import router as health_router
from app.api.v1.profile import router as profile_router
from app.api.v1.purchases import router as purchases_router
from app.api.v1.receipts import router as receipts_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health_router)
api_v1_router.include_router(profile_router)
api_v1_router.include_router(catalog_router)
api_v1_router.include_router(purchases_router)
api_v1_router.include_router(budgets_router)
api_v1_router.include_router(analytics_router)
api_v1_router.include_router(receipts_router)
