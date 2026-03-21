# `scripts/backtest`

Offline **auto-trade backtesting** against historical `trades` (+ `monitor_list` context).

**Full initiative spec (scope, roadmap, units, supervisor parity):** [`docs/BACKTESTING.md`](../../docs/BACKTESTING.md)

## Quick start

```bash
# From repo root; use project venv if `psycopg2` is required
python3 scripts/backtest/simple_backtest.py --help
```

Example: hypothetical position 1500, optimize TTC window (minutes) for March:

```bash
python3 scripts/backtest/simple_backtest.py \
  --monitors mon_0001_10026 \
  --start 2026-03-01T00:00:00-05:00 \
  --end 2026-04-01T00:00:00-05:00 \
  --hypothetical-position 1500 \
  --optimize-ttc-window \
  --optimize-ttc-min-range 0:15 \
  --optimize-ttc-max-range 0:15
```

## Layout

| Path | Role |
|------|------|
| `simple_backtest.py` | CLI entry |
| `helpers/db.py` | Postgres (SSH / env) |
| `helpers/trade_filters.py` | TTC SQL, allowlisted filters |
| `helpers/hypothetical_trades.py` | Fees + hypo PnL / returns |
| `helpers/monitor_context.py` | `monitor_list`, strategy / cycle mode |
| `helpers/aggregates.py` | Metric SQL fragments |

**Important:** backtest TTC grids use **minutes**; `monitor_list.min_time` / `max_time` and `get_current_ttc()` use **seconds**. See `docs/BACKTESTING.md` §3.
