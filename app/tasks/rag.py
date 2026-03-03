"""
Celery task: async document ingestion into the agent knowledge base.

Flow
────
1. Transition the ``kb_documents`` record to *processing*.
2. Read the temp file from the local storage path.
3. Extract plain text (PDF / DOCX / TXT / MD / CSV / URL / YouTube).
4. Chunk, embed (BAAI/bge-small-en-v1.5), and upsert into Qdrant.
5. Mark the ``kb_documents`` record as *completed* with the chunk count.
6. On any error: mark the record as *failed* with the error message and
   schedule an exponential-backoff retry (up to 3 attempts).

The task accepts all its parameters as plain JSON-serialisable strings so
the Celery result backend can serialise them without custom encoders.
"""

from __future__ import annotations

import asyncio
import os
from uuid import UUID

import structlog

from app.core.celery_app import celery_app

log = structlog.get_logger(__name__)


@celery_app.task(
    bind=True,
    name="app.tasks.rag.async_ingest_document",
    max_retries=3,
    default_retry_delay=30,
    queue="default",
    acks_late=True,
)
def async_ingest_document(
    self,
    *,
    doc_id: str,
    agent_id: str,
    org_id: str,
    tmp_path: str,
    file_name: str,
    file_type: str,
    collection: str,
    source_url: str | None = None,
) -> dict:
    """
    Run document ingestion synchronously (wraps the async inner function).

    Args:
        doc_id:      UUID of the ``kb_documents`` row (string form).
        agent_id:    UUID of the owning agent.
        org_id:      UUID of the owning organisation.
        tmp_path:    Absolute path to the previously-uploaded temp file.
        file_name:   Original file name (for logging).
        file_type:   One of pdf | docx | txt | md | csv | url | youtube.
        collection:  Qdrant collection name (``{org_id}_{agent_id}``).
        source_url:  For ``url`` / ``youtube`` types — the source URL.
    """
    try:
        return asyncio.run(
            _ingest_async(
                doc_id=doc_id,
                agent_id=agent_id,
                org_id=org_id,
                tmp_path=tmp_path,
                file_name=file_name,
                file_type=file_type,
                collection=collection,
                source_url=source_url,
            )
        )
    except Exception as exc:
        retry_count = self.request.retries
        countdown = 30 * (2 ** retry_count)
        log.warning(
            "rag_ingest.retry",
            doc_id=doc_id,
            file_name=file_name,
            attempt=retry_count + 1,
            countdown=countdown,
            error=str(exc),
        )
        raise self.retry(exc=exc, countdown=countdown)


async def _ingest_async(
    *,
    doc_id: str,
    agent_id: str,
    org_id: str,
    tmp_path: str,
    file_name: str,
    file_type: str,
    collection: str,
    source_url: str | None,
) -> dict:
    """Async body of the ingestion task — runs inside asyncio.run()."""
    from app.core.database import AsyncSessionFactory
    from app.modules.agents.kb_repository import KbDocumentRepository
    from app.modules.agents.kb_service import KnowledgeBaseIngestor, _extract_text

    async with AsyncSessionFactory() as db:
        repo = KbDocumentRepository(db)

        # 1. Mark processing
        await repo.mark_processing(UUID(doc_id))
        await db.commit()

        try:
            # 2. Read file content
            if file_type in ("url", "youtube"):
                data = b""  # content is fetched inside _extract_text
            else:
                if not os.path.exists(tmp_path):
                    raise FileNotFoundError(f"Temp file not found: {tmp_path}")
                with open(tmp_path, "rb") as fh:
                    data = fh.read()

            # 3. Extract text
            text = await _extract_text(
                data=data,
                file_name=file_name,
                file_type=file_type,
                source_url=source_url,
            )

            # 4. Chunk + embed + upsert
            ingestor = KnowledgeBaseIngestor()
            chunk_count = await ingestor.ingest_document(
                collection=collection,
                doc_id=doc_id,
                text=text,
                metadata={
                    "agent_id": agent_id,
                    "org_id": org_id,
                    "file_name": file_name,
                    "file_type": file_type,
                    "source_url": source_url,
                },
            )

            # 5. Mark completed
            await repo.mark_completed(UUID(doc_id), chunk_count)
            await db.commit()

            log.info(
                "rag_ingest.completed",
                doc_id=doc_id,
                file_name=file_name,
                chunk_count=chunk_count,
            )

        except Exception as exc:
            # 6. Mark failed — do NOT re-raise here; Celery retry logic is in
            #    the outer sync wrapper.
            await repo.mark_failed(UUID(doc_id), str(exc))
            await db.commit()
            log.error("rag_ingest.failed", doc_id=doc_id, error=str(exc))
            raise  # propagate so outer wrapper can retry

        finally:
            # Clean up temp file regardless of outcome
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    return {"doc_id": doc_id, "chunk_count": chunk_count}
