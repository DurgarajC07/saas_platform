"""
Files service.

Business logic for file upload, download, listing, and deletion.
Owns the storage adapter interaction and DB persistence via FileRepository.
"""

from __future__ import annotations

import hashlib
import math
from uuid import UUID, uuid4

import magic
import structlog
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import (
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.modules.auth.models import User
from app.modules.files.models import File
from app.modules.files.repository import FileRepository
from app.modules.files.schemas import (
    DeleteFileResponse,
    DownloadUrlResponse,
    FileListResponse,
    FileResponse,
    UploadResponse,
)
from app.modules.files.storage import StorageBase, get_storage
from app.shared.base_schemas import PaginationMeta

log = structlog.get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    {
        # Images
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
        "image/svg+xml",
        "image/tiff",
        # Documents
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        # Text
        "text/plain",
        "text/csv",
        "text/html",
        "text/markdown",
        # Archives
        "application/zip",
        "application/x-tar",
        "application/gzip",
        # Audio / Video (for voice SaaS)
        "audio/mpeg",
        "audio/ogg",
        "audio/wav",
        "audio/webm",
        "audio/flac",
        "video/mp4",
        "video/webm",
        "video/ogg",
        # JSON / data
        "application/json",
        "application/octet-stream",
    }
)

PRESIGNED_EXPIRES = 3600  # 1 hour


