"""
OllamaLLMProcessor — LLMMessagesFrame → streaming TextFrames.

Calls Ollama's OpenAI-compatible ``/api/chat`` endpoint with streaming enabled.
Each token is pushed downstream as a TextFrame immediately — KokoroTTSProcessor
accumulates them into sentences for synthesis.

Features
--------
* Full conversation context via LLMMessagesFrame (system + history + user turn)
* OpenAI-compatible tool/function calling via ``tools`` parameter
* Streaming token delivery for low TTFB
* Structured logging of token counts and latency

Env vars
--------
  OLLAMA_URL       http://host.docker.internal:11434
  OLLAMA_MODEL     qwen2.5:3b
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

import aiohttp
import structlog
from pipecat.frames.frames import (
    EndFrame,
    Frame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMMessagesFrame,
    TextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)

_OLLAMA_URL_DEFAULT = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
_MODEL_DEFAULT      = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")


class OllamaLLMProcessor(FrameProcessor):
    """
    Ollama LLM processor using the OpenAI-compatible streaming chat API.

    Parameters
    ----------
    model : str
        Ollama model name (e.g. ``'qwen2.5:3b'``, ``'qwen2.5:7b'``).
    system_prompt : str
        Injected as the ``system`` role message in every conversation.
    tools : list[dict] | None
        OpenAI-compatible tool/function definitions.  Set to ``None`` to
        disable tool calling.
    temperature : float
        Sampling temperature (0.0 = deterministic, 1.0 = creative).
    max_tokens : int
        Maximum number of tokens in the completion.
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
        ollama_url: str          = _OLLAMA_URL_DEFAULT,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._model         = model
        self._system_prompt = system_prompt
        self._tools         = tools
        self._temperature   = temperature
        self._max_tokens    = max_tokens
        self._chat_url      = f"{ollama_url.rstrip('/')}/api/chat"
        self._session: aiohttp.ClientSession | None = None
        self._log = logger.bind(processor="OllamaLLM", model=model)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMMessagesFrame):
            await self._run_llm(frame.messages)

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

    async def _run_llm(self, messages: list[dict[str, str]]) -> None:
        """
        Stream completions from Ollama and push each token as a TextFrame.
        """
        # Prepend system prompt
        ctx: list[dict] = [{"role": "system", "content": self._system_prompt}]
        ctx.extend(messages)

        payload: dict[str, Any] = {
            "model":   self._model,
            "messages": ctx,
            "stream":  True,
            "options": {
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

        await self.push_frame(LLMFullResponseStartFrame())

        try:
            async with session.post(self._chat_url, json=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    self._log.error(
                        "ollama_llm.http_error", status=resp.status, body=body[:200]
                    )
                    await self.push_frame(
                        TextFrame(text="I'm sorry, I encountered an error.")
                    )
                    return

                async for line in resp.content:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        chunk: dict = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Tool call handling
                    tool_calls = (
                        chunk.get("message", {}).get("tool_calls") or []
                    )
                    for tc in tool_calls:
                        self._log.info(
                            "ollama_llm.tool_call",
                            name=tc.get("function", {}).get("name"),
                        )
                        await self.push_frame(
                            FunctionCallInProgressFrame(
                                function_name=tc["function"]["name"],
                                tool_call_id=tc.get("id", ""),
                                arguments=tc["function"].get("arguments", {}),
                            )
                        )

                    # Token streaming
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        if first_token_ms is None:
                            first_token_ms = round(
                                (time.perf_counter() - t0) * 1000, 1
                            )
                            self._log.info(
                                "ollama_llm.first_token", ttfb_ms=first_token_ms
                            )
                        token_count += 1
                        await self.push_frame(TextFrame(text=token))

                    if chunk.get("done"):
                        break

        except aiohttp.ClientError as exc:
            self._log.exception("ollama_llm.connection_error", error=str(exc))
            await self.push_frame(
                TextFrame(text="I'm having trouble connecting to my language model.")
            )

        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        tps = round(token_count / max(elapsed / 1000, 0.001), 1)
        self._log.info(
            "ollama_llm.done",
            tokens=token_count,
            elapsed_ms=elapsed,
            tokens_per_s=tps,
        )

        await self.push_frame(LLMFullResponseEndFrame())
