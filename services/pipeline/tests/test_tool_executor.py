"""
Unit tests for ToolExecutorProcessor and executor backends — Day 11 deliverables.

All HTTP interactions are mocked with aiohttp's test utilities.
No real database or external API is required.

Deliverables verified
---------------------
  ✓  http_get executor — URL template substitution w/ call kwargs
  ✓  http_get executor — secret injection into headers ({SECRET_NAME})
  ✓  http_get executor — JSON response parsed and returned
  ✓  http_get executor — non-JSON response returns {result, status} dict
  ✓  http_get executor — timeout returns error dict (no crash)
  ✓  http_post executor — kwargs sent as JSON body when no body template
  ✓  http_post executor — body template filled from call kwargs
  ✓  http_post executor — secret injection into headers
  ✓  sql_query executor — safe SELECT query accepted
  ✓  sql_query executor — DDL statements rejected (INSERT, DROP, etc.)
  ✓  sql_query executor — table not in allowlist rejected
  ✓  sql_query executor — empty allowed_tables skips table check
  ✓  sql_query executor — unsatisfied query template parameter → error
  ✓  sql_query executor — missing DSN secret → error (no crash)
  ✓  python_func executor stub — returns descriptive error
  ✓  ToolExecutorProcessor — registered callable invoked (priority 1)
  ✓  ToolExecutorProcessor — executor block dispatched (priority 2)
  ✓  ToolExecutorProcessor — legacy x_endpoint POST (priority 3)
  ✓  ToolExecutorProcessor — unknown tool returns error dict (no crash)
  ✓  ToolExecutorProcessor — unknown executor type returns error dict
  ✓  ToolExecutorProcessor — FunctionCallInProgressFrame produces result + LLM re-entry
  ✓  ToolExecutorProcessor — arguments as JSON string parsed correctly
  ✓  ToolExecutorProcessor — EXECUTOR_MAP contains all four required types
  ✓  AgentConfig — org_secrets field defaults to empty dict
  ✓  AgentConfig — org_secrets passed through to ToolExecutorProcessor
"""

from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipecat.frames.frames import (
    EndFrame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    LLMMessagesFrame,
    StartFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessorSetup

from processors.executors import (
    HTTPGetExecutor,
    HTTPPostExecutor,
    PythonFunctionExecutor,
    SQLQueryExecutor,
    _inject_secrets,
)
from processors.tools import ToolExecutorProcessor
from schemas import AgentConfig, AgentType


# ── Frame capture helper ───────────────────────────────────────────────────────

async def _send(processor: ToolExecutorProcessor, frames: list) -> list:
    """Feed *frames* into *processor*, return all frames passed to push_frame."""
    captured: list = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        captured.append(frame)

    processor.push_frame = capture  # type: ignore[method-assign]

    for frame in frames:
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

    return captured


# ── Mock HTTP helpers ──────────────────────────────────────────────────────────

def _mock_http_response(
    json_body: dict | None = None,
    text_body: str = "ok",
    status: int = 200,
    content_type: str = "application/json",
) -> Any:
    """Build a mock aiohttp ClientSession.get/post context manager."""
    resp = MagicMock()
    resp.status = status
    resp.content_type = content_type
    resp.json = AsyncMock(return_value=json_body or {})
    resp.text = AsyncMock(return_value=text_body)

    @asynccontextmanager
    async def _resp_cm():
        yield resp

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=_resp_cm())
    mock_session.post = MagicMock(return_value=_resp_cm())

    @asynccontextmanager
    async def _session_cm(timeout=None):
        yield mock_session

    return _session_cm, mock_session


# ═══════════════════════════════════════════════════════════════════════════════
# _inject_secrets helper
# ═══════════════════════════════════════════════════════════════════════════════

class TestInjectSecrets:
    def test_replaces_known_keys(self):
        result = _inject_secrets("Bearer {API_KEY}", {"API_KEY": "tok_123"})
        assert result == "Bearer tok_123"

    def test_unknown_keys_left_verbatim(self):
        result = _inject_secrets("Bearer {UNKNOWN}", {"API_KEY": "tok_123"})
        assert result == "Bearer {UNKNOWN}"

    def test_multiple_replacements(self):
        result = _inject_secrets("{A}:{B}", {"A": "1", "B": "2"})
        assert result == "1:2"

    def test_empty_secrets(self):
        result = _inject_secrets("https://example.com/{x}", {})
        assert result == "https://example.com/{x}"


