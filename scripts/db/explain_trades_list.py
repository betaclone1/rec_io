#!/usr/bin/env python3
"""
Print EXPLAIN (ANALYZE, BUFFERS) for the tenant trade list query shape used by GET /trades
(slim column union, optional date bounds, ORDER BY id DESC, LIMIT).

Uses the same SQL builders as read_api / trades_list_query. Connects via
get_postgresql_connection() (tenant REC_USER_SCHEMA / default users_0001).

Examples:
  python3 scripts/db/explain_trades_list.py --slot 0001
  python3 scripts/db/explain_trades_list.py --slot 0001 --min-date 2025-01-01 --max-date 2025-06-30 --page-size 500
"""

from __future__ import annotations

import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
sys.path.insert(0, PROJECT_ROOT)


def main() -> None:
    parser = argparse.ArgumentParser(description="EXPLAIN ANALYZE for GET /trades list SQL")
    parser.add_argument(
        "--slot",
        default=os.environ.get("REC_USER_NO", "0001").strip().zfill(4)[:4],
        help="Four-digit tenant slot (default REC_USER_NO or 0001)",
    )
    parser.add_argument("--min-date", default=None, help="YYYY-MM-DD inclusive lower bound on date text")
    parser.add_argument("--max-date", default=None, help="YYYY-MM-DD inclusive upper bound on date text")
    parser.add_argument(
        "--page-size",
        type=int,
        default=501,
        help="LIMIT for explain (default 501 = one keyset page + sentinel)",
    )
    args = parser.parse_args()
    slot = args.slot
    if len(slot) != 4 or not slot.isdigit():
        raise SystemExit("--slot must be four digits")

    from fastapi import HTTPException

    from backend.core.config.database import get_postgresql_connection
    from backend.core.trades_list_query import (
        TRADES_LIST_HTTP_COLUMNS,
        normalize_trades_date_query_param,
    )
    from backend.util.trade_log_archivist import (
        fetch_master_trades_column_names,
        union_trades_with_archives_select_columns,
    )

    conn = get_postgresql_connection(tenant_user_no=slot)
    if not conn:
        raise SystemExit("No database connection (check DB_* / REC_DB_* / tenant env)")

    try:
        min_d = normalize_trades_date_query_param("min_date", args.min_date)
        max_d = normalize_trades_date_query_param("max_date", args.max_date)
    except HTTPException as e:
        raise SystemExit(str(e.detail)) from e

    where_parts = []
    params: list = []
    if min_d:
        where_parts.append("date >= %s")
        params.append(min_d)
    if max_d:
        where_parts.append("date <= %s")
        params.append(max_d)
    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
    limit_sql = " LIMIT %s"
    exec_params = tuple(params) + (int(args.page_size),)

    with conn.cursor() as cur:
        if not fetch_master_trades_column_names(cur, slot):
            raise SystemExit(f"No columns for tenant trades table (slot={slot})")
        union_sql, _ = union_trades_with_archives_select_columns(cur, slot, TRADES_LIST_HTTP_COLUMNS)
        inner = f"""
        SELECT * FROM ({union_sql}) AS all_trades
        {where_sql}
        ORDER BY id DESC
        {limit_sql}
        """
        cur.execute("EXPLAIN (ANALYZE, BUFFERS) " + inner, exec_params)
        rows = cur.fetchall()
    conn.close()

    for row in rows:
        print(row[0])


if __name__ == "__main__":
    main()
