# `scripts/backtest`

Offline **auto-trade backtesting** against historical `trades` (+ `monitor_list` context).

**Always run scripts with the repo venv:** `.venv/bin/python3 ...` (not system `python3`) so `psycopg2` and other deps resolve.

**Full initiative spec (scope, roadmap, units, supervisor parity):** [`docs/BACKTESTING.md`](../../docs/BACKTESTING.md)

**Hypothetical entry / peer fill pricing (methodology, holdouts, live vs paper, pipeline):** [`docs/BACKTEST_PRICE_ESTIMATOR.md`](../../docs/BACKTEST_PRICE_ESTIMATOR.md)

## Quick start

```bash
# From repo root — use project venv (required for psycopg2)
.venv/bin/python3 scripts/backtest/core_backtester.py --help
.venv/bin/python3 scripts/backtest/price_estimator.py --help
```

Load Kalshi 1m candles + strike/result + price-history columns (`open`, `high`, …) from `historical_data.btc_price_history` / `eth_price_history` (KXBTC/KXETH tickers) into `backtest.backtest_1m_<slug>` (any tickers; creates tables as needed):

```bash
# REC_IO_BACKTEST_DB defaults to local (see scripts/backtest/helpers/db.py); set =prod only for SSH prod.
.venv/bin/python3 scripts/backtest/core_backtester.py \
  --ingest-kalshi-tickers KXBTC15M-26MAR051345-45
```

## Strike archive → tick HTC replay (live-parity path)

**Preferred method** when you have **`historical_data.strike_table_master`** populated for a Kalshi market (same row shape as live `strike_table_15m` / hourly inserts, plus `market_ticker`). This replays **Hourly HTC–style gates** on **actual strike snapshots** at the cadence they were archived, then sizes a hypothetical position with **`--replay-bankroll`** / **`--replay-allocation-pct`**.

**Not the same as** `--build-tick-backtest`, which synthesizes ticks from `live_price_log_1s_*` + `kalshi_historical_trades_api` (useful when the archive is empty).

**Steps** (from repo root, venv):

1. **Materialize** `backtest.tick_backtest_<slug>` from the archive:

   ```bash
   REC_USER_SCHEMA=users_0001 \
   PYTHONPATH=$(pwd) .venv/bin/python3 scripts/backtest/core_backtester.py \
     --build-tick-backtest-from-archive 'KXETH15M-26APR151700-00'
   ```

2. **Replay** with **monitor** entry settings (`users…monitor_list_*` via tenant rewrite) or strategy defaults:

   ```bash
   REC_USER_SCHEMA=users_0001 \
   PYTHONPATH=$(pwd) .venv/bin/python3 scripts/backtest/core_backtester.py \
     --replay-htc-market 'KXETH15M-26APR151700-00' \
     --replay-from-tick-backtest \
     --replay-monitor-id 10027 \
     --replay-monitor-user 0001 \
     --replay-bankroll 10000 \
     --replay-allocation-pct 20
   ```

**Connection:** `helpers/db.py` — local DB by default; `REC_IO_BACKTEST_DB=prod` uses an SSH tunnel (set `REC_IO_BACKTEST_DB_HOST` or `REC_IO_BACKTEST_SSH`). **Tenant SQL:** use **`REC_USER_SCHEMA=users_NNNN`** (e.g. `users_0001`) so `users.*` in replay queries rewrites to the correct tenant schema.

**Settlement on tick replay:** `market_result` for expiry PnL comes from **`resolve_floor_strike_and_market_result`** (Kalshi/API metadata), not the archive `market_result` column.

**Implementation:** `helpers/tick_backtest_build.py` (`build_tick_backtest_from_strike_archive`), `helpers/htc_backtest_replay.py`, `core_backtester.py`. Spec and limitations: **`docs/BACKTESTING.md`** §5.5.

### Setting grid sweep (many markets × many setting combos)

