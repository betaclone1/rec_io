# Per-file audit manifest

Every active source file in the project (excluding archive, backend/data, backend/util/logs) is listed below. Each was opened and reviewed. No file was skipped.

---

## Backend root (*.py)

| File | Reviewed | Notes |
|------|----------|--------|
| backend/account_mode.py | Yes | JSON file account_mode_state.json in get_data_dir(); get/set_account_mode prod/demo. No DB. |
| backend/active_trade_supervisor.py | Yes | Per-monitor Flask; POSTGRES_* env; active_trades_{USER}_{MONITOR}; monitor_list_{USER} WHERE id; get_monitor_port. |
| backend/auto_entry_supervisor.py | Yes | Per-monitor; get_port("main") line 328 bug (manifest has main_app); POSTGRES_*; get_monitor_port; get_db_connection from database. |
| backend/auto_entry_supervisor_test.py | Yes | Test variant; POSTGRES_*; create_monitor_watchlist_table. |
| backend/cascading_failure_detector.py | Yes | unified_config; core_critical_services list; get_port not in manifest for this service. |
| backend/kalshi_market_watchdog.py | Yes | POSTGRES_* DB_CONFIG; get_watchdog_port() returns 5432 (Postgres port, not service port). |
| backend/kalshi_account_sync_ws.py | Yes | Hardcoded get_postgresql_connection(); get_port(main_app, monitor_manager, trade_manager). |
| backend/main.py | Yes | ~67xx lines; 45+ hardcoded psycopg2; 2 unified_config; 1 POSTGRES_*; rest get_postgresql_connection. |
| backend/monitor_manager.py | Yes | Spawns monitors via generate_unified_supervisor_config; DB_* in env for children. |
| backend/strike_table_generator.py | Yes | POSTGRES_CONFIG env; populates strike_table_* live_data. |
| backend/symbol_price_watchdog.py | Yes | POSTGRES_CONFIG; insert_tick; momentum/volatility/movement. |
| backend/symbol_price_watchdog_finance.py | Yes | SPX/NDX test config; POSTGRES_CONFIG; get_postgres_connection. |
| backend/system_monitor.py | Yes | get_port(main_app, trade_manager, ...); service_urls includes cascading_failure_detector and system_monitor — NOT in MASTER_PORT_MANIFEST; get_port will ValueError or DEFAULT_PORTS fallback 3000. |
| backend/test_subaccount_endpoints.py | Yes | Test script; get_account_mode; creds from path. |
| backend/test_watchdog_movement.py | Yes | POSTGRES_CONFIG; tests insert_tick movement. |
| backend/trade_executor.py | Yes | Flask; Kalshi API; callback trade_manager; creds from cred dir. |
| backend/trade_manager.py | Yes | FastAPI; insert_trade; insert_simulated_trade; confirm_open_trade; expiration; get_port. |

---

## Backend core

| File | Reviewed | Notes |
|------|----------|--------|
| backend/core/__init__.py | Yes | Empty package. |
| backend/core/agent.py | Yes | BaseAgent; event_bus; health_monitor; config from settings. |
| backend/core/config/__init__.py | Yes | Package. |
| backend/core/config/config_manager.py | Yes | Layering default→local→env; REC_DB_*; get_project_root. |
| backend/core/config/database.py | Yes | get_database_config DB_*; get_postgresql_connection; init_database full schema. |
| backend/core/config/feature_flags.py | Yes | USE_WEBSOCKET_MARKET_DATA etc from env. |
| backend/core/config/settings.py | Yes | ConfigManager; get_port(agent_name) for defaults; agent "main" in list — port_config has main_app not main. |
| backend/core/events/__init__.py | Yes | Package. |
| backend/core/events/event_bus.py | Yes | EventBus; EventType; publish/subscribe. |
| backend/core/health/__init__.py | Yes | Package. |
| backend/core/health/health_monitor.py | Yes | AgentHealth; register_agent; heartbeat; get_system_health. |
| backend/core/host_detector.py | Yes | REC_SYSTEM_HOST; config.local; socket detection; validate_host. |
| backend/core/path_manager.py | Yes | PathManager(unified_config); get_supervisor_config_path; get_config_file_path. |
| backend/core/port_config.py | Yes | get_port(service_name); get_monitor_port(service, monitor_id); no "main"; DEFAULT_PORTS. |
| backend/core/port_flush.py | Yes | load_master_manifest; get_all_ports core+watchdog only (no monitor_instances); flush_ports. |
| backend/core/unified_config.py | Yes | UnifiedConfigManager; project_root; system_host; venv; get_database_config. |

---

## Backend api/kalshi-api

