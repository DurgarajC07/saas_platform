"""
Files module repository.

Provides typed async data-access methods for the ``files`` table.
All queries exclude soft-deleted rows by default.
"""

from __future__ import annotations

from datetime import datetime, UTC
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.files.models import File


class FileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Create ────────────────────────────────────────────────────────────

    async def create(
        self,
        *,
        organization_id: UUID | None,
        uploaded_by: UUID,
        file_name: str,
        original_name: str,
        mime_type: str,
        file_size_bytes: int,
        storage_provider: str,
        storage_path: str,
        checksum: str | None = None,
        attachable_type: str | None = None,
        attachable_id: UUID | None = None,
        is_public: bool = False,
        metadata: dict | None = None,
    ) -> File:
        file = File(
            organization_id=organization_id,
            uploaded_by=uploaded_by,
            file_name=file_name,
            original_name=original_name,
            mime_type=mime_type,
            file_size_bytes=file_size_bytes,
            storage_provider=storage_provider,
            storage_path=storage_path,
            checksum=checksum,
            attachable_type=attachable_type,
            attachable_id=attachable_id,
            is_public=is_public,
            metadata_=metadata or {},
        )
        self.session.add(file)
        await self.session.flush()
        await self.session.refresh(file)
        return file

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_by_id(self, file_id: UUID) -> File | None:
        """Return a non-deleted file by primary key."""
        result = await self.session.execute(
            select(File).where(File.id == file_id, File.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_checksum(
        self, organization_id: UUID | None, checksum: str
    ) -> File | None:
        """
        Deduplication lookup: return an existing non-deleted file that
        matches both the org and the SHA-256 checksum.
        """
        stmt = select(File).where(
            File.checksum == checksum,
            File.deleted_at.is_(None),
        )
        if organization_id is not None:
            stmt = stmt.where(File.organization_id == organization_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_files(
        self,
        organization_id: UUID | None,
        *,
        attachable_type: str | None = None,
        attachable_id: UUID | None = None,
        uploaded_by: UUID | None = None,
        mime_type: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[File], int]:
        """
        Return (rows, total_count) for paginated file listing.

        All filter parameters are optional additive constraints.
        """
        stmt = select(File).where(File.deleted_at.is_(None))
        count_stmt = select(func.count()).select_from(File).where(File.deleted_at.is_(None))

        if organization_id is not None:
            stmt = stmt.where(File.organization_id == organization_id)
            count_stmt = count_stmt.where(File.organization_id == organization_id)
        if attachable_type is not None:
            stmt = stmt.where(File.attachable_type == attachable_type)
            count_stmt = count_stmt.where(File.attachable_type == attachable_type)
        if attachable_id is not None:
            stmt = stmt.where(File.attachable_id == attachable_id)
            count_stmt = count_stmt.where(File.attachable_id == attachable_id)
        if uploaded_by is not None:
            stmt = stmt.where(File.uploaded_by == uploaded_by)
            count_stmt = count_stmt.where(File.uploaded_by == uploaded_by)
        if mime_type is not None:
            stmt = stmt.where(File.mime_type == mime_type)
            count_stmt = count_stmt.where(File.mime_type == mime_type)

        stmt = stmt.order_by(File.created_at.desc()).limit(limit).offset(offset)

        rows_result = await self.session.execute(stmt)
        count_result = await self.session.execute(count_stmt)

        return list(rows_result.scalars().all()), count_result.scalar_one()

    # ── Soft delete ───────────────────────────────────────────────────────

    async def soft_delete(self, file_id: UUID) -> File | None:
        """
        Set deleted_at on the row.  Returns the updated file or None if
        it was already deleted / not found.
        """
        file = await self.get_by_id(file_id)
        if file is None:
            return None
        file.deleted_at = datetime.now(UTC)
        await self.session.flush()
        await self.session.refresh(file)
        return file
