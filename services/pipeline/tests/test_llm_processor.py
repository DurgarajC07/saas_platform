"""
Unit tests for OllamaLLMProcessor — Day 6 deliverables.

All HTTP interactions are mocked: no real Ollama server is required.
The aiohttp streaming response is simulated with an async line iterator.

Deliverables verified
---------------------
  ✓  TranscriptionFrame appended to history, LLM invoked
  ✓  Sentence-boundary batching: TextFrame pushed on . / ! / ?
  ✓  Trailing non-sentence text flushed at end of stream
  ✓  Conversation history maintained across multiple turns
  ✓  max_turns cap enforced; oldest turns dropped
  ✓  LLMMessagesFrame (tool result re-entry) extends history
  ✓  Tool call chunk emits FunctionCallInProgressFrame
  ✓  LLMFullResponseStartFrame + LLMFullResponseEndFrame always emitted
  ✓  HTTP error produces error TextFrame, no crash
  ✓  Connection error produces fallback TextFrame, no crash
  ✓  update_system_prompt() changes the prompt mid-session
  ✓  resolve_system_prompt() safe-substitution (unknown keys kept verbatim)
  ✓  PromptContext default today matches today's date
  ✓  AgentConfig max_turns field defaults to 20
"""

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipecat.frames.frames import (
    FunctionCallInProgressFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMMessagesFrame,
    StartInterruptionFrame,
    TextFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from processors.llm import OllamaLLMProcessor
from schemas import (
    AgentConfig,
    AgentType,
    PromptContext,
    resolve_system_prompt,
)


# ── Mock HTTP helpers ──────────────────────────────────────────────────────────

def _token_line(content: str, done: bool = False) -> bytes:
    """Encode a single Ollama streaming chunk as a NDJSON bytes line."""
    return json.dumps({
        "message": {"role": "assistant", "content": content},
        "done": done,
    }).encode()


def _done_line() -> bytes:
    return json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}).encode()


def _tool_line(name: str, arguments: dict, done: bool = False) -> bytes:
    return json.dumps({
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "tc1", "function": {"name": name, "arguments": arguments}}],
        },
        "done": done,
    }).encode()


def _http_error_response(status: int = 500) -> MagicMock:
    """Async context manager simulating a non-200 HTTP response."""
    resp = MagicMock()
    resp.status = status
    resp.text = AsyncMock(return_value="Internal Server Error")

    async def _aiter():
        return
        yield  # make it an async generator

    resp.content = _aiter()

    @asynccontextmanager
    async def _cm():
        yield resp

    return _cm()


class _StreamingResponse:
    """Simulates an aiohttp streaming response with NDJSON lines."""

    def __init__(self, lines: list[bytes], status: int = 200) -> None:
        self.status = status
        self._lines = lines

    @property
    def content(self):
        lines = self._lines

        async def _aiter():
            for line in lines:
                yield line

        return _aiter()

    async def text(self) -> str:
        return b"\n".join(self._lines).decode()


@asynccontextmanager
async def _mock_post(lines: list[bytes], status: int = 200):
    yield _StreamingResponse(lines, status)


def _patch_post(lines: list[bytes], status: int = 200):
    """Return a callable usable as side_effect for mocking session.post."""
    @asynccontextmanager
    async def _cm(*args: Any, **kwargs: Any):
        yield _StreamingResponse(lines, status)
    return _cm


async def _run(
    proc: OllamaLLMProcessor,
    frame: Any,
    post_lines: list[bytes] | None = None,
) -> list[Any]:
    """
    Feed *frame* into *proc*, mock the HTTP layer, collect pushed frames.
    """
    captured: list[Any] = []

    async def capture(f: Any, d: FrameDirection = FrameDirection.DOWNSTREAM) -> None:
        captured.append(f)

    proc.push_frame = capture  # type: ignore[method-assign]

    if post_lines is not None:
        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.post = _patch_post(post_lines)
        proc._session = mock_session

    await proc.process_frame(frame, FrameDirection.DOWNSTREAM)
    return captured


# ── Helpers ───────────────────────────────────────────────────────────────────

def _transcription(text: str = "Hello") -> TranscriptionFrame:
    return TranscriptionFrame(text=text, user_id="caller", timestamp=0)


def _make_proc(**kwargs: Any) -> OllamaLLMProcessor:
    return OllamaLLMProcessor(
        model="qwen2.5:3b",
        system_prompt="You are a helpful assistant.",
        **kwargs,
    )


# ── TestSentenceBatching ───────────────────────────────────────────────────────

