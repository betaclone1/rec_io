# Diagnostics scripts

One-off or occasional checks and cleanup.

- **sample_live_trades_fees_for_validation.py** — Sample live closed trades with recorded fees (position >= 100 only) and compare actual fees to Kalshi taker formula. `--limit N`, `--seed S`, `--no-random`. Read-only.
- **trace_trade_fees.py** — Trace how total fees for one trade were determined: prints trade row and open/close order rows from `users.orders_0001`. We only pay taker fees. Usage: `trace_trade_fees.py <trade_id>`. Read-only.
- **check_kalshi_account_endpoints.py** — Check Kalshi account API endpoints (e.g. deposits/withdrawals).
- **check_monitor_confirmed_failures.py** — Report trades with `monitor_confirmed = FALSE` by monitor and strategy (NULL vs high==low). Run periodically to see if the issue persists or expands. `--days N` (default 7), `--append-log` to append a one-line summary to `monitor_confirmed_failures_log.txt`.
- **view_installation_logs.py** — View installation logs.
- **remove_legacy_credentials.sh** — Clean up legacy credentials.

Run from project root as needed.
