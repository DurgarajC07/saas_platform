"""
Knowledge-base service layer.

KnowledgeBaseService  — HTTP-layer coordinator (DB + task dispatch)
KnowledgeBaseIngestor — Core ingestion engine (chunking + embedding + Qdrant)

Architecture
────────────
                          ┌────────────────────────────────────────┐
  POST /knowledge-base    │  KnowledgeBaseService.upload_document  │
  (multipart upload)  ──► │   1. save temp file                    │
                          │   2. create KbDocument(pending) in DB  │
                          │   3. enqueue async_ingest_document      │
                          │   4. return 202 + doc_id               │
                          └────────────────────────────────────────┘

  Celery worker           ┌────────────────────────────────────────┐
  async_ingest_document ──► KnowledgeBaseIngestor.ingest_document  │
                          │   1. extract text from file/URL         │
                          │   2. chunk text (char-level)            │
                          │   3. embed with BAAI/bge-small-en-v1.5  │
                          │   4. upsert Qdrant points               │
                          │   5. update KbDocument(completed)       │
                          └────────────────────────────────────────┘

Collection naming follows tenant-isolation contract:
    {org_id}_{agent_id}  (e.g. "3f8fd6fc_0a94de0a")

Supported input formats for ingestion
──────────────────────────────────────
  pdf       PyMuPDF (fitz)
  docx      python-docx
  txt / md  direct read
  csv       row-by-row with headers as metadata
  url       html2text + httpx async fetch
  youtube   youtube-transcript-api
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import textwrap
import uuid as _uuid
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import NotFoundException, ValidationException
from app.core.qdrant import get_qdrant_client
from app.modules.agents.kb_repository import KbDocumentRepository
from app.modules.agents.models import KnowledgeBaseDocument
from app.modules.agents.repository import AgentRepository
from app.modules.agents.schemas import (
    KB_FILE_TYPES,
    KbDeleteDocResponse,
    KbDocumentListResponse,
    KbDocumentResponse,
    KbUploadResponse,
)

if TYPE_CHECKING:
    from fastapi import UploadFile

log = structlog.get_logger(__name__)

_settings = get_settings()

# ── helpers ───────────────────────────────────────────────────────────────────

def _collection_name(org_id: UUID, agent_id: UUID) -> str:
    """Derive the Qdrant collection name for an agent (tenant-isolated)."""
    return f"{str(org_id).replace('-', '')}_{str(agent_id).replace('-', '')}"


def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """
    Split *text* into overlapping character-level chunks.

    Using characters rather than tokens avoids a tokenizer dependency;
    at ~4 chars/token, chunk_size=512 ≈ 128 tokens which fits comfortably
    inside bge-small-en-v1.5's 512-token maximum.
    """
    if not text.strip():
        return []
    char_budget = chunk_size * 4          # rough chars per token
    step = max(1, char_budget - overlap * 4)
    chunks: list[str] = []
    for start in range(0, len(text), step):
        chunk = text[start : start + char_budget].strip()
        if chunk:
            chunks.append(chunk)
    return chunks


# ── Text extractors ───────────────────────────────────────────────────────────

def _extract_pdf(data: bytes) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError("PyMuPDF not installed: pip install pymupdf") from exc
    doc = fitz.open(stream=data, filetype="pdf")
    return "\n".join(page.get_text() for page in doc)


def _extract_docx(data: bytes) -> str:
    try:
        import docx  # python-docx
    except ImportError as exc:
        raise RuntimeError("python-docx not installed: pip install python-docx") from exc
    document = docx.Document(io.BytesIO(data))
    return "\n".join(para.text for para in document.paragraphs if para.text.strip())


def _extract_csv(data: bytes) -> str:
    text_io = io.StringIO(data.decode("utf-8", errors="replace"))
    reader = csv.DictReader(text_io)
    rows = []
    for row in reader:
        rows.append(", ".join(f"{k}: {v}" for k, v in row.items()))
    return "\n".join(rows)


async def _extract_url(url: str) -> str:
    try:
        import html2text
        import httpx
    except ImportError as exc:
        raise RuntimeError(
            "html2text / httpx not installed: pip install html2text httpx"
        ) from exc
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        response = await client.get(url)
        response.raise_for_status()
    h = html2text.HTML2Text()
    h.ignore_links = True
    h.ignore_images = True
    return h.handle(response.text)


def _extract_youtube(url: str) -> str:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore[import]
        from youtube_transcript_api._errors import NoTranscriptFound  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "youtube-transcript-api not installed: pip install youtube-transcript-api"
        ) from exc
    video_id = url.split("v=")[-1].split("&")[0]
    transcript = YouTubeTranscriptApi.get_transcript(video_id)
    return " ".join(entry["text"] for entry in transcript)


async def _extract_text(data: bytes, file_name: str, file_type: str, source_url: str | None) -> str:
    """Dispatch to the correct extractor based on *file_type*."""
    ft = file_type.lower()
    if ft == "pdf":
        return _extract_pdf(data)
    if ft == "docx":
        return _extract_docx(data)
    if ft in ("txt", "md"):
        return data.decode("utf-8", errors="replace")
    if ft == "csv":
        return _extract_csv(data)
    if ft == "url":
        return await _extract_url(source_url or file_name)
    if ft == "youtube":
        return _extract_youtube(source_url or file_name)
    # Fallback: try raw UTF-8
    return data.decode("utf-8", errors="replace")


# ═══════════════════════════════════════════════════════════════════════════════
# Core ingestor (also used directly from services/rag/ingestion.py)
# ═══════════════════════════════════════════════════════════════════════════════


class KnowledgeBaseIngestor:
    """
    Low-level ingestion engine — stateless, no DB access.

    Used by:
    • KnowledgeBaseService (HTTP layer, creates DB record first)
    • Celery task async_ingest_document (updates DB record after)
    • RAGRetrievalProcessor (query path, see services/rag/retrieval.py)
    """

    EMBED_MODEL = _settings.RAG_EMBED_MODEL
    CHUNK_SIZE = _settings.RAG_CHUNK_SIZE
    CHUNK_OVERLAP = _settings.RAG_CHUNK_OVERLAP
    VECTOR_SIZE = 384  # BAAI/bge-small-en-v1.5

    def __init__(self) -> None:
        from fastembed import TextEmbedding  # lazy import — model download on first use
        self._embedder = TextEmbedding(self.EMBED_MODEL)
        self._qdrant = get_qdrant_client()

    # ── Collection management ──────────────────────────────────────────────

    async def ensure_collection(self, collection: str) -> None:
        """Create the Qdrant collection if it does not exist yet."""
        from qdrant_client.models import Distance, VectorParams  # type: ignore[import]

        resp = await self._qdrant.get_collections()
        existing = {c.name for c in resp.collections}
        if collection not in existing:
            await self._qdrant.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(
                    size=self.VECTOR_SIZE,
                    distance=Distance.COSINE,
                ),
            )
            log.info("qdrant.collection_created", collection=collection)

    # ── Ingestion ─────────────────────────────────────────────────────────

    async def ingest_document(
        self,
        *,
        collection: str,
        doc_id: str,
        text: str,
        metadata: dict,
    ) -> int:
        """
        Chunk *text*, embed, and upsert into *collection*.

        Returns the number of points/chunks written.
        Every point carries ``doc_id`` in its payload for later filtered
        deletion without knowing individual vector IDs.
        """
        from qdrant_client.models import PointStruct  # type: ignore[import]

        await self.ensure_collection(collection)
        chunks = _chunk_text(text, self.CHUNK_SIZE, self.CHUNK_OVERLAP)
        if not chunks:
            return 0

        embeddings = list(self._embedder.embed(chunks))
        points = [
            PointStruct(
                id=str(_uuid.uuid4()),
                vector=emb.tolist(),
                payload={
                    "text": chunk,
                    "doc_id": doc_id,
                    "chunk_index": idx,
                    **metadata,
                },
            )
            for idx, (emb, chunk) in enumerate(zip(embeddings, chunks))
        ]
        await self._qdrant.upsert(collection_name=collection, points=points)
        log.info(
            "qdrant.upsert_complete",
            collection=collection,
            doc_id=doc_id,
            chunk_count=len(points),
        )
        return len(points)

    # ── Query ─────────────────────────────────────────────────────────────

    async def search(
        self,
        *,
        collection: str,
        query: str,
        top_k: int = 3,
        score_threshold: float = 0.6,
    ) -> list[dict]:
        """
        Embed *query* and return the top-k most relevant chunks.

        Returns a list of dicts with keys: ``text``, ``score``, ``doc_id``.
        """
        resp = await self._qdrant.get_collections()
        existing = {c.name for c in resp.collections}
        if collection not in existing:
            return []

        query_vec = list(self._embedder.embed([query]))[0].tolist()
        results = await self._qdrant.search(
            collection_name=collection,
            query_vector=query_vec,
            limit=top_k,
            score_threshold=score_threshold,
        )
        return [
            {
                "text": r.payload.get("text", ""),
                "score": r.score,
                "doc_id": r.payload.get("doc_id"),
            }
            for r in results
        ]

    # ── Deletion ──────────────────────────────────────────────────────────

    async def delete_document_chunks(
        self,
        *,
        collection: str,
        doc_id: str,
    ) -> int:
        """
        Delete all Qdrant points whose payload ``doc_id`` matches.

        Returns the number of points deleted (via count before/after).
        """
        from qdrant_client.models import FieldCondition, Filter, MatchValue  # type: ignore[import]

        resp = await self._qdrant.get_collections()
        existing = {c.name for c in resp.collections}
        if collection not in existing:
            return 0

        count_before = (
            await self._qdrant.count(collection_name=collection)
        ).count

        await self._qdrant.delete(
            collection_name=collection,
            points_selector=Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
            ),
        )

        count_after = (
            await self._qdrant.count(collection_name=collection)
        ).count
        deleted = max(0, count_before - count_after)
        log.info(
            "qdrant.chunks_deleted",
            collection=collection,
            doc_id=doc_id,
            deleted=deleted,
        )
        return deleted

    async def drop_collection(self, collection: str) -> None:
        """Delete the entire Qdrant collection (clear-all-documents path)."""
        resp = await self._qdrant.get_collections()
        existing = {c.name for c in resp.collections}
        if collection in existing:
            await self._qdrant.delete_collection(collection_name=collection)
            log.info("qdrant.collection_dropped", collection=collection)


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP-layer service (uses DB + ingestor + Celery)
# ═══════════════════════════════════════════════════════════════════════════════


class KnowledgeBaseService:
    """
    Orchestrates the HTTP request/response lifecycle for knowledge-base ops.

    •  upload_document  — save temp file, create DB record, enqueue Celery task
    •  list_documents   — return KB documents for the agent
    •  delete_document  — remove Qdrant chunks + DB record
    •  clear_all        — drop entire collection + all DB records
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = KbDocumentRepository(db)
        self._agent_repo = AgentRepository(db)

    # ── Helpers ───────────────────────────────────────────────────────────

    async def _get_agent_or_404(self, agent_id: UUID, org_id: UUID):
        agent = await self._agent_repo.get_by_id_and_org(agent_id, org_id)
        if not agent:
            raise NotFoundException(f"Agent {agent_id} not found")
        return agent

    # ── Upload ────────────────────────────────────────────────────────────

    async def upload_document(
        self,
        *,
        agent_id: UUID,
        org_id: UUID,
        file,               # UploadFile from FastAPI
        source_url: str | None = None,
    ) -> KbUploadResponse:
        """
        Persist the uploaded file to a temp dir, create a DB record, and
        dispatch the ``async_ingest_document`` Celery task.
        """
        agent = await self._get_agent_or_404(agent_id, org_id)

        # ── Determine file type ──────────────────────────────────────────
        fname: str = getattr(file, "filename", None) or (source_url or "document")
        ext = Path(fname).suffix.lower().lstrip(".") or "txt"
        # Normalise known extensions
        ext_map = {"jpeg": "txt", "jpg": "txt", "png": "txt"}  # unsupported → fallback
        file_type = ext_map.get(ext, ext)

        if file_type not in KB_FILE_TYPES:
            raise ValidationException(
                f"Unsupported file type '.{ext}'. "
                f"Allowed: {', '.join(sorted(KB_FILE_TYPES))}"
            )

        # ── Read content ─────────────────────────────────────────────────
        data: bytes = await file.read() if hasattr(file, "read") else b""
        file_size = len(data)

        # ── Save to temp dir ─────────────────────────────────────────────
        tmp_dir = _settings.LOCAL_STORAGE_PATH
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_filename = f"{_uuid.uuid4().hex}_{fname}"
        tmp_path = os.path.join(tmp_dir, tmp_filename)
        with open(tmp_path, "wb") as fh:
            fh.write(data)

        # ── Derive collection name ───────────────────────────────────────
        collection = _collection_name(org_id, agent_id)

        # ── Create DB record (pending) ───────────────────────────────────
        doc = await self._repo.create(
            agent_id=agent_id,
            org_id=org_id,
            file_name=fname,
            file_type=file_type,
            file_size_bytes=file_size,
            source_url=source_url,
        )
        await self._db.commit()

        # ── Enqueue Celery task ──────────────────────────────────────────
        from app.tasks.rag import async_ingest_document

        task = async_ingest_document.apply_async(
            kwargs={
                "doc_id": str(doc.id),
                "agent_id": str(agent_id),
                "org_id": str(org_id),
                "tmp_path": tmp_path,
                "file_name": fname,
                "file_type": file_type,
                "collection": collection,
                "source_url": source_url,
            },
            queue="default",
        )

        log.info(
            "kb.upload_queued",
            doc_id=str(doc.id),
            agent_id=str(agent_id),
            file_name=fname,
            task_id=task.id,
        )

        # Persist the qdrant_collection back to agent if not set
        if not agent.qdrant_collection:
            agent.qdrant_collection = collection
            await self._db.commit()

        return KbUploadResponse(
            doc_id=doc.id,
            file_name=fname,
            file_type=file_type,
            status="pending",
            task_id=task.id,
            qdrant_collection=collection,
        )

    # ── List ──────────────────────────────────────────────────────────────

    async def list_documents(
        self,
        *,
        agent_id: UUID,
        org_id: UUID,
        status: str | None = None,
    ) -> KbDocumentListResponse:
        await self._get_agent_or_404(agent_id, org_id)
        docs = await self._repo.list_by_agent(agent_id, status=status)
        return KbDocumentListResponse(
            documents=[KbDocumentResponse.model_validate(d) for d in docs],
            total=len(docs),
        )

    # ── Delete single document ────────────────────────────────────────────

    async def delete_document(
        self,
        *,
        agent_id: UUID,
        org_id: UUID,
        doc_id: UUID,
    ) -> KbDeleteDocResponse:
        await self._get_agent_or_404(agent_id, org_id)
        doc = await self._repo.get_by_id_and_agent(doc_id, agent_id)
        if not doc:
            raise NotFoundException(f"Document {doc_id} not found")

        collection = _collection_name(org_id, agent_id)
        ingestor = KnowledgeBaseIngestor()
        chunks_deleted = await ingestor.delete_document_chunks(
            collection=collection, doc_id=str(doc_id)
        )

        await self._repo.delete(doc_id)
        await self._db.commit()

        log.info(
            "kb.document_deleted",
            doc_id=str(doc_id),
            agent_id=str(agent_id),
            chunks_deleted=chunks_deleted,
        )
        return KbDeleteDocResponse(
            doc_id=doc_id,
            chunks_deleted=chunks_deleted,
            message=f"Document removed — {chunks_deleted} vector(s) deleted from Qdrant.",
        )

    # ── Clear all ─────────────────────────────────────────────────────────

    async def clear_all(self, *, agent_id: UUID, org_id: UUID) -> None:
        """Drop the entire Qdrant collection and remove all KB document records."""
        await self._get_agent_or_404(agent_id, org_id)
        collection = _collection_name(org_id, agent_id)
        ingestor = KnowledgeBaseIngestor()
        await ingestor.drop_collection(collection)

        # Bulk-delete all DB records for this agent
        docs = await self._repo.list_by_agent(agent_id)
        for doc in docs:
            await self._repo.delete(doc.id)
        await self._db.commit()
        log.info("kb.cleared", agent_id=str(agent_id), org_id=str(org_id))
