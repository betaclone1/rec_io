# POSTGRESQL MIGRATION ROADMAP — IMMEDIATE EXECUTION

**Purpose:** Final and Immediate Eradication of SQLite from REC.IO Trading System  
**Date:** June 13, 2024  
**Version:** 8.0  
**Status:** LIVE EXECUTION — MIGRATION IN PROGRESS  
**Directive:** THIS MIGRATION IS OCCURRING NOW. THERE IS NO PHASED ROLLOUT. ALL CHANGES ARE BEING IMPLEMENTED AND TESTED IN REAL TIME.  

---

## EXECUTIVE SUMMARY

This document is the authoritative directive for the live and immediate migration of the REC.IO trading system from SQLite to PostgreSQL. This is NOT a phased rollout — every component is being upgraded NOW under strict supervision, with live validation and logging in place. Every developer, process, and function must conform to PostgreSQL compatibility as of this moment. Any use of SQLite is a critical error and will be treated as a system failure.

**CRITICAL SUCCESS FACTORS:**
- Complete eradication of all SQLite imports, connections, and file references
- Zero fallback logic or dual-database handling
- Full integration with universal port/path management system
- Comprehensive testing with trade simulation only (NO LIVE TRADES)
- Real-time logging validation for all database interactions
- Absolutely **NO live trades** are to be placed during the testing or implementation phases. **Only the user may initiate live trades for testing purposes.**

---

## PHASE 1: PRE-MIGRATION AUDIT RESULTS

### 1.1 SQLite Dependencies Identified

#### Core Database Files (7 total):
1. **trades.db** - Trade history and execution records
2. **active_trades.db** - Currently monitored trades
3. **btc_price_history.db** - Bitcoin price time series data
4. **fills.db** - Trade fill records (prod/demo)
5. **orders.db** - Order history (prod/demo)
6. **settlements.db** - Settlement records (prod/demo)
7. **positions.db** - Current position tracking (prod/demo)

#### Affected Python Modules (12 total):
1. `backend/main.py` - Main application database queries
2. `backend/active_trade_supervisor.py` - Active trade monitoring
3. `backend/trade_manager.py` - Trade execution management
4. `backend/live_data_analysis.py` - Real-time data analysis
5. `backend/cascading_failure_detector.py` - System health monitoring
6. `backend/cascading_failure_detector_v2.py` - Enhanced failure detection
7. `backend/api/coinbase-api/coinbase-btc/btc_price_watchdog.py` - BTC price monitoring
8. `backend/api/kalshi-api/kalshi_account_sync_ws.py` - Account synchronization
9. `backend/api/kalshi-api/kalshi_account_sync_OLD.py` - Legacy account sync
10. `backend/api/kalshi-api/kalshi_historical_ingest.py` - Historical data ingestion
11. `backend/api/kalshi-api/kalshi_websocket_watchdog.py` - WebSocket monitoring
12. `backend/util/fingerprint_generator_directional.py` - Fingerprint generation

#### Critical Integration Points:
- **active_trade_supervisor ↔ trade_manager** - Previous migration failures
- **Universal port management system** - Must maintain compliance
- **Frontend database queries** - Real-time trade display
- **WebSocket data feeds** - Live market data
- **Authentication system** - User session management

### 1.2 Schema Analysis

#### Current SQLite Schemas:
```sql
-- trades.db
CREATE TABLE trades (
    id INTEGER PRIMARY KEY,
    trade_id TEXT,
    timestamp TEXT,
    symbol TEXT,
    side TEXT,
    quantity INTEGER,
    price REAL,
    status TEXT,
    ticket_id TEXT
);

-- active_trades.db
CREATE TABLE active_trades (
    id INTEGER PRIMARY KEY,
    trade_id INTEGER NOT NULL,
    ticket_id TEXT,
    symbol TEXT,
    side TEXT,
    quantity INTEGER,
    price REAL,
    status TEXT,
    created_at TEXT,
    updated_at TEXT
);

-- btc_price_history.db
CREATE TABLE price_log (
    id INTEGER PRIMARY KEY,
    timestamp TEXT,
    price REAL,
    volume REAL
);

-- fills.db, orders.db, settlements.db, positions.db
-- (Kalshi-specific schemas with varying structures)
```

