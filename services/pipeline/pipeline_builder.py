"""
Pipeline builder for the Pipeline Service.

``PipelineBuilder`` reads an ``AgentConfig`` and assembles a Pipecat
``Pipeline`` from the appropriate processor modules.  Processor slots are
enabled / disabled at build time so the runtime graph is statically determined
per session:

  transport.input()
      │
      ▼
  [RNNoiseProcessor]         if noise_removal_level != none  (Stage 1, < 1 ms)
      │
      ▼
  [DeepFilterNetProcessor]   if noise_removal_level == deepfilternet  (Stage 2, ~5 ms)
      │
      ▼
  [SileroVADProcessor]       if agent_type != speaker_only
      │
      ▼
  [WhisperSTTProcessor]      if agent_type != speaker_only
      │
      ▼
  [RAGRetrievalProcessor]    if qdrant_collection is set
      │
      ▼
  [OllamaLLMProcessor]       if agent_type != speaker_only
      │
      ▼
  [ToolExecutorProcessor]    if tools_json is set
      │
      ▼
  [InterruptionHandler]      always (no-op when allow_interruptions=False)
      │
      ▼
  [KokoroTTSProcessor]       always
      │
      ▼
  transport.output()

For a ``speaker_only`` agent the pipeline is just:
  input → noise? → VAD → TTS → output
  (no STT / LLM / RAG / tools)
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from pipecat.pipeline.pipeline import Pipeline
from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport

from processors.interrupt import InterruptionHandler
from processors.llm import OllamaLLMProcessor
from processors.noise import DeepFilterNetProcessor, RNNoiseProcessor
from processors.rag import RAGRetrievalProcessor
from processors.stt import WhisperSTTProcessor
from processors.tools import ToolExecutorProcessor
from processors.tts import KokoroTTSProcessor
from processors.vad import SileroVADProcessor
from schemas import AgentConfig, AgentType, NoiseRemovalLevel, resolve_system_prompt

log: structlog.BoundLogger = structlog.get_logger(__name__)


class PipelineBuilder:
    """
    Stateless factory — call ``build()`` once per session.

    Parameters
    ----------
    config:
        Fully-populated ``AgentConfig`` for the agent driving this session.
    """

    def __init__(self, config: AgentConfig) -> None:
        self._cfg = config
        self._tts_processor: KokoroTTSProcessor | None = None

    @property
    def tts_processor(self) -> KokoroTTSProcessor | None:
        """The ``KokoroTTSProcessor`` built by the last ``build()`` call.

        Available after ``build()`` returns; used by ``SessionManager`` to
        update the TTS voice when auto-detected language differs from the
        agent's configured default.
        """
        return self._tts_processor

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def build(
        self,
        transport: FastAPIWebsocketTransport,
        on_transcription: Callable[[str, str | None], Awaitable[None]] | None = None,
        recorder: Any | None = None,
    ) -> Pipeline:
        """
        Assemble and return a ready-to-run Pipecat ``Pipeline``.

        Parameters
        ----------
        transport:
            Configured transport (e.g. from ``transports.websocket``).
            Must expose ``.input()`` and ``.output()`` processor slots.
        on_transcription:
            Optional callback invoked by WhisperSTT with ``(text, language)``
            after each successful transcription.
        recorder:
            Optional ``CallRecorder`` instance passed to ``KokoroTTSProcessor``
            so every outbound audio chunk is mirrored to the recording buffer.

        Returns
        -------
        Pipeline
            The assembled pipeline.  Caller is responsible for starting it
            via ``PipelineTask``.
        """
        cfg = self._cfg
        processors: list = [transport.input()]

        # ── 1. Noise removal (two-stage, level-gated) ─────────────────────────
        if cfg.noise_removal_level != NoiseRemovalLevel.NONE:
            # Stage 1 — RNNoise is always included when noise removal is active
            processors.append(RNNoiseProcessor())
            log.debug("pipeline_slot_enabled", slot="noise_rnnoise")

            # Stage 2 — DeepFilterNet added only at the highest quality level
            if cfg.noise_removal_level == NoiseRemovalLevel.DEEPFILTERNET:
                processors.append(DeepFilterNetProcessor())
                log.debug("pipeline_slot_enabled", slot="noise_deepfilternet")

        # ── 2. VAD (skipped for speaker_only — agent just plays audio) ─
        if cfg.agent_type != AgentType.SPEAKER_ONLY:
            processors.append(
                SileroVADProcessor(
                    vad_threshold=cfg.vad_threshold,
                    min_speech_ms=cfg.min_speech_ms,
                    silence_ms=cfg.silence_ms,
                )
            )
            log.debug("pipeline_slot_enabled", slot="vad")

            # ── 3. STT ────────────────────────────────────────────────
            processors.append(
                WhisperSTTProcessor(
                    whisper_url=cfg.whisper_url,
                    language=cfg.language,
                    on_transcription=on_transcription,
                )
            )
            log.debug(
                "pipeline_slot_enabled",
                slot="stt",
                language=cfg.language or "auto",
            )

        # ── 4. RAG retrieval ──────────────────────────────────────────
        if cfg.qdrant_collection:
            processors.append(
                RAGRetrievalProcessor(
                    qdrant_url=cfg.qdrant_url,
                    collection=cfg.qdrant_collection,
                    top_k=cfg.rag_top_k,
                )
            )
            log.debug(
                "pipeline_slot_enabled",
                slot="rag",
                collection=cfg.qdrant_collection,
            )

        # ── 5. LLM ───────────────────────────────────────────────────
        if cfg.agent_type != AgentType.SPEAKER_ONLY:
            # Resolve system prompt template variables at session start time
            resolved_prompt = resolve_system_prompt(
                cfg.system_prompt or "", cfg.prompt_context
            )
            processors.append(
                OllamaLLMProcessor(
                    model=cfg.llm_model,
                    system_prompt=resolved_prompt,
                    tools=cfg.tools_json,
                    temperature=cfg.temperature,
                    max_tokens=cfg.max_tokens,
                    max_turns=cfg.max_turns,
                )
            )
            log.debug(
                "pipeline_slot_enabled",
                slot="llm",
                model=cfg.llm_model,
                max_turns=cfg.max_turns,
            )

        # ── 6. Tool executor ─────────────────────────────────────────
        if cfg.tools_json:
            processors.append(
                ToolExecutorProcessor(
                    tools_spec=cfg.tools_json,
                    org_secrets=cfg.org_secrets,
                )
            )
            log.debug(
                "pipeline_slot_enabled",
                slot="tools",
                tool_count=len(cfg.tools_json),
            )

        # ── 7. Interruption handler ───────────────────────────────────
        processors.append(
            InterruptionHandler(
                enabled=cfg.allow_interruptions,
                barge_in_threshold=cfg.barge_in_threshold,
            )
        )
        log.debug(
            "pipeline_slot_enabled",
            slot="interruption",
            allow=cfg.allow_interruptions,
            barge_in_threshold=cfg.barge_in_threshold,
        )

        # ── 8. TTS ───────────────────────────────────────────────────
        tts = KokoroTTSProcessor(
            kokoro_url=cfg.kokoro_url,
            voice=cfg.tts_voice,
            speed=cfg.tts_speed,
            lang=cfg.tts_lang,
            recorder=recorder,
        )
        self._tts_processor = tts
        processors.append(tts)
        log.debug("pipeline_slot_enabled", slot="tts", voice=cfg.tts_voice)

        # ── 9. Transport output ───────────────────────────────────────
        processors.append(transport.output())

        pipeline = Pipeline(processors)
        log.info(
            "pipeline_built",
            agent_id=str(cfg.agent_id),
            agent_type=cfg.agent_type,
            slots=len(processors),
        )
        return pipeline

    # ------------------------------------------------------------------
    # WebRTC variant
    # ------------------------------------------------------------------

    async def build_for_webrtc(
        self,
        transport: Any,
        on_transcription: Callable[[str, str | None], Awaitable[None]] | None = None,
        recorder: Any | None = None,
    ) -> Pipeline:
        """
        Assemble a pipeline backed by a ``WebRTCTransport``.

        ``WebRTCTransport`` exposes ``.input()`` (→ ``WebRTCInputProcessor``)
        and ``.output()`` (→ *self*) so it satisfies the duck-type contract
        expected by the inner ``build()`` call.

        Parameters
        ----------
        transport:
            A ``WebRTCTransport`` instance (or any duck-type with compatible
            ``.input()`` / ``.output()`` methods).
        on_transcription, recorder:
            Same semantics as in :meth:`build`.

        Returns
        -------
        Pipeline
        """
        # Delegate to build() — WebRTCTransport.input() / .output() satisfy
        # the same duck-type contract as FastAPIWebsocketTransport.
        return await self.build(
            transport,          # type: ignore[arg-type]
            on_transcription=on_transcription,
            recorder=recorder,
        )

    # ------------------------------------------------------------------
    # Twilio PSTN variant
    # ------------------------------------------------------------------

    async def build_for_twilio(
        self,
        transport: Any,
        on_transcription: Callable[[str, str | None], Awaitable[None]] | None = None,
        recorder: Any | None = None,
    ) -> Pipeline:
        """
        Assemble a pipeline backed by a ``TwilioTransport``.

        Inserts a ``DTMFRouter`` immediately after the input processor when
        the agent config has a ``dtmf_routing_map`` (IVR mode).  For plain
        conversational PSTN agents the build is identical to ``build()``.

        Parameters
        ----------
        transport:
            A ``TwilioTransport`` instance.
        on_transcription, recorder:
            Same semantics as in :meth:`build`.
        """
        from processors.dtmf import DTMFRouter
        from transports.twilio import DTMFFrame, TransferCallFrame  # noqa: F401

        cfg = self._cfg

        # Build the base pipeline (noise → VAD → STT → RAG → LLM → tools → TTS → output)
        pipeline = await self.build(
            transport,          # type: ignore[arg-type]
            on_transcription=on_transcription,
            recorder=recorder,
        )

        # If a DTMF routing map is configured, splice the DTMFRouter into the
        # pipeline after the input processor (index 0 = transport.input()).
        if cfg.dtmf_routing_map:
            # Convert list-of-2 entries to proper (action, dest) tuples
            routing: dict[str, tuple[str, str | None]] = {}
            for digit, entry in cfg.dtmf_routing_map.items():
                if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    routing[digit] = (str(entry[0]), entry[1] if entry[1] else None)
                elif isinstance(entry, (list, tuple)) and len(entry) == 1:
                    routing[digit] = (str(entry[0]), None)

            router = DTMFRouter(
                routing_map=routing,
                operator_number=cfg.operator_number,
            )
            # Splice after input (index 0); Pipeline stores processors as a list.
            # We rebuild the processor list with DTMFRouter in position 1.
            procs = list(pipeline.processors)  # type: ignore[attr-defined]
            procs.insert(1, router)
            pipeline = Pipeline(procs)
            log.info(
                "dtmf_router_spliced",
                agent_id=str(cfg.agent_id),
                routes=list(routing.keys()),
            )

        return pipeline
