# DB structure and data flow (analyst reference)

Summary of PostgreSQL schemas, key tables, how they are populated, and how values are calculated. For full column definitions see `docs/MASTER_DB_SCHEMA_REFERENCE.md`.

---

## Dev vs production (critical for analysis)

- **DEV** = this machine (local). Local DB = dev DB. Kept in sync with production on every release (schema/code). Live trade monitors are **not** run here for real strategy operation—only for code testing when needed.
- **PRODUCTION** = the server running live trading monitors 24/7 with real, calibrated strategies. Production DB holds the trade history and monitor state that reflect actual strategy performance.

**For trade and strategy analysis:** Almost always use **production DB** when analyzing trade performance (real, paper, or simulated), doing strategy deep dives, backtests on real trade history, or monitor tuning. Dev DB is for schema checks, script testing, or dev-only experiments—not for conclusions about how strategies perform in production.

---

## Schemas overview

| Schema | Purpose |
|--------|--------|
| **users** | Live/simulated trades, monitors, strategies, account (balance, history, fills, orders, positions, settlements), preferences, active_trades per monitor. |
| **live_data** | Real-time price ticks, strike tables, Kalshi market snapshots, symbol status. |
| **historical_data** | OHLCV + momentum/volatility/movement (and percentiles) per symbol, 1m bars. |
| **analytics** | Lookup tables (probability by TTC×buffer×momentum), fingerprints, profiles (momentum/volatility/movement/price). |
| **system** | health_status, installation_access_log. |
| **core** | system_state. |

---

## Users schema — trades and related

### users.trades_0001 (live trades)

**Live = real money:** Rows where `paper_trade` and `test_filter` are both FALSE. Those are real orders sent to Kalshi with real money. Any analysis of "live" PnL or "live trades" must filter: `(paper_trade IS NOT TRUE) AND (test_filter IS NOT TRUE)` (or explicitly `= FALSE` if the schema guarantees no NULLs).

**Momentum in our system:** Momentum (and momentum_percentile) is on a scale of about -99 to +99. For our current strategies, the MAGNITUDE (absolute value) is usually what matters; we are mostly directionally agnostic. When you see patterns in momentum, consider whether the signal is really about strength (abs value) rather than direction. Directional momentum patterns are still worth noting if they show up.

**Analyst focus (quant):** Primary concern is performance and how it ties to trading criteria, strategy parameters, and movement of underlying symbol prices. Not the plumbing: which scripts send trades, service wiring, or execution flow. Focus on: PnL and its drivers, parameter sensitivity (e.g. prob cutoffs, windows), entry/exit quality, relationship to momentum/volatility/movement, and backtests that inform strategy and monitor tuning.

**Default query assumptions (unless specified otherwise):** Use **main table only** (users.trades_0001); do not include trades_simulated_0001 unless the user says "simulated." **Exclude test_filter = TRUE** (filter: `test_filter IS NOT TRUE`). **Include both live and paper** (no filter on paper_trade) unless the user is specifically comparing or asking about live vs paper. Do not restate these in the reply; just report the numbers.


- **Written by:** `trade_manager.insert_trade()` (called via HTTP POST to trade_manager `/trades` from auto_entry_supervisor or manual/open API). Updates by `trade_manager.update_trade_status_with_ret_pct()` and cycle backfill.
- **Key columns:** status, date, time, symbol, market, trade_strategy, contract, strike, side, prob, diff, buy_price, position, sell_price, closed_at, fees, pnl, symbol_open, symbol_close, momentum, momentum_percentile, volatility, volatility_percentile, movement, movement_percentile, win_loss, ticker, monitor, order_id, order_id_open, order_id_close, high_price, low_price, hour_idx, weekly_cycle, monitor_confirmed, cycle_win_loss, cycle_pnl, cycle_ret_pct.
- **Context at entry:** momentum/momentum_percentile, volatility/volatility_percentile, movement/movement_percentile are taken from the **latest row** in `live_data.live_price_log_1s_{symbol}` at insert time (trade_manager). symbol_open from same source.
- **At close:** trade_manager sets symbol_close from `one_minute_avg` in live_price_log_1s_{symbol} (or current price fallback). high_price/low_price come from active_trade_supervisor (ATS) during the trade; monitor_confirmed = TRUE iff high_price != low_price (ATS was able to update at least once).

### users.trades_simulated_0001 (simulated 15m trades)

- **Written by:** `trade_manager.insert_simulated_trade()` via POST to trade_manager with `simulated_trade: true` (from auto_entry_supervisor simulated path). Same shape as trades_0001; buy_price, position, fees, bankroll, price_spread, sell_price are NULL by design (no execution).
- **Duplicate guard:** one row per (monitor, date, contract, strike, side).

### users.monitor_list_0001

- **Written by:** monitor_manager (creation), application/API (updates). Defines monitors (id 10xxx): name, symbol, market (hourly/15m), strategy, auto_trade, min_probability, min_differential, position_size, cooldown, loss_prevention, etc.
- **Per-monitor tables:** users.active_trades_0001_10xxx (ATS), users.monitor_cycle_performance_0001_10xxx (cycle win rate, exposure, etc.).

### users.fills_0001, users.settlements_0001, users.orders_0001, users.positions_0001