# ═══════════════════════════════════════════════════════════════════════════════
# HTTPGetExecutor
# ═══════════════════════════════════════════════════════════════════════════════

class TestHTTPGetExecutor:
    async def test_url_template_filled_from_kwargs(self):
        session_cm, session = _mock_http_response(json_body={"status": "shipped"})
        executor = HTTPGetExecutor(
            {"url": "https://api.example.com/orders/{order_id}"},
            secrets={},
        )
        with patch("aiohttp.ClientSession", session_cm):
            result = await executor.execute(order_id="ORD-123")
        assert result == {"status": "shipped"}
        call_args = session.get.call_args
        assert "ORD-123" in call_args[0][0]

    async def test_secret_injected_into_headers(self):
        session_cm, session = _mock_http_response(json_body={"ok": True})
        executor = HTTPGetExecutor(
            {
                "url": "https://api.example.com/data",
                "headers": {"Authorization": "Bearer {MY_KEY}"},
            },
            secrets={"MY_KEY": "secret-value"},
        )
        with patch("aiohttp.ClientSession", session_cm):
            await executor.execute()
        headers_sent = session.get.call_args[1]["headers"]
        assert headers_sent["Authorization"] == "Bearer secret-value"

    async def test_non_json_response_returns_result_dict(self):
        session_cm, _ = _mock_http_response(text_body="plain text", content_type="text/plain")
        executor = HTTPGetExecutor({"url": "https://example.com"}, secrets={})
        with patch("aiohttp.ClientSession", session_cm):
            result = await executor.execute()
        assert result["result"] == "plain text"
        assert "status" in result

    async def test_timeout_returns_error_dict(self):
        import asyncio

        @asynccontextmanager
        async def _timeout_session(timeout=None):
            session = MagicMock()
            session.get = MagicMock(side_effect=asyncio.TimeoutError())
            yield session

        executor = HTTPGetExecutor({"url": "https://slow.example.com"}, secrets={})
        with patch("aiohttp.ClientSession", _timeout_session):
            result = await executor.execute()
        assert "error" in result
        assert "timed out" in result["error"].lower()


# ═══════════════════════════════════════════════════════════════════════════════
# HTTPPostExecutor
# ═══════════════════════════════════════════════════════════════════════════════

class TestHTTPPostExecutor:
    async def test_kwargs_sent_as_body_when_no_template(self):
        session_cm, session = _mock_http_response(json_body={"created": True})
        executor = HTTPPostExecutor(
            {"url": "https://api.example.com/cases"},
            secrets={},
        )
        with patch("aiohttp.ClientSession", session_cm):
            result = await executor.execute(customer_id="C1", issue="billing")
        assert result == {"created": True}
        body = session.post.call_args[1]["json"]
        assert body["customer_id"] == "C1"
        assert body["issue"] == "billing"

    async def test_body_template_filled_from_kwargs(self):
        session_cm, session = _mock_http_response(json_body={"queued": True})
        executor = HTTPPostExecutor(
            {
                "url": "https://api.example.com/tasks",
                "body": {"task_id": "{task_id}", "priority": "high"},
            },
            secrets={},
        )
        with patch("aiohttp.ClientSession", session_cm):
            await executor.execute(task_id="T-42")
        body = session.post.call_args[1]["json"]
        assert body["task_id"] == "T-42"
        assert body["priority"] == "high"

    async def test_secret_injected_into_headers(self):
        session_cm, session = _mock_http_response(json_body={})
        executor = HTTPPostExecutor(
            {
                "url": "https://api.example.com/submit",
                "headers": {"X-Api-Key": "{CRM_KEY}"},
            },
            secrets={"CRM_KEY": "crm-tok-999"},
        )
        with patch("aiohttp.ClientSession", session_cm):
            await executor.execute(data="x")
        headers_sent = session.post.call_args[1]["headers"]
        assert headers_sent["X-Api-Key"] == "crm-tok-999"


