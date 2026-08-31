#!/usr/bin/env python3
from backend.core.config.database import get_system_postgresql_connection

TRADE_ID = 47449
conn = get_system_postgresql_connection()
cur = conn.cursor()
cur.execute(
    """
    SELECT column_name FROM information_schema.columns
    WHERE table_schema='users_0001' AND table_name='trades_0001'
    ORDER BY ordinal_position
    """
)
cols = [r[0] for r in cur.fetchall()]
cur.execute("SELECT * FROM users_0001.trades_0001 WHERE id = %s", (TRADE_ID,))
d = dict(zip(cols, cur.fetchone()))
print("ALL NON-EMPTY COLS:")
for k, v in d.items():
    if v is not None and v != "" and v != 0:
        print(f"  {k}={v!r}")

try:
    cur.execute(
        """
        SELECT id, name, strategy, symbol, market, auto_trade,
               entry_verification_period_enabled, entry_verification_period_seconds,
               min_buffer_pct, min_probability, max_probability,
               min_movement, max_movement, min_ask, max_ask, min_time, max_time,
               min_fill_price
        FROM users_0001.monitor_list_0001 WHERE id = 10046
        """
    )
    labels = [
        "id","name","strategy","symbol","market","auto_trade",
        "entry_verification_period_enabled","entry_verification_period_seconds",
        "min_buffer_pct","min_probability","max_probability",
        "min_movement","max_movement","min_ask","max_ask","min_time","max_time",
        "min_fill_price",
    ]
    row = cur.fetchone()
    print("MONITOR:")
    for lab, val in zip(labels, row):
        print(f"  {lab}={val!r}")
except Exception as e:
    conn.rollback()
    print("MONITOR FAIL", e)
    cur.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema='users_0001' AND table_name='monitor_list_0001'
          AND column_name LIKE '%verif%' OR (
            table_schema='users_0001' AND table_name='monitor_list_0001'
            AND column_name LIKE '%buffer%'
          )
        """
    )
    print("verif/buffer cols", cur.fetchall())

conn.close()
