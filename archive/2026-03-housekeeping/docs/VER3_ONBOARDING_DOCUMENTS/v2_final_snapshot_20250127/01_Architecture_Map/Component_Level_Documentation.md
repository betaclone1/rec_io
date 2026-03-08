# Component Level Documentation

## Overview
This document provides detailed documentation for all major services in the REC.IO v2 system, including their purpose, inputs/outputs, error behavior, dependencies, and operational procedures.

**🔄 RECENT UPDATES:** System has been migrated to PostgreSQL with centralized data architecture. Legacy SQLite services have been deprecated and archived.

---

## Core Services

### 1. Main Application (`backend/main.py`)
**Purpose**: Primary web application serving the frontend interface and API endpoints

**Inputs**:
- HTTP requests from frontend
- Database queries to PostgreSQL
- WebSocket connections for real-time updates

**Outputs**:
- HTML/JS/CSS responses to frontend
- JSON API responses
- WebSocket messages for real-time data

**Error Behavior**:
- Returns HTTP error codes (400, 500, etc.)
- Logs errors to `logs/main_app.err.log`
- Graceful degradation for database connection failures
- Automatic restart via supervisor on critical failures

**Dependencies**:
- PostgreSQL database
- Trade Manager service (port 4000)
- Active Trade Supervisor (port 8007)
- Frontend static files

**Startup Sequence**:
1. Initialize database connections
2. Start WebSocket server
3. Load configuration from `config.json`
4. Register API endpoints
5. Start HTTP server on port 3000

**Shutdown Sequence**:
1. Close database connections
2. Disconnect WebSocket clients
3. Graceful HTTP server shutdown
4. Log shutdown completion

**Failure Recovery**:
- Automatic restart via supervisor
- Database connection retry logic
- WebSocket reconnection handling
- Configuration fallback to defaults

**Data Sources**:
- **BTC Price:** PostgreSQL `live_data.btc_price_log` (migrated from SQLite)
- **Momentum/Delta:** PostgreSQL `live_data.btc_price_log` (direct from database)
- **Trade Data:** PostgreSQL `trades`, `fills`, `settlements` tables

---

### 2. Trade Manager (`backend/trade_manager.py`)
**Purpose**: Core service for managing trade lifecycle and database operations

**Inputs**:
- Trade execution requests from Trade Executor
- Market data from PostgreSQL `live_data.btc_price_log`
- Account updates from Kalshi API

**Outputs**:
- Database writes to PostgreSQL (trades, fills, settlements, positions)
- Trade status updates to frontend
- Position calculations and PnL updates

**Error Behavior**:
- Database transaction rollback on errors
- Retry logic for failed database operations
- Logs errors to `logs/trade_manager.err.log`
- Continues operation with partial data if some operations fail

**Dependencies**:
- PostgreSQL database
- Kalshi API credentials
- Trade Executor service
- Active Trade Supervisor

**Startup Sequence**:
1. Initialize PostgreSQL connection pool
2. Create database schemas if not exists
3. Load user configuration
4. Start trade monitoring loop
5. Initialize position tracking

**Shutdown Sequence**:
1. Complete pending database transactions
2. Close database connections
3. Save current positions state
4. Log shutdown completion

**Failure Recovery**:
- Database connection retry with exponential backoff
- Transaction rollback and retry
- Position recalculation on restart
- Trade state recovery from database

**Data Sources**:
- **Market Data:** PostgreSQL `live_data.btc_price_log` (migrated from SQLite)
- **Momentum Data:** PostgreSQL `live_data.btc_price_log` (direct from database)

---

### 3. Trade Executor (`backend/trade_executor.py`)
**Purpose**: Executes trades on Kalshi API and manages order lifecycle

**Inputs**:
- Trade signals from strategies
- Market data from PostgreSQL `live_data.btc_price_log`
- Account balance from Kalshi API

**Outputs**:
- Kalshi API order submissions
- Order confirmations to Trade Manager
- Fill notifications to frontend

**Error Behavior**:
- Retry failed API calls with exponential backoff
- Logs errors to `logs/trade_executor.err.log`
- Continues operation with error reporting
- Automatic order cancellation on critical failures

**Dependencies**:
- Kalshi API credentials
- Trade Manager service
- PostgreSQL `live_data.btc_price_log`
- Account balance validation

**Startup Sequence**:
1. Load Kalshi credentials
2. Initialize API client
3. Validate account access
4. Start order monitoring loop
5. Initialize risk management