### 1.3 Risk Assessment

#### HIGH RISK COMPONENTS:
1. **active_trade_supervisor.py** - Critical for trade monitoring
2. **trade_manager.py** - Core trade execution logic
3. **btc_price_watchdog.py** - Real-time price data
4. **kalshi_account_sync_ws.py** - Live account synchronization

**NOTE:** Previous migrations failed due to unresolved issues in the communication pipeline between `active_trade_supervisor.py` and `trade_manager.py`. These files must undergo enhanced scrutiny with extra logging and trace-level monitoring enabled during validation.

#### MEDIUM RISK COMPONENTS:
1. **main.py** - Frontend data queries
2. **live_data_analysis.py** - Historical analysis
3. **cascading_failure_detector.py** - System health

#### LOW RISK COMPONENTS:
1. **fingerprint_generator_directional.py** - Offline processing
2. **kalshi_historical_ingest.py** - Batch processing

---

### 1.4 Migration Clarification Summary (Project Manager Directives)

#### Database Configuration & Security
- PostgreSQL credentials will be **generated and stored securely** using the universal configuration system.
- PostgreSQL will run **locally** on the same machine for now. Future containerization will be handled in a separate deployment phase.

#### Migration Timing & System Downtime
- **System may be offline during core migration phases.** Downtime during **IMMEDIATE** migration is acceptable, but should be minimized (<4 hours per sub-phase).
- **No dual-write system is required**. We will accept temporary offline mode during critical phases.
- A **data archiving/cleanup pass is approved** for:
  - `btc_price_history.db` — retain only last 12 months.
  - `fills.db`, `orders.db`, `settlements.db` — retain only most recent 6 months unless user manually whitelists older records.

#### Communication Rewrite
- `active_trade_supervisor ↔ trade_manager` must be **partially refactored**. Maintain current structure but:
  - Replace brittle inter-process calls with resilient message-passing or shared memory access.
  - Log all inputs, outputs, and error traces during simulation.

#### Simulation Environment
- Implement a **full trade simulation environment**, including order queue, balance mirroring, and system state snapshotting.
- **All live trade execution codepaths must be disabled** during testing unless explicitly triggered by the user.
- **Simulation fidelity must replicate order latency and feed timing** to within 100ms.

#### Performance Benchmarks
- <100ms query latency must be measured under both **normal and peak** simulated load.
- Benchmarks apply to:
  - Price polling
  - Trade record insertion
  - Active trade lookups

#### Resource Allocation
- 240 hours is acceptable if developer focus is full-time. Otherwise:
  - Timeline extended to **IMMEDIATE** execution.
  - Buffer added to **NOW**.
  - Optional: One additional developer during **NOW** if possible.

#### Port and Path Management
- PostgreSQL default port `5432` will be added to the **universal port manifest**.
- All database connection strings will be routed through the **universal path config**.

#### Migration Strategy
- Custom migration scripts are **preferred** over generic tools.
- Validation will follow **row-by-row checks** for `trades`, `active_trades`, and `price_log`; **checksum validation** for all others.

#### Rollback Triggers
- Rollback if any of the following occur:
  - >10% performance degradation vs. baseline
  - Integrity checks fail on any core table
  - Trade simulation fails validation
  - Manual halt from user

#### Documentation & Training
- No user-facing training needed.
- A new **PostgreSQL Ops Runbook** will be created for maintenance and troubleshooting.

#### Post-Migration Monitoring
- Enhanced monitoring will continue **for 4 weeks** post-cutover.
- Alert on:
  - Query latency >200ms (avg)
  - Connection pool saturation >85%
  - Unacknowledged inserts or write lag

These directives must be reflected in each relevant roadmap phase before implementation begins.

