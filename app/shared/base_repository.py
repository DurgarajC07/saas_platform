"""
Generic BaseRepository[ModelType].

Every module-level repository extends this class, which provides
type-safe CRUD operations backed by an AsyncSession.

Design decisions:
  - flush() after create/update so the caller gets generated IDs immediately
    without committing the transaction (commit is handled at the request layer).
  - Soft-delete by setting deleted_at instead of issuing DELETE.
  - All queries default to excluding soft-deleted rows.
"""

from __future__ import annotations

from typing import Any, Generic, Sequence, Type, TypeVar
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

ModelType = TypeVar("ModelType")


class BaseRepository(Generic[ModelType]):
    def __init__(self, model: Type[ModelType], session: AsyncSession) -> None:
        self.model = model
        self.session = session

    # ── Read ──────────────────────────────────────────────────────────────
    async def get_by_id(self, id: UUID) -> ModelType | None:
        """Return a single row by primary key, or None if not found / soft-deleted."""
        result = await self.session.execute(
            select(self.model).where(
                self.model.id == id,  # type: ignore[attr-defined]
                self.model.deleted_at.is_(None),  # type: ignore[attr-defined]
            )
        )
        return result.scalar_one_or_none()

    async def get_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        **filters: Any,
    ) -> Sequence[ModelType]:
        """Return all non-deleted rows, with optional keyword filter and pagination."""
        stmt = select(self.model).where(
            self.model.deleted_at.is_(None)  # type: ignore[attr-defined]
        )
        for attr, value in filters.items():
            stmt = stmt.where(getattr(self.model, attr) == value)
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(self, **filters: Any) -> int:
        """Return the count of non-deleted rows matching optional filters."""
        stmt = select(func.count()).select_from(self.model).where(
            self.model.deleted_at.is_(None)  # type: ignore[attr-defined]
        )
        for attr, value in filters.items():
            stmt = stmt.where(getattr(self.model, attr) == value)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    # ── Write ─────────────────────────────────────────────────────────────
    async def create(self, **kwargs: Any) -> ModelType:
        """Insert a new row and flush so generated columns are populated."""
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def update(self, id: UUID, **kwargs: Any) -> ModelType | None:
        """Update columns by primary key and return the refreshed row."""
        await self.session.execute(
            update(self.model)
            .where(
                self.model.id == id,  # type: ignore[attr-defined]
                self.model.deleted_at.is_(None),  # type: ignore[attr-defined]
            )
            .values(**kwargs)
        )
        await self.session.flush()
        return await self.get_by_id(id)

    async def soft_delete(self, id: UUID) -> None:
        """Mark a row as deleted without physically removing it."""
        await self.session.execute(
            update(self.model)
            .where(self.model.id == id)  # type: ignore[attr-defined]
            .values(deleted_at=func.now())
        )
        await self.session.flush()

    async def hard_delete(self, id: UUID) -> None:
        """Physically remove a row — use only where absolutely necessary."""
        instance = await self.get_by_id(id)
        if instance is not None:
            await self.session.delete(instance)
            await self.session.flush()
