# PRE-POSTGRESQL-DATA-PRODUCTION SYSTEM PERFORMANCE AUDIT

**Date:** August 12, 2025  
**System State:** CSV-based fingerprint data with PostgreSQL probability calculator  
**Audit Purpose:** Baseline performance metrics before migrating to PostgreSQL-based data production

## EXECUTIVE SUMMARY

This document establishes baseline performance metrics for the current production system that uses CSV files for fingerprint data storage and calculation. The system consists of three critical components running in a second-by-second production cycle:

1. **unified_production_coordinator.py** - Main production pipeline (36.6% CPU, 170MB RAM)
2. **active_trade_supervisor.py** - Trade monitoring (0.5% CPU, 50MB RAM)  
3. **probability_calculator.py** - CSV-based probability calculations (integrated into UPC)

## SYSTEM ARCHITECTURE OVERVIEW

### Current Data Flow
```
CSV Fingerprint Files → Probability Calculator → btc_live_probabilities.json → Multiple Consumers
                                                      ↓
                                    ┌─────────────────┼─────────────────┐
                                    ↓                 ↓                 ↓
                            UPC Strike Table    Active Trade      Frontend API
                            Generation         Monitoring         Endpoints
```

### Key Components
- **Data Source:** 64 CSV fingerprint files (1.7MB total, ~25KB each)
- **Calculation Engine:** CSV-based probability calculator with scipy.interpolate.griddata
- **Output:** JSON files written every second
- **Consumers:** UPC, active_trade_supervisor, frontend APIs

## DETAILED PERFORMANCE METRICS

### 1. PROCESS RESOURCE USAGE

#### unified_production_coordinator.py (PID: 80225)
- **CPU Usage:** 36.6% (high sustained load)
- **Memory Usage:** 170MB RSS (170,608 KB)
- **Virtual Memory:** 411MB VSZ
- **Runtime:** 6 minutes 24 seconds
- **Status:** Active, running 1-second cycles

#### active_trade_supervisor.py (PID: 78660)
- **CPU Usage:** 0.5% (low load, no active trades)
- **Memory Usage:** 50MB RSS (49,936 KB)
- **Virtual Memory:** 411MB VSZ
- **Runtime:** 23 seconds
- **Status:** Active, monitoring loop running

### 2. SYSTEM-LEVEL METRICS

#### CPU Performance
- **Load Average:** 3.96, 4.48, 4.90 (1m, 5m, 15m)
- **CPU Utilization:** 14.87% user, 16.56% sys, 68.56% idle
- **Total System Load:** High (4.9 load on 10-core system)

#### Memory Performance
- **Physical Memory:** 47GB used, 16GB unused
- **Virtual Memory:** 443TB vsize, 5709MB framework vsize
- **Memory Pressure:** Low (no swap activity)
- **Page Activity:** 40.4B translation faults, 1.3B copy-on-write

#### Disk I/O Performance
- **Disk Throughput:** 6.43 MB/s read, variable write activity
- **I/O Operations:** 429 tps (transactions per second)
- **Storage:** No significant I/O bottlenecks detected

### 3. DATA STORAGE METRICS

#### CSV Fingerprint Data
- **Total Size:** 1.7MB across 64 files
- **File Count:** 64 CSV files (baseline + 63 momentum buckets)
- **Average File Size:** ~25KB per file
- **Storage Location:** `backend/data/historical_data/btc_historical/symbol_fingerprints/`

#### PostgreSQL Fingerprint Data (New)
- **Table Count:** 125 fingerprint tables in analytics schema
- **Baseline Table Size:** 88KB (60 rows)
- **Total Storage:** ~11MB estimated (125 tables × 88KB average)

#### JSON Output Files
- **btc_live_probabilities.json:** 5.6KB, 242 lines
- **btc_strike_table.json:** 6.9KB
- **Update Frequency:** Every second
- **File I/O:** Atomic writes with temporary files

### 4. COMPUTATIONAL COMPLEXITY

#### Probability Calculation Operations
- **Interpolation Method:** scipy.interpolate.griddata with 'nearest' method
- **Data Points:** 60 TTC values × 120 percentage points = 7,200 interpolation points
- **Strike Calculations:** 21 strikes per cycle (10 above + 10 below + current)
- **Momentum Buckets:** 63 momentum-based fingerprints for hot-swapping
- **Calculation Frequency:** Every 1 second

#### Memory Access Patterns
- **CSV Loading:** All 64 files loaded into memory at startup
- **Hot-Swapping:** Momentum fingerprint switching based on current momentum score
- **Interpolation Cache:** Grid data cached in memory for each fingerprint
- **JSON Serialization:** Full data structure serialized every second

