# Master Changelog

This changelog is used when pushing updates to production. Each entry is timestamped and includes a summary plus any instructions for the production server agent (DB schema steps, scripts to run, restart order, etc.).

**Workflow:** Merge feature branch to `main`, sync repo on production, then have the production agent read the latest entry, work through the checklist (checking off each task), and restart services when all boxes are complete.

---

## 2026-08-16 — Release v3.10.2: Fix late TTC window entry (Exp Scalp)

**Summary**
- **Release: v3.10.2**
- **Problem:** Exp Scalp monitors were opening **15–40s late** into a 45s TTC window (`max_time=60` → `min_time=15`). AES/ATS treated frozen ladder `ttc` as wall-clock truth, and quiet-only failsafe starved non-waking ladders while other symbols flooded live_state wakes (seen on local unified BTC vs ETH; same class on prod unified / off-path evals after v3.10.1).
- **Fix:** `ttc_seconds_from_ladder` prefers authoritative settlement end (`settlement_end_ms` / Kalshi ticker) or ages snapshot `ttc` by as-of / lane capture age. AES/ATS failsafe runs on a **1s cadence even while busy** (not every wake). Tick contract doc updated; unit tests for aged TTC + stale_live_state log throttle.
- **No DB migrations.**
- **Reversibility:** Snapshot **`rec-io-prod-pre-update-2026-08-16-ttc-window`**. Code: `git revert` this commit. Full: restore droplet from snapshot.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Regenerate supervisor config and full restart:  
  `cd /opt/rec_io_server && scripts/MASTER_RESTART.sh`
- [x] Verify: `curl -sSf http://127.0.0.1:3000/health` and `curl -sSf http://127.0.0.1:8001/health`; `supervisorctl -c /opt/rec_io_server/backend/supervisord.conf -s unix:///tmp/supervisord.sock status | grep -E 'auto_entry_supervisor|active_trade_supervisor|btc15m_exp_scalp'`
- [x] Spot-check next Exp Scalp window: BTC cutout / unified ACTIVE should land within ~1–3s of `*:14:00` / `*:29:00` / `*:44:00` / `*:59:00` (not 15–40s late).
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.10.2`
- [x] Rollback (if needed): git revert / restore snapshot **`rec-io-prod-pre-update-2026-08-16-ttc-window`**.

---

## 2026-08-16 — Release v3.10.1: BTC 15m Exp Scalp AES cutout + latest-only lane + verify defaults

**Summary**
- **Release: v3.10.1**
- **AES/ATS:** Dedicated BTC 15m Expiration Scalp cutout workers (`btc15m_exp_scalp`) with ports in `port_config` / supervisor generator; main unified AES excludes cutout membership.
- **Tradeflow:** Latest-only mailbox lane (`tradeflow_latest_only_lane`) for denser/non-backlogged evaluation; live_state trigger + unified 15m/hourly monitor wiring.
- **Gates:** Expiration Scalp entry verification dwell path in `auto_entry_expiration_scalp_gates` / AES.
- **DB:** Migration **`20260812_1540_exp_scalp_entry_verification_defaults`** sets Expiration Scalp strategy/monitor `verification_period_enabled=TRUE`, `verification_period_seconds=3` (down restores FALSE/15). Schema ref + tick contract docs updated.
- **Ops:** Logrotate config cleanup; AGENTS / core-operating-law notes.
- **Tests:** Unit tests for cutout, latest-only lane, exp-scalp verification.
- **Reversibility:** Snapshot **`rec-io-prod-pre-update-2026-08-16-full`**. Code: `git revert` this commit (and prior v3.10.0 if needed). DB: `run_migration.py down 20260812_1540_exp_scalp_entry_verification_defaults`. Full: restore droplet from snapshot.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migration (before AES/ATS restart):  
  `cd /opt/rec_io_server && PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260812_1540_exp_scalp_entry_verification_defaults`
- [x] Regenerate supervisor config and full restart:  
  `cd /opt/rec_io_server && scripts/MASTER_RESTART.sh`
- [x] Verify: `curl -sSf http://127.0.0.1:3000/health` and `curl -sSf http://127.0.0.1:8001/health`; `supervisorctl -c /opt/rec_io_server/backend/supervisord.conf -s unix:///tmp/supervisord.sock status | grep -E 'auto_entry_supervisor|active_trade_supervisor|btc15m_exp_scalp'`
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.10.1`
- [x] Rollback (if needed): `run_migration.py down 20260812_1540_exp_scalp_entry_verification_defaults`; git revert / restore snapshot **`rec-io-prod-pre-update-2026-08-16-full`**.

---

## 2026-08-16 — Release v3.10.0: Monitor settings modal hydrate gate (no default overwrite)

**Summary**
- **Release: v3.10.0**
- **Problem:** Unified Auto Trade modal (desktop) could enable Save before `get_auto_entry_settings` finished, while in-memory time-window state still held UI defaults **0–3600**. Saving then overwrote live monitor gate settings (seen on monitor **10046** after position edits).
- **Fix:** Desktop and mobile: Save stays disabled until authoritative settings load (finite `min_time`/`max_time` from API); always await fresh load on open; Enter/Save refuse if not hydrated; do not invent time-window defaults on load.
- Also ships Expiration Scalp verification controls in the modal UI (existing `verification_period_*` columns; no schema change).
- **Scope:** Frontend only (`unified_auto_trade_settings.js`, `dashboard_mobile.html`, `unified_auto_trade_modal.html`). No migrations. No AES/backend cutout in this release.
- **Reversibility:** Droplet snapshot **`rec-io-prod-pre-update-2026-08-16`** (DO action submitted before deploy). Code rollback: `git revert` this commit (or `git checkout <prior> --` the three frontend files) + pull + hard-refresh browsers. No DB down migration required.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Restart `main_app` so static/modal assets are served from the new tree:  
  `supervisorctl -c /opt/rec_io_server/backend/supervisord.conf -s unix:///tmp/supervisord.sock restart main_app`
- [x] Verify: `curl -sSf http://127.0.0.1:3000/health` and `curl -sSf http://127.0.0.1:8001/health`; open a monitor settings modal and confirm Save stays disabled until settings load.
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.10.0`
- [x] Rollback (if needed): restore prior frontend via git revert of this release commit, pull, restart `main_app`; or restore droplet from snapshot **`rec-io-prod-pre-update-2026-08-16`**.

---

## 2026-08-13 — Release v3.9.9: Kalshi exchange sharding balance matrix + order auto-route

**Summary**
- **Release: v3.9.9**
- **Problem:** After Kalshi multi-shard balances appeared (exchange_index × subaccount), prod `GET /portfolio/subaccounts/balances` sync **overwrote** per-subaccount cash with the last shard row (e.g. CASH/MTB stuck at $1 while hero total stayed ~$18k).
- **Fix:** Poll matrix and **sum** cash across shards into `subaccounts_*`.`balance`; store per-shard cents in `exchange_0..3_balance` on `subaccounts_*` / `subaccount_balance_*_*` (migration **`20260813_1448_subaccount_exchange_balances`**). History sab rows use matrix cash + per-sub position marks; hero aggregate unchanged shape.
- **Orders:** `trade_executor` Create Order V2 sends `exchange_index: -1` (auto-route by ticker).
- Docs: `KALSHI_EXCHANGE_SHARDING.md` (+ diagram), portfolio/ingest/architecture pointers.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migration **before** restarting balance pollers:  
  `cd /opt/rec_io_server && PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260813_1448_subaccount_exchange_balances`
- [x] Restart account sync + trade executor (tenant 0001):  
  `supervisorctl -c /opt/rec_io_server/backend/supervisord.conf -s unix:///tmp/supervisord.sock restart kalshi_account_sync_0001 trade_executor_0001`
- [x] Also restart **`read_api`** (GET `/api/subaccounts` live-refreshes from Kalshi on each Account Manager load; stale process re-applied last-shard overwrite):  
  `supervisorctl -c /opt/rec_io_server/backend/supervisord.conf -s unix:///tmp/supervisord.sock restart read_api`
- [x] Verify: `curl -sSf http://127.0.0.1:3000/health` and `curl -sSf http://127.0.0.1:8001/health`; confirm `users_0001.subaccounts_0001` CASH/MTB balances are full matrix sums (not $1); account manager subaccount list matches.
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.9.9`

---

## 2026-08-07 — Release v3.9.8: Lean strike-pipeline master log (15m threshold)

**Summary**
- **Release: v3.9.8**
- **Problem:** Prod System Event Log was ~99% DOGE hourly `strike_pipeline` flap noise (WARNING at ~90s + INFO recovery every few minutes).
- **Fix:** Raise default `STRIKE_PIPELINE_PROLONGED_OUTAGE_SEC` from 90s to **900s (15 minutes)**. Sub-threshold flaps stay in service logs / `strike_pipeline_health` only; master log still gets WARNING + recovery for true prolonged outages.
- Docs: `LOGGING_INVENTORY.md`. No migrations.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Restart strike table generators (load new prolonged-outage default):  
  `supervisorctl -c /opt/rec_io_server/backend/supervisord.conf -s unix:///tmp/supervisord.sock restart strike_table_generator_ws_hourly strike_table_generator_ws_15m`
- [x] Verify: `curl -sSf http://127.0.0.1:3000/health` and `curl -sSf http://127.0.0.1:8001/health`; both strike generators RUNNING; confirm new master_events lines are not DOGE flap pairs every few minutes.
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.9.8`

---

## 2026-08-07 — Release v3.9.7: Tradeflow Stage 0 diagnostics (opt-in, off by default)

**Summary**
- **Release: v3.9.7**
- **Stage 0 observability only** (plan: auto-trade workflow audit / Stage 0). No changes to entry/exit gates, cooldowns, submit/close paths, paper vs live, or settlement.
- Opt-in `[TRADEFLOW TRACE]` lines in AES/ATS via `TRADEFLOW_DECISION_TRACE=1` (optional verbose strike skips). Default unset/off — **do not enable on production for this release**.
- Diagnostic scripts: `check_tradeflow_env_parity.py`, `check_ats_enrollment_health.py`.
- Docs: unified AES tick contract cooldown/live_state wording; Architecture per-tenant unified supervisors.
- Supervisor generator propagates the trace env vars when set at generate time (local only for now).

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Confirm `TRADEFLOW_DECISION_TRACE` is **not** set in the production shell/env used for supervisor regen (leave unset so trading stays at baseline log volume).
- [x] Restart AES/ATS tenants (loads new code; no migrations):  
  `supervisorctl -c /opt/rec_io_server/backend/supervisord.conf -s unix:///tmp/supervisord.sock restart auto_entry_supervisor_0001 active_trade_supervisor_0001`  
  (Also restart other `auto_entry_supervisor_*` / `active_trade_supervisor_*` if present and RUNNING.)
- [x] Verify: `curl -sSf http://127.0.0.1:3000/health` and `curl -sSf http://127.0.0.1:8001/health`; AES/ATS RUNNING; confirm AES logs do **not** spam `[TRADEFLOW TRACE]` (trace stays off).
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.9.7`

---

## 2026-08-06 — Release v3.9.6: Exp Scalp movement window + pipeline market keying

**Summary**
- **Release: v3.9.6**
- **Pipeline gate market keying:** Live open health checks key `strike_pipeline_health` by the trade’s own interval (`15m` / `hourly`). AES tickets now send `market`; TM resolves payload → ticker → monitor (no silent `or "hourly"`). A 15m open must never consult the hourly health row (and vice versa). Unresolved market fails closed for live opens.
- **Expiration Scalp Movement Window:** Monitor `min_movement` / `max_movement` (defaults 0–100) plus joint prob/movement sizing (in-prob = full size; out-of-prob + in-movement = half size; else block). UI dual slider on desktop/mobile; Exp Scalp replay/tests updated. Migration also aligns `min_probability` to `numeric(5,2)` on tenant `monitor_list_*` / `strategy_list_*`.
- **Trade history:** Live / paper / test filter + detail/fills refinements (desktop + mobile).
- **Historical BTC 15m cycle candles:** New `historical_data` tables + pull/build scripts and GDrive download helper for backtesting packs (additive migrations).
- Plans / context: ad-hoc prod A/B diagnosis (10046 vs 10056); related movement-window implementation work. No dedicated plan file required for the gate fix.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Migration pre-flight: confirm these files exist in the deployed commit:  
  `scripts/migrations/20260802_1645_historical_btc15m_cycle_candles.up.sql` / `.down.sql`  
  `scripts/migrations/20260802_1655_btc15m_cycle_candles_timestamp_utc_text.up.sql` / `.down.sql`  
  `scripts/migrations/20260802_1805_btc15m_cycle_candles_market_result.up.sql` / `.down.sql`  
  `scripts/migrations/20260803_1400_monitor_movement_window.up.sql` / `.down.sql`
- [x] Apply migrations **before restart** (additive only; apply in this order):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260802_1645_historical_btc15m_cycle_candles`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260802_1655_btc15m_cycle_candles_timestamp_utc_text`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260802_1805_btc15m_cycle_candles_market_result`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260803_1400_monitor_movement_window`
- [x] Confirm migrations applied:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py list | grep -E '20260802_1645|20260802_1655|20260802_1805|20260803_1400'`
- [x] Schema drift check:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services that load new AES/TM/read/frontend wiring (**only after migrations confirmed**):  
  `supervisorctl -c /opt/rec_io_server/backend/supervisord.conf -s unix:///tmp/supervisord.sock restart auto_entry_supervisor_0001 trade_manager_0001 read_api main_app`
- [x] Verify: `curl -sSf http://127.0.0.1:3000/health` and `curl -sSf http://127.0.0.1:3050/health`; AES/TM RUNNING; after restart, a live 15m open log must show `market=15m` (not `hourly`) on any pipeline-gate block line.
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.9.6`

---

## 2026-07-31 — Release v3.9.5: False drawdown halt guard (settlement understatement)

**Summary**
- **Release: v3.9.5**
- **Problem:** Kalshi `GET /portfolio/balance` can briefly understate MTB equity mid-settlement (cash after buy debits, marks cleared, settlement credits not yet applied). One bad tick crossed the 50% bankroll ratchet and fired emergency halt (prod 2026-07-31 21:59 ET; same class on 2026-07-30).
- **Guard:** Detect large one-tick portfolio drops on MTB; skip write + repoll (`REC_BALANCE_GLITCH_REPOLL_DELAYS_SEC`). Persisting understatement is written; overstatement still keeps last good row.
- **Halt confirm:** Emergency halt requires two consecutive crash-sized portfolio readings (`REC_DRAWDOWN_HALT_CONFIRM_TICKS`, default `2`); first crossing keeps sticky bankroll and does not halt.
- Docs: `docs/PORTFOLIO_ACCOUNT_SYNC.md`. No migrations.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Restart account sync (loads `balance_snapshot` glitch/halt logic):  
  `supervisorctl -c /opt/rec_io_server/backend/supervisord.conf -s unix:///tmp/supervisord.sock restart kalshi_account_sync_0001`
  (Restart other `kalshi_account_sync_*` tenants if present and active.)
- [x] Verify: `supervisorctl … status kalshi_account_sync_0001` RUNNING; `curl -sSf http://127.0.0.1:3000/health`; no import/SyntaxError in `logs/kalshi_account_sync_0001.err.log` after restart.
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.9.5`

---

## 2026-07-30 — Release v3.9.4: Multi-leg order IDs on trades (zero-fill no wipe)

**Summary**
- **Release: v3.9.4**
- **Order-id durability:** Keep scalar `order_id_open` / `order_id_close` as the active confirm wake pointer. Add append-only `order_ids_open` / `order_ids_close` (`TEXT[]`) for filled legs only. Failed IOC top-ups no longer set `order_id_open` to NULL or leave the zero-fill attempt as the durable pointer — scalar reverts to the last filled id; zero-fill ids are never appended.
- **Trade detail:** Fills/Orders loaders resolve all associated order ids via shared `trade_associated_order_ids` (arrays with scalar fallback).
- **DB:** Migration `20260731_0025_trades_order_ids_open_close_arrays` adds the two arrays on tenant `trades_*` / `trades_simulated_*` and matching `archive.trades_archive_{live|paper}_*` tables; backfills from scalars when present. **Must apply before restarting `trade_manager`** so confirm UPDATEs that write the new columns cannot hit `UndefinedColumn`.
- Plans: `.cursor/plans/multi_order_id_storage_2dbc04bd.plan.md`

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Migration pre-flight: confirm these files exist in the deployed commit:  
  `scripts/migrations/20260731_0025_trades_order_ids_open_close_arrays.up.sql`,  
  `scripts/migrations/20260731_0025_trades_order_ids_open_close_arrays.down.sql`
- [x] Apply migration **before any service restart** (additive columns + scalar backfill only):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260731_0025_trades_order_ids_open_close_arrays`
- [x] Confirm migration applied on prod:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py list | grep 20260731_0025_trades_order_ids_open_close_arrays`  
  and columns exist:  
  `psql "$DATABASE_URL" -c "SELECT column_name FROM information_schema.columns WHERE table_schema = 'users_0001' AND table_name = 'trades_0001' AND column_name IN ('order_ids_open','order_ids_close') ORDER BY 1;"`
- [x] Schema drift check:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services that load the new code (**only after migration confirmed**):  
  `supervisorctl -c /opt/rec_io_server/backend/supervisord.conf -s unix:///tmp/supervisord.sock restart trade_manager_0001 read_api`  
  (Hotfix: `c5b4f51` escaped `{{}}` defaults in `init_trades_db` f-string that caused a SyntaxError on first restart.)
- [x] Verify: `curl -sSf http://127.0.0.1:3000/health` and `curl -sSf http://127.0.0.1:3050/health`; `supervisorctl … status trade_manager_0001 read_api` RUNNING; no `UndefinedColumn` / `order_ids_open` errors in trade_manager logs after restart.
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.9.4`

---

## 2026-07-30 — Release v3.9.3: Trade detail fills/orders + archive column parity

**Summary**
- **Release: v3.9.3**
- **Trade history detail:** Desktop modal adds fills (grouped by identical timestamps) and an Orders tab (same Bankroll/Portfolio/PNL tab style), paper-trade title badge with no fills/orders panel, independent candles+line chart layers, and more expanded detail fields (`initial_*`, slippage, order type, LP state, subaccount).
- **API:** `GET /api/trades/{id}/detail` returns `fills` and `orders` from tenant `fills_*` / `orders_*` via `order_id_open` / `order_id_close` (skipped for paper).
- **DB (additive only):** Migration `20260730_1415_archive_trades_union_parity_subaccount_min_gates` adds nullable `subaccount`, `min_fill_price`, `min_slippage` to every `archive.trades_archive_{live|paper}_NNNN` table. **No UPDATE/DELETE/TRUNCATE and no rewriting of existing row values** — only `ADD COLUMN IF NOT EXISTS`.
- **Transfers:** Live subaccount transfers use Kalshi’s truncating transferable-balance read so sub-cent balances are not over-requested.
- Plans: ad-hoc trade-history detail work (no dedicated plan file); schema ref note updated for archive parity.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Migration pre-flight: confirm these files exist in the deployed commit:  
  `scripts/migrations/20260730_1415_archive_trades_union_parity_subaccount_min_gates.up.sql`,  
  `scripts/migrations/20260730_1415_archive_trades_union_parity_subaccount_min_gates.down.sql`
- [x] Apply migration (**schema-only ADD COLUMN; must not modify or delete existing row data**):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260730_1415_archive_trades_union_parity_subaccount_min_gates`
- [x] Schema drift check:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services that load the new code:  
  `supervisorctl restart read_api main_app`
- [x] Verify: `curl -sSf http://127.0.0.1:3000/health` and `curl -sSf http://127.0.0.1:3050/health`; `supervisorctl status read_api main_app` RUNNING; spot-check trade history detail fills/orders tabs on a live trade.
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.9.3`

---

## 2026-07-29 — Release v3.9.2: CFB tick-buffer windowed scans (stop creeping lag)

**Summary**
- **Release: v3.9.2**
- **Hot path:** `backend/core/symbol_tick_buffer.py` no longer does O(n) full-deque scans on every metric lookup. Window reads walk newest→oldest and stop at the cutoff; `append_tick` trims ticks older than 3 hours; `minute_candles` buckets by integer minute (no per-tick `strftime`). Metric CPU stays flat with uptime instead of climbing (~+55 ms/hour previously).
- **Tests:** `tests/unit/test_symbol_tick_buffer_windows.py` pins windowed behavior and retention.
- No schema migrations.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Restart CFB price watchdog (required — loads new tick-buffer code):  
  `supervisorctl restart cfbenchmarks_price_watchdog`
- [x] Verify: `supervisorctl status cfbenchmarks_price_watchdog` RUNNING; `lag_kalshi_ms` stays low (no climb after restart); no reconnect storms.
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.9.2`

---

## 2026-07-29 — Release v3.9.1: CFB live path off Postgres / cycle capture

**Summary**
- **Release: v3.9.1**
- **System-critical:** `cfbenchmarks_price_watchdog` WebSocket loop no longer opens Postgres, prunes, or spawns a thread per tick. Backtesting ring writes go through `backend/core/live_ring_pg_writer.py` (one background thread, one long-lived connection, batched upserts, timed prune). Cycle fanout uses one persistent worker queue instead of per-tick threads.
- **Settlement:** Quarter-close `avg_60s` is no longer a synchronous write on the WS loop; `trade_manager` still polls briefly and the repair pass covers late landings. Rings may lag; live `live_state` must not.
- **Docs:** `docs/MASTER_DB_SCHEMA_REFERENCE.md` population notes for price/metrics rings updated. No schema migrations.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Restart CFB price watchdog (required for hot-path fix):  
  `supervisorctl restart cfbenchmarks_price_watchdog`
- [x] Verify: `supervisorctl status cfbenchmarks_price_watchdog` RUNNING; process has `live_ring_pg` / `cfb_cycle_fanout` threads; ticks show low `lag_kalshi_ms` without reconnect storms; no `ring PG writer dropped` / `cycle fanout queue full` floods.
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.9.1`

---

## 2026-07-27 — Release v3.9.0: Cycle packages (BTC+ETH), CFB rings, Drive warehouse

**Summary**
- **Release: v3.9.0**
- **Cycle packages:** Per-ticker hot tables under `historical_data` (snapshot, deltas, strike, price/metrics rings, market_meta) with hourly `cycle_packager` → `.tar.xz` under `backtesting_data/{SERIES}/…`. Default symbols **BTC + ETH** (`CYCLE_HOT_SYMBOLS`); series map via `CYCLE_SERIES_MAP`. Modules renamed to generic `cycle_*` (not BTC/Kalshi-specific). Inclusive open/close CFB ticks; early hot registration at OB subscribe / live_state.
- **Google Drive warehouse:** Post-package upload to `DATA/HISTORICAL_DATA/BACKTESTING_DATA` (`scripts/gdrive/upload-backtesting-data.js`, `CYCLE_GDRIVE_UPLOAD`). Prod needs OAuth secrets under `backend/data/secrets/` (see `backend/data/secrets/README.md`).
- **CFB live rings:** `live_price_ring_90m_*` UTC ISO-Z + full precision + CFB avgs; new `live_metrics_ring_90m_*`. Migrations **`20260725_1035`**, **`1045`**, **`1300`**, **`1350`**, **`1421`**, plus cycle schema comment **`20260726_1526_btc15m_cycle_package_hot`**.
- **Exact `floor_strike`:** Packages/meta keep Kalshi API decimal text (no int/float truncation).
- **Plans / docs:** `historical-cycle-data-product` (draft), `docs/HISTORICAL_CYCLE_DATA_PRODUCT.md`, schema reference updated.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Migration pre-flight: confirm these files exist in the deployed commit:  
  `scripts/migrations/20260725_1035_live_price_ring_utc_timestamps.up.sql`, `.down.sql`,  
  `scripts/migrations/20260725_1045_live_price_ring_iso_z.up.sql`, `.down.sql`,  
  `scripts/migrations/20260725_1300_live_price_ring_cfb_avgs.up.sql`, `.down.sql`,  
  `scripts/migrations/20260725_1350_live_price_ring_full_precision.up.sql`, `.down.sql`,  
  `scripts/migrations/20260725_1421_live_metrics_ring_90m.up.sql`, `.down.sql`,  
  `scripts/migrations/20260726_1526_btc15m_cycle_package_hot.up.sql`, `.down.sql`
- [x] Apply pending migrations from repo root before restart:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up`
- [x] Schema drift check:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Ensure Drive OAuth secrets on prod (if upload desired):  
  `backend/data/secrets/gdrive_oauth_client.json` and `gdrive_oauth_token.json` (mode 600); Node ≥ 18 available. Skip only if intentionally leaving `CYCLE_GDRIVE_UPLOAD=0`.
- [x] Restart services (regenerates supervisor: program **`cycle_packager`** replaces `btc15m_cycle_packager`):  
  `./scripts/MASTER_RESTART.sh`
- [x] Verify: `supervisorctl status cycle_packager` RUNNING; CFB + `market_watchdog_ws_kalshi` healthy; after next UTC :05 packager pass, local/Drive packages under `KXBTC15M/` and `KXETH15M/` as expected.
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.9.0`

---

## 2026-07-16 — Release v3.8.3: TM min_slippage gate, monitor slider, trades snapshot

**Summary**
- **Release: v3.8.3**
- **Min slippage gate (trade_manager):** New early precheck on projected entry slippage (`initial_proj_price − buy_price`). When monitor `min_slippage` is below 0 (range -0.1000..0.0000; 0 disables), TM rejects paper and live opens before executor using the same pending-insert → delete → `SLIPPAGE FAILURE` path as min_fill. Reuses existing orderbook projection (no extra fetch).
- **Monitor / AES / settings:** Migration **`20260716_1200_min_slippage_gate`** adds `min_slippage` to all tenant `monitor_list_*` (default 0.0000) and snapshots it on `trades_*` / `trades_simulated_*`. AES passes the value on the trade ticket; settings GET/SET validate and persist; new-monitor INSERT defaults to 0.0000.
- **UI:** Min Slippage slider on all strategy monitor settings modals (desktop + mobile), last control before Loss Prevention (Expiration Scalp: after Min Fill Price). Hint lines removed; label spacing uses standard `--uat-slider-label-gap` (no compact class).
- **Database:** `docs/MASTER_DB_SCHEMA_REFERENCE.md` and greenfield `database.py` updated for `min_slippage`.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Migration pre-flight: confirm these files exist in the deployed commit:  
  `scripts/migrations/20260716_1200_min_slippage_gate.up.sql`, `.down.sql`
- [x] Apply migration from repo root before restart:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260716_1200_min_slippage_gate`
- [x] Schema drift check:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services:  
  `./scripts/MASTER_RESTART.sh`
- [x] Verify health/logs for `main_app`, `trade_manager_*`, `trade_executor_*`, `auto_entry_supervisor_*`, `monitor_manager_*`.
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.8.3`

---

## 2026-07-15 — Release v3.8.2: DOGE live pipeline, TM min-fill precheck, trades min_fill_price snapshot

**Summary**
- **Release: v3.8.2**
- **DOGE support (new):** Migration **`20260713_1500_doge_live_tables`** adds `live_price_log_1s_doge`, `price_change_doge`, `live_price_ring_90m_doge`, and registers **DOGE** in `live_data.symbols_list`. CFB watchdog index **`DOGEUSD_RTI`**; Kalshi series **`KXDOGE15M`** / **`KXDOGED`** in market watchdog; 15m strike table + WS generator; trade monitor icon; analytics/backtest symbol lists updated.
- **Slippage gate (trade_manager):** Early `min_fill_price` precheck on `initial_proj_price` for **paper and live** opens — rejects and deletes pending row before executor (same `SLIPPAGE FAILURE` path). TM orderbook projection uses Redis (parity with executor).
- **Trades schema:** Migration **`20260715_1200_trades_min_fill_price`** adds `min_fill_price NUMERIC(6,4) NOT NULL DEFAULT 0.0000` on all tenant `trades_*` / `trades_simulated_*`; TM snapshots monitor floor at insert.
- **Database:** `docs/MASTER_DB_SCHEMA_REFERENCE.md` updated for DOGE live tables and trades `min_fill_price`.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Migration pre-flight: confirm these files exist in the deployed commit:  
  `scripts/migrations/20260713_1500_doge_live_tables.up.sql`, `.down.sql`,  
  `scripts/migrations/20260715_1200_trades_min_fill_price.up.sql`, `.down.sql`
- [x] Apply pending migrations from repo root before restart:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up`
- [x] Schema drift check:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services (regenerates supervisor with `DOGEUSD_RTI` in CFB index list):  
  `./scripts/MASTER_RESTART.sh`
