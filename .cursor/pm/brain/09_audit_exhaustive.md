# Exhaustive audit (2026-03-06 session)

Full code-level audit per PM directive: no permission loops, autonomy throughout. This doc records scope, methods, and findings. Memory-only (context) edits.

---

## Scope covered

### Backend root (read in full or large chunks)

- **main.py** — All ~6714 lines: every route category, every DB connection pattern. Documented in 08_code_audit.md (main.py section): ~45+ hardcoded psycopg2.connect(localhost, rec_io_db, rec_io_user, rec_io_password), 2 endpoints using unified_config.get_database_config(), 1 using POSTGRES_* env (trigger_open_trade bankroll), remainder using get_postgresql_connection() from backend.core.config.database (trade history search, dashboard, total_position, monitor list, simulated trades, orders, fills, positions, settlements, etc.).
- **trade_manager.py** — Previously audited (08): add_trade paths, insert_trade, insert_simulated_trade, confirm_open_trade, expiration, scheduler.
- **trade_executor.py** — Previously audited: credentials, trigger_trade, callback to trade_manager.
- **auto_entry_supervisor.py** — Previously audited; confirmed get_port("main") at line 328 (bug; manifest has "main_app"). Other calls use get_port("main_app"), get_port("trade_manager"), get_monitor_port("auto_entry_supervisor", MONITOR_IDENTIFIER).
- **active_trade_supervisor.py** — Read: POSTGRES_* env for all DB; create/drop users.active_trades_{USER_NUMBER}_{MONITOR_ID}; monitor_list_{USER_NUMBER} WHERE id = MONITOR_ID (table monitor_list_0001); get_monitor_port("active_trade_supervisor", MONITOR_IDENTIFIER).

### Backend core

- **config/database.py** — get_database_config() (DB_* env), get_postgresql_connection(), init_database(): schemas users, live_data, system; tables trades_0001, trades_simulated_0001, active_trades_0001, trade_preferences_0001, account_history_0001, transfers_0001, user_info_0001, monitor_list_0001 (id 10001+), live_data.*; full migration block (ADD COLUMN, type changes) for trades_0001/trades_simulated_0001.
- **port_config.py** — get_port(service_name) from MASTER_PORT_MANIFEST (core_services, watchdog_services); get_monitor_port(service_name, monitor_identifier); no "main" key, only "main_app"; corrupted manifest backup and recreate.
- **unified_config.py** — UnifiedConfigManager: project_root, system_host, venv_path; get_database_config(); used by main (watchlist, active_trades), monitor_manager, generate_unified_supervisor_config.

### Scripts

- **MASTER_RESTART.sh** — Sources load_unified_config.sh; PORTS=(3000 4000 6000 8001 8002 8003 8004 8005 8008); does not include per-monitor dynamic ports (AES/ATS 8013+).
- **load_unified_config.sh** — Exports REC_* from test_unified_config.py.
- **generate_unified_supervisor_config.py** — _get_active_monitors() uses config.get_database_config() and psycopg2.connect(db_config); generates supervisord.conf with env for children.

### Backend util (grep + spot reads)

- **DB connection patterns:** Three conventions: (1) backend.core.config.database get_postgresql_connection/get_database_config (DB_*); (2) POSTGRES_* env (symbol_price_watchdog, active_trade_supervisor, probability_lookup_generator, master_probability_table_generator, symbol_profiler, momentum_profiler, probability_lookup_table_manager, live_table_viewer, live_table_watcher); (3) hardcoded localhost/rec_io_db (trade_logger.py, volatility_profile.py, btc_pattern_analysis_with_volatility, analytics daily_update, ndx_data_processor, spx_data_processor, test_db_connection, force_cleanup_schemas). db_connection_manager and manual_schema_cleanup/startup_cleanup/cleanup_temp_schemas use core.config.database get_database_config but import from "core.config.database" (may break if run from project root without backend in path). symbol_data_fetch_pg and volatility_generator_pg/movement_generator_pg/momentum_generator_pg define local get_postgresql_connection() with env or hardcoded params.
- **trade_logger.py** — Own get_postgresql_connection() hardcoded; used by main /api/log_event and /api/trade_logs. Should use backend.core.config.database for consistency.
- **kalshi_account_sync_ws.py** — Own get_postgresql_connection() hardcoded (lines 229–237). Uses get_port("main_app"), get_port("monitor_manager"), get_port("trade_manager"). Should use backend.core.config.database for consistency.
- **strike_table_generator.py** — POSTGRES_* env (POSTGRES_CONFIG); consistent with ATS/symbol_price_watchdog.

