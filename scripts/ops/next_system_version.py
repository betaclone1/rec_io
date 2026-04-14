#!/usr/bin/env python3
"""
Print the release version string for the *next* deploy (stdout only, no DB write).

- No args: read latest row from system.version_control, bump last numeric segment.
- --bump-from X.Y.Z: print bump(X.Y.Z) without reading DB.
- --version V: print V normalized (strip leading v); for explicit releases.

Used during prepare-update / push-commits to pin the same version in changelog, git commit, and record_system_version.py --version on prod.
"""

from __future__ import annotations

import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SCRIPTS_DIR)
sys.path.insert(0, PROJECT_ROOT)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)


def main() -> int:
    p = argparse.ArgumentParser(description="Compute next release version string (no DB insert).")
    p.add_argument(
        "--bump-from",
        metavar="VER",
        help="Current version to bump (patch); does not query DB.",
    )
    p.add_argument(
        "--version",
        dest="explicit",
        metavar="VER",
        help="Explicit release version (e.g. 3.1.0 or v3.1.0); no bump.",
    )
    args = p.parse_args()

    import system_version_semver as semver

    if args.explicit and args.bump_from:
        print("error: use only one of --version or --bump-from", file=sys.stderr)
        return 1
    if args.explicit:
        print(semver.normalize_version_label(args.explicit))
        return 0
    if args.bump_from:
        try:
            print(semver.bump_patch(args.bump_from))
            return 0
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

    from backend.core.config.database import get_system_postgresql_connection

    conn = get_system_postgresql_connection()
    if not conn:
        print("error: could not connect to PostgreSQL", file=sys.stderr)
        return 1
    try:
        with conn.cursor() as cur:
            cur_ver = semver.fetch_latest_version(cur)
        if not cur_ver:
            print(
                "error: no row in system.version_control; use --bump-from or --version",
                file=sys.stderr,
            )
            return 1
        print(semver.bump_patch(cur_ver))
        return 0
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
