# Services and ports

## MASTER_PORT_MANIFEST.json (source of truth)

- **Path:** backend/core/config/MASTER_PORT_MANIFEST.json.
- **Core:** main_app 3000, trade_manager 4000, active_trade_supervisor 6000, trade_executor 8001.
- **Watchdogs:** kalshi_account_sync 8004, kalshi_market_watchdog_hourly_btc 8005, hourly_eth 8011, 15m_btc 8021, 15m_eth 8022; strike_table_generator hourly btc 8014, eth 8015, spx 8016, ndx 8017; 15m btc 8023, eth 8024; monitor_manager 8012.
- **Monitor instances:** Per-monitor ports from start_port 8013 + (monitor_id - 10000)*2 + offset (auto_entry_supervisor 0, active_trade_supervisor 1). Example: 0001_10019 → 8051, 8052.

## MASTER_RESTART.sh

- **Ports flushed:** 3000 4000 6000 8001 8002 8003 8004 8005 8008 (subset of manifest).
- **Config:** Loads scripts/load_unified_config.sh; SUPERVISOR_CONFIG = backend/supervisord.conf; socket /tmp/supervisord.sock.

## Port resolution in code

- backend/core/port_config.py: get_port(service_name) reads MASTER_PORT_MANIFEST.json (core_services, watchdog_services, monitor_instances). DEFAULT_PORTS fallback if manifest missing.
- Callers: main.py, trade_manager.py, trade_executor.py, active_trade_supervisor.py, auto_entry_supervisor.py, monitor_manager.py, system_monitor.py, kalshi_account_sync_ws.py.

## Service roles (brief)

- main_app: FastAPI; serves frontend, API routes, websockets, DB proxies.
- trade_manager: Trade lifecycle, expiration, simulated 15m close, notify_db_change.
- trade_executor: Order execution (Kalshi).
- active_trade_supervisor: Per-monitor active trade monitoring.
- auto_entry_supervisor: Per-monitor auto entry (live + simulated 15m).
- monitor_manager: Spawns/manages per-monitor processes, REST API for monitor CRUD.
- strike_table_generator_*: Populate live_data.strike_table_*.
- symbol_price_watchdog_*: Populate live_data.live_price_log_1s_*.
- kalshi_market_watchdog_*: Kalshi market data.
- kalshi_account_sync: Sync account/fills/orders/positions to DB.
- cascading_failure_detector, system_monitor: Health/monitoring.
