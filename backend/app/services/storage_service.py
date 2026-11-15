"""Backend-only private Supabase Storage service (never exposes keys to frontend)."""

from __future__ import annotations

from typing import Protocol

import httpx

from app.core.config import Settings
from app.core.errors import AppError, NotFoundError


class StoredObject(tuple[bytes, str]):
    """Bytes and MIME type pair."""


class PrivateStorageService(Protocol):
    async def upload(self, *, bucket: str, path: str, data: bytes, content_type: str) -> str: ...

    async def download(self, *, bucket: str, path: str) -> tuple[bytes, str]: ...

    async def delete(self, *, bucket: str, path: str) -> None: ...


class InMemoryPrivateStorage:
    """In-memory private storage used in tests and unconfigured local development."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], tuple[bytes, str]] = {}

    async def upload(self, *, bucket: str, path: str, data: bytes, content_type: str) -> str:
        self._store[(bucket, path)] = (data, content_type)
        return path

    async def download(self, *, bucket: str, path: str) -> tuple[bytes, str]:
        item = self._store.get((bucket, path))
        if item is None:
            raise NotFoundError("Stored file not found")
        return item

    async def delete(self, *, bucket: str, path: str) -> None:
        self._store.pop((bucket, path), None)


class SupabasePrivateStorage:
    """Private Supabase Storage REST adapter using backend-only SUPABASE_SECRET_KEY."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.supabase_url.rstrip("/")
        self._secret_key = settings.supabase_secret_key

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._secret_key}",
            "apikey": self._secret_key,
        }
        if content_type:
            headers["Content-Type"] = content_type
            headers["x-upsert"] = "true"
        return headers

    async def upload(self, *, bucket: str, path: str, data: bytes, content_type: str) -> str:
        url = f"{self._base_url}/storage/v1/object/{bucket}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(url, content=data, headers=self._headers(content_type))
        if res.status_code >= 400:
            raise AppError(
                status_code=502,
                code="storage_upload_failed",
                message="Failed to store file in private Supabase Storage",
            )
        return path

    async def download(self, *, bucket: str, path: str) -> tuple[bytes, str]:
        url = f"{self._base_url}/storage/v1/object/{bucket}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.get(url, headers=self._headers())
        if res.status_code == 404:
            raise NotFoundError("Stored file not found")
        if res.status_code >= 400:
            raise AppError(
                status_code=502,
                code="storage_download_failed",
                message="Failed to fetch file from private Supabase Storage",
            )
        content_type = res.headers.get("content-type", "application/octet-stream")
        return res.content, content_type

    async def delete(self, *, bucket: str, path: str) -> None:
        url = f"{self._base_url}/storage/v1/object/{bucket}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.delete(url, headers=self._headers())


def build_storage_service(settings: Settings) -> PrivateStorageService:
    if settings.supabase_url and settings.supabase_secret_key:
        return SupabasePrivateStorage(settings)
    return InMemoryPrivateStorage()