### 5. NETWORK AND API PERFORMANCE

#### Internal API Calls
- **Kalshi Market Data:** HTTP requests to Kalshi API
- **BTC Price Data:** External price feed integration
- **Database Queries:** PostgreSQL connections for momentum data
- **File System:** Local JSON file reads/writes

#### External Dependencies
- **Kalshi API:** Market snapshot data
- **Price Feeds:** Real-time BTC price data
- **PostgreSQL:** Momentum analysis data
- **File System:** CSV fingerprint storage

## PERFORMANCE BOTTLENECKS IDENTIFIED

### 1. High CPU Usage in UPC
- **Issue:** 36.6% CPU usage indicates computational intensity
- **Root Cause:** scipy.interpolate.griddata operations every second
- **Impact:** May limit scalability on lower-powered systems

### 2. File I/O Operations
- **Issue:** Multiple JSON file writes per second
- **Root Cause:** Atomic file operations for data consistency
- **Impact:** Potential I/O bottlenecks under high load

### 3. Memory Footprint
- **Issue:** 170MB RAM usage for UPC process
- **Root Cause:** All CSV fingerprints loaded into memory
- **Impact:** Memory pressure on resource-constrained systems

### 4. Data Redundancy
- **Issue:** CSV files duplicated in PostgreSQL
- **Root Cause:** Migration in progress, both systems active
- **Impact:** Storage inefficiency and maintenance overhead

## SCALABILITY ANALYSIS

### Current System Limits
- **CPU Bound:** UPC process consuming significant CPU resources
- **Memory Bound:** Large memory footprint for fingerprint data
- **I/O Bound:** Frequent file system operations
- **Network Bound:** External API dependencies

### Bottleneck Thresholds
- **CPU:** 36.6% usage suggests approaching limits on 2-core systems
- **Memory:** 170MB per process may be excessive for cloud deployments
- **I/O:** File operations may become bottleneck under high concurrency
- **Network:** External API rate limits may impact reliability

## MIGRATION OPPORTUNITIES

### 1. PostgreSQL Data Production
- **Current State:** CSV files generated from raw data, loaded into PostgreSQL
- **Target State:** Direct PostgreSQL table generation from raw data
- **Benefits:** Eliminate CSV file I/O, reduce memory footprint

### 2. Database-Optimized Calculations
- **Current State:** Python-based interpolation with scipy
- **Target State:** PostgreSQL-based calculations or optimized Python
- **Benefits:** Reduce CPU usage, improve scalability

### 3. Caching Optimization
- **Current State:** Full fingerprint data loaded in memory
- **Target State:** Intelligent caching with database backing
- **Benefits:** Reduce memory footprint, improve startup time

### 4. Batch Processing
- **Current State:** Real-time calculations every second
- **Target State:** Optimized batch processing with caching
- **Benefits:** Reduce computational overhead

## RECOMMENDATIONS FOR POSTGRESQL MIGRATION

### Phase 1: Data Migration
1. Complete PostgreSQL fingerprint table generation
2. Validate data integrity between CSV and PostgreSQL
3. Update probability calculator to use PostgreSQL exclusively

### Phase 2: Performance Optimization
1. Implement database-optimized probability calculations
2. Add intelligent caching layer
3. Optimize memory usage patterns

### Phase 3: System Integration
1. Remove CSV file dependencies
2. Implement database-backed caching
3. Optimize file I/O operations

## SUCCESS METRICS

### Performance Targets
- **CPU Usage:** Reduce UPC CPU usage from 36.6% to <20%
- **Memory Usage:** Reduce UPC memory from 170MB to <100MB
- **Response Time:** Maintain <1 second cycle time
- **Scalability:** Support 2-core cloud deployments

### Reliability Targets
- **Uptime:** Maintain 99.9% system availability
- **Data Integrity:** Zero data loss during migration
- **Performance:** No degradation in calculation accuracy

## CONCLUSION

The current CSV-based system provides a solid foundation but shows clear performance bottlenecks that can be addressed through PostgreSQL migration. The high CPU usage (36.6%) in the unified_production_coordinator indicates computational intensity that may limit scalability on resource-constrained systems.

The migration to PostgreSQL-based data production offers significant opportunities for:
- Reduced CPU usage through optimized calculations
- Lower memory footprint through intelligent caching
- Improved scalability for cloud deployments
- Enhanced data consistency and reliability

This audit establishes the baseline metrics needed to measure the success of the PostgreSQL migration and ensure performance improvements are achieved.
