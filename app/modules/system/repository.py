"""
System module repository.

Typed async data-access for the ``system_settings`` table.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.system.models import SystemSetting


class SystemSettingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_key(self, key: str) -> SystemSetting | None:
        result = await self.session.execute(
            select(SystemSetting).where(SystemSetting.key == key)
        )
        return result.scalar_one_or_none()

    async def list_all(self, *, public_only: bool = False) -> list[SystemSetting]:
        stmt = select(SystemSetting).order_by(SystemSetting.key)
        if public_only:
            stmt = stmt.where(SystemSetting.is_public.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def upsert(
        self,
        *,
        key: str,
        value: Any,
        updated_by: UUID | None = None,
        description: str | None = None,
        is_public: bool | None = None,
    ) -> SystemSetting:
        """
        Insert or update a system setting by key.
        Uses PostgreSQL ON CONFLICT DO UPDATE for atomicity.
        """
        now = datetime.now(UTC)

        on_conflict_set: dict[str, Any] = {
            "value": value,
            "updated_by": updated_by,
            "updated_at": now,
        }
        if description is not None:
            on_conflict_set["description"] = description
        if is_public is not None:
            on_conflict_set["is_public"] = is_public

        stmt = (
            insert(SystemSetting)
            .values(
                key=key,
                value=value,
                description=description,
                is_public=is_public if is_public is not None else False,
                updated_by=updated_by,
                updated_at=now,
            )
            .on_conflict_do_update(index_elements=["key"], set_=on_conflict_set)
            .returning(SystemSetting)
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one()
        await self.session.flush()
        return row

    async def delete_by_key(self, key: str) -> bool:
        """Delete a setting by key. Returns True if a row was deleted."""
        result = await self.session.execute(
            delete(SystemSetting).where(SystemSetting.key == key)
        )
        await self.session.flush()
        return result.rowcount > 0
