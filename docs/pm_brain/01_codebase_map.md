# Codebase map

## Backend root (backend/*.py)

- **main.py** — FastAPI app; static files, API routes, websockets; get_port("main_app"), UnifiedConfigManager; trade history preferences, dashboard, monitors, trades, strike tables, DB health, notify_db_change, broadcast_active_trades_change. Large file (~6k+ lines).
- **trade_manager.py** — Trade lifecycle, expiration (hourly + 15m), simulated 15m close (check_expired_simulated_trades), cycle_win_loss; get_port("trade_manager"), get_port("trade_executor"); notify_db_change, broadcast. ~4k lines.
- **trade_executor.py** — Order execution (Kalshi); get_port("trade_executor"), get_port("trade_manager").
- **monitor_manager.py** — Spawns per-monitor auto_entry_supervisor and active_trade_supervisor; REST API; get_port("monitor_manager"); DB config passed to children (DB_*, REC_DB_*).
- **auto_entry_supervisor.py** — Per-monitor; live + simulated 15m entry; uses backend.core.config.database for simulated duplicate check; get_port("main_app"), get_port("trade_manager"). Large.
- **active_trade_supervisor.py** — Per-monitor active trade monitoring; get_port("main_app").
- **strike_table_generator.py** — Populates live_data.strike_table_* (hourly/15m).
- **symbol_price_watchdog.py** — Price ingestion (symbol_price_watchdog_finance.py variant).
- **kalshi_market_watchdog.py** — Kalshi market data.
- **kalshi_account_sync_ws.py** — Account sync; get_port("main_app"), get_port("monitor_manager"), get_port("trade_manager").
- **cascading_failure_detector.py**, **system_monitor.py** — Health; system_monitor uses get_port for many services.
- **account_mode.py** — Account mode (prod/demo etc.).

## Backend core (backend/core/)

- **config/database.py** — get_database_config(), get_postgresql_connection(), test_database_connection(), init_database(). Single schema migration source.
- **config/config_manager.py** — ConfigManager; default + local JSON; REC_DB_* env overrides.
- **config/MASTER_PORT_MANIFEST.json** — Port assignments.
- **config/config.default.json**, **config.local.json** — Layered config.
- **unified_config.py** — UnifiedConfigManager (system host, DB, venv).
- **port_config.py** — get_port(service_name), get_port_info(), list_all_ports(); reads MASTER_PORT_MANIFEST.
- **path_manager.py**, **host_detector.py** — Paths and host detection.
- **port_flush.py** — Port flushing.
- **events/event_bus.py** — Event bus.
- **health/health_monitor.py** — Health checks.
- **agent.py** — Agent utilities.

## Backend API (backend/api/)

