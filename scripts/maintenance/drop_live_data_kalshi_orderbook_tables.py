#!/usr/bin/env python3
"""Drop every ``live_data.orderbook_kalshi_*`` table and truncate the sidecar registry (autocommit per DROP).

Avoids ``max_locks_per_transaction`` exhaustion from dropping thousands of tables in one transaction.
Uses the same DB env as other backend scripts (DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT).
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import psycopg2
from psycopg2 import sql

from backend.core.time_eastern import merge_psycopg2_connect_kwargs


def main() -> int:
    conn = psycopg2.connect(
        **merge_psycopg2_connect_kwargs(
            {
                "host": os.getenv("DB_HOST", "localhost"),
                "port": int(os.getenv("DB_PORT", "5432")),
                "dbname": os.getenv("DB_NAME", "rec_io_db"),
                "user": os.getenv("DB_USER", "rec_io_user"),
                "password": os.getenv("DB_PASSWORD", "rec_io_password"),
            }
        )
    )
    conn.set_session(autocommit=True)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.relname
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'live_data'
          AND c.relkind = 'r'
          AND c.relname ~ '^orderbook_kalshi_[a-z0-9_]+$'
        ORDER BY c.relname
        """
    )
    names = [row[0] for row in cur.fetchall() or ()]
    for i, rel in enumerate(names, 1):
        q = sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
            sql.Identifier("live_data"),
            sql.Identifier(rel),
        )
        cur.execute(q)
        if i % 200 == 0:
            print("dropped", i, "...", flush=True)
    cur.execute(sql.SQL("TRUNCATE TABLE {}").format(sql.Identifier("live_data", "kalshi_orderbook_sidecar_registry")))
    print("dropped", len(names), "tables; registry truncated")
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
