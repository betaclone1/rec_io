#!/usr/bin/env python3
"""
Fail CI if backend Python contains tenant foot-guns:

- SQL literals pinning user_no to '0001' / \"0001\" (wrong when REC_USER_SCHEMA is another tenant)
- Raw probes of legacy ``users.trades_0001`` (table lives in ``users_NNNN.trades_NNNN``)

Legacy ``users.table_0001`` strings passed through :class:`backend.core.tenant_context.TenantConnection`
are rewritten; raw ``psycopg2`` must use :func:`backend.core.tenant_context.process_tenant_context`
+ ``Identifier``, or centralized config.

Excluded paths are intentional DDL (init_database) or tests. Expand exclusions only with a code review.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"

# Whole-file skips (template DDL / generated / tests live only here)
SKIP_FILES = frozenset(
    {
        BACKEND / "core" / "config" / "database.py",
        BACKEND / "auto_entry_supervisor_test.py",
    }
)

SKIP_DIR_PARTS = frozenset(
    {
        "__pycache__",
        "archive",
    }
)

# Lines matching these are forbidden outside exclusions
PATTERNS = (
    (re.compile(r"WHERE\s+user_no\s*=\s*['\"]0001['\"]", re.IGNORECASE), "WHERE user_no = '0001' literal"),
    # Single-line raw probe bypassing TenantConnection (OK on TenantCursor — prefer grep for reviews)
    (
        re.compile(r"execute\(\s*[\"']SELECT\s+1\s+FROM\s+users\.trades_0001\b", re.IGNORECASE),
        "raw psycopg2 execute SELECT 1 FROM users.trades_0001",
    ),
)


def _should_skip(path: Path) -> bool:
    if path in SKIP_FILES:
        return True
    try:
        rel = path.relative_to(BACKEND)
    except ValueError:
        return True
    parts = set(rel.parts)
    if parts & SKIP_DIR_PARTS:
        return True
    if path.name.startswith("test_") and path.suffix == ".py":
        return True
    return False


def main() -> int:
    violations: list[str] = []
    for py in sorted(BACKEND.rglob("*.py")):
        if _should_skip(py):
            continue
        try:
            text = py.read_text(encoding="utf-8")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if line.strip().startswith("#"):
                continue
            for rx, label in PATTERNS:
                if rx.search(line):
                    violations.append(f"{py.relative_to(REPO)}:{i}: {label}\n  {line.strip()}")
    if violations:
        print("Tenant SQL literal check FAILED:\n", file=sys.stderr)
        for v in violations:
            print(v, file=sys.stderr)
        print(
            "\nFix: use process_tenant_context().user_no, get_postgresql_tenant_connection(u_no), "
            "or legacy users.* SQL only on TenantConnection cursors.",
            file=sys.stderr,
        )
        return 1
    print("Tenant SQL literal check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
