#!/usr/bin/env python3
"""
Fail CI when the count of ``users.<table>_0001`` literals in ``backend/main.py`` changes.

Intentional edits: update ``scripts/ci/main_py_users_0001_literal_count.txt`` to match.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "backend" / "main.py"
BASELINE = Path(__file__).resolve().parent / "main_py_users_0001_literal_count.txt"


def main() -> int:
    text = MAIN.read_text(encoding="utf-8")
    n = len(re.findall(r"users\.\w+_0001\b", text))
    expected = int(BASELINE.read_text(encoding="utf-8").strip())
    if n != expected:
        print(
            f"scan_main_tenant_literals: backend/main.py has {n} "
            f"matches of users.<name>_0001; baseline file expects {expected}. "
            "Update the baseline only when the change is intentional.",
            file=sys.stderr,
        )
        return 1
    print(f"scan_main_tenant_literals: OK ({n} literals, matches baseline)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
