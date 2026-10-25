"""
RAGRetrievalProcessor — TranscriptionFrame → augmented LLMMessagesFrame.

Queries the Qdrant vector database with the user's transcribed utterance to
retrieve semantically similar knowledge-base chunks.  The retrieved context
is injected into the LLM messages as a ``system`` message before the user
turn — the LLM will ground its response in the retrieved content.

Embedding model
---------------
Uses ``fastembed`` (BAAI/bge-small-en-v1.5, 384d) — a CPU-only ONNX embedding
library that requires no GPU and no API key.  The model is cached in the
container after the first use.  This MUST match the model used at ingestion
time in ``app/modules/agents/kb_service.py`` — a mismatch puts query and
document vectors in different embedding spaces and silently degrades
retrieval quality (dimension stays 384 either way, so no schema break, but
results get worse).

Enabled only when ``agent_config.qdrant_collection`` is set.

Frame flow
----------
TranscriptionFrame(text="user utterance")
    → Qdrant query (BAAI/bge-small-en-v1.5 embedding)
    → LLMMessagesFrame(messages=[
        {"role": "system", "content": "<RAG context>"},
        {"role": "user",   "content": "user utterance"},
      ])
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from pipecat.frames.frames import (
    EndFrame,
    Frame,
    LLMMessagesFrame,
    StartFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)

_RAG_CONTEXT_TEMPLATE = """\
The following information may be relevant to the user's question.
Use it to answer accurately, but only if it is directly applicable.

{context}
"""


class RAGRetrievalProcessor(FrameProcessor):
    """
    Qdrant-backed RAG retrieval for knowledge-grounded responses.

    Parameters
    ----------
    collection : str
        Qdrant collection name (per-organisation, created during KB ingestion).
    top_k : int
        Number of nearest-neighbour chunks to retrieve (default 3).
    qdrant_url : str
        Qdrant REST API base URL (default ``http://qdrant:6333``).
    score_threshold : float
        Minimum cosine similarity to include a chunk (default 0.65).
    """

    def __init__(
        self,
        collection: str,
        top_k: int        = 3,
        qdrant_url: str   = "http://qdrant:6333",
        score_threshold: float = 0.65,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._collection      = collection
        self._top_k           = top_k
        self._score_threshold = score_threshold
        self._qdrant_url      = qdrant_url
        self._client: Any     = None      # qdrant_client.AsyncQdrantClient
        self._embedder: Any   = None      # fastembed.TextEmbedding
        self._log = logger.bind(
            processor="RAGRetrieval", collection=collection
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            await self._init_clients()
            await self.push_frame(frame, direction)

        elif isinstance(frame, TranscriptionFrame):
            messages = await self._retrieve_and_build(frame.text)
            await self.push_frame(LLMMessagesFrame(messages=messages))

        elif isinstance(frame, EndFrame):
            await self._close()
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _init_clients(self) -> None:
        """Initialise Qdrant async client and FastEmbed model."""
        try:
            from fastembed import TextEmbedding           # type: ignore[import]
            from qdrant_client import AsyncQdrantClient  # type: ignore[import]

            loop = asyncio.get_event_loop()

            # Load embedding model in thread pool (CPU-bound ONNX init)
            self._embedder = await loop.run_in_executor(
                None,
                # Must match the model kb_service.py uses at ingestion time
                # (app/modules/agents/kb_service.py) — otherwise query and
                # document vectors live in different embedding spaces and
                # similarity search silently degrades. Both are 384-dim, so
                # this is a drop-in correction, not a re-index requirement.
                lambda: TextEmbedding("BAAI/bge-small-en-v1.5"),
            )
            import os
            self._client = AsyncQdrantClient(
                url=self._qdrant_url,
                api_key=os.getenv("QDRANT_API_KEY") or None,
            )
            self._log.info("rag.clients_ready")

        except ImportError as exc:
            self._log.warning("rag.missing_dep", error=str(exc))
        except Exception as exc:
            self._log.error("rag.init_failed", error=str(exc))

    async def _close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None

    async def _retrieve_and_build(
        self, user_text: str
    ) -> list[dict[str, str]]:
        """
        Embed user query, search Qdrant, return LLM messages list.

        Falls back to a plain user-only message if retrieval fails.
        """
        user_msg: dict[str, str] = {"role": "user", "content": user_text}

        if not self._client or not self._embedder:
            return [user_msg]

        try:
            loop = asyncio.get_event_loop()

            # Embed query in thread pool
            embedding_gen = await loop.run_in_executor(
                None,
                lambda: list(self._embedder.query_embed(user_text)),
            )
            query_vector: list[float] = embedding_gen[0].tolist()

            # Query Qdrant
            results = await self._client.search(
                collection_name=self._collection,
                query_vector=query_vector,
                limit=self._top_k,
                score_threshold=self._score_threshold,
                with_payload=True,
            )

            if not results:
                self._log.debug("rag.no_results", query=user_text[:60])
                return [user_msg]

            snippets = [
                r.payload.get("text", "")
                for r in results
                if r.payload and r.payload.get("text")
            ]
            context = "\n\n---\n\n".join(snippets)
            self._log.info(
                "rag.retrieved",
                chunks=len(snippets),
                scores=[round(r.score, 3) for r in results],
            )

            rag_system: dict[str, str] = {
                "role":    "system",
                "content": _RAG_CONTEXT_TEMPLATE.format(context=context),
            }
            return [rag_system, user_msg]

        except Exception as exc:
            self._log.exception("rag.retrieval_failed", error=str(exc))
            return [user_msg]
