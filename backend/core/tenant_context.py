"""
Per-tenant PostgreSQL context: schema users_<user_no> and tables suffixed _<user_no>.

Workers and the main app: set ``REC_USER_SCHEMA=users_<slot>`` (or ``REC_USER_NO=<slot>``), or
leave unset with ``REC_SINGLE_USER_MODE=1`` and ``REC_DEFAULT_USER_SCHEMA`` for single-tenant tooling.

Callers that need a specific slot (tools, read-side helpers) pass ``tenant_user_no`` into
:func:`backend.core.config.database.get_postgresql_connection`.

**Isolation:** :class:`TenantConnection` sets ``search_path`` to the tenant schema (plus
``pg_catalog``) and, on every ``execute`` / ``executemany``, rejects SQL or bind parameters
that reference another ``users_MMMM`` schema token or legacy ``users.`` / ``"users".``.
For a full database-enforced boundary, also revoke ``USAGE`` on other tenants' schemas
for the application role (defense in depth).
"""

from __future__ import annotations

import os
import re

import psycopg2
import psycopg2.pool
from dataclasses import dataclass
from typing import Any, Optional

_SCHEMA_RE = re.compile(r"^users_(\d{4})$")
_USER_NO_RE = re.compile(r"^\d{4}$")
# Legacy SQL uses users.<base>_NNNN; rewrite to tenant schema + this process user_no.
_USER_QUAL_TABLE_RE = re.compile(r"users\.([a-zA-Z_][a-zA-Z0-9_]*)_\d{4}\b")
# Quoted schema "users"."table_NNNN" (psycopg2.sql.Identifier) must rewrite too.
_USER_QUAL_QUOTED_RE = re.compile(
    r'"users"\s*\.\s*"([a-zA-Z_][a-zA-Z0-9_]*)_(\d{4})"\b'
)
# Tenant schema tokens users_NNNN (PostgreSQL identifier; not inside longer unbroken names).
_USERS_TENANT_SCHEMA_RE = re.compile(r"(?<![a-zA-Z0-9_])users_(\d{4})\b")
# Bind parameters: only treat as a cross-tenant risk when clearly schema-qualified (users_MMMM.)
# or legacy users., so free text is not rejected.
_PARAM_CROSS_TENANT_SCHEMA = re.compile(r"(?<![a-zA-Z0-9_])users_(\d{4})\.")
# Legacy single schema name ``users`` as qualifier (must never appear on a bound connection).
_LEGACY_USERS_SCHEMA_DOT = re.compile(r"(?<![a-zA-Z0-9_])users\.", re.IGNORECASE)
_LEGACY_USERS_QUOTED_SCHEMA_DOT = re.compile(r'"users"\s*\.', re.IGNORECASE)


class TenantIsolationError(RuntimeError):
    """Raised when SQL or parameters reference a tenant other than the connection's context."""


