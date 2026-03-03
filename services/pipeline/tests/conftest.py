"""
Shared pytest fixtures and configuration for the pipeline service unit tests.

pipecat-ai is only available inside Docker (it is not installed in the local
dev virtualenv).  We inject lightweight stubs for every pipecat symbol that
the source files and tests import so that pytest can collect and run the tests
without the real package installed.
"""
from __future__ import annotations

import enum
import sys
import types
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── asyncio mode ─────────────────────────────────────────────────────────────
def pytest_configure(config: Any) -> None:
    config.addinivalue_line(
        "markers", "asyncio: mark test as async (handled by pytest-asyncio)"
    )


# ── Pipecat stubs ─────────────────────────────────────────────────────────────
# These are added to sys.modules before any test module is imported so that
# "from pipecat.xxx import YYY" resolves to our lightweight stubs.

def _stub_pipecat() -> None:
    if "pipecat" in sys.modules:
        return  # already installed (e.g. running inside Docker)

    # ── base Frame ────────────────────────────────────────────────────────────
    @dataclass
    class Frame:
        pass

    # ── Audio frames ──────────────────────────────────────────────────────────
    @dataclass
    class AudioRawFrame(Frame):
        audio: bytes = b""
        sample_rate: int = 16_000
        num_channels: int = 1

    # ── Lifecycle frames ──────────────────────────────────────────────────────
    @dataclass
    class StartFrame(Frame):
        allow_interruptions: bool = False

    @dataclass
    class EndFrame(Frame):
        pass

    @dataclass
    class StartInterruptionFrame(Frame):
        pass

    # ── STT / TTS frames ──────────────────────────────────────────────────────
    @dataclass
    class TranscriptionFrame(Frame):
        text: str = ""
        user_id: str = ""
        timestamp: str = ""

    @dataclass
    class UserStartedSpeakingFrame(Frame):
        pass

    # ── LLM frames ────────────────────────────────────────────────────────────
    @dataclass
    class TextFrame(Frame):
        text: str = ""

    @dataclass
    class LLMMessagesFrame(Frame):
        messages: list = field(default_factory=list)

    @dataclass
    class LLMFullResponseStartFrame(Frame):
        pass

    @dataclass
    class LLMFullResponseEndFrame(Frame):
        pass

    # ── Tool / function-call frames ───────────────────────────────────────────
    @dataclass
    class FunctionCallInProgressFrame(Frame):
        function_name: str = ""
        arguments: Any = None
        tool_call_id: str = ""

    @dataclass
    class FunctionCallResultFrame(Frame):
        function_name: str = ""
        arguments: Any = None
        result: Any = None
        tool_call_id: str = ""

    # ── FrameDirection ────────────────────────────────────────────────────────
    class FrameDirection(enum.Enum):
        DOWNSTREAM = "downstream"
        UPSTREAM = "upstream"

    # ── FrameProcessor (minimal base class) ──────────────────────────────────
    class FrameProcessor:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def push_frame(
            self,
            frame: Frame,
            direction: FrameDirection = FrameDirection.DOWNSTREAM,
        ) -> None:
            pass

        async def process_frame(
            self,
            frame: Frame,
            direction: FrameDirection = FrameDirection.DOWNSTREAM,
        ) -> None:
            pass

    # ── Build module tree ─────────────────────────────────────────────────────

    # pipecat (root)
    pipecat = types.ModuleType("pipecat")

    # pipecat.frames
    pipecat_frames = types.ModuleType("pipecat.frames")
    pipecat_frames_frames = types.ModuleType("pipecat.frames.frames")
    for _cls in [
        Frame, AudioRawFrame, StartFrame, EndFrame, StartInterruptionFrame,
        TranscriptionFrame, UserStartedSpeakingFrame, TextFrame,
        LLMMessagesFrame, LLMFullResponseStartFrame, LLMFullResponseEndFrame,
        FunctionCallInProgressFrame, FunctionCallResultFrame,
    ]:
        setattr(pipecat_frames_frames, _cls.__name__, _cls)

    # pipecat.processors
    pipecat_processors = types.ModuleType("pipecat.processors")
    pipecat_processors_fp = types.ModuleType("pipecat.processors.frame_processor")
    pipecat_processors_fp.FrameDirection = FrameDirection
    pipecat_processors_fp.FrameProcessor = FrameProcessor

    # pipecat.audio
    pipecat_audio = types.ModuleType("pipecat.audio")
    pipecat_audio_vad = types.ModuleType("pipecat.audio.vad")
    pipecat_audio_vad_analyzer = types.ModuleType("pipecat.audio.vad.vad_analyzer")

    class VADState(enum.Enum):
        QUIET = "quiet"
        STARTING = "starting"
        SPEAKING = "speaking"
        STOPPING = "stopping"

    pipecat_audio_vad_analyzer.VADState = VADState
    pipecat_audio_vad_silero = types.ModuleType("pipecat.audio.vad.silero")
    pipecat_audio_vad_silero.SileroVADAnalyzer = MagicMock

    # pipecat.pipeline
    pipecat_pipeline = types.ModuleType("pipecat.pipeline")
    for _name in ("pipeline", "runner", "task"):
        _m = types.ModuleType(f"pipecat.pipeline.{_name}")
        for _attr in ("Pipeline", "PipelineRunner", "PipelineParams", "PipelineTask"):
            setattr(_m, _attr, MagicMock)
        sys.modules[f"pipecat.pipeline.{_name}"] = _m

    # pipecat.transports
    pipecat_transports = types.ModuleType("pipecat.transports")
    pipecat_transports_ws = types.ModuleType("pipecat.transports.websocket")
    pipecat_transports_ws_fastapi = types.ModuleType("pipecat.transports.websocket.fastapi")
    pipecat_transports_ws_fastapi.FastAPIWebsocketTransport = MagicMock
    pipecat_transports_ws_fastapi.FastAPIWebsocketParams = MagicMock

    # pipecat.serializers
    pipecat_serializers = types.ModuleType("pipecat.serializers")
    pipecat_serializers_base = types.ModuleType("pipecat.serializers.base_serializer")
    pipecat_serializers_base.FrameSerializer = MagicMock

    # Register everything in sys.modules
    sys.modules.update({
        "pipecat": pipecat,
        "pipecat.frames": pipecat_frames,
        "pipecat.frames.frames": pipecat_frames_frames,
        "pipecat.processors": pipecat_processors,
        "pipecat.processors.frame_processor": pipecat_processors_fp,
        "pipecat.audio": pipecat_audio,
        "pipecat.audio.vad": pipecat_audio_vad,
        "pipecat.audio.vad.vad_analyzer": pipecat_audio_vad_analyzer,
        "pipecat.audio.vad.silero": pipecat_audio_vad_silero,
        "pipecat.pipeline": pipecat_pipeline,
        "pipecat.transports": pipecat_transports,
        "pipecat.transports.websocket": pipecat_transports_ws,
        "pipecat.transports.websocket.fastapi": pipecat_transports_ws_fastapi,
        "pipecat.serializers": pipecat_serializers,
        "pipecat.serializers.base_serializer": pipecat_serializers_base,
    })


_stub_pipecat()
