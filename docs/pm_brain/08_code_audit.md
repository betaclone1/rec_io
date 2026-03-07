# Code audit (flows and invariants)

Actual control flow, data flow, and invariants from reading the code. Structure-only audit is in 01/07; this doc is code-level.

---

## trade_manager.py

### Open trade (POST /trades, intent=open)

1. **Simulated path:** `data.simulated_trade` true → `insert_simulated_trade(data)` → UPDATE trades_simulated_0001 SET status='open', fees=NULL, order_id_open=NULL WHERE id= trade_id → return {id}. No executor; no _is_trading_enabled check.
2. **Maintenance guard:** Else branch: `_is_trading_enabled()` false → return error trading_disabled.
3. **Paper path:** `data.paper_trade` true → insert_trade (status pending) → UPDATE trades_0001 SET status='open', fees=0, order_id_open=NULL → background thread notify_active_trade_supervisor_direct(pending then open) → return {id}. No executor.
4. **Live path:** Else → executor first: POST http://localhost:{executor_port}/trigger_trade with data (count_fp set via _format_count_fp if missing) → then insert_trade(data) status pending → notify_active_trade_supervisor_direct(pending) → return {id}. Order_id not yet stored; executor will callback /api/update_trade_status with accepted + order_id.

### insert_trade (live/paper)

- Symbol required. symbol_open, momentum*, volatility*, movement* from live_data.live_price_log_1s_{symbol} (latest row); fallback main_app /api/{symbol}_price. hour_idx from contract; weekly_cycle = base_weekly_cycle + quarter/10 (quarter from contract :00/:15/:30/:45). monitor_key → _fetch_monitor_state (loss_prevention, multiplier), cooldown_timer from monitor_list. price_spread from strike table via _get_price_spread_from_strike_table. INSERT users.trades_0001 with all fields; notify_frontend_trade_change(); return last_id.

### insert_simulated_trade

- _ensure_trades_simulated_id_sequence() once. symbol_open/momentum/etc from live_price_log_1s_{symbol} (same as insert_trade). buy_price, position, fees, bankroll, price_spread forced NULL. INSERT users.trades_simulated_0001, entry_method default 'simulated_15m', paper_trade True, test_filter False. RETURNING id; commit; return last_id.

### Status update (POST /api/update_trade_status)

- From executor. accepted: store order_id in order_id_open or order_id_close by intent; if intent=open and order_id present, start thread confirm_open_trade(id, ticket_id). error: if intent=close → update status close_failed, notes; else if insufficient_resting_volume or insufficient balance → delete pending trade and notify deleted; else update status error and notify.

### confirm_open_trade

- Poll users.orders_0001 by order_id_open until order status=executed, remaining=0, fill>0 (uses _fp columns). Compute fees, position, buy_price from orders row. If trade still pending: update trades_0001 position, buy_price, fees, symbol_open (main_app API or live_price_log fallback), status='open'; notify ATS open. Then refresh_monitor_cycle_performance_for_trade, check_and_update_cycle_metrics.

### positions_updated (POST /api/positions_updated)

- db_name=positions: for each pending trade start thread confirm_open_trade. db_name=orders: for each closing trade call confirm_close_trade (sync).

### Expiration (check_expired_trades)

- Runs every 15m (APScheduler CronTrigger minute="*/15"). delete_error_trades() first. If current_minute % 15 != 0 return. check_expired_simulated_trades() always (all open simulated → symbol_close from live_price_log_1s_{symbol} one_minute_avg/price, win_loss YES/NO vs strike, UPDATE status closed, close_method expired, sell_price NULL; then set cycle_win_loss per (monitor, date, weekly_cycle): L if any closed trade in that window has win_loss L else W). Then live trades: select open/closing/close_failed; at minute 0 process all; at 15/30/45 process only _is_15m_strategy(trade_strategy). For each: symbol_close from live_price_log_1s_{symbol}; re-check status before UPDATE (immutability: never touch status=closed); get_high_low_prices_from_active_trades; monitor_confirmed = (high_price != low_price). UPDATE status expired, closed_at, symbol_close, close_method, high_price, low_price, monitor_confirmed. notify ATS expired; separate paper vs live; paper: immediate settlement (sell_price 1 or 0, pnl, ret_pct, update_trade_status_with_ret_pct, notify closed); live: poll_settlements_for_matches(expired_tickers).

### Scheduler

- check_expired_trades: */15. check_expired_trades_for_settlements: */5. refresh_all_monitor_cycle_performance: 03:15. Lifespan also starts a daemon thread refresh_all_monitor_cycle_performance(window_days=84).