- [x] Verify DOGE live pipeline on prod:  
  `psql` — `SELECT symbol FROM live_data.symbols_list WHERE UPPER(symbol)='DOGE';` returns one row;  
  `tail -50 logs/cfbenchmarks_price_watchdog.out.log | grep -i DOGEUSD` shows ticks after restart;  
  `tail -50 logs/strike_table_generator_ws_15m.out.log | grep -i DOGE` shows 15m strike processing (or no errors for KXDOGE15M).
- [x] Verify health/logs for `main_app`, `trade_manager_*`, `trade_executor_*`, `cfbenchmarks_price_watchdog`, `strike_table_generator_ws_15m`.
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.8.2`
- [x] Hotfix follow-up (post-deploy): pull `fde0690` (DOGE in 15m strike allowlist) and restart `strike_table_generator_ws_15m`, `market_watchdog_ws_kalshi`, `cfbenchmarks_price_watchdog`.

---

## 2026-07-05 — Release v3.8.1: Master system event log, CASH→MTB funding fix, admin timeline

**Summary**
- **Release: v3.8.1**
- **Master system event log:** New `system.event_log` table (migration **`20260704_1500_system_event_log`**) plus dual-sink writer (`backend/util/master_system_log.py`, `logs/master_events.log`). REST endpoints on admin tools for timeline browse; hooks in `MASTER_RESTART`, deploy scripts, auth halts, `monitor_manager`, `system_monitor`, and Kalshi WS ingest.
- **CASH→MTB manual funding:** `initiate-transfer` now bumps MTB `base_value` before Kalshi transfer, suppresses automatic profit-rake on the post-transfer balance poll, and uses a single full `sync_balance(full=True)` instead of a duplicate bankroll snapshot (fixes false rake + double-count after funding from CASH).
- **Paper internal transfers:** Same base bump + hero snapshot path; automatic rake skipped on manual transfer refresh.
- **Ops:** `record_system_version.py` logs deploy events; `simple_git_pull_on_prod.sh` and `git_update_system.sh` emit deploy log entries.
- **Database:** Migration **`20260704_1500_system_event_log`**; `docs/MASTER_DB_SCHEMA_REFERENCE.md` updated.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Migration pre-flight: confirm these files exist in the deployed commit:  
  `scripts/migrations/20260704_1500_system_event_log.up.sql`, `.down.sql`
- [x] Apply pending migrations from repo root before restart:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up`
- [x] Schema drift check:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh`
- [x] Verify health/logs for `main_app`, `trade_executor_*`, `kalshi_account_sync_*`, `monitor_manager_*`; spot-check Admin Tools system events timeline and a CASH→MTB manual transfer does not trigger automatic rake.
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.8.1`

---

## 2026-06-28 — Release v3.8.0: Monitor reverse mode, min fill price gate, strike orderbook projection

**Summary**
- **Release: v3.8.0**
- **Monitor reverse mode:** Per-monitor `reverse` flag (migration **`20260627_1200_monitor_reverse`**). AES flips executed side at dispatch; dedup uses executed side; ATS skips auto-stop; UI shows `Reverse {strategy}`; trade history rolls reverse trades into reverse monitor performance rows.
- **Min fill price / slippage gate:** Migration **`20260613_1200_orderbook_strike_min_fill_price`** adds `monitor_list_*.min_fill_price`. Expiration Scalp settings UI; `trade_manager` forwards threshold to executor; `trade_executor` rejects opens when projected taker VWAP is below threshold (disabled when NULL/0).
- **Orderbook strike prices:** `orderbook_strike_prices` module projects taker fill from sidecar orderbook; strike table generator uses orderbook-backed active-side ask where applicable.
- **Monitor settings cache:** Separate Redis keys per bool field (`auto_trade`, `reverse`) to prevent reverse flag cross-contamination.
- **Trade history UI:** Desktop results table fills dark inset edge-to-edge; reverse strategy filter/attribution fixes (desktop + mobile).
- **Database:** Migrations **`20260613_1200_orderbook_strike_min_fill_price`**, **`20260627_1200_monitor_reverse`**; `docs/MASTER_DB_SCHEMA_REFERENCE.md` updated.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Migration pre-flight: confirm these files exist in the deployed commit:  
  `scripts/migrations/20260613_1200_orderbook_strike_min_fill_price.up.sql`, `.down.sql`,  
  `scripts/migrations/20260627_1200_monitor_reverse.up.sql`, `.down.sql`
- [x] Apply pending migrations from repo root before restart:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up`
- [x] Schema drift check:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh`
- [x] Verify health/logs for `main_app`, `trade_executor_*`, `auto_entry_supervisor_*`, `active_trade_supervisor_*`, `monitor_manager_*`; spot-check reverse monitor tile label and Expiration Scalp min fill price setting save.
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.8.0`

---

## 2026-06-17 — Release v3.7.5: Expiration Scalp strategy, monitor_manager pool fixes, local restart hardening

**Summary**
- **Release: v3.7.5**
- **Expiration Scalp:** New strategy seeded via migration **`20260612_1200_expiration_scalp_strategy`** (TTC 0–60s, prob 90–100%, ask $0.90–$0.99). AES entry scans YES/NO independently with side-aware probability and active-side ask window (not HTC `active_side` path). ATS no-op auto-stop. Desktop + mobile UAT settings.
- **monitor_manager:** Fix Postgres connection pool leaks (cleanup, status watcher, regime reconcile); release DB connection before post-save regime reconcile; default pool max 8. Monitor settings saves no longer exhaust the pool.
- **Local ops:** `MASTER_RESTART.sh` / supervisord macOS daemon mode, venv binary paths, skip redundant Step 6 on fresh start; `load_unified_config.sh` / `paths.py` venv resolution.
- **Database:** Migration **`20260612_1200_expiration_scalp_strategy`** required on prod; `docs/MASTER_DB_SCHEMA_REFERENCE.md` updated.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Migration pre-flight: confirm these files exist in the deployed commit:  
  `scripts/migrations/20260612_1200_expiration_scalp_strategy.up.sql`, `.down.sql`
- [x] Apply pending migrations from repo root before restart:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up`
- [x] Schema drift check:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh`
- [x] Verify health/logs for `main_app`, `trade_executor_*`, `monitor_manager_*`, `auto_entry_supervisor_*`; confirm monitor settings save works (no pool exhausted error).
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.7.5`

---

## 2026-06-04 — Release v3.7.4: CFB price watchdog, live price ring, quarter-hour expiry fix, monitor health

**Summary**
- **Release: v3.7.4**
- **CFB price watchdog:** New `cfbenchmarks_price_watchdog` publishes CFB spot to Redis `live_state`; feed-health reconnect on tick drought; optional CFB feed test UI tab. Legacy symbol price watchdogs retired from supervisor template.
- **Live price ring (90m):** Migration **`20260603_1200_live_price_ring_90m`** adds `live_data.live_price_ring_90m_*` sidecar tables for ring hydration on watchdog restart.
- **Trade expiration:** `trade_manager` uses CFB ring 60s avg (with `live_state` fallback) for `symbol_close`; quarter-hour sweeps process **tenant trades before simulated**, refresh wall clock for expiry filter, and run simulated settlement in a background thread so `:15/:30/:45` cron slots are not blocked.
- **Monitor health:** `strike_pipeline_health` prefers `live_state` / ring over missing `live_price_log_1s_*`; rollback on gate errors so monitor tiles do not false-degrade.
- **HF trade monitor / orderbook:** `hft_engine` refactor; orderbook-redis UI and HF monitor tab updates; `redis_switchboard` and realtime wiring adjustments.
- **Database:** Migration **`20260603_1200_live_price_ring_90m`** required on prod; `docs/MASTER_DB_SCHEMA_REFERENCE.md` updated.
- Plans: `live-price-feed-hygiene`

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Migration pre-flight: confirm these files exist in the deployed commit:  
  `scripts/migrations/20260603_1200_live_price_ring_90m.up.sql`, `.down.sql`
- [x] Apply pending migrations from repo root before restart:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up`
- [x] Schema drift check:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh`
- [x] Verify health/logs for `main_app`, `trade_manager_*`, `cfbenchmarks_price_watchdog`, `redis_switchboard`; confirm 15m monitor trades expire at quarter hour; monitor power lights not false-red.
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.7.4`

---

## 2026-05-27 — Release v3.7.3: Dashboard performance snapshot, trade history live marks, HF trade monitor, orderbook resting orders

**Summary**
- **Release: v3.7.3**
- **Dashboard performance:** Fix rollup recompute when master `trades_*` has columns (e.g. `subaccount`) not yet on archive tables — union uses column intersection; `main_app` warms Redis `performance_snapshot` on startup and lazy-fills on `GET /api/dashboard/performance-snapshot` when missing.
- **Trade history (desktop + mobile):** Live open-trade PnL/ret via `/ws/active-trades-hot-path` and `trade_marks_updated`; refetch on `UPDATE` (not only INSERT/DELETE); mobile parity with hot-path marks and `data-trade-id` DOM patches.
- **Orderbook UI:** Resting-order badges (clock + signed remaining count) on trade monitor orderbook; portfolio orders API passthrough; live WS updates for orders/positions/fills.
- **Strike table / Rising Devil:** Carry forward 15m ask min/max from Redis ladder when PG strike writes are skipped (`LIVE_STATE_PG_WRITES=off`).
- **HF trade monitor:** New `backend/hft_engine.py`, `hf_trade_monitor.html`, routes, and orderbook-redis UI integration.
- **Live path cache monitor:** Portfolio tables sort newest-first; fill `created_time` stamped when missing from WS.
- **Database:** No new migrations in this release (code-only union fix for performance rollups).

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Restart services: `./scripts/MASTER_RESTART.sh`
- [x] Verify health/logs for `main_app`, `read_api`, `redis_switchboard`, `kalshi_account_sync_*`; dashboard Performance strip shows period values (not em dashes); trade history open rows update PnL without full page refresh.
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.7.3`

---

## 2026-05-25 — Release v3.7.2: HF orderbook hot path, subaccount tracking for portfolio + trades

**Summary**
- **Release: v3.7.2**
- **HF orderbook hot path:** Tiered hot/cold flush in `market_watchdog_ws_kalshi` — hot tickers flush immediately to Redis with `redis_written_ms` timestamp; cold tickers continue on coalesced timer. Pre-built WS payloads skip rebuild in switchboard; sequence-number dedup prevents stale frames. Dedicated `OrderbookHotSubscriber` API for backend HF scripts. New `ob_latency_probe.py` dev tool and `docs/ORDERBOOK_HOT_CACHE.md`.
- **Subaccount tracking (portfolio):** Fills, orders, and positions now carry `subaccount` (integer, default 1 = primary) from Kalshi WS through Redis hot state and PG. Positions unique index changed from `(ticker)` to `(ticker, subaccount)`. Redis hash field for positions is now `{ticker}:{subaccount}`. Live Path Cache Monitor displays subaccount column for all three tables.
- **Subaccount tracking (trades):** `trades_NNNN` and `trades_simulated_NNNN` gain `subaccount INTEGER NOT NULL DEFAULT 1`; `insert_trade()` records `trade.get("subaccount", 1)` from the execution flow. All existing rows backfilled as subaccount 1.
- **Database:** Migrations **`20260525_0830_portfolio_subaccount_column`** (fills/orders/positions subaccount + positions composite index) and **`20260525_0855_trades_subaccount_column`** (trades/trades_simulated subaccount). `docs/MASTER_DB_SCHEMA_REFERENCE.md` updated.
- **Tradeflow:** AES/ATS wake on orderbook hints for hot tickers with separate `TRADEFLOW_ORDERBOOK_TRIGGER_MIN_SEC` coalesce.
- Plans: `subaccount_tracking_d3aad9b4`

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Migration pre-flight: confirm these files exist in the deployed commit:  
  `scripts/migrations/20260525_0830_portfolio_subaccount_column.up.sql`, `.down.sql`,  
  `scripts/migrations/20260525_0855_trades_subaccount_column.up.sql`, `.down.sql`
- [x] Apply pending migrations from repo root before restart:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up`
- [x] Schema drift check:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh`
- [x] Verify health/logs for `main_app`, `trade_executor`, `kalshi_account_sync_*`, `market_watchdog_ws_kalshi`; confirm hot-path and subaccount changes are live.
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.7.2`

---

## 2026-05-24 — Release v3.7.1: Kalshi subaccount balance pipeline, MTB rake to CASH, account manager UX

**Summary**
- **Release: v3.7.1**
- **Balance pipeline (live):** `sync_balance` polls `GET /portfolio/subaccounts/balances`, per-subaccount `GET /portfolio/balance?subaccount=N` into `subaccount_balance_*_<n>`, aggregates hero `account_balance_*`; startup baseline uses `sync_balance(full=True)` (no 120s throttle).
- **Subaccounts:** Kalshi #0 = **CASH**, #1 = **Master Trading Bankroll**, #2+ = `undefined_*`; removed deposit routing; `trade_executor` defaults orders to subaccount **1**.
- **Automatic MTB rake (live):** When `automatic_transfers` and PnL target met, `POST /portfolio/subaccounts/transfer` **#1 → #0** (CASH), updates MTB `base_value`, then full balance repoll; paper simulates MTB → CASH in DB.
- **Account manager:** Initiate Transfer modal closes immediately on Submit (transfer continues in background); desktop + mobile.
- **Database:** Migrations **`20260523_1200_subaccount_balance_polling`** (rename CASH/`undefined_2`, create `subaccount_balance_*_0/_1/_2` per tenant) and **`20260524_1200_subaccount_balance_3_table`** (`subaccount_balance_*_3`); `docs/MASTER_DB_SCHEMA_REFERENCE.md` and `docs/PORTFOLIO_ACCOUNT_SYNC.md` updated.
- **Tests:** Unit coverage for subaccount balance polling, Kalshi transfer mapping, automatic MTB rake.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Migration pre-flight: confirm these files exist in the deployed commit:  
  `scripts/migrations/20260523_1200_subaccount_balance_polling.up.sql`, `.down.sql`,  
  `scripts/migrations/20260524_1200_subaccount_balance_3_table.up.sql`, `.down.sql`
- [x] Apply pending migrations from repo root before restart:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up`
- [x] Schema drift check:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh`
- [x] Verify health/logs for `main_app`, `trade_executor`, `kalshi_account_sync_*`; confirm startup log lines `Full account/subaccount balance sync` and `Full live balance poll` without balance poll errors.
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.7.1`

---

## 2026-05-22 — Release v3.7.0: Unified Kalshi live_state ingest, trade log hot path, expiry fix

**Summary**
- **Release: v3.7.0**
- **Kalshi market ingest:** Single `market_watchdog_ws_kalshi` process (`--market all`) replaces dual 15m/hourly watchdogs; Redis `live_state` is the hot path for ladders, orderbooks, and strike generation (PG `market_kalshi_*` writers and orderbook sidecar removed).
- **Trade monitor / history:** Split live-path WebSockets — trade log patches `sell`/`pnl` only; active-trades panel gets live `prob`; Live Path Cache Monitor debug UI replaces the old hot-path test page.
- **Tradeflow:** AES/tradeflow read symbol metrics from `live_state`; `live_symbol_status` is LP/cooldown only (no real-time tick mirror).
- **Trade manager:** Live expiry sweep skips trades until contract wall-clock expiration (fixes premature hourly `expired` at :00).
- **Database:** Migrations **`20260515_1430_live_data_strike_tables_fair_price`** (`fair_price` on strike tables) and **`20260517_1500_live_symbol_status_lp_only_drop_price_sync`** (drop price-log → `live_symbol_status` triggers); `database.py` init and **`docs/MASTER_DB_SCHEMA_REFERENCE.md`** aligned.
- **Docs:** `docs/KALSHI_MARKET_INGEST.md`, `docs/PRE_DEPLOY_CHECK_2026-05-22.md`, prod CPU/RAM baseline for post-deploy comparison.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Migration pre-flight: confirm these files exist in the deployed commit:  
  `scripts/migrations/20260515_1430_live_data_strike_tables_fair_price.up.sql`, `.down.sql`,  
  `scripts/migrations/20260517_1500_live_symbol_status_lp_only_drop_price_sync.up.sql`, `.down.sql`
- [x] Apply pending migrations from repo root before restart:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up`
- [x] Schema drift check:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh`
- [x] Verify health/logs for `main_app`, `trade_executor`, `market_watchdog_ws_kalshi`, `strike_table_generator_ws_*`, `auto_entry_supervisor`, `active_trade_supervisor`, `trade_manager`; confirm `rollover_15m` / `WS_ROLLOVER_OK` in watchdog logs and no missing-column errors.
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.7.0`

---

## 2026-05-12 — Release v3.6.1: Market-wide loss prevention, sim-trade close anchor fix

**Summary**
- **Release: v3.6.1**
- **Market-wide LP:** Per-user `system_settings` adds `market_wide_loss_prevention` (master toggle, default true), `hero_monitor_id`, and `stop_loss_count_threshold`; when enabled and the hero’s cooldown loss count meets the threshold, followers with `symbol_wide_loss_prevention` resolve to **`live_loss_market_wide_1c`** (`*_symbol_wide` persisted attribution). Merge order: local vs symbol-wide vs market-wide via existing seriousness ordering; follower sync clears stale market-wide suffixed rows when LSS is off and re-runs market-wide projection after symbol-wide fanout.
- **Sizing / consumers:** `auto_entry_supervisor` and `active_trade_supervisor` treat `live_loss_market_wide_1c` like other full live-sizing LP states; `system_settings_store` and `/api/system_settings` expose the new fields with split transaction save and fleet reconcile where applicable.
- **Monitor API:** `monitor_list_api` merges market-wide effective state and hero cooldown anchors for badges and tooltips; `main_misc_routes` wired for persistence.
- **Replay / SQL:** `time_based_loss_prevention._sql_close_anchor_timestamptz` no longer prefixes a date literal when `closed_at` is already a full ISO instant (TEXT), fixing Postgres invalid timestamp input on symbol-wide and related saves.
- **UI:** Desktop and mobile dashboard LP labels and tooltips for market-wide state, threshold line, and Eastern end time where surfaced.
- **Database:** Reversible migration **`20260512_1600_system_settings_market_wide_loss_prevention`** adds the new columns across tenant `users*` `system_settings_*` tables; `database.py` init and **`docs/MASTER_DB_SCHEMA_REFERENCE.md`** aligned.
- **Plans:** `market-wide-loss-prevention.plan.md`.

**Production checklist**
- [ ] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [ ] Migration pre-flight: confirm `scripts/migrations/20260512_1600_system_settings_market_wide_loss_prevention.up.sql` and `.down.sql` are present in the deployed commit.
- [ ] Apply pending migrations from repo root before restart:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up`
- [ ] Schema drift check:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [ ] Restart services: `./scripts/MASTER_RESTART.sh`
- [ ] Verify health/logs for `main_app`, `trade_executor`, `monitor_manager`, `auto_entry_supervisor`, `active_trade_supervisor`, `trade_manager`; confirm no missing-column errors for `market_wide_loss_prevention`, `hero_monitor_id`, or `stop_loss_count_threshold` on `system_settings_*`.
- [ ] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.6.1`

---

## 2026-05-14 — Release v3.6.0: Kalshi external-api v2 account sync, direction fields, credits history

**Summary**
- **Release: v3.6.0**
- **Kalshi hosts:** REST and WS clients use Kalshi **external-api** trade-api **v2** base URLs; v1 user routes remain on elections API where required.
- **Signing:** Trade-api v2 requests sign the path **without** query string (`?limit=`, `cursor=`, etc.) so deposits, withdrawals, account history, and paginated syncs authenticate correctly.
- **Account sync:** WS-first writes for orders and fills where supported; periodic REST reconcile; v2 **deposits** / **withdrawals** sync; **credit_history** table per tenant plus poller on balance sync.
- **Schema:** Migration **`20260513120000_account_sync_direction_credits`** adds **`outcome_side`** / **`orderbook_side`** on orders and fills (tenant tables), maps legacy **`side`**, and creates **`credits_history_<slot>`**; `docs/MASTER_DB_SCHEMA_REFERENCE.md` and `docs/PORTFOLIO_ACCOUNT_SYNC.md` updated.
- **Consumers:** `trade_manager`, `read_api`, `kalshi_historical_ingest`, account manager desktop/mobile (CSV and UI labels for outcome side).
- **Runtime:** `active_trade_supervisor` refreshes active pool rows when trade_manager re-notifies open/partial after IOC top-up so position/fees match canonical trades.
- **Plans:** Session work (account sync modernization + external-api v2 alignment); see `docs/kalshi_account_sync_preflight.md` for migration validation notes.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Migration pre-flight: confirm `scripts/migrations/20260513120000_account_sync_direction_credits.up.sql` and `.down.sql` are present in the deployed commit.
- [x] Apply pending migrations from repo root before restart:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up`
- [x] Schema drift check:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh`
- [x] Verify health/logs for `main_app`, `trade_manager`, `kalshi_account_sync`, `trade_executor`; confirm no missing-column errors for `outcome_side`, `orderbook_side`, or `credits_history_*`.
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.6.0`

---

## 2026-05-11 — Release v3.5.3: Symbol-wide loss prevention

**Summary**
- **Release: v3.5.3**
- **Behavior:** Adds symbol-wide loss prevention where `live_data.live_symbol_status` mirrors configured `user_0001` hero monitor LP state/cooldowns per symbol, and opted-in monitors use that state whenever it is not `off`.
- **Trade attribution:** Symbol-wide effective states carry `_symbol_wide` in `loss_prevention_state` for trade logs while UI labels continue to display the normal LP state text; hover tooltips show the symbol-wide source.
- **UI/API:** Monitor settings split Time-method `simulated_trade_loss_prevention` from the independent `symbol_wide_loss_prevention` checkbox.
- **UI guardrails:** Hero monitors publish symbol-wide LP and cannot enable the follower checkbox; dashboard tooltips identify symbol-wide LP without exposing the followed monitor name.
- **Database:** Reversible migration **`20260511_1455_symbol_wide_loss_prevention`** adds symbol-wide LP fields to `live_data.live_symbol_status` and adds independent `symbol_wide_loss_prevention` defaults to monitor/strategy tables.
- **Realtime:** Hero monitor LP writes update `live_symbol_status`, using the existing DB-change / Redis / WebSocket stream to notify UIs and runtime readers.
- **Plans:** `symbol-wide-lp_01a6b111.plan.md`.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Migration pre-flight: confirm `scripts/migrations/20260511_1455_symbol_wide_loss_prevention.up.sql` and `.down.sql` are present.
- [x] Apply pending migrations from repo root before restart:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up`
- [x] Schema drift check:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh`
- [x] Verify health/logs for `main_app`, `monitor_manager`, `auto_entry_supervisor`, `active_trade_supervisor`, and `trade_manager`; confirm no missing-column errors for `symbol_wide_loss_prevention` or `live_symbol_status.loss_prevention_state`.
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.5.3`

---

## 2026-05-11 — Release v3.5.2: Loss prevention consolidation

**Summary**
- **Release: v3.5.2**
- **Backend/API:** Consolidates monitor LP around master `loss_prevention_toggle`, `loss_prevention_method` (`win_streak` / `time`), and renamed `loss_prevention_state` plus generalized cooldown fields.
- **Behavior:** Win-streak LP only runs when method is `win_streak`; Time LP uses `loss_prevention_duration`, live losses trigger `live_loss_1c`, and `simulated_trade_loss_prevention` now only controls whether simulated trades participate in Time-method tiering.
- **Code organization:** Time-method LP implementation moved from `simulated_trade_loss_prevention.py` to `time_based_loss_prevention.py`.
- **UI:** Monitor settings now show one LP checkbox, method dropdown, Win Streak controls for `win_streak`, and duration plus Include Simulated Trades for `time`; LP sliders use the same value-bubble layout and section spacing as the other modal sliders.
- **Database:** Reversible migration **`20260511_1035_loss_prevention_consolidation`** renames monitor/strategy LP columns and migrates existing intent.
- **Docs:** `docs/SYSTEM_BIBLE.md` and `docs/HELP_CENTER_CONTENT_MAP.md` include the consolidated monitor loss prevention controls for future manual/help-center surfaces.
- **Plans:** Session work (loss prevention consolidation and time-based LP rename); no single canonical `Status: done` `.cursor/plans/*.md` plan slug in-repo for this batch.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Migration pre-flight: confirm `scripts/migrations/20260511_1035_loss_prevention_consolidation.up.sql` and `.down.sql` are present.
- [x] Apply pending migrations from repo root:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up`
- [x] Schema drift check:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh`
- [x] Verify health and logs: health on `3000`, `8001`, and `3050`; `venv/bin/supervisorctl -c backend/supervisord.conf status`; review `trade_manager_0001`, `trade_executor_0001`, `kalshi_account_sync_0001`, `main_app`, and one `market_watchdog_ws` log for errors after process start.
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.5.2`

---

## 2026-05-10 — Release v3.5.1: Per-monitor simulated-trade loss prevention, live_loss_1c, migrations

**Summary**
- **Release: v3.5.1**
- **Backend:** Per-monitor **simulated-trade loss prevention** (`simulated_trade_loss_prevention.py`): cycle ledger, tiered `loss_prevention` (`sim_loss_50` / `sim_loss_25` / `sim_loss_1c`), Eastern time anchors for cooldowns, startup reconcile + trade close hooks. **`live_loss_1c`**: real (non-paper) closed loss sets **`live_trade_cooldown_start_time`** and caps sizing for the same duration as sim cooldown; while live throttle is active, simulated losses may slide **`simulated_trade_cooldown_start_time`** but do **not** increment **`simulated_trade_cooldown_loss_count`** (tier cannot jump to sim tiers until live window ends or settings clear sim LP).
- **API/UI:** `monitor_list_api` exposes **`live_trade_cooldown_start_time`**, **`live_trade_cooldown_live`**, combined **`symbol_wide_cooldown_live`**; dashboard + mobile cooldown math and tooltips.
- **Consumers:** `trade_manager`, `auto_entry_supervisor`, `active_trade_supervisor`, `monitor_manager`, `read_api` / routers as staged; `symbol_wide_loss_prevention` remains a re-export shim.
- **Database:** Reversible migrations **`20260509_2000_trades_loss_prevention_state_win_streak_lp`**, **`20260509_2100_monitor_strategy_simulated_trade_columns`**, **`20260509_2200_archive_trades_loss_prevention_state`**, **`20260510_1200_monitor_live_trade_cooldown_column`**, **`20260510_1215_trades_simulated_drop_market_result`**; `database.py` init / DO blocks aligned with **`docs/MASTER_DB_SCHEMA_REFERENCE.md`**.
- **Tests:** `tests/unit/test_loss_prevention_new.py`, `test_simulated_contract_expiration.py`, `test_time_eastern.py`, flip_sell test touch-up.
- **Plans:** Session work (sim LP + live throttle); no single canonical **`Status: done`** plan slug in-repo for this batch.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] **Migration pre-flight:** Confirm the commit on the server contains every file for slugs **`20260509_2000_trades_loss_prevention_state_win_streak_lp`**, **`20260509_2100_monitor_strategy_simulated_trade_columns`**, **`20260509_2200_archive_trades_loss_prevention_state`**, **`20260510_1200_monitor_live_trade_cooldown_column`**, **`20260510_1215_trades_simulated_drop_market_result`** (each `.up.sql` / `.down.sql` under `scripts/migrations/`).
- [x] Apply pending migrations (from repo root on production):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up`
- [x] Schema drift check (non-blocking if clean):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server; wait until it finishes successfully).
- [x] Verify: `curl -sSf http://localhost:3000/health && curl -sSf http://localhost:8001/health && curl -sSf http://localhost:3050/health`; `venv/bin/supervisorctl -c backend/supervisord.conf status`; tail `trade_manager_0001`, `trade_executor_0001`, `kalshi_account_sync_0001`, `main_app`, and one `market_watchdog_ws` log for errors **after** process start (no `live_trade_cooldown_start_time` does not exist; no stuck aborted transactions from LP).
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.5.1`

---

## 2026-05-08 — CPU load reduction (read paths, trading-safe)

**Summary**
- **read_api:** Single-query `live_symbol_status_snapshot`; one-query `monitor_auto_stop_accuracy`; shared PG connection for dashboard `history-bundle`; `/core` uses one DB connection where practical, Kraken ticker short TTL cache, route timing on auto-stop + orderbook liquidity; strike-table read path tweaks; **~0.35s** TTL cache on batch orderbook liquidity map (keyed by sorted ticker set).
- **read_api logging:** [`backend/web/read_api_logging.py`](../backend/web/read_api_logging.py) attaches a flushing **stdout** handler so **`read_api_route`** lines reliably land in **`logs/read_api.out.log`** for baseline and deploy checks.
- **Deploy gate:** [`scripts/verify_read_path_deploy_ready.sh`](../scripts/verify_read_path_deploy_ready.sh) — health on **3000 / 8001 / 3050**, **`GET /core`** smoke, and grep for **`read_api_route`** in the read_api log tail.
- **main_app:** Non-blocking `requests` in dashboard read proxies and auto-entry monitor accuracy proxy (`asyncio.to_thread`); `dashboard_read_proxy` timing logs; **`/frontend-changes`** uses short TTL cache + `asyncio.to_thread` for `os.walk`.
- **Frontend:** Strike-table fallback poll **3.5s** (WS + debounced refresh remains primary).
- **Docs:** [`docs/cpu-read-path-baseline.md`](../cpu-read-path-baseline.md) for baseline/compare procedure.
- **Watchlist removal:** All watchlist API code, UI hooks, supervisor dead code, **`auto_entry_supervisor_test.py`**, and **`users.watchlist_*`** provisioning/sanitize/clone steps removed from install scripts.
- **Trading plane:** No intentional changes to `trade_manager`, `trade_executor`, `auto_entry_supervisor` **runtime** behavior, `monitor_manager`, `redis_switchboard`, or lifecycle consumers.

**Rollback**
- Revert the commit(s) touching `read_api.py`, `dashboard_portfolio_queries.py`, dashboard/auto-entry routers, `main_misc_routes.py`, and the listed frontend JS files; restart `./scripts/MASTER_RESTART.sh`.

**Verification checklist (local after restart)**
- [ ] `./scripts/verify_read_path_deploy_ready.sh` (must pass before treating read-path deploy as green)
- [ ] `curl -sSf http://localhost:3000/health && curl -sSf http://localhost:8001/health && curl -sSf http://localhost:3050/health`
- [ ] `supervisorctl` status for `read_api`, `main_app`, supervisors
- [ ] Smoke: dashboard history charts load; trade monitor strike ladder; auto-entry accuracy panel if used
- [ ] Logs: `grep -E 'read_api_route|read_api_proxy|dashboard_read_proxy' logs/*.out.log` — no spike in errors; compare hot-route ms vs prior baseline per [`docs/cpu-read-path-baseline.md`](../cpu-read-path-baseline.md)

---

## 2026-05-08 — Release v3.5.0: Slim main_app wiring, extracted backend/web routers, and tenant-literal CI guard update

**Summary**
- **Release: v3.5.0**
- **Backend architecture:** `backend/main.py` is reduced to wiring/bootstrap responsibilities, while route and middleware logic is extracted into `backend/web/*` and `backend/web/routers/*` modules.
- **Route behavior:** Main app paths remain stable while handlers are delegated through extracted router modules, including read-api proxy routes, internal service proxy routes, monitor/admin routes, auth proxy routes, and frontend/static serving routes.
- **Read path alignment:** `backend/read_api.py` is aligned with the split so main-app delegates remain behavior-compatible with the read-api edge.
- **CI guardrail:** `scripts/ci/scan_main_tenant_literals.py` now scans both `backend/main.py` and `backend/web/**/*.py`; baseline updated to match the split architecture.
- **Docs/rules:** `AGENTS.md`, `.cursor/rules/07-main-app-slim.mdc`, and related architecture/logging docs were updated to reflect the new main-app surface.
- **Plans:** `slim-main-app-architecture` (active implementation plan), `logging-audit` (`Status: done`; logging inventory alignment touch-up).
- **DB impact:** No schema migration in this release.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Restart services from repo root on production:  
  `./scripts/MASTER_RESTART.sh`
- [x] Verify runtime health after restart:  
  `curl -sSf http://localhost:3000/health && curl -sSf http://localhost:8001/health && curl -sSf http://localhost:3050/health && supervisorctl -c /opt/rec_io_server/backend/supervisord.conf status`
