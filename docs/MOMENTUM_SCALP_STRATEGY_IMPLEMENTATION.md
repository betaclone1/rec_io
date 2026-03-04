# MOMENTUM SCALP Strategy Implementation

**Status**: IN PROGRESS  
**Last Updated**: 2025-01-27  
**Strategy Type**: Momentum-based scalping strategy

---

## Strategy Overview

**Goal**: Enter multiple ITM (In-The-Money) positions during momentum spikes and exit via trailing stops or profit targets for quick scalps.

**Core Concept**: 
- Unlike HOURLY HTC which **pauses** on momentum spikes, MOMENTUM SCALP **activates** on momentum spikes
- Enters multiple simultaneous positions in the direction of momentum
- Uses trailing stops and profit targets for quick exits (seconds/minutes, not hours)

---

## Required Monitor Settings

### Time Window Settings (Same as HOURLY HTC)
- `min_time` - Minimum TTC window (seconds)
- `max_time` - Maximum TTC window (seconds)

### Momentum Entry Settings
- `momentum_scalp_entry_threshold` - Momentum threshold to trigger entry (e.g., ±98)
  - Positive spike: `momentum >= threshold`
  - Negative spike: `momentum <= -threshold`

### Entry Filter Settings (Same as HOURLY HTC)
- `min_volume` - Minimum volume threshold
- `min_probability` - Minimum probability threshold

### Exit Settings
- `momentum_scalp_trailing_stop_amount` - Trailing stop amount in dollars (e.g., 0.10 for 10 cents)
- `momentum_scalp_profit_target` - Profit target as position value (e.g., 0.99 for $0.99)
- `min_ttc_seconds` - Minimum TTC before exit allowed (same as HOURLY HTC)

### Shared Settings (Same as HOURLY HTC)
- `total_position` - Position size per trade
- `bankroll_allotment_total` - Capital allocation
- `multiplier` - Position multiplier

---

## Entry Logic (auto_entry_supervisor.py)

### Activation Conditions

Monitor becomes **ACTIVE** when **BOTH** conditions are met:

1. **Time Window Open**: `min_time <= current_ttc <= max_time`
2. **Momentum Spike Detected**: 
   - `momentum >= momentum_scalp_entry_threshold` (UP spike)
   - OR `momentum <= -momentum_scalp_entry_threshold` (DOWN spike)

### Direction Determination

- **UP Momentum Spike** → Look at **YES strikes BELOW money line** (ITM YES)
  - Condition: `strike < current_price` AND `active_side == 'yes'`
  
- **DOWN Momentum Spike** → Look at **NO strikes ABOVE money line** (ITM NO)
  - Condition: `strike > current_price` AND `active_side == 'no'`

### Entry Scanning Process

1. **Filter by Volume**: Only strikes with `volume >= min_volume`
2. **Filter by Probability**: Only strikes with `probability >= min_probability`
3. **Filter by ITM Status**: Only strikes on correct side of money line based on momentum direction
4. **Sort by Probability**: Highest probability first, descending
5. **Check Duplicates**: Skip strikes already pending or open (uses `is_strike_already_traded()`)
6. **Enter All Eligible**: Enter all strikes that pass filters, in probability order

### Entry Execution

- Uses same `trigger_auto_entry_trade()` function as HOURLY HTC
- Respects `total_position`, `bankroll_allotment_total`, `multiplier` settings
- Loss prevention does NOT apply to MOMENTUM SCALP (per plan document)

---

## Exit Logic (active_trade_supervisor.py)

### Exit Conditions

Trade exits when **EITHER** condition is met (both require TTC protection):

#### 1. Trailing Stop Exit
- **Condition**: `current_close_price <= (high_price - momentum_scalp_trailing_stop_amount)`
- **AND**: `ttc_seconds >= min_ttc_seconds`
- **Behavior**: 
  - Trailing stop follows `high_price` upward
  - Maintains fixed distance (`momentum_scalp_trailing_stop_amount`) below high
  - Example: If `high_price = 0.90` and `trailing_stop_amount = 0.10`, exit at `current_close_price <= 0.80`

#### 2. Profit Target Exit
- **Condition**: `1 - current_close_price >= momentum_scalp_profit_target`
- **AND**: `ttc_seconds >= min_ttc_seconds`
- **Behavior**:
  - Hard cap on profit - locks in gains immediately
  - Example: If `profit_target = 0.98`, exit when `current_close_price <= 0.02`

### TTC Protection

- **Required**: Both exit conditions respect `min_ttc_seconds`
- **Behavior**: Won't exit if `ttc_seconds < min_ttc_seconds`, even if trailing stop or profit target is met
- **Same as HOURLY HTC**: Uses same `min_ttc_seconds` setting

### Exit Execution

