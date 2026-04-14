#!/usr/bin/env python3
"""
Static scan for code paths that may touch PostgreSQL tenant schemas (users_NNNN).

Excludes archive trees per TENANT_TOUCH_REGISTRY scope. Outputs JSON for manifests / CI.

Exemption: a line may contain `# tenant-touch-exempt: <short reason>` on the same line
to silence CI guardrails for that hit (use sparingly; document in registry).

Usage:
  PYTHONPATH=$(pwd) python3 scripts/db/scan_tenant_touch.py
  PYTHONPATH=$(pwd) python3 scripts/db/scan_tenant_touch.py --json scripts/db/output/tenant_touch_scan.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Repo root = parent of scripts/db
REPO_ROOT = Path(__file__).resolve().parents[2]

EXCLUDE_DIR_PARTS = (
    "/archive/",
    "/.pre-pull-backup",
    "/scripts/archive",
    "__pycache__",
)

# Same-line exemption (CI reads this exact substring)
EXEMPT_MARK = "tenant-touch-exempt:"

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("users_schema_token", re.compile(r"users_\d{4}")),
    ("legacy_users_qualified_table", re.compile(r"users\.[a-zA-Z_][a-zA-Z0-9_]*_\d{4}\b")),
    ("information_schema_users_literal", re.compile(r"table_schema\s*=\s*['\"]users['\"]")),
    ("pg_catalog_users_literal", re.compile(r"nspname\s*=\s*['\"]users['\"]")),
    ("from_join_users_dot", re.compile(r"\b(FROM|JOIN)\s+users\.", re.IGNORECASE)),
    ("get_postgresql_connection", re.compile(r"get_postgresql_connection\s*\(")),
    ("TenantConnection", re.compile(r"\bTenantConnection\b")),
    ("REC_USER_SCHEMA", re.compile(r"REC_USER_SCHEMA")),
    ("psycopg2_connect", re.compile(r"psycopg2\.connect\s*\(")),
]


def _should_scan(path: Path) -> bool:
    s = str(path)
    if not s.endswith(".py"):
        return False
    for part in EXCLUDE_DIR_PARTS:
        if part in s:
            return False
    if "/backend/" in s:
        return True
    if "/scripts/" in s and "/scripts/migrations/" not in s:
        return True
    if "/tests/" in s:
        return True
    return False


def _iter_py_files() -> list[Path]:
    out: list[Path] = []
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in ("venv", ".git", "__pycache__", "node_modules")]
        for f in files:
            if not f.endswith(".py"):
                continue
            p = Path(root) / f
            if _should_scan(p):
                out.append(p)
    out.sort()
    return out


def scan_file(path: Path) -> list[dict]:
    hits: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return hits
    lines = text.splitlines()
    for lineno, line in enumerate(lines, start=1):
        if EXEMPT_MARK in line:
            continue
        for rule, rx in PATTERNS:
            if rx.search(line):
                hits.append(
                    {
                        "file": str(path.relative_to(REPO_ROOT)),
                        "line": lineno,
                        "rule": rule,
                        "text": line.strip()[:240],
                    }
                )
                break
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description="Scan repo for tenant-schema touch patterns.")
    ap.add_argument(
        "--json",
        metavar="PATH",
        help="Write full results as JSON (parent dir created if needed)",
    )
    ap.add_argument("--summary", action="store_true", help="Print rule counts only")
    args = ap.parse_args()

    files = _iter_py_files()
    all_hits: list[dict] = []
    by_rule: dict[str, int] = {r: 0 for r, _ in PATTERNS}
    by_file: dict[str, int] = {}

    for p in files:
        fh = scan_file(p)
        for h in fh:
            all_hits.append(h)
            by_rule[h["rule"]] = by_rule.get(h["rule"], 0) + 1
            f = h["file"]
            by_file[f] = by_file.get(f, 0) + 1

    summary = {
        "repo_root": str(REPO_ROOT),
        "files_scanned": len(files),
        "hit_count": len(all_hits),
        "files_with_hits": len(by_file),
        "by_rule": by_rule,
        "top_files": sorted(by_file.items(), key=lambda x: -x[1])[:40],
    }

    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"summary": summary, "hits": all_hits}
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote {out_path} ({len(all_hits)} hits)")

    if args.summary or not args.json:
        print(json.dumps(summary, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
