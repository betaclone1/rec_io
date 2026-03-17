#!/usr/bin/env python3
"""
Standalone script: every 0.5s, set test_value_1..20 on the first row of testing.redis_basic_test
to random integers 0-9. Uses rec_io DB; trigger will NOTIFY so the Redis switchboard test UI updates.

Run from project root: PYTHONPATH=$(pwd) venv/bin/python scripts/redis_basic_test_randomizer.py
"""
import os
import sys
import time
import random

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from backend.core.config.database import get_postgresql_connection

COLUMNS = [f"test_value_{i}" for i in range(1, 21)]


def ensure_one_row(conn):
    cur = conn.cursor()
    cur.execute("SELECT id FROM testing.redis_basic_test LIMIT 1")
    if cur.fetchone() is None:
        cols = ", ".join(COLUMNS)
        placeholders = ", ".join(["0"] * 20)
        cur.execute(f"INSERT INTO testing.redis_basic_test ({cols}) VALUES ({placeholders})")
        conn.commit()
    cur.close()


def randomize_row(conn):
    cur = conn.cursor()
    cur.execute("SELECT id FROM testing.redis_basic_test LIMIT 1")
    row = cur.fetchone()
    if not row:
        ensure_one_row(conn)
        cur.execute("SELECT id FROM testing.redis_basic_test LIMIT 1")
        row = cur.fetchone()
    if not row:
        return
    row_id = row[0]
    values = [random.randint(0, 9) for _ in COLUMNS]
    set_clause = ", ".join(f"{c} = %s" for c in COLUMNS)
    cur.execute(f"UPDATE testing.redis_basic_test SET {set_clause} WHERE id = %s", values + [row_id])
    conn.commit()
    cur.close()


def main():
    conn = get_postgresql_connection()
    if not conn:
        print("Failed to connect to DB", file=sys.stderr)
        sys.exit(1)
    ensure_one_row(conn)
    print("Randomizing test_value_1..20 every 0.5s (Ctrl+C to stop)")
    try:
        while True:
            randomize_row(conn)
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    conn.close()


if __name__ == "__main__":
    main()
