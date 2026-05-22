#!/usr/bin/env python3
"""
CI guardrail: listed **global** modules must not contain tenant-table SQL tokens.

Forbidden (unless same line contains ``# tenant-touch-exempt: reason``):
  - ``users_NNNN`` schema tokens
  - Legacy ``users.table_NNNN`` qualifiers
  - ``FROM users.`` / ``JOIN users.``

Run from repo root:
  python3 scripts/ci/check_global_tenant_touch.py

Exit 1 if any violation; exit 0 if clean.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Paths relative to repo root — global daemons / shared-schema writers only.
GLOBAL_MODULES = (
    "backend/core/market_watchdog/venues/kalshi_ws_ingest.py",
    "backend/core/market_watchdog/kalshi_schedule_rest.py",
    "backend/strike_table_generator_ws.py",
    "backend/symbol_price_watchdog.py",
    "backend/symbol_price_watchdog_finance.py",
    "backend/redis_switchboard.py",
)

EXEMPT = "tenant-touch-exempt:"
RX_USERS_SCHEMA = re.compile(r"users_[0-9]{4}")
RX_LEGACY_QUAL = re.compile(r"users\.[a-zA-Z_][a-zA-Z0-9_]*_[0-9]{4}\b")
RX_FROM_JOIN = re.compile(r"\b(FROM|JOIN)\s+users\.", re.IGNORECASE)


def check_file(path: Path) -> list[tuple[int, str]]:
    bad: list[tuple[int, str]] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for i, line in enumerate(text.splitlines(), start=1):
        if EXEMPT in line:
            continue
        if RX_USERS_SCHEMA.search(line) or RX_LEGACY_QUAL.search(line) or RX_FROM_JOIN.search(line):
            bad.append((i, line.strip()[:200]))
    return bad


def main() -> int:
    failed = False
    for rel in GLOBAL_MODULES:
        p = REPO / rel
        if not p.is_file():
            continue
        hits = check_file(p)
        if hits:
            failed = True
            print(f"FAIL {rel}:")
            for ln, preview in hits:
                print(f"  L{ln}: {preview}")
    if failed:
        print(
            "\nFix: remove tenant SQL from global modules or add rare same-line "
            f"`# {EXEMPT} <reason>` after review.",
            file=sys.stderr,
        )
        return 1
    print("OK: global tenant-touch check passed (%s files)" % len(GLOBAL_MODULES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