class TestSentenceBatching:
    """Tokens are buffered and pushed as single TextFrames on sentence boundaries."""

    async def test_sentence_with_period_batched(self) -> None:
        lines = [
            _token_line("Hello"),
            _token_line(" world"),
            _token_line("."),
            _done_line(),
        ]
        proc = _make_proc()
        frames = await _run(proc, _transcription(), lines)

        text_frames = [f for f in frames if isinstance(f, TextFrame)]
        assert len(text_frames) == 1
        assert text_frames[0].text == "Hello world."

    async def test_sentence_with_exclamation_batched(self) -> None:
        lines = [_token_line("Great!"), _done_line()]
        proc = _make_proc()
        frames = await _run(proc, _transcription(), lines)

        text = "".join(f.text for f in frames if isinstance(f, TextFrame))
        assert "Great!" in text

    async def test_trailing_text_flushed_at_end(self) -> None:
        """Non-sentence-ending text must still be pushed after stream ends."""
        lines = [
            _token_line("Processing"),
            _token_line(" your request"),
            _done_line(),
        ]
        proc = _make_proc()
        frames = await _run(proc, _transcription(), lines)

        text_frames = [f for f in frames if isinstance(f, TextFrame)]
        assert len(text_frames) == 1
        combined = text_frames[0].text
        assert "Processing" in combined
        assert "your request" in combined

    async def test_multiple_sentences_multiple_frames(self) -> None:
        """Two sentences in one stream should produce two TextFrames."""
        lines = [
            _token_line("Hello."),
            _token_line(" How are you?"),
            _done_line(),
        ]
        proc = _make_proc()
        frames = await _run(proc, _transcription(), lines)

        text_frames = [f for f in frames if isinstance(f, TextFrame)]
        assert len(text_frames) == 2

    async def test_lifecycle_frames_always_emitted(self) -> None:
        """LLMFullResponseStartFrame and EndFrame must bracket every response."""
        lines = [_token_line("Hi."), _done_line()]
        proc = _make_proc()
        frames = await _run(proc, _transcription(), lines)

        types = [type(f) for f in frames]
        assert LLMFullResponseStartFrame in types
        assert LLMFullResponseEndFrame in types
        start_idx = types.index(LLMFullResponseStartFrame)
        end_idx   = len(types) - 1 - types[::-1].index(LLMFullResponseEndFrame)
        assert start_idx < end_idx, "StartFrame must precede EndFrame"


# ── TestConversationHistory ────────────────────────────────────────────────────