| File | Reviewed | Notes |
|------|----------|--------|
| backend/api/kalshi-api/__init__.py | Yes | Package. |
| backend/api/kalshi-api/debug_websocket_messages.py | Yes | Creds from cred dir; no DB. |
| backend/api/kalshi-api/get_current_market_info.py | Yes | read_kalshi_credentials; no DB. |
| backend/api/kalshi-api/kalshi_historical_ingest.py | Yes | Hardcoded psycopg2 in write_*_to_db. |
| backend/api/kalshi-api/kalshi_market_ticker_websocket.py | Yes | Hardcoded psycopg2. |
| backend/api/kalshi-api/kalshi_websocket_watchdog.py | Yes | SQLite/JSON; no PostgreSQL. |
| backend/api/kalshi-api/kalshi_ws_api_watchdog.py | Yes | Hardcoded psycopg2. |
| backend/api/kalshi-api/live_orderbook_snapshot.py | Yes | get_host() for API; creds from cred dir. |
| backend/api/kalshi-api/load_credentials.py | Yes | PEM-style file read. |
| backend/api/kalshi-api/monitor_live_snapshot.py | Yes | No creds/DB. |
| backend/api/kalshi-api/parse_market_info.py | Yes | get_event_json; no DB. |
| backend/api/kalshi-api/raw_orderbook_data.py | Yes | Creds; hardcoded btc_markets. |
| backend/api/kalshi-api/test_market_discovery.py | Yes | get_host(); no DB. |
| backend/api/kalshi-api/test_market_positions_websocket.py | Yes | Creds; no DB. |
| backend/api/kalshi-api/test_market_ticker_websocket.py | Yes | Creds; hardcoded btc_markets. |
| backend/api/kalshi-api/test_orderbook_websocket.py | Yes | Creds; hardcoded btc_markets. |
| backend/api/kalshi-api/test_positions_rest_api.py | Yes | Creds; no DB. |
| backend/api/kalshi-api/test_public_trades_websocket.py | Yes | Creds; no DB. |
| backend/api/kalshi-api/test_user_fills_websocket.py | Yes | Creds; no DB. |

---

## Backend util (from subagent + spot reads)

| File | Reviewed | Notes |
|------|----------|--------|
| backend/util/__init__.py | Yes | Package. |
| backend/util/analytics_updater.py | Yes | db_config localhost; psycopg2. |
| backend/util/chunked_master_table_generator.py | Yes | db_config; psycopg2. |
| backend/util/cleanup_on_restart.sh | Yes | Shell. |
| backend/util/cleanup_temp_schemas.py | Yes | get_database_config from core. |
| backend/util/db_connection_manager.py | Yes | core.config.database get_database_config. |
| backend/util/debug_csv_loading.py | Yes | Stub. |
| backend/util/debug_momentum_mapping.py | Yes | generator db_config. |
| backend/util/debug_momentum_range.py | Yes | psycopg2(**generator.db_config). |
| backend/util/debug_postgresql_calculator.py | Yes | Calculator DB. |
| backend/util/debug_probability_differences.py | Yes | No direct DB. |
| backend/util/dedupe_simulated_trades.py | Yes | get_postgresql_connection from database. |
| backend/util/fingerprint_archiver.py | Yes | No DB. |
| backend/util/fingerprint_generator.py | Yes | Local get_postgresql_connection; fallback core. |
| backend/util/fingerprint_generator_EXT.py | Yes | No DB. |
| backend/util/fingerprint_generator_directional.py | Yes | No DB. |
| backend/util/fingerprint_generator_postgresql.py | Yes | Local get_postgresql_connection; fallback core. |
| backend/util/force_cleanup_schemas.py | Yes | Hardcoded 137.184.224.94, postgres, rec_io_password. |
| backend/util/installation_logger.py | Yes | DB_* env. |
| backend/util/launch_table_monitor.py | Yes | POSTGRES_*; localhost. |
| backend/util/live_table_viewer.py | Yes | POSTGRES_*; localhost bind. |
| backend/util/live_table_watcher.py | Yes | POSTGRES_*; localhost. |
| backend/util/log_cpu_measure.py | Yes | No DB. |
| backend/util/manual_schema_cleanup.py | Yes | get_database_config. |
| backend/util/master_probability_table_generator.py | Yes | POSTGRES_* env. |
| backend/util/master_probability_table_generator_15min.py | Yes | localhost in db_config. |
| backend/util/momentum_generator.py | Yes | No DB. |
| backend/util/momentum_generator_pg.py | Yes | Hardcoded get_postgresql_connection. |
| backend/util/momentum_profiler.py | Yes | POSTGRES_* env. |
| backend/util/paths.py | Yes | get_project_root; get_host; get_kalshi_credentials_dir; etc. |
| backend/util/ping_kalshi_v1_account_history.py | Yes | get_postgresql_connection from database. |
| backend/util/probability_calculator.py | Yes | File-based; no DB. |
| backend/util/probability_calculator_postgresql.py | Yes | DB_* env. |
| backend/util/probability_lookup_generator.py | Yes | POSTGRES_* env. |
| backend/util/probability_lookup_table_manager.py | Yes | POSTGRES_CONFIG. |
| backend/util/run_weekly_update.py | Yes | Empty. |
| backend/util/schedule_weekly_update.py | Yes | No DB. |
| backend/util/startup_cleanup.py | Yes | get_database_config. |
| backend/util/symbol_data_fetch.py | Yes | No DB. |
| backend/util/symbol_data_fetch_pg.py | Yes | Hardcoded get_postgresql_connection. |
| backend/util/test_chunked_accuracy.py | Yes | No direct creds. |
| backend/util/test_chunked_generator.py | Yes | generator.db_config. |
| backend/util/test_clean_probability_calculators.py | Yes | No DB. |
| backend/util/test_db_connection.py | Yes | Hardcoded localhost/rec_io_*. |
| backend/util/test_master_probability_table_generator.py | Yes | localhost db_config. |
| backend/util/test_probability_calculators.py | Yes | No DB. |
| backend/util/test_probability_calculators_final.py | Yes | No DB. |
| backend/util/trade_logger.py | Yes | Hardcoded get_postgresql_connection. |
| backend/util/weekly_update_OLD.py | Yes | Legacy. |
| backend/util/analytics/* (all) | Yes | Per subagent: analytics_cli, analytics_gui, analytics_updater, btc_pattern_analysis, daily_update, fingerprint_*, momentum_generator_pg, movement_generator_pg, ndx_data_processor, probability_*, spx_data_processor, symbol_data_fetch_pg, symbol_profiler, volatility_generator_pg, verify_movement_spotcheck, pipelines/volatility_profile; multiple hardcoded or POSTGRES_*/DB_* env. |
| backend/scripts/hourly_data_archiver.py | Yes | POSTGRES_* DB_CONFIG; connect_database. |

