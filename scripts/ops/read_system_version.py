#!/usr/bin/env python3
"""Print the latest version in system.version_control (one line, stdout). Exit 1 if none."""

from __future__ import annotations

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SCRIPTS_DIR)
sys.path.insert(0, PROJECT_ROOT)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)


def main() -> int:
    import system_version_semver as semver

    from backend.core.config.database import get_system_postgresql_connection

    conn = get_system_postgresql_connection()
    if not conn:
        print("error: could not connect to PostgreSQL", file=sys.stderr)
        return 1
    try:
        with conn.cursor() as cur:
            v = semver.fetch_latest_version(cur)
        if not v:
            print("error: system.version_control has no rows", file=sys.stderr)
            return 1
        print(v)
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
