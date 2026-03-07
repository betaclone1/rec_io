# Audit log (read-only)

Timestamped summary of exhaustive deep audit. No project files or DB schema were modified.

---

## 2026-03-06 — Full project audit (initial)

**Scope:** Entire repo: code, docs, config, scripts; DB introspection (read-only); PM brain created and populated.

**Done**

- Created docs/pm_brain/ (INDEX, 00–07). Brain is PM-only writable; no other project files touched.
- **Repo layout:** Root: backend, frontend, scripts, docs, config, tests, archive, backup, reports, rec_webview_app. Key root files: AGENTS.md, INSTALL.md, PROJECT_STRUCTURE.md, install.sh, requirements.txt, .cursor/rules (pm, updater, changelog).
- **Backend:** 123 .py files. main.py ~76 API routes (FastAPI); trade_manager.py entry: uvicorn on get_port("trade_manager"). Core: database.py, port_config.py, config_manager.py, unified_config.py, MASTER_PORT_MANIFEST.json. Services: main, trade_manager, trade_executor, monitor_manager, auto_entry_supervisor, active_trade_supervisor, strike_table_generator, symbol_price_watchdog, kalshi_market_watchdog, kalshi_account_sync_ws, cascading_failure_detector, system_monitor.
- **DB:** Introspected schemas (users, live_data, historical_data, analytics, system, archive, core, work_progress, testing, public). Tables: users.trades_0001 (8965 rows at audit), trades_simulated_0001, monitor_list_0001, strategy_list_0001, strike_table_*, live_price_log_1s_*, etc. Connection: DB_* (or REC_DB_*→DB_* after load_dotenv). init_database() in backend/core/config/database.py is single migration source.
- **Ports:** MASTER_PORT_MANIFEST.json + port_config.get_port(). MASTER_RESTART.sh flushes 3000,4000,6000,8001–8005,8008. Supervisor: backend/supervisord.conf (generated or static); programs get DB_*, REC_DB_*, POSTGRES_* in environment.
- **Docs:** 224+ markdown files under docs/ (excluding pm_brain); changelog in docs/changelog/; MASTER_DB_SCHEMA_REFERENCE.md; VER3_ONBOARDING_DOCUMENTS; many deployment/installation/audit docs.
- **Backend files using init_database/get_postgresql_connection/get_database_config:** database.py, main.py, trade_manager.py, monitor_manager.py, auto_entry_supervisor.py, active_trade_supervisor.py, kalshi_account_sync_ws.py; config_manager, unified_config; util: dedupe_simulated_trades, trade_logger, fingerprint_*, momentum_*, cleanup_temp_schemas, db_connection_manager, etc.; util/analytics: symbol_profiler, fingerprint_*, momentum_*, movement_*, volatility_*, symbol_data_fetch_pg, verify_movement_spotcheck.

**Findings (informational only; no changes made)**

- **main.py:** get_trade_history_preferences_postgresql() uses hardcoded localhost, rec_io_db, rec_io_user, rec_io_password instead of env/config.
- **auto_entry_supervisor.py:** Line 328 uses get_port("main"); port_config has "main_app", not "main". May be bug (wrong service name).
- **Env conventions:** Three conventions (DB_*, REC_DB_*, POSTGRES_*) across codebase; scripts that use database.py should load .env and map REC_DB_*→DB_*.
- **MASTER_RESTART PORTS:** Subset of manifest; supervisor may start additional processes (strike generators, watchdogs, monitor_manager, per-monitor AES/ATS) with ports from manifest.
- **docs/changelog/TODO.md:** Open items: DB maintenance system audit, Kalshi account history (/deposits, /withdrawals), system-wide logging audit, script CPU optimization.

**Brain docs written**

- INDEX.md, 00_project_overview.md, 01_codebase_map.md, 02_services_ports.md, 03_db_schema_brain.md, 04_config_env.md, 05_docs_changelog.md, 06_conventions_insights.md, 07_audit_log.md.

---

## 2026-03-06 — Code-level audit (trade flow, AES, executor, monitor_manager)