class FileService:
    def __init__(
        self,
        session: AsyncSession,
        storage: StorageBase | None = None,
    ) -> None:
        self.session = session
        self.repo = FileRepository(session)
        settings = get_settings()
        self.storage: StorageBase = storage or get_storage()
        self.settings = settings

    # ── Upload ────────────────────────────────────────────────────────────

    async def upload_file(
        self,
        *,
        file: UploadFile,
        uploader: User,
        org_id: UUID | None,
        attachable_type: str | None = None,
        attachable_id: UUID | None = None,
        is_public: bool = False,
    ) -> UploadResponse:
        """
        Validate, deduplicate, and persist an uploaded file.

        Steps:
        1. Read body and enforce 100 MB cap.
        2. Detect MIME type from file content (not extension) via libmagic.
        3. Validate MIME against allow-list.
        4. Compute SHA-256 checksum; return existing record if duplicate.
        5. Build org-scoped storage path and upload to backing store.
        6. Persist File row in DB.
        """
        content = await file.read()
        file_size = len(content)

        if file_size == 0:
            raise ValidationException("File is empty")
        if file_size > MAX_FILE_SIZE:
            raise ValidationException(
                f"File too large: {file_size / 1024 / 1024:.1f} MB (max 100 MB)"
            )

        # MIME detection from content — not from extension or Content-Type header
        detected_mime: str = magic.from_buffer(content, mime=True)
        if detected_mime not in ALLOWED_MIME_TYPES:
            raise ValidationException(f"File type not allowed: {detected_mime}")

        # SHA-256 deduplication
        checksum = hashlib.sha256(content).hexdigest()
        existing = await self.repo.get_by_checksum(org_id, checksum)
        if existing is not None:
            log.info(
                "file.deduplicated",
                checksum=checksum,
                existing_id=str(existing.id),
            )
            await self.session.commit()
            return UploadResponse(
                file=FileResponse.model_validate(existing),
                deduplicated=True,
            )

        # Build org-scoped path: {org_id}/{uuid}/{filename}
        org_prefix = str(org_id) if org_id else "shared"
        storage_path = f"{org_prefix}/{uuid4()}/{file.filename}"

        await self.storage.upload(storage_path, content, detected_mime)

        db_file = await self.repo.create(
            organization_id=org_id,
            uploaded_by=uploader.id,
            file_name=storage_path,
            original_name=file.filename or "upload",
            mime_type=detected_mime,
            file_size_bytes=file_size,
            storage_provider=self.settings.STORAGE_PROVIDER,
            storage_path=storage_path,
            checksum=checksum,
            attachable_type=attachable_type,
            attachable_id=attachable_id,
            is_public=is_public,
        )
        await self.session.commit()
        await self.session.refresh(db_file)

        log.info(
            "file.uploaded",
            file_id=str(db_file.id),
            path=storage_path,
            mime=detected_mime,
            bytes=file_size,
        )

        return UploadResponse(
            file=FileResponse.model_validate(db_file),
            deduplicated=False,
        )

    # ── Download ──────────────────────────────────────────────────────────

    async def get_download_url(
        self,
        *,
        file_id: UUID,
        requesting_user: User,
        org_id: UUID | None,
    ) -> DownloadUrlResponse:
        """Generate a presigned / direct URL for downloading a file."""
        db_file = await self._get_accessible_file(file_id, requesting_user, org_id)
        url = await self.storage.generate_presigned_url(
            db_file.storage_path, expires=PRESIGNED_EXPIRES
        )
        return DownloadUrlResponse(url=url, expires_in=PRESIGNED_EXPIRES)

    async def stream_file(
        self,
        *,
        file_id: UUID,
        requesting_user: User,
        org_id: UUID | None,
    ) -> tuple[bytes, str]:
        """
        Download the raw bytes from storage for direct streaming.

        Returns (content_bytes, mime_type).
        Used by the local-storage download endpoint.
        """
        db_file = await self._get_accessible_file(file_id, requesting_user, org_id)
        content = await self.storage.download(db_file.storage_path)
        return content, db_file.mime_type

    # ── Metadata ──────────────────────────────────────────────────────────

    async def get_file(
        self,
        *,
        file_id: UUID,
        requesting_user: User,
        org_id: UUID | None,
    ) -> FileResponse:
        """Return file metadata (no content download)."""
        db_file = await self._get_accessible_file(file_id, requesting_user, org_id)
        return FileResponse.model_validate(db_file)

    # ── List ──────────────────────────────────────────────────────────────

    async def list_files(
        self,
        *,
        org_id: UUID | None,
        attachable_type: str | None = None,
        attachable_id: UUID | None = None,
        uploaded_by: UUID | None = None,
        mime_type: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> FileListResponse:
        limit = page_size
        offset = (page - 1) * page_size
        rows, total = await self.repo.list_files(
            org_id,
            attachable_type=attachable_type,
            attachable_id=attachable_id,
            uploaded_by=uploaded_by,
            mime_type=mime_type,
            limit=limit,
            offset=offset,
        )
        total_pages = max(1, math.ceil(total / page_size))
        return FileListResponse(
            files=[FileResponse.model_validate(r) for r in rows],
            pagination=PaginationMeta(
                page=page,
                page_size=page_size,
                total_items=total,
                total_pages=total_pages,
                has_next=page < total_pages,
                has_previous=page > 1,
            ),
        )

    # ── Delete ────────────────────────────────────────────────────────────

    async def delete_file(
        self,
        *,
        file_id: UUID,
        requesting_user: User,
        org_id: UUID | None,
    ) -> DeleteFileResponse:
        """
        Soft-delete the DB record and enqueue async storage cleanup via Celery.
        """
        db_file = await self._get_accessible_file(file_id, requesting_user, org_id)
        storage_path = db_file.storage_path
        storage_provider = db_file.storage_provider

        deleted = await self.repo.soft_delete(file_id)
        if deleted is None:
            raise NotFoundException("File not found")
        await self.session.commit()

        # Enqueue async cleanup — do not block the HTTP response
        try:
            from app.tasks.files import cleanup_storage_object
            cleanup_storage_object.delay(
                storage_path=storage_path,
                storage_provider=storage_provider,
            )
        except Exception as exc:  # pylint: disable=broad-except
            log.warning("file.cleanup_dispatch_failed", error=str(exc), path=storage_path)

        log.info("file.soft_deleted", file_id=str(file_id), path=storage_path)
        return DeleteFileResponse(deleted=True, file_id=file_id)

    # ── Internal helpers ──────────────────────────────────────────────────

    async def _get_accessible_file(
        self, file_id: UUID, user: User, org_id: UUID | None
    ) -> File:
        """
        Fetch a non-deleted file and enforce org-scoped access control.

        Public files are visible to any authenticated user.
        Private files require the requester to belong to the same org
        or to be the uploader.
        """
        db_file = await self.repo.get_by_id(file_id)
        if db_file is None:
            raise NotFoundException("File not found")

        if db_file.is_public:
            return db_file

        # Org-scoped: requester must be in the same org or be the uploader
        same_org = org_id is not None and db_file.organization_id == org_id
        is_owner = db_file.uploaded_by == user.id

        if not (same_org or is_owner):
            raise ForbiddenException("You do not have access to this file")

        return db_file