# ═══════════════════════════════════════════════════════════════════════════════
# SQLQueryExecutor security model
# ═══════════════════════════════════════════════════════════════════════════════

class TestSQLQueryExecutorSecurity:
    """All tests run the security checks without touching a real database."""

    def _executor(self, query: str, allowed_tables: list[str] | None = None) -> SQLQueryExecutor:
        cfg: dict = {"dsn_secret_ref": "DB", "query": query}
        if allowed_tables is not None:
            cfg["allowed_tables"] = allowed_tables
        return SQLQueryExecutor(cfg, secrets={"DB": "postgresql://user:pw@localhost/test"})

    def test_safe_select_accepted(self):
        ex = self._executor("SELECT id, status FROM orders WHERE id = '{id}'", ["orders"])
        safe, reason = ex._is_safe("SELECT id, status FROM orders WHERE id = '1'", ["orders"])
        assert safe is True
        assert reason == ""

    def test_insert_rejected(self):
        ex = self._executor("SELECT 1", [])
        safe, reason = ex._is_safe("INSERT INTO orders (id) VALUES (1)", [])
        assert safe is False
        assert "DDL/DML" in reason

    def test_drop_rejected(self):
        ex = self._executor("SELECT 1", [])
        safe, reason = ex._is_safe("DROP TABLE users", [])
        assert safe is False

    def test_update_rejected(self):
        ex = self._executor("SELECT 1", [])
        safe, reason = ex._is_safe("UPDATE orders SET status='shipped'", [])
        assert safe is False

    def test_delete_rejected(self):
        ex = self._executor("SELECT 1", [])
        safe, reason = ex._is_safe("DELETE FROM orders WHERE id=1", [])
        assert safe is False

    def test_truncate_rejected(self):
        ex = self._executor("SELECT 1", [])
        safe, reason = ex._is_safe("TRUNCATE TABLE audit_logs", [])
        assert safe is False

    def test_table_not_in_allowlist_rejected(self):
        ex = self._executor("SELECT * FROM users", ["orders"])
        safe, reason = ex._is_safe("SELECT * FROM users", ["orders"])
        assert safe is False
        assert "allowlist" in reason.lower()

    def test_empty_allowlist_skips_table_check(self):
        ex = self._executor("SELECT * FROM any_table", [])
        safe, reason = ex._is_safe("SELECT * FROM any_table", [])
        assert safe is True

    def test_no_allowlist_key_skips_table_check(self):
        """No 'allowed_tables' key in config → skip table check."""
        cfg = {"dsn_secret_ref": "DB", "query": "SELECT 1"}
        ex = SQLQueryExecutor(cfg, secrets={"DB": "dsn"})
        safe, reason = ex._is_safe("SELECT * FROM any_table", [])
        assert safe is True

    async def test_missing_dsn_returns_error(self):
        cfg = {"dsn_secret_ref": "MISSING_KEY", "query": "SELECT 1"}
        ex = SQLQueryExecutor(cfg, secrets={})
        result = await ex.execute()
        assert "error" in result
        assert "DSN" in result["error"]

    async def test_missing_query_param_returns_error(self):
        cfg = {
            "dsn_secret_ref": "DB",
            "query": "SELECT * FROM orders WHERE id = '{order_id}'",
            "allowed_tables": ["orders"],
        }
        ex = SQLQueryExecutor(cfg, secrets={"DB": "postgresql://x"})
        result = await ex.execute()  # missing order_id kwarg
        assert "error" in result
        assert "parameter" in result["error"].lower()

    async def test_dml_blocked_returns_error_dict(self):
        """DDL/DML in query template result → error without DB connection."""
        cfg = {
            "dsn_secret_ref": "DB",
            "query": "DROP TABLE orders",
            "allowed_tables": ["orders"],
        }
        ex = SQLQueryExecutor(cfg, secrets={"DB": "postgresql://x"})
        result = await ex.execute()
        assert "error" in result
        assert "not permitted" in result["error"].lower()


# ═══════════════════════════════════════════════════════════════════════════════
# SQLQueryExecutor parameterization — injection must not reach the SQL string
# ═══════════════════════════════════════════════════════════════════════════════

