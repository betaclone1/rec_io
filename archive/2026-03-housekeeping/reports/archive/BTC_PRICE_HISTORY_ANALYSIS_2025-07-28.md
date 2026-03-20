# BTC PRICE HISTORY DATABASE ANALYSIS

## 🚨 CRITICAL FINDING: NO ROLLING WINDOW IMPLEMENTED

**Date**: July 28, 2025  
**Issue**: Local BTC watchdog lacks 30-day rolling window  
**Status**: Database will grow indefinitely

---

## 📊 CURRENT BTC PRICE HISTORY STATUS

### DATABASE ANALYSIS
```
Database Size: 4.2MB
Total Records: 69,050
Date Range: 2025-07-27T12:01:15 to 2025-07-28T14:58:02
Growth Rate: ~46,000 records/day
Projected 30 Days: ~1,380,000 records
```

### GROWTH PROJECTIONS
| Time Period | Records | Database Size | Status |
|-------------|---------|---------------|--------|
| **Current (1.5 days)** | 69,050 | 4.2MB | ✅ Manageable |
| **1 Week** | 322,000 | ~20MB | ⚠️ Growing |
| **1 Month** | 1,380,000 | ~84MB | ❌ Large |
| **3 Months** | 4,140,000 | ~252MB | ❌ Very Large |
| **6 Months** | 8,280,000 | ~504MB | ❌ Massive |

---

## 🔍 IMPLEMENTATION COMPARISON

### CLOUD VERSION (CORRECT)
**File**: `backend/cloud_backend/symbol_price_watchdog_cloud.py`
```python
def save_price(symbol, timestamp: str, price: float):
    """Save price to database with 30-day rolling window"""
    conn = sqlite3.connect(DB_PATHS[symbol])
    c = conn.cursor()
    c.execute(f'''
        INSERT OR REPLACE INTO {TABLE_NAME} (timestamp, price) VALUES (?, ?)
    ''', (timestamp, price))
    
    # Use EST timezone for cutoff calculation
    est_tz = ZoneInfo('US/Eastern')
    cutoff_time = datetime.now(est_tz) - timedelta(days=30)
    cutoff_iso = cutoff_time.strftime("%Y-%m-%dT%H:%M:%S")
    c.execute(f"DELETE FROM {TABLE_NAME} WHERE timestamp < ?", (cutoff_iso,))
    
    conn.commit()
    conn.close()
```

### LOCAL VERSION (MISSING ROLLING WINDOW)
**File**: `backend/api/coinbase-api/coinbase-btc/btc_price_watchdog.py`
```python
def insert_tick(timestamp: str, price: float):
    conn = sqlite3.connect(BTC_PRICE_HISTORY_DB)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS price_log (
            timestamp TEXT PRIMARY KEY,
            price REAL
        )
    ''')
    dt = datetime.now(ZoneInfo("America/New_York")).replace(microsecond=0)
    rounded_timestamp = dt.strftime("%Y-%m-%dT%H:%M:%S")
    cursor.execute('''
        INSERT OR REPLACE INTO price_log (timestamp, price) VALUES (?, ?)
    ''', (rounded_timestamp, price))
    conn.commit()
    conn.close()
    # ❌ NO ROLLING WINDOW CLEANUP
```

---

## 🚨 PROBLEM IDENTIFICATION

### MISSING ROLLING WINDOW
1. **No DELETE statements** in local BTC watchdog
2. **No 30-day cutoff calculation**
3. **No cleanup of old records**
4. **Database will grow indefinitely**

### IMPACT ANALYSIS
- **Storage Growth**: Unlimited (currently 4.2MB, will reach 84MB in 30 days)
- **Performance Impact**: Slower queries as database grows
- **Resource Usage**: Increasing memory and disk usage
- **Maintenance**: Manual cleanup required

---

## ✅ SOLUTION: IMPLEMENT ROLLING WINDOW

### REQUIRED CHANGES
1. **Add 30-day cutoff calculation**
2. **Add DELETE statement for old records**
3. **Import timedelta from datetime**
4. **Test the implementation**

### IMPLEMENTATION PLAN
```python
def insert_tick(timestamp: str, price: float):
    conn = sqlite3.connect(BTC_PRICE_HISTORY_DB)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS price_log (
            timestamp TEXT PRIMARY KEY,
            price REAL
        )
    ''')
    dt = datetime.now(ZoneInfo("America/New_York")).replace(microsecond=0)
    rounded_timestamp = dt.strftime("%Y-%m-%dT%H:%M:%S")
    cursor.execute('''
        INSERT OR REPLACE INTO price_log (timestamp, price) VALUES (?, ?)
    ''', (rounded_timestamp, price))
    
    # ✅ ADD ROLLING WINDOW CLEANUP
    cutoff_time = dt - timedelta(days=30)
    cutoff_iso = cutoff_time.strftime("%Y-%m-%dT%H:%M:%S")
    cursor.execute("DELETE FROM price_log WHERE timestamp < ?", (cutoff_iso,))
    
    conn.commit()
    conn.close()
```

---

## 📊 JSON ANALYSIS

```json
{
  "btc_price_history_analysis": {
    "current_status": {
      "database_size": "4.2MB",
      "total_records": 69050,
      "date_range": "2025-07-27T12:01:15 to 2025-07-28T14:58:02",
      "growth_rate": "46000_records_per_day"
    },
    "implementation_issue": {
      "local_version": "missing_rolling_window",
      "cloud_version": "has_rolling_window",
      "problem": "database_will_grow_indefinitely"
    },
    "projected_growth": {
      "1_week": "20MB",
      "1_month": "84MB", 
      "3_months": "252MB",
      "6_months": "504MB"
    },
    "required_fix": {
      "add_cutoff_calculation": true,
      "add_delete_statement": true,
      "import_timedelta": true,
      "test_implementation": true
    },
    "solution_priority": "high"
  }
}
```

---

## 🎯 RECOMMENDATION

### IMMEDIATE ACTION REQUIRED
1. **Implement rolling window** in local BTC watchdog
2. **Add 30-day cutoff calculation**
3. **Add DELETE statement for old records**
4. **Test the implementation**

### EXPECTED RESULTS
- **Database size**: Capped at ~84MB (30 days of data)
- **Performance**: Consistent query performance
- **Storage**: Sustainable growth
- **Maintenance**: Automatic cleanup

**The local BTC watchdog needs the rolling window implementation to prevent unlimited database growth.** 