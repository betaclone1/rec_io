# Project overview

## Company and product

- **Company:** rec.io (Eric Wais, founder/CEO). Domain: rec-io.com.
- **Product (inferred):** Trading system for prediction markets (Kalshi). Live and simulated trading; hourly and 15m cycles; BTC/ETH (and SPX/NDX in analytics). Strategy: Hourly HTC, momentum scalp, etc. Monitors per symbol; auto_entry_supervisor and active_trade_supervisor per monitor.
- **Domain flow (brief):** Price data → symbol_price_watchdog → live_price_log_1s_*; Kalshi markets → kalshi_market_watchdog → market_kalshi_*; strike_table_generator → strike_table_* (ttc, probability). Monitors (monitor_list_0001) have auto_trade; auto_entry_supervisor reads strike tables and inserts trades (live → trades_0001, simulated → trades_simulated_0001). trade_manager handles expiration (hourly + 15m), symbol_close from live price, cycle_win_loss. trade_executor sends orders to Kalshi. main_app serves UI and API; monitor_manager spawns per-monitor AES/ATS processes.

## Repo layout (root)

- **backend/** — Python app: main FastAPI (main.py), trade_manager, trade_executor, monitor_manager, auto_entry_supervisor, active_trade_supervisor, strike_table_generator, symbol_price_watchdog, kalshi_market_watchdog, kalshi_account_sync, cascading_failure_detector, system_monitor. Core in backend/core/, API in backend/api/kalshi-api/, util in backend/util/.
- **frontend/** — Web UI: HTML tabs (dashboard, trade_monitor, history, settings, etc.), JS (live-data, strike-table, watchlist, trade-execution-controller, etc.), CSS. Mobile variants in frontend/mobile/.
- **scripts/** — Bash and Python: MASTER_RESTART.sh, load_unified_config.sh, package_user_data.sh, generate_unified_supervisor_config.py, backfill scripts, DB audit/compare, install/backup. Archives in scripts/archive/, scripts/archive_old/.
- **docs/** — Documentation. Changelog in docs/changelog/ (MASTER_CHANGELOG.md, CHANGELOG_AGENT_INSTRUCTIONS.md, TODO.md). Schema: docs/MASTER_DB_SCHEMA_REFERENCE.md. PM brain: docs/pm_brain/.
- **config/** — firewall_whitelist.json, etc.
- **tests/** — Unit/integration tests (database abstraction, system integration, active_trade_supervisor_v2, etc.).
- **.cursor/rules/** — pm.mdc, updater.mdc, changelog.mdc. AGENTS.md at root.
- **logs/** — Application logs (gitignored pattern).
- **venv/** — Python venv (gitignored).

## Key paths

- Project root: where install.sh, requirements.txt, AGENTS.md live.
- Backend entry: backend/main.py (FastAPI), backend/trade_manager.py, backend/trade_executor.py, backend/monitor_manager.py, backend/auto_entry_supervisor.py, backend/active_trade_supervisor.py.
- Port config: backend/core/config/MASTER_PORT_MANIFEST.json. Port resolution: backend/core/port_config.py get_port(service_name).
- DB config: backend/core/config/database.py (get_database_config, get_postgresql_connection, init_database). Env: DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT (or REC_DB_* from .env).
- Unified config: backend/core/unified_config.py (UnifiedConfigManager); ConfigManager: backend/core/config/config_manager.py. Default config: backend/core/config/config.default.json.
