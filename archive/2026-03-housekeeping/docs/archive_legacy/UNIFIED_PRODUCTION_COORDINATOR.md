# UNIFIED PRODUCTION COORDINATOR

## Overview

The **Unified Production Coordinator** replaces the previous system of independent scripts running every second with a coordinated, sequential data production pipeline. This ensures data consistency, eliminates race conditions, and provides better monitoring and control.

## Architecture

### Previous System (Independent Scripts)
```
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ probability_    │  │ strike_table_   │  │ btc_price_      │
│ writer.py       │  │ manager.py      │  │ watchdog.py     │
│ (Port 8008)     │  │ (Port 8009)     │  │ (Port 8002)     │
└─────────────────┘  └─────────────────┘  └─────────────────┘
         │                     │                     │
         ▼                     ▼                     ▼
   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
   │ btc_live_   │    │ btc_strike_ │    │ btc_price_  │
   │ prob.json   │    │ table.json  │    │ history.db  │
   └─────────────┘    └─────────────┘    └─────────────┘
```

**Problems:**
- ❌ No coordination between scripts
- ❌ Race conditions
- ❌ Redundant data fetching
- ❌ No dependency management
- ❌ Difficult to monitor and debug

### New System (Unified Coordinator)
```
┌─────────────────────────────────────────────────────────────┐
│                UNIFIED PRODUCTION COORDINATOR              │
│                     (Port 8010)                           │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │
│  │   STEP 1    │  │   STEP 2    │  │   STEP 3    │      │
│  │ BTC PRICE   │  │   MARKET    │  │PROBABILITIES│      │
│  │  FETCH      │  │  SNAPSHOT   │  │ CALCULATION │      │
│  └─────────────┘  └─────────────┘  └─────────────┘      │
│         │                │                │              │
│         ▼                ▼                ▼              │
│  ┌─────────────────────────────────────────────────────┐  │
│  │              STEP 4: STRIKE TABLE                  │  │
│  │           (Requires Steps 1-3)                    │  │
│  └─────────────────────────────────────────────────────┘  │
│                           │                              │
│                           ▼                              │
│  ┌─────────────────────────────────────────────────────┐  │
│  │              STEP 5: WATCHLIST                     │  │
│  │           (Requires Step 4)                        │  │
│  └─────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

**Benefits:**
- ✅ Sequential execution ensures data consistency
- ✅ Clear dependency management
- ✅ Centralized error handling and retry logic
- ✅ Comprehensive monitoring and logging
- ✅ Single point of control

## Data Flow

### Step 1: Live Symbol Price
- **Source**: Coinbase WebSocket API
- **Output**: `backend/data/price_history/btc_price_history.db`
- **Frequency**: Every second
- **Dependencies**: None (primary data source)

### Step 2: Market Snapshot
- **Source**: Kalshi API
- **Output**: `backend/data/kalshi/latest_market_snapshot.json`
- **Frequency**: Every second
- **Dependencies**: None (primary data source)

### Step 3: Probability Calculation
- **Source**: BTC price + Market snapshot (TTC calculation)
- **Output**: `backend/data/live_probabilities/btc_live_probabilities.json`
- **Frequency**: Every second
- **Dependencies**: Steps 1 & 2 (requires fresh BTC price and market data)

### Step 4: Strike Table Generation
- **Source**: BTC price + Market snapshot + Probabilities
- **Output**: `backend/data/strike_tables/btc_strike_table.json`
- **Frequency**: Every second
- **Dependencies**: Steps 1, 2 & 3 (requires all previous data)

### Step 5: Watchlist Generation
- **Source**: Strike table data (filtered)
- **Output**: `backend/data/strike_tables/btc_watchlist.json`
- **Frequency**: Every second
- **Dependencies**: Step 4 (requires strike table data)

## API Endpoints

The unified coordinator provides a REST API for monitoring and control:

### Health Check
```
GET http://localhost:8010/health
```
Returns overall system health status.

### Pipeline Status
```
GET http://localhost:8010/status
```
Returns detailed pipeline status including current cycle, timing, and last results.

### Start Pipeline
```
POST http://localhost:8010/start
```
Starts the unified production pipeline.

### Stop Pipeline
```
POST http://localhost:8010/stop
```
Stops the unified production pipeline.

### Restart Pipeline
```
POST http://localhost:8010/restart
```
Restarts the unified production pipeline.

### Performance Statistics
```
GET http://localhost:8010/performance
```
Returns performance metrics including success rate, cycle times, and failure counts.

## Configuration

### Port Assignment
The unified coordinator runs on port **8010** as defined in:
- `backend/core/config/MASTER_PORT_MANIFEST.json`
- `backend/core/port_config.py`

### Supervisor Configuration
```ini
[program:unified_production_coordinator]
command=python backend/unified_production_coordinator_api.py
directory=.
autostart=true
autorestart=true
stderr_logfile=logs/unified_production_coordinator.err.log
stdout_logfile=logs/unified_production_coordinator.out.log
environment=PATH="venv/bin",PYTHONPATH=".",TRADING_SYSTEM_HOST="localhost"
```

## Migration from Old System

### Step 1: Stop Old Scripts
```bash
# Note: probability_writer has been replaced by unified_production_coordinator