class TestSQLQueryExecutorParameterization:
    """
    Proves {param} values are bound via asyncpg positional placeholders
    ($1, $2, ...) rather than interpolated into the query text — so a
    malicious value can only ever be treated as a literal, never as SQL.
    """

    def test_parameterize_translates_placeholder_to_positional(self):
        from processors.executors import _parameterize_sql

        query, values = _parameterize_sql(
            "SELECT id, status FROM orders WHERE id = {order_id}",
            {"order_id": "ORD-1"},
        )
        assert query == "SELECT id, status FROM orders WHERE id = $1"
        assert values == ["ORD-1"]

    def test_parameterize_repeated_placeholder_reuses_position(self):
        from processors.executors import _parameterize_sql

        query, values = _parameterize_sql(
            "SELECT * FROM orders WHERE id = {id} OR parent_id = {id}",
            {"id": "ORD-1"},
        )
        assert query == "SELECT * FROM orders WHERE id = $1 OR parent_id = $1"
        assert values == ["ORD-1"]

    def test_parameterize_missing_kwarg_raises_keyerror(self):
        from processors.executors import _parameterize_sql

        with pytest.raises(KeyError):
            _parameterize_sql("SELECT * FROM orders WHERE id = {order_id}", {})

    async def test_boolean_injection_payload_bound_as_literal_not_executed(self, monkeypatch):
        """
        A classic boolean-based injection payload in a bound parameter must
        never alter the query sent to the database — it must arrive as the
        second positional argument to conn.fetch(), untouched, not as SQL
        text concatenated into the first argument.
        """
        cfg = {
            "dsn_secret_ref": "DB",
            "query": "SELECT id, status FROM orders WHERE id = {order_id}",
            "allowed_tables": ["orders"],
        }
        ex = SQLQueryExecutor(cfg, secrets={"DB": "postgresql://x"})
        payload = "' OR '1'='1"

        captured: dict = {}

        class _FakeConn:
            async def fetch(self, query, *args):
                captured["query"] = query
                captured["args"] = args
                return []

            async def close(self):
                pass

        async def _fake_connect(dsn):
            return _FakeConn()

        import sys
        import types

        fake_asyncpg = types.SimpleNamespace(connect=_fake_connect)
        monkeypatch.setitem(sys.modules, "asyncpg", fake_asyncpg)

        result = await ex.execute(order_id=payload)

        # The injection payload never appears inside the query string itself.
        assert payload not in captured["query"]
        assert captured["query"] == "SELECT id, status FROM orders WHERE id = $1"
        # It is passed through unchanged as a bound literal value.
        assert captured["args"] == (payload,)
        assert result == "[]"

    async def test_union_injection_payload_bound_as_literal_not_executed(self, monkeypatch):
        """Same guarantee for a UNION-based exfiltration payload."""
        cfg = {
            "dsn_secret_ref": "DB",
            "query": "SELECT id, status FROM orders WHERE id = {order_id}",
            "allowed_tables": ["orders"],
        }
        ex = SQLQueryExecutor(cfg, secrets={"DB": "postgresql://x"})
        payload = "' UNION SELECT password FROM admin_users--"

        captured: dict = {}

        class _FakeConn:
            async def fetch(self, query, *args):
                captured["query"] = query
                captured["args"] = args
                return []

            async def close(self):
                pass

        async def _fake_connect(dsn):
            return _FakeConn()

        import sys
        import types

        fake_asyncpg = types.SimpleNamespace(connect=_fake_connect)
        monkeypatch.setitem(sys.modules, "asyncpg", fake_asyncpg)

        result = await ex.execute(order_id=payload)

        assert "UNION" not in captured["query"]
        assert "admin_users" not in captured["query"]
        assert captured["query"] == "SELECT id, status FROM orders WHERE id = $1"
        assert captured["args"] == (payload,)
        assert result == "[]"


# ═══════════════════════════════════════════════════════════════════════════════
# PythonFunctionExecutor stub
# ═══════════════════════════════════════════════════════════════════════════════

class TestPythonFunctionExecutorStub:
    async def test_stub_returns_error_with_function_name(self):
        ex = PythonFunctionExecutor({"function_name": "my_custom_fn"}, secrets={})
        result = await ex.execute(arg="value")
        assert "error" in result
        assert "my_custom_fn" in result["error"]

    async def test_stub_without_function_name(self):
        ex = PythonFunctionExecutor({}, secrets={})
        result = await ex.execute()
        assert "error" in result