class TestConversationHistory:
    """History is maintained and grows with each turn."""

    async def test_user_turn_appended_on_transcription(self) -> None:
        lines = [_done_line()]
        proc = _make_proc()
        await _run(proc, _transcription("What is AI?"), lines)

        assert len(proc._history) >= 1
        user_msgs = [m for m in proc._history if m["role"] == "user"]
        assert user_msgs[0]["content"] == "What is AI?"

    async def test_assistant_turn_appended_after_response(self) -> None:
        lines = [_token_line("AI is intelligence"), _token_line("."), _done_line()]
        proc = _make_proc()
        await _run(proc, _transcription("What is AI?"), lines)

        assistant_msgs = [m for m in proc._history if m["role"] == "assistant"]
        assert len(assistant_msgs) == 1
        assert "AI is intelligence" in assistant_msgs[0]["content"]

    async def test_history_grows_across_turns(self) -> None:
        proc = _make_proc()
        for i in range(3):
            lines = [_token_line(f"Response {i}."), _done_line()]
            await _run(proc, _transcription(f"Turn {i}"), lines)

        assert len(proc._history) == 6  # 3 user + 3 assistant

    async def test_llm_messages_frame_extends_history(self) -> None:
        """Tool result re-entry via LLMMessagesFrame should extend history."""
        proc = _make_proc()
        tool_msg = {"role": "tool", "content": '{"result": "ok"}', "name": "do_thing"}
        lines = [_token_line("Done."), _done_line()]
        frames = await _run(
            proc,
            LLMMessagesFrame(messages=[tool_msg]),
            lines,
        )

        tool_msgs = [m for m in proc._history if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["name"] == "do_thing"

    async def test_clear_history_empties_list(self) -> None:
        proc = _make_proc()
        proc._history.append({"role": "user", "content": "hi"})
        proc.clear_history()
        assert proc._history == []


# ── TestMaxTurns ───────────────────────────────────────────────────────────────

class TestMaxTurns:
    """Conversation history is capped at max_turns exchange pairs."""

    async def test_history_capped_at_max_turns(self) -> None:
        max_turns = 3
        proc = _make_proc(max_turns=max_turns)

        # Send 5 turns — only the last 3 pairs (6 messages) should survive
        for i in range(5):
            lines = [_token_line(f"Answer {i}."), _done_line()]
            await _run(proc, _transcription(f"Question {i}"), lines)

        assert len(proc._history) == max_turns * 2

    async def test_oldest_turns_dropped_first(self) -> None:
        proc = _make_proc(max_turns=2)

        for i in range(4):
            lines = [_token_line(f"Ans{i}."), _done_line()]
            await _run(proc, _transcription(f"Q{i}"), lines)

        # Only the last 2 user questions survive
        user_msgs = [m["content"] for m in proc._history if m["role"] == "user"]
        assert "Q0" not in user_msgs
        assert "Q1" not in user_msgs
        assert "Q2" in user_msgs
        assert "Q3" in user_msgs

    async def test_default_max_turns_is_20(self) -> None:
        proc = _make_proc()
        assert proc._max_turns == 20

    async def test_agent_config_max_turns_default(self) -> None:
        cfg = AgentConfig(agent_id="a", organization_id="o", name="Test")
        assert cfg.max_turns == 20


# ── TestToolCalling ────────────────────────────────────────────────────────────

class TestToolCalling:
    """Tool call chunks emit FunctionCallInProgressFrame with correct fields."""

    async def test_tool_call_emits_function_call_frame(self) -> None:
        lines = [
            _tool_line("get_weather", {"city": "London"}),
            _done_line(),
        ]
        proc = _make_proc()
        frames = await _run(proc, _transcription("Weather?"), lines)

        fn_frames = [f for f in frames if isinstance(f, FunctionCallInProgressFrame)]
        assert len(fn_frames) == 1
        assert fn_frames[0].function_name == "get_weather"
        assert fn_frames[0].arguments == {"city": "London"}

    async def test_tool_call_id_propagated(self) -> None:
        lines = [_tool_line("lookup", {}), _done_line()]
        proc = _make_proc()
        frames = await _run(proc, _transcription("Lookup?"), lines)

        fn_frame = next(f for f in frames if isinstance(f, FunctionCallInProgressFrame))
        assert fn_frame.tool_call_id == "tc1"


# ── TestUpdateSystemPrompt ─────────────────────────────────────────────────────

class TestUpdateSystemPrompt:
    """update_system_prompt() replaces the prompt for subsequent turns."""

    async def test_prompt_updated_mid_session(self) -> None:
        proc = _make_proc()
        original = proc._system_prompt
        new_prompt = "You are a French-speaking assistant."
        proc.update_system_prompt(new_prompt)

        assert proc._system_prompt == new_prompt
        assert proc._system_prompt != original

    async def test_updated_prompt_used_in_next_call(self) -> None:
        """Verify that the new prompt is included in the messages sent to Ollama."""
        sent_payloads: list[dict] = []

        proc = _make_proc()
        new_prompt = "You are a pirate."
        proc.update_system_prompt(new_prompt)

        mock_session = MagicMock()
        mock_session.closed = False

        @asynccontextmanager
        async def mock_post(url: str, json: dict, **_kw: Any):
            sent_payloads.append(json)
            yield _StreamingResponse([_done_line()])

        mock_session.post = mock_post
        proc._session = mock_session

        await proc.process_frame(_transcription("Arr"), FrameDirection.DOWNSTREAM)

        assert len(sent_payloads) == 1
        system_msgs = [m for m in sent_payloads[0]["messages"] if m["role"] == "system"]
        assert system_msgs[0]["content"] == new_prompt


# ── TestErrorHandling ──────────────────────────────────────────────────────────

class TestErrorHandling:
    """HTTP and connection errors produce a fallback TextFrame, never crash."""

    async def test_http_500_emits_error_text_frame(self) -> None:
        proc = _make_proc()

        mock_session = MagicMock()
        mock_session.closed = False

        @asynccontextmanager
        async def mock_post(*_a: Any, **_kw: Any):
            yield _StreamingResponse([], status=500)

        mock_session.post = mock_post
        proc._session = mock_session

        frames = []

        async def capture(f: Any, d: FrameDirection = FrameDirection.DOWNSTREAM) -> None:
            frames.append(f)

        proc.push_frame = capture  # type: ignore[method-assign]
        await proc.process_frame(_transcription("Hello"), FrameDirection.DOWNSTREAM)

        text_frames = [f for f in frames if isinstance(f, TextFrame)]
        assert len(text_frames) == 1
        assert "error" in text_frames[0].text.lower()

    async def test_connection_error_emits_fallback_text_frame(self) -> None:
        import aiohttp

        proc = _make_proc()

        mock_session = MagicMock()
        mock_session.closed = False

        @asynccontextmanager
        async def mock_post(*_a: Any, **_kw: Any):
            raise aiohttp.ClientConnectionError("refused")
            yield  # make it a generator

        mock_session.post = mock_post
        proc._session = mock_session

        frames: list[Any] = []

        async def capture(f: Any, d: FrameDirection = FrameDirection.DOWNSTREAM) -> None:
            frames.append(f)

        proc.push_frame = capture  # type: ignore[method-assign]
        await proc.process_frame(_transcription("Ping"), FrameDirection.DOWNSTREAM)

        text_frames = [f for f in frames if isinstance(f, TextFrame)]
        assert any("trouble" in f.text.lower() or "language model" in f.text.lower() for f in text_frames)

    async def test_lifecycle_frames_emitted_even_on_http_error(self) -> None:
        """Start + End frames must still bracket the response even on failure."""
        proc = _make_proc()
        mock_session = MagicMock()
        mock_session.closed = False

        @asynccontextmanager
        async def mock_post(*_a: Any, **_kw: Any):
            yield _StreamingResponse([], status=503)

        mock_session.post = mock_post
        proc._session = mock_session
        frames: list[Any] = []

        async def capture(f: Any, d: FrameDirection = FrameDirection.DOWNSTREAM) -> None:
            frames.append(f)

        proc.push_frame = capture  # type: ignore[method-assign]
        await proc.process_frame(_transcription("Hi"), FrameDirection.DOWNSTREAM)

        types = [type(f) for f in frames]
        assert LLMFullResponseStartFrame in types
        assert LLMFullResponseEndFrame in types


# ── TestBargeInCancellation ────────────────────────────────────────────────────

class TestBargeInCancellation:
    """
    StartInterruptionFrame must cancel an in-flight generation rather than
    letting the stream keep running to completion in the background.
    """

    async def test_interruption_cancels_in_flight_generation(self) -> None:
        proc = _make_proc()
        release = asyncio.Event()

        class _SlowStreamingResponse:
            status = 200

            @property
            def content(self):
                async def _aiter():
                    yield _token_line("Partial response that should ")
                    await release.wait()  # never set — simulates a long stream
                    yield _token_line("never arrive.")  # pragma: no cover
                    yield _done_line()  # pragma: no cover
                return _aiter()

            async def text(self) -> str:
                return ""

        mock_session = MagicMock()
        mock_session.closed = False

        @asynccontextmanager
        async def mock_post(*_a: Any, **_kw: Any):
            yield _SlowStreamingResponse()

        mock_session.post = mock_post
        proc._session = mock_session

        captured: list[Any] = []

        async def capture(f: Any, d: FrameDirection = FrameDirection.DOWNSTREAM) -> None:
            captured.append(f)

        proc.push_frame = capture  # type: ignore[method-assign]

        run_task = asyncio.create_task(
            proc.process_frame(_transcription("Hello"), FrameDirection.DOWNSTREAM)
        )
        # Let the task start streaming and register _current_task.
        for _ in range(100):
            if proc._current_task is not None:
                break
            await asyncio.sleep(0)
        assert proc._current_task is not None, "generation task was never started"

        await proc.process_frame(StartInterruptionFrame(), FrameDirection.DOWNSTREAM)
        await run_task  # must complete cleanly, not raise

        # Partial output must never reach conversation history.
        assistant_msgs = [m for m in proc._history if m["role"] == "assistant"]
        assert assistant_msgs == []
        assert len(proc._history) == 1  # only the user turn
        assert proc._current_task is None

        # StartInterruptionFrame is still forwarded downstream for the rest
        # of the pipeline (TTS flush, etc.) even though we consumed it here.
        assert any(isinstance(f, StartInterruptionFrame) for f in captured)


# ── TestPromptTemplate ─────────────────────────────────────────────────────────

class TestPromptTemplate:
    """resolve_system_prompt() does safe variable substitution."""

    def test_all_variables_replaced(self) -> None:
        template = "You are {agent_name} for {org_name}. Speak {language}."
        ctx = PromptContext(agent_name="Eva", org_name="Acme", language="French")
        result = resolve_system_prompt(template, ctx)
        assert result == "You are Eva for Acme. Speak French."

    def test_unknown_placeholder_kept_verbatim(self) -> None:
        template = "Hello {unknown_var} and {agent_name}."
        ctx = PromptContext(agent_name="Bot")
        result = resolve_system_prompt(template, ctx)
        assert "{unknown_var}" in result
        assert "Bot" in result

    def test_none_ctx_returns_template_unchanged(self) -> None:
        template = "Static prompt with no placeholders."
        assert resolve_system_prompt(template, None) == template

    def test_today_auto_filled(self) -> None:
        ctx = PromptContext()
        assert ctx.today == date.today().isoformat()

    def test_custom_instructions_substituted(self) -> None:
        template = "Base. {custom_instructions}"
        ctx = PromptContext(custom_instructions="Always be polite.")
        result = resolve_system_prompt(template, ctx)
        assert "Always be polite." in result

    def test_pricing_response_substituted(self) -> None:
        template = "Pricing: {pricing_response}"
        ctx = PromptContext(pricing_response="$9.99/month")
        assert "$9.99/month" in resolve_system_prompt(template, ctx)

    def test_max_words_substituted(self) -> None:
        template = "Keep under {max_words} words."
        ctx = PromptContext(max_words=75)
        assert "75" in resolve_system_prompt(template, ctx)
