"""Mandatory BaseRepository enforcing Option A server-side user scoping."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, NotFoundError


class BaseRepository[ModelT]:
    """Enforces user_id scoping on every query and mutation for user-owned models.

    `user_id` MUST come exclusively from server-side installation context,
    never from client request payloads or AI tool arguments.
    """

    def __init__(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        model: type[ModelT],
    ) -> None:
        if not isinstance(user_id, uuid.UUID):
            raise ValueError("Trusted server-side user_id UUID is required.")
        self._session = session
        self._user_id = user_id
        self._model: Any = model

    @property
    def session(self) -> AsyncSession:
        return self._session

    @property
    def user_id(self) -> uuid.UUID:
        return self._user_id

    def scoped_select(self) -> Select[tuple[ModelT]]:
        stmt: Select[tuple[ModelT]] = select(self._model).where(
            self._model.user_id == self._user_id
        )
        return stmt

    async def scalar_one_or_none(self, stmt: Select[tuple[ModelT]]) -> ModelT | None:
        result: ModelT | None = await self._session.scalar(stmt)
        return result

    async def list_matching(self, stmt: Select[tuple[ModelT]]) -> list[ModelT]:
        result = await self._session.scalars(stmt)
        rows: list[ModelT] = list(result.all())  # type: ignore[arg-type]
        return rows

    async def get_by_id(self, record_id: uuid.UUID) -> ModelT | None:
        stmt = self.scoped_select().where(self._model.id == record_id)
        return await self.scalar_one_or_none(stmt)

    async def get_by_id_or_raise(self, record_id: uuid.UUID) -> ModelT:
        instance = await self.get_by_id(record_id)
        if instance is None:
            raise NotFoundError(f"{self._model.__name__} not found")
        return instance

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[ModelT]:
        stmt = self.scoped_select().limit(limit).offset(offset)
        return await self.list_matching(stmt)

    async def create(self, **fields: Any) -> ModelT:
        fields.pop("user_id", None)
        instance: ModelT = self._model(user_id=self._user_id, **fields)
        self._session.add(instance)
        await self._session.flush()
        return instance

    async def update(self, record_id: uuid.UUID, **fields: Any) -> ModelT:
        fields.pop("user_id", None)
        fields.pop("id", None)
        instance = await self.get_by_id_or_raise(record_id)
        for key, value in fields.items():
            setattr(instance, key, value)
        await self._session.flush()
        return instance

    async def delete(self, record_id: uuid.UUID) -> None:
        instance = await self.get_by_id_or_raise(record_id)
        await self._session.delete(instance)
        await self._session.flush()

    async def verify_owned_reference(
        self,
        target_model: type[Any],
        target_id: uuid.UUID | None,
        *,
        allow_system: bool = False,
    ) -> Any | None:
        """Verify that a linked FK record belongs to the current user (or is system-owned)."""
        if target_id is None:
            return None
        model_any: Any = target_model
        instance = await self._session.scalar(select(model_any).where(model_any.id == target_id))
        if instance is None:
            raise NotFoundError(f"Referenced {target_model.__name__} not found")

        if allow_system and getattr(instance, "is_system", False) is True:
            return instance

        owner_id = getattr(instance, "user_id", None)
        if owner_id != self._user_id:
            raise ForbiddenError(f"Cross-user access to {target_model.__name__} is forbidden")
        return instance