**Shutdown Sequence**:
1. Cancel pending orders
2. Close API connections
3. Save execution state
4. Log shutdown completion

**Failure Recovery**:
- API authentication retry
- Order state recovery from Kalshi
- Balance reconciliation
- Risk limit enforcement

**Data Sources**:
- **BTC Price:** PostgreSQL `live_data.btc_price_log` (migrated from SQLite)

---

### 4. Active Trade Supervisor (`backend/active_trade_supervisor.py`)
**Purpose**: Monitors active trades and manages position risk

**Inputs**:
- Active trade data from PostgreSQL database
- Market price updates from PostgreSQL `live_data.btc_price_log`
- Risk management rules

**Outputs**:
- Trade closure signals to Trade Executor
- Risk alerts to frontend
- Position updates to database

**Error Behavior**:
- Continues monitoring with available data
- Logs errors to `logs/active_trade_supervisor.err.log`
- Graceful degradation for missing market data
- Emergency position closure on critical failures

**Dependencies**:
- PostgreSQL database
- PostgreSQL `live_data.btc_price_log`
- Trade Executor service
- Risk management configuration

**Startup Sequence**:
1. Load active trades from database
2. Initialize risk management rules
3. Start monitoring loop
4. Connect to PostgreSQL price feeds
5. Initialize alert system

**Shutdown Sequence**:
1. Save current monitoring state
2. Close database connections
3. Log final positions
4. Complete shutdown

**Failure Recovery**:
- Position state recovery from database
- Risk rule reinitialization
- Database reconnection
- Emergency stop procedures

**Data Sources**:
- **BTC Price:** PostgreSQL `live_data.btc_price_log` (migrated from SQLite)

---

## Watchdog Services

### 5. Symbol Price Watchdog BTC (`backend/symbol_price_watchdog_btc.py`)
**Purpose**: Monitors Bitcoin price and writes live data to PostgreSQL

**Inputs**:
- Coinbase API price data via WebSocket
- Historical price data from PostgreSQL

**Outputs**:
- Real-time price updates to PostgreSQL `live_data.btc_price_log`
- Live momentum and delta calculations to PostgreSQL
- Price alerts to other services

**Error Behavior**:
- Continues operation with cached data
- Logs errors to `logs/symbol_price_watchdog_btc.err.log`
- Automatic retry for API failures
- Fallback to last known price

**Dependencies**:
- Coinbase API WebSocket
- PostgreSQL `live_data.btc_price_log`
- Network connectivity

**Startup Sequence**:
1. Initialize PostgreSQL connection
2. Load historical price data
3. Start WebSocket connection
4. Initialize price update loop
5. Start momentum/delta calculations

**Shutdown Sequence**:
1. Save current price state
2. Close WebSocket connections
3. Complete database writes
4. Log shutdown completion

**Failure Recovery**:
- WebSocket reconnection with backoff
- Database recovery procedures
- Price interpolation for gaps
- Alert system for extended failures

**Data Sources**:
- **Live Data:** Coinbase WebSocket API
- **Storage:** PostgreSQL `live_data.btc_price_log`

---

### 6. Symbol Price Watchdog ETH (`backend/symbol_price_watchdog_eth.py`)
**Purpose**: Monitors Ethereum price and writes live data to PostgreSQL

**Inputs**:
- Coinbase API price data via WebSocket
- Historical price data from PostgreSQL

**Outputs**:
- Real-time price updates to PostgreSQL `live_data.eth_price_log`
- Live momentum and delta calculations to PostgreSQL
- Price alerts to other services

**Error Behavior**:
- Continues operation with cached data
- Logs errors to `logs/symbol_price_watchdog_eth.err.log`
- Automatic retry for API failures
- Fallback to last known price

**Dependencies**:
- Coinbase API WebSocket
- PostgreSQL `live_data.eth_price_log`
- Network connectivity

**Startup Sequence**:
1. Initialize PostgreSQL connection
2. Load historical price data
3. Start WebSocket connection
4. Initialize price update loop
5. Start momentum/delta calculations

**Shutdown Sequence**:
1. Save current price state
2. Close WebSocket connections
3. Complete database writes
4. Log shutdown completion

**Failure Recovery**:
- WebSocket reconnection with backoff
- Database recovery procedures
- Price interpolation for gaps
- Alert system for extended failures

**Data Sources**:
- **Live Data:** Coinbase WebSocket API
- **Storage:** PostgreSQL `live_data.eth_price_log`

---

### 7. Kalshi Account Sync (`backend/api/kalshi-api/kalshi_account_sync_ws.py`)
**Purpose**: Synchronizes account data with Kalshi API

