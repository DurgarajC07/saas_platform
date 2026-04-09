"""
Tool executor backends for ToolExecutorProcessor.

Each executor corresponds to a ``tools_json`` entry's ``executor.type`` field:

    http_get      —  GET request; URL/header values support ``{param}`` and
                     ``{SECRET_NAME}`` token substitution.
    http_post     —  POST request; JSON body template filled from call kwargs.
    sql_query     —  Read-only asyncpg query: allowlist guard + DDL/DML block.
    python_func   —  Delegates to a callable registered via
                     ``ToolExecutorProcessor.register_tool()``.

Tool definition ``executor`` block example
------------------------------------------
::

    "executor": {
        "type": "http_get",
        "url": "https://api.acme.com/orders/{order_id}",
        "headers": { "Authorization": "Bearer {ACME_API_KEY}" }
    }

Secret injection
----------------
``org_secrets`` is a dict of **pre-decrypted** key-value pairs supplied by the
platform at session-creation time.  ``{KEY}`` placeholders in URLs and header
values are resolved from this dict — secrets are never stored in ``tools_json``
or written to logs.

SQL security model
------------------
* Only SELECT statements are accepted; any DDL / DML keyword triggers an
  immediate rejection with a human-readable error.
* An ``allowed_tables`` list (recommended) constrains which tables the
  LLM-generated SQL may reference.  An empty list skips the table check.
* Results are capped at ``max_rows`` (default 10) to prevent runaway queries.
* The PostgreSQL DSN is referenced via ``dsn_secret_ref`` (an ``org_secrets``
  key) so the real connection string never appears in ``tools_json``.
"""

from __future__ import annotations

import asyncio
import json
import re
from abc import ABC, abstractmethod
from typing import Any

import aiohttp
import structlog

log = structlog.get_logger(__name__)

# ── SQL safety patterns ────────────────────────────────────────────────────────

_UNSAFE_SQL_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|EXEC|EXECUTE|"
    r"GRANT|REVOKE|MERGE|REPLACE|CALL|DO|PRAGMA|COPY)\b",
    re.IGNORECASE,
)

# Capture table names that appear after FROM or JOIN keywords
_TABLE_REF_RE = re.compile(r"\b(?:FROM|JOIN)\s+(\w+)", re.IGNORECASE)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _inject_secrets(template: str, secrets: dict[str, str]) -> str:
    """
    Replace ``{KEY}`` placeholders in *template* with values from *secrets*.

    Placeholders with no matching key are kept verbatim (safe substitution).
    """
    result = template
    for key, value in secrets.items():
        result = result.replace(f"{{{key}}}", value)
    return result


# ── Base executor ─────────────────────────────────────────────────────────────

class BaseExecutor(ABC):
    """
    Abstract base class for all tool executor backends.

    Parameters
    ----------
    config:
        The ``executor`` block from the tool definition (``type`` key removed
        before passing here — it is already consumed by the factory dispatch).
    secrets:
        Pre-decrypted org-level secrets.  ``{KEY}`` tokens in config string
        values are resolved from this mapping at execution time.
    """

    def __init__(
        self,
        config: dict[str, Any],
        secrets: dict[str, str] | None = None,
    ) -> None:
        self._config = config
        self._secrets: dict[str, str] = secrets or {}

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        """Execute the tool and return a JSON-serialisable result."""
        ...

    # ── Protected helpers ────────────────────────────────────────────────────

    def _resolve(self, value: str) -> str:
        """Resolve secret placeholders in a string value."""
        return _inject_secrets(value, self._secrets)

    def _resolve_url(self, url_template: str, **kwargs: Any) -> str:
        """
        Fill URL path parameters from call kwargs **after** resolving secrets.

        Order:
          1. Resolve ``{SECRET_NAME}`` tokens from ``self._secrets``.
          2. Replace ``{param}`` tokens with tool-call argument values.
        """
        url = self._resolve(url_template)
        for key, val in kwargs.items():
            url = url.replace(f"{{{key}}}", str(val))
        return url

    def _resolve_headers(self, raw: dict[str, str]) -> dict[str, str]:
        """Resolve secret placeholders in all header values."""
        return {k: self._resolve(v) for k, v in raw.items()}


