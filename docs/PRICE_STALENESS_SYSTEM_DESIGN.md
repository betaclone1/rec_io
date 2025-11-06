# Price Staleness Detection & Trading Halt System

## Executive Summary

**Problem:** On 2025-10-25, a 5.82-hour Coinbase outage caused the system to trade with stale BTC prices ($111,466.20) for nearly 6 hours. The watchdog had no mechanism to detect or halt trading on stale data.

**Solution:** Implement a comprehensive staleness detection system with automatic trading halt when price data becomes stale.

---

## System Architecture

### 1. Core Components

#### A. Price Staleness Monitor (`backend/price_staleness_monitor.py`)
**Purpose:** Central monitoring service that tracks price freshness for all symbols

**Key Functions:**
- Monitor last update timestamp for each symbol
- Detect repeated identical prices
- Calculate staleness status (fresh/warning/stale/critical)
- Publish staleness events via Redis/pub-sub
- Expose staleness API for other services

#### B. Enhanced Symbol Price Watchdog
**Purpose:** Detect and report staleness conditions

**Enhancements:**
- Track consecutive identical prices
- Track last valid timestamp
- Emit staleness events when thresholds exceeded
- Set staleness flags in database

#### C. Trading Circuit Breaker
**Purpose:** Halt automated trading when staleness detected

**Integration Points:**
- `auto_entry_supervisor.py` - Block new entries
- `trade_manager.py` - Reject manual trades
- `active_trade_supervisor.py` - Alert on monitor staleness

---

## Configuration

```python
# backend/core/config/staleness_config.py

STALENESS_CONFIG = {
    # Timing thresholds (seconds)
    'max_price_age_warning': 15,      # Warn if price > 15s old
    'max_price_age_stale': 30,         # Stale if price > 30s old
    'max_price_age_critical': 60,      # Critical if price > 60s old
    
    # Repeated price detection
    'max_identical_price_duration': 30,  # Same price for 30s = stale
    'max_identical_price_count': 10,     # 10 identical updates = stale
    
    # WebSocket health
    'max_consecutive_timeouts': 6,       # 6 consecutive timeouts = stale
    'timeout_window_seconds': 60,        # Window for timeout counting
    
    # Circuit breaker behavior
    'trading_halt_on_stale': True,       # Auto-halt trading on stale
    'trading_resume_on_fresh': True,     # Auto-resume when fresh
    'manual_override_required': False,   # Require manual override to trade stale
}
```

---

## Database Schema Changes

### New Table: `live_data.price_staleness_status`

```sql
CREATE TABLE live_data.price_staleness_status (
    symbol VARCHAR(10) PRIMARY KEY,
    status VARCHAR(20) NOT NULL,  -- 'fresh', 'warning', 'stale', 'critical'
    last_valid_timestamp TIMESTAMP NOT NULL,
    last_valid_price DECIMAL(15,2) NOT NULL,
    consecutive_identical_count INTEGER DEFAULT 0,
    consecutive_timeouts INTEGER DEFAULT 0,
    staleness_reason TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_price_staleness_status ON live_data.price_staleness_status(updated_at);
```

### Add to Existing Tables

```sql
-- Add staleness flag to price log tables
ALTER TABLE live_data.live_price_log_1s_btc ADD COLUMN IF NOT EXISTS is_stale BOOLEAN DEFAULT FALSE;
ALTER TABLE live_data.live_price_log_1s_eth ADD COLUMN IF NOT EXISTS is_stale BOOLEAN DEFAULT FALSE;
ALTER TABLE live_data.live_price_log_1s_spx ADD COLUMN IF NOT EXISTS is_stale BOOLEAN DEFAULT FALSE;
ALTER TABLE live_data.live_price_log_1s_ndx ADD COLUMN IF NOT EXISTS is_stale BOOLEAN DEFAULT FALSE;
```

---

## Implementation Details

### 1. Price Staleness Monitor Service

**File:** `backend/price_staleness_monitor.py`

**Key Functions:**

```python
class PriceStalenessMonitor:
    def __init__(self):
        self.symbol_config = {...}  # Symbol config from watchdog
        self.check_interval = 5  # Check every 5 seconds
        self.staleness_status = {}  # Per-symbol status
    
    def check_price_staleness(self, symbol: str) -> dict:
        """Check if price is stale and return status"""
        # Query database for latest price
        # Calculate age since last update
        # Check for repeated identical prices
        # Return staleness status
        pass
    
    def update_staleness_status(self, symbol: str, status: dict):
        """Update staleness status in database and broadcast"""
        # Update database
        # Broadcast to Redis/pub-sub
        # Notify dependent services
        pass
    
    def is_trading_allowed(self, symbol: str) -> bool:
        """Check if trading is allowed for symbol"""
        # Query current staleness status
        # Return False if stale
        pass
    
    def get_staleness_status(self, symbol: str = None) -> dict:
        """Get current staleness status for symbol(s)"""
        # Return current staleness status
        pass
```