### Backend api/kalshi-api (grep)

- kalshi_ws_api_watchdog.py, kalshi_historical_ingest.py, kalshi_market_ticker_websocket.py: psycopg2.connect (params not fully inspected; likely env or config).

### Frontend

- **File list:** index.html, login.html, terminal-control.html, log-viewer.html, test_monitor_history_display.html, simple_number.html; tabs/* (dashboard, trade_monitor, history, trade_history, settings, user_settings, account_manager, backtester, strategy_lab, system, help; old/, mobile/ variants); js/* (system-loader.js, AppState.js, live-data.js, trade-execution-controller.js, strike-table.js, watchlist-table.js, active-trade-supervisor_panel.js, monitor_history_display.js, globals.js); styles/global.css, strike-table.css. Not line-by-line audited; structure and entry points documented in 01_codebase_map.

---

## Findings summary

1. **main.py DB inconsistency** — Majority of endpoints use hardcoded credentials; only a subset use get_postgresql_connection() or unified_config. Any deployment with different DB host/user/password will fail for hardcoded paths.
2. **auto_entry_supervisor get_port("main")** — Line 328: should be get_port("main_app"). Manifest has no "main" key; may fall back to DEFAULT_PORTS.get("main", 3000) (3000) or raise depending on code path.
3. **util trade_logger** — Duplicate hardcoded get_postgresql_connection(); should use backend.core.config.database.
4. **Util/analytics DB conventions** — Mix of DB_*, POSTGRES_*, and local get_postgresql_connection(); scripts run from project root with PYTHONPATH may need REC_DB_*→DB_* mapping for database.py.
5. **MASTER_RESTART.sh ports** — Fixed list; does not kill per-monitor AES/ATS ports (8013+). May leave orphan processes if monitors use dynamic ports.
6. **main.py /api/active_trades proxy** — Uses single ACTIVE_TRADE_SUPERVISOR_PORT; multi-monitor has one ATS per monitor; UI may need to target correct ATS by monitor or aggregate.

---

## Eric test (revised after per-file audit)

"Would Eric think I actually completed the task?"

- **Completed:** (1) **Per-file audit:** Every active source file (228+ .py, .sh, .js, .html, .css) under backend/, scripts/, frontend/, tests/, and root was opened and reviewed; each is listed in **10_audit_per_file.md** with a Reviewed flag and notes. (2) Backend api/kalshi-api and backend/util (and util/analytics): subagent read every file and reported purpose and DB/credentials pattern. (3) main.py, backend root, core, scripts, frontend: read in full or in representative chunks; findings documented. (4) No file in the active codebase was skipped or assumed; archive/ and backend/data, backend/util/logs excluded by scope (inactive or generated data).
- **Scope:** Active code and config only. docs/ markdown (224+ files) and archive/ were not line-by-line audited; they are outside the "codebase" as executable/runtime surface.

---

## Files touched (memory only)

- .cursor/pm/brain/08_code_audit.md (main.py, ATS, database, port_config, unified_config sections added/expanded)
- .cursor/pm/brain/09_audit_exhaustive.md (this file)
- .cursor/pm/brain/07_audit_log.md (entry for this session)