- [x] Verify key logs for current errors after process start (`trade_executor_0001`, `kalshi_account_sync_0001`, `main_app`, one `market_watchdog_ws` service).
- [x] Record release in DB:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.5.0`

---

## 2026-05-06 — Dashboard filenames: NEW → canonical `dashboard.html`, legacy → `*_OLD.html`

**Summary:** The former **`dashboard_NEW.html`** is now **`frontend/tabs/dashboard.html`**; the previous legacy dashboard is **`frontend/tabs/dashboard_OLD.html`**. Same pattern for mobile: **`dashboard_mobile.html`** (canonical) and **`dashboard_mobile_OLD.html`**. **`frontend/index.html`** loads **`/tabs/dashboard.html`**. **`backend/main.py`** **`/mobile/dashboard`** and **`/mobile/dashboard_new`** serve **`dashboard_mobile.html`**.

---

## 2026-05-05 — Release v3.4.8: Performance rollups schema, Redis performance snapshot, dashboard_NEW and realtime WS coordinator

**Summary**
- **Release: v3.4.8**
- **Database:** Reversible migration chain **`20260505_1200_performance_rollup_tables`** through **`20260505_1450_performance_rollups_updated_at_last`** adds per-tenant **`performance_total_*`** / **`performance_monitors_*`**, dashboard prefs column for rollup view, NOTIFY/stream wiring for **`performance_rollups`**, and follow-up PK/column renames. **`docs/MASTER_DB_SCHEMA_REFERENCE.md`** and **`database.py`** aligned in this batch.
- **Backend:** **`performance_rollups`** compute/publish path; **`monitor_manager`** closes hook; **`GET /api/dashboard/performance-snapshot`** serves the WS-shaped snapshot **from Redis only** (no DB cold-fill when Redis or the snapshot key is missing). Snapshot written to Redis on rollup publish; trading Redis comms key documented.
- **read_api / main / stream_registry:** Rollup-related reads and proxies; stream registry entries for rollup NOTIFY payloads.
- **Frontend (v3.4.8 shipping layout):** Introduced Redis-first dashboard surfaces as **`dashboard_NEW`** / **`dashboard_mobile_NEW`**; filenames were later unified (see **2026-05-06** entry). Rollup hydrate, **`realtime-ws-coordinator`**, **`__dashboardPerformanceRedisRequired`**, and **`monitor_history_display.js`** (no HTTP monitor-tiles when Redis required). Trade monitor / orderbook / strike-table / portfolio query touch-ups as staged.
- **Tooling:** **`scripts/db/backfill_performance_rollups.py`** — optional one-shot recompute from closed trades per slot.
- **Migration note:** **`20260505_1200_performance_rollup_tables`** is a **no-op**; the first applied DDL is **`20260505_1400`** (`quote_ident` for `1d_*` / `1w_*` / … column names). An earlier revision of `1200` used unquoted names starting with a digit (invalid in PostgreSQL).
- **Plans:** **`redis-platform-initiative`** (in progress; backbone + snapshot alignment), **`mtb-account-dashboard`** (`Status: done`; dashboard data surfaces).

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply pending migrations (applies all **`20260505_*`** rollup chain not yet in **`system.schema_migrations`**):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up`
- [x] Schema drift check (non-blocking if clean):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Optional — backfill rollup rows from existing closed trades (repeat slot args as needed; set **`REC_DEFAULT_USER_SCHEMA`** e.g. **`users_0001`** if the script errors without worker tenant context):  
  `REC_DEFAULT_USER_SCHEMA=users_0001 PYTHONPATH=$(pwd) venv/bin/python scripts/db/backfill_performance_rollups.py 0001`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c /opt/rec_io_server/backend/supervisord.conf status`; tail key `logs/*.out.log` / `*.err.log` for current errors after restart.
- [x] Record release in DB on **production** (must match git/changelog):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.4.8`

---

## 2026-05-03 — Release v3.4.7: Trades PnL NUMERIC(12,6), dashboard monitor PnL whole dollars

**Summary**
- **Release: v3.4.7**
- **Database:** Reversible migration **`20260503_1500_trades_pnl_numeric_6dp`** sets **`pnl`** to **`NUMERIC(12,6)`** on tenant **`trades_*`**, **`trades_simulated_*`**, and **`archive.trades_archive_{live|paper}_*`** (aligned with buy/sell and fee precision). **`database.py`** greenfield templates updated; **`docs/MASTER_DB_SCHEMA_REFERENCE.md`** updated.
- **Backend:** **`trade_manager`**, **`active_trade_supervisor`** (open-trade mirror to **`trades_*`**), and **`trade_open_telemetry_sync`** compute/store PnL at **six** decimal places; active_trades **`current_pnl`** display string stays **two** decimals for ATS UI.
- **Frontend:** Dashboard and mobile **`getMonitorStatValue`** / **`monitor_history_display`** show monitor-tile PnL **rounded to the nearest dollar** (no cents). **`monitor_list_api`** monitor **`pnl`** string matches whole-dollar formatting.
- **Assets:** **`frontend/images`** updates (PSD + new PNGs) included in this batch.
- **Plans:** Session work (PnL precision + tile display); no single **`Status: done`** `.cursor/plans/*.md` slug.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migration (idempotent):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260503_1500_trades_pnl_numeric_6dp`
- [x] Schema drift check (non-blocking if clean):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status`; tail `trade_executor_0001`, `kalshi_account_sync_0001`, `main_app`, and one `market_watchdog_ws` log for current errors.
- [x] Record release in DB on **production** (must match git/changelog):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.4.7`

---

## 2026-05-03 — Release v3.4.6: Trade fee confirm serialization, position NUMERIC(12,2), repair script

**Summary**
- **Release: v3.4.6**
- **Trade manager:** Per-trade `threading.Lock` serializes **`confirm_open_trade`** and **`confirm_close_trade`** so overlapping notifications (executor failsafe vs `positions_updated`) cannot apply the same **`orders_*`** fee twice to **`trades_*`.fees.
- **Database:** Reversible migration **`20260501_1700_trades_position_numeric_2dp`** alters **`position`** to **`NUMERIC(12,2)`** on tenant **`trades_*`**, **`trades_simulated_*`**, and **`active_trades_*`** where still integer (Kalshi fractional fills). **`database.py`** bootstrap and **`trade_manager`** / **`active_trade_supervisor`** / **`balance_snapshot`** / **`paper_collateral`** / **`main.py`** aligned; **`docs/MASTER_DB_SCHEMA_REFERENCE.md`** updated.
- **Frontend:** Active trade supervisor and mobile trade views show position with integer truncation where appropriate.
- **Tooling:** **`scripts/db/repair_trade_fees_pnl_from_orders.py`** — one-off repair of fees + PnL / ret metrics from synced order rows for a closed trade.
- **Plans:** Session work (fee accuracy, fractional position storage); no single **`Status: done`** `.cursor/plans/*.md` slug for this batch.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migration (idempotent):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260501_1700_trades_position_numeric_2dp`
- [x] Schema drift check (non-blocking if clean):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status`; tail `trade_executor_0001`, `kalshi_account_sync_0001`, `main_app`, and one `market_watchdog_ws` log for current errors.
- [x] Record release in DB on **production** (must match git/changelog):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.4.6`

---

## 2026-05-01 — Release v3.4.5: Hotfix — monitor_list symbol_wide columns (restore /api/monitors)

**Summary**
- **Release: v3.4.5**
- **Root cause:** `GET /api/monitors` (via `backend/core/monitor_list_api.py`) selects `symbol_wide_loss_prevention`, `symbol_wide_cooldown_duration`, and `symbol_wide_cooldown_start_time` on every `monitor_list_%`. Those columns existed only in **`init_database()`** repair loops, not in a shipped migration, so **production** tables never gained them → SQL error → API returned `status: error` → dashboard/trade-history UI fell back to **NEW MONITOR** only while **`/api/monitors/allocation`** (narrower SELECT) still worked.
- **Fix:** Reversible migration **`20260501_2200_monitor_list_symbol_wide_columns`** adds the three columns on all **`monitor_list_%`** under **`users`** and **`users_NNNN`** (idempotent).

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migration (idempotent):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260501_2200_monitor_list_symbol_wide_columns`
- [x] Verify: spot-check `GET /api/monitors` from the app (monitor tiles and trade-history monitor strip); `curl -sSf http://localhost:3000/health`
- [x] Record release in DB on **production**:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.4.5`

---

## 2026-05-01 — Release v3.4.4: Strategy list schema migration, monitor defaults parity, symbol-wide LP stack

**Summary**
- **Release: v3.4.4**
- **Database:** Reversible migration **`20260501_1200_strategy_list_unified_auto_trade_columns`** adds `min_cooldown_timer`, `max_cooldown_timer`, `regime_monitor_enabled`, `regime_window`, `time_in_force`, `order_type` (with CHECKs), `symbol_wide_*`, and `flip_sell_*` to every **`strategy_list_%`** under **`users`** / **`users_NNNN`** and to **`system.strategy_list_default`** when missing (idempotent). Greenfield-only DDL in **`database.py`** alone did not update existing DBs until this migration.
- **`monitor_manager`:** `get_strategy_default_settings` SELECT / dict / code fallback include the new fields; **`create_monitor`** INSERT copies them from strategy defaults; **`paper_trade`** follows strategy with **false** fallback (no longer forced true); **`symbol_wide_cooldown_start_time`** stays NULL on create.
- **Backend:** Symbol-wide loss prevention module, monitor list API surface, DB schema contract checks, **`stream_registry`** / **`trade_manager`** / supervisor alignment as in staged tree; **`docs/MASTER_DB_SCHEMA_REFERENCE.md`** updated for strategy list columns.
- **Frontend:** Unified auto-trade settings, trade monitor (desktop + mobile), dashboard hooks as staged.
- **Plans:** Session work (strategy/monitor parity, UAT); no single completed `.cursor/plans/*.md` slug.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migration (idempotent):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260501_1200_strategy_list_unified_auto_trade_columns`
- [x] Schema drift check (non-blocking if clean):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status`; tail `trade_executor_0001`, `kalshi_account_sync_0001`, `main_app`, and one `market_watchdog_ws` log for current errors.
- [x] Record release in DB on **production** (must match git/changelog):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.4.4`

---

## 2026-05-01 — Release v3.4.3: Kalshi v2 executor path, orderbook notify routing, Trade Monitor and dashboard UI

**Summary**
- **Release: v3.4.3**
- **Kalshi execution (trade_executor):** Create orders via Trade API v2 **`/portfolio/events/orders`** with YES-book **`price`**, mapped from legacy side and limit; opens keep monitor TIF normalization; **closes** use aggressive limit + **FoK**, **self_trade_prevention_type** **maker**, and treat **zero/missing fill** on close as an error so trade_manager can retry instead of silently leaving positions open.
- **Realtime:** **`stream_registry`** maps **`live_data.orderbook_kalshi_*`** table NOTIFY sources to the **`orderbook_kalshi`** stream for listeners.
- **Trade manager:** Tenant **`orders_*`** table helper (**`legacy_users_orders`**) wired into SQL that resolves Kalshi **`order_id`** for open/close bookkeeping.
- **Frontend:** Trade Monitor NEW layout (orderbook and active-trade panels), **orderbook-redis-ui** strike diff display and reduced **`#mktWindow`** churn; **trade-monitor-new-init** / **trade-execution-controller** / **active-trade-supervisor** panel alignment; **unified_auto_trade** modal partial and settings script; **dashboard** tab slimmed; **strike-table** CSS; mobile trade monitor and legacy tab hooks; symbol icon assets.
- **Tooling:** **`.cursor/rules/07-main-app-slim.mdc`** — keep **`main.py`** thin; prefer feature modules for new HTTP surface.
- **Symbol-wide loss prevention (follow-up):** `monitor_list_*` columns (`symbol_wide_loss_prevention`, `symbol_wide_cooldown_duration`, `symbol_wide_cooldown_start_time`); qualifying closed losses on **`trades.test_filter = false`** fan out cooldown start and **`loss_prevention = symbol_one_contract`** via shared helpers; AES startup reconcile + 1s expiry tick; unified modal + legacy/desktop + mobile trade monitor settings; dashboard + mobile dashboard LP-style badge showing cooldown end (ET, 15-minute rounding) with **`monitor_list`** on **`/ws/db_changes`** soft refresh. **Rollback:** paired snippets in **`backend/core/config/database.py`** (e.g. `DROP INDEX IF EXISTS users.idx_trades_<slot>_sw_lp_startup`; drop the three columns per `monitor_list_%` tenant loop).
- **Plans:** Session work (Kalshi v2 order path, orderbook UI, Trade Monitor NEW); no single completed `.cursor/plans/*.md` file for this batch.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status`; tail `trade_executor_0001`, `kalshi_account_sync_0001`, `main_app`, and one `market_watchdog_ws` log for current errors.
- [x] Record release in DB on **production** (must match git/changelog):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.4.3`

---

## 2026-04-29 — Release v3.4.2: trade_manager startup lock-timeout guard and Trade Monitor tab rollback

**Summary**
- **Release: v3.4.2**
- **Trade manager startup resilience:** `backend/trade_manager.py` now applies a short local PostgreSQL `lock_timeout` around startup `ALTER TABLE` / backfill steps for `order_id_open` and `order_id_close` and skips those steps when the table is busy, preventing lock-chain startup stalls.
- **Trade Monitor routing rollback:** `frontend/index.html` routes the Trade Monitor tab and iframe back to `trade_monitor.html` while `trade_monitor_NEW` follow-up work continues.
- **Plans:** Session hotfix work (no completed `.cursor/plans/*.md` plan file tied to this deploy batch).

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migration (idempotent):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260427_1200_live_data_kalshi_orderbook_sidecar_registry`
- [x] Apply migration (idempotent):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260428_1500_live_data_price_change_db_notify`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status`; tail `trade_executor_0001`, `kalshi_account_sync_0001`, `main_app`, and one `market_watchdog_ws` log for current errors.
- [x] Record release in DB on **production** (must match git/changelog):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.4.2`

---

## 2026-04-26 — Release v3.4.1: Kalshi execution settings, pending-before-executor, partial expiry, AES cooldown

**Summary**
- **Release: v3.4.1**
- **Kalshi execution:** **`kalshi_execution_settings`** (TIF / order-type normalization); migrations **`20260426_1600_monitor_trades_execution_settings`** and **`20260426_1600_kalshi_execution_monitor_trades_archive`** add **`time_in_force`** / **`order_type`** on tenant **`monitor_list_*`**, **`trades_*`**, **`trades_simulated_*`**, and archive **`trades_archive_*`** (UNION parity for **`GET /trades`**). **`trade_executor`**, **`trade_manager`**, **`auto_entry_settings_store`**, **`main`**, **`active_trade_supervisor`**, **`database.py`**, **`MASTER_DB_SCHEMA_REFERENCE`**, dashboard / mobile execution controls.
- **Live open path:** Insert **`pending`** row before **`send_trigger_to_executor`**; **`insert_trade`** returns **`(id, inserted_new)`** so ticket dedupe and active-row reuse never trigger a second executor submission.
- **Expiry:** **`check_expired_trades`** and **`check_expired_simulated_trades`** treat **`partial`** like **`open`** for cycle expiration.
- **AES:** **`TRADE_COOLDOWN`** **1** second (**`auto_entry_supervisor`**, test harness, **`aes_hourly_tick_replay`**).
- **Governance:** **`AGENTS.md`**, **`.cursor/rules/02-code-change-safety.mdc`**, **`.cursor/rules/05-db-migration-hygiene.mdc`** — schema changes ship via migration pairs and **`run_migration.py up`**.

**Plans:** Session work (limit-order / execution integration, trade lifecycle and expiry hardening.)

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply tenant migration if not already recorded:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260426_1600_monitor_trades_execution_settings`
- [x] Apply archive parity migration if not already recorded:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260426_1600_kalshi_execution_monitor_trades_archive`
- [x] Schema drift check:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status`; tail **`trade_executor_0001`**, **`main_app`**, **`kalshi_account_sync_0001`**, one **`market_watchdog_ws`** log; spot-check **`GET /trades`** and execution UI.
- [x] Record release in DB on **production** (must match git/changelog):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.4.1`
- [x] Record release in DB on **local** (same version string):  
  From local project root: `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.4.1`

---

## 2026-04-26 — Release v3.4.0: trade close semantics, volume retry loop, pricing parity migrations

**Summary**
- **Release: v3.4.0**
- **Trade lifecycle:** Remove persisted **`close_failed`** on tenant trades; failed closes keep **`open`** and **`trade_manager`** alerts + notifies ATS with **`close_attempt_failed`**. **`active_trade_supervisor`** handles that notification, reverts pool rows to **active**, and runs a **10s** background retry loop (**`ATS_CLOSE_VOLUME_RETRY_INTERVAL_SEC`**, default 10) until the row is **closed** / **expired**, past the Kalshi auto-close window, or gone from the pool. **`close_attempt_failed_retry`** maps to **`auto_close_retry`** for **`close_method`**.
- **Queries:** **`auto_entry_supervisor`**, **`paper_collateral`**, **`balance_snapshot`**, **`kalshi_lifecycle_*`** no longer filter on **`close_failed`**.
- **Database:** Migration **`20260425_1425_trades_initial_proj_price_fees`** — **`initial_proj_price`**, **`initial_proj_fees`** on all per-tenant **`trades_*`** / **`trades_simulated_*`**. Migration **`20260425_1438_trades_buy_sell_price_6dp`** — **`buy_price`** / **`sell_price`** precision. Migration **`20260425_1610_archive_trades_union_parity_proj_prices`** — archive UNION parity for projection/fee columns. Migration **`20260426_1520_trades_normalize_close_failed_status`** — backfill **`close_failed` → `open`** on **`trades_*`** and **`trades_simulated_*`** across **`users`** / **`users_NNNN`**.
- **`trade_manager`:** Close path, paper close / projection, **`_mark_close_trade_failed`** behavior, expiry sweeps, and related fixes aligned with the above.
- **`database.py` / `MASTER_DB_SCHEMA_REFERENCE.md`:** Init and docs aligned with new columns and **`status`** semantics (no **`close_failed`**).
- **Plans:** (session work; trade close handling, ATS retry, tenant trade pricing parity.)

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migration (idempotent):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260425_1425_trades_initial_proj_price_fees`
- [x] Apply migration (idempotent):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260425_1438_trades_buy_sell_price_6dp`
- [x] Apply migration (idempotent):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260425_1610_archive_trades_union_parity_proj_prices`
- [x] Apply migration (idempotent):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260426_1520_trades_normalize_close_failed_status`
- [x] Schema drift check:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status`; tail **`trade_executor_0001`**, **`main_app`**, **`kalshi_account_sync_0001`**, one **`market_watchdog_ws`** log for current errors.
- [x] Record release in DB on **production** (must match git/changelog):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.4.0`
- [x] Record release in DB on **local** (same version string as production):  
  From local project root: `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.4.0`

---

## 2026-04-25 — Release v3.3.2: strike Redis publish path, archive union columns, supervision stack, dashboard win streak

**Summary**
- **Release: v3.3.2**
- **Database:** Migration **`20260423_1800_strike_archive_snapshot_provenance`** — **`snapshot_wall_second`**, **`snapshot_generation_seq`** on **`historical_data.strike_table_master`**. Migration **`20260420_1800_archive_trades_initial_price_slippage_initial_count`** — **`initial_price`**, **`slippage`**, **`initial_count`** on every **`archive.trades_archive_live_*`** / **`archive.trades_archive_paper_*`** table (UNION parity with master **`trades_*`**).
- **Strike / archive path:** **`strike_snapshot_publisher`**, **`strike_snapshot_redis`**, **`strike_ladder_fetch`**; **`historical_strike_table_archive`** publisher-first append and runtime DDL guard; default **`REC_STRIKE_TABLE_ARCHIVE_SOURCE=publisher`** via generated supervisor env when unset.
- **Workers / ingest:** **`monitor_manager`** tenant pool proxy, bounded wait, unified AES/ATS sync per slot; **`active_trade_supervisor`**, **`auto_entry_supervisor`**, **`market_watchdog_ws`**, **`kalshi_event_market_readiness`**; **`generate_unified_supervisor_config`** updates.
- **Reliability / tenancy:** **`drawdown_emergency_restore`** + **`restore_drawdown_emergency_monitors`**; **`tenant_provision`** advisory lock and retries; **`system_settings_store`** / **`main`** touchpoints as in diff.
- **Frontend:** Dashboard and mobile **`win_streak`** tooltips use **`monitor.win_streak`**; **`monitor_history_display`** does not overwrite **`data-win-streak`** from rolling history stats.
- **Ops / docs:** **`docs/PRODUCTION_HOST.md`**; **`scripts/prod/rec_prod_ssh.sh`**, **`scripts/prod/simple_git_pull_on_prod.sh`**; tests (**`test_active_trade_supervisor_flip_sell`**, **`test_market_watchdog_ws_readiness`**); optional **`docs/investigations/`** note.
- **Plans:** (session work; consolidated from 2026-04-23 strike snapshot checklist plus trading/UI follow-ups.)

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migration (idempotent):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260423_1800_strike_archive_snapshot_provenance`
- [x] Apply migration (idempotent):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260420_1800_archive_trades_initial_price_slippage_initial_count` (already recorded applied on prod before this pull; runner may report “already applied”.)
- [x] Schema drift check:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `cd /opt/rec_io_server && supervisorctl -c backend/supervisord.conf status`; confirm **`strike_snapshot_publisher`** is **RUNNING**; tail **`trade_executor_0001`**, **`main_app`**, one **`market_watchdog_ws`** program log for current errors.
- [x] Record release in DB on **production** (must match git/changelog):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.3.2`
- [x] Record release in DB on **local** (same version string as production):  
  From local project root: `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.3.2`

---

## 2026-04-20 — Release v3.3.1: trades intent columns, trade_manager tenant SQL, paper collateral recovery hook

**Summary**
- **Release: v3.3.1**
- **Database:** Migration **`20260420_1230_trades_initial_price_slippage_initial_count`** — **`initial_price`**, **`slippage`**, **`initial_count`** on every per-tenant **`trades_*`** table under **`users`** and **`users_NNNN`**.
- **`trade_manager`:** Tenant-qualified SQL for live and simulated **`insert_trade`** (resolved table names in idempotency, cooldown, monitor read, and INSERT) so workers always write the correct slot.
- **`database.py`:** Init-time DDL aligned with the new trade columns.
- **`MASTER_DB_SCHEMA_REFERENCE`:** Documents the new columns.
- **`paper_collateral`:** Optional **`REC_SKIP_PAPER_COLLATERAL_CAP`** (dev/recovery only; logs a warning) to bypass the paper open collateral cap when local state is temporarily inconsistent.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migration (skip errors if already applied):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260420_1230_trades_initial_price_slippage_initial_count`
- [x] Schema drift check (recommended):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status`; tail `trade_executor_0001`, `main_app` for current errors.
- [x] Record release in DB on **production** (must match git/changelog):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.3.1`
- [x] Record release in DB on **local** (same version string as production):  
  From local project root: `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.3.1`

---

## 2026-04-20 — Release v3.3.0: tenant SQL literal cleanup and schema naming clarity

**Summary**
- **Release: v3.3.0**
- **Tenant SQL hygiene:** Replaced hardcoded tenant table literals in runtime code and operator/backfill/diagnostic scripts with tenant-aware resolution (`TenantContext` + legacy SQL helpers), including new helper module **`backend/core/tenant_legacy_sql.py`**.
- **Bootstrap/runtime alignment:** `backend/core/config/database.py` init-time DDL now derives and applies the active tenant slot suffix at runtime rather than assuming `_0001`.
- **Guardrails:** `scripts/ci/check_tenant_sql_literals.py` expanded checks so raw tenant literals (for active code paths) are caught consistently; tests updated for tenant-safe references.
- **Docs:** `docs/MASTER_DB_SCHEMA_REFERENCE.md` and related docs now explicitly document `users_NNNN` physical schemas, legacy `users.*_NNNN` rewrite behavior, and that `0001` headings are illustrative slot examples.
- **Plans:** `db-prod-schema-alignment.md` (follow-up schema/documentation consistency work).

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status`; tail `main_app`, `trade_executor_0001`, `kalshi_account_sync_0001`, and one `market_watchdog_ws` log for current errors.
- [x] Record release in DB on **production** (must match git/changelog):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.3.0`
- [x] Record release in DB on **local** (same version string as production):  
  From local project root: `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.3.0`

---

## 2026-04-19 — Release v3.2.0: Postgres connection budget, ATS strike-table probability, supervisor config batching

**Summary**
- **Release: v3.2.0**
- **Database:** Migration **`20260416_1810_archive_trades_win_loss_confirmed_match_master`** (if not already applied on production) — nullable **`win_loss_confirmed`** on all **`archive.trades_archive_{live|paper}_*`** for union parity with master trades; schema reference already documents this migration.
- **Runtime / Postgres:** **`backend/core/config/database.py`** — transient **`OperationalError`** retries on connect; **warning** logs with severity tokens stripped (avoids noisy `FATAL` lines in app logs). **`backend/monitor_manager.py`** — small **per-process `ThreadedConnectionPool`** for tenant DB (env **`REC_MONITOR_MANAGER_PG_POOL_MAX`**, default 4). **`backend/market_watchdog_ws.py`** — lower default DB pool cap (env **`REC_MARKET_WATCHDOG_DB_POOL_MAX`**, default 8). **`scripts/MASTER_RESTART.sh`** — **5s** post-kill wait so Postgres releases sessions before the next spawn burst.
- **`backend/core/exchange_credentials.py`** — **`fetch_kalshi_enabled_map_for_user_nos`** (single query); **`scripts/config/generate_unified_supervisor_config.py`** uses it so config regen does not open one system connection per tenant.
- **ATS:** **`backend/active_trade_supervisor.py`** — **`get_current_probability_from_live_strike_table`** reads side-aware model probability from **`live_data.strike_table_*`** by **ticker** (aligned with UI / strike pipeline); existing lookup path is **fallback** only when the row is missing.
- **Governance:** **`.cursor/rules/06-tenant-users-schema-parity.mdc`** (always-on): tenant DDL must cover all **`users_NNNN`** schemas, not a single slot.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migration (skip errors if already applied):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260416_1810_archive_trades_win_loss_confirmed_match_master`
- [x] Schema drift check (recommended):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status`; tail `kalshi_account_sync_0001.out.log` for baseline + WS OK.
- [x] Record release in DB on **production** (must match git/changelog):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.2.0`
- [x] Record release in DB on **local** (same version string as production):  
  From local project root: `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.2.0`

---

## 2026-04-19 — Release v3.1.8: strike_table_master Eastern wall timestamps

**Summary**
- **Release: v3.1.8**
- **Database:** Migration **`20260426_1430_strike_table_master_eastern_naive_timestamp`** — `historical_data.strike_table_master` **`timestamp`** / **`created_at`** are **`TIMESTAMP WITHOUT TIME ZONE`** (US Eastern wall), aligned with other `historical_data` time-series; monthly partitions use **Eastern calendar** bounds; existing rows converted from legacy `TIMESTAMPTZ` via `AT TIME ZONE 'America/New_York'`.
- **Runtime:** **`backend/historical_strike_table_archive.py`** — writes Eastern naive on insert; partition ensure uses Eastern months. **`backend/core/time_eastern.py`** — **`eastern_wall_naive()`**. **`backend/core/config/database.py`** — bootstrap DDL/partition DO block match.
- **Backtest:** **`tick_backtest_build.build_tick_backtest_from_strike_archive`** — reads archive timestamps as already-Eastern naive (no double `AT TIME ZONE`).
- **Docs:** **`MASTER_DB_SCHEMA_REFERENCE`**, **`BACKTESTING.md`** — archive timestamp semantics.
- **Plans:** (session work; archive timestamp convention parity.)

**Deploy order (prod):** pull → **`MASTER_RESTART.sh`** (strike writers load new Python) → verify → **then** migration (schema matches writers) → drift → `record_system_version`.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server) **before** migration so processes load `eastern_wall_naive` archive writes.
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status`; tail `main_app` / `trade_executor_0001` / `kalshi_account_sync_0001` logs.
- [x] Apply migration (from project root on the server):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260426_1430_strike_table_master_eastern_naive_timestamp`
- [x] Schema drift check (recommended):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Record release in DB on **production** (must match git/changelog):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.1.8`
- [x] Record release in DB on **local** (same version string as production):  
  From local project root: `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.1.8`

---

## 2026-04-16 — Release v3.1.7: trades list index, shared trade fetch JS, history insights and UI

**Summary**
- **Release: v3.1.7**
- **Database:** Migration **`20260416_1730_trades_date_id_list_index`** — composite **`(date, id DESC)`** index on every matching **`users_<slot>.trades_<slot>`** and **`archive.trades_archive_{live|paper}_<slot>`** for **`GET /trades`** date filters with keyset / `ORDER BY id DESC` (avoids large sorts on wide windows).
- **Backend:** **`trades_list_query`** refinements; **`trades_history_insights`** expanded behavior; **`trade_log_archivist`** updates aligned with trade history flows.
- **Frontend:** New shared **`frontend/js/rec_trades_fetch.js`** (wired from trade history, trade monitor, dashboard desktop/mobile, test harness); **trade history** desktop and **mobile** refactors; small **dashboard** / **trade monitor** / **`monitor_history_display`** / **`trade-execution-controller`** adjustments.
- **Scripts / research (optional on prod):** **`scripts/db/explain_trades_list.py`**; **`scripts/backtest/aes_hourly_contract_replay.py`** and **`scripts/backtest/helpers/aes_hourly_tick_replay.py`** — AES hourly replay helpers.
- **Docs / planning:** **`MASTER_DB_SCHEMA_REFERENCE`** index note for the migration; **`.cursor/plans/trading_pipeline_coherence_future_plan.md`** (internal future plan, no runtime effect).

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migration (from project root on the server):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260416_1730_trades_date_id_list_index`
- [x] Schema drift check (recommended):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status`; spot-check trade history and monitor pages load **`rec_trades_fetch.js`** without console errors.
- [x] Record release in DB on **production** (must match git/changelog):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.1.7`
- [x] Record release in DB on **local** (same version string as production):  
  From local project root: `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.1.7`

---

## 2026-04-16 — Release v3.1.6: trade history read_api split, monitor tiles, insights, preferences column

**Summary**
- **Release: v3.1.6**
- **Database:** Migration **`20260416_1500_trade_history_preferences_monitor_selection`** — per-tenant `trade_history_preferences_*`.`monitor_selection` JSONB (`mon_<slot>_<id>` → checked) for persisted monitor strip state.
- **Backend:** **`read_api`** — tenant **`GET /trades`** (keyset paging, shared query **`trades_list_query`**), **`POST /api/trades/history/insights`** (**`trades_history_insights`**); trade history **GET/POST `/api/get_trade_history_preferences`** and **`/api/set_trade_history_preferences`** via **`trade_history_preferences_store`** / **`trade_history_preferences_handlers`**. **`main_app`** trimmed (trade list + insights + preferences proxied or removed in favor of read_api patterns per `AGENTS.md`).
- **Frontend — trade history (desktop):** Monitor **tile strip** with off-tile **preview** (chart + per-monitor table + top summary via insights body), **cross-highlight** that survives live `/trades` refresh, **analysis** bar chart styling aligned with monitors Ret % chart (colors, grid opacity, always-on “highlighted” bar fill), slightly **redder** negative bars.
- **Frontend — trade history (mobile) + dashboard:** Parity and wiring updates; monitor list / preferences refresh behavior aligned with **`/api/monitors`** and realtime preferences channel where applicable.
- **Ops / plumbing:** **`trading_redis_comms`**, **`stream_registry`**, **`kalshi_account_sync_ws`**, **`monitor_manager`**, **`exchange_credentials`**, **`auth_routes`** — adjustments supporting the above (no intentional behavior regressions).
- **Backtest scripts:** **`htc_backtest_replay`**, **`htc_setting_grid_sweep`**, **`htc_archive_setting_sweep`** — incremental fixes/features as in diff.
- **Docs:** **`AGENTS.md`**, **`MASTER_DB_SCHEMA_REFERENCE`** (`monitor_selection`).
- **Plans:** (session work; trade history UX + read service extraction + preferences persistence.)

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migration (from project root on the server):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260416_1500_trade_history_preferences_monitor_selection`
- [x] Schema drift check (recommended):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status`; spot-check trade history (tiles, preview, summary, analysis chart).
- [x] Record release in DB on **production** (must match git/changelog):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.1.6`
- [x] Record release in DB on **local** (same version string as production):  
  From local project root: `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.1.6`

---

## 2026-04-15 — Release v3.1.5: archive tick backtest build, HTC setting grid sweep, synthetic grid_sweep_trades

**Summary**
- **Release: v3.1.5**
- **Database:** Migration **`20260416_1015_backtest_grid_sweep_trades`** — `backtest.grid_sweep_trades` (LIKE `users_0001.trades_0001` + `sweep_batch_id`, `synthetic_monitor_id`, `source_monitor_id`) for persisted sweep replays.
- **Backtest / research:** `tick_backtest_build.build_tick_backtest_from_strike_archive` (windowed slices from `historical_data.strike_table_master`); **`core_backtester.py`** flag **`--build-tick-backtest-from-archive`**. **`htc_backtest_replay`**: `fetch_monitor_trade_meta`, tick row payloads on replay, `ret_pct_reference_balance` surfaced on output.
- **Grid sweep:** `htc_setting_grid_sweep.py`, CLI **`htc_archive_setting_sweep.py`** — Cartesian monitor overrides over archive markets; **compounding** bankroll across markets (default); **`--persist-trades`** → `backtest.grid_sweep_trades`; **`grid_sweep_trades.py`** inserts trade-shaped rows.
- **Docs:** `BACKTESTING.md` §5.5–5.6, `scripts/backtest/README.md`, `MASTER_DB_SCHEMA_REFERENCE` (`backtest.grid_sweep_trades`).
- **Plans:** (session work; archive-backed tick replay + optimization sweep persistence.)

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`  
  (Note: unstaged edits on prod were stashed as `autostash before v3.1.5 pull`; review with `git stash list` / `git stash show` on the server if needed.)
- [x] Apply migration (from project root on the server):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260416_1015_backtest_grid_sweep_trades`
- [x] Schema drift check (recommended):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c /opt/rec_io_server/backend/supervisord.conf status` (no application restart required for this release unless you choose to align with a full deploy).
- [x] Record release in DB on **production** (must match git/changelog):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.1.5`
- [x] Record release in DB on **local** (same version string as production):  
  From local project root: `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.1.5`

---

## 2026-04-15 — Release v3.1.4: historical strike archive, lifecycle settlement backfill, WS pipeline health defaults

**Summary**
- **Release: v3.1.4**
- **Database:** Migration **`20260415_1730_historical_strike_table_master_partitioned`** — `historical_data.strike_table_master` (monthly partitions on `timestamp`), indexes, bootstrap partitions for current month + next two. **`init_database()`** parity in `backend/core/config/database.py`.
- **Archive:** `backend/historical_strike_table_archive.py` — append live strike rows (unified 15m/hourly shape + `market_ticker`, `market_result`) after each live insert; partition ensure-on-write; **`REC_STRIKE_TABLE_ARCHIVE`** toggle (`0` disables). Ops helper **`scripts/db/maintain_strike_archive_partitions.py`** for future months (optional cron).
- **Writers:** `strike_table_generator.py` / **`strike_table_generator_ws.py`** — archive hook; WS **`evaluate_pipeline_health`** ties freshness strictness to **`STRIKE_PIPELINE_HEALTH_STRICT_MODE`** (fail-closed path) and **`STRIKE_PIPELINE_FRESHNESS_STRICT`**; clearer degraded/masked logging on startup prime and refresh.
- **Lifecycle:** `kalshi_lifecycle_trade_outcome.py` — after successful market result commit, **`backfill_strike_archive_market_result`** updates archive rows by `market_ticker`.
- **Supervisor:** `generate_unified_supervisor_config.py` — default env for strike pipeline programs: **`STRIKE_PIPELINE_HEALTH_STRICT_MODE=1`**, **`STRIKE_PIPELINE_FRESHNESS_STRICT=1`**, **`PIPELINE_HEALTH_WRITER_DEAD_SEC=900`**, **`PIPELINE_CATASTROPHIC_TRANSPORT_SEC=600`** when not already set (regenerate config on prod before restart).
- **Docs:** `MASTER_DB_SCHEMA_REFERENCE` — `strike_table_master` section.
- **Plans:** (session work; durable strike snapshots + pipeline health alignment.)

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations (from project root; includes **`20260415_1730_historical_strike_table_master_partitioned`** if not yet applied):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up`
- [x] Schema drift check (recommended):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Regenerate supervisor config:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/config/generate_unified_supervisor_config.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status`; spot-check strike generators and pipeline health if needed.
- [x] Record release in DB on **production** (must match git/changelog):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.1.4`
- [x] Record release in DB on **local** (same version string as production):  
  From local project root: `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.1.4`

---

## 2026-04-15 — Release v3.1.3: auto-stop monitor UI, credential log noise, read_api docs

**Summary**
- **Release: v3.1.3**
- **Frontend:** Unified auto-trade modal — keep **Flip Sell** (checkbox and multipliers) **right-aligned** when 7d/30d accuracy lines are short; auto-stop accuracy lines show **`pct · confirmed/total losses confirmed`**, with **`-`** when there is no losing-trade data in the window; **dashboard** `normalizeMonitorIdForApi` accepts **`mon_*`** tile ids **case-insensitively**. **Dashboard**, **trade monitor**, and **mobile dashboard** updated consistently.
- **Backend:** `exchange_credentials` — demote common paper/missing-column paths from **warning/info** to **debug** so supervisors are not noisy on restart.
- **API docs:** `read_api` docstrings for **monitor auto-stop accuracy** clarified (behavior unchanged).
- **Plans:** (session work; monitor settings UX and ops logging.)

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Schema drift check (recommended):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Regenerate supervisor config:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/config/generate_unified_supervisor_config.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status`; spot-check monitor auto-trade modal (Flip Sell alignment, accuracy lines).
- [x] Record release in DB on **production** (must match git/changelog):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.1.3`
- [x] Record release in DB on **local** (same version string as production):  
  From local project root: `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.1.3`

---

## 2026-04-14 — Release v3.1.2: admin tools, monitor_list realtime, ops and registration polish

**Summary**
- **Release: v3.1.2**
- **Database:** `20260414_2000_system_master_users_rec_io_db_notify`, `20260414_2100_system_master_users_drop_legacy_columns`, `20260414_2200_system_master_users_last_login`, and **`20260423_1100_tenant_monitor_list_rec_io_db_notify`** (per-tenant `monitor_list_*` → `rec_io_db_notify`, stream **`monitor_list`**). Runner applies any pending id in order.
- **Backend:** `master_users` admin API — active **Monitors** count per tenant, supervisor resync hooks, registration/activation email, `read_api` / `main_app` / `system_monitor` / Kalshi sync and trading alignment, `stream_registry` **`monitor_list`** mapping.
- **Frontend:** **Admin Tools** tab (search, layout, date display, WebSocket refetch on **`master_users`** + **`monitor_list`**), **index.html** admin icon attention state via **`/ws/db_changes`**, system UI and **`rec_session`** updates, admin icon assets.
- **Docs:** `MASTER_DB_SCHEMA_REFERENCE`, `REALTIME_BACKBONE`, registration guide; supervisor/config and manage scripts as needed.
- **Plans:** (session work; admin UX + realtime backbone alignment.)

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations (from project root; applies every pending id):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up`
- [x] Schema drift check (recommended):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Regenerate supervisor config:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/config/generate_unified_supervisor_config.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status`; spot-check Admin Tools and login.
- [x] Record release in DB on **production** (must match git/changelog):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.1.2`
- [x] Record release in DB on **local** (same version string as production):  
  From local project root: `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.1.2`

---

## 2026-04-14 — Release v3.1.0: tenant schemas, web auth, system version, trading/supervisor alignment

**Summary**
- **Release: v3.1.0**
- **Database:** Catch-up chain from **`20260409_2100`** through **`20260422_1000`** — system settings, `master_users` strategy list + registration + password hash + `exchange_credentials`, `users` → `users_0001`, tenant RLS session GUC, monitor list serial/seq fixes, active trades default, trades `rec_io_db_notify` per tenant schema, tenant balance trade timestamps, backtest historical trades API, drop legacy Kalshi user-info tables on master, and **`system.version_control`**. Each id has a paired **`.down.sql`** (reversible rollbacks).
- **Backend / web:** Multi-tenant context, web auth and session routes, trading Redis consumers and graceful shutdown paths, Kalshi account sync / lifecycle, `read_api` / `main_app` alignment, paper collateral, supervisor config generation, ops (`read_system_version.py`, `record_system_version.py`).
- **Frontend:** Login/register, `rec_session.js`, dashboard and mobile updates, system status version + last-updated row.
- **Docs / CI:** Schema reference, tenant touch registry, SMTP secrets README pattern, workflow and AGENTS updates.
- **Plans:** `db-prod-schema-alignment` (and related multi-session work).
- **Deploy notes (2026-04-14):** Droplet snapshot `rec-io-prod-pre-update-2026-04-14`. Pull required moving aside an untracked `backend/data/secrets/README.md` on the server. **`ALTER ROLE rec_io_user NOBYPASSRLS`** was applied once as **`postgres`** so RLS could take effect (migration also skips that `ALTER` when the runner is not a superuser). Pending migrations were applied with **`PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up`** (applies every missing id in sorted file order). Follow-up commits on `main` after the initial release commit: RLS migration superuser gate, `rec.tenant_pg_schema` in monitor_list sequence migrations, RLS-safe tenant subaccount seeding in `tenant_provision`.

**DB migrations (required on production, strict timestamp order — runner skips already-applied ids)**
1. `20260409_2100_system_settings_0001`
2. `20260409_2200_system_master_users_strategy_list`
3. `20260409_2300_system_strategy_list_rename_to_default`
4. `20260410_1000_system_settings_trading_halt_active`
5. `20260410_1000_trades_monitor_confirmed_default_null`
6. `20260410_1015_users_master_users_to_system`
7. `20260410_1020_system_master_users_registration_columns`
8. `20260410_1030_system_master_users_user_id_unique`
9. `20260410_2100_system_master_users_exchange_credentials`
10. `20260411_1100_system_settings_drawdown_halt_monitor_snapshot`
11. `20260411_1100_transfers_paper_0001`
12. `20260411_1200_trades_close_method_auto_to_auto_probability`
13. `20260411_1300_rename_users_schema_to_users_0001`
14. `20260411_1500_rec_tenant_rls_session_guc`
15. `20260411_1605_system_master_users_password_hash`
16. `20260411_1700_tenant_monitor_list_id_serial`
17. `20260412_1000_monitor_test_filter_trade_history_include_test`
18. `20260412_1015_monitor_list_seq_slot_prefix_resync`
19. `20260412_1500_monitor_list_seq_ignore_misplaced_99xxx`
20. `20260412_1630_active_trades_pool_status_default`
21. `20260412_2000_trades_tenant_schemas_rec_io_db_notify`
22. `20260412_2145_tenant_balance_trade_timestamps`
23. `20260413_1000_backfill_paper_trade_for_test_filter_monitors`
24. `20260414_1000_backtest_kalshi_candles_1m_kxbtc15m_26mar051345_45`
25. `20260415_1200_backtest_rename_kalshi_candles_tables_to_backtest_1m`
26. `20260416_1000_backtest_1m_add_spot_price_columns`
27. `20260417_1000_backtest_1m_rename_spot_to_price_history_names`
28. `20260418_1000_backtest_1m_running_ask_15m_columns`
29. `20260419_1000_backtest_1m_rename_cycle_ask_to_price_15m`
30. `20260420_1000_system_master_users_registration_user_no`
31. `20260420_1010_system_master_users_widen_first_last_name`
32. `20260420_1200_system_master_users_email_verification`
33. `20260420_1430_backtest_kalshi_historical_trades_api`
34. `20260421_1400_master_users_kalshi_drop_user_info_tables`
35. `20260422_1000_system_version_control`

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations (from project root; applies every pending id in sorted order — same ids as numbered list above; or run each `run_migration.py up <id>` individually):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up`
- [x] Schema drift check (recommended):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Regenerate supervisor config:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/config/generate_unified_supervisor_config.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status`; spot-check login, dashboard, system version display.
- [x] Record release in DB: `PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version 3.1.0`

---

## 2026-04-09 — System settings, trading halt UI, MTB bankroll chart, drawdown/monitor wiring, backtest schema helpers

**Summary**
- **Database:** `users.system_settings_0001` (drawdown halt + threshold), trading halt active flag, drawdown halt monitor snapshot columns (migrations `20260409_2100_system_settings_0001`, `20260410_1000_system_settings_trading_halt_active`, `20260411_1100_system_settings_drawdown_halt_monitor_snapshot`). Backtest 1m candle / price-history table lineage (`20260414_1000` through `20260419_1000` slugs below).
- **Backend:** `system_settings_store`, drawdown emergency restore path, `monitor_manager` / balance snapshot / `main.py` APIs (system settings, account balance includes `master_trading_bankroll`), `read_api` bankroll history uses `COALESCE(master_trading_bankroll, bankroll_current)`, `auto_entry_htc_gates`, `prod_target`, analytics GUI tweaks, Kalshi sync touch-up.
- **Frontend:** Dashboard + mobile — trading halt badge, system settings popover, portfolio header stacking/cursor fixes, Bankroll tab chart and top line use master trading bankroll (MTB); `.env.example` hints.
- **Scripts / tests:** Backtest helpers (`backtest_price_history`, strike span, HTC replay, Kalshi ticker construct), `restore_drawdown_emergency_monitors.py`, unit tests for backtest columns and ticker construct.

**Plans:** (mixed session work; related: `mtb-account-dashboard`, monitor/dashboard UX)

**DB migrations (required on production, in timestamp order — runner skips already-applied ids)**
1. `20260409_2100_system_settings_0001`
2. `20260410_1000_system_settings_trading_halt_active`
3. `20260411_1100_system_settings_drawdown_halt_monitor_snapshot`
4. `20260414_1000_backtest_kalshi_candles_1m_kxbtc15m_26mar051345_45`
5. `20260415_1200_backtest_rename_kalshi_candles_tables_to_backtest_1m`
6. `20260416_1000_backtest_1m_add_spot_price_columns`
7. `20260417_1000_backtest_1m_rename_spot_to_price_history_names`
8. `20260418_1000_backtest_1m_running_ask_15m_columns`
9. `20260419_1000_backtest_1m_rename_cycle_ask_to_price_15m`

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations (from project root on server, in order above):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260409_2100_system_settings_0001`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260410_1000_system_settings_trading_halt_active`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260411_1100_system_settings_drawdown_halt_monitor_snapshot`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260414_1000_backtest_kalshi_candles_1m_kxbtc15m_26mar051345_45`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260415_1200_backtest_rename_kalshi_candles_tables_to_backtest_1m`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260416_1000_backtest_1m_add_spot_price_columns`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260417_1000_backtest_1m_rename_spot_to_price_history_names`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260418_1000_backtest_1m_running_ask_15m_columns`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260419_1000_backtest_1m_rename_cycle_ask_to_price_15m`
- [x] Schema drift check (recommended):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; spot-check dashboard Bankroll tab (MTB series), system settings popover, trading halt visibility; `read_api` healthy if used.

---

## 2026-04-08 — Paper subaccounts id parity + automatic MTB rake in paper mode

**Summary**
- **DB:** Rebuild **`users.subaccounts_paper_0001`** so each row’s **`id`** matches **`users.subaccounts_0001`** for the same **`subaccount`** (preserves paper balances). Migration **`20260407_1200_subaccounts_paper_id_match_live_0001`**.
- **DB:** Restore paper **`automatic_transfers`** from legacy “all false” where appropriate without clobbering paper-only TRUE (**`p OR live`**). Migration **`20260407_1210_paper_subaccounts_mirror_automatic_transfers`**.
- **Backend:** **`balance_snapshot`:** paper snapshots use **`record_internal_transfers=True`**; automatic rake rows insert into **`users.transfers_paper_0001`** (parity with live **`transfers_0001`**).
- **Docs:** **`MASTER_DB_SCHEMA_REFERENCE`** — paper subaccount ids and **`automatic_transfers`** behavior.

**Plans:** (session work; paper parity)

**DB migrations (required on production, in timestamp order — runner skips already-applied ids)**
1. `20260407_1200_subaccounts_paper_id_match_live_0001`
2. `20260407_1210_paper_subaccounts_mirror_automatic_transfers`

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations (from project root on server, in order above):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260407_1200_subaccounts_paper_id_match_live_0001`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260407_1210_paper_subaccounts_mirror_automatic_transfers`
- [x] Schema drift check (recommended):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; spot-check paper MTB target-rake and **`transfers_paper`** when `automatic_transfers` is true.

---

## 2026-04-07 — Monitor test_filter, trade history TEST filter and styling, paper-only test monitors

**Summary**
- **Database:** `test_filter BOOLEAN` on all `users.monitor_list_*` tables; `include_test_trades` on `users.trade_history_preferences_0001`; backfill sets `paper_trade = TRUE` where `test_filter` is true (migrations below).
- **Trading / API:** New and closed trades carry `test_filter`; paper balance ledger skips test-filter trades; `insert_trade` / monitor paths force paper for test-filter monitors; monitor APIs expose effective paper mode and block LIVE when test filter is on; preferences API for `include_test_trades`.
- **Auto-entry:** Enabling test filter forces paper trading in `auto_entry_settings_store` / apply paths.
- **Frontend:** Dashboard monitor tiles use a **red border** for test-filter monitors (desktop + mobile); trade history **TEST** toggle with preference persistence; `test_filter` trade rows use dark red background (desktop + mobile).

**Plans:** (session work; no single `.cursor/plans` file for the full batch)

**DB migrations (required on production, in timestamp order — runner skips already-applied ids)**
1. `20260412_1000_monitor_test_filter_trade_history_include_test`
2. `20260413_1000_backfill_paper_trade_for_test_filter_monitors`

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations (from project root on server, in order above):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260412_1000_monitor_test_filter_trade_history_include_test`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260413_1000_backfill_paper_trade_for_test_filter_monitors`
- [x] Schema drift check (recommended):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Regenerate supervisor config if your deploy relies on it:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/config/generate_unified_supervisor_config.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status` shows key programs RUNNING; spot-check test-filter monitor settings, trade history TEST filter, and dashboard tile border.

---

## 2026-04-06 — Flip-sell monitor flags, UAT modal position save, trade history monitor labels, analysis chart, trades close_method backfill

**Summary**
- **Monitor list / auto-entry:** `flip_sell_prob`, `flip_sell_floor`, `flip_sell_prob_mult`, `flip_sell_floor_mult` on `users.monitor_list_0001` (migration `20260406_1400_monitor_flip_sell`); shared **`backend/core/auto_entry_settings_store.py`**; API and **`auto_entry_supervisor`** / **`monitor_manager`** wiring; docs **`TRADING_REDIS_COMMS`** / schema reference updates.
- **Redis / read API:** `trading_redis_comms` extensions and **`read_api`** adjustments as in repo (preferences / strike-driven paths).
- **Unified auto-trade modals:** **`frontend/js/uat_unified_modal_position_size.js`** — deferred position persistence until Save; dashboard, trade monitor, and mobile surfaces wired; cancel restores snapshot.
- **Trade history:** Monitor dropdown labels **`{id} - {symbol} {strategy}, {market}`** from **`GET /api/monitors`** (active rows, same ordering as dashboard); desktop + mobile refresh on **`monitor_list_updated`** over **`/ws/preferences`**; **`SELECT_MONITOR`** postMessage matches `data-monitor-id`.
- **Trade history analysis:** Bar chart redraw gated by rounded period fingerprint + **`animation: false`**; resize uses **`chart.resize()`**; fewer duplicate listeners.
- **Trades log backfill:** Migration **`20260411_1200_trades_close_method_auto_to_auto_probability`** sets `close_method` from `auto` → `auto_probability` on live, simulated, and archive trade tables (legacy archive table if present).

**Plans:** (mixed session work; no single `.cursor/plans` file for the full batch)

**DB migrations (required on production, in timestamp order — runner skips already-applied ids)**
1. `20260406_1400_monitor_flip_sell`
2. `20260411_1200_trades_close_method_auto_to_auto_probability`

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations (from project root on server, in order above):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260406_1400_monitor_flip_sell`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260411_1200_trades_close_method_auto_to_auto_probability`
- [x] Schema drift check (recommended):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Regenerate supervisor config if your deploy relies on it:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/config/generate_unified_supervisor_config.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status` shows key programs RUNNING; spot-check unified modal position Save/Cancel and trade history monitor filter.

---

## 2026-04-06 — Global paper trading mode, paper balance tables, dashboard and account manager UI

**Summary**
- **Trading mode:** Persisted `live` | `paper` in `backend/trading_mode.py` (same JSON path as account mode); API `GET/POST /api/trading_mode`, `GET /api/set_trading_mode`; WebSocket broadcast for mode; read paths switch `account_balance` / `subaccounts` / `transfers` / fills-positions-settlements where applicable; executor and sync guarded for paper; `balance_snapshot` / Kalshi sync refactored for shared apply path; `paper_bankroll` seed endpoint and NOTIFY stream `account_balance_paper`.
- **Database:** New paper mirror tables (`account_balance_paper_0001`, `subaccounts_paper_0001`, etc.), `transfers_paper_0001`, balance integer alignment migration; `stream_registry` and `MASTER_DB_SCHEMA_REFERENCE` updated.
- **Frontend:** Dashboard and mobile trading mode picker (LIVE/PAPER styling), paper-aware fetches and panels; account manager Paper balance modal and transfers stream; trade monitor labels; trading mode overlay separator CSS fix (flex shrink); assorted parity and db_changes streams.
- **Ops:** `MASTER_RESTART` / watchdog hooks as changed in repo; mode-sensitive APIs use `Cache-Control: no-store` where applicable.

**Plans:** (paper feature work; related direction in `unified-aes-ats-strike-driven-refactor` where overlapping)

**DB migrations (required on production, in timestamp order — runner skips already-applied ids)**
1. `20260404_1200_paper_account_balance_tables`
2. `20260404_1210_paper_subaccounts_disable_auto_transfer`
3. `20260404_2000_account_balance_balance_integer`
4. `20260411_1100_transfers_paper_0001`

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations (from project root on server, in order above):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260404_1200_paper_account_balance_tables`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260404_1210_paper_subaccounts_disable_auto_transfer`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260404_2000_account_balance_balance_integer`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260411_1100_transfers_paper_0001`
- [x] Schema drift check (recommended):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Regenerate supervisor config if your deploy relies on it:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/config/generate_unified_supervisor_config.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status` shows key programs RUNNING; spot-check trading mode and account manager in UI.

---

## 2026-04-03 — Hotfix: archive `monitor_confirm_detail` for trades UNION

**Summary**
- **`union_trades_with_archives_select`** builds the UNION from **`users.trades_0001`** column names. Migration **`20260409_1310_trades_monitor_confirm_detail`** added the column on master (and simulated) but not on **`archive.trades_archive_*_0001`**, causing PostgreSQL errors when listing trades.

**DB migrations (required on production)**
1. `20260403_2330_archive_trades_monitor_confirm_detail`

**Production checklist**
- [x] Confirm codebase (pull): `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migration: `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260403_2330_archive_trades_monitor_confirm_detail`
- [x] Verify: `curl -sSf http://localhost:3000/health`; tail `logs/main_app.err.log` — no repeating `monitor_confirm_detail` / UNION errors.

---

## 2026-04-03 — Strike yes/no probs, trades ats_updated, AES/ATS strike-driven pool loop

**Summary**
- **Strike tables:** Add **yes_prob_hourly** / **no_prob_hourly** / **yes_prob_15m** / **no_prob_15m** (literal lookup legs). **`strike_table_generator`** (and shared insert paths) populate and read them; **`MASTER_DB_SCHEMA_REFERENCE`** updated.
- **Trades:** Add **`ats_updated`** on **`users.trades_0001`** / **`users.trades_simulated_0001`** and matching archive columns; **`init_database()`** / **`database.py`** aligned.
- **Pool AES/ATS:** **`backend/core/unified_all_monitors.py`** merges active 15m + hourly monitor rows for unified supervisors; **AES** / **ATS** refactors (strike-driven binding, lifecycle / telemetry). **`kalshi_lifecycle_trade_outcome`** updates.
- **Migrations:** Ordered list below includes a **create + drop** pair for **`ats_monitoring_events`** (net no lasting table); strike + trades + archive + active_trades telemetry + **`monitor_confirm_detail`** + in-flight **`monitor_confirmed`** NULL cleanup.
- **Ops / UI:** Trade history desktop + mobile tweaks; **`install.sh`** / **`config/logrotate.conf`** / supervisor generator and health paths aligned with **user-suffixed** supervisor program names where applicable.

**Plans:** `unified-aes-ats-strike-driven-refactor` (direction; partial implementation in this batch)

**DB migrations (required on production, in timestamp order — runner skips already-applied ids)**
1. `20260402_2000_ats_monitoring_events`
2. `20260402_2100_drop_ats_monitoring_events`
3. `20260402_2300_strike_table_yes_no_prob_columns`
4. `20260402_2310_trades_ats_updated`
5. `20260402_2320_archive_trades_ats_updated`
6. `20260409_1000_active_trades_monitor_confirm_telemetry`
7. `20260409_1200_trades_monitor_confirmed_null_until_closed`
8. `20260409_1310_trades_monitor_confirm_detail`

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations (from project root on server, in order above):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260402_2000_ats_monitoring_events`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260402_2100_drop_ats_monitoring_events`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260402_2300_strike_table_yes_no_prob_columns`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260402_2310_trades_ats_updated`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260402_2320_archive_trades_ats_updated`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260409_1000_active_trades_monitor_confirm_telemetry`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260409_1200_trades_monitor_confirmed_null_until_closed`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260409_1310_trades_monitor_confirm_detail`
- [x] Schema drift check (recommended):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Regenerate supervisor config (picks pool user + ports):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/config/generate_unified_supervisor_config.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status` shows **`trade_manager_*`**, **`trade_executor_*`**, **`active_trade_supervisor_*`**, **`auto_entry_supervisor_*`**, **`main_app`** RUNNING.

---

## 2026-04-02 — ATS trade-log tick reconcile; trades monitor_confirmed default NULL

**Summary**
- **`active_trade_supervisor`:** Each monitoring tick calls **`reconcile_active_trades_with_trade_log_each_tick()`** for the bound monitor: enroll missing **`pending` / `open` / `closing`** rows from **`users.trades_*`** (`monitor = mon_<user>_<id>`), promote pool pending when the log shows open, mark pool closing when the log shows closing, remove pool rows when the canonical trade is terminal. Monitoring loop, failsafes, and startup/brute-force checks treat **`active` + `pending` + `closing`** as “tracked” so pending-only monitors keep the loop alive. Unified pool monitor discovery includes monitors that only have pending/closing rows.
- **Database:** New trades default **`monitor_confirmed`** to **NULL** until close logic sets true/false — **`init_database()`** DDL for **`users.trades_0001`** / **`users.trades_simulated_0001`** aligned; **`MASTER_DB_SCHEMA_REFERENCE`** updated.
- **Migration:** **`20260410_1000_trades_monitor_confirmed_default_null`** alters column default on live + simulated trade tables.

**DB migrations (required on production, in order)**
1. `20260410_1000_trades_monitor_confirmed_default_null`

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migration (from project root on server):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260410_1000_trades_monitor_confirmed_default_null`  
  *(Already recorded in `system.schema_migrations` on prod before this pull; runner reported already applied.)*
- [x] Schema drift check (recommended):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status` shows **`active_trade_supervisor_*`**, **`trade_manager`**, **`main_app`**, **`trade_executor`** RUNNING.

---

## 2026-04-02 — Hotfix: trade list empty after archive UNION (RealDictCursor)

**Summary**
- **`main.py`:** `GET /trades` and `GET /api/db/trades` use a default psycopg2 cursor for `union_trades_with_archives_select` (which reads `information_schema` via tuple rows). `RealDictCursor` caused a silent exception and empty `[]` / `{ "trades": [] }`.
- **`trade_manager.py`:** `GET /trades/{trade_id}` uses a default cursor for the same union; build the response dict from `cursor.description` while the cursor is still open.

**DB migrations:** None.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status` shows key programs RUNNING.

---

## 2026-04-02 — Trade archival tables + Mobile Stop Loss Price UI parity

**Summary**
- **DB:** Create `archive.trades_archive_live_0001` / `archive.trades_archive_paper_0001` tables and archive trades from `users.trades_0001` when their monitors are archived/missing (split by `paper_trade`).
- **API:** `main.py`, `read_api.py`, and `trade_manager.py` now surface archived trades via `UNION` across master + archive; `/api/monitor/archive` archives trades in the same transaction as monitor status updates; add per-trade lookup by id across master + archive.
- **Data ops:** Add `backend/util/trade_log_archivist.py` and `scripts/db/backfill_archive_trades_for_archived_monitors.py` to backfill/archive existing archived/missing-monitor trades.
- **Frontend:** Desktop + mobile dashboard and trade monitor now include the Stop Loss Price slider/bubble behavior in parity.

**Plans:** `db-prod-schema-alignment`, `monitor-activate-deactivate-and-dashboard-ui`, `frontend-mobile-parity-rule`

**DB migrations (required on production, in timestamp order — runner skips already-applied ids)**
1. `20260327_2200_archive_trades_live_paper_0001`

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations (from project root on server):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260327_2200_archive_trades_live_paper_0001`
- [x] Run archive backfill sweep (from project root on server):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/backfill_archive_trades_for_archived_monitors.py --user-number 0001`
- [x] Schema drift check (recommended):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `curl -sSf http://localhost:3000/health` and `curl -sSf http://localhost:8001/health`; `supervisorctl -c backend/supervisord.conf status` shows key programs RUNNING.

---

## 2026-04-01 — Rising Devil min ask range, AES ladder/logging, trades NOTIFY trigger

**Summary**
- **Database:** Migration adds **`min_ask_range`** (NUMERIC 18,4) to all **`users.monitor_list_*`** and **`users.strategy_list_*`** tables when missing; optional per-monitor Rising Devil threshold (NULL = unset).
- **API:** **`main.py`** and **`monitor_manager`** expose get/set for **`min_ask_range`** alongside other monitor auto-entry fields.
- **Frontend (desktop + mobile):** Rising Devil **`min_ask_range`** controls on dashboard, trade monitor, and trade history surfaces (parity across tabs).
- **AES:** Master ladder fetch includes **`yes_ask_range_15m` / `no_ask_range_15m`** so Rising Devil sees DB ranges; per-monitor Rising Devil scan/TTC/diagnostic INFO; **`STATUS CHANGE`** INFO throttled (120s, always INFO for **DISABLED**); duplicate-trade skip message at **DEBUG**; **`cleanup_old_cooldowns`** logs once per pass at **DEBUG** (fixes nested-loop spam). **`auto_entry_supervisor_test`** aligned.
- **Realtime backbone:** Migration adds **`AFTER INSERT OR UPDATE OR DELETE`** NOTIFY trigger on **`users.trades_0001`** using **`public.rec_io_db_notify()`**; **`stream_registry`** registers **`users.trades_0001`** → **`trades`** stream; **`REALTIME_BACKBONE`** doc touch.

**Plans:** Informal — Rising Devil threshold + AES observability; trades row-level NOTIFY for WS/db_changes (no single repo plan file).

**DB migrations (apply in order on production)**
1. `20260401_1500_rising_devil_min_ask_range`
2. `20260401_1600_trades_0001_rec_io_db_notify`

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations (from project root on server):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260401_1500_rising_devil_min_ask_range`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260401_1600_trades_0001_rec_io_db_notify`
- [x] Schema drift check (recommended):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `main_app` :3000 and `trade_executor` :8001 `/health`; supervisor **RUNNING**; spot-check **`auto_entry_supervisor_*`** logs for monitor-scoped Rising Devil lines; confirm trade UI still receives **`/ws/db_changes`** updates for trade rows after NOTIFY trigger.
- [x] Snapshot reference (pre-deploy): **`rec-io-prod-pre-update-2026-04-01`** (DO action **`3119838396`**; confirm **completed** in DigitalOcean when convenient).

---

## 2026-04-01 — Canonical production host (165.22.13.146) and ops documentation

**Summary**
- **`docs/PRODUCTION_HOST.md`:** Single source for production IPv4, `/opt/rec_io_server`, and `REC_PROD_SSH_HOST` / `REC_PROD_DB_HOST`.
- **Repo docs:** `AGENTS.md`, `ARCHITECTURE.md`, `README.md`, `MASTER_DB_SCHEMA_REFERENCE.md`, `PRODUCTION_SYNC_CHECKLIST.md`, `DIGITAL_OCEAN_DEPLOYMENT_GUIDE.md`, `INSTALLATION_PACKAGE_SUMMARY.md`, `PRODUCTION_DB_SCHEMA_AND_BACKFILL_MASTER.md`, changelog/audit notes — all point at the canonical host or include the current IP for copy-paste.
- **Cursor:** Skills, commands, and `01-core-operating-law` updated with **165.22.13.146** and the host doc; `prepare-update` snapshot step references `PRODUCTION_HOST.md`.
- **`db-prod-schema-alignment` plan:** Scope line for production host doc.
- **Scripts:** Paper-trade backfill module docstrings reference `PRODUCTION_HOST.md`.

**Plans:** Informal — production droplet / DNS alignment documentation (no feature plan file).

**DB migrations:** None.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] No database migrations or `MASTER_RESTART` required (documentation and agent metadata only).
- [x] Verify: `main_app` :3000 and `trade_executor` :8001 `/health`; `supervisorctl` shows expected **RUNNING** programs.

---

## 2026-04-01 — Eastern time helpers, hourly final-quarter strike asks, prod script DB hints

**Summary**
- **`backend/core/time_eastern` + `prod_target`:** Central **America/New_York** wall time (`now_est`, `today_est`, UTC ISO helpers) and **psycopg2** `options` merge to pin session **`timezone=America/New_York`**. Optional **production DB host** helpers for legacy analytics/scripts.
- **`strike_table_generator`:** Hourly **`yes_ask_*_15m` / `no_ask_*_15m` / `*_range_15m`** stay **NULL** until **`ttc_hourly <= 900`** (final 15m of the contract); **15m** tables unchanged. Title/TTC paths use **`now_est()`** instead of host-local **`datetime.now()`** / **pytz**.
- **Trading plane:** **`trade_executor`**, **`active_trade_supervisor`**, **`auto_entry_supervisor`**, **`kalshi_account_sync_ws`**, **`monitor_manager`**, **`main`**, **`cascading_failure_detector`**, **`system_monitor`**, **`trading_redis_comms`**, **`port_config`**: adopt **`time_eastern`** where staged.
- **Analytics / utilities:** Staged scripts use **`merge_psycopg2_connect_kwargs`** for consistent DB session TZ; **`installation_logger`** import path fixed to **`backend.core.time_eastern`**.
- **Frontend:** **`frontend/js/ny-timezone.js`** for NY display on trade monitor (desktop + mobile) and system tab.
- **Docs / Cursor:** **`ARCHITECTURE`**, **`MASTER_DB_SCHEMA_REFERENCE`**, install docs, DB audit notes; deploy/verify **skills** and **commands** updates.
- **Other:** Staged **`market_watchdog`**, **`trade_manager`**, backfill/compare scripts, **`MASTER_RESTART`**, etc., as in diff.

**Plans:** `.cursor/plans/db-prod-schema-alignment.md` (doc/skill alignment); hourly strike behavior per product spec (informal).

**DB migrations:** None for this release.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Schema drift check (recommended):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `main_app` :3000 and `trade_executor` :8001 health; supervisor **RUNNING**; spot-check **strike_table_generator_ws** logs for hourly/15m **strike refresh ok**; spot-check **trade_manager** after restart.
- [x] Snapshot reference (pre-deploy): **`rec-io-prod-pre-update-2026-04-01`** (DO action **`3119534122`**; confirm **completed** in DigitalOcean when convenient).

---

## 2026-04-01 — Trade resolution: market_result finalization, lifecycle hook, remove settlement polling

**Summary**
- **trade_manager:** Held-to-expiration closes use venue **`market_result`** + **`side`** for **`sell_price`** (0/1), PnL, and returns; **`finalize_expired_trade_from_market_result`** promotes **`expired` → `closed`**. Removed **`poll_settlements_for_matches`** (DB settlement polling loop). Five-minute job **`sweep_finalize_expired_trades_with_market_result`** finalizes **`expired`** rows that already have **`market_result`**. **`/api/manual_settlement_poll`** triggers that sweep. Paper expiry repairs **`symbol_close`** only; closes via the same finalizer when **`market_result`** exists. **`_finalize_closed_trade_win_loss_confirmed`** prefers venue confirmation for **`close_method = expired`** when **`market_result`** is set.
- **kalshi_lifecycle_trade_outcome** + **kalshi_event_market_fetch:** Normalize Kalshi lifecycle **`result`**; **`apply_lifecycle_market_result_for_ticker`** applies **`market_result`** to trade rows and calls **`finalize_expired_trade_from_market_result`** for **`expired`** rows after commit.
- **market_watchdog_ws:** Lifecycle subscription retention keeps tickers while rows need **`market_result`**, any **`expired`** row (until **`closed`**), or **`closed`** pending backfill.
- **Other (already staged):** Remove legacy **`kalshi_market_watchdog`**; watchdog / account-sync / auto-entry / restart script / schema ref / frontend system tab / firewall whitelist / docs touch-ups as in diff.

**Plans:** Trade resolution unification (informal; prior `.cursor/plans/unify_trade_resolution_source_dc53d53e.plan.md` if present in workspace).

**DB migrations (required on production, in timestamp order — runner skips already-applied ids)**
1. `20260331_2300_trades_kalshi_outcome_verified_at`
2. `20260401_1200_trades_rename_outcome_evaluated_column`
3. `20260402_1000_trades_outcome_checked_at_short_name`
4. `20260402_1400_trades_market_result_from_outcome_check`
5. `20260403_1000_trades_drop_outcome_checked_at`

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations in order (from project root):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260331_2300_trades_kalshi_outcome_verified_at`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260401_1200_trades_rename_outcome_evaluated_column`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260402_1000_trades_outcome_checked_at_short_name`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260402_1400_trades_market_result_from_outcome_check`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260403_1000_trades_drop_outcome_checked_at`
- [x] Schema drift check:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `main_app` :3000 and `trade_executor` :8001 respond; supervisor **RUNNING**; spot-check **`trade_manager`** and **`market_watchdog_ws`** logs after restart; confirm recent **`expired` → `closed`** trades show **`market_result`** and coherent **`sell_price`** / **`win_loss`**.
- [x] Snapshot reference (pre-deploy): **`rec-io-prod-pre-update-2026-04-01`** (DO action **`3119398569`**; confirm **completed** in DigitalOcean when convenient).

---

## 2026-03-31 — Follow-on: trade_manager graceful shutdown, Redis-only trading UI fanout, logging cleanup

**Summary**
- **trade_manager:** Cooperative shutdown during long settlement polling (`poll_settlements_for_matches`); set a shutdown event on FastAPI lifespan teardown; `APScheduler.shutdown(wait=False)` so supervisord SIGTERM is not blocked for tens of minutes; **`generate_unified_supervisor_config`** adds **`stopwaitsecs=120`** for `trade_manager` (local `backend/supervisord.conf` already aligned in repo).
- **Trading-plane UI notifications (Redis-first):** Remove HTTP fallbacks to `main_app` for ATS automated-close notify, active-trades broadcast, kalshi account sync DB-change notify, and **monitor_manager** monitor-list / total-position / statistics delivery (**`http_path=None`**). When Redis is off, paths now log drop/skip instead of posting removed routes.
- **main.py:** Remove temporary legacy route-hit counter, **`/api/internal/legacy_route_hits`**, and **`[LEGACY_ROUTE_HIT]`** logs; surface **WARNING** when Redis **`publish_preferences_event`** fails for monitor total-position updates after allocation changes.
- **auto_entry_supervisor:** Log Redis **`publish_preferences_event`** failures instead of silent **`except: pass`**.
- **Frontend:** Small trade monitor desktop + mobile cleanups (removed lines as in diff).

**Plans:** (informal) local verification and Redis transport hardening; no single plan file required for checklist traceability.

**DB migrations:** None for this release.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Confirm trading Redis is enabled for supervised services (e.g. `USE_TRADING_REDIS_COMMS=1` in prod environment / supervisord `environment=` — required for UI fanout after HTTP fallback removal).
- [x] Confirm **`trade_manager`** has adequate stop patience (e.g. **`stopwaitsecs=120`**) in production **`supervisord.conf`** if not using the latest generated template; reload supervisord if you edit the file by hand.
- [x] Restart services: `./scripts/MASTER_RESTART.sh` (from repo root on the server).
- [x] Verify: `main_app` :3000 and `trade_executor` :8001 health; supervisor **RUNNING**; spot-check **`trade_manager`** log for clean **shutdown complete** after restart; **`main_app`** subscribed to Redis **`rec_io:preferences`** / **`rec_io:db_changes`** in log; no unexpected burst of **“broadcast dropped”** if Redis is healthy.
- [x] Snapshot reference (pre-deploy): **`rec-io-prod-pre-update-2026-03-31`** (DO action submitted **`3118238581`**, verify **`completed`** in DO when convenient).

---

## 2026-03-31 — Trading Redis comms hardening + unified active-trades naming/hourly pool

**Summary**
- **Trading-plane Redis comms:** `trade_manager`, `trade_executor`, `monitor_manager`, `main.py`, `auto_entry_supervisor`, and `active_trade_supervisor` now use Redis-first communication for trigger/status/DB-change paths with controlled HTTP fallback where configured.
- **ATS/TM reliability:** Added Redis consumer/subscriber paths, idempotency guards, and throttled fallback logging to reduce noisy retries and duplicate/late notifications.
- **Unified active-trades table naming:** Standardized pooled table naming to `users.active_trades_15m_0001` and `users.active_trades_hourly_0001` (from legacy suffix-last names), with codepaths aligned across supervisors and manager services.
- **Hourly active-trades pool migration:** Added the hourly pooled active-trades table migration for user `0001`, then rename normalization migration for both 15m/hourly pool table names plus index/constraint names.
- **Docs/schema alignment:** Updated `docs/MASTER_DB_SCHEMA_REFERENCE.md`, `backend/core/config/database.py`, and Redis comms audit doc to reflect migration-backed table naming and communication topology.

**Plans:** `.cursor/plans/redis-platform-initiative.md`, `.cursor/plans/unified-15m-aes-ats-reads.md`, `.cursor/plans/unified-kalshi-ws-master-aes-ats.md`

**DB migrations (required on production, in this order — runner skips already-applied ids)**
1. `20260330_2200_active_trades_0001_hourly_pool`
2. `20260331_1115_active_trades_unified_table_naming`

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations in order (from project root):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260330_2200_active_trades_0001_hourly_pool`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260331_1115_active_trades_unified_table_naming`
- [x] Schema drift check after migrations:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services:  
  `./scripts/MASTER_RESTART.sh`
- [x] Verify health and runtime status: `main_app` :3000, `trade_executor` :8001, supervisor `RUNNING`, and no fresh post-restart critical errors in `trade_manager`, `kalshi_account_sync`, `main_app`, `market_watchdog_ws_kalshi_15m`.
- [x] Verify unified active-trades tables present and used:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py list` and spot-check table existence/row flow for `users.active_trades_15m_0001` and `users.active_trades_hourly_0001`.
- [x] Fast rollback readiness (only if errant live behavior appears): keep this snapshot id handy and execute in this order: stop trading entry points, run migration downs below, restart, then verify health before re-enabling trading.
- [x] Rollback migration commands (reverse order):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py down 20260331_1115_active_trades_unified_table_naming`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py down 20260330_2200_active_trades_0001_hourly_pool`
- [x] Snapshot reference for emergency VM restore: `rec-io-prod-pre-update-2026-03-31` (DO action `3117800227`, status `completed`).

---

## 2026-03-30 — Unified hourly Kalshi pipeline, WS rollover + tick verify, migrations, AES/ATS reads

**Summary**
- **Hourly market WS (`market_watchdog_ws.py`):** Discover-before-delete; **atomic** DELETE + REST seed in **one transaction** (no committed empty `market_kalshi_hourly` window). **Relaxed first-tick verify** for hourly (fraction + minimum count; illiquid strikes often never emit Kalshi ticker). Longer effective verify window for hourly (env `MARKET_WATCHDOG_WS_HOURLY_VERIFY_SEC`, default 240s). Optional strict mode via `MARKET_WATCHDOG_WS_HOURLY_TICK_VERIFY_STRICT=1`.
- **AES / ATS:** Unified `strike_table_hourly` + exchange/symbol filters; **15m vs hourly** “no strike ladder” log hints point at the correct `market_kalshi_*` watchdog and strike generator.
- **Pipeline health:** `live_data.strike_pipeline_health`, `backend/core/strike_pipeline_health.py`, integration with AES/trade paths where applicable.
- **DB:** Restore/migrations for unified hourly tables, column alignment with 15m shape, legacy table drops, housekeeping restore migration. See ordered ids below.
- **Other:** Kalshi normalization/watchdog/test workflow tweaks, trade monitor / database monitor / mobile parity edits, `generate_unified_supervisor_config`, cascading failure detector, runbook updates.

**Plans:** `.cursor/plans/unified-kalshi-ws-master-aes-ats.md`, `.cursor/plans/unified-15m-aes-ats-reads.md`, `.cursor/plans/db-prod-schema-alignment.md`

**DB migrations (required on production, in this order — runner skips already-applied ids)**

1. `20260327_2230_restore_accidental_housekeeping_table_drops`
2. `20260329_1500_hourly_kalshi_strike_dollars_fp` (legacy hourly BTC/ETH tables; skip safely if already superseded — runner records applied)
3. `20260329_1800_strike_tables_volume_open_interest_fp_text`
4. `20260329_1900_testing_market_kalshi_btc_websocket_dollars_fp` (`testing` schema parity)
5. `20260329_2359_unified_hourly_pipeline_health`
6. `20260330_1000_hourly_tables_match_15m_shape`
7. `20260331_1200_live_data_drop_legacy_split_and_equity_tables`
8. `20260331_1400_strike_hourly_yes_no_ask_dollars`
9. `20260331_1410_strike_hourly_momentum_percentile`
10. `20260331_1530_hourly_market_strike_align_15m`

**Production checklist**
- [x] Confirm codebase:  
  `cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations **in order** (from project root; use `venv/bin/python` or `.venv/bin/python` as on server):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260327_2230_restore_accidental_housekeeping_table_drops`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260329_1500_hourly_kalshi_strike_dollars_fp`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260329_1800_strike_tables_volume_open_interest_fp_text`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260329_1900_testing_market_kalshi_btc_websocket_dollars_fp`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260329_2359_unified_hourly_pipeline_health`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260330_1000_hourly_tables_match_15m_shape`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260331_1200_live_data_drop_legacy_split_and_equity_tables`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260331_1400_strike_hourly_yes_no_ask_dollars`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260331_1410_strike_hourly_momentum_percentile`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260331_1530_hourly_market_strike_align_15m`  
  (Runner skips ids already in `system.schema_migrations`. Also fine: `run_migration.py up` with no id applies pending in file order.)
- [x] Schema drift:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart: `./scripts/MASTER_RESTART.sh` (from repo root on the server)
- [x] Verify: `main_app` :3000 and `trade_executor` :8001 health; supervisor RUNNING for hourly/15m WS and strike generators; spot-check `live_data.market_kalshi_hourly` / `strike_table_hourly`.

---

## 2026-03-28 — Combined deploy: trade cadence, symbol expiration W/L, strike final-quarter asks, trades snapshot columns, monitor stop-loss, ATS 15m, dashboards

**Summary**
- **Trades:** `market` (hourly vs 15m); `symbol_expiration` / `win_loss_confirmed`; six strike final-window ask snapshot columns at insert (`yes_ask_min_15m` … `no_ask_range_15m`). `trade_manager` resolves cadence from `monitor_list.market` or strategy/ticker, reads `price_spread` and ask extrema from unified or per-symbol strike tables.
- **Strike tables:** Final-quarter YES/NO ask min/max/range in dollars (4 dp) on unified and legacy `live_data` strike tables; generator carry-forward; WS hourly hook where applicable.
- **Monitors / strategies:** Stop-loss price column migration where applicable.
- **Supervisors / API:** `active_trade_supervisor` 15m iteration and related logic; `strike_table_generator` / WS; `main.py` strike/API; `monitor_manager` adjustments.
- **Frontend:** Dashboard and trade monitor (desktop + mobile) for new metrics and layout.
- **One-time data:** Backfill `symbol_expiration` from price history; backfill `market` and `win_loss_confirmed` on existing rows (scripts below).
- **Planning doc:** `unified-kalshi-ws-master-aes-ats.md` updated (north-star / scalability notes).

**Plans:** `.cursor/plans/unified-15m-aes-ats-reads.md`, `.cursor/plans/unified-kalshi-ws-master-aes-ats.md`, `.cursor/plans/db-prod-schema-alignment.md`

**DB migrations (required on production, in this order — runner skips already-applied ids)**

1. `20260328_1500_trades_symbol_expiration_win_loss_confirmed`
2. `20260328_2115_strike_table_final_quarter_ask_tracking`
3. `20260329_1100_monitor_strategy_stop_loss_price`
4. `20260330_1015_trades_market_cadence`
5. `20260330_2130_strike_final_quarter_asks_numeric_4dp`
6. `20260330_2200_trades_strike_final_quarter_asks`

**Production checklist**
- [x] Confirm codebase:  
  `git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations in order:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260328_1500_trades_symbol_expiration_win_loss_confirmed`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260328_2115_strike_table_final_quarter_ask_tracking`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260329_1100_monitor_strategy_stop_loss_price`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260330_1015_trades_market_cadence`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260330_2130_strike_final_quarter_asks_numeric_4dp`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260330_2200_trades_strike_final_quarter_asks`  
  (Use **`venv/bin/python`** or **`.venv/bin/python`** per server.)
- [x] Schema drift:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] **One-time backfills (run once per environment):**  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/backfill_trades_symbol_expiration_from_history.py --dry-run` then without `--dry-run` when ready (`--force` only if overwriting `symbol_expiration` is intended).  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/backfill_trades_market_and_win_loss_confirmed.py --dry-run` then without `--dry-run`.
- [x] Restart: `./scripts/MASTER_RESTART.sh`
- [x] Verify: `main_app` :3000 and `trade_executor` :8001 health; supervisor `RUNNING` for strike generators and 15m WS stack; spot-check `users.trades_0001` for `market`, ask snapshot columns on new inserts, and strike tables for final-quarter columns; dashboard / trade monitor UI.

---

## 2026-03-30 — Trades `market` cadence column + historical backfill for `symbol_expiration` / `win_loss_confirmed`

**Summary**
- **Schema:** `users.trades_0001` and `users.trades_simulated_0001` gain **`market`** (`hourly` | `15m`) — Kalshi cadence, distinct from venue **`exchange`**. Migration `20260330_1015_trades_market_cadence` adds the column and backfills from `trade_strategy` / `ticker` where needed.
- **Inserts:** `trade_manager.insert_trade` / `insert_simulated_trade` set **`market`** from `monitor_list.market` when present, else from strategy/ticker heuristics.
- **One-time data fix:** Script **`scripts/db/backfill_trades_symbol_expiration_from_history.py`** fills **`symbol_expiration`** from **`historical_data.{symbol}_price_history`** at the contract cycle end derived from **`date`**, **`contract`**, and **`market`** (hourly = end of named hour; 15m = clock time in contract). Then sets **`win_loss_confirmed`** for **paper and live** rows when W/L is computable (same rules as `trade_manager`). Rows without a history bar (very recent dates, or symbols without a `*_price_history` table) are skipped. Use **`--dry-run`** first; **`--force`** overwrites existing **`symbol_expiration`**.

**Production checklist**

*Superseded — run the **2026-03-28 — Combined deploy** entry above once on production (same release batch; includes `20260330_1015` and related steps).*

---

## 2026-03-27 — 15m rollover contract, fixed-point market columns, strike_table dollars-only, trade monitor hygiene

**Summary**
- **15m quarter-hour rollover (`market_watchdog_ws`):** At each quarter boundary, delete **all** rows in `live_data.market_kalshi_15m`, reset WebSocket subscriptions, poll REST for the new event per symbol, then seed and subscribe only when a symbol has ticker metadata, **explicit `floor_strike`**, and non-empty `yes_ask_dollars` / `yes_bid_dollars`. Symbols still missing metadata stay pending with warning logs until a later attempt succeeds. Reconnect path can trigger an immediate rollover if the process crosses a quarter hour while connecting.
- **Kalshi fixed-point fidelity:** `live_data.market_kalshi_15m` — `volume_fp` and `open_interest_fp` stored as **TEXT** (API-aligned fixed-point strings); legacy integer `open_interest` removed after backfill. REST and WS normalization paths updated (`market_watchdog.py`, `market_watchdog_ws.py`).
- **Strike table (`live_data.strike_table_15m`):** Add `open_interest` **NUMERIC(20,2)**; widen `volume` to **NUMERIC(20,2)**; drop legacy `yes_ask` / `no_ask` — consumers use `*_dollars` only. Generator, WS generator, `auto_entry_supervisor`, and `redis_switchboard` queries adjusted; transient “no market rows” during rollover logged at DEBUG for unified 15m.
- **Real-time UI hook:** `NOTIFY` trigger on `live_data.strike_table_15m` via `public.rec_io_db_notify()` (same pattern as other `rec_io_db_notify` triggers).
- **Trade integrity:** `trade_manager` refuses to insert a trade when the `monitor` string cannot be resolved against `users.monitor_list_0001` (prevents trades tagged to non-existent monitors).
- **15m monitor IDs:** `unified_15m_monitors` always emits `monitor_id` from the DB primary key; logs a warning if `name` implies a different numeric suffix.
- **High monitor IDs / ports:** `port_config` maps monitor numbers through `_monitor_id_port_offset` so off-range IDs (e.g. local 99xxx hygiene) do not break port assignment.
- **HTTP API / dashboards:** `main.py` — 15m `/api/postgresql/strike_table/{symbol}` reads unified `strike_table_15m` (`exchange='kalshi'`); optional `raw=1` returns numeric fields as strings for full DB precision; `/api/strike_tables/{symbol}` hourly vs 15m column layout fixed so `trade_monitor.html` regains hourly strike rows and live price. New tab `frontend/tabs/database_monitor.html` (generalized live DB observer via `/ws/db_changes`; configure `SYMBOLS` / `WATCH_DATABASES` in-page).
- **Dev-only (optional):** `scripts/db/dev_only_monitor_list_seq_start_99000.sql` advances `monitor_list_0001` sequence for local ID bands — **do not run on production.**

**Hard rollback note (droplet snapshot / VM restore):** Disk restore does not automatically reconcile `system.schema_migrations` with the restored data files. After any restore, run `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py list` (or query `system.schema_migrations`) and apply **only** migration IDs that are missing before restarting services, so code and DDL stay matched.

**DB migrations (required on production, in this order — skip any id already applied)**

1. `20260326_2000_strike_table_15m_db_notify`
2. `20260327_2005_market_kalshi_15m_fp_text_columns`
3. `20260327_2030_strike_table_15m_open_interest_and_dollars_only`

**Production checklist**
- [x] Confirm codebase:  
  `git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations in order (from project root; safe to re-run `up` — runner skips applied ids):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260326_2000_strike_table_15m_db_notify`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260327_2005_market_kalshi_15m_fp_text_columns`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260327_2030_strike_table_15m_open_interest_and_dollars_only`  
  **Note (2026-03-27 deploy):** If the server had never applied the **2026-03-26 WS prerequisite** batch, bare `run_migration.py up` can fail (lexicographic order runs `20260326_1215` before `20260328_1000`). Apply **dependency order** first: `20260328_1000` → `20260328_1200` → `20260328_1300` → `20260326_1215` → `20260326_1245` → `20260326_1335` → `20260326_1600`, then the three ids above (see **2026-03-26** entry).
- [x] Schema drift (local or prod DB matching this checkout):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/check_db_schema_drift.py`
- [x] Restart services:  
  `./scripts/MASTER_RESTART.sh`
- [x] Verify: `main_app` :3000 and `trade_executor` :8001 health; supervisor `RUNNING` for `market_watchdog_ws_kalshi_15m`, `strike_table_generator_ws_15m`, and hourly watchdogs as needed; `live_data.market_kalshi_15m` and `live_data.strike_table_15m` show fresh timestamps and current `event_ticker` after a quarter hour; `trade_monitor.html` hourly and 15m strike + spot price; optional `/tabs/database_monitor.html` confirms live WS-driven refresh.
- [x] Fidelity: `git rev-parse HEAD` on prod matches expected deploy commit; migration ids above present in `system.schema_migrations`.

**Follow-ups (future; trigger from logs if needed — not required for this deploy)**

- **Subscribe instrumentation:** In `market_watchdog_ws.py`, debug log immediately before WebSocket subscribe `send`: ticker count, sample tickers, subscription generation.
- **REST 429 handling:** In `market_watchdog.py`, detect HTTP 429 on Kalshi REST (including `fetch_event_json` and 15m event-ticker list calls), honor `Retry-After`, backoff.
- **Discovery loop caps:** In `market_watchdog_ws.py`, max attempts / max wait on `_resolve_one_symbol_until_ready` and `_refetch_event_until_floor_strikes` so 429 or slow API cannot spam indefinitely.
- **Tests:** Unit tests mocking `requests.get` for 429 backoff and `Retry-After` behavior.
- **Soak verification:** On dev, run WS 15m pipeline across several rollovers; confirm stable updates to `market_kalshi_15m` / `strike_table_15m` and review logs for 429 patterns.
- **Pipeline health vs thin markets:** `strike_pipeline_health_15m` sometimes flags stale market data when quoting is simply quiet (SOL/XRP). Decouple “data unhealthy” from “no price prints”: track WebSocket connectivity / last successful frame or heartbeat (and optionally symbol-specific staleness thresholds), so thin liquidity does not produce false reds.

---

## 2026-03-26 — 15m WS cutover + canonical tables cleanup (Kalshi)

**Summary**
- **15m WS ingestion:** `market_watchdog_ws.py` and `strike_table_generator_ws.py` now write to canonical `live_data.market_kalshi_15m` and `live_data.strike_table_15m` (no `_ws_15m` writes).
- **Fail-closed trading gates:** `auto_entry_supervisor.py` and `active_trade_supervisor.py` block auto entry / auto stop-close when `live_data.strike_pipeline_health_15m` is unhealthy or stale.
- **DB schema cleanup:** drop unused legacy integer quote/volume columns from `live_data.market_kalshi_15m` while preserving `ttc_hourly` and `probability_hourly` in `live_data.strike_table_15m`.
- **Frontend strictness:** `trade_monitor` computes ask prices only from `*_dollars` fields (no fallbacks to removed integer columns).
- **Ops hygiene:** monitoring health expectations cleaned up so canonical WS services are reflected correctly.

Plans: `.cursor/plans/unified-15m-aes-ats-reads.md`, `.cursor/plans/kalshi-websocket-orderbook-market-watchdog.md`

**DB migrations (required on production, in dependency order)**
1. `20260328_1000_market_kalshi_ws_15m`
2. `20260328_1200_market_kalshi_ws_15m_slim_columns`
3. `20260328_1300_market_kalshi_ws_15m_volume_fp_text`
4. `20260326_1215_strike_table_ws_15m_and_ws_notify`
5. `20260326_1245_strike_table_ws_15m_pipeline_health_columns`
6. `20260326_1335_strike_pipeline_health_15m`
7. `20260326_1600_market_kalshi_15m_drop_unused_legacy_columns`

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations in order (from project root):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260328_1000_market_kalshi_ws_15m`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260328_1200_market_kalshi_ws_15m_slim_columns`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260328_1300_market_kalshi_ws_15m_volume_fp_text`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260326_1215_strike_table_ws_15m_and_ws_notify`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260326_1245_strike_table_ws_15m_pipeline_health_columns`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260326_1335_strike_pipeline_health_15m`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260326_1600_market_kalshi_15m_drop_unused_legacy_columns`
- [x] Restart application services:  
  `./scripts/MASTER_RESTART.sh`
- [x] Verify: health endpoints (`main_app` :3000, `trade_executor` :8001), supervisor `RUNNING` including `market_watchdog_ws_kalshi_15m` and `strike_table_generator_ws_15m`; spot-check a symbol row shows fresh updates in `live_data.market_kalshi_15m` and `live_data.strike_table_15m`; confirm dashboard is not degraded.
- [x] Fidelity check: compare local vs prod `git rev-parse HEAD` and confirm the expected migration is present in `run_migration.py list`.

---

## 2026-03-25 — Unified 15m stack (AES/ATS/generator/watchdog), venue `exchange` schema, trade_manager expiry and Kalshi settlement hardening

**Summary**
- **Unified 15m data plane:** Single global 15m `auto_entry_supervisor` and `active_trade_supervisor` with explicit `monitor_id` routing; fixed ports via `port_config`; reads from unified `live_data.market_kalshi_15m` and `live_data.strike_table_15m` filtered by symbol and venue. New helpers (`unified_15m_monitors.py`, `exchange_ids.py`), dedicated `market_watchdog_kalshi_15m` and `strike_table_generator_15m`, `generate_unified_supervisor_config` and `MASTER_RESTART.sh` wiring.
- **Schema / naming:** Migrations add and evolve unified 15m Kalshi/strike tables; broker→exchange (venue) renames where applicable; per-monitor `active_trades` pool columns for 15m and monitoring price precision; `database.py` and `MASTER_DB_SCHEMA_REFERENCE.md` aligned.
- **trade_manager:** Settlement polling dedupes tickers so duplicate `expired` rows cannot stall the job to timeout; clearer `[15-MIN CHECK]` / expiry sweep logging.
- **active_trade_supervisor (15m):** Kalshi ticker settlement time parsing (15m end vs hourly hour bucket); suppresses auto-close POST after settlement plus grace; periodic flush of stale active-trade pool rows past settlement (bounded logging).
- **Ops / UI:** `system_monitor`, `cascading_failure_detector`, `system.html` live-data labels; `main.py` URL glue; `ats_enrollment_redis` dispatch-compatible with unified 15m ATS; tests updated.

Plans: `.cursor/plans/unified-15m-aes-ats-reads.md` (in progress; this deploy is the unified 15m cut). Prior related context: 2026-03-24 entry below (checklist superseded here).

**DB migrations (required on production, lexicographic order — includes any not yet applied from 2026-03-24)**

1. `20260320_2200_sol_xrp_live_price_log_watchdog_columns`
2. `20260322_1200_strike_15m_sol_xrp_numeric_precision`
3. `20260323_1400_live_symbol_status_sync_sol_xrp`
4. `20260324_1000_trades_symbol_spot_numeric_precision`
5. `20260324_1210_market_kalshi_15m_unified`
6. `20260325_1000_market_kalshi_15m_broker_column`
7. `20260325_1500_strike_table_15m_unified`
8. `20260325_1600_strike_table_15m_drop_exchange_display`
9. `20260326_1000_venue_exchange_column_names`
10. `20260326_1800_active_trades_0001_15m_pool`
11. `20260327_1015_active_trades_ensure_exchange`
12. `20260327_1020_active_trades_monitoring_price_precision`

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations in order (from project root — skip any id already in `system.schema_migrations` if `run_migration.py` reports it applied):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260320_2200_sol_xrp_live_price_log_watchdog_columns`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260322_1200_strike_15m_sol_xrp_numeric_precision`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260323_1400_live_symbol_status_sync_sol_xrp`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260324_1000_trades_symbol_spot_numeric_precision`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260324_1210_market_kalshi_15m_unified`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260325_1000_market_kalshi_15m_broker_column`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260325_1500_strike_table_15m_unified`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260325_1600_strike_table_15m_drop_exchange_display`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260326_1000_venue_exchange_column_names`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260326_1800_active_trades_0001_15m_pool`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260327_1015_active_trades_ensure_exchange`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260327_1020_active_trades_monitoring_price_precision`  
  *(Production also applied prior pending `20260312_1500_kalshi_market_volume_fp` via `run_migration.py up` sweep.)*
- [x] Restart application services:  
  `./scripts/MASTER_RESTART.sh`
- [x] Verify: health (`main_app` :3000, `trade_executor` :8001), supervisor `RUNNING` including `auto_entry_supervisor_15m`, `active_trade_supervisor_15m`, `market_watchdog_kalshi_15m`, `strike_table_generator_15m`; spot-check `trade_manager` for `[15-MIN CHECK]` and ATS for enrollment; optional log grep `[STALE FLUSH]` after settlement windows.

---

## 2026-03-24 — Trade manager ↔ ATS Redis enrollment, monitor_manager hardening, SOL/XRP DB precision and watchdogs

**Summary**
- **ATS open-trade handoff:** `trade_manager` publishes open events to Redis (`rec_io:ats_enroll_request`) and waits for an ACK key; `active_trade_supervisor` subscribes per monitor, runs the same enrollment core as HTTP, and stores the result for the waiter. HTTP notify remains fallback. New module `backend/core/ats_enrollment_redis.py`; `docs/REALTIME_BACKBONE.md` updated.
- **monitor_manager:** Safer unpacking of cycle statistics rows when reconciling monitor stats from trades; avoids 500s on malformed/short result sets; optional partial error reporting in responses.
- **SOL/XRP / precision / feeds:** Migrations extend live price log watchdog columns, tighten 15m strike table numeric precision, add `live_symbol_status` sync for SOL/XRP, and widen trades symbol/spot numeric precision; aligned `database.py` / schema reference. Watchdogs (`kalshi_market_watchdog`, `symbol_price_watchdog`), `strike_table_generator`, and `system_monitor` adjustments as staged.
- **trade_manager / AES:** Resilience and logging around notifications and entry context; `auto_entry_supervisor` clearer strike-table-missing logs (table name) and spike cooldown wording.
- **Frontend:** Trade monitor / trade history desktop + mobile small alignment with ongoing MTB work (`globals.js`, tab HTML).
- **Tooling / docs:** `generate_unified_supervisor_config`, `port_config`; analytics probability lookup / daily update touches; backtest simulator/helper and `docs/BACKTESTING.md`.

Plans: `redis-platform-initiative.md` (ATS enrollment slice), operational hardening adjacent to prior `monitor_manager` / feed plans.

**DB migrations (required on production, in lexicographic order)**

1. `20260320_2200_sol_xrp_live_price_log_watchdog_columns`
2. `20260322_1200_strike_15m_sol_xrp_numeric_precision`
3. `20260323_1400_live_symbol_status_sync_sol_xrp`
4. `20260324_1000_trades_symbol_spot_numeric_precision`

**Production checklist**
- [x] Superseded — use **2026-03-25** entry for pull, migrations (full ordered list), restart, and verify. Do not run this shorter checklist in isolation if production is tracking `main` at this batch.

---

## 2026-03-22 — Backtesting stack, auto-entry HTC gates, testing Kalshi 1m candle tables, migration hygiene rules

**Summary**
- **Backtesting / analytics:** Expanded backtest tooling (`core_backtester.py`, market simulator, price estimator, Kalshi candle helpers, risk/HTC replay helpers), updated `docs/BACKTESTING.md` / `docs/backtests/README.md`, and added `docs/BACKTEST_PRICE_ESTIMATOR.md`.
- **Auto-entry:** `auto_entry_supervisor` updates plus new `backend/util/auto_entry_htc_gates.py` for HTC-style gating behavior.
- **Dashboard:** Desktop and mobile dashboard HTML updates aligned with ongoing MTB / backtest UX work.
- **Testing schema (PostgreSQL):** Reversible migrations add/iterate `testing` candlestick 1m tables for specific Kalshi tickers (see ordered list below). Optional one-off populate scripts under `scripts/testing/`.
- **Agent governance:** `AGENTS.md` and `.cursor/rules/05-db-migration-hygiene.mdc` — batch DDL, one migration id per logical change, delete unapplied superseded pairs; `scripts/migrations/README.md` and Builder skill cross-links.

Plans: `candlestick-charting-frontend` (partial / experimental tables), `paper-trade-fee-estimates` (context), prior backtest initiative commit on branch.

**DB migrations (required on production, in lexicographic / dependency order)**

1. `20260321_2200_testing_candlesticks_1m_kxbtcd_26mar2116`
2. `20260321_2300_testing_candlesticks_1m_timestamp_est`
3. `20260322_1000_testing_candlesticks_1m_drop_payload_timestamp_first`
4. `20260322_1400_testing_candlesticks_1m_kxbtcd_26jan1320`
5. `20260322_1420_testing_candlesticks_1m_kxbtc15m_26mar191745_45`

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations in order (from project root):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260321_2200_testing_candlesticks_1m_kxbtcd_26mar2116`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260321_2300_testing_candlesticks_1m_timestamp_est`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260322_1000_testing_candlesticks_1m_drop_payload_timestamp_first`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260322_1400_testing_candlesticks_1m_kxbtcd_26jan1320`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260322_1420_testing_candlesticks_1m_kxbtc15m_26mar191745_45`
- [x] Restart application services:  
  `./scripts/MASTER_RESTART.sh`
- [x] Verify: health (`main_app` :3000, `trade_executor` :8001), supervisor `RUNNING`; optional — confirm `testing` candlestick tables exist if using backfill scripts.

---

## 2026-03-21 — Regime monitor: rolling sum uses `ret_pct`

**Summary**
- **Metric alignment:** `monitor_manager` regime evaluation now rolls up **`SUM(ret_pct)`** (and requires `ret_pct IS NOT NULL`) instead of `SUM(ret_pct_base)`, matching dashboard monitor tiles and trade-history return semantics.
- **Logging:** `REGIME_SWITCH` / `REGIME_COOLDOWN` payload field renamed from `window_ret_base` to `window_ret_pct`.

**Production checklist**
- [x] Pull latest on production and restart **`monitor_manager`** (or full `./scripts/MASTER_RESTART.sh`).

---

## 2026-03-20 — Multi-initiative sync: help center, regime reconcile, SOL/XRP feed, tooling/docs baseline

**Summary**
- Added a data-driven Help Center experience (`frontend/tabs/help.html` + `frontend/data/help_center_index.json`) and linked supporting docs so in-app help can be browsed and searched without hardcoded placeholder content.
- Added immediate regime reconciliation hooks between `main_app` and `monitor_manager` after auto-entry settings updates, including a dedicated reconcile API for single-monitor and full-sweep mode checks.
- Extended symbol/feed and analytics support to include SOL/XRP paths in watchdog + analytics tooling and added the related DB migration pair for SOL/XRP live tables.
- Consolidated command/skill/rules/plans documentation and removed deprecated `.cursor/pm` path references across active workflow docs.
- Added diagnostics/testing/ops scaffolding (snapshot helper, diagnostics scripts, migration docs, workflow docs) needed for ongoing production maintenance and investigations.

Plans: `logging-audit`, `db-prod-schema-alignment`, `monitor-script-lifecycle-investigation`, `monitor-activate-deactivate-and-dashboard-ui`, `frontend-mobile-parity-rule`, `live-price-feed-hygiene`, `housekeeping-backlog`.

**DB migrations (required on production, in order)**
1. `20260316_1500_trade_logs_widen_varchar`
2. `20260316_1700_redis_basic_test_add_columns`
3. `20260320_2100_sol_xrp_live_tables`

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations in order (from project root):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260316_1500_trade_logs_widen_varchar`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260316_1700_redis_basic_test_add_columns`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260320_2100_sol_xrp_live_tables`
- [x] Restart services after migrations/code sync:  
  `./scripts/MASTER_RESTART.sh`
- [x] Verify:
  - health endpoints (`main_app` :3000, `trade_executor` :8001)
  - supervisor status is RUNNING for core services
  - Help Center renders from `/data/help_center_index.json` on desktop/mobile
  - regime reconcile endpoint responds and monitor mode refreshes after settings save
  - SOL/XRP price feed paths and related tables are present/healthy

---

## 2026-03-20 — Regime monitor auto-switch (LIVE/PAPER) + dashboard parity

**Summary**
- **Per-monitor regime controls:** Added `regime_monitor_enabled` and `regime_window` (`30d`, `7d`, `1d`, `12h`) to monitor settings so each monitor can independently enable/disable rolling performance-based mode switching.
- **Auto-switch behavior:** `monitor_manager` evaluates rolling `SUM(ret_pct)` on trade close events (same basis as dashboard tile / trade-history return sums) and, when regime monitoring is enabled, switches `paper_trade` automatically (`< 0` => PAPER, `>= 0` => LIVE) with cooldown guardrails and frontend refresh notifications.
- **API + UI wiring:** Exposed regime settings via monitor/settings endpoints; desktop and mobile auto-trade modals now support regime toggle/window, disable manual LIVE/PAPER toggle while active, and include clearer labels/tooltip behavior.
- **DB + schema alignment:** Added reversible migration `20260320_2000_regime_monitor_columns` and aligned `backend/core/config/database.py` + `docs/MASTER_DB_SCHEMA_REFERENCE.md`.
- **Dashboard history stability fix:** Included `read_api` history-query updates from parallel UI remediation work (`updated_at` ordering/time filtering adjustments).

Plans: `regime-monitor_4935aaf6.plan.md` (implemented), plus `read_api` UI stability follow-up from parallel agent work.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply DB migration for regime monitor columns (from project root):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260320_2000_regime_monitor_columns`
- [x] Restart application services so `main_app`, `monitor_manager`, and dashboard assets load the new behavior:  
  `./scripts/MASTER_RESTART.sh`
- [x] Verify:
  - health endpoints (`main_app` :3000, `trade_executor` :8001) and supervisor `RUNNING`
  - monitor settings modal (desktop + mobile) shows regime controls with `30 Days / 7 Days / 1 Day / 12 Hours`
  - when regime toggle is OFF, regime window dropdown is disabled/greyed out
  - when regime toggle is ON and rolling `SUM(ret_pct)` is negative, monitor flips to PAPER and manual LIVE/PAPER toggle is disabled with tooltip text
  - `read_api` portfolio/bankroll history charts load correctly across 1d/1w/1m/1y/all periods

---

## 2026-03-19 — Momentum Contain (AES): minimum-width, centered bracket strike selection

**Summary**
- **Strike selection:** `check_auto_entry_conditions_momentum_contain()` now builds the YES/NO bracket from available strikes using a minimum width of **0.35%** of spot, then picks the **smallest actual width not below** that minimum, with **price as close to the bracket midpoint as possible** (strict `YES < price < NO`). Applies uniformly across symbols (BTC/ETH) based on the live strike table.

**Docs:** `docs/MOMENTUM_CONTAIN_SYMBOL_SILO_TEMPORARY.md`

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `git fetch && git checkout main && git pull --ff-only origin main`
- [x] Restart application services so auto-entry supervisors load the new logic:  
  `./scripts/MASTER_RESTART.sh`
- [x] Verify: health (`main_app` :3000, `trade_executor` :8001), supervisor `RUNNING` for `auto_entry_supervisor_*`. Optional: tail AES logs for `[AUTO ENTRY MOMENTUM CONTAIN] 🎯` (min width, selected strikes, midpoint, center offset).

---

## 2026-03-18 — Real-time backbone Phase 1a: read_api + dashboard bankroll panel

**Summary**
- **Dashboard (Bankroll / Portfolio / PnL top panel):** Implemented Redis-backed real-time data backbone for the panel as a proof of concept: PostgreSQL `users.account_balance_0001` NOTIFY events are routed through `redis_switchboard` and the dashboard WebSocket (`/ws/db_changes`), while the panel’s data is served by the new `read_api` service (`/api/portfolio/history`, `/api/bankroll/history`, `/api/pnl/history`, `/api/performance/realized`). `main.py` now acts as a thin HTTP proxy for these endpoints.
- **Services & system UI:** Added `redis_switchboard` and `read_api` as supervisor-managed core services and exposed them in the desktop/mobile system status UI; desktop and mobile dashboard assets were updated in lockstep to use the same event-driven refresh pattern.
- **monitor_manager cap semantics:** `monitor_manager` bulk notification now applies `current_max_pct_exposure` capping only when `performance_based_allocation` is enabled for the monitor.

Plans: `redis-platform-initiative` (Phase 1a complete), `mtb-account-dashboard` (dashboard/MTB context), `monitor-activate-deactivate-and-dashboard-ui` (monitor lifecycle context).

**DB migrations (required on production, in order)**
- **Prerequisite:** `testing.redis_basic_test` is created/aligned by `init_database()` in `backend/core/config/database.py` (no separate `run_migration` slug for table create). If production DB predates that table, run once from project root:  
  `PYTHONPATH=$(pwd) venv/bin/python -c "from backend.core.config.database import init_database; init_database()"`
- `20260316_1600_redis_basic_test_notify_trigger` — create NOTIFY trigger for `testing.redis_basic_test` so the Redis switchboard can push DB changes.
- `20260316_1800_rec_io_db_notify_public` — create `public.rec_io_db_notify()` and repoint `testing.redis_basic_test` trigger to the public function.
- `20260317_1400_account_balance_db_notify` — add NOTIFY trigger on `users.account_balance_0001` so `account_balance` stream refreshes the dashboard panel.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations in order (from project root):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260316_1600_redis_basic_test_notify_trigger`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260316_1800_rec_io_db_notify_public`  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260317_1400_account_balance_db_notify`
- [x] Restart application services so `redis_switchboard` and `read_api` load the new code (standard restart):  
  `scripts/MASTER_RESTART.sh`
- [x] Verify: health (main_app :3000, trade_executor :8001), supervisor status includes `redis_switchboard` and `read_api`. Spot-check dashboard: Bankroll/Portfolio/PnL top panel updates after changing the latest `users.account_balance_0001` row (event-driven, no interval polling).

---

## 2026-03-18 — Live price feed hygiene: Postgres trigger sync to `live_symbol_status`

**Summary**
- **Watchdog CPU hygiene:** Updated `backend/symbol_price_watchdog.py` so BTC/ETH no longer dual-write derived fields into `live_data.live_symbol_status`.
- **DB responsibility:** Added reversible Postgres triggers that keep `live_data.live_symbol_status` synchronized from the newest rows in `live_data.live_price_log_1s_btc` / `live_data.live_price_log_1s_eth`.
- **Safety model:** Added a deterministic uniqueness guarantee for `live_data.live_symbol_status(symbol)` so the trigger upsert can reliably use `ON CONFLICT (symbol)`.

**DB migrations (required on production, in order)**
1. `20260318_1300_live_symbol_status_sync_from_live_price_logs` — add trigger sync functions + triggers on `live_price_log_1s_btc` / `live_price_log_1s_eth`, plus the initial `live_symbol_status(symbol)` uniqueness guarantee.
2. `20260318_1310_live_symbol_status_unique_on_symbol_non_partial` — replace the partial uniqueness index with a full-table uniqueness index compatible with `ON CONFLICT (symbol)`.
3. `20260318_1405_live_symbol_status_db_notify_trigger` — add `AFTER INSERT OR UPDATE OR DELETE` NOTIFY trigger on `live_data.live_symbol_status` so Redis websocket signals `db_change` updates for the standalone live UI.

**Production checklist**
- [x] Confirm codebase changes (pull latest on production):  
  `git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations in order (from project root):
  - `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260318_1300_live_symbol_status_sync_from_live_price_logs`
  - `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260318_1310_live_symbol_status_unique_on_symbol_non_partial`
- [x] Apply DB notify trigger migration (required for websocket signals):
  - `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260318_1405_live_symbol_status_db_notify_trigger`
- [x] Restart watchdog services so they no longer write `live_symbol_status` directly:  
  `supervisorctl -c backend/supervisord.conf restart symbol_price_watchdog_btc symbol_price_watchdog_eth`  
  (plus full `./scripts/MASTER_RESTART.sh` in the same deploy window)
- [x] Verify:
  - Update/observe a row in `live_data.live_price_log_1s_btc` and confirm `live_data.live_symbol_status` for `symbol='BTC'` changes within the same tick.
  - Same check for `symbol='ETH'`.
- [x] Verify standalone UI: open `/tabs/live_symbol_status_test.html` and confirm values refresh on `live_symbol_status` db_change events (UI asset may need to be deployed separately if not yet on prod).

---

## 2026-03-17 — Trade ROI %, monitor total_position refresher (temp), housekeeping

**Summary**

- **Trade ROI %:** Added `roi_pct` column to `users.trades_0001` and `users.trades_simulated_0001` (schema + reversible migration). `trade_manager` now computes per-trade return on investment net of fees as `(pnl / (buy_price × position)) × 100` when closing trades and writes it on update; helper also back-computes ROI when possible. A one-time backfill in the migration populates `roi_pct` for existing closed trades where `pnl`, `buy_price`, and `position` are available.
- **Monitor total_position refresher (temporary safety net):** `monitor_manager` now starts a lightweight 30-second background loop on startup that calls `recalculate_monitor_total_positions()` to recompute `total_position` for active monitors from current monitor settings. This is explicitly a temporary guardrail to correct drift until the Redis-backed position sizing refactor replaces the legacy path.
- **Docs and housekeeping:** `docs/MASTER_DB_SCHEMA_REFERENCE.md` updated for the new `roi_pct` column and clarified monitor semantics; minor PM/backtest/docs cleanup (retiring a few legacy PM/backtest docs) aligned with existing housekeeping work.

Plans: `monitor-activate-deactivate-and-dashboard-ui` (context for monitor lifecycle/total_position notes). Redis refactor follow-ups live in `redis-platform-initiative` (no Redis code shipped in this batch).

**DB migrations (required on production, in order)**

- `20260317_add_roi_pct_to_trades` — add `roi_pct` to `users.trades_0001` and `users.trades_simulated_0001` and backfill for existing closed trades.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production):  
  `git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations in order (from project root):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260317_add_roi_pct_to_trades`
- [x] Restart application services so `trade_manager` and `monitor_manager` load the new code (standard restart):  
  `scripts/MASTER_RESTART.sh`
- [x] Verify: health (main_app :3000, trade_executor :8001), supervisor status. Spot-check: new closed trades have `roi_pct` populated and reasonable; `total_position` on monitor tiles in dashboard reflects updated monitor settings after edits and restarts.

---

## 2026-03-15 — Monitor activate/deactivate sync, dashboard MTB and Ret % base, status-light UX

**Summary**

- **Monitor activate/deactivate:** main_app now runs in-process sync (generate_unified_supervisor_config + supervisorctl reread/update) after both deactivate and activate so AES/ATS tear down or spin up even if monitor_manager is unreachable. Doc clarification: `status` = script lifecycle; `auto_trade` / `auto_trade_status` = auto-trading only (monitor_manager, generate script, MASTER_DB_SCHEMA_REFERENCE).
- **Dashboard (Bankroll view):** Bankroll chart and value use `mtb_base_value` (fallback to `bankroll_current`) from `/api/bankroll/history`. Performance panel Ret % boxes show sum of `ret_pct_base` when Bankroll tab is active, and `ret_pct` when Portfolio or PNL is active; `/api/performance/realized` now returns `ret_pct_base` per period. Desktop and mobile.
- **Dashboard (monitor tile):** On status-light click, tile and light update immediately (optimistic) and the light is non-clickable until the request completes; revert on failure. Desktop and mobile.

Plans: `monitor-activate-deactivate-and-dashboard-ui` (done). MTB dashboard work (Bankroll chart + Performance ret_pct_base) aligns with `mtb-account-dashboard` scope. No DB migrations.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production):  
  `git fetch && git checkout main && git pull --ff-only origin main`
- [x] Restart application services so main_app serves updated frontend and backend:  
  `scripts/MASTER_RESTART.sh`
- [x] Verify: health (main_app :3000, trade_executor :8001), supervisor status. Spot-check dashboard: Bankroll tab chart/value and Performance Ret % in Bankroll vs Portfolio view; monitor status-light toggles tile immediately.

---

## 2026-03-14 — Dashboard portfolio chart animation, sync bankroll drawdown threshold

**Summary**

- **Dashboard (desktop):** Portfolio chart now has `animation: false` so the 30s refresh does not visibly re-animate the line (matches mobile). Fixes chart "redrawing" every 30s on production when the tab is focused.
- **kalshi_account_sync_ws:** Bankroll ratchet drawdown threshold is now pegged to `mtb_base_value` (70% of base) when set, instead of 70% of previous bankroll; docstring and logic updated.

No DB migrations. Frontend and backend code only.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production):  
  `git fetch && git checkout main && git pull --ff-only origin main`
- [x] Restart application services so main_app serves updated frontend and kalshi_account_sync loads new code:  
  `scripts/MASTER_RESTART.sh`
- [x] Verify: health (main_app :3000, trade_executor :8001), supervisor status. Spot-check dashboard: portfolio chart does not visibly redraw every 30s.

---

## 2026-03-14 — MTB snapshot and ret_pct_base on trades, insufficient-resting-volume log

**Summary**

- **trade_executor:** Rejection log line now includes intent (open/close). Standalone JSONL log `logs/insufficient_resting_volume_rejections.jsonl` records each fill_or_kill_insufficient_resting_volume rejection with monitor, contract, position size, ticker, etc.; rotates monthly to `..._YYYY-MM.jsonl`. Rationale: track liquidity ceilings as bankroll scales.
- **trade_manager:** On insert, reads latest `master_trading_bankroll` and `mtb_base_value` from `users.account_balance_0001` and stores them on the trade row. On close, computes `ret_pct_base` (same formula as ret_pct but using mtb_base_value); one-time backfill copies ret_pct into ret_pct_base for existing rows.
- **DB migrations (required on production, in order):** (1) `20260314_1200_trades_mtb_snapshot_columns` — add master_trading_bankroll, mtb_base_value to trades_0001 and trades_simulated_0001. (2) `20260314_1210_trades_ret_pct_base` — add ret_pct_base. (3) `20260314_1220_backfill_ret_pct_base_from_ret_pct` — backfill ret_pct_base = ret_pct for existing closed trades.
- **Schema:** MASTER_DB_SCHEMA_REFERENCE.md and database.py CREATE TABLEs updated.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production):  
  `git fetch && git checkout main && git pull --ff-only origin main`
- [x] Apply migrations in order (from project root):  
  `PYTHONPATH=$(pwd) python3 scripts/db/run_migration.py up 20260314_1200_trades_mtb_snapshot_columns`  
  `PYTHONPATH=$(pwd) python3 scripts/db/run_migration.py up 20260314_1210_trades_ret_pct_base`  
  `PYTHONPATH=$(pwd) python3 scripts/db/run_migration.py up 20260314_1220_backfill_ret_pct_base_from_ret_pct`
- [x] Restart application services so trade_manager and trade_executor load the new code:  
  `scripts/MASTER_RESTART.sh`
- [x] Verify: health (main_app :3000, trade_executor :8001), supervisor status.

---

## 2026-03-14 — Script crash fixes, critical-asset logging, push-and-update command

**Summary**

- **system_monitor:** Self-restart no longer kills the process; when system_monitor is in the failed list it launches a detached child to run `supervisorctl restart system_monitor` after a short delay, then exits so supervisor can respawn a new instance.
- **active_trade_supervisor:** Failsafe skips when DB is unreachable (`get_db_connection()` returns None) instead of crashing and restart-looping.
- **Critical-asset logging:** Supervisord log moved to `logs/supervisord.log` with rotation (50MB × 10 backups) in generator and local conf; system_monitor and cascading_failure_detector get higher retention (20MB/10MB × 10). Policy doc: `docs/CRITICAL_ASSET_LOGGING.md`.
- **Push-commits-and-update-production:** New command and skill (prepare-update → commit & push with suggested message → apply-update-from-local). AGENTS.md updated.
- **Frontend:** system-loader.js uses AbortController for fetch timeouts so health checks cannot hang indefinitely.

No DB migrations. Prod will use new supervisord log path and retention after config is regenerated (or on next deploy with existing generated config).

**Production checklist**

- [x] Confirm codebase changes (pull latest on production):  
  `git fetch && git checkout main && git pull --ff-only origin main`
- [x] Regenerate supervisor config on prod so supervisord uses `logs/supervisord.log` with rotation (optional; run from project root):  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/config/generate_unified_supervisor_config.py`
- [x] Restart application services so system_monitor and active_trade_supervisor load the new code:  
  `scripts/MASTER_RESTART.sh` (or equivalent supervisorctl restarts).
- [x] Verify: health (main_app :3000, trade_executor :8001), supervisor status. Confirm system_monitor and all ATS processes RUNNING.

---

## 2026-03-13 — Paper trade fee estimates, PnL/ret backfill, and monitor/AES tweaks

**Summary**

- **Paper trade fee estimates:** Trade manager now computes and stores estimated taker fees for paper trades using Kalshi’s formula `round_up(0.07 × position × P × (1 − P))` at open and (when closed before expiration) at close. Open path sets `fees` at open; close path adds close fee to existing open fee; expiration path uses open fee only. PnL and ret_pct use these fees.
- **Backfills (already run on production):** `scripts/db/backfill_paper_trade_fees.py` and `scripts/db/backfill_paper_trade_pnl_ret.py` were run once on prod to backfill `fees` and then `pnl` / `ret_pct` / `win_loss` (and cycle_* for affected cycles) for all paper trades. No need to re-run on apply unless re-backfilling a fresh DB.
- **Trade history UI:** Desktop and mobile trade history tables style paper-trade rows with italic; no new columns.
- **Auto-entry and monitors:** Auto_entry_supervisor runs a 30s loop calling `periodic_status_sync()` so `auto_trade_status` stays in sync. On monitor deactivate, main_app sets `auto_trade_status = 'off'` and triggers `sync_monitor_processes` so AES/ATS tear down promptly. Monitor_manager `create_monitor` returns 207 and a clear message when spawn fails.
- **AGENTS.md:** Command names updated to `/system-restart-local` and `/system-restart-production`.

Plans: `paper-trade-fee-estimates` (done). No DB migrations; schema unchanged.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production):  
  `git fetch && git checkout main && git pull --ff-only origin main`
- [x] Restart application services so trade_manager, main_app, monitor_manager, and auto_entry_supervisor load the new code:  
  `scripts/MASTER_RESTART.sh` (or equivalent supervisorctl restarts).
- [x] Verify: health (main_app :3000, trade_executor :8001), supervisor status. Spot-check trade history: paper trades show italic and fee values where applicable.

---

## 2026-03-12 — Active trade supervisor fix (confirm_open_trade post fixed-point)

**Summary**

- **Bug:** After the fixed-point migration, `confirm_open_trade()` in trade_manager still referenced `taker_fill_cost_cents`, which was removed from `users.orders_0001`. When `_parse_dollars(taker_fill_cost_dollars)` returned None, the code raised NameError and confirm_open_trade crashed. Trades never moved to `status = 'open'`, so active_trade_supervisor never received the "open" notification and never tracked them (monitor_confirmed = FALSE).
- **Fix:** Removed the legacy fallback; when total cost from orders is missing, we keep the existing `buy_price` from `users.trades_0001` so the trade is still confirmed and ATS is notified.
- **Docs:** Added `docs/AUDIT_ACTIVE_TRADE_SUPERVISOR_TRADE_MANAGER.md` (pipeline, failure modes, fixed-point impact, duplicate-entry explanation).

No DB migrations. Code change in `backend/trade_manager.py` only.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production):  
  `git fetch && git checkout main && git pull --ff-only origin main`
- [x] Restart trade_manager so the fix is loaded:  
  `supervisorctl -c backend/supervisord.conf restart trade_manager`  
  (Optional: restart active_trade_supervisor processes if you want them to pick up any related state; the fix is in trade_manager.)
- [x] Verify: health (main_app :3000, trade_executor :8001), supervisor status. After deploy, new opens should be tracked; monitor_confirmed = FALSE counts may drop over the next days (run `scripts/diagnostics/check_monitor_confirmed_failures.py --days 7` to spot-check).

---

## 2026-03-12 — Fixed-point migration completion and MTB (DB migrations required)

**Summary**

- **DB migrations (required on production in order):** This update completes the Kalshi fixed-point migration and adds MTB tracking. All four migrations below must be applied on the target server **before** restarting services. No code that reads legacy integer/cents columns remains; the DB schema must match.
- **account_balance_0001:** Add `master_trading_bankroll` and `mtb_base_value` (migration `20260312_2000_account_balance_mtb_columns`). Sync writes these on balance updates.
- **orders_0001:** Add fee/cost dollar columns, then drop legacy integer columns (migrations `20260312_2015_orders_fee_dollars_columns`, `20260312_2045_orders_drop_legacy_int_columns`). Orders use only `*_dollars` and `*_fp` fields.
- **fills_0001, positions_0001, settlements_0001:** Drop legacy integer/cents columns (migration `20260312_2115_fp_drop_legacy_ints_fills_positions_settlements`). Live sync and historical ingest write only `_fp` and `*_dollars`.
- **Code:** `trade_manager` (open/close and PnL), `kalshi_account_sync_ws` (orders/fills/positions/settlements sync and balance), and `kalshi_historical_ingest` (write_orders_to_db, write_fills_to_db, write_positions_to_db, write_settlements_to_db) use only the new columns. Order INSERT placeholder count fixed so baseline order sync no longer errors.

Plans: `db-prod-schema-alignment` (in progress). Schema ref: `docs/MASTER_DB_SCHEMA_REFERENCE.md`.

**Production checklist**

- [x] Confirm codebase changes on production (pull latest `main`):  
  `git fetch && git checkout main && git pull --ff-only origin main`
- [x] **DB migration 1 — account_balance MTB columns.** From project root on the target server:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260312_2000_account_balance_mtb_columns`
- [x] **DB migration 2 — orders fee/cost dollar columns.** From project root:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260312_2015_orders_fee_dollars_columns`
- [x] **DB migration 3 — drop legacy integer columns from orders_0001.** From project root:  
  `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260312_2045_orders_drop_legacy_int_columns`
- [x] **DB migration 4 — drop legacy columns from fills, positions, settlements (direct SQL, one-time).** From psql or an equivalent SQL console on the production database, run once:

  ```sql
  -- Fills: keep count_fp and dollar prices only
  ALTER TABLE users.fills_0001
      DROP COLUMN IF EXISTS count;

  -- Positions: keep *_fp and *_dollars; legacy numeric columns are no longer read
  ALTER TABLE users.positions_0001
      DROP COLUMN IF EXISTS total_traded,
      DROP COLUMN IF EXISTS position,
      DROP COLUMN IF EXISTS market_exposure,
      DROP COLUMN IF EXISTS realized_pnl,
      DROP COLUMN IF EXISTS fees_paid;

  -- Settlements: keep *_fp and *_total_cost_dollars; legacy int counts are no longer read
  ALTER TABLE users.settlements_0001
      DROP COLUMN IF EXISTS yes_count,
      DROP COLUMN IF EXISTS no_count;
  ```

  Then confirm via `\d users.fills_0001`, `\d users.positions_0001`, and `\d users.settlements_0001` that these columns are gone.
- [x] Run `scripts/MASTER_RESTART.sh` so kalshi_account_sync, trade_manager, and dependent services load the new code.
- [x] Verify: health (main_app :3000, trade_executor :8001), supervisor status, and `logs/kalshi_account_sync.out.log` shows no "Failed to insert order" errors on baseline sync.

---

## 2026-03-12 — PM/update pipeline and trade history filters

**Summary**

- **PM / update flow:** Wired `/prepare-update` to treat `.cursor/plans/*.md` as the canonical record of work done, and to always create a fresh changelog entry with an open Production checklist that references the relevant plans for each batch. Updated the updater rules so changelog entries explicitly list associated plans and include a standard “Confirm codebase changes (pull latest on production)” task.
- **Backlog cleanup:** Retired legacy PM/brain docs under `.cursor/brain` in favor of plans, and clarified that active task tracking lives solely in `.cursor/plans/`.
- **Account history filters:** Stabilized the Strategy dropdown options on desktop and mobile trade history so they are cleaned, deduplicated, and ordered with core strategies first and the rest sorted alphabetically, driven by `/api/strategies`.
- **Mobile UX:** Improved mobile trade history dropdown labels so when multiple values are selected the buttons read “Multiple Strategies / Symbols / Contracts / Days / Monitors,” making each control self-explanatory without external labels.
- **Frontend parity convention:** Documented a mobile-parity convention in `AGENTS.md` so future frontend changes consider whether a corresponding change is needed on mobile.

Plans: `logging-audit`, `db-prod-schema-alignment`, `account-history-strategy-filters`, `frontend-mobile-parity-rule`

**Production checklist**

- [x] Confirm codebase changes on production (pull latest `main`):  
  `git fetch && git checkout main && git pull --ff-only origin main`
- [x] Verify: health (main_app :3000, trade_executor :8001), and spot-check desktop and mobile trade history Strategy dropdowns for the cleaned, deterministic ordering and updated “Multiple …” labels.

---

## 2026-03-12 — Kalshi market volume_fp alignment

**Summary**

- Rename Kalshi market volume columns on all live market tables from `volume` / `volume_24h` to `volume_fp` / `volume_24h_fp` to match the Kalshi API’s fixed-point fields.
- Update `kalshi_market_watchdog` to write `volume_fp` and `volume_24h_fp` as integer counts derived from the API’s fixed-point strings (e.g. `"56658.00"` → `56658`), with safe fallbacks.
- Keep strike table schemas unchanged; `strike_table_generator` now reads `volume_fp` / `volume_24h_fp` from `market_kalshi_*` and continues to store them in the existing `volume` column on the strike tables.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] Update DB schema on production Kalshi market tables: rename `live_data.market_kalshi_hourly_{btc,eth,ndx,spx}` and `live_data.market_kalshi_15m_{btc,eth}` columns from `volume` → `volume_fp` and `volume_24h` → `volume_24h_fp` using direct DDL (one-time ALTER TABLE per table).
- [x] Run `scripts/MASTER_RESTART.sh` so all Kalshi watchdogs, strike generators, and dependent services load the new code.
- [x] Verify production: health (main_app :3000, trade_executor :8001), supervisor status, and that Kalshi market tables on prod now have `volume_fp` / `volume_24h_fp` columns and are being populated with non-zero values.

---

## 2026-03-11 — Drawdown safety valve and monitor list frontend sync

**Summary**

- **Drawdown safety valve:** When account sync detects a significant drawdown (Master Trading Bankroll ≤ 70% of previous bankroll), it steps down `bankroll_current` and notifies monitor_manager with `bankroll_stepped_down: true`. Monitor_manager then sets all monitors' `auto_trade` to FALSE and `auto_trade_status` to `'off'` so auto entry is halted until the user manually re-enables per monitor.
- **Sync path:** `kalshi_account_sync_ws` sets `bankroll_stepped_down` only in the ratchet step-down branch and passes it in the POST body to `/api/bankroll_updated`. Monitor_manager reads the flag and runs the bulk UPDATE on `users.monitor_list_0001` before recalculating allotments.
- **Frontend notify on every monitor_list change:** Monitor_manager now calls `_notify_frontend_monitor_list_updated()` whenever it changes the monitor list (bankroll update, position variables update, statistics update, create monitor, toggle auto_trade, sync_monitor_processes). The main app broadcasts `monitor_list_updated` so the dashboard runs `loadMonitors()` and refreshes tiles.
- **Dashboard (tabs + mobile) failsafe:** The AUTO TRADE toggle on monitor tiles is updated in the same 30s refresh loop as other tile stats. `updateMonitorStatValues` now syncs the `.auto-trade-toggle` element's `active` class from the API data (`autoTrade` / `auto_trade`), so if a WebSocket update is missed, the next poll corrects the toggle.

No DB schema changes. Backend (kalshi_account_sync_ws, monitor_manager) and frontend (dashboard.html, dashboard_mobile.html) only.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] No DB migrations. Run `scripts/MASTER_RESTART.sh` so kalshi_account_sync and monitor_manager load the new code.
- [x] Verify: health (main_app :3000, trade_executor :8001), supervisor status. Optionally simulate a drawdown (or wait for one) and confirm dashboard toggles show auto_trade off and refresh when expected.

---

## 2026-03-12 — Kalshi API: fills and settlements _dollars (schema)

**Summary**

- **Fills:** Kalshi API now exposes `yes_price_dollars` and `no_price_dollars`; legacy `yes_price_fixed` / `no_price_fixed` and cent fields deprecated. We removed deprecated columns and added `yes_price_dollars`, `no_price_dollars` to `users.fills_0001`. Sync and ingest read from API _dollars (fallback to _fixed during rollout). Frontend uses the new column names.
- **Settlements:** API exposes `yes_total_cost_dollars` and `no_total_cost_dollars`. We removed `yes_total_cost`, `no_total_cost` and added `yes_total_cost_dollars`, `no_total_cost_dollars` to `users.settlements_0001`. Sync and ingest read _dollars (fallback to cent fields).
- **Schema:** Direct DDL only (no migration files). Reference: `docs/MASTER_DB_SCHEMA_REFERENCE.md`. CREATE TABLEs updated in trade_manager.py, kalshi_account_sync_ws.py, kalshi_historical_ingest.py.

**DB schema change required.** This update requires running DDL on the database. The apply-update process runs the DB step below automatically on the target server as part of the production checklist. Do not skip it; there is no separate manual migration step.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] **DB schema update (required; run automatically as part of this update):** From project root on the target server, run the DDL below. Apply-update executes this step; do not run migrations manually on other servers. Command (idempotent; safe if schema already updated):

  ```bash
  PYTHONPATH=$(pwd) venv/bin/python -c "
  from backend.core.config.database import get_postgresql_connection
  conn = get_postgresql_connection()
  cur = conn.cursor()
  # fills_0001: add new columns
  cur.execute('ALTER TABLE users.fills_0001 ADD COLUMN IF NOT EXISTS yes_price_dollars TEXT')
  cur.execute('ALTER TABLE users.fills_0001 ADD COLUMN IF NOT EXISTS no_price_dollars TEXT')
  cur.execute(\"SELECT 1 FROM information_schema.columns WHERE table_schema='users' AND table_name='fills_0001' AND column_name='yes_price_fixed'\")
  if cur.fetchone():
      cur.execute(\"UPDATE users.fills_0001 SET yes_price_dollars = yes_price_fixed, no_price_dollars = no_price_fixed WHERE yes_price_fixed IS NOT NULL OR no_price_fixed IS NOT NULL\")
      for col in ('yes_price_fixed', 'no_price_fixed', 'yes_price', 'no_price'):
          cur.execute(\"ALTER TABLE users.fills_0001 DROP COLUMN IF EXISTS \" + col)
  # settlements_0001: add new columns
  cur.execute('ALTER TABLE users.settlements_0001 ADD COLUMN IF NOT EXISTS yes_total_cost_dollars NUMERIC(10,2)')
  cur.execute('ALTER TABLE users.settlements_0001 ADD COLUMN IF NOT EXISTS no_total_cost_dollars NUMERIC(10,2)')
  cur.execute(\"SELECT 1 FROM information_schema.columns WHERE table_schema='users' AND table_name='settlements_0001' AND column_name='yes_total_cost'\")
  if cur.fetchone():
      cur.execute(\"UPDATE users.settlements_0001 SET yes_total_cost_dollars = yes_total_cost, no_total_cost_dollars = no_total_cost WHERE yes_total_cost IS NOT NULL OR no_total_cost IS NOT NULL\")
      cur.execute('ALTER TABLE users.settlements_0001 DROP COLUMN IF EXISTS yes_total_cost')
      cur.execute('ALTER TABLE users.settlements_0001 DROP COLUMN IF EXISTS no_total_cost')
  conn.commit()
  conn.close()
  print('DB schema update done')
  "
  ```

  Then verify schema: `users.fills_0001` has `yes_price_dollars`, `no_price_dollars` and no `yes_price_fixed`, `no_price_fixed`, `yes_price`, `no_price`; `users.settlements_0001` has `yes_total_cost_dollars`, `no_total_cost_dollars` and no `yes_total_cost`, `no_total_cost`.

- [x] Run `scripts/MASTER_RESTART.sh` so kalshi_account_sync and any dependent services load the new code.
- [x] Verify: health (main_app :3000, trade_executor :8001), supervisor status; optionally trigger a fills/settlements sync and confirm no errors in kalshi_account_sync logs.

---

## 2026-03-11 — Dashboard Performance panel and mobile dashboard tweaks

**Summary**

- **Performance panel (desktop + mobile):** Removed the delta/compare column (previous-period change) from the Performance panel; rows now show only label, PnL, and PnL %. Applied a 20px left shift via `transform: translateX(-20px)` on `.performance-periods` so the block is better centered in the panel.
- **Mobile dashboard:** Chart animation disabled so periodic refreshes do not re-animate the line; pull-to-refresh now triggers a full page reload; WebSocket reconnect no longer gated by `DASHBOARD_MOBILE_PAUSED`.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] No DB or backend service changes. Frontend only; no restart required. Optional: hard refresh or clear cache on clients to pick up updated dashboard HTML/CSS.

---

## 2026-03-10 — Trade history mobile: disable contract filter (parity with desktop)

**Summary**

- **Issue:** Mobile trade history showed a subset of trades for the same filter parameters as desktop; e.g. trade 10625 appeared on desktop but not on mobile.
- **Cause:** Desktop has contract filtering disabled in `applyFilters()` (commented out); mobile was still applying `filterTradesByContract()`, which only keeps trades whose contract string matches hourly labels (12am–11pm) and excluded others.
- **Fix:** Disabled contract filter in mobile `applyFilters()` in `frontend/mobile/trade_history_mobile.html` so mobile shows all contracts like desktop. Same effective filters on both: date, win/loss, strategy, symbol, monitor, day, paper/live.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] No DB or backend changes. Frontend only; no restart required. Optional: hard refresh or clear cache on mobile client to pick up updated `trade_history_mobile.html`.

---

## 2026-03-10 — Simulated trade duplicate prevention (AES + trade_manager)

**Summary**

- **Root cause:** AES `is_strike_already_simulated_traded()` only checked open/pending and (monitor, ticker, side). After the 15m expiration job closed a simulated trade, the next scan did not see it and inserted again for the same cycle. trade_manager had no server-side duplicate guard.
- **Fix:** (1) AES: duplicate check now requires date, contract, and strike in strike_data and queries for **any** row (no status filter) with (monitor, date, contract, strike, side). Caller `check_simulated_15m_entry_hourly_htc` passes date_str and contract_name (same as trigger_simulated_trade). (2) trade_manager `insert_simulated_trade`: before INSERT, SELECT for existing (monitor, date, contract, strike, side); if found, return that id and skip insert.
- **No schema or migrations.** See `docs/AUDIT_SIMULATED_TRADE_DUPLICATES.md` for full audit.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] No DB migrations. Run `scripts/MASTER_RESTART.sh` so all auto_entry_supervisor and trade_manager processes load the new logic.
- [x] Verify: health (main_app :3000, trade_executor :8001), supervisor status. Optionally after a few 15m cycles, run duplicate detection on prod (e.g. inline query or script) to confirm no new duplicate groups in `users.trades_simulated_0001`.

---

## 2026-03-10 — Trade history filters and preferences (dynamic Strategy/Symbol, All/None, migrations)

**Summary**

- **Trade history (desktop + mobile):** Strategy and Symbol dropdowns are populated from the database (`strategy_list`, `symbols_list`). Contract, Monitor, and Day dropdowns use **All | None** links instead of a single "Select All" checkbox. Reset sets Strategy to only strategies with `default=TRUE` in `strategy_list`; Symbol and other dropdowns reset to all selected. Preferences persist per-strategy and per-symbol selection via JSONB.
- **Backend:** `/api/strategies` returns `strategies` and `default_strategy_names`. `get_trade_history_preferences` and `save_trade_history_preferences` read/write `strategy_selection` and `symbol_selection` (JSONB); fallbacks when columns are missing for backward compatibility.
- **Migrations:** Three reversible migrations: `20260310_1200_trade_history_preferences_strategy_selection` (strategy_selection JSONB), `20260310_1210_trade_history_preferences_symbol_selection` (symbol_selection JSONB), `20260310_1220_strategy_list_default_column` (`"default"` boolean on strategy_list_0001). Apply in order from project root with `PYTHONPATH=. venv/bin/python scripts/db/run_migration.py up <slug>`.
- **PM:** One-time migration/backfill script cleanup tracking documented in `docs/LOGGING_INVENTORY.md` and INDEX (HOUSEKEEPING_SCRIPTS_INVENTORY + MASTER_CHANGELOG).

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] Apply migrations if not already applied: `20260310_1200_trade_history_preferences_strategy_selection`, `20260310_1210_trade_history_preferences_symbol_selection`, `20260310_1220_strategy_list_default_column` (from project root with `PYTHONPATH=. venv/bin/python scripts/db/run_migration.py up <slug>` for each, or run all pending via your usual process). **Prod schema verified 2026-03-11: strategy_selection and symbol_selection exist on trade_history_preferences_0001; default exists on strategy_list_0001.**
- [x] Run `scripts/MASTER_RESTART.sh` so frontend and main_app load the new code.
- [x] Verify: health (main_app :3000, trade_executor :8001), supervisor status; optional: open Trade History and confirm Strategy/Symbol dropdowns load and Reset sets Strategy to defaults only.

---

## 2026-03-10 — Ghost monitor guard and MASTER_RESTART startup order

**Summary**

- **Ghost monitor guard:** `auto_entry_supervisor` and `active_trade_supervisor` now exit immediately if their monitor row is missing from `users.monitor_list_*` or has no symbol. This prevents deleted monitors from continuing to run and send trades. On startup, `get_monitor_symbol()` and (in AES) `is_auto_trade_enabled()` treat missing/invalid monitor as fatal and call `os._exit(0)` after logging.
- **kalshi_account_sync startup:** Before running the initial baseline sync, `kalshi_account_sync_ws` now waits until `trade_manager` is reachable on its port (TCP connect, up to 30s). Notify to `trade_manager` (`/api/positions_updated`) uses a shared helper with 3 retries and backoff so transient connection refused is not logged as ERROR.
- **MASTER_RESTART:** New Step 5b: after starting supervisor, the script waits until core ports 3000, 4000, and 8001 are listening (up to 30s) before proceeding to restart all services, so `trade_manager` is up before dependent services run their first sync.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] No DB schema changes or migrations.
- [x] Run `scripts/MASTER_RESTART.sh` so all processes load the new code; ghost monitors (if any) will self-exit on next start.
- [x] Verify: health (main_app :3000, trade_executor :8001), supervisor status, and that no "Error notifying trade_manager" appears in `kalshi_account_sync.out.log` for the current process start.

---

## 2026-03-10 — Logging housekeeping (prod logs directory)

**Summary**

- **Prod logs cleanup:** Bring the production `logs/` directory back to a manageable, recent window of history by archiving/compressing rotated supervisor logs, pruning excess rotations beyond a small fixed count, and purging old logs for services that are no longer supervised.
- **Scope:** This is purely a logging/housekeeping change: it does not alter any service behavior, DB schema, or business logic. It only moves or deletes historical log files according to the rules encoded in the diagnostics scripts.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] From project root on prod (`/opt/rec_io_server`), archive or remove existing rotated logs so that only the current `.out.log`/`.err.log` files remain for each active service.
- [x] Prune older numeric rotations for active services so there are no stale `.out.log.N` / `.err.log.N` segments left in `logs/`.
- [x] Purge stale logs for services no longer managed by supervisor (including legacy SPX/NDX watchers and their strike/price logs) so only active BTC/ETH services remain.
- [x] Spot-check `logs/` on prod: confirm that each active service still has its current `.out.log` and `.err.log`, that historical clutter (e.g. daily_update* cron logs) has been removed, and that no errors occurred while cleaning the directory.

---

## 2026-03-08 — OpSec remediation (DB password, auth, CORS, bcrypt)

**Summary**

- **OpSec audit fixes:** Production now requires `DB_PASSWORD` or `REC_DB_PASS` when `REC_ENVIRONMENT=production` (no default). All backend and scripts use `get_database_config()` / `get_postgresql_connection()`. Auth: `local_dev_` bypass only when not production; bcrypt required for new password hashes; change_password uses centralized config. CORS: in production, explicit origins only (no `"*"`). Password prints removed from setup_auth/install (archive). bcrypt added to requirements.txt.
- **Production server agent:** Before or immediately after pull, ensure the production server has **DB_PASSWORD** or **REC_DB_PASS** set in the environment (e.g. in `.env` or in the env that feeds supervisor). If not set, app and config generation will fail until set. See **.cursor/OPSEC_AUDIT_AND_UPGRADE.md** section "Production server: OpSec update (2026-03-08)" for full instructions.

**Production checklist**

- [x] **Before or right after pull:** Confirm production has `DB_PASSWORD` or `REC_DB_PASS` set (e.g. in `.env` or wherever supervisor gets its env). If `REC_ENVIRONMENT=production` and neither is set, `get_database_config()` will raise and services will not start. If unsure, run: `cd project_root && source .env 2>/dev/null; echo "DB_PASSWORD set: $(if [ -n \"$DB_PASSWORD\" ] || [ -n \"$REC_DB_PASS\" ]; then echo yes; else echo NO; fi)"`.
- [x] Confirm codebase changes (pull latest on production).
- [x] Install Python deps so **bcrypt** is present: from project root run `venv/bin/pip install -r requirements.txt` (or your usual deploy install). Required for change-password; existing logins unaffected.
- [x] Run `scripts/MASTER_RESTART.sh` (blocking, with permissions to stop supervisor and free ports). Config generation uses `get_database_config()` and will fail if production env has no DB password.
- [x] Run verify workflow (health, supervisor status, logs, status block per VERIFY_COMMAND.md). If any service fails to start with a DB or config error, ensure `DB_PASSWORD` or `REC_DB_PASS` is set and restart again.

---

## 2026-03-08 — DigitalOcean integration and prepare-update prod snapshot

**Summary**

- **@digitalocean agent:** Rule and AGENTS.md entry; authority on DO API, snapshots, backups, droplets. MCP **digitalocean-droplets** (remote) in mcp.json with token; tool **snapshot-droplet** for autonomous snapshot create.
- **Prepare-update:** Step 1 added: create prod snapshot **rec-io-prod-pre-update-YYYY-MM-DD** (droplet 513735057) before verify/audit/changelog so the update is revertable.
- **/apply-update:** Slash command and APPLY_UPDATE_COMMAND.md for production to run open MASTER_CHANGELOG checklists and calibrate server.
- **Scripts/docs:** scripts/do/snapshot_prod.sh, docs/DEPLOYMENT_GUIDE.md, DO_AGENT_SNAPSHOT_FIX.md, sandbox.json (optional .env read). .env.example and master .env include DIGITALOCEAN_API_TOKEN.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] No DB schema changes or migrations; no restart required.
- [x] Optional: On prod, if using Cursor/agents, add digitalocean-droplets MCP to mcp.json for snapshot/backup; token in env/headers.