- **Written by:** `kalshi_account_sync_ws` (live sync from Kalshi API) and `backend/api/kalshi-api/kalshi_historical_ingest.py` (historical backfill). Fills/settlements use yes_price_dollars/no_price_dollars and yes_total_cost_dollars/no_total_cost_dollars (Kalshi _dollars migration); count_fp for fixed-point contract counts.

### users.account_history_0001, users.transfers_0001, users.account_balance_0001

- **Written by:** kalshi_account_sync_ws (balance sync, account history from /deposits and /withdrawals; internal/external transfers).

---

## live_data schema

### live_data.live_price_log_1s_{btc,eth,spx,ndx}

- **Written by:** `backend/symbol_price_watchdog.py` — one row per tick (timestamp, price, one_minute_avg, momentum, delta_1m..delta_30m, momentum_percentile, momentum_5s_avg, momentum_30s_avg, volatility, volatility_percentile, move_1m..move_30m, movement, movement_percentile).
- **Calculations:** momentum = weighted composite of deltas (same weights as movement); movement = weighted composite of move_1m..move_30m where move_Xm = (high−low)/open for last Xm window; percentiles from analytics.*_momentum_profile, *_volatility_profile, *_movement_profile. Rolling 30-day window (older rows deleted).

### live_data.live_symbol_status

- **Written by:** symbol_price_watchdog — one row per symbol, updated on each tick (latest tick values). Same fields as live_price_log plus prev_day_avg_* and daily_update.

### live_data.strike_table_hourly_{btc,eth,spx,ndx}, strike_table_15m_{btc,eth}

- **Written by:** `backend/strike_table_generator.py`. Reads current price and TTC from Kalshi event/market; gets probability from **analytics.probability_lookup_{symbol}_master_YYYYMMDD** via LookupProbabilityCalculator (bilinear interpolation on ttc_seconds, buffer_points, momentum_bucket). Also writes volatility, volatility_percentile, movement, movement_percentile from the latest row in live_price_log_1s_{symbol}.

### live_data.market_kalshi_hourly_{symbol}, market_kalshi_15m_{btc,eth}

- **Written by:** `backend/kalshi_market_watchdog.py`. Snapshot of Kalshi markets (event_ticker, market_ticker, strike, yes_bid/ask, no_bid/ask, last_price, volume, etc.). TRUNCATE on event rotation; open-trade tickers are re-inserted (pinned) so ATS has a price source for monitor_confirmed.

### live_data.btc_price_change, eth_price_change, price_change_*

- **Written by:** scripts or legacy paths. change1h, change3h, change1d.

---

## historical_data schema

### historical_data.{btc,eth,ndx,spx}_price_history

- **Written by:** Analytics pipeline: `backend/util/symbol_data_fetch_pg.py` (Yahoo-sourced 1m OHLCV → INSERT/ON CONFLICT), `backend/util/analytics/ndx_data_processor.py`, `spx_data_processor.py` (CSV → INSERT). Momentum/volatility/movement and their percentiles are updated by `momentum_generator_pg`, volatility logic, `movement_generator_pg` and profilers (analytics.*_momentum_profile, etc.). Timestamps EST (without time zone).
- **Columns:** timestamp, open, high, low, close, volume, momentum, momentum_percentile, volatility, volatility_percentile, movement, movement_percentile.

---

## analytics schema

### probability_lookup_{symbol}_master_YYYYMMDD

- **Written by:** `backend/util/probability_lookup_generator.py` (and related generators). Key columns: ttc_seconds, buffer_points, momentum_bucket, prob_within_positive, prob_within_negative. Used by strike_table_generator for probability_hourly / probability_15m.

### *_fingerprint_* (e.g. btc_fingerprint_-10, btc_fingerprint_20)

- **Written by:** `backend/util/fingerprint_generator_postgresql.py`. time_to_close + pos/neg probability grid (pos_0_00, neg_0_00, …). Used for strategy/backtest analysis.

### *_momentum_profile_*, *_volatility_profile_*, *_movement_profile_*, *_price_profile_*

- **Written by:** Analytics profilers (e.g. symbol_profiler, movement profile generation). Percentile → value mapping; used by symbol_price_watchdog and strike_table_generator to compute momentum_percentile, volatility_percentile, movement_percentile.

---

## End-to-end flow (trades)

1. **Entry:** Monitor in monitor_list_0001 → auto_entry_supervisor (AES) reads strike table (live_data.strike_table_*), checks probability/differential/cooldown/duplicate → POST to trade_manager `/trades` → insert_trade() writes users.trades_0001 (or insert_simulated_trade() → trades_simulated_0001). trade_executor sends order to Kalshi.
2. **During trade:** active_trade_supervisor (ATS) updates high_price/low_price from live_data.market_kalshi_* or live price; trade_manager can close (stop/expiration) using symbol_close from live_price_log_1s_{symbol}.one_minute_avg.
3. **Close:** trade_manager sets status, closed_at, sell_price, symbol_close, pnl, ret_pct, high_price, low_price, monitor_confirmed (TRUE if high != low). Cycle metrics (cycle_pnl, cycle_ret_pct, cycle_win_loss) backfilled per monitor/contract/date.
4. **Kalshi sync:** kalshi_account_sync_ws writes fills, settlements, orders, positions to users.*.

---

*Last updated: 2026-03-11.*