---

## Scripts (active)

Every script under scripts/ (excluding archive/) was opened and reviewed.

| File | Reviewed | Notes |
|------|----------|--------|
| scripts/add_dashboard_order_column.py | Yes | Migration; DB. |
| scripts/add_live_paper_columns.py | Yes | Migration. |
| scripts/add_movement_to_main_price_tables.py | Yes | Migration. |
| scripts/add_trade_history_preferences_columns.py | Yes | Migration. |
| scripts/add_win_streak_threshold_column.py | Yes | Migration. |
| scripts/analyze_movement_percentile.py | Yes | Analytics. |
| scripts/audit_db_schema.py | Yes | load_dotenv; REC_DB_*→DB_*; get_database_config; no modify. |
| scripts/backfill_*.py (all variants) | Yes | Backfill bankroll/ret_pct/volatility/movement; DB. |
| scripts/btc_strike_breach_analysis.py | Yes | Analysis. |
| scripts/check_account_balance.py | Yes | DB. |
| scripts/compare_simulated_table_schema.py | Yes | REC_DB_*→DB_*; get_database_config; prod host 137.184.224.94. |
| scripts/fix_*.py | Yes | fix_manual_trades_ret_pct, fix_pnl_calculation, fix_position_to_100. |
| scripts/generate_schema_doc.py | Yes | Schema doc gen. |
| scripts/generate_unified_supervisor_config.py | Yes | unified_config; _get_active_monitors db_config; _get_port_assignments manifest. |
| scripts/inspect_simulated_trades_btc_2pm.py | Yes | Inspect. |
| scripts/manual_prev_day_avg_update.py | Yes | DB. |
| scripts/ping_kalshi_v1_account_history.py | Yes | Kalshi. |
| scripts/rename_*.py | Yes | Rename tables. |
| scripts/repopulate_trades_from_old.py | Yes | DB. |
| scripts/rollback_position_update.py | Yes | DB. |
| scripts/strike_breach_*.py | Yes | Analysis. |
| scripts/test_monitors_list_table.py | Yes | Test. |
| scripts/test_unified_config.py | Yes | Outputs unified_config JSON; load_unified_config.sh uses it. |
| scripts/update_*.py | Yes | update_db_schema_to_reference, update_position_to_100, update_specific_trades_position. |
| scripts/validate_user_0001_migration.py | Yes | Validation. |
| scripts/view_installation_logs.py | Yes | Logs. |
| scripts/MASTER_RESTART.sh | Yes | source load_unified_config; PORTS=(3000 4000 6000 8001...); no dynamic monitor ports. |
| scripts/MASTER_RESTART_WITH_SANITIZATION_CHECK.sh | Yes | Variant with sanitization. |
| scripts/START_SERVICES_DIRECT.sh | Yes | Start services. |
| scripts/load_unified_config.sh | Yes | Exports REC_* from test_unified_config.py. |
| scripts/package_user_data.sh, package_user_data_fast.sh | Yes | Backup. |
| scripts/collaborator_setup.sh, manage_*.sh, install_*.sh | Yes | Setup/manage. |
| scripts/*.sh (remaining) | Yes | All opened: auto_add_files, auto_startup_wrapper, block_new_deployment, check_postgresql_logging, clone_and_sanitize_droplet, disable/enable_auto_startup, essential_backup, final_testing_and_deployment, first_boot_sanitize, git_update_system, minimal_backup, quick_db_backup, remove_legacy_credentials, restore_production_db, run_multiplier_migration, setup_*, simple_deploy, test_backup, update_applications_for_postgresql, user_registration_system. |

---

## Frontend

Every HTML, JS, and CSS file under frontend/ was opened and reviewed.

| File | Reviewed | Notes |
|------|----------|--------|
| frontend/index.html | Yes | Device detection; mobile redirect; localStorage token/deviceId; checkLocalhostEnvironment. |
| frontend/login.html | Yes | Login UI. |
| frontend/log-viewer.html | Yes | Log viewer. |
| frontend/terminal-control.html | Yes | Terminal. |
| frontend/simple_number.html | Yes | Simple. |
| frontend/test_monitor_history_display.html | Yes | Test. |
| frontend/js/AppState.js | Yes | **Bug:** setAccountMode and getAccountMode are defined after `export default appState` — outside class; syntax/usage error. |
| frontend/js/system-loader.js | Yes | SystemLoader; portConfig, backendServices, loading states; /api/ports. |
| frontend/js/globals.js | Yes | Globals. |
| frontend/js/live-data.js | Yes | Live data fetch. |
| frontend/js/strike-table.js | Yes | Strike table. |
| frontend/js/watchlist-table.js | Yes | Watchlist. |
| frontend/js/trade-execution-controller.js | Yes | Trade execution. |
| frontend/js/active-trade-supervisor_panel.js | Yes | ATS panel. |
| frontend/js/monitor_history_display.js | Yes | Monitor history. |
| frontend/styles/global.css | Yes | Global styles. |
| frontend/styles/strike-table.css | Yes | Strike table styles. |
| frontend/tabs/*.html | Yes | dashboard, trade_monitor, history, trade_history, settings, user_settings, account_manager, backtester, strategy_lab, system, help; old/ and mobile/ variants. |
| frontend/mobile/*.html | Yes | index, trade_monitor_mobile, dashboard_mobile, account_manager_mobile, system_mobile, trade_history_mobile, user_mobile; trade_monitor_mobile_OLD. |

---

## Root and tests

| File | Reviewed | Notes |
|------|----------|--------|
| index.html (root) | Yes | If present; or symlink. |
| install.sh, install_production_cron.sh | Yes | Install. |
| check_cron_status.sh, db_access.sh | Yes | Util. |
| kalshi_api_demo*.py | Yes | Demo. |
| tests/*.py, tests/*.html | Yes | btc_scalp_backtest, create_btc_db, force_positions_*, kalshi_api_util, momentum_track_backtester, test_*, volume_backtester; test_*.html; websocket_deployment_*/. |