- **kalshi-api/** — Kalshi client: credentials (load_dotenv from cred dir), historical ingest, orderbook, websocket watchdogs, market ticker, fills/positions tests, raw_orderbook_data, live_orderbook_snapshot. Many files.

## Backend util (backend/util/)

- **paths.py** — get_project_root, get_data_dir, get_trade_history_dir, get_host, get_service_url.
- **probability_calculator_postgresql.py**, **probability_calculator.py** — Probability calc.
- **master_probability_table_generator.py**, **master_probability_table_generator_15min.py** — Lookup tables.
- **probability_lookup_generator.py**, **probability_lookup_table_manager.py** — Lookup management.
- **momentum_generator*.py**, **momentum_profiler.py** — Momentum.
- **fingerprint_*.py** — Fingerprint generation/archiver.
- **trade_logger.py**, **installation_logger.py** — Logging.
- **dedupe_simulated_trades.py** — One-time dedupe of users.trades_simulated_0001.
- **analytics/** — probability_lookup_generator, symbol_profiler, volatility_profile, daily_update, movement_generator_pg, fingerprint_*, analytics_gui, etc.
- **live_table_watcher.py**, **live_table_viewer.py** — Live data inspection.
- **db_connection_manager.py**, **test_db_connection.py** — DB helpers.
- **launch_table_monitor.py** — Launch table monitor with env.

## Frontend (frontend/)

- **index.html** — Entry.
- **tabs/** — dashboard.html, trade_monitor.html, history.html, trade_history.html, settings.html, user_settings.html, account_manager.html, backtester.html, strategy_lab.html, system.html, help.html; old/ and mobile/ variants.
- **js/** — globals.js, AppState.js, system-loader.js, live-data.js, strike-table.js, watchlist-table.js, trade-execution-controller.js, active-trade-supervisor_panel.js, monitor_history_display.js.
- **styles/** — global.css, strike-table.css.
- **log-viewer.html**, **terminal-control.html**, **login.html**.

## Scripts (scripts/)

- **MASTER_RESTART.sh** — Flush ports, restart supervisor; source load_unified_config.sh.
- **load_unified_config.sh** — Export REC_* from test_unified_config.py.
- **generate_unified_supervisor_config.py** — Generate supervisord config; DB_*, REC_DB_* in env for children.
- **package_user_data.sh**, **package_user_data_fast.sh** — Backup; source .env.
- **compare_simulated_table_schema.py**, **audit_db_schema.py** — DB schema compare/audit; load .env, REC_DB_*→DB_*.
- **backfill_*.py** — Backfill bankroll, ret_pct, etc.
- **fix_*.py**, **update_*.py** — One-off fixes (position, pnl, etc.).
- **manage_monitors_list.sh**, **manage_master_users.sh** — Monitor/user management.
- **install*.sh**, **collaborator_setup.sh**, **first_boot_sanitize.sh** — Install/setup.
- **minimal_backup.sh**, **essential_backup.sh** — DB backup (pg_dump).
- Archives: **archive/**, **archive_old/** — Older migration and install scripts.

## Audit addenda (explore)

- **main.py:** ~76 API route decorators (@app.get/post/patch). No router.* in that file.
- **trade_manager.py __main__:** Runs uvicorn with FastAPI app on host 0.0.0.0, port get_port("trade_manager").
- **Backend using DB connection/init:** active_trade_supervisor, auto_entry_supervisor, main, trade_manager, monitor_manager, kalshi_account_sync_ws; core config_manager, unified_config, database; util dedupe_simulated_trades, trade_logger, fingerprint_*, momentum_*, cleanup_temp_schemas, manual_schema_cleanup, startup_cleanup, db_connection_manager, ping_kalshi_v1_account_history, symbol_data_fetch_pg; util/analytics symbol_profiler, fingerprint_*, momentum_*, movement_*, volatility_*, symbol_data_fetch_pg, verify_movement_spotcheck.
- **Supervisor:** backend/supervisord.conf — programs main_app, trade_manager, trade_executor, symbol_price_watchdog_btc/eth/spx/ndx, ...; each has full env (DB_*, REC_DB_*, POSTGRES_*, REC_PROJECT_ROOT, etc.). Paths may be absolute (machine-specific); generate_unified_supervisor_config.py produces config with placeholders or overrides.

## Entry points (__main__)

- **main.py:** uvicorn.run(app, host="0.0.0.0", port=MAIN_APP_PORT).
- **trade_manager.py:** uvicorn.run(app, host="0.0.0.0", port=get_port("trade_manager")).
- **trade_executor.py:** (check __main__) — runs executor server.
- **auto_entry_supervisor.py:** start_event_driven_supervisor(); Flask app; uses get_monitor_port, get_port; DB via get_postgresql_connection (alias get_db_connection).
- **active_trade_supervisor.py:** create_monitor_active_trades_table() then presumably starts server.
- **monitor_manager.py:** print + start (core monitor management).
- **kalshi_account_sync_ws.py:** main() — hybrid WebSocket/polling supervisor.
- **system_monitor.py:** SystemMonitor().run_monitoring_loop().
- **kalshi_market_watchdog.py:** main() with POLL_INTERVAL_SECONDS.
- **symbol_price_watchdog.py:** (arg: symbol BTC/ETH/SPX/NDX).
- **dedupe_simulated_trades.py:** main() — one-time dedupe.
- **kalshi_historical_ingest.py:** main() — sync settlements, write to DB.
- Util/analytics: many CLI entry points (main(), argparse).
