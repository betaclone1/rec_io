#!/usr/bin/env python3
"""
Record a new row in system.version_control (append-only deploy history).

Default: read latest version, increment the last numeric segment (3.0.1 -> 3.0.2).
Override: --version 3.1.0

Run on the target host whose DB should reflect the deploy (typically production via SSH
after a successful apply). Uses DB_* / REC_DB_* like other tooling.

Examples:
  python3 scripts/ops/record_system_version.py
  python3 scripts/ops/record_system_version.py --version 3.1.0
  python3 scripts/ops/record_system_version.py --dry-run
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
    p = argparse.ArgumentParser(description="Insert system.version_control row for this deploy.")
    p.add_argument(
        "--version",
        dest="explicit",
        metavar="SEMVER",
        help="Set version explicitly (e.g. 3.1.0). If omitted, bump patch on latest row.",
    )
    p.add_argument("--dry-run", action="store_true", help="Print version only; do not insert.")
    args = p.parse_args()

    import system_version_semver as semver

    from backend.core.config.database import get_system_postgresql_connection

    conn = get_system_postgresql_connection()
    if not conn:
        print("error: could not connect to PostgreSQL", file=sys.stderr)
        return 1

    try:
        with conn.cursor() as cur:
            if args.explicit:
                next_ver = semver.normalize_version_label(args.explicit)
            else:
                cur_ver = semver.fetch_latest_version(cur)
                if not cur_ver:
                    print(
                        "error: no prior row in system.version_control; use --version",
                        file=sys.stderr,
                    )
                    return 1
                try:
                    next_ver = semver.bump_patch(cur_ver)
                except ValueError as e:
                    print(f"error: {e}; use --version", file=sys.stderr)
                    return 1

            if args.dry_run:
                print(next_ver)
                return 0

            cur.execute(
                "INSERT INTO system.version_control (version, updated_at) VALUES (%s, NOW())",
                (next_ver,),
            )
        conn.commit()
        try:
            from backend.util.master_system_log import log_system_event

            log_system_event(
                category="DEPLOY",
                message=f"System version recorded: {next_ver}",
                source="record_system_version",
                severity="info",
                detail_ref="supervisord",
                metadata={"version": next_ver},
            )
        except Exception:
            pass
        print(next_ver)
        return 0
    except Exception as e:
        conn.rollback()
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
