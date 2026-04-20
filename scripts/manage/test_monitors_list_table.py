#!/usr/bin/env python3
"""
Smoke test: monitor_list_<slot> exists and accepts a sample INSERT (dev / local only).

Uses REC_USER_NO / REC_DEFAULT_USER_SCHEMA (see default_pool_user_number).
"""

from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.core.config.database import get_postgresql_connection, init_database
from backend.core.port_config import default_pool_user_number
from backend.core.tenant_context import TenantContext
from backend.core.tenant_legacy_sql import legacy_users_monitor_list


def test_monitors_list_table() -> bool:
    slot = default_pool_user_number()
    ctx = TenantContext.from_schema(f"users_{slot}")
    mon_table = legacy_users_monitor_list(slot)
    mon_suffix = f"monitor_list_{slot}"
    seq_name = f"monitor_list_{slot}_id_seq"

    print(f"Testing {mon_table} (schema {ctx.pg_schema})...")
    success, message = init_database()
    if not success:
        print(f"Database initialization failed: {message}")
        return False
    print("Database initialized OK")

    conn = get_postgresql_connection(tenant_user_no=slot)
    if not conn:
        print("Failed to connect to database")
        return False

    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = %s AND table_name = %s
            );
            """,
            (ctx.pg_schema, mon_suffix),
        )
        if not cursor.fetchone()[0]:
            print(f"Table missing: {ctx.pg_schema}.{mon_suffix}")
            return False
        print(f"Table exists: {ctx.pg_schema}.{mon_suffix}")

        cursor.execute(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.sequences
                WHERE sequence_schema = %s AND sequence_name = %s
            );
            """,
            (ctx.pg_schema, seq_name),
        )
        if not cursor.fetchone()[0]:
            print(f"Sequence missing: users.{seq_name}")
            return False
        print(f"Sequence exists: {ctx.pg_schema}.{seq_name}")

        cursor.execute(f'SELECT last_value FROM "{ctx.pg_schema}"."{seq_name}";')
        print(f"Current sequence value: {cursor.fetchone()[0]}")

        cursor.execute(
            f"""
            INSERT INTO {mon_table} (
                name, symbol, strategy, auto_trade, auto_trade_status,
                trades, win_loss, ret_pct, pnl, bankroll_allotment, status
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            ) RETURNING id;
            """,
            (
                "Smoke Test Monitor",
                "BTC",
                "momentum_based",
                True,
                "inactive",
                0,
                0.0,
                0.0,
                0.0,
                25.0,
                "active",
            ),
        )
        mid = cursor.fetchone()[0]
        print(f"Inserted test row id={mid}")

        cursor.execute(f"DELETE FROM {mon_table} WHERE id = %s", (mid,))
        conn.commit()
        print("Removed test row.")
        return True
    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(0 if test_monitors_list_table() else 1)
