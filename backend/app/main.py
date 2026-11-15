"""FastAPI application factory and lifespan bootstrap."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.router import api_v1_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.db.seed import seed_reference_data
from app.db.session import build_engine, build_session_factory
from app.services.profile_service import bootstrap_local_profile
from app.services.storage_service import PrivateStorageService, build_storage_service


def create_app(
    settings: Settings | None = None,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    storage_service: PrivateStorageService | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.environment)

    owns_engine = session_factory is None
    engine = build_engine(resolved_settings) if owns_engine else None
    resolved_session_factory = session_factory or build_session_factory(engine)  # type: ignore[arg-type]
    resolved_storage = storage_service or build_storage_service(resolved_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if resolved_settings.environment != "test":
            async with resolved_session_factory() as session:
                await seed_reference_data(session)
            await bootstrap_local_profile(
                resolved_session_factory,
                default_currency=resolved_settings.default_currency,
                default_locale=resolved_settings.default_locale,
            )
        try:
            yield
        finally:
            if owns_engine and engine is not None:
                await engine.dispose()

    application = FastAPI(
        title="AI Grocery & Household Shopping Expense Manager API",
        version=resolved_settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.session_factory = resolved_session_factory
    application.state.storage_service = resolved_storage

    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    register_exception_handlers(application)
    application.include_router(api_v1_router)
    return application


app = create_app()
