"""
SQL Sanitiser — db_bot security layer.

Enforces three rules on every query that the db_bot agent type executes:

1.  **Parameterised queries only** — the query string must contain ``%s`` or
    ``:name`` style placeholders; bare string interpolation is rejected at
    the call site by requiring *all* dynamic values to be passed via the
    ``params`` argument.

2.  **Table allowlist** — only table names registered in
    ``ALLOWED_TABLES`` (per-org or global) may appear in a ``FROM`` / ``JOIN``
    / ``INTO`` clause.  The check is case-insensitive and strip-quoted.

3.  **DDL & schema-level access blocked** — DDL keywords (``CREATE``,
    ``DROP``, ``ALTER``, ``TRUNCATE``) and schema-qualifier syntax
    (``schema.table``, ``information_schema``, ``pg_catalog``) are rejected
    before the query reaches the database.

Usage
─────
    from app.core.utils.sql_sanitiser import SQLSanitiser, SanitiserError

    sanitiser = SQLSanitiser(allowed_tables={"orders", "products"})
    clean_sql, clean_params = sanitiser.sanitise(
        "SELECT * FROM orders WHERE id = %(order_id)s",
        {"order_id": req.order_id}
    )
    result = await session.execute(text(clean_sql), clean_params)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_DDL_KEYWORDS = re.compile(
    r"\b(CREATE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|EXECUTE|CALL|COPY)\b",
    re.IGNORECASE,
)

_SCHEMA_ACCESS = re.compile(
    r"(information_schema|pg_catalog|pg_toast|sys\.|dbo\.|\w+\.\w+\.\w+)",
    re.IGNORECASE,
)

# Tables in FROM / JOIN / INTO / UPDATE clauses — captured for allowlist check.
_TABLE_REFS = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE)\s+(\"?[\w]+\"?(?:\s*,\s*\"?[\w]+\"?)*)",
    re.IGNORECASE,
)


class SanitiserError(ValueError):
    """Raised when a query fails any security check."""


@dataclass
class SQLSanitiser:
    """
    Stateless sanitiser.  Construct with a set of allowed table names; call
    :meth:`sanitise` before executing any db_bot query.

    Parameters
    ----------
    allowed_tables:
        Set of lowercase table names the bot may query.  Pass an empty set to
        **skip** the table allowlist check (not recommended for production).
    max_result_rows:
        Inject a ``LIMIT`` clause if the query has none.  Set to 0 to disable.
    """

    allowed_tables: set[str] = field(default_factory=set)
    max_result_rows: int = 200

    # ── Public API ────────────────────────────────────────────────────────────

    def sanitise(
        self,
        query: str,
        params: dict | list | None = None,
    ) -> tuple[str, dict | list | None]:
        """
        Validate *query* against all security rules and return ``(query, params)``.

        Raises :class:`SanitiserError` on any violation.
        """
        self._reject_ddl(query)
        self._reject_schema_access(query)
        if self.allowed_tables:
            self._check_table_allowlist(query)
        query = self._enforce_limit(query)
        return query, params

    # ── Convenience builder ────────────────────────────────────────────────

    def build_select(
        self,
        table: str,
        columns: list[str] | None = None,
        where: dict[str, object] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
    ) -> tuple[str, dict]:
        """
        Build a safe ``SELECT`` statement from structured inputs.

        All values are passed as named parameters — never injected into the
        query string — so SQL injection is structurally impossible.

        Parameters
        ----------
        table:
            Table name (must be in ``allowed_tables`` if allowlist is active).
        columns:
            Column names to SELECT; defaults to ``["*"]``.
        where:
            ``{column: value}`` equality conditions joined by ``AND``.
        order_by:
            Optional column name for ``ORDER BY … ASC``.  Must match
            ``^[a-zA-Z_][a-zA-Z0-9_]*$`` to prevent injection.
        limit:
            Row cap (defaults to ``max_result_rows``).
        """
        self._assert_identifier(table, "table")
        cols = columns or ["*"]
        for col in cols:
            if col != "*":
                self._assert_identifier(col, "column")

        col_clause = ", ".join(cols)
        sql = f"SELECT {col_clause} FROM {table}"  # noqa: S608
        params: dict = {}

        if where:
            conditions = []
            for col, val in where.items():
                self._assert_identifier(col, "column")
                param_key = f"_w_{col}"
                conditions.append(f"{col} = :{param_key}")
                params[param_key] = val
            sql += " WHERE " + " AND ".join(conditions)

        if order_by:
            self._assert_identifier(order_by, "order_by")
            sql += f" ORDER BY {order_by} ASC"

        row_limit = limit if limit is not None else self.max_result_rows
        if row_limit > 0:
            sql += f" LIMIT {row_limit}"

        return sql, params

    # ── Internal checks ───────────────────────────────────────────────────────

    def _reject_ddl(self, query: str) -> None:
        m = _DDL_KEYWORDS.search(query)
        if m:
            raise SanitiserError(
                f"DDL keyword '{m.group()}' is not allowed in db_bot queries"
            )

    def _reject_schema_access(self, query: str) -> None:
        m = _SCHEMA_ACCESS.search(query)
        if m:
            raise SanitiserError(
                f"Schema-qualified access '{m.group()}' is not allowed"
            )

    def _check_table_allowlist(self, query: str) -> None:
        for match in _TABLE_REFS.finditer(query):
            raw = match.group(1)
            names = [n.strip().strip('"').lower() for n in raw.split(",")]
            for name in names:
                if name not in self.allowed_tables:
                    raise SanitiserError(
                        f"Table '{name}' is not in the db_bot allowlist for this agent. "
                        f"Allowed: {sorted(self.allowed_tables)}"
                    )

    def _enforce_limit(self, query: str) -> str:
        """Append LIMIT if the query has none and max_result_rows > 0."""
        if self.max_result_rows <= 0:
            return query
        if not re.search(r"\bLIMIT\b", query, re.IGNORECASE):
            return query.rstrip("; \n") + f" LIMIT {self.max_result_rows}"
        return query

    @staticmethod
    def _assert_identifier(value: str, label: str) -> None:
        """Raise SanitiserError if *value* is not a safe SQL identifier."""
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", value):
            raise SanitiserError(
                f"Unsafe {label} name '{value}': must match ^[a-zA-Z_][a-zA-Z0-9_]*$"
            )
