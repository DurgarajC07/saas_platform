#!/usr/bin/env python3
"""
Smoke Test — Tool Executor Framework (Day 11 deliverables).

Checks:
  ── API: Tools CRUD ──────────────────────────────────────────────────────────
  1   Login as platform admin
  2   Create org + agent
  3   PUT /agents/{id}/tools — store http_get tool definition
  4   GET /agents/{id} — tools_json round-trips correctly
  5   Executor block present in stored definition
  6   Executor type is http_get
  7   Secret placeholder preserved at rest (not expanded)
  8   PUT /agents/{id}/tools — replace with http_post + sql_query tools
  9   tools_json has 2 tools after replace
 10   http_post tool present after replace
 11   sql_query tool present after replace
 12   SQL tool uses dsn_secret_ref (not raw DSN)
 13   PUT /agents/{id}/tools — clear (empty list)
 14   tools_json empty after clear

  ── SQL Executor: Security Model ─────────────────────────────────────────────
 15   SELECT on allowlisted table → passes
 16   INSERT statement → blocked (DDL/DML guard)
 17   UPDATE statement → blocked
 18   DROP statement → blocked
 19   TRUNCATE statement → blocked
 20   Table not in allowlist → blocked with clear reason
 21   Empty allowlist → any table allowed (unrestricted mode)
 22   Missing DSN secret → error dict, no crash
 23   Missing SQL parameter → error dict, no crash

  ── HTTP Executor: Secret Injection ──────────────────────────────────────────
 24   _inject_secrets resolves {KEY} from secrets dict
 25   _inject_secrets leaves unknown {KEY} verbatim

  ── HTTP GET Executor (mocked network) ───────────────────────────────────────
 26   GET result returned from mocked response
 27   GET URL template filled with call kwarg
 28   GET header secret injected

  ── HTTP POST Executor (mocked network) ──────────────────────────────────────
 29   POST result returned from mocked response
 30   POST body template filled from kwargs
 31   POST body static value preserved

  ── ToolExecutorProcessor Dispatch ───────────────────────────────────────────
 32   EXECUTOR_MAP has all 4 required types
 33   Registered Python callable dispatched with top priority
 34   Unknown tool name → error dict, no crash

Run:
    python scripts/smoke_test_tool_executor.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import requests

# ── Pipeline service on sys.path ──────────────────────────────────────────────
_PIPELINE_SRC = Path(__file__).parent.parent / "services" / "pipeline"
sys.path.insert(0, str(_PIPELINE_SRC))
sys.path.insert(0, str(_PIPELINE_SRC / "processors"))


# ── Lightweight pipecat stubs (not in the platform venv) ─────────────────────
def _stub_pipecat() -> None:
    import enum as _enum
    import types as _types
    from dataclasses import dataclass as _dc, field as _field
    from unittest.mock import MagicMock as _MM

    if "pipecat" in sys.modules:
        return  # real package installed (e.g. Docker)

    @_dc
    class Frame:
        pass

    @_dc
    class AudioRawFrame(Frame):
        audio: bytes = b""
        sample_rate: int = 16_000
        num_channels: int = 1

    @_dc
    class StartFrame(Frame):
        allow_interruptions: bool = False

    @_dc
    class EndFrame(Frame):
        pass

    @_dc
    class StartInterruptionFrame(Frame):
        pass

    @_dc
    class TranscriptionFrame(Frame):
        text: str = ""
        user_id: str = ""
        timestamp: str = ""

    @_dc
    class UserStartedSpeakingFrame(Frame):
        pass

    @_dc
    class LLMMessagesFrame(Frame):
        messages: list = _field(default_factory=list)

    @_dc
    class LLMFullResponseEndFrame(Frame):
        pass

    @_dc
    class FunctionCallInProgressFrame(Frame):
        function_name: str = ""
        arguments: Any = None
        tool_call_id: str = ""

    @_dc
    class FunctionCallResultFrame(Frame):
        function_name: str = ""
        arguments: Any = None
        result: Any = None
        tool_call_id: str = ""

    class FrameDirection(_enum.Enum):
        DOWNSTREAM = "downstream"
        UPSTREAM = "upstream"

    class FrameProcessor:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def push_frame(self, frame: Any, direction: Any = None) -> None:
            pass

        async def process_frame(self, frame: Any, direction: Any = None) -> None:
            pass

    pipecat = _types.ModuleType("pipecat")
    pc_frames = _types.ModuleType("pipecat.frames")
    pc_fr_fr = _types.ModuleType("pipecat.frames.frames")
    for _cls in [
        Frame, AudioRawFrame, StartFrame, EndFrame, StartInterruptionFrame,
        TranscriptionFrame, UserStartedSpeakingFrame, LLMMessagesFrame,
        LLMFullResponseEndFrame, FunctionCallInProgressFrame, FunctionCallResultFrame,
    ]:
        setattr(pc_fr_fr, _cls.__name__, _cls)

    pc_proc = _types.ModuleType("pipecat.processors")
    pc_proc_fp = _types.ModuleType("pipecat.processors.frame_processor")
    pc_proc_fp.FrameDirection = FrameDirection
    pc_proc_fp.FrameProcessor = FrameProcessor

    for _submod in ("pipeline", "runner", "task"):
        _m = _types.ModuleType(f"pipecat.pipeline.{_submod}")
        for _attr in ("Pipeline", "PipelineRunner", "PipelineParams", "PipelineTask"):
            setattr(_m, _attr, _MM)
        sys.modules[f"pipecat.pipeline.{_submod}"] = _m

    _m_fastapi = _types.ModuleType("pipecat.transports.websocket.fastapi")
    _m_fastapi.FastAPIWebsocketTransport = _MM
    _m_fastapi.FastAPIWebsocketParams = _MM
    _m_silero = _types.ModuleType("pipecat.audio.vad.silero")
    _m_silero.SileroVADAnalyzer = _MM
    _m_vad = _types.ModuleType("pipecat.audio.vad.vad_analyzer")

    class _VADState(_enum.Enum):
        QUIET = "quiet"
        SPEAKING = "speaking"

    _m_vad.VADState = _VADState
    _m_serial = _types.ModuleType("pipecat.serializers.base_serializer")
    _m_serial.FrameSerializer = _MM

    sys.modules.update({
        "pipecat": pipecat,
        "pipecat.frames": pc_frames,
        "pipecat.frames.frames": pc_fr_fr,
        "pipecat.processors": pc_proc,
        "pipecat.processors.frame_processor": pc_proc_fp,
        "pipecat.pipeline": _types.ModuleType("pipecat.pipeline"),
        "pipecat.audio": _types.ModuleType("pipecat.audio"),
        "pipecat.audio.vad": _types.ModuleType("pipecat.audio.vad"),
        "pipecat.audio.vad.vad_analyzer": _m_vad,
        "pipecat.audio.vad.silero": _m_silero,
        "pipecat.transports": _types.ModuleType("pipecat.transports"),
        "pipecat.transports.websocket": _types.ModuleType("pipecat.transports.websocket"),
        "pipecat.transports.websocket.fastapi": _m_fastapi,
        "pipecat.serializers": _types.ModuleType("pipecat.serializers"),
        "pipecat.serializers.base_serializer": _m_serial,
    })


_stub_pipecat()

BASE = "http://127.0.0.1:8000/api/v1"
ADMIN_EMAIL = "admin@test.com"
ADMIN_PASSWORD = "TestPass123!"

PASS_SYM = "\033[92m✓\033[0m"
FAIL_SYM = "\033[91m✗\033[0m"

ok = errors = 0
_RUN_ID = uuid.uuid4().hex[:6]

# ── Sample tool definitions ───────────────────────────────────────────────────

_HTTP_GET_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "get_order_status",
        "description": "Look up order status by order ID",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
        "executor": {
            "type": "http_get",
            "url": "https://api.acme.com/orders/{order_id}",
            "headers": {"Authorization": "Bearer {ACME_API_KEY}"},
        },
    },
}

_HTTP_POST_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "create_support_ticket",
        "description": "Open a support ticket",
        "parameters": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "priority": {"type": "string"},
            },
            "required": ["subject"],
        },
        "executor": {
            "type": "http_post",
            "url": "https://crm.acme.com/api/tickets",
            "headers": {"X-API-Key": "{CRM_API_KEY}"},
            "body": {"subject": "{subject}", "priority": "{priority}"},
        },
    },
}

_SQL_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "get_customer_info",
        "description": "Fetch customer record",
        "parameters": {
            "type": "object",
            "properties": {"customer_id": {"type": "string"}},
            "required": ["customer_id"],
        },
        "executor": {
            "type": "sql_query",
            "dsn_secret_ref": "CRM_DB_DSN",
            "query": "SELECT id, name, email FROM customers WHERE id = '{customer_id}'",
            "allowed_tables": ["customers"],
            "max_rows": 1,
        },
    },
}

# ── Formatting helpers ────────────────────────────────────────────────────────


def check(label: str, cond: bool, detail: str = "") -> None:
    global ok, errors
    sym = PASS_SYM if cond else FAIL_SYM
    suffix = f"  ({detail})" if detail else ""
    print(f"  {sym}  {label}{suffix}")
    if cond:
        ok += 1
    else:
        errors += 1
        print(f"       ↳ FAILED: {detail if detail else 'condition was False'}")


# ── API helpers ───────────────────────────────────────────────────────────────


def login(email: str, password: str) -> str:
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"Login failed ({r.status_code}): {r.text}"
    return r.json()["accessToken"]


def hdr(token: str, org_id: str | None = None) -> dict:
    h = {"Authorization": f"Bearer {token}"}
    if org_id:
        h["X-Organization-ID"] = org_id
    return h


def create_org(token: str) -> str:
    slug = f"tools-org-{_RUN_ID}"
    r = requests.post(
        f"{BASE}/organizations",
        headers=hdr(token),
        json={"name": f"Tools Org {_RUN_ID}", "slug": slug, "plan": "trial"},
    )
    assert r.status_code in (200, 201), f"Create org failed: {r.text}"
    return r.json()["id"]


def create_agent(token: str, org_id: str) -> str:
    r = requests.post(
        f"{BASE}/agents",
        headers=hdr(token, org_id),
        json={
            "name": f"Tools Agent {_RUN_ID}",
            "slug": f"tools-agent-{_RUN_ID}",
            "agent_type": "rag_bot",
            "system_prompt": "Use tools when asked.",
            "llm_model": "gpt-4o-mini",
        },
    )
    assert r.status_code == 201, f"Create agent failed ({r.status_code}): {r.text}"
    return r.json()["id"]


def put_tools(token: str, org_id: str, agent_id: str, tools: list) -> requests.Response:
    return requests.put(
        f"{BASE}/agents/{agent_id}/tools",
        headers=hdr(token, org_id),
        json={"toolsJson": tools},  # CamelModel: tools_json → toolsJson
        timeout=15,
    )


def get_agent(token: str, org_id: str, agent_id: str) -> dict:
    r = requests.get(f"{BASE}/agents/{agent_id}", headers=hdr(token, org_id), timeout=10)
    assert r.status_code == 200, f"Get agent failed: {r.text}"
    return r.json()


def stored_tools(agent: dict) -> list:
    """Accept both camelCase and snake_case response keys."""
    return agent.get("toolsJson") or agent.get("tools_json") or []


# ── Mock HTTP helper ──────────────────────────────────────────────────────────


def _mock_http(json_body: dict) -> tuple[Any, Any]:
    resp = MagicMock()
    resp.status = 200
    resp.content_type = "application/json"
    resp.json = AsyncMock(return_value=json_body)
    resp.text = AsyncMock(return_value=json.dumps(json_body))

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


# ── API Tests ─────────────────────────────────────────────────────────────────


def run_api_tests() -> None:
    print("\n── Auth + Setup ──")
    token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    check("Login → JWT obtained", bool(token))

    org_id = create_org(token)
    check("Org created", bool(org_id), org_id)

    agent_id = create_agent(token, org_id)
    check("Agent created", bool(agent_id), agent_id)

    print("\n── Tools CRUD ──")

    # Store single http_get tool
    r = put_tools(token, org_id, agent_id, [_HTTP_GET_TOOL])
    check("PUT /agents/{id}/tools (http_get)", r.status_code == 200, f"status={r.status_code}")

    agent = get_agent(token, org_id, agent_id)
    tools = stored_tools(agent)
    check("tools_json round-trips via API", len(tools) == 1, f"count={len(tools)}")

    if tools:
        fn = tools[0].get("function", {})
        check("Tool name preserved", fn.get("name") == "get_order_status", fn.get("name"))

        executor = fn.get("executor", {})
        check("Executor block present in stored definition", bool(executor))
        check("Executor type is http_get", executor.get("type") == "http_get", executor.get("type"))

        header_val = executor.get("headers", {}).get("Authorization", "")
        check(
            "Secret placeholder {ACME_API_KEY} preserved at rest",
            "{ACME_API_KEY}" in header_val,
            f"header={header_val!r}",
        )

    # Replace with two tools
    r = put_tools(token, org_id, agent_id, [_HTTP_POST_TOOL, _SQL_TOOL])
    check("PUT /agents/{id}/tools — replace with 2 tools", r.status_code == 200, f"status={r.status_code}")

    agent = get_agent(token, org_id, agent_id)
    tools = stored_tools(agent)
    check("tools_json has 2 tools after replace", len(tools) == 2, f"count={len(tools)}")

    tool_names = {t.get("function", {}).get("name") for t in tools}
    check("http_post tool present", "create_support_ticket" in tool_names, str(tool_names))
    check("sql_query tool present", "get_customer_info" in tool_names, str(tool_names))

    sql_t = next((t for t in tools if t.get("function", {}).get("name") == "get_customer_info"), None)
    if sql_t:
        sql_ex = sql_t.get("function", {}).get("executor", {})
        check(
            "SQL tool uses dsn_secret_ref (not raw DSN)",
            "dsn_secret_ref" in sql_ex and "dsn" not in sql_ex,
            str(sql_ex),
        )

    # Clear
    r = put_tools(token, org_id, agent_id, [])
    check("PUT /agents/{id}/tools — clear", r.status_code == 200, f"status={r.status_code}")

    agent = get_agent(token, org_id, agent_id)
    tools = stored_tools(agent)
    check("tools_json empty after clear", len(tools) == 0, f"count={len(tools)}")


# ── Executor Unit Tests ───────────────────────────────────────────────────────


async def run_executor_tests_async() -> None:
    from processors.executors import (
        HTTPGetExecutor,
        HTTPPostExecutor,
        SQLQueryExecutor,
        _inject_secrets,
    )
    from processors.tools import ToolExecutorProcessor

    # ── SQL Security Model ────────────────────────────────────────────────────
    print("\n── SQL Executor: Security Model ──")

    def sql_ex(query: str, allowed: list[str] | None = None) -> SQLQueryExecutor:
        cfg: dict[str, Any] = {"dsn_secret_ref": "DSN", "query": query}
        if allowed is not None:
            cfg["allowed_tables"] = allowed
        return SQLQueryExecutor(cfg, secrets={"DSN": "postgresql://u:p@db/test"})

    safe, _ = sql_ex("SELECT id FROM orders", ["orders"])._is_safe(
        "SELECT id FROM orders", ["orders"]
    )
    check("SELECT on allowlisted table → passes", safe is True)

    safe, reason = sql_ex("X", [])._is_safe("INSERT INTO orders VALUES (1)", [])
    check("INSERT → blocked (DDL/DML guard)", not safe and "DDL/DML" in reason, reason)

    safe, reason = sql_ex("X", [])._is_safe("UPDATE orders SET status='x'", [])
    check("UPDATE → blocked", not safe, reason)

    safe, reason = sql_ex("X", [])._is_safe("DROP TABLE users", [])
    check("DROP → blocked", not safe, reason)

    safe, reason = sql_ex("X", [])._is_safe("TRUNCATE audit_logs", [])
    check("TRUNCATE → blocked", not safe, reason)

    safe, reason = sql_ex("X", ["orders"])._is_safe("SELECT * FROM users", ["orders"])
    check("Table not in allowlist → blocked", not safe and "allowlist" in reason.lower(), reason)

    safe, _ = sql_ex("X", [])._is_safe("SELECT * FROM anything", [])
    check("Empty allowlist → any table allowed", safe is True)

    result = await SQLQueryExecutor(
        {"dsn_secret_ref": "MISSING", "query": "SELECT 1"}, secrets={}
    ).execute()
    check("Missing DSN → error dict, no crash", "error" in result, str(result)[:80])

    result = await sql_ex(
        "SELECT * FROM orders WHERE id = '{order_id}'", ["orders"]
    ).execute()  # order_id kwarg not passed
    check("Missing SQL param → error dict, no crash", "error" in result, str(result)[:80])

    # ── Secret Injection ──────────────────────────────────────────────────────
    print("\n── HTTP Executor: Secret Injection ──")

    resolved = _inject_secrets("Bearer {KEY}", {"KEY": "tok-123"})
    check("_inject_secrets resolves {KEY}", resolved == "Bearer tok-123", resolved)

    resolved = _inject_secrets("Bearer {UNKNOWN}", {"OTHER": "x"})
    check("_inject_secrets leaves unknown {KEY} verbatim", resolved == "Bearer {UNKNOWN}", resolved)

    # ── HTTP GET (mocked) ─────────────────────────────────────────────────────
    print("\n── HTTP GET Executor (mocked) ──")

    session_cm, session = _mock_http({"status": "shipped", "order_id": "ORD-123"})
    ex_get = HTTPGetExecutor(
        {
            "url": "https://api.acme.com/orders/{order_id}",
            "headers": {"Auth": "Bearer {KEY}"},
        },
        secrets={"KEY": "secret-tok"},
    )
    with patch("aiohttp.ClientSession", session_cm):
        result = await ex_get.execute(order_id="ORD-123")

    check("GET result returned from mocked response", result.get("status") == "shipped", str(result))

    call_url = session.get.call_args[0][0] if session.get.call_args else ""
    check("GET URL template filled with kwarg", "ORD-123" in call_url, call_url)

    call_headers = session.get.call_args[1].get("headers", {}) if session.get.call_args else {}
    check("GET header secret injected", call_headers.get("Auth") == "Bearer secret-tok", str(call_headers))

    # ── HTTP POST (mocked) ────────────────────────────────────────────────────
    print("\n── HTTP POST Executor (mocked) ──")

    session_cm, session = _mock_http({"ticket_id": "T-99"})
    ex_post = HTTPPostExecutor(
        {
            "url": "https://crm.acme.com/tickets",
            "body": {"subject": "{subject}", "priority": "normal"},
        },
        secrets={},
    )
    with patch("aiohttp.ClientSession", session_cm):
        result = await ex_post.execute(subject="Billing issue")

    check("POST result returned from mocked response", result.get("ticket_id") == "T-99", str(result))

    body_sent = session.post.call_args[1].get("json", {}) if session.post.call_args else {}
    check("POST body template filled from kwargs", body_sent.get("subject") == "Billing issue", str(body_sent))
    check("POST body static value preserved", body_sent.get("priority") == "normal", str(body_sent))

    # ── ToolExecutorProcessor Dispatch ───────────────────────────────────────
    print("\n── ToolExecutorProcessor Dispatch ──")

    tools_spec = [
        {
            "type": "function",
            "function": {
                "name": "get_order_status",
                "parameters": {},
                "executor": {
                    "type": "http_get",
                    "url": "https://api.acme.com/orders/{order_id}",
                },
            },
        }
    ]
    proc = ToolExecutorProcessor(tools_spec=tools_spec, org_secrets={"KEY": "val"})

    check(
        "EXECUTOR_MAP has all 4 types",
        all(k in proc.EXECUTOR_MAP for k in ("http_get", "http_post", "sql_query", "python_func")),
    )

    async def my_fn(arguments):  # _dispatch passes arguments dict as positional arg
        return {"from": "callable"}

    proc.register_tool("get_order_status", my_fn)
    result = await proc._dispatch("get_order_status", {"order_id": "X"})
    check(
        "Registered callable dispatched with top priority",
        result.get("from") == "callable",
        str(result),
    )

    result = await proc._dispatch("does_not_exist", {})
    check("Unknown tool → error dict, no crash", "error" in result, str(result)[:80])


def run_executor_tests() -> None:
    asyncio.run(run_executor_tests_async())


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    print(f"\n━━━━  Smoke Test: Tool Executor Framework  (run={_RUN_ID})  ━━━━")

    run_api_tests()
    run_executor_tests()

    total = ok + errors
    print(f"\n━━━━  {ok}/{total} checks passed  ━━━━\n")
    sys.exit(0 if errors == 0 else 1)


if __name__ == "__main__":
    main()
