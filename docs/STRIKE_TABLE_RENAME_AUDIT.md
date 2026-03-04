# Audit: `live_data.strike_table_{symbol}` → `live_data.strike_table_hourly_{symbol}`

Full system audit before renaming strike tables. **Rename applied 2026-02-27**; code and schema doc updated.

---

## 1. Database tables (rename targets)

| Current name | New name |
|--------------|----------|
| `live_data.strike_table_btc` | `live_data.strike_table_hourly_btc` |
| `live_data.strike_table_eth` | `live_data.strike_table_hourly_eth` |
| `live_data.strike_table_ndx` | `live_data.strike_table_hourly_ndx` |
| `live_data.strike_table_spx` | `live_data.strike_table_hourly_spx` |

---

## 2. Backend – direct table name usage (must change)

### 2.1 `backend/strike_table_generator.py`

- **421** – `CREATE TABLE IF NOT EXISTS live_data.strike_table_{self.symbol.lower()}`
- **475** – `ALTER TABLE live_data.strike_table_{self.symbol.lower()} ADD COLUMN ...`
- **484–485** – `CREATE INDEX ... ON live_data.strike_table_{self.symbol.lower()}`
- **786** – `DELETE FROM live_data.strike_table_{self.symbol.lower()}`
- **887** – `INSERT INTO live_data.strike_table_{self.symbol.lower()}`
- **941** – `SELECT MAX(timestamp) FROM live_data.strike_table_{self.symbol.lower()}`
- **954** – `FROM live_data.strike_table_{self.symbol.lower()}` (get_latest_strike_table_json)
- **1046** – `FROM live_data.strike_table_{generator.symbol.lower()}`
- **1113** – `FROM live_data.strike_table_{generator.symbol.lower()}`
- **1125** – `FROM live_data.strike_table_{generator.symbol.lower()}`
- **1159** – `FROM live_data.strike_table_{self.symbol.lower()}` (get_strike_table_consistency_info)

### 2.2 `backend/active_trade_supervisor.py`

- **1291** – `FROM live_data.strike_table_{symbol.lower()}` (get_current_probability)
- **2571** – `SELECT ttc_seconds FROM live_data.strike_table_{symbol.lower()} LIMIT 1` (get_unified_ttc_seconds)

### 2.3 `backend/auto_entry_supervisor.py`

- **1710** – `FROM live_data.strike_table_{current_symbol.lower()}` (get_master_strike_table_data header)
- **1734** – `FROM live_data.strike_table_{current_symbol.lower()}` (get_master_strike_table_data rows)

### 2.4 `backend/auto_entry_supervisor_test.py`

- **474** – `FROM live_data.strike_table_{symbol.lower()}`
- **1055** – `FROM live_data.strike_table_{current_symbol.lower()}`
- **1075** – `FROM live_data.strike_table_{current_symbol.lower()}`

### 2.5 `backend/trade_manager.py`

- **194** – `sql.Identifier(f'strike_table_{symbol_lower}')` in `_get_price_spread_from_strike_table` (table name in SELECT)

### 2.6 `backend/main.py`

- **2606** – `FROM live_data.strike_table_btc` – `/api/strike_table` (mobile; hardcoded BTC)
- **3367** – `FROM live_data.strike_table_btc` – `/api/live_probabilities` (hardcoded BTC)
- **3443** – `FROM live_data.strike_table_{symbol_lower}` – `/api/strike_tables/{symbol}` (header)
- **3468** – `FROM live_data.strike_table_{symbol_lower}` – `/api/strike_tables/{symbol}` (rows)
- **3535** – `FROM live_data.strike_table_{symbol.lower()}` – `/api/postgresql/strike_table/{symbol}` (header)
- **3560** – `FROM live_data.strike_table_{symbol.lower()}` – `/api/postgresql/strike_table/{symbol}` (rows)
- **3804** – `FROM live_data.strike_table_btc` – `/api/unified_ttc/{symbol}` (bug: uses BTC regardless of `symbol` param)

### 2.7 `backend/core/config/database.py`

- **486** – `ARRAY['strike_table_btc','strike_table_eth','strike_table_spx','strike_table_ndx']` in DO block (add volatility/movement columns to existing tables)
- **624** – `CREATE TABLE IF NOT EXISTS live_data.strike_table_btc` (init_database bootstrap; only creates BTC table)

---

## 3. Backend – service/config only (no table rename)

These refer to **process/service** names or **file paths**, not the DB table name. Leave as-is for the rename; only the DB table name changes.

- **backend/core/port_config.py** – `strike_table_generator_btc`, `strike_table_generator_eth` (service names)
- **backend/system_monitor.py** – `strike_table_generator_*`, `strike_table_port`, etc. (service discovery)
- **backend/cascading_failure_detector.py** – `strike_table_generator_btc` etc. (service list)
- **scripts/generate_unified_supervisor_config.py** – `strike_table_generator_*`, script name (service config)
- **backend/auto_entry_supervisor.py** – `get_strike_table_path()`, `get_master_strike_table_data()`, `strike_table_data` (vars), `generate_watchlist_from_strike_table_DELETED` (file path `strike_table_{symbol}.json` under data dir)
- **backend/auto_entry_supervisor_test.py** – `get_strike_table_path()`, `get_master_strike_table_data()`, `strike_table_data`, `generate_watchlist_from_strike_table()` (same: paths/vars, not table name)
- **backend/trade_manager.py** – `_get_price_spread_from_strike_table`, `notify_strike_table_trade_change` (function names; one of them uses the table—see 2.5)

