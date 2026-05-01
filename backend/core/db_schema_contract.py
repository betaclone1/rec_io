"""
Runtime contract: required PostgreSQL catalog for production processes.

If ``system.master_users`` exists, it must expose the columns this codebase reads.
Otherwise we exit immediately with a loud ``DB_SCHEMA_MISMATCH`` message instead of
limping along with UndefinedColumn errors later.

Greenfield: before ``system.master_users`` is created (init_database / migrations),
verification is skipped so bootstrap can run.

Opt out (emergency only): ``REC_SKIP_DB_SCHEMA_CONTRACT=1``.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, List, Optional, Sequence, Tuple

_logger = logging.getLogger(__name__)

_verified_ok: bool = False

# (schema, table, column, expected PostgreSQL data_type or None to skip type check)
_REQUIRED_COLUMNS: Tuple[Tuple[str, str, str, Optional[str]], ...] = (
    ("system", "master_users", "exchange_credentials", "jsonb"),
    ("system", "master_users", "kalshi_user_id", "character varying"),
    ("system", "master_users", "user_no", None),
)


def _skip_contract() -> bool:
    return os.environ.get("REC_SKIP_DB_SCHEMA_CONTRACT", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _master_users_regclass(cur: Any) -> Optional[str]:
    cur.execute("SELECT pg_catalog.to_regclass('system.master_users')::text")
    row = cur.fetchone()
    if not row:
        return None
    v = row[0]
    return str(v).strip() if v else None


def collect_schema_violations(cur: Any) -> Optional[List[str]]:
    """
    Return None if ``system.master_users`` does not exist yet (skip enforcement).
    Return [] if catalog matches.
    Return list of human-readable violations otherwise.
    """
    if not _master_users_regclass(cur):
        return None

    violations: List[str] = []
    for schema, table, column, expect_type in _REQUIRED_COLUMNS:
        cur.execute(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s AND column_name = %s
            """,
            (schema, table, column),
        )
        row = cur.fetchone()
        if not row:
            violations.append(
                f"Missing column {schema}.{table}.{column} "
                f"(apply migrations; DB must match repo schema — this is not optional)."
            )
            continue
        actual = (row[0] or "").lower()
        if expect_type and actual != expect_type.lower():
            violations.append(
                f"Wrong type for {schema}.{table}.{column}: "
                f"found {row[0]!r}, required {expect_type!r}."
            )
    return violations


def enforce_on_raw_connection(conn) -> None:
    """
    Call once per process after a successful ``psycopg2.connect``.

    Exits the process with code 1 if the catalog is present but invalid.
    """
    global _verified_ok
    if _verified_ok:
        return
    if _skip_contract():
        _verified_ok = True
        _logger.warning(
            "REC_SKIP_DB_SCHEMA_CONTRACT is set; skipping DB schema contract check "
            "(not for production)."
        )
        return

    try:
        with conn.cursor() as cur:
            violations = collect_schema_violations(cur)
    except Exception as e:
        lines = [
            "DB_SCHEMA_MISMATCH: could not verify PostgreSQL catalog.",
            f"  Cause: {e}",
            "  Fix: ensure DB is reachable and migrations are applied.",
            "  Override (emergency only): REC_SKIP_DB_SCHEMA_CONTRACT=1",
        ]
        msg = "\n".join(lines)
        _logger.critical(msg)
        print(msg, file=sys.stderr)
        sys.exit(1)

    if violations is None:
        # Bootstrap / empty DB — master_users not created yet.
        _verified_ok = True
        return

    if violations:
        lines = [
            "DB_SCHEMA_MISMATCH: PostgreSQL catalog does not match this codebase.",
            "Required objects are missing or wrong type. Apply pending migrations;",
            "do not run production with a patched or partial schema.",
            "",
        ]
        lines.extend(f"  - {v}" for v in violations)
        lines.append("")
        lines.append("Override (emergency only): REC_SKIP_DB_SCHEMA_CONTRACT=1")
        msg = "\n".join(lines)
        _logger.critical(msg)
        print(msg, file=sys.stderr)
        sys.exit(1)

    _verified_ok = True