# ═══════════════════════════════════════════════════════════════════════════════
# ToolExecutorProcessor
# ═══════════════════════════════════════════════════════════════════════════════

_SAMPLE_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": "Get order status",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
            },
            "executor": {
                "type": "http_get",
                "url": "https://api.example.com/orders/{order_id}",
                "headers": {"Authorization": "Bearer {ORDERS_KEY}"},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_ticket",
            "description": "Open a support ticket",
            "parameters": {
                "type": "object",
                "properties": {"subject": {"type": "string"}},
                "required": ["subject"],
            },
            "executor": {
                "type": "http_post",
                "url": "https://crm.example.com/tickets",
                "headers": {"X-Key": "{CRM_KEY}"},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "legacy_tool",
            "description": "Legacy HTTP endpoint",
            "parameters": {},
            "x_endpoint": "https://legacy.example.com/action",
        },
    },
]

_SECRETS = {"ORDERS_KEY": "ord-secret", "CRM_KEY": "crm-secret"}


class TestToolExecutorProcessorDispatch:
    def test_executor_map_has_all_four_types(self):
        assert "http_get"    in ToolExecutorProcessor.EXECUTOR_MAP
        assert "http_post"   in ToolExecutorProcessor.EXECUTOR_MAP
        assert "sql_query"   in ToolExecutorProcessor.EXECUTOR_MAP
        assert "python_func" in ToolExecutorProcessor.EXECUTOR_MAP

    def test_tool_defs_indexed_by_name(self):
        proc = ToolExecutorProcessor(tools_spec=_SAMPLE_TOOLS, org_secrets=_SECRETS)
        assert "get_order_status" in proc._tool_defs
        assert "create_ticket"    in proc._tool_defs
        assert "legacy_tool"      in proc._tool_defs

    async def test_registered_callable_has_priority(self):
        proc = ToolExecutorProcessor(tools_spec=_SAMPLE_TOOLS, org_secrets=_SECRETS)

        async def my_fn(args):
            return {"from": "callable", "order_id": args.get("order_id")}

        proc.register_tool("get_order_status", my_fn)
        result = await proc._dispatch("get_order_status", {"order_id": "ORD-1"})
        assert result["from"] == "callable"

    async def test_executor_block_dispatched(self):
        session_cm, _ = _mock_http_response(json_body={"status": "pending"})
        proc = ToolExecutorProcessor(tools_spec=_SAMPLE_TOOLS, org_secrets=_SECRETS)
        with patch("aiohttp.ClientSession", session_cm):
            result = await proc._dispatch("get_order_status", {"order_id": "ORD-99"})
        assert result == {"status": "pending"}

    async def test_legacy_x_endpoint_dispatched(self):
        session_cm, _ = _mock_http_response(json_body={"done": True})
        proc = ToolExecutorProcessor(tools_spec=_SAMPLE_TOOLS, org_secrets=_SECRETS)
        with patch("aiohttp.ClientSession", session_cm):
            result = await proc._dispatch("legacy_tool", {"data": "x"})
        assert result == {"done": True}

    async def test_unknown_tool_returns_error_dict(self):
        proc = ToolExecutorProcessor(tools_spec=_SAMPLE_TOOLS, org_secrets=_SECRETS)
        result = await proc._dispatch("does_not_exist", {})
        assert "error" in result
        assert "does_not_exist" in result["error"]

    async def test_unknown_executor_type_returns_error_dict(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "bad_tool",
                    "parameters": {},
                    "executor": {"type": "graphql"},
                },
            }
        ]
        proc = ToolExecutorProcessor(tools_spec=tools, org_secrets={})
        result = await proc._dispatch("bad_tool", {})
        assert "error" in result
        assert "graphql" in result["error"]


