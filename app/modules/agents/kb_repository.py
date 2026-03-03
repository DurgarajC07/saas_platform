"""
Knowledge-base document repository.

Handles all PostgreSQL persistence for the ``kb_documents`` table.
Qdrant operations are handled by ``kb_service.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents.models import KnowledgeBaseDocument

log = structlog.get_logger(__name__)


class KbDocumentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Write ─────────────────────────────────────────────────────────────

    async def create(
        self,
        *,
        agent_id: UUID,
        org_id: UUID,
        file_name: str,
        file_type: str,
        file_size_bytes: int | None = None,
        source_url: str | None = None,
    ) -> KnowledgeBaseDocument:
        now = datetime.now(UTC)
        doc = KnowledgeBaseDocument(
            agent_id=agent_id,
            org_id=org_id,
            file_name=file_name,
            file_type=file_type,
            file_size_bytes=file_size_bytes,
            source_url=source_url,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        self._db.add(doc)
        await self._db.flush()
        await self._db.refresh(doc)
        return doc

    async def mark_processing(self, doc_id: UUID) -> None:
        await self._db.execute(
            update(KnowledgeBaseDocument)
            .where(KnowledgeBaseDocument.id == doc_id)
            .values(status="processing", updated_at=datetime.now(UTC))
        )

    async def mark_completed(self, doc_id: UUID, chunk_count: int) -> None:
        await self._db.execute(
            update(KnowledgeBaseDocument)
            .where(KnowledgeBaseDocument.id == doc_id)
            .values(
                status="completed",
                chunk_count=chunk_count,
                updated_at=datetime.now(UTC),
            )
        )

    async def mark_failed(self, doc_id: UUID, error_message: str) -> None:
        await self._db.execute(
            update(KnowledgeBaseDocument)
            .where(KnowledgeBaseDocument.id == doc_id)
            .values(
                status="failed",
                error_message=error_message,
                updated_at=datetime.now(UTC),
            )
        )

    async def delete(self, doc_id: UUID) -> None:
        doc = await self.get_by_id(doc_id)
        if doc:
            await self._db.delete(doc)

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_by_id(self, doc_id: UUID) -> KnowledgeBaseDocument | None:
        result = await self._db.execute(
            select(KnowledgeBaseDocument).where(KnowledgeBaseDocument.id == doc_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_and_agent(
        self, doc_id: UUID, agent_id: UUID
    ) -> KnowledgeBaseDocument | None:
        result = await self._db.execute(
            select(KnowledgeBaseDocument).where(
                KnowledgeBaseDocument.id == doc_id,
                KnowledgeBaseDocument.agent_id == agent_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_agent(
        self,
        agent_id: UUID,
        *,
        status: str | None = None,
    ) -> list[KnowledgeBaseDocument]:
        stmt = select(KnowledgeBaseDocument).where(
            KnowledgeBaseDocument.agent_id == agent_id
        )
        if status:
            stmt = stmt.where(KnowledgeBaseDocument.status == status)
        stmt = stmt.order_by(KnowledgeBaseDocument.created_at.desc())
        result = await self._db.execute(stmt)
        return list(result.scalars().all())