### 2. Enhanced Symbol Price Watchdog

**Enhancements to:** `backend/symbol_price_watchdog.py`

**Add to `log_symbol_price()` function:**

```python
class StalenessTracker:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.last_price = None
        self.last_price_timestamp = None
        self.consecutive_identical = 0
        self.consecutive_timeouts = 0
        self.staleness_flags = set()
    
    def check_identical_price(self, price: float, timestamp: datetime) -> bool:
        """Check if price is identical to last price"""
        if self.last_price == price:
            self.consecutive_identical += 1
            duration = (timestamp - self.last_price_timestamp).total_seconds()
            if duration > STALENESS_CONFIG['max_identical_price_duration']:
                self.staleness_flags.add('identical_price_too_long')
                return True
        else:
            self.consecutive_identical = 0
            self.last_price = price
            self.last_price_timestamp = timestamp
        return False
    
    def record_timeout(self):
        """Record a WebSocket timeout"""
        self.consecutive_timeouts += 1
        if self.consecutive_timeouts >= STALENESS_CONFIG['max_consecutive_timeouts']:
            self.staleness_flags.add('too_many_timeouts')
    
    def reset_timeout_count(self):
        """Reset timeout counter on successful connection"""
        self.consecutive_timeouts = 0
```

**Modify timeout handling:**

```python
except asyncio.TimeoutError:
    print("⚠️ WebSocket timeout. Reconnecting...")
    staleness_tracker.record_timeout()
    
    # Check for staleness
    if staleness_tracker.is_stale():
        print(f"🚨 STALENESS DETECTED for {symbol}: {staleness_tracker.get_staleness_flags()}")
        # Update staleness status
        # Broadcast event
        # Potentially trigger trading halt
    
    break
```

### 3. Trading Circuit Breaker

**Integration with `auto_entry_supervisor.py`:**

```python
def check_auto_entry_conditions():
    """Check if auto entry conditions are met and trigger trades"""
    
    # NEW: Check price staleness before processing
    if is_price_stale(get_current_monitor_symbol()):
        log(f"[AUTO ENTRY] ⛔ STALENESS DETECTED - Auto entry blocked")
        # Update indicator to show staleness
        # Return early
        return
    
    # ... existing logic
```

**Integration with `trade_manager.py`:**

```python
@router.post("/trades", status_code=status.HTTP_201_CREATED)
async def add_trade(request: Request):
    """Create a new trade - handles both open and close intents"""
    data = await request.json()
    symbol = data.get('symbol')
    
    # NEW: Check price staleness
    if is_price_stale(symbol):
        return {
            "error": "Price data is stale - trading blocked for safety",
            "staleness_status": get_staleness_status(symbol)
        }
    
    # ... existing logic
```

### 4. Redis/Event Broadcasting

**Implement event broadcasting for staleness:**

```python
def broadcast_staleness_event(symbol: str, status: dict):
    """Broadcast staleness event to all services"""
    
    event = {
        'event_type': 'price_staleness',
        'symbol': symbol,
        'status': status['status'],  # 'warning', 'stale', 'critical'
        'last_valid_timestamp': status['last_valid_timestamp'],
        'reason': status['reason'],
        'trading_allowed': not status['is_stale'],
        'timestamp': datetime.now().isoformat()
    }
    
    # Publish to Redis pub/sub
    redis_client.publish('price_staleness_events', json.dumps(event))
    
    # Also broadcast via WebSocket if available
    broadcast_to_websockets(event)
```

---

## User Interface Changes

### Frontend Indicators

**Add staleness indicator to trading interface:**

```javascript
// Show staleness warning in header
function updateStalenessIndicator(symbol) {
    fetch(`/api/price_staleness/${symbol}`)
        .then(res => res.json())
        .then(data => {
            if (data.status !== 'fresh') {
                showStalenessWarning(data);
                disableTradingButtons();
            } else {
                hideStalenessWarning();
                enableTradingButtons();
            }
        });
}

function showStalenessWarning(data) {
    const indicator = document.getElementById('staleness-indicator');
    indicator.innerHTML = `
        <div class="alert alert-warning">
            ⚠️ Price data is ${data.status}: ${data.reason}
            <br>Last update: ${formatTimestamp(data.last_valid_timestamp)}
            <br>Trading is currently blocked for safety
        </div>
    `;
    indicator.style.display = 'block';
}
```

