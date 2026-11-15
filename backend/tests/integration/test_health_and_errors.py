from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.errors import AppError, BootstrapUnavailableError, ConflictError, NotFoundError
from app.main import create_app


async def test_health_endpoint_returns_ok() -> None:
    app = create_app(Settings(_env_file=None, ENVIRONMENT="test"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "test"
    assert "timezone" in body


async def test_consistent_error_envelope_across_status_codes() -> None:
    app = create_app(Settings(_env_file=None, ENVIRONMENT="test"))
    test_router = APIRouter(prefix="/api/v1/_test-errors")

    @test_router.get("/not-found")
    async def raise_not_found() -> None:
        raise NotFoundError("Receipt not found", details={"receipt_id": "123"})

    @test_router.get("/conflict")
    async def raise_conflict() -> None:
        raise ConflictError("Duplicate receipt file", details={"existing_receipt_id": "abc"})

    @test_router.get("/bootstrap")
    async def raise_bootstrap() -> None:
        raise BootstrapUnavailableError("Local profile bootstrap unavailable")

    @test_router.get("/bad-request")
    async def raise_bad_request() -> None:
        raise AppError(status_code=400, code="bad_request", message="Invalid currency")

    app.include_router(test_router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r404 = await client.get("/api/v1/_test-errors/not-found")
        assert r404.status_code == 404
        assert r404.json()["error"]["code"] == "not_found"
        assert r404.json()["error"]["details"] == {"receipt_id": "123"}

        r409 = await client.get("/api/v1/_test-errors/conflict")
        assert r409.status_code == 409
        assert r409.json()["error"]["code"] == "conflict"

        r503 = await client.get("/api/v1/_test-errors/bootstrap")
        assert r503.status_code == 503
        assert r503.json()["error"]["code"] == "bootstrap_unavailable"

        r400 = await client.get("/api/v1/_test-errors/bad-request")
        assert r400.status_code == 400
        assert r400.json()["error"]["code"] == "bad_request"


async def test_cors_allows_localhost_and_blocks_external_origin() -> None:
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="test",
        CORS_ORIGINS="http://localhost:3000",
    )
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        allowed = await client.options(
            "/api/v1/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert allowed.headers.get("access-control-allow-origin") == "http://localhost:3000"

        blocked = await client.options(
            "/api/v1/health",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert blocked.headers.get("access-control-allow-origin") is None