# ── HTTP GET executor ─────────────────────────────────────────────────────────

class HTTPGetExecutor(BaseExecutor):
    """
    Execute an HTTP GET request.

    ``executor`` config keys
    ------------------------
    url      (required) — URL template; ``{param}`` tokens filled from call
                          arguments; ``{SECRET_NAME}`` tokens from secrets.
    headers  (optional) — dict of header name → value; secret-injection applied.
    timeout  (optional) — total request timeout in seconds (default 10).

    Example
    -------
    ::

        "executor": {
            "type": "http_get",
            "url": "https://api.example.com/orders/{order_id}",
            "headers": { "Authorization": "Bearer {ORDERS_API_KEY}" },
            "timeout": 5
        }
    """

    async def execute(self, **kwargs: Any) -> Any:
        url = self._resolve_url(self._config["url"], **kwargs)
        headers = self._resolve_headers(self._config.get("headers", {}))
        timeout = aiohttp.ClientTimeout(total=self._config.get("timeout", 10))

        log.debug("http_get.executing", url=url)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.content_type and "json" in resp.content_type:
                        return await resp.json()
                    return {"result": await resp.text(), "status": resp.status}
        except asyncio.TimeoutError:
            return {"error": f"HTTP GET timed out after {timeout.total}s (url={url})"}
        except aiohttp.ClientError as exc:
            log.error("http_get.failed", url=url, error=str(exc))
            return {"error": str(exc)}


# ── HTTP POST executor ────────────────────────────────────────────────────────

class HTTPPostExecutor(BaseExecutor):
    """
    Execute an HTTP POST request with a JSON body.

    ``executor`` config keys
    ------------------------
    url      (required) — URL template (path params filled from call kwargs).
    headers  (optional) — Header map; secret-injection applied.
    body     (optional) — JSON body template: string values may contain
                          ``{param}`` placeholders filled from call kwargs.
                          If omitted, all call kwargs are sent as the body.
    timeout  (optional) — Default 10 s.

    Example
    -------
    ::

        "executor": {
            "type": "http_post",
            "url": "https://crm.example.com/api/cases",
            "headers": { "X-API-Key": "{CRM_API_KEY}" },
            "body": { "customer_id": "{customer_id}", "priority": "high" }
        }
    """

    async def execute(self, **kwargs: Any) -> Any:
        url = self._resolve_url(self._config["url"], **kwargs)
        headers = self._resolve_headers(self._config.get("headers", {}))
        timeout = aiohttp.ClientTimeout(total=self._config.get("timeout", 10))

        # Build request body from template or pass kwargs directly
        body_template = self._config.get("body")
        if body_template is not None:
            body: dict[str, Any] = {}
            for k, v in body_template.items():
                if isinstance(v, str):
                    filled = v
                    for arg_k, arg_v in kwargs.items():
                        filled = filled.replace(f"{{{arg_k}}}", str(arg_v))
                    body[k] = filled
                else:
                    body[k] = v
        else:
            body = dict(kwargs)

        log.debug("http_post.executing", url=url, body_keys=list(body.keys()))
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=body, headers=headers) as resp:
                    if resp.content_type and "json" in resp.content_type:
                        return await resp.json()
                    return {"result": await resp.text(), "status": resp.status}
        except asyncio.TimeoutError:
            return {"error": f"HTTP POST timed out after {timeout.total}s (url={url})"}
        except aiohttp.ClientError as exc:
            log.error("http_post.failed", url=url, error=str(exc))
            return {"error": str(exc)}


# ── SQL query executor ────────────────────────────────────────────────────────