---

## Operational Procedures

### Automated Response

1. **Warning State (15-30s old):**
   - Log warning
   - Continue trading (brief spikes acceptable)
   - Monitor closely

2. **Stale State (30-60s old):**
   - Block new automated trades
   - Allow manual override
   - Alert on UI
   - Log incident

3. **Critical State (>60s old):**
   - Halt all automated trading
   - Require manual override for any trades
   - Emergency alert
   - Investigation required

### Manual Override

**Admin interface to override staleness:**

```python
@router.post("/api/manual_override_staleness")
async def manual_override_staleness(symbol: str, override_reason: str):
    """Manually override staleness protection for emergency trading"""
    
    # Log the override
    log_override(symbol, override_reason, request.headers.get('user'))
    
    # Temporarily disable staleness check
    set_staleness_override(symbol, duration=300)  # 5 minutes
    
    # Notify system
    broadcast_override_event(symbol, override_reason)
    
    return {"status": "override_active", "duration": 300}
```

---

## Testing Strategy

### Test Cases

1. **Stale Price Detection:**
   - Stop price updates
   - Verify staleness detected at 30s
   - Verify trading blocked

2. **Repeated Price Detection:**
   - Send identical prices for 30+ seconds
   - Verify staleness detected
   - Verify trading blocked

3. **Timeout Detection:**
   - Cause 6 consecutive timeouts
   - Verify staleness detected
   - Verify trading blocked

4. **Recovery:**
   - Resume price updates
   - Verify staleness clears
   - Verify trading resumes

5. **Manual Override:**
   - Activate override
   - Verify trading allowed
   - Verify override expires

### Simulation Test

```python
def simulate_outage(seconds: int = 300):
    """Simulate a Coinbase outage for testing"""
    # Pause price updates
    pause_price_updates()
    
    # Wait for staleness detection
    wait_for_staleness_detection()
    
    # Attempt to place trade
    result = attempt_trade()
    assert result['error'] == 'Price data is stale'
    
    # Resume updates
    resume_price_updates()
    
    # Verify staleness clears
    wait_for_staleness_clear()
    
    # Verify trading resumes
    result = attempt_trade()
    assert result['status'] == 'success'
```

---

## Monitoring & Alerts

### Metrics to Track

1. **Staleness Events:**
   - Count of staleness events per day
   - Duration of staleness events
   - Symbols affected

2. **Trading Impact:**
   - Trades blocked due to staleness
   - Revenue impact
   - Manual overrides used

3. **System Health:**
   - Watchdog uptime
   - Average price freshness
   - Timeout frequency

### Alerting

- **Critical:** Staleness > 60s
- **Warning:** Staleness > 30s
- **Info:** Manual override used

---

## Migration Plan

### Phase 1: Detection (Week 1)
- Implement staleness monitoring
- Deploy staleness status API
- Add logging and metrics

### Phase 2: Integration (Week 2)
- Integrate with auto entry supervisor
- Integrate with trade manager
- Add UI indicators

### Phase 3: Enforcement (Week 3)
- Enable trading halt
- Add manual override
- Full deployment

---

## Success Metrics

**Primary Goals:**
- Zero trades on stale data (after deployment)
- <5 minute mean time to staleness detection
- <1 false positive per day

**Secondary Goals:**
- <2% of trading time lost to staleness
- User confidence in system reliability
- Clear audit trail for any incidents

---

## Appendix: Code Structure

```
backend/
├── price_staleness_monitor.py      # NEW: Core staleness monitoring
├── price_staleness_config.py       # NEW: Configuration
├── price_staleness_api.py          # NEW: REST API for status
│
├── symbol_price_watchdog.py        # MODIFY: Add staleness detection
│
├── auto_entry_supervisor.py        # MODIFY: Check staleness
├── trade_manager.py                # MODIFY: Check staleness
├── active_trade_supervisor.py      # MODIFY: Check staleness
│
└── migrations/
    └── add_price_staleness_tables.sql  # NEW: Database schema
```

---

## References

- Incident Date: 2025-10-25
- Duration: 5 hours 49 minutes
- Impact: All trades used stale $111,466.20 price
- Root Cause: No staleness detection in price watchdog





