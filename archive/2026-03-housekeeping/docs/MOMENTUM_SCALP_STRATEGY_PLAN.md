# Momentum Scalp Strategy Implementation Plan

## Overview

This document outlines the plan to add **Momentum Scalp** strategy support to `auto_entry_supervisor.py` and `active_trade_supervisor.py` without affecting existing **Hourly BTC** strategy functionality.

## Current State Analysis

### Hourly BTC Strategy (Existing - DO NOT MODIFY)

#### Auto Entry Supervisor (`auto_entry_supervisor.py`)
- **Entry Logic**: TTC-based time window
  - Checks if `min_time <= current_ttc <= max_time` (TTC window requirement)
  - Uses probability threshold (`min_probability`)
  - Uses differential threshold (`min_differential`, `max_differential`)
  - Checks volume (`min_volume`)
  - **Momentum Spike Detector**: Pauses entries when momentum spikes above threshold
    - Triggers when `momentum >= spike_alert_momentum_threshold` (positive or negative)
    - Stays paused until recovery conditions met:
      - Momentum drops below `spike_alert_cooldown_threshold`
      - Stays below threshold for `spike_alert_cooldown_minutes` duration
      - If momentum spikes again during recovery, timer resets
- **Settings Source**: `monitor_list_XXXX` table fields:
  - `min_time`, `max_time` (TTC window)
  - `min_probability`, `min_differential`, `max_differential`
  - `min_volume`
  - `spike_alert_enabled`, `spike_alert_momentum_threshold`, `spike_alert_cooldown_threshold`, `spike_alert_cooldown_minutes`
- **Key Functions**:
  - `check_auto_entry_conditions()` - Main entry logic
  - `get_auto_entry_settings()` - Reads from monitor_list
  - `get_current_ttc()` - Gets time to close
  - `check_spike_alert_conditions()` - Momentum spike detector