**Inputs**:
- Kalshi WebSocket account updates
- REST API account queries

**Outputs**:
- Account balance updates to PostgreSQL database
- Position updates to Trade Manager
- Account alerts to frontend

**Error Behavior**:
- WebSocket reconnection on disconnects
- Logs errors to `logs/kalshi_account_sync.err.log`
- Continues with cached account data
- Alert system for authentication failures

**Dependencies**:
- Kalshi API credentials
- WebSocket connection
- PostgreSQL database

**Startup Sequence**:
1. Load Kalshi credentials
2. Initialize WebSocket connection
3. Authenticate with API
4. Start account monitoring
5. Initialize balance tracking

**Shutdown Sequence**:
1. Close WebSocket connection
2. Save account state
3. Complete database writes
4. Log shutdown completion

**Failure Recovery**:
- WebSocket reconnection logic
- API authentication retry
- Account state recovery
- Balance reconciliation

---

### 8. Kalshi API Watchdog (`backend/api/kalshi-api/kalshi_api_watchdog.py`)
**Purpose**: Monitors Kalshi API health and market data

**Inputs**:
- Kalshi REST API responses
- Market data from Kalshi

**Outputs**:
- API health status to system monitor
- Market snapshots to JSON files
- Heartbeat updates to logs

**Error Behavior**:
- Continues monitoring with degraded functionality
- Logs errors to `logs/kalshi_api_watchdog.err.log`
- Alert system for API failures
- Fallback to cached market data

**Dependencies**:
- Kalshi API access
- File system for snapshots
- System monitor integration

**Startup Sequence**:
1. Initialize API client
2. Start health monitoring loop
3. Initialize market data collection
4. Start heartbeat system
5. Load cached market data

**Shutdown Sequence**:
1. Save current market state
2. Complete snapshot writes
3. Close API connections
4. Log shutdown completion

**Failure Recovery**:
- API reconnection procedures
- Market data recovery
- Health status reset
- Alert system reset

---

### 9. Unified Production Coordinator (`backend/unified_production_coordinator.py`)
**Purpose**: Coordinates data production and generates strike table JSON

**Inputs**:
- Momentum and delta data from PostgreSQL `live_data.btc_price_log`
- Database queries for market data
- Frontend requests for strike table

**Outputs**:
- Strike table JSON to `backend/data/live_data/markets/kalshi/strike_tables/btc_strike_table.json`
- Live probabilities JSON
- System status reports

**Error Behavior**:
- Continues operation with available data
- Logs errors to `logs/unified_production_coordinator.err.log`
- Graceful degradation for missing services
- Alert system for critical failures

**Dependencies**:
- PostgreSQL `live_data.btc_price_log`
- PostgreSQL database
- File system for JSON outputs

**Startup Sequence**:
1. Initialize PostgreSQL connection
2. Start data coordination loop
3. Initialize JSON file monitoring
4. Load configuration
5. Start status monitoring

**Shutdown Sequence**:
1. Complete database operations
2. Save coordination state
3. Complete JSON file writes
4. Log shutdown completion

**Failure Recovery**:
- Database reconnection logic
- Data coordination recovery
- JSON file recovery
- Status monitoring reset

**Data Sources**:
- **Momentum/Delta:** PostgreSQL `live_data.btc_price_log` (direct from database, migrated from `live_data_analysis.py`)

---

### 10. Auto Entry Supervisor (`backend/auto_entry_supervisor.py`)
**Purpose**: Manages automated trade entries based on momentum signals

**Inputs**:
- Momentum data from PostgreSQL `live_data.btc_price_log`
- Trade signals from strategies
- Market conditions

**Outputs**:
- Automated trade entry signals
- Entry alerts to frontend
- Trade status updates

**Error Behavior**:
- Continues operation with available data
- Logs errors to `logs/auto_entry_supervisor.err.log`
- Graceful degradation for missing market data
- Disables auto-entry on critical failures

**Dependencies**:
- PostgreSQL `live_data.btc_price_log`
- Trade Manager service
- Risk management configuration

**Startup Sequence**:
1. Initialize PostgreSQL connection
2. Load momentum data
3. Start monitoring loop
4. Initialize trade signals
5. Start auto-entry logic

**Shutdown Sequence**:
1. Save current state
2. Close database connections
3. Log final status
4. Complete shutdown

**Failure Recovery**:
- Database reconnection
- Momentum data recovery
- Trade signal reset
- Auto-entry disable on critical failure