---

## PHASE 2: MIGRATION STRATEGY

### 2.1 PostgreSQL Infrastructure Setup

#### Database Configuration:
```sql
-- PostgreSQL Database Creation
CREATE DATABASE rec_trading_system;
CREATE USER rec_trading_user WITH PASSWORD 'secure_password';
GRANT ALL PRIVILEGES ON DATABASE rec_trading_system TO rec_trading_user;

-- Connection Pool Configuration
-- Max connections: 50
-- Pool timeout: 30 seconds
-- Connection lifetime: 1 hour
```

#### Schema Migration:
```sql
-- PostgreSQL Schema (PostgreSQL-compatible)
CREATE TABLE trades (
    id SERIAL PRIMARY KEY,
    trade_id VARCHAR(255),
    timestamp TIMESTAMP WITH TIME ZONE,
    symbol VARCHAR(50),
    side VARCHAR(10),
    quantity INTEGER,
    price DECIMAL(10,2),
    status VARCHAR(20),
    ticket_id VARCHAR(255)
);

CREATE TABLE active_trades (
    id SERIAL PRIMARY KEY,
    trade_id INTEGER NOT NULL,
    ticket_id VARCHAR(255),
    symbol VARCHAR(50),
    side VARCHAR(10),
    quantity INTEGER,
    price DECIMAL(10,2),
    status VARCHAR(20),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE price_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE,
    price DECIMAL(10,2),
    volume DECIMAL(15,2)
);

-- Indexes for performance
CREATE INDEX idx_trades_timestamp ON trades(timestamp);
CREATE INDEX idx_trades_status ON trades(status);
CREATE INDEX idx_active_trades_trade_id ON active_trades(trade_id);
CREATE INDEX idx_price_log_timestamp ON price_log(timestamp);
```

### 2.2 Database Connection Layer

#### New PostgreSQL Connection Manager:
```python
# backend/core/database.py
import psycopg2
import psycopg2.pool
from contextlib import contextmanager
from typing import Generator
import logging

class PostgreSQLManager:
    def __init__(self):
        self.pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=5,
            maxconn=50,
            host='localhost',
            database='rec_trading_system',
            user='rec_trading_user',
            password='secure_password',
            port=5432
        )
        self.logger = logging.getLogger(__name__)
    
    @contextmanager
    def get_connection(self) -> Generator[psycopg2.extensions.connection, None, None]:
        conn = self.pool.getconn()
        try:
            yield conn
        except Exception as e:
            conn.rollback()
            self.logger.error(f"Database error: {e}")
            raise
        finally:
            self.pool.putconn(conn)
    
    def execute_query(self, query: str, params: tuple = None) -> list:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                return cursor.fetchall()
    
    def execute_transaction(self, queries: list) -> bool:
        with self.get_connection() as conn:
            try:
                with conn.cursor() as cursor:
                    for query, params in queries:
                        cursor.execute(query, params)
                conn.commit()
                return True
            except Exception as e:
                conn.rollback()
                self.logger.error(f"Transaction failed: {e}")
                return False
```

### 2.3 Data Migration Strategy

#### Migration Scripts:
1. **Schema Migration** - Create PostgreSQL tables
2. **Data Export** - Export SQLite data to CSV/JSON
3. **Data Import** - Import data into PostgreSQL
4. **Validation** - Verify data integrity
5. **Cleanup** - Remove SQLite files

#### Migration Validation:
```python
# Migration validation script
def validate_migration():
    """Validate that all data migrated correctly"""
    checks = [
        ("trades", "SELECT COUNT(*) FROM trades"),
        ("active_trades", "SELECT COUNT(*) FROM active_trades"),
        ("price_log", "SELECT COUNT(*) FROM price_log"),
        # Add all other tables
    ]
    
    for table_name, query in checks:
        count = execute_query(query)
        print(f"{table_name}: {count} records")
```

---

## LIVE IMPLEMENTATION TRACKING

