#!/usr/bin/env python3
"""
Reversible migration runner for PostgreSQL.

Apply or revert schema/data migrations under scripts/migrations/.
Tracks applied migrations in system.schema_migrations.

Usage:
  python3 scripts/db/run_migration.py list
  python3 scripts/db/run_migration.py up [migration_id]
  python3 scripts/db/run_migration.py down <migration_id>

Uses backend.core.config.database.get_postgresql_connection() (DB_* / REC_DB_* env).
See scripts/migrations/README.md.
"""

import os
import sys

# Project root (run_migration lives in scripts/db/; migrations live in scripts/migrations/)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SCRIPTS_DIR)
MIGRATIONS_DIR = os.path.join(SCRIPTS_DIR, "migrations")

sys.path.insert(0, PROJECT_ROOT)


def get_conn():
    from backend.core.config.database import get_postgresql_connection
    return get_postgresql_connection()


def ensure_tracking_table(conn):
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS system;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS system.schema_migrations (
                migration_id TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ DEFAULT now()
            );
        """)
    conn.commit()


def list_migrations(conn):
    ensure_tracking_table(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT migration_id, applied_at FROM system.schema_migrations ORDER BY applied_at;"
        )
        rows = cur.fetchall()
    return rows


def migration_files():
    if not os.path.isdir(MIGRATIONS_DIR):
        return []
    seen = set()
    for name in sorted(os.listdir(MIGRATIONS_DIR)):
        if name.endswith(".up.sql"):
            migration_id = name[:-len(".up.sql")]
            if migration_id not in seen:
                seen.add(migration_id)
                up_path = os.path.join(MIGRATIONS_DIR, f"{migration_id}.up.sql")
                down_path = os.path.join(MIGRATIONS_DIR, f"{migration_id}.down.sql")
                if os.path.isfile(down_path):
                    yield migration_id, up_path, down_path


def run_sql_file(conn, path):
    with open(path, "r") as f:
        sql = f.read()
    with conn.cursor() as cur:
        cur.execute(sql)


def apply_one(conn, migration_id):
    for mid, up_path, down_path in migration_files():
        if mid == migration_id:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM system.schema_migrations WHERE migration_id = %s;",
                    (migration_id,),
                )
                if cur.fetchone():
                    raise RuntimeError(f"Migration already applied: {migration_id}")
            run_sql_file(conn, up_path)
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO system.schema_migrations (migration_id) VALUES (%s);",
                    (migration_id,),
                )
            conn.commit()
            return
    raise FileNotFoundError(f"No migration pair for: {migration_id}")


def revert_one(conn, migration_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM system.schema_migrations WHERE migration_id = %s;",
            (migration_id,),
        )
        if not cur.fetchone():
            raise RuntimeError(f"Migration not applied: {migration_id}")
    for mid, up_path, down_path in migration_files():
        if mid == migration_id:
            run_sql_file(conn, down_path)
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM system.schema_migrations WHERE migration_id = %s;",
                    (migration_id,),
                )
            conn.commit()
            return
    raise FileNotFoundError(f"No migration pair for: {migration_id}")


def apply_pending(conn):
    ensure_tracking_table(conn)
    applied = {row[0] for row in list_migrations(conn)}
    for migration_id, up_path, down_path in migration_files():
        if migration_id in applied:
            continue
        run_sql_file(conn, up_path)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO system.schema_migrations (migration_id) VALUES (%s);",
                (migration_id,),
            )
        conn.commit()
        print(f"  Applied: {migration_id}")
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: run_migration.py list | up [migration_id] | down <migration_id>", file=sys.stderr)
        sys.exit(1)
    cmd = sys.argv[1].lower()
    conn = get_conn()
    if not conn:
        print("Failed to connect to database.", file=sys.stderr)
        sys.exit(1)
    try:
        if cmd == "list":
            ensure_tracking_table(conn)
            rows = list_migrations(conn)
            for mid, applied_at in rows:
                print(f"  {mid}  ({applied_at})")
        elif cmd == "up":
            if len(sys.argv) >= 3:
                migration_id = sys.argv[2]
                ensure_tracking_table(conn)
                apply_one(conn, migration_id)
                print(f"Applied: {migration_id}")
            else:
                apply_pending(conn)
        elif cmd == "down":
            if len(sys.argv) < 3:
                print("Usage: run_migration.py down <migration_id>", file=sys.stderr)
                sys.exit(1)
            migration_id = sys.argv[2]
            ensure_tracking_table(conn)
            revert_one(conn, migration_id)
            print(f"Reverted: {migration_id}")
        else:
            print("Unknown command. Use list | up | down.", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
