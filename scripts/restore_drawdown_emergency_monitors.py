#!/usr/bin/env python3
"""
Restore ``users.monitor_list_<slot>`` paper_trade and test_filter from the drawdown halt snapshot.

Default source: ``users.system_settings_<slot>``.drawdown_halt_monitor_snapshot (JSONB), written by
MonitorManager.apply_drawdown_emergency_monitor_halt.

Usage (from project root):
  PYTHONPATH=$(pwd) python3 scripts/restore_drawdown_emergency_monitors.py --dry-run
  PYTHONPATH=$(pwd) python3 scripts/restore_drawdown_emergency_monitors.py
  PYTHONPATH=$(pwd) python3 scripts/restore_drawdown_emergency_monitors.py --file /path/to/legacy.json

  Full restore (apply monitors + clear trading_halt_active + NULL snapshot), same as dashboard:
  PYTHONPATH=$(pwd) python3 scripts/restore_drawdown_emergency_monitors.py --full-restore
"""

from __future__ import annotations

import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
LEGACY_DEFAULT_SNAPSHOT = os.path.join(
    PROJECT_ROOT, "backend", "data", "drawdown_emergency_restore.json"
)

sys.path.insert(0, PROJECT_ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore monitor paper_trade / test_filter from drawdown halt snapshot (DB or file)."
    )
    parser.add_argument(
        "--file",
        default=None,
        help=f"Legacy JSON path (default: use DB column; legacy file was {LEGACY_DEFAULT_SNAPSHOT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned UPDATEs only (no DB writes).",
    )
    parser.add_argument(
        "--full-restore",
        action="store_true",
        help="Apply snapshot, set trading_halt_active false, and clear JSONB column (matches API restore).",
    )
    args = parser.parse_args()
    user_no = resolve_user_no(args)

    from backend.core.drawdown_emergency_restore import (
        validate_drawdown_monitor_snapshot,
    )

    if args.full_restore:
        if args.dry_run:
            print("--full-restore with --dry-run is not supported.", file=sys.stderr)
            return 1
        from backend.core.system_settings_store import restore_trade_operations_from_snapshot

        ok, msg, n = restore_trade_operations_from_snapshot(user_no)
        if not ok:
            print(msg, file=sys.stderr)
            return 1
        print(f"Done. Full restore OK ({n} monitor update(s)).")
        return 0

    if args.file:
        path = args.file
        if not os.path.isfile(path):
            print(f"Snapshot not found: {path}", file=sys.stderr)
            return 1
        if args.dry_run:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            ok, vmsg = validate_drawdown_monitor_snapshot(data)
            if not ok:
                print(vmsg, file=sys.stderr)
                return 1
            for m in data.get("monitors") or []:
                mid = m.get("id")
                if mid is None:
                    continue
                pt, tf = m.get("paper_trade"), m.get("test_filter")
                if pt is None or tf is None:
                    print(f"skip id={mid}: missing paper_trade or test_filter", file=sys.stderr)
                    continue
                print(f"would UPDATE id={mid} paper_trade={pt} test_filter={tf}")
            print("Done. (dry-run, file)")
            return 0
        from backend.core.drawdown_emergency_restore import (
            restore_monitors_from_drawdown_snapshot_file,
        )

        ok, msg, n = restore_monitors_from_drawdown_snapshot_file(path, user_number="0001")
        if not ok:
            print(msg, file=sys.stderr)
            return 1
        print(f"Done. ({n} update(s), file)")
        return 0

    # Default: DB snapshot only (does not clear trading_halt_active or JSONB column)
    if args.dry_run:
        from backend.core.config.database import get_postgresql_connection
        from backend.core.system_settings_store import _settings_table_ident
        from psycopg2 import sql

        conn = get_postgresql_connection(tenant_user_no=user_no)
        if not conn:
            print("database connection failed", file=sys.stderr)
            return 1
        try:
            with conn.cursor() as cursor:
                ident = _settings_table_ident(user_no)
                cursor.execute(
                    sql.SQL(
                        "SELECT drawdown_halt_monitor_snapshot FROM {} WHERE id = 1"
                    ).format(ident)
                )
                row = cursor.fetchone()
                raw = row[0] if row else None
            if raw is None:
                print("no drawdown_halt_monitor_snapshot in system_settings", file=sys.stderr)
                return 1
            data = raw if isinstance(raw, dict) else json.loads(raw) if isinstance(raw, str) else None
            if not isinstance(data, dict):
                print("invalid JSONB payload", file=sys.stderr)
                return 1
            ok, vmsg = validate_drawdown_monitor_snapshot(data)
            if not ok:
                print(vmsg, file=sys.stderr)
                return 1
            for m in data.get("monitors") or []:
                mid = m.get("id")
                if mid is None:
                    continue
                pt, tf = m.get("paper_trade"), m.get("test_filter")
                if pt is None or tf is None:
                    print(f"skip id={mid}: missing paper_trade or test_filter", file=sys.stderr)
                    continue
                print(f"would UPDATE id={mid} paper_trade={pt} test_filter={tf}")
            print("Done. (dry-run, DB)")
            return 0
        finally:
            conn.close()

    from backend.core.drawdown_emergency_restore import restore_monitors_from_db_snapshot_only

    ok, msg, n = restore_monitors_from_db_snapshot_only(user_number=user_no)
    if not ok:
        print(msg, file=sys.stderr)
        return 1
    print(f"Done. ({n} update(s), DB snapshot; trading_halt_active unchanged — use --full-restore to clear latch.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