def _truthy_env(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip() in ("1", "true", "True", "yes", "YES")


@dataclass(frozen=True)
class TenantContext:
    user_no: str
    pg_schema: str

    @staticmethod
    def from_schema(pg_schema: str) -> TenantContext:
        m = _SCHEMA_RE.match(pg_schema)
        if not m:
            raise ValueError(f"invalid tenant schema: {pg_schema!r} (expected users_NNNN)")
        return TenantContext(user_no=m.group(1), pg_schema=pg_schema)

    def ut(self, base_without_suffix: str) -> str:
        """Return qualified table e.g. ut('trades') -> users_<slot>.trades_<slot>."""
        if not base_without_suffix or not base_without_suffix.replace("_", "").isalnum():
            raise ValueError(f"invalid table base: {base_without_suffix!r}")
        return f"{self.pg_schema}.{base_without_suffix}_{self.user_no}"

    def qualify_raw_table(self, table_name: str) -> str:
        """Qualified name when table_name already includes suffix (e.g. monitor_list_<slot>)."""
        if not table_name.endswith(f"_{self.user_no}"):
            raise ValueError(
                f"table {table_name!r} must end with _{self.user_no} for tenant {self.user_no}"
            )
        return f"{self.pg_schema}.{table_name}"

    def data_dir_user_folder(self) -> str:
        from backend.util.paths import get_data_dir

        return os.path.join(get_data_dir(), "users", f"user_{self.user_no}")


def is_single_user_mode() -> bool:
    """When True, unset REC_USER_SCHEMA falls back to REC_DEFAULT_USER_SCHEMA."""
    return _truthy_env("REC_SINGLE_USER_MODE", "1")


def strict_session_tenant_for_db_enabled() -> bool:
    """
    Internet-facing apps (main_app, read_api) set this so :func:`get_postgresql_connection`
    and :func:`resolved_tenant_user_no_for_app` never fall back to a process default tenant
    when no valid web session is bound.
    """
    return _truthy_env("REC_STRICT_SESSION_TENANT_FOR_DB", "0")


def default_pg_schema_for_init() -> str:
    """Schema name for init_database and greenfield installs (must be set explicitly)."""
    s = os.environ.get("REC_DEFAULT_USER_SCHEMA", "").strip()
    if not s:
        raise RuntimeError(
            "REC_DEFAULT_USER_SCHEMA is not set. Set it to your tenant schema name "
            "(e.g. users_<four-digit slot>) for single-user fallback and init tooling."
        )
    return s


def get_worker_tenant_context() -> TenantContext:
    """Process-wide tenant for workers (supervisor sets env per program)."""
    schema = os.environ.get("REC_USER_SCHEMA", "").strip()
    if schema:
        return TenantContext.from_schema(schema)
    user_no = os.environ.get("REC_USER_NO", "").strip()
    if user_no and _USER_NO_RE.match(user_no):
        return TenantContext(user_no=user_no, pg_schema=f"users_{user_no}")
    if is_single_user_mode():
        return TenantContext.from_schema(default_pg_schema_for_init())
    raise RuntimeError(
        "Multi-user: set REC_USER_SCHEMA or REC_USER_NO for this process, "
        "or set REC_SINGLE_USER_MODE=1 and REC_DEFAULT_USER_SCHEMA for single-tenant fallback."
    )


def process_tenant_context() -> TenantContext:
    """
    Tenant for this OS process when running raw SQL (no :class:`TenantConnection`).

    Uses :func:`get_worker_tenant_context` when env is set; otherwise falls back to
    :func:`default_pg_schema_for_init` (same as legacy single-tenant tooling). For
    multi-tenant production, always set ``REC_USER_SCHEMA`` / ``REC_USER_NO`` on the
    process so the fallback is not used unintentionally.
    """
    try:
        return get_worker_tenant_context()
    except RuntimeError:
        return TenantContext.from_schema(default_pg_schema_for_init())


def get_api_tenant_context(user_no: str) -> TenantContext:
    """Resolve tenant from authenticated user number only."""
    if not user_no or not _USER_NO_RE.match(user_no):
        raise ValueError("invalid user_no")
    return TenantContext(user_no=user_no, pg_schema=f"users_{user_no}")


_worker_ctx: Optional[TenantContext] = None


def worker_tenant_context_cached() -> TenantContext:
    """Lazy singleton for modules that call repeatedly (same process)."""
    global _worker_ctx
    if _worker_ctx is None:
        _worker_ctx = get_worker_tenant_context()
    return _worker_ctx


def reset_worker_tenant_context_cache() -> None:
    global _worker_ctx
    _worker_ctx = None


def resolved_tenant_user_no_for_app() -> str:
    """
    Effective four-digit slot for code that builds per-tenant table names (e.g. ``trades_NNNN``).

    Prefer the bound web request tenant when set; otherwise the worker/process tenant.
    When :func:`strict_session_tenant_for_db_enabled` is True, there is no process fallback
    for code paths that expect an HTTP session (fail closed).
    """
    try:
        from backend.web.tenant_asgi import get_web_api_user_no

        u = get_web_api_user_no()
        if u and _USER_NO_RE.match(u):
            return u
    except Exception:
        pass
    if strict_session_tenant_for_db_enabled():
        raise RuntimeError(
            "resolved_tenant_user_no_for_app: no authenticated session tenant is bound "
            "(REC_STRICT_SESSION_TENANT_FOR_DB is enabled on this process)"
        )
    return process_tenant_context().user_no


def effective_pg_schema_for_sql_rewrite() -> str:
    """Schema used to rewrite literal `users.` in SQL (workers, API, scripts)."""
    return effective_tenant_context_for_sql_rewrite().pg_schema


def effective_tenant_context_for_sql_rewrite() -> TenantContext:
    """Tenant for connections without an explicit API user (workers, scripts)."""
    try:
        return get_worker_tenant_context()
    except RuntimeError:
        if is_single_user_mode():
            return TenantContext.from_schema(default_pg_schema_for_init())
        raise


def sql_string_needs_users_rewrite(query: str) -> bool:
    """True if legacy ``users`` schema may appear in this SQL text."""
    if not isinstance(query, str) or not query:
        return False
    if "users." in query:
        return True
    if _USER_QUAL_QUOTED_RE.search(query):
        return True
    return re.search(r'"users"\s*\.', query) is not None


def assert_sql_and_params_target_only_connection_tenant(
    sql_text: str,
    ctx: TenantContext,
    vars: Any = None,
    *,
    _param_walk_depth: int = 0,
) -> None:
    """
    Fail closed if ``sql_text`` or bind values mention another tenant's ``users_MMMM`` schema
    or legacy ``users.`` / ``"users".`` qualifiers.
    """
    if not isinstance(sql_text, str):
        return
    if _LEGACY_USERS_SCHEMA_DOT.search(sql_text) or _LEGACY_USERS_QUOTED_SCHEMA_DOT.search(
        sql_text
    ):
        raise TenantIsolationError(
            "tenant SQL must not use legacy schema qualifier users.* or \"users\".* "
            f"(connection is {ctx.pg_schema})"
        )
    for m in _USERS_TENANT_SCHEMA_RE.finditer(sql_text):
        if m.group(1) != ctx.user_no:
            raise TenantIsolationError(
                f"SQL references tenant schema users_{m.group(1)} but this connection is "
                f"bound to users_{ctx.user_no} ({ctx.pg_schema})"
            )
    if vars is None or _param_walk_depth > 12:
        return
    if isinstance(vars, dict):
        for v in vars.values():
            assert_sql_and_params_target_only_connection_tenant(
                "", ctx, v, _param_walk_depth=_param_walk_depth + 1
            )
        return
    if isinstance(vars, (list, tuple)):
        for v in vars:
            assert_sql_and_params_target_only_connection_tenant(
                "", ctx, v, _param_walk_depth=_param_walk_depth + 1
            )
        return
    if isinstance(vars, (str, bytes)):
        s = vars.decode("utf-8", "replace") if isinstance(vars, bytes) else vars
        for m in _PARAM_CROSS_TENANT_SCHEMA.finditer(s):
            if m.group(1) != ctx.user_no:
                raise TenantIsolationError(
                    f"bind parameter contains tenant schema token users_{m.group(1)} but "
                    f"this connection is bound to users_{ctx.user_no}"
                )
        if _LEGACY_USERS_SCHEMA_DOT.search(s) or _LEGACY_USERS_QUOTED_SCHEMA_DOT.search(s):
            raise TenantIsolationError(
                "bind parameter must not contain legacy users.* schema qualifiers"
            )
        return
    return


def rewrite_users_qualified_sql(query: str, ctx: TenantContext) -> str:
    """
    Map legacy ``users.some_table_NNNN`` → ``{ctx.pg_schema}.some_table_{ctx.user_no}``,
    quoted ``"users"."some_table_NNNN"`` → ``"{pg_schema}"."some_table_{user_no}"``,
    then any remaining ``users.`` → ``{ctx.pg_schema}.`` (legacy single-schema prefix).
    """
    if not isinstance(query, str) or not sql_string_needs_users_rewrite(query):
        return query

    def _repl_quoted(m) -> str:
        base = m.group(1)
        return f'"{ctx.pg_schema}"."{base}_{ctx.user_no}"'

    q = _USER_QUAL_QUOTED_RE.sub(_repl_quoted, query)

    def _repl(m) -> str:
        base = m.group(1)
        return f"{ctx.pg_schema}.{base}_{ctx.user_no}"

    q = _USER_QUAL_TABLE_RE.sub(_repl, q)
    # Remaining quoted schema "users". (identifier-composed SQL).
    q = re.sub(r'"users"(\s*\.)', f'"{ctx.pg_schema}"\\1', q)
    if "users." in q:
        q = q.replace("users.", f"{ctx.pg_schema}.")
    return q


class TenantRewritingCursor:
    """psycopg2 cursor proxy: qualify legacy ``users.*`` SQL to the active tenant."""

    __slots__ = ("_cursor", "_ctx")

    def __init__(self, cursor, ctx: TenantContext):
        self._cursor = cursor
        self._ctx = ctx

    @property
    def tenant_context(self) -> TenantContext:
        """Bound tenant for this cursor (same as the wrapping :class:`TenantConnection`)."""
        return self._ctx

    def _finalize_query(self, query, vars):
        """Return (query_for_execute, vars) with rewrite + isolation checks."""
        from psycopg2 import sql as psql

        q_for_exec = query
        if isinstance(query, psql.Composable):
            raw_conn = getattr(self._cursor, "connection", None)
            if raw_conn is None:
                raise TenantIsolationError(
                    "tenant cursor has no connection; cannot validate SQL composable"
                )
            try:
                qstr = query.as_string(raw_conn)
            except Exception as e:
                raise TenantIsolationError(
                    f"cannot render SQL composable for tenant validation: {e}"
                ) from e
            if not (isinstance(qstr, str) and qstr.strip()):
                raise TenantIsolationError("empty SQL composable after render")
            if sql_string_needs_users_rewrite(qstr):
                q_for_exec = rewrite_users_qualified_sql(qstr, self._ctx)
            else:
                q_for_exec = qstr
            assert_sql_and_params_target_only_connection_tenant(q_for_exec, self._ctx, vars)
        elif isinstance(query, bytes):
            q_dec = query.decode("utf-8", "replace")
            q_for_exec = (
                rewrite_users_qualified_sql(q_dec, self._ctx)
                if sql_string_needs_users_rewrite(q_dec)
                else q_dec
            )
            assert_sql_and_params_target_only_connection_tenant(q_for_exec, self._ctx, vars)
        elif isinstance(query, str):
            q_for_exec = (
                rewrite_users_qualified_sql(query, self._ctx)
                if sql_string_needs_users_rewrite(query)
                else query
            )
            assert_sql_and_params_target_only_connection_tenant(q_for_exec, self._ctx, vars)
        else:
            raise TenantIsolationError(
                "tenant cursor only accepts str, bytes, or psycopg2.sql composable query; "
                f"got {type(query).__name__}"
            )
        return q_for_exec, vars

    def execute(self, query, vars=None):
        q_for_exec, v = self._finalize_query(query, vars)
        if v is None:
            return self._cursor.execute(q_for_exec)
        return self._cursor.execute(q_for_exec, v)

    def executemany(self, query, vars_list):
        q_for_exec, _ = self._finalize_query(query, None)
        if not vars_list:
            return self._cursor.executemany(q_for_exec, vars_list)
        for row in vars_list:
            assert_sql_and_params_target_only_connection_tenant("", self._ctx, row)
        return self._cursor.executemany(q_for_exec, vars_list)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self._cursor.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class TenantConnection:
    """psycopg2 connection proxy: cursors rewrite legacy ``users.*`` to the active tenant."""

    __slots__ = ("_conn", "_ctx")

    def __init__(self, conn, ctx: TenantContext):
        self._conn = conn
        self._ctx = ctx
        self._apply_session_tenant_guc()
        self._apply_session_search_path()

    def _apply_session_tenant_guc(self) -> None:
        """
        Set ``rec.tenant_pg_schema`` for the session so PostgreSQL RLS policies on ``users_*``
        schemas (migration ``20260411_1500_rec_tenant_rls_session_guc``) allow only the active tenant.
        """
        cur = self._conn.cursor()
        try:
            cur.execute(
                "SELECT set_config(%s, %s, false)",
                ("rec.tenant_pg_schema", self._ctx.pg_schema),
            )
        except Exception as e:
            raise TenantIsolationError(
                f"Could not set session rec.tenant_pg_schema={self._ctx.pg_schema!r}: {e}. "
                "Ensure migration 20260411_1500_rec_tenant_rls_session_guc is applied. "
                "If the server rejects this parameter, set custom_variable_classes = 'rec' in "
                "postgresql.conf and restart PostgreSQL."
            ) from e
        finally:
            cur.close()

    def _apply_session_search_path(self) -> None:
        from psycopg2 import sql as psql

        cur = self._conn.cursor()
        try:
            cur.execute(
                psql.SQL("SET search_path TO {}, pg_catalog").format(
                    psql.Identifier(self._ctx.pg_schema)
                )
            )
        finally:
            cur.close()

    def cursor(self, *args, **kwargs):
        return TenantRewritingCursor(self._conn.cursor(*args, **kwargs), self._ctx)

    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, *args):
        return self._conn.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self._conn, name)


class TenantThreadedConnectionPool(psycopg2.pool.ThreadedConnectionPool):
    """
    Like ThreadedConnectionPool but every connection is wrapped in TenantConnection
    so cursor.execute rewrites legacy ``users.*`` to the process tenant schema.
    """

    def __init__(self, minconn: int, maxconn: int, tenant_ctx: TenantContext, **connect_kwargs):
        from backend.core.time_eastern import merge_psycopg2_connect_kwargs

        self._tenant_ctx = tenant_ctx
        super().__init__(minconn, maxconn, **merge_psycopg2_connect_kwargs(connect_kwargs))

    def _connect(self, key=None):
        conn = psycopg2.connect(*self._args, **self._kwargs)
        wrapped = TenantConnection(conn, self._tenant_ctx)
        if key is not None:
            self._used[key] = wrapped
            self._rused[id(wrapped)] = key
        else:
            self._pool.append(wrapped)
        return wrapped