---

## 2026-03-08 — PM and agent housekeeping (Cursor commands, brain, skills, archive)

**Summary**

- **Cursor / PM:** Slash commands and PM docs moved or added under `.cursor/`: commands (`verify`, `log-chat`, `system-restart`, `prepare-update`), PM brain (from `docs/pm_brain/` to `.cursor/plans/`), new brain docs (INDEX, config/env, proposed tasks, context retention, chat summary log), PM command docs (VERIFY, LOG_CHAT, SYSTEM_RESTART, PREPARE_UPDATE, ORG_CHART, DB_REVERSIBLE_MIGRATIONS), and rules (db, kalshi, pm). Skills added for verify, log-chat, system-restart, prepare-update.
- **CI:** `.github/workflows/db-schema-drift.yml` added (runs schema drift check on push/PR to main and master).
- **Archive:** `docs/pm_brain/` content moved to `.cursor/plans/`; many legacy docs and corrupted `MASTER_PORT_MANIFEST.json` snapshots moved to `archive/2026-03-housekeeping/` (docs and backend/core/config corrupt copies). `AGENTS.md` and `.gitignore` updated for new paths and ignores.
- **No application or DB changes:** No backend code, schema, or migrations in this commit. Production behavior unchanged.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] No DB schema changes or migrations; no restart required for this release.
- [x] Optional: If using Cursor/agents on this repo, ensure local `.cursor` config (e.g. MCP paths) is set for your machine; `mcp.json` and credentials remain gitignored.