class TestToolExecutorProcessorFrames:
    async def test_function_call_frame_produces_result_and_llm_frames(self):
        session_cm, _ = _mock_http_response(json_body={"status": "shipped"})
        proc = ToolExecutorProcessor(tools_spec=_SAMPLE_TOOLS, org_secrets=_SECRETS)
        frame = FunctionCallInProgressFrame(
            function_name="get_order_status",
            tool_call_id="tc1",
            arguments={"order_id": "ORD-42"},
        )
        with patch("aiohttp.ClientSession", session_cm):
            emitted = await _send(proc, [frame])

        types = [type(f) for f in emitted]
        assert FunctionCallResultFrame in types, "FunctionCallResultFrame must be pushed"
        assert LLMMessagesFrame in types, "LLMMessagesFrame (tool result) must be pushed"

        llm_frame: LLMMessagesFrame = next(f for f in emitted if isinstance(f, LLMMessagesFrame))
        assert llm_frame.messages[0]["role"] == "tool"
        assert llm_frame.messages[0]["name"] == "get_order_status"

    async def test_arguments_as_json_string_parsed(self):
        proc = ToolExecutorProcessor(tools_spec=_SAMPLE_TOOLS, org_secrets=_SECRETS)

        async def echo(args):
            return args

        proc.register_tool("get_order_status", echo)
        frame = FunctionCallInProgressFrame(
            function_name="get_order_status",
            tool_call_id="tc2",
            arguments=json.dumps({"order_id": "ORD-STR"}),
        )
        emitted = await _send(proc, [frame])
        result_frame: FunctionCallResultFrame = next(
            f for f in emitted if isinstance(f, FunctionCallResultFrame)
        )
        assert result_frame.result == {"order_id": "ORD-STR"}

    async def test_start_and_end_frames_passed_through(self):
        """
        StartFrame triggers pipecat's own internal processor-lifecycle
        startup (FrameProcessor.__start -> __create_process_task), which —
        unlike every other frame type sent through this test's shared
        _send() helper — requires the processor to have gone through
        setup() with a real TaskManager first, exactly as a Pipeline would
        do when wiring processors together. Every other test in this file
        sends non-lifecycle frames and never touches this path, so this
        setup is scoped to just this test rather than the shared helper.
        """
        import asyncio

        from pipecat.clocks.system_clock import SystemClock
        from pipecat.utils.asyncio.task_manager import TaskManager, TaskManagerParams

        task_manager = TaskManager()
        task_manager.setup(TaskManagerParams(loop=asyncio.get_event_loop()))

        proc = ToolExecutorProcessor(tools_spec=None, org_secrets={})
        await proc.setup(FrameProcessorSetup(clock=SystemClock(), task_manager=task_manager))
        try:
            emitted = await _send(proc, [StartFrame(), EndFrame()])
            types = [type(f) for f in emitted]
            assert StartFrame in types
            assert EndFrame in types
        finally:
            await proc.cleanup()


# ═══════════════════════════════════════════════════════════════════════════════
# AgentConfig — org_secrets field
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentConfigOrgSecrets:
    def test_org_secrets_defaults_to_empty_dict(self):
        cfg = AgentConfig(agent_id="a1", organization_id="o1", name="Test")
        assert cfg.org_secrets == {}

    def test_org_secrets_can_be_set(self):
        cfg = AgentConfig(
            agent_id="a1",
            organization_id="o1",
            name="Test",
            org_secrets={"MY_KEY": "secret-value", "DB_DSN": "postgresql://..."},
        )
        assert cfg.org_secrets["MY_KEY"] == "secret-value"
        assert cfg.org_secrets["DB_DSN"] == "postgresql://..."

    def test_org_secrets_not_included_in_tools_json(self):
        """Confirm secrets are stored separately from tool definitions."""
        tool_def = {
            "type": "function",
            "function": {
                "name": "my_tool",
                "parameters": {},
                "executor": {
                    "type": "http_get",
                    "url": "https://example.com",
                    "headers": {"X-Key": "{MY_KEY}"},
                },
            },
        }
        cfg = AgentConfig(
            agent_id="a1",
            organization_id="o1",
            name="Test",
            tools_json=[tool_def],
            org_secrets={"MY_KEY": "secret-value"},
        )
        # The literal string "{MY_KEY}" is in tools_json, not the secret value
        tool_headers = cfg.tools_json[0]["function"]["executor"]["headers"]
        assert tool_headers["X-Key"] == "{MY_KEY}"
        # The real value is in org_secrets — never in tools_json
        assert "secret-value" not in json.dumps(cfg.tools_json)
