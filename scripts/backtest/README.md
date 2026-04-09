# `scripts/backtest`

Offline **auto-trade backtesting** against historical `trades` (+ `monitor_list` context).

**Always run scripts with the repo venv:** `.venv/bin/python3 ...` (not system `python3`) so `psycopg2` and other deps resolve.

**Full initiative spec (scope, roadmap, units, supervisor parity):** [`docs/BACKTESTING.md`](../../docs/BACKTESTING.md)

**Hypothetical entry / peer fill pricing (methodology, holdouts, live vs paper, pipeline):** [`docs/BACKTEST_PRICE_ESTIMATOR.md`](../../docs/BACKTEST_PRICE_ESTIMATOR.md)

## CI: Kalshi quote naming (run before you push)

GitHub Actions runs [`scripts/dev/check_no_legacy_kalshi_quotes.sh`](../dev/check_no_legacy_kalshi_quotes.sh) on **`backend/`**, **`frontend/`**, and **`scripts/backtest/`** (`*.py`, `*.js`, `*.html`). It fails if **bare** Kalshi REST/WebSocket cent-field names appear: `yes_ask`, `no_ask`, `yes_bid`, `no_bid` (word boundaries).

**Allowed:** dollar-style names such as `yes_ask_dollars` / `no_bid_dollars`, and a tiny allowlist of true wire parsers (see the script). **Not scanned:** this `README.md` and other non-matching paths.

From repo root, after editing anything under `scripts/backtest/` (or the other trees above):

```bash
bash scripts/dev/check_no_legacy_kalshi_quotes.sh
```

If that prints `OK`, the Actions step will pass for this rule.

## Quick start

```bash
# From repo root — use project venv (required for psycopg2)
.venv/bin/python3 scripts/backtest/core_backtester.py --help

Load Kalshi 1m candles + strike/result + price-history columns (`open`, `high`, …) from `historical_data.btc_price_history` / `eth_price_history` (KXBTC/KXETH tickers) into `backtest.backtest_1m_<slug>` (any tickers; creates tables as needed):

```bash
# REC_IO_BACKTEST_DB defaults to local (see scripts/backtest/helpers/db.py); set =prod only for SSH prod.
.venv/bin/python3 scripts/backtest/core_backtester.py \
  --ingest-kalshi-tickers KXBTC15M-26MAR051345-45
```
.venv/bin/python3 scripts/backtest/price_estimator.py --help
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

**Important:** backtest TTC grids use **minutes**; `monitor_list.min_time` / `max_time` and `get_current_ttc()` use **seconds**. See `docs/BACKTESTING.md` §3.

**AES parity:** when you change **`backend/auto_entry_supervisor.py`** entry behavior, update the offline mirrors documented in **`docs/BACKTESTING.md` §2.1** (e.g. `helpers/htc_aes_replay.py`, `backend/util/auto_entry_htc_gates.py` for Hourly HTC gates).
