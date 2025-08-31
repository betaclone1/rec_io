# REC.IO Documentation

## Overview
This directory contains comprehensive documentation for the REC.IO trading system, including architecture guides, deployment procedures, and operational documentation.

---

## 🔄 **RECENT MAJOR UPDATES (Latest)**

### **🛡️ Automatic Maintenance Protection Added**
- **✅ CRITICAL FIX:** Installation script now automatically disables Ubuntu's automatic maintenance services
- **✅ PROTECTED:** Prevents automatic deletion of virtual environment binaries and critical system files
- **✅ PRODUCTION SAFE:** Eliminates risk of automatic system maintenance causing trading system failures
- **✅ BUILT-IN:** All new installations are automatically protected from Digital Ocean's default cleanup operations

### **PostgreSQL Migration Complete**
- **✅ Migrated:** All BTC price data from legacy SQLite to PostgreSQL `live_data.live_price_log_1s_btc`
- **✅ Retired:** `btc_price_watchdog` service (archived to `archive/deprecated_services/`)
- **✅ Retired:** `live_data_analysis.py` module (archived to `archive/deprecated_services/`)
- **✅ Updated:** All services now read BTC price, momentum, and delta data directly from PostgreSQL
- **✅ Enhanced:** `symbol_price_watchdog_btc` now writes live BTC price, momentum, and delta values to PostgreSQL

### **System Architecture Updates**
- **Active Services:** 12 services running under supervisor
- **Data Architecture:** Centralized PostgreSQL `live_data` schema
- **Frontend Enhancements:** Panel styling for system restart modals with countdown timers

---

## 📚 **Documentation Index**

### **Core Documentation**
- **[VER3_ONBOARDING_DOCUMENTS/](VER3_ONBOARDING_DOCUMENTS/)** - Complete v2 system snapshot and onboarding package
- **[DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)** - Comprehensive deployment procedures
- **[AUTHENTICATION_GUIDE.md](AUTHENTICATION_GUIDE.md)** - Authentication and security setup
- **[README_FIREWALL.md](README_FIREWALL.md)** - Firewall configuration and network security
- **[AUTOMATIC_MAINTENANCE_PROTECTION.md](AUTOMATIC_MAINTENANCE_PROTECTION.md)** - Critical protection against automatic system maintenance failures

### **Migration & Architecture**
- **[POSTGRESQL_MIGRATION_PLAN.md](POSTGRESQL_MIGRATION_PLAN.md)** - PostgreSQL migration strategy (COMPLETED)
- **[POSTGRESQL_MIGRATION_ROADMAP_V7.md](POSTGRESQL_MIGRATION_ROADMAP_V7.md)** - Migration roadmap and timeline
- **[SYSTEM_CLEANUP_PLAN.md](SYSTEM_CLEANUP_PLAN.md)** - System cleanup and optimization
- **[PORTABILITY_AUDIT_REPORT.md](PORTABILITY_AUDIT_REPORT.md)** - System portability analysis

### **Database & Schema**
- **[BACKEND_SQLITE_MIGRATION_CHECKLIST.md](BACKEND_SQLITE_MIGRATION_CHECKLIST.md)** - SQLite migration checklist (COMPLETED)
- **[LEGACY_SQLITE_DEPRECATION_CHECKLIST.md](LEGACY_SQLITE_DEPRECATION_CHECKLIST.md)** - Legacy cleanup procedures
- **[SCHEMA_MAPPING_ANALYSIS.md](SCHEMA_MAPPING_ANALYSIS.md)** - Database schema analysis
- **[AUTO_ENTRY_SUPERVISOR_SQLITE_MIGRATION_CHECKLIST.md](AUTO_ENTRY_SUPERVISOR_SQLITE_MIGRATION_CHECKLIST.md)** - Auto entry migration (COMPLETED)

### **System Analysis & Audits**
- **[SYSTEM_AUDIT_REPORT_THIRD_PARTY_REVIEW.md](SYSTEM_AUDIT_REPORT_THIRD_PARTY_REVIEW.md)** - Third-party system audit
- **[BACKEND_SQLITE_MIGRATION_AUDIT_REPORT.md](BACKEND_SQLITE_MIGRATION_AUDIT_REPORT.md)** - Migration audit report

### **Future Planning**
- **[REDIS_INTEGRATION_PROPOSAL.md](REDIS_INTEGRATION_PROPOSAL.md)** - Redis integration strategy
- **[REAL_TIME_DATABASE_SUBSCRIPTION_PROPOSAL.md](REAL_TIME_DATABASE_SUBSCRIPTION_PROPOSAL.md)** - Real-time data proposals

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
- **Live Data Source:** `live_data.live_price_log_1s_btc` for BTC price, momentum, delta
- **Legacy Data:** Archived SQLite databases in `archive/` directory
- **Configuration:** Centralized port and path management via `MASTER_PORT_MANIFEST.json`

---

## 📂 **Directory Structure**

### **VER3_ONBOARDING_DOCUMENTS/**
- **v2_final_snapshot_20250127/** - Complete system snapshot
  - **01_Architecture_Map/** - System architecture and component documentation
  - **02_Config/** - Configuration files and port manifests
  - **03_Database_Schemas/** - Database schemas and migration plans
  - **04_Infrastructure/** - Deployment and infrastructure guides
  - **05_Security/** - Security policies and procedures
  - **06_Strategy_and_Product_Logic/** - Trading strategy and product documentation
  - **07_API_Contracts/** - API documentation and contracts

### **archive/**
- **deprecated_services/** - Archived services (`btc_price_watchdog`, `live_data_analysis.py`)
- **old_logs/** - Historical log files
- **old_scripts/** - Legacy scripts and utilities

---

## 🔧 **Quick Reference**

### **System Management**
- **Master Restart:** 45-second countdown with panel-styled confirmation modal
- **Service Monitoring:** Real-time health checks via `system_monitor`
- **Data Flow:** Coinbase WebSocket → PostgreSQL → All services

### **Data Sources**
- **BTC Price:** PostgreSQL `live_data.live_price_log_1s_btc`
- **ETH Price:** PostgreSQL `live_data.eth_price_log`
- **Trade Data:** PostgreSQL core tables
- **System Health:** PostgreSQL `system.health_status`

### **Configuration**
- **Ports:** `MASTER_PORT_MANIFEST.json`
- **Paths:** `config.json`
- **Environment:** `.env` files and supervisor configuration

---

## 🚨 **Critical Safety Notice**

> **NO AI AGENTS OR TEAM MEMBERS ARE PERMITTED TO PLACE LIVE TRADES FOR TESTING OR ANY OTHER PURPOSES.**  
> **NO AI AGENTS OR TEAM MEMBERS ARE PERMITTED TO ENABLE AUTOMATED TRADING FUNCTIONS FOR TESTING OR ANY OTHER PURPOSES.**  
> All testing must be performed in **read-only** or **simulation** modes only.

---

## 📝 **Documentation Maintenance**

### **Update Guidelines**
- All production changes must be reflected in relevant documentation
- Migration status should be updated in appropriate files
- New services should be documented in component documentation
- Port changes should be updated in `MASTER_PORT_MANIFEST.json`

### **Review Schedule**
- Quarterly review of all documentation by assigned owners
- All updates must be reviewed before merging to `main`
- Migration status updates as services are completed

---

## 🔗 **Related Resources**

- **Codebase:** `/backend/` - Main application code
- **Frontend:** `/frontend/` - Web interface and mobile apps
- **Scripts:** `/scripts/` - Deployment and utility scripts
- **Configuration:** `/config/` - System configuration files