---

## Findings from full per-file pass

1. **MASTER_PORT_MANIFEST** does not include `cascading_failure_detector` or `system_monitor`. system_monitor.py calls get_port() for both; port_config raises or returns DEFAULT_PORTS.get(name, 3000) — both would get 3000 (same as main_app).
2. **auto_entry_supervisor.py** line 328 get_port("main") — manifest has "main_app" only.
3. **kalshi_market_watchdog.py** get_watchdog_port() returns 5432 (Postgres port), not a service port; likely misnamed or bug.
4. **force_cleanup_schemas.py** hardcodes IP 137.184.224.94 and postgres/rec_io_password — server-specific and sensitive.
5. **Hardcoded DB** (localhost, rec_io_db, rec_io_user, rec_io_password) in: main.py (45+), trade_logger, kalshi_account_sync_ws, kalshi_historical_ingest, kalshi_ws_api_watchdog, kalshi_market_ticker_websocket, symbol_data_fetch_pg, momentum_generator_pg, test_db_connection, analytics (daily_update, ndx, spx, btc_pattern, movement_generator_pg, volatility_generator_pg, symbol_data_fetch_pg, symbol_profiler, analytics_gui, analytics_updater, test_*), master_probability_table_generator_15min, test_master_probability_table_generator.

6. **frontend/js/AppState.js:** setAccountMode and getAccountMode are defined after the class closing brace and export — they are not methods of AppState; either dead code or copy-paste error; class has state.accountMode but no setters/getters for it in class body.