- Uses same `trigger_auto_stop_close()` function as HOURLY HTC
- No verification period (exits immediately when conditions met)
- No probability-based exit logic (doesn't use `current_probability` threshold)

---

## Strategy Comparison: MOMENTUM SCALP vs HOURLY HTC

| Aspect | HOURLY HTC | MOMENTUM SCALP |
|--------|------------|----------------|
| **Spike Behavior** | Pauses entries on spikes | Activates on spikes |
| **Entry Trigger** | TTC window + probability + differential | TTC window + momentum spike + ITM status |
| **TTC Window** | Required | Required (same) |
| **Probability Check** | Required (min_probability) | Required (min_probability) |
| **Differential Check** | Required (min/max_differential) | NOT USED |
| **Strike Selection** | Any strike meeting criteria | Only ITM strikes (correct side of momentum) |
| **Position Count** | Typically one at a time | Multiple simultaneous |
| **Entry Timing** | Within TTC window | Within TTC window + momentum spike |
| **Exit Method** | Probability threshold or hold to expiration | Trailing stop + profit target |
| **Exit Timing** | Can hold until expiration | Quick scalps (seconds/minutes) |
| **Trailing Stop** | Not used | 10 cent trailing stop |
| **Profit Target** | Not used | Hard cap (e.g., $0.99) |
| **TTC Protection** | Yes (min_ttc_seconds) | Yes (min_ttc_seconds) |
| **Verification Period** | Optional | Not used |
| **Duplicate Prevention** | Yes (pending + open) | Yes (same logic) |

---

## Implementation Status

### Phase 1: Database Schema ✅
- [x] `momentum_scalp_entry_threshold` column added
- [x] `momentum_scalp_trailing_stop_amount` column added
- [x] `momentum_scalp_profit_target` column added
- [x] Database migration completed

### Phase 2: Strategy Detection & Routing
- [ ] Add `get_monitor_strategy()` function to auto_entry_supervisor.py
- [ ] Add `get_monitor_strategy()` function to active_trade_supervisor.py
- [ ] Route `check_auto_entry_conditions()` to strategy-specific functions
- [ ] Route `monitoring_worker()` exit logic to strategy-specific functions

### Phase 3: MOMENTUM SCALP Entry Implementation
- [ ] Create `check_auto_entry_conditions_momentum_scalp()` function
- [ ] Implement momentum spike detection (UP/DOWN)
- [ ] Implement ITM strike filtering (correct side based on direction)
- [ ] Implement probability-based sorting
- [ ] Integrate with existing `trigger_auto_entry_trade()` function
- [ ] Add `get_momentum_scalp_entry_settings()` helper function

### Phase 4: MOMENTUM SCALP Exit Implementation
- [ ] Create `check_momentum_scalp_exit_conditions()` function
- [ ] Implement trailing stop calculation (`high_price - trailing_stop_amount`)
- [ ] Implement profit target check (`1 - current_close_price >= profit_target`)
- [ ] Add TTC protection (`ttc_seconds >= min_ttc_seconds`)
- [ ] Integrate with existing `trigger_auto_stop_close()` function
- [ ] Add `get_momentum_scalp_exit_settings()` helper function

### Phase 5: Testing & Validation
- [ ] Unit tests for strategy detection
- [ ] Unit tests for entry logic
- [ ] Unit tests for exit logic
- [ ] Integration tests for full entry/exit flow
- [ ] Regression tests to verify HOURLY HTC unaffected
- [ ] Live testing on test monitor

### Phase 6: UI Updates
- [ ] Add strategy selector to monitor configuration UI
- [ ] Show/hide settings based on selected strategy
- [ ] Display MOMENTUM SCALP-specific settings
- [ ] Update active trades display for MOMENTUM SCALP trades

---

## Code Structure

### auto_entry_supervisor.py Changes

```
auto_entry_supervisor.py
├── Strategy Detection
│   ├── get_monitor_strategy() [NEW]
│   └── Route to strategy logic
├── HOURLY HTC Logic (EXISTING - UNCHANGED)
│   ├── check_auto_entry_conditions() [MODIFIED - routes to _hourly_htc]
│   └── check_auto_entry_conditions_hourly_htc() [RENAMED from existing]
└── MOMENTUM SCALP Logic (NEW)
    ├── check_auto_entry_conditions_momentum_scalp() [NEW]
    └── get_momentum_scalp_entry_settings() [NEW]
```

### active_trade_supervisor.py Changes

```
active_trade_supervisor.py
├── Strategy Detection
│   └── get_monitor_strategy() [NEW]
├── HOURLY HTC Logic (EXISTING - UNCHANGED)
│   └── monitoring_worker() [MODIFIED - routes exit logic]
└── MOMENTUM SCALP Logic (NEW)
    ├── check_momentum_scalp_exit_conditions() [NEW]
    └── get_momentum_scalp_exit_settings() [NEW]
```

---

## Key Implementation Notes

### Safety Measures
1. **Strategy Isolation**: All HOURLY HTC logic remains untouched
2. **Default Fallback**: Unknown strategies default to HOURLY HTC
3. **Error Handling**: Strategy detection errors default to HOURLY HTC
4. **Backward Compatibility**: Existing HOURLY HTC monitors continue working identically

### Performance Considerations
- Strategy detection should be fast (cache if needed)
- Entry/exit checks should not impact monitoring loop speed
- Logging should clearly mark which strategy logic is executing

### Testing Strategy
1. Test strategy detection and routing
2. Test full entry/exit flow for each strategy
3. Verify HOURLY HTC still works identically
4. Test MOMENTUM SCALP on test monitor first

---

## Open Questions / Future Enhancements

- [ ] Should MOMENTUM SCALP respect `max_differential` setting? (Currently: NOT USED)
- [ ] Should MOMENTUM SCALP use `spike_alert` logic? (Currently: NOT USED - opposite behavior)
- [ ] Should MOMENTUM SCALP support `allow_re_entry`? (Currently: Uses duplicate prevention)
- [ ] Position sizing strategy for multiple simultaneous entries?
- [ ] Capital allocation limits for MOMENTUM SCALP vs HOURLY HTC?

---

## Change Log

### 2025-01-27
- Initial documentation created
- Strategy requirements defined
- Entry and exit logic specified
- Implementation phases outlined

