"""
Files / Media module ORM models.

Tables: files
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.base_models import SoftDeleteMixin, TimestampMixin


class File(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    original_name: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(150), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_provider: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # s3 | gcs | azure | local
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)

    # Polymorphic attachment
    attachable_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    attachable_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    checksum: Mapped[str | None] = mapped_column(String(255), nullable=True)  # SHA-256
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_files_org", "organization_id"),
        Index("ix_files_attachable", "attachable_type", "attachable_id"),
        Index("ix_files_deleted_at", "deleted_at"),
    )

    def __repr__(self) -> str:
        return f"<File name={self.file_name} org={self.organization_id}>"
