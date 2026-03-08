# System Overview – REC.IO Trading Platform v2 (Final Production Snapshot)

## 1. Purpose
This document provides a high-level overview of the REC.IO v2 trading system architecture, its components, data flows, and deployment setup. It is intended as an onboarding reference for BMAD agents and technical staff preparing for v3 development.

---

## 2. Core Architecture

### 2.1 Service Layer
- **Main Application (Port 3000)** – Web interface + API gateway with enhanced system monitoring.
- **Trade Manager (Port 4000)** – Creates/updates trade records, manages lifecycle.
- **Trade Executor (Port 8001)** – Sends orders to Kalshi API.
- **Active Trade Supervisor (Port 8007)** – Monitors open trades in real time.
- **Auto Entry Supervisor (Port 8009)** – Generates entry signals and trade recommendations.

### 2.2 Watchdog Services
- **BTC Price Watchdog (Port 8002)** – Tracks BTC price & momentum.
- **Symbol Price Watchdog BTC (Port 8006)** – Monitors BTC symbol prices.
- **Symbol Price Watchdog ETH (Port 8008)** – Monitors ETH symbol prices.
- **Kalshi Account Sync (Port 8004)** – Syncs account positions/balances.
- **Kalshi API Watchdog (Port 8005)** – Monitors API health and pulls market data.
- **Unified Production Coordinator (Port 8010)** – Oversees data production & sync.
- **Cascading Failure Detector (Port 8011)** – Detects and prevents cascading service failures.
- **System Monitor (Port 8012)** – Comprehensive system health monitoring with duplicate process detection.

### 2.3 Frontend Layer
- **Desktop Interface** (`frontend/tabs/`) – Full-featured web interface with system monitoring.
- **Mobile Interface** (`frontend/mobile/`) – Responsive mobile-optimized interface.
- **Real-time Updates** – WebSocket-based live data streaming.
- **System Health Dashboard** – Real-time system status and resource monitoring.
- **Admin Controls** – Supervisor management and terminal access.

### 2.4 Data Layer
- **PostgreSQL** – Centralized store for trades, positions, market data, system health.
- **SQLite** – Local caches for price history & trade monitoring.
- **File Storage** – JSON snapshots & historical archives.

---

## 3. Service & Data Flow

### 3.1 Trade Execution
1. Auto Entry Supervisor signals trade.
2. Trade Manager records trade in PostgreSQL.
3. Trade Executor sends order to Kalshi API.
4. Active Trade Supervisor monitors execution status.
5. System waits for expiry & settlement.

### 3.2 Data Flow
1. Kalshi API Watchdog → market data.
2. BTC/ETH Price Watchdogs → live crypto prices.
3. Kalshi Account Sync → positions & balances.
4. System Monitor → health metrics & duplicate process detection.
5. All writes → PostgreSQL.
6. WebSockets push → frontend (desktop & mobile).

### 3.3 System Monitoring Flow
1. System Monitor → health checks every 15 seconds.
2. Cascading Failure Detector → service dependency monitoring.
3. Health data → PostgreSQL system.health_status table.
4. Frontend → real-time health display with dynamic icons.
5. Admin controls → supervisor management & terminal access.

---

## 4. Port Management
- Centralized via `MASTER_PORT_MANIFEST.json`.
- Dynamic retrieval ensures no hardcoding.
- Ports consistent across environments.

Core Ports:
```
main_app: 3000
trade_manager: 4000
trade_executor: 8001
active_trade_supervisor: 8007
auto_entry_supervisor: 8009
btc_price_watchdog: 8002
symbol_price_watchdog_btc: 8006
symbol_price_watchdog_eth: 8008
kalshi_account_sync: 8004
kalshi_api_watchdog: 8005
unified_production_coordinator: 8010
cascading_failure_detector: 8011
system_monitor: 8012
```

---

## 5. Process Management
- All services run under **supervisord**.
- Auto-restart on failure.
- Centralized logging + rotation.
- Environment variables applied globally.
- **Enhanced monitoring**: System Monitor detects duplicate processes outside supervisor.
- **Admin interface**: Web-based supervisor control with individual script management.

---

## 6. Frontend Enhancements

### 6.1 Desktop Interface
- **System Status Panel**: Real-time health monitoring with resource usage.
- **Admin Controls**: Supervisor management, terminal access, system restart.
- **Enhanced Resource Display**: CPU, memory, disk usage with progress bars.
- **Dynamic System Icons**: Status-based icon updates in navigation.
- **Script Management**: Individual restart/log access for all supervisor processes.

### 6.2 Mobile Interface
- **Responsive Design**: Optimized for mobile devices.
- **Simplified System Panel**: Essential monitoring without complex controls.
- **Touch-friendly Interface**: Optimized for mobile interaction.
- **Real-time Updates**: Live data streaming to mobile devices.

### 6.3 Authentication & Security
- **User-based Access Control**: Role-based permissions (master_admin, user).
- **Secure Credential Storage**: User-specific credential directories.
- **Session Management**: Secure login/logout functionality.

---

## 7. Current Deployment State
- Local PostgreSQL primary DB (95% migrated from SQLite).
- Fully centralized port & path management.
- Secure authentication implemented.
- Enhanced system monitoring with duplicate process detection.
- Desktop and mobile frontend interfaces.
- Local + cloud-ready deployment.

---

## 8. Technical Debt & Limitations
- Some legacy scripts remain in config.
- A few hardcoded env-specific values.
- Certain services require file existence.
- Error handling inconsistent.
- Redis caching planned for v3.

---

## 9. v3 Migration Path
- Redis for caching/pub-sub.
- Containerized microservices.
- Central API gateway.
- Advanced monitoring & alerting.
- Keep PostgreSQL schema and stable APIs.
- Enhanced mobile experience.
- Advanced system monitoring dashboard.