### Invariants (trade_manager)

- Never UPDATE a trade whose status is already 'closed'. confirm_open_trade only updates if current_status == 'pending'. Simulated path never calls executor. Paper path never calls executor.

---

## auto_entry_supervisor.py

### DB connection

- get_db_connection = get_postgresql_connection from backend.core.config.database (so DB_* / REC_DB_*; same as trade_manager).

### is_strike_already_simulated_traded(strike_data)

- conn = get_db_connection(). SELECT 1 FROM users.trades_simulated_0001 WHERE status IN ('open','pending') AND monitor = mon_0001_{MONITOR_ID} AND ticker = ? AND side = Y/N. Returns True if row exists. Prevents duplicate simulated trade for same strike/side/ticker per monitor.

### trigger_simulated_trade(strike_data)

- POST http://localhost:{get_port("trade_manager")}/trades with intent open (default), payload simulated_trade=True, paper_trade=True, contract = next 15m boundary (e.g. BTC 2:15pm), entry_method simulated_15m. trade_manager add_trade sees simulated_trade → insert_simulated_trade then UPDATE open.

### check_simulated_15m_entry_hourly_htc()

- get_auto_entry_settings() for min_time, max_time, min_probability, max_probability. get_master_strike_table_data_simulated_15m() (ttc_15m, probability_15m from hourly strike table). If ttc not in [min_t, max_t] or no strikes return. For each strike: active_side; strike_key = strike-side; can_trade_strike_simulated (cooldown); is_strike_already_simulated_traded; prob in [min_p, max_p]; trigger_simulated_trade(sd). Single-threaded per monitor: _simulated_15m_lock.acquire(blocking=False) so only one simulated scan at a time (avoids race on duplicate check).

### check_auto_entry_conditions()

- If hourly + auto_trade and strategy not Momentum Breakout/Contain: run check_simulated_15m_entry_hourly_htc() under _simulated_15m_lock. Then check_spike_alert_conditions(); then strategy-specific live entry (market hours, etc.).

### get_port("main") bug

- Line 328: get_port("main"). port_config has "main_app" not "main". May return wrong port or KeyError depending on manifest fallback.

---

## main.py (backend/main.py)

### DB connection patterns (exhaustive)

- **Hardcoded** (localhost, rec_io_db, rec_io_user, rec_io_password): ~45+ distinct locations. Used in: get_trade_history_preferences_postgresql (lines 93, 254), get_core_data (1339, 1376, 1444), get_trades (1564), get_btc_price_changes (1674), get_eth_price_changes (1717), get_kalshi_snapshot (1759), account/balance (1831), subaccounts get (1873), subaccounts PATCH (1903, 1937, 1988), initiate-transfer (2045), monitor/bankroll (2115), account/balance/history (2156), db/fills (2198), db/positions (2239), db/settlements (2285), db/transfers (2331), db/system_health (2375), db/trades (2421), get_current_fingerprint path, get_momentum (2503), get_btc_price (2540), get_eth_price (2567), get_momentum_score (2593), get_auto_entry_settings (2997), set_auto_entry_settings (3071), get_strike_table mobile (2632), get_live_probabilities (3408), get_strike_tables (3481), get_postgresql_strike_table (3573), historical_price_data (3934), get_system/health (4397), change_password (4377), portfolio/current (4880), portfolio/history (4923), bankroll/history (5037), pnl/history (5136), performance/realized (5209).
- **unified_config.get_database_config()**: get_watchlist (3672), get_active_trades_for_monitor (3770). Two endpoints only.
- **POSTGRES_* env with hardcoded fallbacks**: trigger_open_trade bankroll fetch (3306) uses os.getenv('POSTGRES_HOST','localhost') etc.
- **get_postgresql_connection()** (backend.core.config.database): Used from ~5299 onward: dashboard preferences get/save, total_position, and all trade-history search / monitor list / simulated trades / orders / fills / positions / settlements endpoints (see grep lines 5299, 5339, 5384, 5405, 5559, 5599, 5637, 5695, 5786, 5836, 5883, 5968, 6102, 6177, 6263, 6347, 6453, 6527, 6603).

### Route categories