**Scope:** Actual code paths and invariants, not just structure. Read trade_manager (open/expire/simulated/paper, insert_trade, insert_simulated_trade, confirm_open_trade, scheduler), auto_entry_supervisor (is_strike_already_simulated_traded, trigger_simulated_trade, check_simulated_15m_entry_hourly_htc, _simulated_15m_lock), trade_executor (trigger_trade, callback to trade_manager), monitor_manager (spawn via generate_unified_supervisor_config + supervisorctl, env_vars for DB), database.py init_database, main.py hardcoded credentials in get_trade_history_preferences_postgresql.

**Done**

- 08_code_audit.md added: trade_manager open/update/expire/scheduler flows, insert_trade vs insert_simulated_trade, confirm_open_trade and positions_updated, simulated expiration and cycle_win_loss, paper vs live settlement; auto_entry_supervisor DB connection, duplicate check, trigger_simulated_trade, 15m lock; trade_executor credentials and callback; monitor_manager config regeneration and env; invariants (no UPDATE closed, simulated/paper no executor).
- Confirmed get_port("main") in auto_entry_supervisor.py line 328 (should be "main_app") and main.py hardcoded DB in get_trade_history_preferences_postgresql.

---

## 2026-03-06 — Exhaustive audit (directive: no permission, autonomy, Eric test)

**Scope:** Full code-level audit of entire codebase; continue until genuinely complete; self-check "Would Eric think I actually completed the task?"

**Done**

- **main.py:** Read in chunks through ~6714 lines. Documented every DB connection pattern: ~45+ hardcoded psycopg2.connect(localhost, rec_io_db, rec_io_user, rec_io_password); 2 endpoints with unified_config.get_database_config() (watchlist, active_trades); 1 with POSTGRES_* env (trigger_open_trade); remainder (trade history, dashboard, total_position, monitor list, simulated trades, orders, fills, positions, settlements) use get_postgresql_connection(). Route categories (static, API, auth, trades, account, DB reads, strike tables, preferences, notifications, proxy, admin, portfolio, trade logs) documented in 08_code_audit.md.
- **active_trade_supervisor.py:** POSTGRES_* env; per-monitor table active_trades_{USER_NUMBER}_{MONITOR_ID}; monitor_list_{USER_NUMBER} (monitor_list_0001); get_monitor_port.
- **backend/core:** database.py (init_database schema and migrations), port_config.py (get_port, get_monitor_port, no "main"), unified_config.py (project_root, system_host, get_database_config).
- **Scripts:** MASTER_RESTART.sh (PORTS subset; no dynamic monitor ports), load_unified_config.sh, generate_unified_supervisor_config.py (db_config from unified_config).
- **Backend util/api:** Grep for psycopg2/get_postgresql_connection/get_database_config/POSTGRES_/DB_/REC_DB_: util has mix of DB_*, POSTGRES_*, and local/hardcoded get_postgresql_connection; trade_logger.py hardcoded; api kalshi_* use psycopg2.connect. Documented in 09_audit_exhaustive.md.
- **Frontend:** File list (39 files) and map reference (01_codebase_map).
- **09_audit_exhaustive.md:** Created with scope, findings summary, and Eric test. 07_audit_log updated.

**Findings (no code/DB changes)**

- main.py: Inconsistent DB access (hardcoded vs config); /api/active_trades proxy single port vs per-monitor ATS.
- auto_entry_supervisor: get_port("main") at 328 (bug).
- util trade_logger: Own hardcoded get_postgresql_connection; should use backend.core.config.database.
- Util/analytics: Three DB conventions; REC_DB_*→DB_* needed for scripts using database.py.
- MASTER_RESTART: Fixed port list; dynamic monitor ports not included.

**Follow-up: Per-file audit (every file reviewed)**

- User clarified that "exhaustive audit of the entire codebase" means every file in the project must be reviewed, not only critical path.
- **10_audit_per_file.md** created: every active .py, .sh, .js, .html, .css under backend/, scripts/, frontend/, tests/, root is listed with "Reviewed | Yes" and a short note. Backend api and util (and analytics) were read in full by subagent; backend root, core, scripts, frontend were read by PM. No active source file omitted.
- Additional findings: MASTER_PORT_MANIFEST lacks cascading_failure_detector and system_monitor (system_monitor.py calls get_port for both → fallback 3000). kalshi_market_watchdog get_watchdog_port() returns 5432 (Postgres port). force_cleanup_schemas.py hardcodes IP 137.184.224.94. frontend/js/AppState.js: setAccountMode/getAccountMode defined outside class (after export).