When enough archive history exists, **`htc_archive_setting_sweep.py`** walks a time window, finds markets in **`strike_table_master`**, rebuilds **window-sliced** tick tables, and runs the **Cartesian product** of override grids (default three axes: **`max_time`** seconds high→low, **`min_probability`**, **`stop_loss_price`** in dollars). Ranks combos by **`--objective`** (`sum_pnl`, `win_rate`, …). **Compounding** is on by default (equity rolls forward in market order); **`--no-compound`** fixes bankroll per replay. **`--persist-trades`** writes rows to **`backtest.grid_sweep_trades`** (mirror of tenant **`trades`** + batch/synthetic ids). See **`docs/BACKTESTING.md`** §5.6.

```bash
REC_USER_SCHEMA=users_0001 PYTHONPATH=$(pwd) .venv/bin/python3 scripts/backtest/htc_archive_setting_sweep.py --help
```

Example: hypothetical position 1500, optimize TTC window (minutes) for March:

```bash
.venv/bin/python3 scripts/backtest/core_backtester.py \
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
| `core_backtester.py` | CLI entry |
| `backtest_market_simulator.py` | One-ticker 1m walk; **default** `--storage testing` → `testing."candlesticks_1m_<ticker>"` on **local** (`REC_IO_BACKTEST_DB=local` + `.venv/bin/python3`). See script docstring. |
| `price_estimator.py` | Peer medians / k-NN; `--paper paper` vs live; `--spot-check-dual IDS`; `--peer-holdout` |
| `helpers/db.py` | Postgres (SSH / env) |
| `helpers/trade_filters.py` | TTC SQL, allowlisted filters |
| `helpers/hypothetical_trades.py` | Fees + hypo PnL / returns |
| `helpers/monitor_context.py` | `monitor_list`, strategy / cycle mode |
| `helpers/aggregates.py` | Metric SQL fragments |
| `helpers/kalshi_candles_1m.py` | Kalshi 1m candle fetch + upsert (shared with testing populate scripts) |
| `helpers/kalshi_market_candles_scratch.py` | CLI: load ephemeral `historical_data.kalshi_candles_1m_*_YYYYMMDD`; `--cleanup-only` (hourly, 15m, etc. — see BACKTESTING §5.4) |
| `helpers/htc_aes_replay.py` | Replay helpers mirroring AES strike order / 15m TTC; keep in sync with supervisor per BACKTESTING §2.1 |
| `helpers/tick_backtest_build.py` | `build_tick_backtest_table` (1s log + trades) and **`build_tick_backtest_from_strike_archive`** (`historical_data.strike_table_master` → `backtest.tick_backtest_*`) |
| `helpers/htc_backtest_replay.py` | Single-market HTC replay on `backtest_1m_*` or **`tick_backtest_*`** (`--replay-from-tick-backtest`) |
| `helpers/htc_setting_grid_sweep.py` | Cartesian monitor overrides × many archive markets; used by **`htc_archive_setting_sweep.py`** |
| `helpers/grid_sweep_trades.py` | INSERT into **`backtest.grid_sweep_trades`** when **`--persist-trades`** |
| `htc_archive_setting_sweep.py` | CLI: grid sweep over a window (§5.6) |
| `cycle_replay_parity.py` | Sealed cycle-package replay vs live `trades_*` (entry/exit times first) |

## Cycle packages → live diagnostics

Packages under `backend/util/cycle_replay/` are not only for strategy economics. When replay enters earlier (or at all) and live did not, treat that as a **live-workflow investigation** first: classify remediate vs accept pipeline reality; only then consider explicit simulated lag in replay. See **`docs/BACKTESTING.md` §2.3**.

**Important:** backtest TTC grids use **minutes**; `monitor_list.min_time` / `max_time` and `get_current_ttc()` use **seconds**. See `docs/BACKTESTING.md` §3.

**AES parity:** when you change **`backend/auto_entry_supervisor.py`** entry behavior, update the offline mirrors documented in **`docs/BACKTESTING.md` §2.1** (e.g. `helpers/htc_aes_replay.py`, `backend/util/auto_entry_htc_gates.py` for Hourly HTC gates).
