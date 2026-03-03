"""
Session manager for the Pipeline Service.

``SessionManager`` maintains an in-memory registry of active pipeline sessions
and exposes an async-safe API used by ``server.py``:

* ``create()``   — allocate a session, build the pipeline, return ``SessionInfo``
* ``get()``      — look up a session by ID
* ``end()``      — tear down the pipeline and remove from registry
* ``run_ws()``   — run the full WebSocket → Pipeline → WebSocket loop
* ``active_count()`` — number of live sessions (used by /health)

Thread safety
-------------
All mutations are protected by a single ``asyncio.Lock`` so that concurrent
``POST /sessions`` requests can never stomp each other.  Pipecat pipelines run
as isolated ``asyncio.Task`` objects; each task is tracked and cancelled on
``end()``.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Dict

import structlog
from fastapi import WebSocket
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask

from call_recorder import CallRecorder
from pipeline_builder import PipelineBuilder
from schemas import AgentConfig, SessionInfo, LANGUAGE_VOICE_MAP
from transports.websocket import make_ws_transport

log: structlog.BoundLogger = structlog.get_logger(__name__)


class _SessionState:
    """Internal holder for a running session."""

    __slots__ = (
        "info",
        "config",
        "task",
        "recorder",
        "created_at",
        "detected_language",
        "tts_processor",
    )

    def __init__(
        self,
        info: SessionInfo,
        config: AgentConfig,
        task: asyncio.Task | None = None,
        recorder: CallRecorder | None = None,
    ) -> None:
        self.info = info
        self.config = config
        self.task = task
        self.recorder = recorder
        self.created_at = datetime.now(tz=timezone.utc)
        self.detected_language: str | None = None
        self.tts_processor = None  # KokoroTTSProcessor, set after pipeline build


class SessionManager:
    """
    Manages the lifecycle of active pipeline sessions.

    Must be initialised once at application startup via ``startup()`` and
    cleanly shut down via ``shutdown()`` so that all in-flight sessions are
    gracefully terminated.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, _SessionState] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def startup(self) -> None:
        log.info("session_manager_started")

    async def shutdown(self) -> None:
        """Cancel all active pipeline tasks and wait for them to finish."""
        session_ids = list(self._sessions.keys())
        log.info("session_manager_shutdown_start", active=len(session_ids))
        await asyncio.gather(
            *(self.end(sid) for sid in session_ids), return_exceptions=True
        )
        log.info("session_manager_shutdown_complete")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create(
        self,
        agent_config: AgentConfig,
        call_id: str,
        metadata: dict,
        *,
        base_url: str = "ws://localhost:7000",
    ) -> SessionInfo:
        """
        Allocate a new session.

        Parameters
        ----------
        agent_config:
            Fully-populated agent configuration.
        call_id:
            Caller-supplied identifier for the call (used for recording path).
        metadata:
            Arbitrary JSON metadata stored in ``SessionInfo``.
        base_url:
            Base WebSocket URL prepended to the session's ``ws_url``.

        Returns
        -------
        SessionInfo
            Newly created session descriptor.
        """
        session_id = str(uuid.uuid4())
        ws_url = f"{base_url}/sessions/{session_id}/ws"
        info = SessionInfo(
            session_id=session_id,
            agent_id=str(agent_config.agent_id),
            call_id=call_id,
            status="idle",
            ws_url=ws_url,
            created_at=datetime.now(tz=timezone.utc).isoformat(),
            metadata=metadata,
        )
        state = _SessionState(info=info, config=agent_config)

        async with self._lock:
            self._sessions[session_id] = state

        log.info(
            "session_created",
            session_id=session_id,
            agent_id=info.agent_id,
            call_id=call_id,
        )
        return info

    def get(self, session_id: str) -> SessionInfo | None:
        """Return the ``SessionInfo`` for *session_id*, or ``None``."""
        state = self._sessions.get(session_id)
        return state.info if state else None

    async def end(self, session_id: str) -> bool:
        """
        Tear down the session with *session_id*.

        Cancels the running pipeline task (if any), flushes the call
        recorder, and removes the session from the registry.

        Returns
        -------
        bool
            ``True`` if the session existed and was removed, ``False`` if not
            found.
        """
        async with self._lock:
            state = self._sessions.pop(session_id, None)

        if state is None:
            return False

        # Cancel the pipeline task
        if state.task and not state.task.done():
            state.task.cancel()
            try:
                await state.task
            except (asyncio.CancelledError, Exception):
                pass

        # Flush call recording
        if state.recorder:
            try:
                await state.recorder.finish()
            except Exception as exc:
                log.warning(
                    "call_recorder_flush_failed",
                    session_id=session_id,
                    error=str(exc),
                )

        log.info("session_ended", session_id=session_id)
        return True

    def active_count(self) -> int:
        """Return the number of sessions currently in the registry."""
        return len(self._sessions)

    # ------------------------------------------------------------------
    # WebSocket runner
    # ------------------------------------------------------------------

    async def run_ws(self, session_id: str, ws: WebSocket) -> None:
        """
        Run the full pipeline lifecycle on an accepted WebSocket connection.

        This coroutine blocks until the session ends (client disconnect,
        ``end()`` called by HTTP, or pipeline error).

        Parameters
        ----------
        session_id:
            Must be a session returned by ``create()``.
        ws:
            Already-accepted FastAPI ``WebSocket``.
        """
        state = self._sessions.get(session_id)
        if state is None:
            log.warning("run_ws_session_not_found", session_id=session_id)
            await ws.close(code=4404)
            return

        state.info.status = "active"
        config = state.config

        # ── Build transport + pipeline ─────────────────────────────────
        transport = make_ws_transport(ws)
        builder = PipelineBuilder(config)

        async def _on_transcription(text: str, language: str | None) -> None:
            """Called by WhisperSTTProcessor after each successful transcription.

            Updates the session's detected language and switches the TTS voice
            so multilingual callers are responded to in their own language.
            """
            if not language or state.detected_language == language:
                return
            state.detected_language = language
            log.info(
                "language_detected",
                session_id=session_id,
                language=language,
            )
            if state.tts_processor is not None:
                voice = LANGUAGE_VOICE_MAP.get(language, config.tts_voice)
                state.tts_processor.set_voice(voice, language)
                log.info(
                    "tts_voice_updated",
                    session_id=session_id,
                    language=language,
                    voice=voice,
                )

        # ── Optional call recorder (created before pipeline so TTS can write to it)
        recorder: CallRecorder | None = None
        try:
            recorder = CallRecorder(
                session_id=session_id,
                call_id=state.info.call_id,
                organization_id=str(config.organization_id),
            )
            await recorder.start()
            state.recorder = recorder
        except Exception as exc:
            log.warning(
                "call_recorder_start_failed",
                session_id=session_id,
                error=str(exc),
            )

        pipeline = await builder.build(
            transport, on_transcription=_on_transcription, recorder=recorder
        )
        state.tts_processor = builder.tts_processor

        # ── Run pipeline ───────────────────────────────────────────────
        task = PipelineTask(
            pipeline,
            params=PipelineParams(allow_interruptions=config.allow_interruptions),
            enable_rtvi=False,   # raw PCM transport — no RTVI handshake required
        )
        runner = PipelineRunner()

        async def _run() -> None:
            await runner.run(task)

        pipeline_task = asyncio.create_task(_run(), name=f"pipeline_{session_id}")
        state.task = pipeline_task

        log.info("pipeline_task_started", session_id=session_id)
        try:
            await pipeline_task
        except asyncio.CancelledError:
            log.info("pipeline_task_cancelled", session_id=session_id)
        except Exception as exc:
            log.error(
                "pipeline_task_error",
                session_id=session_id,
                error=str(exc),
                exc_info=True,
            )
        finally:
            state.info.status = "ended"
            if recorder:
                try:
                    await recorder.finish()
                except Exception as exc:
                    log.warning(
                        "call_recorder_finish_failed",
                        session_id=session_id,
                        error=str(exc),
                    )
            log.info("pipeline_ws_loop_done", session_id=session_id)