### NOW: Infrastructure Setup
**Estimated Time:** 2 hours
**Risk Level:** LOW

#### Tasks:
- [ ] Install PostgreSQL server
- [ ] Configure database user and permissions
- [ ] Create database schemas
- [ ] Set up connection pooling
- [ ] Implement database manager class
- [ ] Create migration validation scripts
- [ ] Set up logging for database operations

#### Deliverables:
- PostgreSQL server running
- Database schemas created
- Connection manager implemented
- Migration scripts ready

### NOW: Core Migration
**Estimated Time:** 3 hours
**Risk Level:** HIGH

#### Tasks:
- [ ] Migrate trades.db to PostgreSQL
- [ ] Migrate active_trades.db to PostgreSQL
- [ ] Migrate btc_price_history.db to PostgreSQL
- [ ] Update active_trade_supervisor.py
- [ ] Update trade_manager.py
- [ ] Validate core functionality
- [ ] Test trade simulation

#### Deliverables:
- Core databases migrated
- Core services updated
- Trade simulation working

### NOW: Kalshi Integration Migration
**Estimated Time:** 3 hours
**Risk Level:** HIGH

#### Tasks:
- [ ] Migrate fills.db to PostgreSQL
- [ ] Migrate orders.db to PostgreSQL
- [ ] Migrate settlements.db to PostgreSQL
- [ ] Migrate positions.db to PostgreSQL
- [ ] Update kalshi_account_sync_ws.py
- [ ] Update kalshi_historical_ingest.py
- [ ] Update kalshi_websocket_watchdog.py
- [ ] Validate account synchronization

#### Deliverables:
- Kalshi databases migrated
- Account sync working
- WebSocket feeds functional

### NOW: Frontend/API Integration
**Estimated Time:** 2 hours
**Risk Level:** MEDIUM

#### Tasks:
- [ ] Update main.py database queries
- [ ] Update live_data_analysis.py
- [ ] Update cascading_failure_detector.py
- [ ] Update btc_price_watchdog.py
- [ ] Update fingerprint_generator_directional.py
- [ ] Test frontend data display
- [ ] Validate real-time updates

#### Deliverables:
- Frontend queries updated
- Real-time data working
- All APIs functional

### NOW: Testing/Validation
**Estimated Time:** 2 hours
**Risk Level:** MEDIUM

#### Tasks:
- [ ] Comprehensive integration testing
- [ ] Performance testing under load
- [ ] Stress testing database connections
- [ ] Validate all system components
- [ ] Test rollback procedures
- [ ] Final data integrity checks

#### Deliverables:
- System fully tested
- Performance validated
- Rollback procedures ready

### NOW: Cleanup/Documentation
**Estimated Time:** 1 hour
**Risk Level:** LOW

#### Tasks:
- [ ] Remove all SQLite files
- [ ] Remove SQLite imports
- [ ] Update documentation
- [ ] Create migration guide
- [ ] Final system audit
- [ ] Performance optimization

#### Deliverables:
- Zero SQLite dependencies
- Complete documentation
- Optimized system

---

## PHASE 4: CRITICAL SUCCESS FACTORS

### 4.1 Protocol Compliance
- [ ] All database connections use universal port system
- [ ] All file paths use universal path system
- [ ] No hardcoded database paths
- [ ] No hardcoded connection strings

### 4.2 Testing Requirements
- [ ] **Trade simulation only — absolutely NO live trades may be executed by the system under any circumstances during testing. ONLY the user may place live trades during this phase.**
- [ ] Comprehensive unit tests for all database operations
- [ ] Integration tests for all system components
- [ ] Performance tests under realistic load
- [ ] Stress tests for connection pooling

### 4.3 Validation Checklist
- [ ] All SQLite imports removed
- [ ] All .db files removed
- [ ] All database queries updated for PostgreSQL
- [ ] All connection strings updated
- [ ] All error handling updated
- [ ] All logging updated
- [ ] All tests passing
- [ ] Performance benchmarks met