```

### Step 2: Start Unified Coordinator
```bash
supervisorctl start unified_production_coordinator
```

### Step 3: Verify Migration
```bash
python backend/migrate_to_unified_coordinator.py
```

## Monitoring

### Performance Metrics
- **Success Rate**: Percentage of successful pipeline cycles
- **Average Cycle Time**: Average time per pipeline cycle
- **Consecutive Failures**: Number of consecutive failed cycles
- **Total Cycles**: Total number of pipeline cycles executed

### Health Status
- **Healthy**: Pipeline running with < 3 consecutive failures
- **Degraded**: Pipeline running with ≥ 3 consecutive failures
- **Error**: Pipeline not running or critical errors

### Log Files
- **stdout**: `logs/unified_production_coordinator.out.log`
- **stderr**: `logs/unified_production_coordinator.err.log`

## Error Handling

### Automatic Retry Logic
- Failed steps are logged with detailed error information
- Pipeline continues to next cycle even if current cycle fails
- After 5 consecutive failures, pipeline pauses for 10 seconds

### Data Validation
- Each step validates required input data before processing
- Missing or stale data causes step failure with clear error messages
- Dependencies are checked before each step execution

## Benefits

### Data Consistency
- Sequential execution ensures all data is fresh and consistent
- No race conditions between different data sources
- Guaranteed data flow from primary sources to final outputs

### Reliability
- Centralized error handling and retry logic
- Automatic recovery from temporary failures
- Comprehensive logging for debugging

### Monitoring
- Real-time performance metrics
- Health status monitoring
- Detailed pipeline status reporting

### Maintainability
- Single coordinator instead of multiple independent scripts
- Clear data flow and dependency management
- Easy to add new data sources or modify flow

## Troubleshooting

### Common Issues

#### Pipeline Not Starting
1. Check if port 8010 is available
2. Verify supervisor configuration
3. Check log files for errors

#### Data Files Not Updating
1. Check coordinator health status
2. Verify data source availability (BTC price, Kalshi API)
3. Check performance metrics for failures

#### High Failure Rate
1. Check network connectivity to data sources
2. Verify API credentials and rate limits
3. Review error logs for specific failure reasons

### Debug Commands
```bash
# Check coordinator status
curl http://localhost:8010/health

# Get detailed status
curl http://localhost:8010/status

# Check performance
curl http://localhost:8010/performance

# Restart pipeline
curl -X POST http://localhost:8010/restart
```

## Future Enhancements

### Planned Features
- **Web Dashboard**: Real-time monitoring interface
- **Alert System**: Email/SMS notifications for failures
- **Data Quality Metrics**: Validation of output data quality
- **Scalability**: Support for multiple symbols and data sources
- **Configuration UI**: Web interface for pipeline configuration

### Extensibility
The unified coordinator is designed to be easily extensible:
- Add new data sources by implementing new steps
- Modify data flow by changing step dependencies
- Add new output formats by extending the pipeline
- Integrate with external monitoring systems 