---

## Entry format

Each entry below uses:

- **Date** – When the update is intended for production (YYYY-MM-DD).
- **Summary** – What the release contains.
- **Production checklist** – A list of tasks with checkboxes (`- [ ]`). Whoever runs the update (from local via /apply-update-from-local or on prod via /apply-update) checks these off as each is completed. Every entry has at least a minimal checklist (e.g. "Confirm codebase changes", "Update local database" if applicable). Details or commands for a task can appear under the checklist or inline in the task text.

---

## 2026-03-07 — Kalshi fixed-point migration (March 12 2026 cutoff)

**Summary**

- **Kalshi API:** Legacy integer count fields and integer cents price fields are removed by Kalshi on **March 12, 2026**. All integration code now prefers `_fp` (e.g. `count_fp`) and `_dollars` (e.g. `yes_bid_dollars`) and derives legacy values when API omits them.
- **trade_executor.py:** Already sent only `count_fp` and `yes_price_dollars` / `no_price_dollars`; no changes. No legacy `count` or `yes_price`/`no_price` in order payload.
- **kalshi_account_sync_ws.py:** Added `_prefer_fp_or_legacy()` and `_prefer_dollars_or_legacy_cents()`. Positions, fills, orders, and settlements now prefer `*_fp` and `*_dollars` from API responses; legacy counts/prices derived when missing. Settlements support `yes_total_cost_dollars` / `no_total_cost_dollars` / `revenue_dollars` when present.
- **kalshi_market_watchdog.py:** Market data: prefer `yes_bid_dollars` etc.; derive `yes_bid`/`no_bid`/… (cents) from `_dollars` when legacy cents not returned. Module-level helper `_market_cents_from_dollars()`.
- **live_orderbook_snapshot.py:** Orderbook delta messages: accept `price_dollars` or `price` (cents); normalize to cents for internal orderbook.
- **kalshi_market_ticker_websocket.py:** Orderbook delta: accept `price_dollars` and `delta_fp`; snapshot levels normalized from price_dollars/size_fp to cents/int for existing logic.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] No DB schema changes required; existing `_fp` and `_dollars` columns already used.
- [x] Restart services that talk to Kalshi: `trade_executor`, `kalshi_account_sync`, `kalshi_market_watchdog` (and any hourly/15m watchdog instances), plus `main_app` if it proxies Kalshi. Full restart: `scripts/MASTER_RESTART.sh` or equivalent.
- [x] After March 12 2026: confirm orders, fills, positions, and market data continue to sync and display; no reliance on deprecated integer/cents fields.