### 4.4 Rollback Protocol
```bash
# Emergency rollback procedure
1. Stop all services
2. Restore SQLite files from backup
3. Revert code changes
4. Restart services
5. Validate system functionality
6. Document rollback reason
```

---

## PHASE 5: RISK MITIGATION

### 5.1 High-Risk Mitigation
- **active_trade_supervisor ↔ trade_manager communication**
  - Implement comprehensive testing
  - Add real-time monitoring
  - Create fallback procedures
  - **This connection must be isolated, monitored, and rigorously tested with scenario-based inputs. Log all function calls, inputs, and outputs during test runs.**

- **Real-time data feeds**
  - Implement connection pooling
  - Add retry logic
  - Monitor performance metrics

- **Data integrity**
  - Implement transaction logging
  - Add data validation checks
  - Create backup procedures

### 5.2 Performance Considerations
- **Connection pooling** - Prevent connection exhaustion
- **Query optimization** - Ensure fast response times
- **Indexing strategy** - Optimize for common queries
- **Caching layer** - Reduce database load

### 5.3 Monitoring and Alerting
- **Database performance monitoring**
- **Connection pool monitoring**
- **Query performance tracking**
- **Error rate monitoring**
- **System health checks**

---

## PHASE 6: POST-MIGRATION VERIFICATION

### 6.1 Final Audit Checklist
- [ ] No `import sqlite3` statements in codebase
- [ ] No `.db` file references
- [ ] No SQLite-specific SQL syntax
- [ ] All database connections use PostgreSQL
- [ ] All tests passing
- [ ] Performance benchmarks met
- [ ] Documentation updated
- [ ] Migration guide created

### 6.2 Performance Benchmarks
- **Query response time** < 100ms for common queries
- **Connection pool utilization** < 80%
- **Database size** optimized and monitored
- **Backup procedures** tested and documented

### 6.3 Documentation Requirements
- **Migration guide** for future reference
- **Database schema documentation**
- **Connection management guide**
- **Troubleshooting procedures**
- **Performance tuning guide**

---


## LIVE EXECUTION TIMELINE

This migration is already underway. All phases must be executed in sequence with live validation at each step. Estimated time per step is provided as a guideline for tracking purposes only — there is no scheduled delay or staging.

| Phase                          | Status         | Est. Time | Risk Level |
|-------------------------------|----------------|-----------|------------|
| Infrastructure Setup          | IN PROGRESS    | 2 hours   | LOW        |
| Core Migration                | PENDING        | 3 hours   | HIGH       |
| Kalshi Integration Migration  | PENDING        | 3 hours   | HIGH       |
| Frontend/API Integration      | PENDING        | 2 hours   | MEDIUM     |
| Testing/Validation            | PENDING        | 2 hours   | MEDIUM     |
| Cleanup/Documentation         | FINAL STAGE    | 1 hour    | LOW        |

---

## SUCCESS CRITERIA

### 6.1 Technical Success
- [ ] Zero SQLite dependencies in codebase
- [ ] All database operations use PostgreSQL
- [ ] Performance meets or exceeds SQLite baseline
- [ ] All system components functional
- [ ] No data loss during migration

### 6.2 Operational Success
- [ ] Trade simulation working correctly
- [ ] Real-time data feeds functional
- [ ] Account synchronization working
- [ ] Frontend displays accurate data
- [ ] System monitoring operational

### 6.3 Compliance Success
- [ ] Universal port system compliance
- [ ] Universal path system compliance
- [ ] No hardcoded values
- [ ] Proper error handling
- [ ] Comprehensive logging

---

## CONCLUSION

This migration is being executed live and without delay. Every developer and system component must operate under the assumption that PostgreSQL is now the authoritative database system. All testing, validation, and cleanup is occurring in real time. SQLite is no longer supported or acceptable anywhere in the system.

---

**Document Version:** 8.0  
**Last Updated:** June 13, 2024  
**Next Review:** Upon migration completion confirmation