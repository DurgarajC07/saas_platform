"""
ToolExecutorProcessor — FunctionCallInProgressFrame → FunctionCallResultFrame.

Receives tool invocation requests from the LLM (via OllamaLLMProcessor),
executes the named function, and injects the result back into the LLM context.

Two built-in tool categories
-----------------------------
1. **HTTP tools** — POST to an external API endpoint, return JSON body.
   Tool definition schema::

       {
         "type": "function",
         "function": {
           "name": "check_order_status",
           "description": "Look up a customer order by order ID",
           "parameters": { ... },
           "x_endpoint": "https://api.example.com/orders/{order_id}"
         }
       }

2. **Python callables** — register at runtime via ``register_tool(name, fn)``.
   Used for DB lookups, calculation, date/time, etc.

Fallback
--------
If a tool name is unknown the processor logs a warning and injects an error
result so the LLM can respond gracefully ("I couldn't find that information").
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Coroutine

import aiohttp
import structlog
from pipecat.frames.frames import (
    EndFrame,
    Frame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    LLMMessagesFrame,
    StartFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)

# Type alias for async tool callables
ToolFn = Callable[[dict[str, Any]], Coroutine[Any, Any, Any]]


class ToolExecutorProcessor(FrameProcessor):
    """
    Executes function/tool calls from the LLM and returns results.

    Parameters
    ----------
    tools : list[dict]
        OpenAI-compatible tool definitions (the same list passed to Ollama).
        ``x_endpoint`` is a custom extension key for HTTP-based tools.
    http_timeout_s : float
        Timeout for external HTTP tool calls (default 10s).
    """

    def __init__(
        self,
        tools: list[dict[str, Any]] | None = None,
        http_timeout_s: float = 10.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._tool_defs  = {
            t["function"]["name"]: t["function"]
            for t in (tools or [])
            if t.get("type") == "function"
        }
        self._callables: dict[str, ToolFn]       = {}
        self._session: aiohttp.ClientSession | None = None
        self._http_timeout = aiohttp.ClientTimeout(total=http_timeout_s)
        self._log = logger.bind(processor="ToolExecutor")

    # ── Public API ────────────────────────────────────────────────────────────

    def register_tool(self, name: str, fn: ToolFn) -> None:
        """Register a Python coroutine as a callable tool."""
        self._callables[name] = fn
        self._log.debug("tool.registered", name=name)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            self._session = aiohttp.ClientSession(timeout=self._http_timeout)
            await self.push_frame(frame, direction)

        elif isinstance(frame, FunctionCallInProgressFrame):
            result = await self._execute(
                frame.function_name, frame.arguments
            )
            # Inject result back into LLM context
            await self.push_frame(
                FunctionCallResultFrame(
                    function_name=frame.function_name,
                    tool_call_id=frame.tool_call_id,
                    arguments=frame.arguments,
                    result=result,
                )
            )
            # Re-enter LLM with the tool result as assistant message
            await self.push_frame(
                LLMMessagesFrame(
                    messages=[
                        {
                            "role":    "tool",
                            "content": json.dumps(result),
                            "name":    frame.function_name,
                        }
                    ]
                )
            )

        elif isinstance(frame, EndFrame):
            if self._session and not self._session.closed:
                await self._session.close()
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _execute(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """
        Route tool call to the appropriate executor.

        Priority:
          1. Registered Python callable (registered via ``register_tool``)
          2. HTTP endpoint declared in ``x_endpoint`` tool definition field
          3. Unknown tool — returns error dict
        """
        self._log.info("tool.executing", name=name, args=list(arguments.keys()))

        # 1. Python callable
        if name in self._callables:
            try:
                return await self._callables[name](arguments)
            except Exception as exc:
                self._log.exception("tool.callable_failed", name=name, error=str(exc))
                return {"error": str(exc)}

        # 2. HTTP endpoint
        tool_def = self._tool_defs.get(name, {})
        endpoint: str | None = tool_def.get("x_endpoint")
        if endpoint:
            return await self._call_http(endpoint, arguments)

        # 3. Unknown
        self._log.warning("tool.unknown", name=name)
        return {"error": f"Tool '{name}' is not registered."}

    async def _call_http(self, endpoint: str, params: dict[str, Any]) -> Any:
        """POST params to an HTTP endpoint, return parsed JSON body."""
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._http_timeout)
        try:
            async with self._session.post(endpoint, json=params) as resp:
                if resp.content_type == "application/json":
                    return await resp.json()
                text = await resp.text()
                return {"result": text, "status": resp.status}
        except asyncio.TimeoutError:
            return {"error": f"HTTP tool timed out after {self._http_timeout.total}s"}
        except aiohttp.ClientError as exc:
            self._log.error("tool.http_failed", endpoint=endpoint, error=str(exc))
            return {"error": str(exc)}