---

## 2026-03-07 — Kalshi account history: /deposits and /withdrawals only

**Summary**

- **Endpoints:** Account history sync no longer uses the legacy `account/history` endpoint (404). It uses only `GET /v1/users/{user_id}/deposits` and `GET /v1/users/{user_id}/withdrawals`. Legacy fetcher and converter removed from `kalshi_account_sync_ws.py`.
- **Schema:** `users.account_history_0001` has new columns `kalshi_id`, `vendor`, `rail` (reversible migration `20260307_1600_account_history_vendor_rail_kalshi_id`). Upsert uses `kalshi_id` when present; backfill updates existing rows with NULLs by matching API data (UTC-normalized time + amount).
- **Transfers:** `users.transfers_0001` From/To and status are derived from account_history (vendor/rail/deposit_type). `_refresh_transfer_from_to_from_account_history` keeps them in sync after backfill or sync.
- **Backfill:** Sync runs `_backfill_account_history_vendor_rail` after each upsert so existing rows get `kalshi_id`/vendor/rail when the API delivers them. One-off script `scripts/db/backfill_account_history_vendor_rail.py` can be run manually to backfill existing rows (e.g. after first deploy): `PYTHONPATH=. python3 scripts/db/backfill_account_history_vendor_rail.py`.
- **Rail:** Only withdrawals have `rail` in the API; deposits correctly have `rail` NULL.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] Apply migration if not already applied: `python3 scripts/db/run_migration.py up 20260307_1600_account_history_vendor_rail_kalshi_id` (from project root with PYTHONPATH set). If already applied, `run_migration.py list` will show it.
- [x] Optional one-time backfill for existing account_history rows with NULL kalshi_id/vendor/rail: `PYTHONPATH=. python3 scripts/db/backfill_account_history_vendor_rail.py`. Run once; sync will backfill on its own thereafter.
- [x] Restart `kalshi_account_sync` (or full restart: `scripts/MASTER_RESTART.sh`) so sync uses new code.
- [x] Confirm: Account manager transfers table shows From/To and Status; account_history rows have vendor/rail populated where API provides them.

