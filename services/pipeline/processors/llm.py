"""
OllamaLLMProcessor — TranscriptionFrame → streaming TextFrames.

Calls Ollama's OpenAI-compatible ``/api/chat`` endpoint with streaming enabled.
Text is buffered to sentence boundaries before pushing downstream so
``KokoroTTSProcessor`` can start synthesis on complete phrases rather than
individual tokens, reducing TTFB.

Features
--------
* Per-session conversation history with configurable ``max_turns`` (default 20)
* System prompt template variables resolved at session start
* OpenAI-compatible function/tool calling — routes to ``ToolExecutorProcessor``
* Sentence-boundary batching: TextFrame pushed when ``.`` / ``!`` / ``?`` seen
* LLM model hot-swappable via ``AgentConfig.llm_model``
* ``update_system_prompt()`` for mid-session prompt updates
* Structured TTFB and tokens/s logging

Env vars
--------
  OLLAMA_URL       http://host.docker.internal:11434
  OLLAMA_MODEL     qwen2.5:3b
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any

import aiohttp
import structlog
from metrics import get_metrics
from pipecat.frames.frames import (
    EndFrame,
    Frame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMMessagesFrame,
    TextFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)

_OLLAMA_URL_DEFAULT = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
_MODEL_DEFAULT      = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

# Characters that mark the end of a sentence / natural TTS dispatch boundary
_SENTENCE_ENDS_RE = re.compile(r'[.!?][\s"\')]?$')


class OllamaLLMProcessor(FrameProcessor):
    """
    Ollama LLM processor using the OpenAI-compatible streaming chat API.

    Parameters
    ----------
    model : str
        Ollama model name (e.g. ``'qwen2.5:3b'``, ``'qwen2.5:7b'``).
    system_prompt : str
        Injected as the ``system`` role message in every conversation.  May
        contain ``{variable}`` placeholders pre-resolved by
        ``resolve_system_prompt()``.
    tools : list[dict] | None
        OpenAI-compatible tool/function definitions.  Set to ``None`` to
        disable tool calling.
    temperature : float
        Sampling temperature (0.0 = deterministic, 1.0 = creative).
    max_tokens : int
        Maximum number of tokens in the completion.
    max_turns : int
        Maximum number of conversational turns to keep in history.  Older
        turns are silently dropped.  One turn = one user + one assistant
        message pair.  Default is 20.
    ollama_url : str
        Base URL of the Ollama server.
    """

    def __init__(
        self,
        model: str               = _MODEL_DEFAULT,
        system_prompt: str       = "You are a helpful voice assistant.",
        tools: list[dict] | None = None,
        temperature: float       = 0.7,
        max_tokens: int          = 512,
        max_turns: int           = 20,
        ollama_url: str          = _OLLAMA_URL_DEFAULT,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._model         = model
        self._system_prompt = system_prompt
        self._tools         = tools
        self._temperature   = temperature
        self._max_tokens    = max_tokens
        self._max_turns     = max_turns
        self._chat_url      = f"{ollama_url.rstrip('/')}/api/chat"
        self._session: aiohttp.ClientSession | None = None
        self._history: list[dict[str, str]] = []   # user/assistant turn pairs
        self._log = logger.bind(processor="OllamaLLM", model=model)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    # ── Public API ────────────────────────────────────────────────────────────

    def update_system_prompt(self, prompt: str) -> None:
        """Replace the system prompt mid-session (e.g. after language detection)."""
        self._system_prompt = prompt
        self._log.info("ollama_llm.system_prompt_updated", length=len(prompt))

    def clear_history(self) -> None:
        """Wipe conversation history (useful for test isolation or session reset)."""
        self._history.clear()

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            # New user utterance — append to history and run LLM
            self._history.append({"role": "user", "content": frame.text})
            self._log.debug(
                "ollama_llm.user_turn",
                text=frame.text[:80],
                history_len=len(self._history),
            )
            await self._run_llm()

        elif isinstance(frame, LLMMessagesFrame):
            # Tool-result re-entry from ToolExecutorProcessor — extend history
            for msg in frame.messages:
                self._history.append(msg)
            await self._run_llm()

        elif isinstance(frame, EndFrame):
            await self._close_session()
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)

    # ── Internal ────────────────────────────────────────────────────────────

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if not self._session or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=60, connect=5)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _close_session(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _run_llm(self) -> None:
        """
        Stream completions from Ollama using the current history.

        Tokens are accumulated into ``_text_buf`` and flushed as a single
        ``TextFrame`` whenever a sentence-ending character is detected.  Any
        remaining text is pushed as a final frame after the stream ends.
        The complete assistant response is appended to ``_history`` and the
        history is trimmed to ``max_turns``.
        """
        # System message + current conversation history
        ctx: list[dict] = [
            {"role": "system", "content": self._system_prompt}
        ] + self._history

        payload: dict[str, Any] = {
            "model":    self._model,
            "messages": ctx,
            "stream":   True,
            "options":  {
                "temperature": self._temperature,
                "num_predict": self._max_tokens,
            },
        }
        if self._tools:
            payload["tools"] = self._tools

        session = await self._ensure_session()
        t0 = time.perf_counter()
        token_count = 0
        first_token_ms: float | None = None
        full_response: str = ""
        text_buf: str = ""

        await self.push_frame(LLMFullResponseStartFrame())

        try:
            async with session.post(self._chat_url, json=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    self._log.error(
                        "ollama_llm.http_error",
                        status=resp.status,
                        body=body[:200],
                    )
                    await self.push_frame(
                        TextFrame(text="I'm sorry, I encountered an error.")
                    )
                    return  # EndFrame emitted in finally below

                async for raw_line in resp.content:
                    line = raw_line.strip()
                    if not line:
                        continue

                    try:
                        chunk: dict = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # ── Tool call handling ─────────────────────────────────
                    tool_calls = (
                        chunk.get("message", {}).get("tool_calls") or []
                    )
                    for tc in tool_calls:
                        fn_name = tc.get("function", {}).get("name", "")
                        fn_args = tc.get("function", {}).get("arguments", {})
                        self._log.info(
                            "ollama_llm.tool_call",
                            name=fn_name,
                        )
                        await self.push_frame(
                            FunctionCallInProgressFrame(
                                function_name=fn_name,
                                tool_call_id=tc.get("id", ""),
                                arguments=fn_args,
                            )
                        )

                    # ── Token streaming ────────────────────────────────────
                    token: str = chunk.get("message", {}).get("content", "")
                    if token:
                        if first_token_ms is None:
                            first_token_ms = round(
                                (time.perf_counter() - t0) * 1000, 1
                            )
                            self._log.info(
                                "ollama_llm.first_token",
                                ttfb_ms=first_token_ms,
                            )
                            _m = get_metrics()
                            if _m is not None:
                                _m.record_llm_ttft_ms(first_token_ms)
                        token_count += 1
                        full_response += token
                        text_buf      += token

                        # Flush on sentence boundary for low-latency TTS start
                        if _SENTENCE_ENDS_RE.search(text_buf):
                            await self.push_frame(TextFrame(text=text_buf))
                            text_buf = ""

                    if chunk.get("done"):
                        break

        except aiohttp.ClientError as exc:
            self._log.exception("ollama_llm.connection_error", error=str(exc))
            await self.push_frame(
                TextFrame(text="I'm having trouble connecting to my language model.")
            )

        finally:
            # Flush any remaining buffered text
            if text_buf.strip():
                await self.push_frame(TextFrame(text=text_buf))

            elapsed = round((time.perf_counter() - t0) * 1000, 1)
            tps = round(token_count / max(elapsed / 1000, 0.001), 1)
            self._log.info(
                "ollama_llm.done",
                tokens=token_count,
                elapsed_ms=elapsed,
                tokens_per_s=tps,
                first_token_ms=first_token_ms,
            )

            await self.push_frame(LLMFullResponseEndFrame())

            # Persist assistant response and enforce history cap
            if full_response:
                self._history.append(
                    {"role": "assistant", "content": full_response}
                )
            self._trim_history()

    def _trim_history(self) -> None:
        """
        Enforce the ``max_turns`` cap.

        ``max_turns`` = number of user/assistant exchange pairs to retain.
        Older pairs are dropped from the front; the most recent turns are
        always preserved.
        """
        max_messages = self._max_turns * 2  # each turn = 1 user + 1 assistant
        if len(self._history) > max_messages:
            dropped = len(self._history) - max_messages
            self._history = self._history[dropped:]
            self._log.debug(
                "ollama_llm.history_trimmed",
                dropped=dropped,
                retained=len(self._history),
            )
