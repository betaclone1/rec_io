#!/usr/bin/env python3
from backend.core.config.database import get_system_postgresql_connection

conn = get_system_postgresql_connection()
cur = conn.cursor()
cur.execute(
    """
    SELECT id, name, strategy, symbol, market, auto_trade,
           verification_period_enabled, verification_period_seconds,
           stop_verification_period_enabled, stop_verification_period_seconds,
           min_buffer_pct, min_probability, max_probability,
           min_movement, max_movement, min_ask, max_ask, min_time, max_time,
           min_fill_price
    FROM users_0001.monitor_list_0001 WHERE id = 10046
    """
)
labs = [
    "id",
    "name",
    "strategy",
    "symbol",
    "market",
    "auto_trade",
    "verification_period_enabled",
    "verification_period_seconds",
    "stop_verification_period_enabled",
    "stop_verification_period_seconds",
    "min_buffer_pct",
    "min_probability",
    "max_probability",
    "min_movement",
    "max_movement",
    "min_ask",
    "max_ask",
    "min_time",
    "max_time",
    "min_fill_price",
]
row = cur.fetchone()
print("MONITOR 10046:")
for a, b in zip(labs, row):
    print(f"  {a}={b!r}")
conn.close()