**Data Sources**:
- **Momentum Data:** PostgreSQL `live_data.btc_price_log` (migrated from `live_data_analysis.py`)

---

### 11. Cascading Failure Detector (`backend/cascading_failure_detector.py`)
**Purpose**: Monitors critical services for failures and triggers recovery

**Inputs**:
- Service health checks via HTTP endpoints
- Database connection status
- System resource monitoring

**Outputs**:
- Failure alerts and notifications
- Service restart commands
- System status reports

**Error Behavior**:
- Continues monitoring with available services
- Logs errors to `logs/cascading_failure_detector.err.log`
- Alert system for critical failures
- Automatic service restart on failures

**Dependencies**:
- All critical services
- PostgreSQL database
- Supervisor process management

**Startup Sequence**:
1. Initialize service monitoring
2. Start health check loop
3. Initialize alert system
4. Load critical service list
5. Start failure detection

**Shutdown Sequence**:
1. Save monitoring state
2. Close service connections
3. Log final status
4. Complete shutdown

**Failure Recovery**:
- Service reconnection logic
- Health check recovery
- Alert system reset
- Automatic restart procedures

**Critical Services Monitored**:
- `symbol_price_watchdog_btc` (replaced `btc_price_watchdog`)
- `symbol_price_watchdog_eth`
- `trade_manager`
- `trade_executor`
- `active_trade_supervisor`
- `unified_production_coordinator`

---

### 12. System Monitor (`backend/system_monitor.py`)
**Purpose**: Comprehensive system health monitoring with duplicate process detection and resource tracking

**Inputs**:
- Database connection status
- Service health checks via HTTP endpoints
- Performance metrics (CPU, memory, disk)
- Process monitoring via psutil
- System resource utilization

**Outputs**:
- Health status reports to PostgreSQL system.health_status table
- Performance alerts and notifications
- System status to frontend via API
- Duplicate process detection and termination
- SMS alerts for critical failures

**Error Behavior**:
- Continues monitoring with available data
- Logs errors to `logs/system_monitor.err.log`
- Alert system for critical failures
- Graceful degradation for missing services
- Automatic duplicate process cleanup

**Dependencies**:
- PostgreSQL database
- All system services
- SMS notification system
- Process monitoring tools

**Startup Sequence**:
1. Initialize database connection
2. Start service monitoring
3. Initialize resource tracking
4. Start duplicate process detection
5. Initialize alert system

**Shutdown Sequence**:
1. Save monitoring state
2. Close database connections
3. Complete health reports
4. Log shutdown completion

**Failure Recovery**:
- Database reconnection logic
- Service monitoring recovery
- Resource tracking reset
- Alert system recovery

**Monitored Services**:
- All 12 active services (updated from previous list)
- System resources (CPU, memory, disk)
- Database connectivity
- Network connectivity

---

## 🗂️ **Deprecated Services (Archived)**

### BTC Price Watchdog (`archive/deprecated_services/btc_price_watchdog.py`)
**Status**: DEPRECATED - Migrated to PostgreSQL
**Replacement**: `symbol_price_watchdog_btc` with PostgreSQL storage
**Migration Date**: Latest system update
**Reason**: Centralized data architecture with PostgreSQL

### Live Data Analysis (`archive/deprecated_services/live_data_analysis.py`)
**Status**: DEPRECATED - Functionality migrated to PostgreSQL
**Replacement**: Direct PostgreSQL queries for momentum/delta data
**Migration Date**: Latest system update
**Reason**: Redundant calculations, now using pre-calculated values from PostgreSQL

---

## 🔄 **Data Flow Architecture**

### **Current Data Flow**
1. **Coinbase WebSocket** → `symbol_price_watchdog_btc` → **PostgreSQL `live_data.btc_price_log`**
2. **PostgreSQL `live_data.btc_price_log`** → All services (direct queries)
3. **Kalshi API** → `kalshi_account_sync` → **PostgreSQL account tables**
4. **PostgreSQL** → `unified_production_coordinator` → **Strike table JSON files**

### **Legacy Data Flow (Deprecated)**
- ~~Coinbase API → `btc_price_watchdog` → SQLite `btc_price_history.db`~~
- ~~SQLite → `live_data_analysis.py` → Momentum calculations~~

### **Benefits of New Architecture**
- **Single Source of Truth**: PostgreSQL `live_data.btc_price_log`
- **Reduced Complexity**: No redundant calculations
- **Better Performance**: Direct database queries
- **Improved Consistency**: Centralized data storage
- **Easier Maintenance**: Single data source to manage