---

## 2026-03-07 — Fix known bugs (get_port, main.py DB)

**Summary**

- **auto_entry_supervisor.py:** `get_port("main")` → `get_port("main_app")` at the `update_monitor_position` call so the correct port is used.
- **main.py:** `get_trade_history_preferences_postgresql()` now uses `get_postgresql_connection()` from `backend.core.config.database` instead of hardcoded localhost/rec_io_user/rec_io_password. Aligns with server-agnostic config.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] Restart `auto_entry_supervisor` (or full restart: `scripts/MASTER_RESTART.sh`) and `main_app` so changes take effect.
- [x] Confirm: no errors in logs; monitor position updates and trade history preferences work.

---

## 2026-03-07 — Env conventions: DB_* / REC_DB_* only

**Summary**

- **Single pattern:** All DB access goes through `backend.core.config.database`: `get_postgresql_connection()` or `get_database_config()`. No POSTGRES_* or hardcoded credentials in application code.
- **database.py:** Prefers DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT; if unset, falls back to REC_DB_HOST, REC_DB_NAME, REC_DB_USER, REC_DB_PASS, REC_DB_PORT. One place for both conventions; scripts do not need to map REC_DB_* → DB_*.
- **Updated modules:** symbol_price_watchdog_finance, strike_table_generator, backend/util/cleanup_temp_schemas, symbol_data_fetch_pg, symbol_profiler, live_table_viewer, probability_lookup_generator; scripts: update_position_to_100, rollback_position_update, generate_schema_doc, audit_db_schema.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] Ensure .env or deploy sets either DB_* or REC_DB_* (database.py uses both). No code changes required if already using DB_* or REC_DB_*.
- [x] Restart any services that were changed (full restart recommended: `scripts/MASTER_RESTART.sh`) so they load the new database module behavior.
- [x] Confirm: DB-dependent scripts and services connect successfully (e.g. run a script that uses get_postgresql_connection).

