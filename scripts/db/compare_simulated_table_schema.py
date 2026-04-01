#!/usr/bin/env python3
"""
Compare users.trades_simulated_0001 (and related) between local and prod DB.
Usage: PYTHONPATH=$(pwd) venv/bin/python scripts/compare_simulated_table_schema.py
Uses DB_* env vars (or REC_DB_* from .env). Prod side requires REC_PROD_DB_HOST or REC_PROD_SSH_HOST.
"""
import os
import sys

# Load .env from project root so DB_* or REC_DB_* are set
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
except ImportError:
    pass
# Map REC_DB_* to DB_* if DB_* not set (some configs use REC_DB_*)
_m = [('REC_DB_HOST', 'DB_HOST'), ('REC_DB_PORT', 'DB_PORT'), ('REC_DB_NAME', 'DB_NAME'), ('REC_DB_USER', 'DB_USER'), ('REC_DB_PASS', 'DB_PASSWORD')]
for rec_k, db_k in _m:
    if os.getenv(rec_k) and not os.getenv(db_k):
        os.environ[db_k] = os.getenv(rec_k)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from backend.core.config.database import get_database_config

from backend.core.prod_target import get_production_db_host

def get_conn(host_override=None):
    import psycopg2
    cfg = get_database_config()
    if host_override:
        cfg = {**cfg, 'host': host_override}
    return psycopg2.connect(**cfg)

def get_columns(conn, schema, table):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """, (schema, table))
        return cur.fetchall()

def get_pk(conn, schema, table):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relname = %s AND i.indisprimary
              AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY array_position(i.indkey, a.attnum)
        """, (schema, table))
        return [r[0] for r in cur.fetchall()]

def get_sequence(conn, schema, table, column):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT pg_get_serial_sequence(%s::regclass::text, %s)
        """, (f'"{schema}"."{table}"', column))
        row = cur.fetchone()
        return row[0] if row and row[0] else None

def main():
    local_host = os.getenv('DB_HOST', 'localhost')
    prod_host = get_production_db_host()
    if not prod_host:
        print(
            "Set REC_PROD_DB_HOST or REC_PROD_SSH_HOST for the production host, then re-run.",
            file=sys.stderr,
        )
        sys.exit(1)
    schema, table = 'users', 'trades_simulated_0001'

    print("=== LOCAL (host=%s) ===" % local_host)
    try:
        local_conn = get_conn(None)
        local_cols = get_columns(local_conn, schema, table)
        local_pk = get_pk(local_conn, schema, table)
        local_seq = get_sequence(local_conn, schema, table, 'id') if local_cols else None
        local_conn.close()
    except Exception as e:
        print("Local connection failed:", e)
        local_cols = []
        local_pk = []
        local_seq = None

    if local_cols:
        print("Columns:", len(local_cols))
        for c in local_cols:
            print("  ", c[0], c[1], "NULL" if c[2] == 'YES' else "NOT NULL", c[3] or "")
        print("Primary key:", local_pk)
        print("id sequence:", local_seq)
    else:
        print("Table missing or no columns.")

    print("\n=== PROD (host=%s) ===" % prod_host)
    try:
        prod_conn = get_conn(prod_host)
        prod_cols = get_columns(prod_conn, schema, table)
        prod_pk = get_pk(prod_conn, schema, table)
        prod_seq = get_sequence(prod_conn, schema, table, 'id') if prod_cols else None
        prod_conn.close()
    except Exception as e:
        print("Prod connection failed:", e)
        prod_cols = []
        prod_pk = []
        prod_seq = None

    if prod_cols:
        print("Columns:", len(prod_cols))
        for c in prod_cols:
            print("  ", c[0], c[1], "NULL" if c[2] == 'YES' else "NOT NULL", c[3] or "")
        print("Primary key:", prod_pk)
        print("id sequence:", prod_seq)
    else:
        print("Table missing or no columns.")

    print("\n=== DIFF ===")
    local_names = {c[0] for c in local_cols}
    prod_names = {c[0] for c in prod_cols}
    only_local = local_names - prod_names
    only_prod = prod_names - local_names
    if only_local:
        print("Only on LOCAL:", sorted(only_local))
    if only_prod:
        print("Only on PROD:", sorted(only_prod))
    if local_pk != prod_pk:
        print("PK diff: local=%s prod=%s" % (local_pk, prod_pk))
    if local_seq != prod_seq:
        print("id sequence diff: local=%s prod=%s" % (local_seq, prod_seq))
    if not only_local and not only_prod and local_pk == prod_pk and local_seq == prod_seq:
        # compare types
        local_map = {c[0]: (c[1], c[2], c[3]) for c in local_cols}
        prod_map = {c[0]: (c[1], c[2], c[3]) for c in prod_cols}
        for name in sorted(local_map.keys()):
            if local_map[name] != prod_map.get(name):
                print("Column %s differs: local=%s prod=%s" % (name, local_map[name], prod_map.get(name)))
        if not any(local_map.get(n) != prod_map.get(n) for n in local_map):
            print("No column type/default differences.")
    print("Done.")

if __name__ == '__main__':
    main()
