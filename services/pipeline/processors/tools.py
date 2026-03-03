"""
ToolExecutorProcessor — FunctionCallInProgressFrame → FunctionCallResultFrame.

Receives tool invocation requests from the LLM (via OllamaLLMProcessor),
dispatches them to the correct executor backend, and injects the result back
into the LLM context so the model can formulate its final response.

Tool definition format
----------------------
Each entry in ``tools_json`` uses the OpenAI function-calling schema extended
with an ``executor`` block inside the ``function`` object::

    {
      "type": "function",
      "function": {
        "name": "get_order_status",
        "description": "Look up order status by order ID",
        "parameters": {
          "type": "object",
          "properties": {
            "order_id": { "type": "string", "description": "The order ID" }
          },
          "required": ["order_id"]
        },
        "executor": {
          "type": "http_get",
          "url": "https://api.acme.com/orders/{order_id}",
          "headers": { "Authorization": "Bearer {ACME_API_KEY}" }
        }
      }
    }

Supported executor types
------------------------
http_get      —  GET request; ``{param}`` tokens filled from call args;
                 ``{SECRET_NAME}`` tokens resolved from ``org_secrets``.
http_post     —  POST request; JSON body template merged with call kwargs.
sql_query     —  Read-only asyncpg query with allowlist guard + DDL/DML block.
python_func   —  Name-dispatch to a Python callable registered at runtime.

Secret injection
----------------
``org_secrets`` is a dict of **pre-decrypted** values provided by the platform
at session creation.  ``{SECRET_NAME}`` placeholders in URLs and headers are
resolved from this dict — secrets never appear in ``tools_json`` or log lines.

Backward compatibility
----------------------
Tool definitions that use the older ``x_endpoint`` key instead of an
``executor`` block are still supported via an implicit HTTP POST call.

Dispatch priority
-----------------
1. Registered Python callable (``register_tool(name, fn)``) — highest priority.
2. ``executor`` block → routed via ``EXECUTOR_MAP``.
3. Legacy ``x_endpoint`` — HTTP POST.
4. Unknown tool — error dict returned, LLM responds gracefully.
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

from processors.executors import (
    HTTPGetExecutor,
    HTTPPostExecutor,
    PythonFunctionExecutor,
    SQLQueryExecutor,
)

logger = structlog.get_logger(__name__)

# Type alias for async tool callables registered at runtime
ToolFn = Callable[[dict[str, Any]], Coroutine[Any, Any, Any]]


class ToolExecutorProcessor(FrameProcessor):
    """
    Routes LLM function-call frames to the correct executor backend.

    Parameters
    ----------
    tools_spec:
        OpenAI-compatible tool definition list.  Each ``function`` block may
        carry an ``executor`` sub-object (new-style) or an ``x_endpoint`` key
        (legacy style).
    org_secrets:
        Pre-decrypted org-level secrets used to resolve ``{SECRET_NAME}``
        placeholders in executor URLs and headers.  **Never** stored in
        ``tools_json`` — supplied by the platform at session-creation time.
    http_timeout_s:
        Default HTTP timeout applied to legacy ``x_endpoint`` tools (seconds).
    """

    #: Executor backend registry — maps ``executor.type`` → class
    EXECUTOR_MAP = {
        "http_get":    HTTPGetExecutor,
        "http_post":   HTTPPostExecutor,
        "sql_query":   SQLQueryExecutor,
        "python_func": PythonFunctionExecutor,
    }

    def __init__(
        self,
        tools_spec: list[dict[str, Any]] | None = None,
        org_secrets: dict[str, str] | None = None,
        http_timeout_s: float = 10.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._org_secrets: dict[str, str] = org_secrets or {}
        self._http_timeout_s = http_timeout_s
        self._log = logger.bind(processor="ToolExecutorProcessor")

        # Index: function_name → full ``function`` block (parameters + executor)
        self._tool_defs: dict[str, dict[str, Any]] = {}
        for entry in (tools_spec or []):
            if entry.get("type") == "function":
                fn_block = entry["function"]
                self._tool_defs[fn_block["name"]] = fn_block

        # Runtime Python callable registry
        self._callables: dict[str, ToolFn] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def register_tool(self, name: str, fn: ToolFn) -> None:
        """
        Register an async coroutine as a Python-callable tool.

        The callable receives all LLM-supplied arguments as keyword arguments
        and must return a JSON-serialisable value.
        """
        self._callables[name] = fn
        self._log.debug("tool.registered", name=name)

    # ── Frame lifecycle ───────────────────────────────────────────────────────

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)

        elif isinstance(frame, FunctionCallInProgressFrame):
            # Parse arguments — pipecat may pass them as a JSON string or dict
            args: dict[str, Any]
            if isinstance(frame.arguments, dict):
                args = frame.arguments
            else:
                try:
                    args = json.loads(frame.arguments or "{}")
                except (json.JSONDecodeError, TypeError):
                    args = {}

            result = await self._dispatch(frame.function_name, args)

            # Push the structured result frame (pipecat internal)
            await self.push_frame(
                FunctionCallResultFrame(
                    function_name=frame.function_name,
                    tool_call_id=frame.tool_call_id,
                    arguments=frame.arguments,
                    result=result,
                )
            )
            # Re-enter LLM with the tool result as a "tool" role message
            await self.push_frame(
                LLMMessagesFrame(
                    messages=[
                        {
                            "role":    "tool",
                            "content": (
                                result
                                if isinstance(result, str)
                                else json.dumps(result)
                            ),
                            "name": frame.function_name,
                        }
                    ]
                )
            )

        elif isinstance(frame, EndFrame):
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)

    # ── Internal dispatch ─────────────────────────────────────────────────────

    async def _dispatch(self, name: str, arguments: dict[str, Any]) -> Any:
        """
        Route a tool call to its executor.

        Dispatch priority
        -----------------
        1. Registered Python callable — runtime override, highest priority.
        2. ``executor`` block from the tool definition (new-style).
        3. Legacy ``x_endpoint`` key — HTTP POST fallback.
        4. Unknown / unconfigured — returns a descriptive error dict.
        """
        self._log.info(
            "tool.dispatching", name=name, arg_keys=list(arguments.keys())
        )

        # 1. Python callable
        if name in self._callables:
            try:
                return await self._callables[name](arguments)
            except Exception as exc:
                self._log.exception("tool.callable_failed", name=name, error=str(exc))
                return {"error": str(exc)}

        tool_def = self._tool_defs.get(name)
        if tool_def:
            # 2. Executor block (new-style)
            executor_cfg = tool_def.get("executor")
            if executor_cfg:
                return await self._run_executor(name, executor_cfg, arguments)

            # 3. Legacy x_endpoint (backward compat)
            legacy_url: str | None = tool_def.get("x_endpoint")
            if legacy_url:
                return await self._legacy_http_post(legacy_url, arguments)

        # 4. Unknown
        self._log.warning("tool.unknown", name=name)
        return {
            "error": (
                f"Tool '{name}' is not registered or has no executor configured. "
                "Check the agent's tools_json definition."
            )
        }

    async def _run_executor(
        self,
        name: str,
        executor_cfg: dict[str, Any],
        arguments: dict[str, Any],
    ) -> Any:
        """Instantiate the correct executor from EXECUTOR_MAP and run it."""
        executor_type = executor_cfg.get("type")
        if not executor_type:
            return {"error": f"Tool '{name}' executor is missing the required 'type' field"}

        executor_cls = self.EXECUTOR_MAP.get(executor_type)
        if not executor_cls:
            known = list(self.EXECUTOR_MAP)
            return {
                "error": (
                    f"Unknown executor type '{executor_type}' for tool '{name}'. "
                    f"Known types: {known}"
                )
            }

        executor = executor_cls(executor_cfg, secrets=self._org_secrets)
        try:
            return await executor.execute(**arguments)
        except Exception as exc:
            self._log.exception(
                "tool.executor_raised",
                name=name,
                executor_type=executor_type,
                error=str(exc),
            )
            return {"error": f"Executor '{executor_type}' raised an unexpected error: {exc}"}

    async def _legacy_http_post(
        self, url: str, params: dict[str, Any]
    ) -> Any:
        """Backward-compatible HTTP POST for ``x_endpoint``-style tool definitions."""
        timeout = aiohttp.ClientTimeout(total=self._http_timeout_s)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=params) as resp:
                    if resp.content_type and "json" in resp.content_type:
                        return await resp.json()
                    return {"result": await resp.text(), "status": resp.status}
        except asyncio.TimeoutError:
            return {
                "error": f"HTTP POST timed out after {self._http_timeout_s}s (url={url})"
            }
        except aiohttp.ClientError as exc:
            self._log.error("tool.legacy_http_failed", url=url, error=str(exc))
            return {"error": str(exc)}