#### Active Trade Supervisor (`active_trade_supervisor.py`)
- **Exit Logic**: Probability-based auto-stop
  - Triggers when `current_probability < threshold`
  - Respects `min_ttc_seconds` (won't close too early)
  - Has verification period option (waits X seconds before confirming auto-stop)
  - Momentum spike auto-stopout (closes all NO trades on positive spike, YES trades on negative spike)
- **Settings Source**: `monitor_list_XXXX` table fields:
  - `current_probability` (auto-stop threshold)
  - `min_ttc_seconds` (minimum time before close)
  - `verification_period_enabled`, `verification_period_seconds`
  - `momentum_spike_enabled`, `momentum_spike_threshold`
- **Key Functions**:
  - `monitoring_worker()` - Main monitoring loop with auto-stop logic
  - `get_auto_stop_threshold()` - Gets probability threshold
  - `get_min_ttc_seconds()` - Gets minimum TTC
  - `get_verification_period_*()` - Gets verification settings
- **Settlement**: Trades expire at top of hour, then await settlement data to finalize PnL

### Strategy Detection Pattern

Both scripts currently:
1. Query `strategy` field from `monitor_list_XXXX` table
2. Read strategy-specific settings from monitor_list fields
3. Use those settings in their logic

**Current strategy values**: "Hourly BTC" (or similar)

---

## Momentum Scalp Strategy Requirements

### Complete Strategy Specification

**Core Concept**: Enter on momentum spikes (opposite of Hourly BTC), ride the momentum with trailing stops, take quick profits.

### Entry Logic (Auto Entry Supervisor)

**Key Differences from Hourly BTC:**
- **Enters ON momentum spikes** (opposite behavior - Hourly BTC pauses on spikes)
- **NO TTC window** - Can enter at any time when momentum conditions met
- **NO probability threshold** - Doesn't check win probability
- **NO differential threshold** - Doesn't check price differentiation
- **Multiple simultaneous positions** - Can enter many strikes at once
- **ITM strikes only** - Only enters strikes that are already in the money
- **Immediate entry** - Enters all eligible strikes immediately on spike detection

**Entry Conditions:**
1. **Momentum Spike Detection**: 
   - Positive spike (UP): Enter when `momentum >= momentum_scalp_entry_threshold`
   - Negative spike (DOWN): Enter when `momentum <= -momentum_scalp_entry_threshold`
2. **Direction-Based Strike Selection**:
   - **Positive spike**: Enter all YES strikes that are ITM (strike < symbol price)
   - **Negative spike**: Enter all NO strikes that are ITM (strike > symbol price)
3. **Strike Selection Order**:
   - Start with **deepest ITM strikes** (furthest from money line)
   - Work **towards the money line** (closer to ATM)
   - Deepest ITM = safest, most likely to profit quickly
   - If capital runs out, safest trades are filled first
4. **Volume Filter**: Only strikes meeting `min_volume` threshold
5. **Position Size**: Set position size per trade (same as Hourly BTC)
6. **Duplicate Prevention**: Reuse existing `is_strike_already_traded()` logic
   - Checks both pending and open trades
   - Prevents duplicate entries
7. **Continuous Entry**: While momentum stays above threshold, continue entering new ITM strikes as they become available

### Exit Logic (Active Trade Supervisor)

**Key Differences from Hourly BTC:**
- **NO probability-based exit** - Doesn't use current_probability threshold
- **NO TTC protection** - Can exit immediately, no min_ttc_seconds
- **NO verification period** - Exits immediately when conditions met
- **Trailing stop based** - Uses high_price we just implemented
- **Profit target** - Hard cap on position value
- **Faster exits** - Designed for quick scalps (seconds/minutes, not hours)

**Exit Conditions:**
1. **Trailing Stop** (10 cent fixed amount):
   - **Initial**: Entry at $0.70 → trailing stop = $0.60 (entry - 0.10)
   - **For both YES and NO**: `trailing_stop = high_price - 0.10`
   - Exit when `current_position_value < (high_price - 0.10)`
   - As `high_price` increases, trailing stop moves up automatically
   - **Note**: Same logic for YES and NO contracts (no difference in pricing/stop logic)
2. **Profit Target** (Hard cap):
   - If `current_position_value >= profit_target` (e.g., $0.99) → close immediately
   - Takes profit and frees capital for new entries
   - Applies to any trade that reaches this level
3. **Momentum Reversal**: Not implemented yet (trailing stop handles reversals)

**Capital Management:**
- As trades hit profit target, freed capital can enter new strikes
- Allows continuous entry while momentum stays above threshold

---

## Implementation Plan

### Phase 1: Database Schema Changes

#### New Fields in `monitor_list_XXXX` Table

**For Momentum Scalp Entry:**
- `momentum_scalp_entry_threshold` DECIMAL(5,2) - Momentum threshold to trigger entry (e.g., 35.0 for ±35%)
  - Reuses existing `min_volume` for volume filtering
  - Reuses existing `total_position` for position size
  - Reuses existing `bankroll_allotment` for capital allocation

**For Momentum Scalp Exit:**
- `momentum_scalp_trailing_stop_amount` DECIMAL(5,2) DEFAULT 0.10 - Trailing stop amount in dollars (e.g., 0.10 for 10 cents)
- `momentum_scalp_profit_target` DECIMAL(5,2) DEFAULT 0.99 - Profit target as position value (e.g., 0.99 for $0.99)

**Note**: 
- Loss prevention does not apply to Momentum Scalp strategy
- No maximum position limit - enters as many strikes as collateral allows
- Strategy enable/disable controlled by `strategy` field selection

**Documentation:**
- Add to `DATABASE_CHANGES_LOG.md`

### Phase 2: Strategy Detection & Routing

#### Pattern: Strategy-Specific Function Wrappers

**In both scripts, add strategy detection at key decision points:**

```python
def get_monitor_strategy():
    """Get the strategy name for this monitor"""
    # Query monitor_list for strategy field
    # Return "Hourly BTC" or "Momentum Scalp" or None

def check_auto_entry_conditions():
    """Main entry check - routes to strategy-specific logic"""
    strategy = get_monitor_strategy()
    
    if strategy == "Hourly BTC":
        return check_auto_entry_conditions_hourly_btc()  # EXISTING LOGIC
    elif strategy == "Momentum Scalp":
        return check_auto_entry_conditions_momentum_scalp()  # NEW LOGIC
    else:
        log("Unknown strategy, defaulting to Hourly BTC")
        return check_auto_entry_conditions_hourly_btc()
```

**Key Decision Points:**

**Auto Entry Supervisor:**
1. `check_auto_entry_conditions()` - Route to strategy-specific function
2. `get_auto_entry_settings()` - Return strategy-specific settings
3. `determine_auto_entry_status()` - Strategy-specific status logic

**Active Trade Supervisor:**
1. `monitoring_worker()` - Route auto-stop logic to strategy-specific function
2. Auto-stop checks - Strategy-specific exit conditions

### Phase 3: Momentum Scalp Implementation

#### Auto Entry Supervisor Changes

**New Function: `check_auto_entry_conditions_momentum_scalp()`**
- Get momentum from `get_current_momentum()` (already exists)
- Check if momentum >= entry threshold (positive spike) OR momentum <= -entry threshold (negative spike)
- Determine direction: positive = YES strikes ITM, negative = NO strikes ITM
- Get all ITM strikes for selected direction
- Sort strikes by distance from money line (deepest ITM first)
- Filter by volume (min_volume)
- Check each strike not already traded (reuse `is_strike_already_traded()`)
- Enter all eligible strikes immediately (no cooldown)
- **NO TTC window check** - Can enter anytime
- **NO probability check** - Doesn't use min_probability
- **NO differential check** - Doesn't use min_differential

**New Function: `get_momentum_scalp_entry_settings()`**
- Read from monitor_list:
  - `momentum_scalp_entry_threshold`
  - Reuse existing `min_volume` for volume filtering
  - Reuse existing `total_position` for position size
  - Reuse existing `bankroll_allotment` for capital allocation

**Modified Function: `get_auto_entry_settings()`**
- Check strategy
- If "Momentum Scalp": return momentum scalp settings
- If "Hourly BTC": return existing hourly BTC settings (unchanged)

#### Active Trade Supervisor Changes

**New Function: `check_momentum_scalp_exit_conditions(trade)`**
- Get current position value: `position_value = 1 - current_market_price`
- Get high_price from trade record
- **Check Trailing Stop**:
  - Calculate: `trailing_stop = high_price - trailing_stop_amount`
  - If `position_value < trailing_stop` → return True (exit)
- **Check Profit Target**:
  - If `position_value >= profit_target` → return True (exit)
- Return False if no exit conditions met

**New Function: `get_momentum_scalp_exit_settings()`**
- Read from monitor_list:
  - `momentum_scalp_trailing_stop_amount` (e.g., 0.10 for 10 cents)
  - `momentum_scalp_profit_target` (e.g., 0.99 for $0.99)

**Modified Function: `monitoring_worker()`**
- Check strategy at start of monitoring loop
- If "Momentum Scalp": Use momentum scalp exit logic
- If "Hourly BTC": Use existing hourly BTC exit logic (unchanged)

**Trailing Stop Calculation:**
```python
# For both YES and NO trades (same logic)
position_value = 1 - current_market_price
high_price = trade.get('high_price')

if high_price:
    trailing_stop = high_price - trailing_stop_amount  # e.g., high_price - 0.10
    if position_value < trailing_stop:
        # Trigger exit
        trigger_auto_stop_close(trade)

# Profit Target Check
if position_value >= profit_target:  # e.g., >= 0.99
    # Trigger exit
    trigger_auto_stop_close(trade)
```

### Phase 4: UI Changes

**Monitor Configuration UI:**
- Add strategy selector dropdown
- Show/hide settings based on selected strategy
- **Hourly BTC**: Show existing TTC, probability, differential settings
- **Momentum Scalp**: Show momentum entry/exit settings

**Active Trades Display:**
- Show high_price and low_price for Momentum Scalp trades
- Show trailing stop distance
- Visual indicator for strategy type

**Settings Validation:**
- Ensure all required fields are set for selected strategy
- Prevent saving incomplete configurations

---

## Safety Measures

### 1. Strategy Isolation
- **All Hourly BTC logic remains untouched**
- New logic only executes when strategy == "Momentum Scalp"
- Default fallback to Hourly BTC if strategy unknown

### 2. Backward Compatibility
- Existing monitors with "Hourly BTC" continue working exactly as before
- No changes to existing database fields
- New fields are optional (default to NULL/FALSE)

### 3. Testing Strategy
1. **Unit Tests**: Test strategy detection and routing
2. **Integration Tests**: Test full entry/exit flow for each strategy
3. **Regression Tests**: Verify Hourly BTC still works identically
4. **Live Testing**: Test Momentum Scalp on test monitor first

### 4. Rollout Plan
1. Add database fields (Phase 1)
2. Add strategy detection (Phase 2) - No behavior change yet
3. Implement Momentum Scalp logic (Phase 3) - Still defaults to Hourly BTC
4. Add UI controls (Phase 4)
5. Enable on test monitor
6. Monitor for issues
7. Enable on production monitors

---

## Code Structure

### File Organization

**Auto Entry Supervisor:**
```
auto_entry_supervisor.py
├── Strategy Detection
│   ├── get_monitor_strategy()
│   └── route_to_strategy_logic()
├── Hourly BTC Logic (EXISTING - UNCHANGED)
│   ├── check_auto_entry_conditions() [renamed to _hourly_btc]
│   └── get_auto_entry_settings() [modified to route]
└── Momentum Scalp Logic (NEW)
    ├── check_auto_entry_conditions_momentum_scalp()
    └── get_momentum_scalp_entry_settings()
```

**Active Trade Supervisor:**
```
active_trade_supervisor.py
├── Strategy Detection
│   └── get_monitor_strategy()
├── Hourly BTC Logic (EXISTING - UNCHANGED)
│   └── monitoring_worker() [modified to route]
└── Momentum Scalp Logic (NEW)
    ├── check_momentum_scalp_exit_conditions()
    └── get_momentum_scalp_exit_settings()
```

---

## Database Migration

### SQL for New Fields

```sql
-- Add Momentum Scalp entry field
ALTER TABLE users.monitor_list_0001 
ADD COLUMN momentum_scalp_entry_threshold DECIMAL(5,2) DEFAULT NULL;

-- Add Momentum Scalp exit fields
ALTER TABLE users.monitor_list_0001
ADD COLUMN momentum_scalp_trailing_stop_amount DECIMAL(5,2) DEFAULT 0.10,
ADD COLUMN momentum_scalp_profit_target DECIMAL(5,2) DEFAULT 0.99;

-- Add comments for documentation
COMMENT ON COLUMN users.monitor_list_0001.momentum_scalp_entry_threshold IS 'Momentum threshold to trigger entry (e.g., 35.0 for ±35%). Positive spike enters YES ITM strikes, negative spike enters NO ITM strikes';
COMMENT ON COLUMN users.monitor_list_0001.momentum_scalp_trailing_stop_amount IS 'Trailing stop amount in dollars (e.g., 0.10 for 10 cents). Applied to both YES and NO contracts';
COMMENT ON COLUMN users.monitor_list_0001.momentum_scalp_profit_target IS 'Profit target as position value (e.g., 0.99 for $0.99). Hard cap - closes immediately when reached';
```

---

## Strategy Comparison

| Aspect | Hourly BTC | Momentum Scalp |
|--------|------------|----------------|
| **Spike Behavior** | Pauses entries on spikes | Enters on spikes |
| **Entry Trigger** | TTC window + probability + differential | Momentum spike + ITM status |
| **TTC Window** | Required (min_time to max_time) | Not used |
| **Probability Check** | Required (min_probability) | Not used |
| **Differential Check** | Required (min/max_differential) | Not used |
| **Strike Selection** | Any strike meeting criteria | Only ITM strikes (deepest first) |
| **Position Count** | Typically one at a time | Multiple simultaneous |
| **Entry Timing** | Within TTC window | Immediately on spike |
| **Exit Method** | Probability threshold or hold to expiration | Trailing stop + profit target |
| **Exit Timing** | Can hold until expiration | Quick scalps (seconds/minutes) |
| **Trailing Stop** | Not used | 10 cent trailing stop |
| **Profit Target** | Not used | Hard cap (e.g., $0.99) |
| **Duplicate Prevention** | Yes (pending + open) | Yes (reuse same logic) |

## Open Questions

1. **Momentum Source**: Use `momentum_percentile` or `momentum_5s_avg`? (Currently using 5s avg for spike detection in Hourly BTC)
2. **Position Sizing**: Same as Hourly BTC or different logic?
3. **Capital Limits**: Any maximum capital allocation for Momentum Scalp vs Hourly BTC?

---

## Implementation Details

### Strike Selection Algorithm

```python
def get_eligible_momentum_scalp_strikes(momentum, symbol_price, strike_table_data):
    """
    Get eligible strikes for Momentum Scalp entry
    
    Returns: List of strikes sorted by distance from money line (deepest ITM first)
    """
    eligible_strikes = []
    
    # Determine direction based on momentum
    if momentum >= entry_threshold:
        # Positive spike - enter YES strikes ITM
        direction = 'yes'
        for strike in strike_table_data['strikes']:
            strike_price = float(strike['strike'])
            if strike_price < symbol_price and strike['side'] == 'yes':
                # ITM YES strike
                distance_from_money = symbol_price - strike_price
                eligible_strikes.append({
                    'strike': strike,
                    'distance': distance_from_money
                })
    elif momentum <= -entry_threshold:
        # Negative spike - enter NO strikes ITM
        direction = 'no'
        for strike in strike_table_data['strikes']:
            strike_price = float(strike['strike'])
            if strike_price > symbol_price and strike['side'] == 'no':
                # ITM NO strike
                distance_from_money = strike_price - symbol_price
                eligible_strikes.append({
                    'strike': strike,
                    'distance': distance_from_money
                })
    
    # Sort by distance (deepest ITM first)
    eligible_strikes.sort(key=lambda x: x['distance'], reverse=True)
    
    # Filter by volume and check duplicates
    final_strikes = []
    for item in eligible_strikes:
        strike = item['strike']
        if strike['volume'] >= min_volume:
            if not is_strike_already_traded(strike):
                final_strikes.append(strike)
    
    return final_strikes
```

### Entry Flow

1. Check momentum against threshold
2. If spike detected, get eligible ITM strikes (sorted deepest first)
3. Enter all eligible strikes immediately
4. Continue monitoring for new ITM strikes while momentum stays above threshold

### Exit Flow

1. Every monitoring cycle, check each Momentum Scalp trade:
   - Calculate current position value
   - Check trailing stop: `position_value < (high_price - 0.10)`
   - Check profit target: `position_value >= 0.99`
2. If either condition met, trigger close immediately
3. Freed capital can be used for new entries

## Next Steps

1. ✅ **Review this plan** - Complete
2. ✅ **Finalize Momentum Scalp requirements** - Complete
3. **Create database migration** - Add new fields to monitor_list
4. **Implement strategy routing** - Add detection and routing logic
5. **Implement Momentum Scalp logic** - Add new entry/exit functions
6. **Add UI controls** - Update frontend for strategy selection
7. **Test thoroughly** - Ensure Hourly BTC unaffected
8. **Deploy** - Roll out incrementally

---

## Notes

- All existing Hourly BTC functionality must remain **100% unchanged**
- Strategy detection should be fast (cache if needed)
- Error handling: Default to Hourly BTC on any error
- Logging: Clearly mark which strategy logic is executing
- Performance: Strategy checks should not impact monitoring loop speed
