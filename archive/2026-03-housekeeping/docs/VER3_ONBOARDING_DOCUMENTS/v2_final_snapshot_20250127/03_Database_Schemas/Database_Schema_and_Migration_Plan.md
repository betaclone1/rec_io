# Database Schema & Migration Plan – REC.IO v2

## Purpose
Define current database schema state, migration history, and completed transition from mixed storage (PostgreSQL + SQLite + JSON) to fully centralized PostgreSQL.

---

## 1. Current State (v2 Snapshot - UPDATED)
**Primary DB:** PostgreSQL (`03_Database_Schemas/postgresql_schema.sql`)

**✅ MIGRATION COMPLETE:** All live data now centralized in PostgreSQL

**Current Data Architecture:**
- **PostgreSQL `live_data.btc_price_log`**: Live BTC price, momentum, and delta data (migrated from SQLite)
- **PostgreSQL `live_data.eth_price_log`**: Live ETH price, momentum, and delta data
- **PostgreSQL Core Tables**: Trades, positions, settlements, fills, account data
- **PostgreSQL System Tables**: Health checks, supervisor logs, system state

**Legacy Data Stores (ARCHIVED):**
- **SQLite** (`btc_price_history.db`): Archived to `archive/deprecated_services/`
- **SQLite** (legacy ingest): Archived and replaced with PostgreSQL-only writes
- **JSON snapshots**: Retained for archival purposes only

**Schema Scope in PostgreSQL:**
- **Trades**: Full lifecycle records (`trades`, `positions`, `settlements`, `fills`)
- **Market Data**: Real-time Kalshi market state, BTC/ETH prices (complete)
- **Live Data**: Momentum, delta calculations, price history (complete)
- **Account Data**: Balances, open positions
- **System State**: Health checks, supervisor logs (all services)

**User Data Isolation:** All tables under `user_0001` namespace

---

## 2. Migration History (COMPLETED)
- **v1 → v2**: Introduced PostgreSQL as primary store; 95% of live writes migrated from SQLite/JSON
- **v2 milestone**: Port/path/env centralized; PostgreSQL schema unified
- **✅ COMPLETED**: Final removal of SQLite/JSON for live writes
- **✅ COMPLETED**: `btc_price_watchdog` → `symbol_price_watchdog_btc` with PostgreSQL storage
- **✅ COMPLETED**: `live_data_analysis.py` → Direct PostgreSQL queries for momentum/delta data

---

## 3. Migration Tasks (COMPLETED)
1. **✅ btc_price_watchdog** – Migrated to `symbol_price_watchdog_btc` with PostgreSQL storage
2. **✅ live_data_analysis** – Replaced with direct PostgreSQL queries for momentum/delta data
3. **✅ kalshi_api_watchdog** – PostgreSQL inserts for market data (JSON export retained for archives)
4. **✅ kalshi_historical_ingest** – PostgreSQL-only writes implemented
5. **✅ SQLite schemas** – Archived `.db` files and removed from runtime paths

---

## 4. Data Retention & Archiving (CURRENT)
- **BTC price history**: Retained in PostgreSQL `live_data.btc_price_log` (2+ years)
- **ETH price history**: Retained in PostgreSQL `live_data.eth_price_log`
- **Market data snapshots**: JSONs archived to cold storage; no runtime reads
- **Historical Kalshi data**: All migrated to PostgreSQL; legacy SQLite archived

---

## 5. Migration Execution (COMPLETED)
**✅ Pre-reqs Completed:**
- `postgresql_schema.sql` updated with latest production DB
- All SQLite and JSON datasets backed up before migration

**✅ Steps Completed:**
1. **✅** PostgreSQL insert logic added to all legacy writers
2. **✅** Dual-write paths run in parallel for validation
3. **✅** Parity validated: Row counts, hash checks between old and new sources
4. **✅** Legacy write code removed; all readers switched to PostgreSQL
5. **✅** SQLite/JSON dependencies removed from config
6. **✅** `.db` and snapshot files archived and removed from active paths

**✅ Downtime:** None - deployed via rolling restarts

---

## 6. Rollback Strategy (ARCHIVED)
- **✅** Dual-write branches retained for 1 month post-cutover (completed)
- **✅** Legacy write paths archived in VCS tags
- **✅** SQLite/JSON backups maintained for emergency recovery

---

## 7. Verification Checklist (COMPLETED)
- **✅** All services start without missing file errors for SQLite/JSON
- **✅** BTC price history table in PostgreSQL has continuous data with correct intervals
- **✅** Market snapshot table matches JSON export frequency
- **✅** Historical ingest jobs populate PostgreSQL only
- **✅** Legacy `.db` and `.json` files removed from runtime paths
- **✅** `symbol_price_watchdog_btc` writing to PostgreSQL `live_data.btc_price_log`
- **✅** All services reading momentum/delta from PostgreSQL directly
- **✅** `unified_production_coordinator` using PostgreSQL data for strike table generation

---

## 8. Current Data Flow Architecture

### **Live Data Pipeline**
1. **Coinbase WebSocket** → `symbol_price_watchdog_btc` → **PostgreSQL `live_data.btc_price_log`**
2. **Coinbase WebSocket** → `symbol_price_watchdog_eth` → **PostgreSQL `live_data.eth_price_log`**
3. **PostgreSQL `live_data.btc_price_log`** → All services (direct queries)
4. **Kalshi API** → `kalshi_account_sync` → **PostgreSQL account tables**
5. **PostgreSQL** → `unified_production_coordinator` → **Strike table JSON files**

### **Benefits Achieved**
- **Single Source of Truth**: PostgreSQL `live_data` schema
- **Reduced Complexity**: No redundant calculations
- **Better Performance**: Direct database queries
- **Improved Consistency**: Centralized data storage
- **Easier Maintenance**: Single data source to manage

---

## 9. Schema Details

### **live_data Schema**
```sql
-- BTC Price Log (Primary live data source)
CREATE TABLE live_data.btc_price_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    price DECIMAL(20,8),
    momentum DECIMAL(10,6),
    delta_1m DECIMAL(10,6),
    delta_2m DECIMAL(10,6),
    delta_3m DECIMAL(10,6),
    delta_4m DECIMAL(10,6),
    delta_15m DECIMAL(10,6),
    delta_30m DECIMAL(10,6)
);

-- ETH Price Log
CREATE TABLE live_data.eth_price_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    price DECIMAL(20,8),
    momentum DECIMAL(10,6),
    delta_1m DECIMAL(10,6),
    delta_2m DECIMAL(10,6),
    delta_3m DECIMAL(10,6),
    delta_4m DECIMAL(10,6),
    delta_15m DECIMAL(10,6),
    delta_30m DECIMAL(10,6)
);
```

### **Core Tables**
- `trades`: Trade lifecycle records
- `positions`: Current positions
- `settlements`: Settlement data
- `fills`: Fill records
- `system.health_status`: System monitoring data

---

## 10. Maintenance Procedures

### **Data Retention**
- **Live Data**: Retain 2+ years in PostgreSQL
- **Archived Data**: Compressed backups in `archive/` directory
- **Log Files**: Rotated via logrotate configuration

### **Backup Strategy**
- **PostgreSQL**: Daily automated backups
- **Configuration**: Version controlled in Git
- **Archived Services**: Preserved in `archive/deprecated_services/`

### **Monitoring**
- **Data Quality**: Continuous monitoring via system services
- **Performance**: PostgreSQL query optimization
- **Health Checks**: Automated via `system_monitor` service
