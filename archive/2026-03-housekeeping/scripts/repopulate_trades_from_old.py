#!/usr/bin/env python3
"""
Repopulate users.trades_0001 from an OLD/backup table in chronological order
so that new ids align (oldest = smallest id, newest = largest id).

Prerequisites:
  1. Create backup: CREATE TABLE users.trades_OLD_0001 (LIKE users.trades_0001 INCLUDING ALL);
  2. Copy data:    INSERT INTO users.trades_OLD_0001 SELECT * FROM users.trades_0001;
  3. Clear main:  TRUNCATE users.trades_0001 RESTART IDENTITY;

Usage:
  python3 scripts/repopulate_trades_from_old.py [source_table]
  source_table: e.g. users.trades_OLD_0001 or users.trades_0001_OLD (default: users.trades_OLD_0001)

Order: rows are inserted ORDER BY created_at, closed_at, date, time (oldest first) so ids match chronology.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def get_columns(conn, schema: str, table: str):
    """Return ordered list of column names for the table."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """, (schema, table))
        return [r[0] for r in cur.fetchall()]


def main():
    source = (sys.argv[1] if len(sys.argv) > 1 else "users.trades_OLD_0001").strip()
    if "." in source:
        schema_src, table_src = source.split(".", 1)
    else:
        schema_src = "users"
        table_src = source

    from backend.core.config.database import get_postgresql_connection
    conn = get_postgresql_connection()
    if not conn:
        print("Could not connect to database.")
        sys.exit(1)

    # Resolve target
    schema_tgt, table_tgt = "users", "trades_0001"

    cols_src = get_columns(conn, schema_src, table_src)
    cols_tgt = get_columns(conn, schema_tgt, table_tgt)
    if not cols_src:
        print(f"Source table {schema_src}.{table_src} not found or has no columns.")
        conn.close()
        sys.exit(1)
    if not cols_tgt:
        print(f"Target table {schema_tgt}.{table_tgt} not found.")
        conn.close()
        sys.exit(1)

    # Insert list: all target columns except id (so serial generates new ids)
    cols_tgt_no_id = [c for c in cols_tgt if c != "id"]
    # Only include columns that exist in both
    cols_both = [c for c in cols_tgt_no_id if c in cols_src]
    if not cols_both:
        print("No common columns between source and target (excluding id).")
        conn.close()
        sys.exit(1)

    # Order by timestamp: oldest first.
    order_cols = [c for c in ["created_at", "closed_at", "date", "time"] if c in cols_src]
    if not order_cols:
        order_cols = [cols_src[0]]
    order_sql = " ORDER BY " + ", ".join(f'"{c}" ASC NULLS LAST' for c in order_cols)

    quoted = lambda c: f'"{c}"' if c in ("from", "to", "order", "date", "time") else c
    cols_sel = ", ".join(quoted(c) for c in cols_both)
    cols_ins = ", ".join(quoted(c) for c in cols_both)
    full_src = f'"{schema_src}"."{table_src}"'
    full_tgt = f'"{schema_tgt}"."{table_tgt}"'
    sql = f'INSERT INTO {full_tgt} ({cols_ins}) SELECT {cols_sel} FROM {full_src}{order_sql}'

    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {full_src}")
        n_src = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM {full_tgt}")
        n_tgt_before = cur.fetchone()[0]

    print(f"Source: {full_src} ({n_src} rows)")
    print(f"Target: {full_tgt} (before: {n_tgt_before} rows)")
    print(f"Columns to copy: {len(cols_both)}")
    if n_tgt_before > 0:
        print("Target table is not empty. Clear it first if you want to repopulate from scratch.")
        conn.close()
        sys.exit(1)
    if n_src == 0:
        print("Source has no rows. Nothing to do.")
        conn.close()
        return

    with conn.cursor() as cur:
        cur.execute(sql)
        inserted = cur.rowcount
    conn.commit()
    print(f"Inserted {inserted} rows into {full_tgt} (oldest to newest).")
    conn.close()


if __name__ == "__main__":
    main()
