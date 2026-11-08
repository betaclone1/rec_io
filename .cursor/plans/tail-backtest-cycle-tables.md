# Tail backtest cycle tables (UT/LT historical PG)

**Goal:** Maintain one Postgres cycle table per asset with Lower Tail and Upper Tail backtest outcomes (exact-cent tape), updated by the hourly public-trades historical worker, as the durable source for participation and win-rate scoring later.
**Scope:** Schema + scoring from public-trades/market-results archives into `historical_data`; extend `public_trades_drive_sync` wake to upsert cycle rows **and** refresh 7/30/90 trading-day rolling rate snapshots. Out of scope for now: UI, monitor gating thresholds, live-path verification.
**Status:** done (prod seeded)

## Locked decisions

| Topic | Decision |
|-------|----------|
| Source of truth | Backtest tape only (exact-cent first print). Live OB/monitor path stays separate; may verify later. |
| LT rule | First exact `$0.01` yes or no print in cycle; hold to settlement; win iff side == `market_result`. |
| UT rule | Same frame, first exact `$0.99` print. |
| Assets (v1) | `KXBTC15M`, `KXETH15M`, `KXSOL15M`, `KXXRP15M`, `KXGOLD15M`, `KXSILVER15M`, `KXWTI15M`. New assets case-by-case. |
| Granularity | One **row per cycle** per asset. Never omit a cycle. |
| UT+LT shape | **One table per asset**, LT and UT columns on the same row (parse either side later). |
| No exact-cent hit | Still insert the cycle row; that tail’s fill fields / `win_loss` stay **NULL** (participation yes, WR denominator no). |
| Rolling windows | Always **trading days** (crypto expected 24/7; unexplained gaps outside known Kalshi maintenance → **flag**). Materialized in `historical_data.tail_backtest_rolling_rates` (7/30/90) and refreshed every hourly wake. |
| Writer | Same hourly historical worker that updates public-trades + Drive also upserts these tables. Part of that historical dataset. |
| Isolation | Still off the live trading / Redis / monitor path. System PG only (`get_system_postgresql_connection`). |

## Proposed schema (per series)

Schema: `historical_data`. Table names (example): `kxbtc15m_tail_backtest_cycles` (lowercase series slug + `_tail_backtest_cycles`).

Conventions: first column `"timestamp"` = cycle open (or settlement end — pick one and document; align ET naive with other `historical_data` series). Unique key on cycle identity (`ticker` or `end_period_ts`).

Suggested columns (wide LT/UT):

- `timestamp` — ET naive cycle anchor
- `ticker`, `end_period_ts` (or equivalent cycle id)
- `market_result` (`yes`/`no`/NULL if unsettled)
- LT: `lt_fill_ts`, `lt_side`, `lt_price`, `lt_win_loss` (NULL if no fill or unsettled)
- UT: `ut_fill_ts`, `ut_side`, `ut_price`, `ut_win_loss` (same NULL rules)
- `trading_day` (date used for lookbacks)
- `gap_flag` / `gap_reason` (optional; for crypto unexplained dark windows)
- `updated_at`

Win-rate queries: `WHERE lt_win_loss IS NOT NULL` (and same for UT). Participation: fraction of cycles with non-null fill in window.

## Steps

1. [x] Migration `20261107_1600_tail_backtest_cycles`; local `up` applied; schema ref + drift check
2. [x] `backend/core/tail_backtest_cycles.py` scorer + upsert
3. [x] `public_trades_drive_sync` wake calls `score_lookback_for_sync` (`--skip-score` / env bypass)
4. [x] Crypto gap flags + commodity session-gated expected cycles; docs in LOWER_TAIL_STRATEGY
5. [x] Unit tests in `tests/unit/test_tail_backtest_cycles.py`
6. [x] Local smoke: 2026-11-06 KXBTC15M → 96 rows upserted

## Completion criteria

- [x] Seven tables exist via migration; local `run_migration.py up` succeeded
- [x] Hourly worker upserts cycles after historical catchup
- [x] No-fill and unsettled rows never invent win/loss
- [x] Docs state backtest-only ledger + trading-day / gap rules
- [x] No live trading path changes; no companion rollup yet

## Blockers / decisions

- Exact cycle anchor column (`timestamp` = open vs close) — implementer picks ET-naive convention matching existing 15m cycle tables and documents it.
- Full historical backfill volume/runtime — may run as a one-time local/prod job after schema lands; hourly only maintains recent cycles.