class SQLQueryExecutor(BaseExecutor):
    """
    Execute a read-only SQL query against an external PostgreSQL database.

    Security model
    --------------
    * Only SELECT queries are permitted — any DDL/DML keyword causes an
      immediate rejection without touching the database.
    * An ``allowed_tables`` list (strongly recommended) constrains which tables
      the LLM-generated SQL may reference; tables found after ``FROM`` or
      ``JOIN`` that are not in the list are rejected.
    * Results are capped at ``max_rows`` (default: 10 rows).
    * The DSN is **never** stored in ``tools_json``.  Refer to it via
      ``dsn_secret_ref``; the actual value comes from ``org_secrets``.

    ``executor`` config keys
    ------------------------
    dsn_secret_ref   (required) — Key in ``org_secrets`` that holds the
                                  PostgreSQL DSN (e.g. ``"DB_DSN"``).
    query            (required) — SQL template; ``{param}`` placeholders
                                  filled from tool call arguments.
    allowed_tables   (optional) — Allowlist of table names.  Empty → no check.
    max_rows         (optional) — Row result cap (default 10).

    Example
    -------
    ::

        "executor": {
            "type": "sql_query",
            "dsn_secret_ref": "ORDERS_DB_DSN",
            "query": "SELECT id, status, updated_at FROM orders WHERE id = '{order_id}'",
            "allowed_tables": ["orders"],
            "max_rows": 5
        }
    """

    def _is_safe(self, query: str, allowed_tables: list[str]) -> tuple[bool, str]:
        """
        Return ``(is_safe, rejection_reason)``.

        Checks DDL/DML keywords first, then the table allowlist.
        """
        if _UNSAFE_SQL_RE.search(query):
            return False, "DDL/DML statements are not permitted"
        if allowed_tables:
            tables_used = set(_TABLE_REF_RE.findall(query))
            disallowed = tables_used - set(allowed_tables)
            if disallowed:
                return False, f"Table(s) not in allowlist: {sorted(disallowed)}"
        return True, ""

    async def execute(self, **kwargs: Any) -> Any:
        # 1. Resolve DSN from secrets — never from tools_json
        dsn_key = self._config.get("dsn_secret_ref", "")
        dsn = self._secrets.get(dsn_key, "")
        if not dsn:
            log.warning("sql.no_dsn", dsn_key=dsn_key)
            return {
                "error": (
                    "SQL executor: DSN secret not configured. "
                    f"Add '{dsn_key}' to org_secrets."
                )
            }

        # 2. Fill query template
        query_template = self._config.get("query", "")
        try:
            query = query_template.format(**kwargs)
        except KeyError as exc:
            return {"error": f"SQL query missing required parameter: {exc}"}

        # 3. Security checks
        allowed_tables: list[str] = self._config.get("allowed_tables", [])
        safe, reason = self._is_safe(query, allowed_tables)
        if not safe:
            log.warning("sql.blocked", reason=reason, query=query[:200])
            return {"error": f"Query not permitted: {reason}"}

        # 4. Execute
        max_rows: int = self._config.get("max_rows", 10)
        try:
            import asyncpg  # deferred import — only required when SQL executor is used
            conn = await asyncpg.connect(dsn)
            try:
                rows = await conn.fetch(query)
                result = [dict(r) for r in rows[:max_rows]]
                log.info("sql.executed", row_count=len(result), table_hint=query[:60])
                return json.dumps(result)
            finally:
                await conn.close()
        except ImportError:
            return {"error": "asyncpg is not installed; cannot execute SQL queries"}
        except Exception as exc:
            log.error("sql.failed", error=str(exc))
            return {"error": f"SQL execution failed: {exc}"}


# ── Python function executor ──────────────────────────────────────────────────

class PythonFunctionExecutor(BaseExecutor):
    """
    Placeholder executor for ``python_func`` tool type.

    ``ToolExecutorProcessor._dispatch()`` checks ``self._callables`` *before*
    reaching this class, so a registered callable will always be invoked
    directly.  This stub is reached only when no callable is registered for the
    tool name — it returns a clear error message instead of silently failing.

    ``executor`` config keys
    ------------------------
    function_name — Name of the expected Python callable (informational only).

    To register a real Python function::

        processor.register_tool("my_func", my_async_fn)
    """

    async def execute(self, **kwargs: Any) -> Any:
        fn = self._config.get("function_name", "<unnamed>")
        log.warning("python_func.not_registered", function_name=fn)
        return {
            "error": (
                f"Python callable '{fn}' is not registered with this processor. "
                "Use processor.register_tool(name, async_fn) at session start."
            )
        }
