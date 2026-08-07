#!/usr/bin/env python3
"""
Compare open/pending/closing trades_* rows vs ATS unified active_trades pool enrollment.

Highlights trades that may skip auto-stops because they are not in the ATS pool
(and pool ghosts not present in the trade log).

Read-only. Usage (from repo root):
  python3 scripts/diagnostics/check_ats_enrollment_health.py --user-no 0001
  python3 scripts/diagnostics/check_ats_enrollment_health.py --user-no 0001 --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Set

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.core.config.database import get_postgresql_connection
from backend.core.tenant_legacy_sql import legacy_users_trades
from backend.core.tenant_script_args import add_user_no_argument, resolve_user_no


def _norm_slot(user_no: str) -> str:
    s = str(user_no).strip()
    if s.isdigit():
        return f"{int(s):04d}"
    return s


def _list_pool_tables(cur, schema: str, slot: str) -> List[str]:
    """Unified pool tables only (legacy per-monitor active_trades_* skipped)."""
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = %s
          AND (
            table_name = %s
            OR table_name = %s
          )
        ORDER BY table_name
        """,
        (schema, f"active_trades_15m_{slot}", f"active_trades_hourly_{slot}"),
    )
    return [r[0] for r in cur.fetchall()]


def main() -> int:
    ap = argparse.ArgumentParser(description="ATS enrollment health vs trades_*")
    add_user_no_argument(ap)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    user_no = resolve_user_no(args)
    slot = _norm_slot(user_no)
    schema_candidates = [f"users_{slot}", "users"]

    conn = get_postgresql_connection(tenant_user_no=user_no)
    if not conn:
        print("No database connection.", file=sys.stderr)
        return 1

    trades_t = legacy_users_trades(user_no)
    report: Dict[str, Any] = {
        "user_no": slot,
        "trades_table": trades_t,
        "missing_from_pool": [],
        "pool_ghosts": [],
        "in_sync_n": 0,
        "pool_tables": [],
    }

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, monitor, status, ticket_id, trade_strategy
                FROM {trades_t}
                WHERE LOWER(TRIM(status)) IN ('pending', 'open', 'closing')
                ORDER BY id
                """
            )
            trade_rows = cur.fetchall()

            pool_by_trade: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
            schema_used = None
            for sch in schema_candidates:
                tables = _list_pool_tables(cur, sch, slot)
                if not tables:
                    continue
                schema_used = sch
                report["pool_schema"] = sch
                report["pool_tables"] = [f"{sch}.{t}" for t in tables]
                for tbl in tables:
                    try:
                        cur.execute("SAVEPOINT ats_enroll_tbl")
                        cur.execute(
                            f"""
                            SELECT trade_id, status, monitor_id
                            FROM {sch}.{tbl}
                            WHERE LOWER(TRIM(status::text)) IN ('pending', 'active', 'closing')
                            """
                        )
                        for trade_id, status, monitor_id in cur.fetchall():
                            tid = int(trade_id)
                            pool_by_trade[tid].append(
                                {
                                    "table": f"{sch}.{tbl}",
                                    "status": status,
                                    "monitor_id": monitor_id,
                                }
                            )
                        cur.execute("RELEASE SAVEPOINT ats_enroll_tbl")
                    except Exception as e:
                        try:
                            cur.execute("ROLLBACK TO SAVEPOINT ats_enroll_tbl")
                        except Exception:
                            pass
                        report.setdefault("table_errors", []).append(
                            {"table": f"{sch}.{tbl}", "error": str(e)[:160]}
                        )
                break

            trade_ids: Set[int] = set()
            for tid, monitor, status, ticket_id, strategy in trade_rows:
                tid_i = int(tid)
                trade_ids.add(tid_i)
                if tid_i not in pool_by_trade:
                    report["missing_from_pool"].append(
                        {
                            "trade_id": tid_i,
                            "monitor": monitor,
                            "status": status,
                            "ticket_id": ticket_id,
                            "strategy": strategy,
                        }
                    )
                else:
                    report["in_sync_n"] += 1

            for tid, entries in pool_by_trade.items():
                if tid not in trade_ids:
                    report["pool_ghosts"].append({"trade_id": tid, "pool": entries})

            if schema_used is None:
                report["warning"] = (
                    "No unified active_trades_15m_*/hourly_* tables found; "
                    "pool may be Redis-only — check ATS logs + live_state."
                )
    finally:
        conn.close()

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    print(f"ATS enrollment health user={report['user_no']} trades={report['trades_table']}")
    if report.get("warning"):
        print(f"WARNING: {report['warning']}")
    print(f"pool_schema={report.get('pool_schema')} tables={report.get('pool_tables')}")
    print(f"in_sync={report['in_sync_n']}")
    print(f"missing_from_pool={len(report['missing_from_pool'])}")
    for row in report["missing_from_pool"][:50]:
        print(
            f"  MISSING trade_id={row['trade_id']} status={row['status']} "
            f"monitor={row['monitor']} strategy={row.get('strategy')}"
        )
    print(f"pool_ghosts={len(report['pool_ghosts'])}")
    for row in report["pool_ghosts"][:50]:
        print(f"  GHOST trade_id={row['trade_id']} pool={row['pool']}")
    if report.get("table_errors"):
        print("table_errors:")
        for e in report["table_errors"]:
            print(f"  {e}")
    rc = 1 if report["missing_from_pool"] or report["pool_ghosts"] else 0
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
