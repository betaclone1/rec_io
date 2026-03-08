# REC.IO v2 – Final Snapshot & Onboarding Package

## Purpose
This package contains the complete v2 system snapshot from the system architect and all BMAD onboarding documentation. It is the **single source of truth** for understanding, operating, and supporting REC.IO v2 prior to the launch of v3.

> **🚨 CRITICAL SAFETY NOTICE:**  
> **NO AI AGENTS OR TEAM MEMBERS ARE PERMITTED TO PLACE LIVE TRADES FOR TESTING OR ANY OTHER PURPOSES.**  
> **NO AI AGENTS OR TEAM MEMBERS ARE PERMITTED TO ENABLE AUTOMATED TRADING FUNCTIONS FOR TESTING OR ANY OTHER PURPOSES.**  
> All testing must be performed in **read-only** or **simulation** modes only.

---

## 🔄 **RECENT MAJOR SYSTEM UPDATES (Latest)**

### **PostgreSQL Migration Complete**
- **✅ Migrated:** All BTC price data from legacy SQLite to PostgreSQL `live_data.btc_price_log`
- **✅ Retired:** `btc_price_watchdog` service (archived to `archive/deprecated_services/`)
- **✅ Retired:** `live_data_analysis.py` module (archived to `archive/deprecated_services/`)
- **✅ Updated:** All services now read BTC price, momentum, and delta data directly from PostgreSQL
- **✅ Enhanced:** `symbol_price_watchdog_btc` now writes live BTC price, momentum, and delta values to PostgreSQL

### **Data Flow Simplification**
- **Before:** Multiple services reading from legacy SQLite `btc_price_history.db`
- **After:** Centralized PostgreSQL `live_data.btc_price_log` as single source of truth
- **Benefits:** Improved data consistency, reduced complexity, better performance

### **Service Architecture Updates**
- **Active Services:** 12 services running under supervisor
- **Deprecated Services:** `btc_price_watchdog`, `live_data_analysis.py`
- **New Data Source:** PostgreSQL `live_data` schema for all live market data

---

## 📂 Folder Structure & Documentation Index

### 01_Architecture_Map/
- `notes.md` – Architect's raw v2 architecture notes
- `System_Overview.md` – High-level architecture & service flow
- `Component_Level_Documentation.md` – Detailed per-service description with purpose, inputs/outputs, error behavior, dependencies, startup/shutdown sequence, and failure recovery steps
- `Frontend_Enhancements_Documentation.md` – Comprehensive frontend interface documentation including desktop/mobile interfaces, system monitoring, and admin controls
- `v2_current_architecture.png` – Current architecture diagram (to be created)
- `v3_target_architecture.png` – Target v3 architecture diagram (to be created)
- `v2_data_flow.png` – Data flow diagram (to be created)

### 02_Config/
- `MASTER_PORT_MANIFEST.json` – Canonical port assignments
- `config.json` – Global paths & settings
- `Port_and_Path_Configuration_Reference.md` – Human-readable reference for ports/paths/env

### 03_Database_Schemas/
- `postgresql_schema.sql` – Live DB schema
- `Database_Schema_and_Migration_Plan.md` – PostgreSQL migration plan & legacy cleanup steps

### 04_Infrastructure/
- `Deployment_Playbook.md` – Deploy/rollback procedures
- `CI_CD_and_Container_Guide.md` – Local-first → DigitalOcean pipeline
- `DigitalOcean_Deployment_Guide.md` – Complete DigitalOcean deployment guide with environment setup, deployment procedures, rollback mechanisms, and maintenance
- `Performance_Baselines.md` – Current v2 performance metrics, v3 targets, monitoring setup, and alert thresholds
- `POSTGRESQL_MIGRATION_PERFORMANCE_AUDIT.md` – Comprehensive performance audit comparing pre/post PostgreSQL migration with 97% CPU reduction and 70% memory improvement
- `supervisor/*.conf` – Process management configs

### 05_Security/
- `Secrets_Management_Policy.md` – Secrets handling & rotation procedures
- `Disaster_Recovery_Plan.md` – Recovery steps for DB/service/API/deploy failures

### 06_Strategy_and_Product_Logic/
- `Trade_Strategy_Book.md` – HOURLY HTC strategy & v3 multi-strategy vision
- `Feature_Roadmap.md` – Development priorities
- `Known_Issues_and_Design_Constraints.md` – Technical debt & brittle areas
- `Partner_Onboarding_Guide.md` – New team/stakeholder onboarding procedures

### 07_API_Contracts/
- `Kalshi_REST_and_WebSocket.md` – Complete Kalshi API contract with endpoints, authentication, examples, error codes, and retry logic
- `Coinbase_Symbol_Feed.md` – Comprehensive Coinbase API contract for symbol feed integration
- `Third_Party_Services.md` – Additional third-party services API contracts and integration patterns

---

### Root Files
- `Ownership_Assignment_and_AI_Prompt_Index.md` – Document owners & approved AI prompts
- `README.md` – This index

---

## 🏗️ **Current System Architecture**

### **Active Services (12 total)**
1. **main_app** (port 3000) - Primary web application
2. **trade_manager** (port 4000) - Core trade lifecycle management
3. **trade_executor** (port 5000) - Trade execution engine
4. **active_trade_supervisor** (port 8007) - Active trade monitoring
5. **auto_entry_supervisor** (port 8008) - Automated trade entry
6. **cascading_failure_detector** (port 8009) - System health monitoring
7. **unified_production_coordinator** (port 8010) - Data production coordination
8. **system_monitor** (port 8011) - System monitoring dashboard
9. **kalshi_account_sync** (port 8012) - Kalshi account synchronization
10. **kalshi_api_watchdog** (port 8013) - Kalshi API monitoring
11. **symbol_price_watchdog_btc** (port 8014) - BTC price monitoring
12. **symbol_price_watchdog_eth** (port 8015) - ETH price monitoring

### **Data Architecture**
- **Primary Database:** PostgreSQL with `live_data` schema
- **Live Data Source:** `live_data.btc_price_log` for BTC price, momentum, delta
- **Legacy Data:** Archived SQLite databases in `archive/` directory
- **Configuration:** Centralized port and path management via `MASTER_PORT_MANIFEST.json`

---

## Usage Guidelines
- **Reference First** – All production actions should be guided by these docs
- **Review Before Change** – Any code/config change must be reflected in relevant doc
- **Follow Safety Rules** – Absolutely no AI/agent live trade execution or automation enabling for testing
- **PostgreSQL First** – All new data operations should use PostgreSQL, not legacy SQLite

---

## Review & Maintenance
- Owners are responsible for quarterly review of their assigned docs
- All updates must be reviewed by Eric before merging to `main`
- **Migration Status:** PostgreSQL migration complete, legacy cleanup ongoing
