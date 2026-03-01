"""
Files module Pydantic schemas.

All response models use CamelModel (alias_generator=to_camel) so the
JSON response uses camelCase while Python code uses snake_case.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import AliasChoices, Field, field_validator

from app.shared.base_schemas import CamelModel, PaginationMeta


# ── File response ─────────────────────────────────────────────────────────

class FileResponse(CamelModel):
    id: UUID
    organization_id: UUID | None
    uploaded_by: UUID
    file_name: str
    original_name: str
    mime_type: str
    file_size_bytes: int
    storage_provider: str
    storage_path: str
    attachable_type: str | None
    attachable_id: UUID | None
    checksum: str | None
    is_public: bool
    # ORM attribute is `metadata_`; accept both names during validation
    metadata: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("metadata_", "metadata"),
    )
    created_at: datetime
    updated_at: datetime

    @field_validator("metadata", mode="before")
    @classmethod
    def coerce_metadata(cls, v: object) -> dict:
        if v is None:
            return {}
        return v if isinstance(v, dict) else {}


class FileListResponse(CamelModel):
    files: list[FileResponse]
    pagination: PaginationMeta


# ── Upload response ───────────────────────────────────────────────────────

class UploadResponse(CamelModel):
    file: FileResponse
    deduplicated: bool = Field(
        default=False,
        description="True when an identical file already existed; no new storage was consumed.",
    )


# ── Presigned URL response ────────────────────────────────────────────────

class DownloadUrlResponse(CamelModel):
    url: str
    expires_in: int = 3600


# ── Delete response ───────────────────────────────────────────────────────

class DeleteFileResponse(CamelModel):
    deleted: bool = True
    file_id: UUID