---

## 4. Frontend – API usage only (no change for rename)

Frontend calls **API routes**; it does not reference the DB table name. After backend table rename and code updates, these continue to work unchanged.

- **frontend/js/strike-table.js** – `apiCall(\`/api/postgresql/strike_table/${symbol}\`)`, `getApiBaseUrl` test URL
- **frontend/js/system-loader.js** – `/api/postgresql/strike_table/btc` (health check)
- **frontend/tabs/trade_monitor.html** – `fetch(.../api/strike_tables/${currentSymbol.toLowerCase()})`
- **frontend/tabs/system.html** – `strike_table_generator` in script list (service name)
- **frontend/mobile/trade_monitor_mobile.html** – `fetch(.../api/strike_tables/${currentSymbol.toLowerCase()})`
- **frontend/mobile/trade_monitor_mobile_OLD.html** – `fetch(.../api/strike_tables/btc)` (legacy)

---

## 5. Docs and logs (update for consistency)

- **docs/MASTER_DB_SCHEMA_REFERENCE.md** – Sections for `live_data.strike_table_btc`, `strike_table_eth`, `strike_table_ndx`, `strike_table_spx`; all index/constraint SQL that references those table names.
- **DATABASE_CHANGES_LOG.md** – References to `live_data.strike_table_btc` etc. and ALTER examples.
- **docs/PRODUCTION_DB_SCHEMA_AND_BACKFILL_MASTER.md** – Table list and generator description.

---

## 6. Archive / legacy (optional)

- **scripts/archive_old/migrate_strike_table.py** – Old migration: creates/inserts into `live_data.strike_table_btc`. Only matters if someone re-runs it; can leave as-is or update to `strike_table_hourly_btc` for consistency.
- **scripts/archive_old/start_postgresql_system.sh**, **stop_postgresql_system.sh** – `strike_table_analysis.py` (different script name).
- **scripts/archive_old/generate_supervisor_config.sh** – `strike_table_generator` (service).
- **scripts/archive_old/fix_strike_table.sh** – `strike_table_generator` (service).
- **docs/archive/** – Various mentions of `strike_tables` API or `strike_table_generator`; no direct DB table names that need changing for the rename.

---

## 7. Other files (no table name change)

- **.gitignore** – `strike_tables/` directory path.
- **config/logrotate_updated.conf** – `strike_table_generator_*.log` (log file pattern).
- **scripts/MASTER_RESTART.sh**, **MASTER_RESTART_WITH_SANITIZATION_CHECK.sh** – `strike_table_generator` in process kill list.
- **docs/MOMENTUM_SCALP_STRATEGY_PLAN.md**, **AUTO_ENTRY_SUPERVISOR_AUDIT.md**, **PAPER_TRADING_IMPLEMENTATION.md**, **NEW_TRADE_ENTRY_AND_RECORDING_REFERENCE.md** – Logic or “strike table” in prose; no `live_data.strike_table_*` table names.

---

## 8. Summary – what to change for the rename

| Category | Action |
|----------|--------|
| **DB** | Run migration: `ALTER TABLE live_data.strike_table_* RENAME TO strike_table_hourly_*` for btc, eth, ndx, spx. |
| **Backend (table name)** | Update all 2.x references above to `strike_table_hourly_{symbol}` (or `strike_table_hourly_btc` where hardcoded). Fix `main.py` `/api/unified_ttc/{symbol}` to use `symbol` in the table name. |
| **database.py** | Update ARRAY and `CREATE TABLE` to use `strike_table_hourly_*`. |
| **Frontend** | No change (API contract unchanged). |
| **Docs** | Update MASTER_DB_SCHEMA_REFERENCE.md, DATABASE_CHANGES_LOG.md, PRODUCTION_DB_SCHEMA_AND_BACKFILL_MASTER.md. |
| **Archive** | Optional: update `scripts/archive_old/migrate_strike_table.py` if you want old script to target new name. |

---

## 9. Future: 15-minute markets

When monitors are added for 15m markets, they can use a separate strike table set (e.g. `live_data.strike_table_15m_{symbol}`). Monitor configuration (symbol + interval or table name) will direct that monitor’s iterative scripts—strike table generator, auto entry, TTC/probability reads—to the correct table. Hourly monitors keep using `strike_table_hourly_*`; 15m monitors point at the 15m tables. No change to this rename is required for that.

---

## 10. Note on `/api/unified_ttc/{symbol}` and `/api/strike_table` / `/api/live_probabilities`

- **`/api/unified_ttc/{symbol}`** – Currently queries `live_data.strike_table_btc` only; should query `live_data.strike_table_hourly_{symbol}` (or equivalent with `symbol` param).
- **`/api/strike_table`** – No symbol param; hardcodes BTC. If this is mobile-only and always BTC, renaming to `strike_table_hourly_btc` is sufficient; otherwise consider adding symbol or deprecating.
- **`/api/live_probabilities`** – No symbol param; hardcodes BTC. Same as above for the rename.
