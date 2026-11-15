"""Consistent domain exceptions and HTTP error handlers (Section 6.13)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base structured application error."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


class BadRequestError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(status_code=400, code="bad_request", message=message, details=details)


class ForbiddenError(AppError):
    def __init__(
        self, message: str = "Unauthorized operation", details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(status_code=403, code="forbidden", message=message, details=details)


class NotFoundError(AppError):
    def __init__(
        self, message: str = "Resource not found", details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(status_code=404, code="not_found", message=message, details=details)


class ConflictError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(status_code=409, code="conflict", message=message, details=details)


class ValidationDomainError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(status_code=422, code="validation_error", message=message, details=details)


class RateLimitError(AppError):
    def __init__(
        self, message: str = "Rate limit exceeded", details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(
            status_code=429, code="rate_limit_exceeded", message=message, details=details
        )


class BootstrapUnavailableError(AppError):
    def __init__(
        self,
        message: str = "Local profile bootstrap unavailable",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=503, code="bootstrap_unavailable", message=message, details=details
        )


def _error_payload(
    code: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    """Attach consistent JSON error envelopes to a FastAPI instance."""

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                "validation_error",
                "Request payload validation failed",
                {"issues": exc.errors()},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code_map = {
            400: "bad_request",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            422: "validation_error",
            429: "rate_limit_exceeded",
            503: "bootstrap_unavailable",
        }
        code = code_map.get(exc.status_code, "http_error")
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(code, str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled application error: %s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content=_error_payload(
                "internal_server_error", "An unexpected internal error occurred."
            ),
        )