- **Static/HTML**: /, /app, /login, /favicon.ico, /terminal-control.html, /log-viewer.html, /styles/*, /js/*, /mobile/* (multiple pages), /test_monitor_history_display.html.
- **API ports/health**: /api/ports, /api/test-health, /api/system-health; WebSockets /ws, /ws/preferences, /ws/db_changes.
- **Core data**: /core (get_core_data: BTC price, momentum, TTC, kraken changes; hardcoded conn x3), /api/ttc.
- **Auth**: /api/auth/login, verify, logout; /api/user/info, change-password; get_user_credentials from DB (hardcoded).
- **Trades**: /trades (list), /trades/{id} (forward to trade_manager), POST /trades (forward); /api/trigger_open_trade (build payload, POST to trade_manager).
- **Account**: /api/account/sync, balance, balance/history; /api/subaccounts (get, PATCH automatic-transfers, transfer-settings, base-value), /api/subaccounts/initiate-transfer; /api/monitor/bankroll.
- **DB entity reads**: /api/db/fills, positions, settlements, transfers, system_health, trades; all hardcoded conn except where noted.
- **Prices/momentum**: /api/btc_price, /api/eth_price, /btc_price_changes, /eth_price_changes, /api/momentum, /api/momentum_score, /api/current_fingerprint.
- **Strike tables**: /api/strike_table (mobile), /api/strike_tables/{symbol}, /api/postgresql/strike_table/{symbol}, /api/live_probabilities; /api/watchlist/{monitor_name}, /api/active_trades/{monitor_name} (unified_config).
- **Kalshi**: /kalshi_market_snapshot.
- **Preferences**: /api/update_preferences; trade history prefs get/set (load/save_trade_history_preferences → get/update_trade_history_preferences_postgresql, hardcoded); /api/get_auto_entry_settings, /api/set_auto_entry_settings (monitor_list); dashboard preferences (get_postgresql_connection).
- **Notifications**: /api/notify_auto_trade_status_change, notify_cooldown_timer_change, notify_automated_trade, notify_automated_close, broadcast_auto_entry_indicator, broadcast_active_trades_change, broadcast_monitor_total_position, broadcast_monitor_list_update, /api/notify_db_change.
- **Proxy**: /api/active_trades → ACTIVE_TRADE_SUPERVISOR_PORT; /api/auto_entry_indicator → get_port("auto_entry_supervisor").
- **Admin**: /api/admin/supervisor-status, execute-restart, execute-command, get-log-stream, create-backup, download-file.
- **Portfolio/analytics**: /api/portfolio/current, history; /api/bankroll/history; /api/pnl/history; /api/performance/realized; /api/dashboard/preferences; /api/total_position.
- **Trade logs**: /api/trade_logs, /api/log_event (trade_logger); /api/historical_price_data.

### Invariants / issues

- Inconsistent DB access: majority of endpoints ignore backend.core.config.database and use hardcoded credentials; only a subset use get_postgresql_connection() or unified_config. Production/staging with different DB credentials will fail for all hardcoded paths.
- /api/active_trades proxy uses constant ACTIVE_TRADE_SUPERVISOR_PORT; multi-monitor setups may have per-monitor ATS ports (see MASTER_PORT_MANIFEST); proxy may need to target correct ATS by monitor.
- active_trade_supervisor in critical_services (system-health) is one global name; actual processes are per-monitor (e.g. active_trade_supervisor_0001_10019).

---

## active_trade_supervisor.py

- Per-monitor Flask service. Monitor ID from script name (e.g. active_trade_supervisor_0001_10019 → 0001_10019). USER_NUMBER = 0001, MONITOR_ID = 10019. Port: get_monitor_port("active_trade_supervisor", MONITOR_IDENTIFIER). DB: POSTGRES_HOST/POSTGRES_DB/POSTGRES_USER/POSTGRES_PASSWORD (no DB_*); create/drop monitor table users.active_trades_{USER_NUMBER}_{MONITOR_ID}; get_monitor_symbol queries users.monitor_list_{USER_NUMBER} WHERE id = %s (MONITOR_ID) — table is monitor_list_0001, id is numeric monitor id (10019). Registers monitor ports via register_monitor_ports(MONITOR_IDENTIFIER).

---

## backend/core/config/database.py

- get_database_config(): DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT from env (defaults localhost, rec_io_db, rec_io_user, rec_io_password, 5432). get_postgresql_connection(): uses that config. init_database(): creates schemas users, live_data, system; creates/alters tables: trades_0001, trades_simulated_0001 (with sequence, nullable buy_price/position), active_trades_0001, trade_preferences_0001, account_history_0001, transfers_0001 (status, external_transfer_id), user_info_0001 (kalshi_user_id), monitor_list_0001 (id from sequence 10001–99999), live_data.eth_price_log, live_data.live_price_log_1s_btc (and migrations for delta_*, move_*, movement, etc.). Many ADD COLUMN IF NOT EXISTS / type migrations for trades_0001 and trades_simulated_0001 (loss_prevention, multiplier, price_spread, weekly_cycle NUMERIC, volatility_percentile, paper_trade, cooldown_timer, monitor_confirmed, cycle_*, created_at, updated_at, test_filter, notes, ret_pct, momentum_5s_avg, volatility, movement, movement_percentile, order_id). Single source of truth for schema creation; MASTER_DB_SCHEMA_REFERENCE.md should match.

---

## backend/core/port_config.py

- PORT_CONFIG_FILE = backend/core/config/MASTER_PORT_MANIFEST.json. get_port(service_name): reads manifest, checks core_services then watchdog_services; KeyError → DEFAULT_PORTS fallback. get_monitor_port(service_name, monitor_identifier): for active_trade_supervisor | auto_entry_supervisor; monitor_identifier e.g. 0001_10009; port = start_port + (monitor_id - 10000)*2 + service_offset (0 for AES, 1 for ATS). Corrupted manifest: backup to .corrupted_*, remove, ensure_port_config_exists(), retry. register_monitor_ports: can write monitor_instances into manifest (optional). No "main" key in manifest — only "main_app".

---

## backend/core/unified_config.py

- UnifiedConfigManager: project_root (find backend/main.py), system_host (REC_SYSTEM_HOST or config.local.json or socket detection or localhost), venv_path. Layered config. get_database_config() returns DB connection params (delegates to same env as database.get_database_config or mapped REC_DB_*). Used by main (watchlist, active_trades), monitor_manager, generate_unified_supervisor_config.

---

## trade_executor.py

- Flask. Credentials: load_credentials() from get_kalshi_credentials_dir() / {mode} / .env (KEY_ID, KEY_PATH=kalshi.pem). get_account_mode() → prod or demo; base URL elections.kalshi.com or demo-api.kalshi.co. /trigger_trade POST: ticket_id, ticker, side (Y/yes → yes); count_fp from data or derived from count/position; order_type limit; yes_price_dollars/no_price_dollars 0.99; time_in_force fill_or_kill; action buy; Kalshi signature via generate_kalshi_signature(POST, path, timestamp, key_path). On 200/201: extract order_id from response; POST trade_manager /api/update_trade_status with status=accepted, order_id, intent. On 4xx or request error: POST /api/update_trade_status status=error, error_message. trade_manager then stores order_id_open/order_id_close and for open intent kicks confirm_open_trade in background.

---

## monitor_manager.py

- Flask. UnifiedConfigManager; db_config = unified_config.get_database_config(); get_database_connection() uses that (database key for psycopg2). get_active_monitors(): SELECT from users.monitor_list_0001 WHERE status='active'. Spawn: does NOT fork directly; calls scripts/generate_unified_supervisor_config.py to regenerate full supervisord config (which includes per-monitor [program:auto_entry_supervisor_{id}] and [program:active_trade_supervisor_{id}] with command python backend/auto_entry_supervisor.py {id} and env_vars). _create_environment_variables() builds DB_*, POSTGRES_*, REC_DB_* from db_config. Then supervisorctl reread, update. Ports for monitor processes from get_monitor_port(service, monitor_identifier) (port_config).

---

## main.py (relevant to trade flow)

- get_trade_history_preferences_postgresql() hardcodes psycopg2.connect(host=localhost, database=rec_io_db, user=rec_io_user, password=rec_io_password) — does not use env or get_postgresql_connection. Serves /api/{symbol}_price (used as fallback by insert_trade and confirm_open_trade). notify_db_change, broadcast_active_trades_change called by trade_manager. Many routes for dashboard, monitors, strike tables, health; ~76 route decorators total.

---

## database.py (init_database)

- get_postgresql_connection() from get_database_config() (DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT). init_database(): creates schemas users, live_data, system; CREATE TABLE IF NOT EXISTS for trades_0001, trades_simulated_0001 (full column list); DO $$ blocks for additive migrations (loss_prevention, multiplier, price_spread, weekly_cycle numeric, trades_simulated id sequence and nullable buy_price/position, volatility_percentile, paper_trade, cooldown_timer, cycle_*, created_at, updated_at, test_filter, notes, ret_pct, momentum_5s_avg, volatility, movement, movement_percentile, order_id*); active_trades_0001, trade_preferences_0001, account_history_0001, monitor_list_0001, strategy_list_0001; live_data tables (eth_price_log, live_price_log_1s_btc/eth, strike_table_hourly_btc, 15m tables, live_symbol_status, price_change_*); system health_status, installation_access_log; historical_data btc/eth_price_history; analytics not created here (separate scripts). Grant privileges to rec_io_user.
