"""
services/rag/ingestion.py
─────────────────────────
Standalone knowledge-base ingestion engine.

This module implements the plan-spec ``KnowledgeBaseIngestor`` exactly as
described in section 10.1 of the technical implementation plan and can be
imported independently by:

• The SaaS platform's HTTP service layer (app/modules/agents/kb_service.py)
• The Celery worker task (app/tasks/rag.py)
• The voice-pipeline RAG retrieval processor (services/pipeline/processors/rag.py)

Architecture
────────────
FastEmbed runs on CPU using BAAI/bge-small-en-v1.5 (384-dim, ~130 MB).
Each agent stores its vectors in its own Qdrant collection:

    collection = f"{org_id}_{agent_id}"          # no dashes

This guarantees complete tenant isolation — one org cannot query another's
knowledge base even if they happen to use the same Qdrant instance.
"""

from __future__ import annotations

import io
import uuid
import csv
from typing import Any

import structlog
from fastembed import TextEmbedding
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

log = structlog.get_logger(__name__)

_QDRANT_URL_DEFAULT = "http://qdrant:6333"

try:
    from app.config import get_settings as _get_settings

    _cfg = _get_settings()
    _QDRANT_URL = _cfg.QDRANT_URL
    _QDRANT_API_KEY = _cfg.QDRANT_API_KEY or None
    _EMBED_MODEL = _cfg.RAG_EMBED_MODEL
    _CHUNK_SIZE = _cfg.RAG_CHUNK_SIZE
    _CHUNK_OVERLAP = _cfg.RAG_CHUNK_OVERLAP
    _SCORE_THRESHOLD = float(_cfg.RAG_SCORE_THRESHOLD)
except Exception:  # running standalone, config not available
    _QDRANT_URL = _QDRANT_URL_DEFAULT
    _QDRANT_API_KEY = None
    _EMBED_MODEL = "BAAI/bge-small-en-v1.5"
    _CHUNK_SIZE = 512
    _CHUNK_OVERLAP = 50
    _SCORE_THRESHOLD = 0.6


def _chunk_text(text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Split *text* into overlapping character-level chunks."""
    char_budget = chunk_size * 4
    step = max(1, char_budget - overlap * 4)
    chunks: list[str] = []
    for start in range(0, len(text), step):
        chunk = text[start : start + char_budget].strip()
        if chunk:
            chunks.append(chunk)
    return chunks


class KnowledgeBaseIngestor:
    """
    CPU-only, FastEmbed-based ingestion engine.

    Usage (async)::

        ingestor = KnowledgeBaseIngestor()
        collection = f"{org_id}_{agent_id}"

        # Ingest a document
        n = await ingestor.ingest_document(
            collection=collection,
            text="full extracted plain text …",
            metadata={"doc_id": "…", "file_name": "policy.pdf"},
        )
        print(f"Ingested {n} chunks")

        # Delete a document
        await ingestor.delete_document_chunks(collection=collection, doc_id="…")

        # Search
        results = await ingestor.search(collection=collection, query="refund policy")
    """

    EMBED_MODEL: str = _EMBED_MODEL  # 384-dim, CPU-fast, ~130 MB
    CHUNK_SIZE: int = _CHUNK_SIZE    # tokens per chunk (approx)
    CHUNK_OVERLAP: int = _CHUNK_OVERLAP
    VECTOR_SIZE: int = 384

    def __init__(self, qdrant_url: str = _QDRANT_URL, qdrant_api_key: str | None = _QDRANT_API_KEY) -> None:
        self._embedder = TextEmbedding(self.EMBED_MODEL)
        self._qdrant = AsyncQdrantClient(url=qdrant_url, api_key=qdrant_api_key)

    # ── Collection ────────────────────────────────────────────────────────

    async def ensure_collection(self, collection: str) -> None:
        """Create *collection* in Qdrant if it does not already exist."""
        existing = {c.name for c in await self._qdrant.get_collections()}
        if collection not in existing:
            await self._qdrant.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(size=self.VECTOR_SIZE, distance=Distance.COSINE),
            )
            log.info("qdrant.collection_created", collection=collection)

    async def drop_collection(self, collection: str) -> None:
        """Delete *collection* entirely (clear-all-documents path)."""
        existing = {c.name for c in await self._qdrant.get_collections()}
        if collection in existing:
            await self._qdrant.delete_collection(collection_name=collection)
            log.info("qdrant.collection_dropped", collection=collection)

    # ── Write ─────────────────────────────────────────────────────────────

    async def ingest_document(
        self,
        collection: str,
        text: str,
        metadata: dict[str, Any],
    ) -> int:
        """
        Chunk *text*, embed, and upsert into *collection*.

        ``metadata`` must contain ``doc_id`` so chunks can later be
        filtered and deleted by document.  Any extra keys are stored in
        the Qdrant payload alongside the chunk text.

        Returns the number of points written.
        """
        await self.ensure_collection(collection)
        chunks = _chunk_text(text, self.CHUNK_SIZE, self.CHUNK_OVERLAP)
        if not chunks:
            return 0

        embeddings = list(self._embedder.embed(chunks))
        doc_id = metadata.get("doc_id") or str(uuid.uuid4())
        points = [
            PointStruct(
                id=str(uuid.uuid4()),
                vector=emb.tolist(),
                payload={
                    "text": chunk,
                    "doc_id": doc_id,
                    "chunk_index": idx,
                    **{k: v for k, v in metadata.items() if k != "doc_id"},
                },
            )
            for idx, (emb, chunk) in enumerate(zip(embeddings, chunks))
        ]
        await self._qdrant.upsert(collection_name=collection, points=points)
        log.info(
            "qdrant.upsert_complete",
            collection=collection,
            doc_id=doc_id,
            chunks=len(points),
        )
        return len(points)

    # ── Delete ────────────────────────────────────────────────────────────

    async def delete_document_chunks(self, collection: str, doc_id: str) -> int:
        """
        Delete all points whose payload ``doc_id`` equals *doc_id*.

        Returns the approximate number of vectors removed.
        """
        existing = {c.name for c in await self._qdrant.get_collections()}
        if collection not in existing:
            return 0

        before = (await self._qdrant.count(collection_name=collection)).count
        await self._qdrant.delete(
            collection_name=collection,
            points_selector=Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
            ),
        )
        after = (await self._qdrant.count(collection_name=collection)).count
        deleted = max(0, before - after)
        log.info("qdrant.chunks_deleted", collection=collection, doc_id=doc_id, n=deleted)
        return deleted

    # ── Query ─────────────────────────────────────────────────────────────

    async def search(
        self,
        collection: str,
        query: str,
        limit: int = 3,
        score_threshold: float = _SCORE_THRESHOLD,
    ) -> list[dict]:
        """
        Semantic search: embed *query* and return top-*limit* chunks.

        Returns list of dicts: ``{"text": …, "score": …, "doc_id": …}``.
        """
        existing = {c.name for c in await self._qdrant.get_collections()}
        if collection not in existing:
            return []

        query_vec = list(self._embedder.embed([query]))[0].tolist()
        results = await self._qdrant.search(
            collection_name=collection,
            query_vector=query_vec,
            limit=limit,
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