---

## 2026-03-07 — DB schema drift check and reversible migrations

**Summary**

- **Drift check:** `scripts/db/check_db_schema_drift.py` compares `backend/core/config/database.py` with `docs/MASTER_DB_SCHEMA_REFERENCE.md` for critical tables (trades_0001, trades_simulated_0001, monitor_list_0001, strategy_list_0001); exits with error if definitions drift. No DB connection required.
- **CI:** `.github/workflows/db-schema-drift.yml` runs the drift check on push/PR to main and master.
- **Reversible migrations:** `scripts/db/run_migration.py` (list / up / down); migrations live in `scripts/migrations/` as `YYYYMMDD_HHMM_slug.up.sql` and `.down.sql`; applied migrations tracked in `system.schema_migrations`. See `scripts/migrations/README.md`.
- **update_db_schema_to_reference.py:** Now uses `get_postgresql_connection()` from project config (env); docstring states type/default fixes are out of scope (use reversible migrations or manual ALTERs).
- **Audit findings:** `docs/changelog/DB_MAINTENANCE_AUDIT_FINDINGS.md` documents local audit and single source of truth. **Local alignment complete:** drift check passes. Prod schema changes are part of the normal update process; @updater coordinates and verifies when pushing to production.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] No prod DDL required for this release. CI will run drift check on future push/PR.
- [x] Optional: to audit prod schema, set DB_* (or REC_DB_*) to point at prod and run `PYTHONPATH=. python3 scripts/audit_db_schema.py` from project root. Do not run migrations or ALTERs on prod without a maintenance window and backup.

---

## 2026-03-07 — Simulated trade duplicate fix, dedupe script (util), one-time DB cleanup

**Summary**

- **Simulated trade duplicate prevention:** Auto-entry supervisor and trade_manager now use the same server-agnostic DB connection (`backend.core.config.database.get_postgresql_connection`) for simulated trades. `is_strike_already_simulated_traded` in AES no longer uses a separate `POSTGRES_*` connection; it uses the shared config (DB_* / REC_DB_*) so the duplicate check sees the same rows that trade_manager writes. This prevents new duplicates. Trade_manager's local hardcoded `get_postgresql_connection` was removed in favor of the centralized one.
- **Dedupe script (one-time):** `backend/util/dedupe_simulated_trades.py` removes duplicate rows in `users.trades_simulated_0001` that accumulated before the connection fix. The script is **one-time only**; duplicate prevention is now in-app. It is documented as too aggressive (it deduped by date+contract only); if a future one-off dedupe is ever needed, use (date, contract, strike, side) and keep min(id) per group.
- **No code changes to live/paper trading;** only simulated path and shared DB usage.

**Production checklist**

- [x] Confirm codebase changes (pull latest `main` on production).
- [x] Update local database: run from project root  
  `PYTHONPATH=$(pwd) venv/bin/python -c "from backend.core.config.database import init_database; init_database()"`  
  if any schema migrations are pending.
- [x] **One-time dedupe of simulated trades table (after restart):** From project root, run once:  
  `PYTHONPATH=$(pwd) venv/bin/python -m backend.util.dedupe_simulated_trades`  
  This removes duplicate rows in `users.trades_simulated_0001` that may exist from before the connection fix. If the script reports "No duplicate rows (by date, contract) found.", no action needed. Do not run the dedupe repeatedly.
- [x] Restart application services (main_app, strike_table_generator, trade_manager, active_trade_supervisor, auto_entry_supervisor as applicable).
- [x] Confirm: no errors in logs after restart; simulated trades no longer double up on the same strike per cycle.

---

## 2026-03-05 — Simulated 15m trade system (production)

**Summary**

- **Simulated 15m trades on hourly markets:** `auto_entry_supervisor` now runs a simulated 15m entry path for all hourly monitors with `auto_trade=TRUE`, excluding Momentum Breakout/Contain (for testing). It reuses each monitor’s existing `min_time` / `max_time` window and reads `ttc_15m` / `probability_15m` from the hourly strike tables. Simulated trades ignore price/diff/volume/momentum spike rules, are always `paper_trade = TRUE` / `test_filter = FALSE`, and never call the executor or send real orders.
- **Contract + weekly_cycle per 15m window:** Simulated trades use contract labels at the *next* 15-minute boundary (e.g. `BTC 2:15pm`, `BTC 2:30pm`), so `trade_manager` can derive `hour_idx` and `weekly_cycle` with the correct decimal (.0 / .1 / .2 / .3) via the existing contract parsing logic. This ensures every simulated trade is tagged to the correct 15m window for later calibration.
- **15m expiration + symbol-close settlement (simulated):** `trade_manager`’s 15-minute expiration job now always calls `check_expired_simulated_trades()` at :00/:15/:30/:45, regardless of whether there are live trades. This function closes *only* `users.trades_simulated_0001` rows (no impact on `trades_0001`), using the latest `one_minute_avg` (or `price` fallback) from `live_data.live_price_log_1s_{symbol}` as `symbol_close` and setting `status = 'closed'`, `close_method = 'expired'`, and `win_loss` based on a YES/NO vs strike comparison. `sell_price` is recorded as `NULL` for simulated trades.
- **Simulated cycle_win_loss per 15m window:** For each 15m window (grouped by `monitor`, `date`, `weekly_cycle`) that has simulated trades closed in a given expiration run, `trade_manager` sets `cycle_win_loss` on `users.trades_simulated_0001` to `L` if **any** trade in that window is a loss, otherwise `W`. This gives a single, conservative win/loss flag per monitor per 15m cycle for downstream Strategy Health Score (SHS) work.
- **DB schema + load characteristics:** No new columns were added for this feature; it relies on the existing `users.trades_simulated_0001` schema (including `weekly_cycle NUMERIC(5,1)`, `cycle_win_loss`, `cycle_pnl`, `cycle_ret_pct`) and the `live_data.live_price_log_1s_{symbol}` tables. `insert_simulated_trade` explicitly records `diff`, `buy_price`, `position`, `fees`, `bankroll`, `price_spread`, and `sell_price` as `NULL` and touches only `users.trades_simulated_0001`. The system leverages existing CPU-intensive processes (strike generators, price logs, auto-entry loops); the new work is limited to light `SELECT` / `INSERT` / `UPDATE` statements and does not introduce new schedulers or external API calls.

**Production checklist**

- [x] Confirm codebase changes (pull latest `main` on production).
- [x] Update local database schema to latest (id sequences, PKs, numeric weekly_cycle, simulated table shape) by running from project root:
  - `PYTHONPATH=$(pwd) venv/bin/python -c "from backend.core.config/database import init_database; init_database()"`
  - This ensures `users.trades_simulated_0001` exists with a working `id` sequence / primary key and matches the definition in `docs/MASTER_DB_SCHEMA_REFERENCE.md` (including `weekly_cycle NUMERIC(5,1)`, `cycle_win_loss`, `cycle_pnl`, `cycle_ret_pct`, and boolean flags).
- [x] Restart application services in the standard order (or run `scripts/MASTER_RESTART.sh`): at minimum `main_app`, `trade_manager`, `monitor_manager` (which runs `auto_entry_supervisor` / `active_trade_supervisor`), and strike table / price watchdog services.
- [x] Verify simulated trades path:
  - Confirm `users.trades_simulated_0001` is receiving new rows for hourly monitors with `auto_trade=TRUE` (excluding Momentum Breakout / Momentum Contain), with `position`, `fees`, `bankroll`, `price_spread`, and `sell_price` recorded as `NULL`.
  - After at least one 15m boundary, confirm those simulated trades transition to `status='closed'` with `symbol_close` populated and `win_loss` correctly reflecting YES/NO vs strike.
  - For a given monitor/date/`weekly_cycle`, confirm all simulated trades share the same `cycle_win_loss` (`L` if any loss in that 15m window, otherwise `W`).
- [x] Verify no impact to live trading:
  - Confirm `users.trades_0001` behavior is unchanged (entries, expirations, cycle metrics, and pnl/ret_pct), and that real orders are still executed only from live paths.
  - Scan logs for `AUTO ENTRY`, `TRADE MANAGER`, and `SIMULATED 15m` messages to ensure there are no new errors or unexpected restarts.

---

## 2026-03-03 — Strike table alignment, simulated trades table, weekly_cycle 15m decimal

**Summary**

- **Strike tables:** Hourly and 15m strike tables now share the same column set (`ttc_hourly`, `ttc_15m`, `probability_hourly`, `probability_15m`). Legacy columns `ttc_seconds` and `probability` were removed from 15m tables; all 15m readers use `ttc_15m` and `probability_15m`. Hourly tables already used `ttc_hourly` / `probability_hourly`; no change to hourly column names. Strike table generator, main.py, active_trade_supervisor, and auto_entry_supervisor read/write the correct columns per market. See `docs/SIMULATED_15M_CYCLES_HOURLY_HTC_PLAN.md` and `docs/MASTER_DB_SCHEMA_REFERENCE.md`.
- **users.trades_simulated_0001:** New table (duplicate of `trades_0001`) for simulated 15m-cycle trades; documented in MASTER_DB_SCHEMA_REFERENCE. Any future schema changes to `trades_0001` must be applied to `trades_simulated_0001` as well.
- **weekly_cycle decimal:** `users.trades_0001.weekly_cycle` (and `trades_simulated_0001` if present) now stored with one decimal place: hourly trades = `hour.4` (e.g. 64.4 = fourth quarter of the hour); 15m trades = `hour.0 | .1 | .2 | .3` from contract minutes (:00, :15, :30, :45). Column type migrated from INTEGER to `NUMERIC(5,1)`. Cycle performance and monitor_cycle_performance still use the integer part only (`FLOOR(weekly_cycle)`); decimals are for record-keeping and future use.

**Production checklist**

- [x] Confirm codebase changes (pull latest `main` on production).
- [x] Update local database: run `PYTHONPATH=$(pwd) venv/bin/python -c "from backend.core.config.database import init_database; init_database()"` from project root. This applies: (1) drop `ttc_seconds` and `probability` from `live_data.strike_table_15m_btc` and `strike_table_15m_eth` if present; (2) alter `users.trades_0001.weekly_cycle` and `users.trades_simulated_0001.weekly_cycle` (if table exists) from integer to `NUMERIC(5,1)`.
- [x] Restart application services (main_app, strike_table_generator, trade_manager, active_trade_supervisor, auto_entry_supervisor as applicable).
- [x] Confirm: no errors in logs after restart; strike tables and trade monitor UI load correctly; new trades receive `weekly_cycle` with one decimal (e.g. 64.4 for hourly, 64.1 for 2:15pm 15m).

---

## 2025-03-04 — Kalshi fixed-point migration (count / _fp)

**Summary**

- Backend support for Kalshi’s fixed-point migration for contract counts. We now record and use `_fp` fields (e.g. `count_fp`, `remaining_count_fp`, `position_fp`) in addition to legacy integer fields across portfolio sync, trade manager, order submission, and API responses.
- **Recording:** Account sync and historical ingest write all `_fp` columns to `users.fills_0001`, `users.orders_0001`, `users.positions_0001`, `users.settlements_0001` (stored as `NUMERIC(12,2)`).
- **Reading:** Trade manager and main app prefer `_fp` when present (legacy can be NULL once the API deprecates it). Order delta check in sync uses `_fp` for comparison.
- **Outbound:** Order submission sends only `count_fp` to the Kalshi API (legacy `count` no longer sent). Internal callers (main, auto_entry, ATS, frontend) pass `count_fp` through the trade chain.
- If the API stops sending legacy count fields, operations continue unchanged; legacy columns may be NULL for new data. See `docs/FIXED_POINT_LEGACY_DEPRECATION_AUDIT.md` for details.

**Production checklist**

- [x] Confirm codebase changes (pull latest `main` on production; or merge feature branch into `main` then pull).
- [x] Update local database: ensure `_fp` columns exist on `users.fills_0001`, `users.orders_0001`, `users.positions_0001`, `users.settlements_0001` per `docs/MASTER_DB_SCHEMA_REFERENCE.md`. Add any missing as `NUMERIC(12,2)` (nullable). Columns: `fills_0001` → `count_fp`; `orders_0001` → `initial_count_fp`, `remaining_count_fp`, `fill_count_fp`; `positions_0001` → `total_traded_fp`, `position_fp`; `settlements_0001` → `yes_count_fp`, `no_count_fp`. Example: `ALTER TABLE users.fills_0001 ADD COLUMN IF NOT EXISTS count_fp NUMERIC(12,2);`
- [x] Run historical ingest once to backfill new columns from Kalshi API: `PYTHONPATH=$(pwd) venv/bin/python backend/api/kalshi-api/kalshi_historical_ingest.py` (see schema ref section "4. After updating portfolio-level user tables").
- [x] Restart application services (main_app, trade_manager, trade_executor, kalshi_account_sync, active_trade_supervisor as applicable).
- [x] Confirm: no errors in logs after restart; trading and account sync behave as expected.

---
