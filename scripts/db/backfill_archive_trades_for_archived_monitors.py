#!/usr/bin/env python3
"""
Backfill: move trades from users.trades_0001 into archive.trades_archive_live_<n> / paper when:

- The trade's monitor is missing from users.monitor_list_<n>, OR
- monitor_list status is not active or inactive (e.g. ARCHIVED), OR
- monitor text is null/invalid, or mon_* user prefix != <n>.

Runs archive_trades_not_in_active_or_inactive_monitor (one transaction per run from caller).

Optional: --archived-monitors-only uses only explicit ARCHIVED rows (legacy narrow pass).

From repo root:
  PYTHONPATH=$(pwd) .venv/bin/python3 scripts/db/backfill_archive_trades_for_archived_monitors.py --dry-run
  PYTHONPATH=$(pwd) .venv/bin/python3 scripts/db/backfill_archive_trades_for_archived_monitors.py --user-number 0001

Requires migration 20260327_2200_archive_trades_live_paper_0001 applied.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SCRIPTS_DIR)
sys.path.insert(0, PROJECT_ROOT)

from backend.core.config.database import get_postgresql_connection
from backend.util.trade_log_archivist import (
    archive_trades_for_monitor,
    archive_trades_not_in_active_or_inactive_monitor,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--user-number",
        default="0001",
        help="Monitor list / archive table suffix (default 0001)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count rows only; no INSERT/DELETE",
    )
    parser.add_argument(
        "--archived-monitors-only",
        action="store_true",
        help="Only move trades for monitors with status ARCHIVED (narrow legacy mode)",
    )
    args = parser.parse_args()
    if not re.fullmatch(r"\d{4}", args.user_number or ""):
        print("--user-number must be four digits (e.g. 0001).", file=sys.stderr)
        sys.exit(1)

    conn = get_postgresql_connection()
    if not conn:
        print("Failed to connect to PostgreSQL.", file=sys.stderr)
        sys.exit(1)

    if args.archived_monitors_only:
        mon_table = f"monitor_list_{args.user_number}"
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id FROM users.{mon_table}
                    WHERE UPPER(TRIM(status)) = 'ARCHIVED'
                    ORDER BY id
                    """
                )
                monitor_ids = [str(row[0]) for row in cur.fetchall()]
        except Exception as e:
            print(f"Failed to query users.{mon_table}: {e}", file=sys.stderr)
            conn.close()
            sys.exit(1)

        total_paper = total_live = 0
        for mid in monitor_ids:
            with conn.cursor() as cur:
                try:
                    stats = archive_trades_for_monitor(
                        cur,
                        args.user_number,
                        mid,
                        dry_run=args.dry_run,
                    )
                except Exception as e:
                    print(f"monitor {mid}: error: {e}", file=sys.stderr)
                    if not args.dry_run:
                        conn.rollback()
                    continue
                if args.dry_run:
                    print(
                        f"monitor {mid} ({stats.get('monitor_key')}): "
                        f"paper={stats.get('paper_rows')} live={stats.get('live_rows')}"
                    )
                    total_paper += int(stats.get("paper_rows") or 0)
                    total_live += int(stats.get("live_rows") or 0)
                else:
                    print(
                        f"monitor {mid}: moved paper={stats.get('paper_moved')} "
                        f"live={stats.get('live_moved')} "
                        f"deleted={stats.get('deleted_from_master')}"
                    )
                    conn.commit()

        if args.dry_run:
            print(
                f"dry-run totals (--archived-monitors-only): "
                f"paper_rows={total_paper} live_rows={total_live} monitors={len(monitor_ids)}"
            )
        conn.close()
        return

    try:
        with conn.cursor() as cur:
            stats = archive_trades_not_in_active_or_inactive_monitor(
                cur,
                args.user_number,
                dry_run=args.dry_run,
            )
    except Exception as e:
        print(f"Archive sweep failed: {e}", file=sys.stderr)
        if not args.dry_run:
            conn.rollback()
        conn.close()
        sys.exit(1)

    if args.dry_run:
        print(
            f"dry-run sweep: paper_rows={stats.get('paper_rows')} "
            f"live_rows={stats.get('live_rows')} "
            "(trades where monitor is not active/inactive in monitor_list)"
        )
    else:
        print(
            f"sweep: paper_moved={stats.get('paper_moved')} "
            f"live_moved={stats.get('live_moved')} "
            f"deleted_from_master={stats.get('deleted_from_master')}"
        )
        conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
