#!/usr/bin/env python3
"""
Fail CI when the count of ``users.<table>_0001`` literals on the main_app edge changes.

Scanned paths:
  - ``backend/main.py``
  - ``backend/web/**/*.py`` (routers and helpers split out of main_app)

Intentional edits: update ``scripts/ci/main_py_users_0001_literal_count.txt`` to match.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "backend" / "main.py"
WEB = ROOT / "backend" / "web"
BASELINE = Path(__file__).resolve().parent / "main_py_users_0001_literal_count.txt"
PATTERN = re.compile(r"users\.\w+_0001\b")


def _main_app_edge_py_files() -> list[Path]:
    paths: list[Path] = [MAIN]
    if WEB.is_dir():
        paths.extend(sorted(WEB.rglob("*.py")))
    return [p for p in paths if "__pycache__" not in p.parts and p.is_file()]


def main() -> int:
    n = 0
    for path in _main_app_edge_py_files():
        n += len(PATTERN.findall(path.read_text(encoding="utf-8")))
    expected = int(BASELINE.read_text(encoding="utf-8").strip())
    if n != expected:
        print(
            f"scan_main_tenant_literals: main_app edge (backend/main.py + backend/web/**/*.py) "
            f"has {n} matches of users.<name>_0001; baseline file expects {expected}. "
            "Update the baseline only when the change is intentional.",
            file=sys.stderr,
        )
        return 1
    print(f"scan_main_tenant_literals: OK ({n} literals, matches baseline)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
