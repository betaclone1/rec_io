# Auto Entry Supervisor - HOURLY HTC Audit

**Date**: 2025-01-27  
**Purpose**: Thorough audit of `auto_entry_supervisor.py` to understand current HOURLY HTC implementation before adding MOMENTUM SCALP strategy support

---

## Architecture Overview

### Entry Point
- **Main Function**: `start_event_driven_supervisor()` (line 2401)
- **Monitoring Loop**: `start_monitoring_loop()` → `monitoring_worker()` (lines 2188-2238)
- **Loop Frequency**: 1 second intervals (`time.sleep(1)`)

### Key Components
1. **Strategy Detection**: `get_trade_strategy()` (line 1684) - **Currently UNUSED in entry logic**
2. **Settings Retrieval**: `get_auto_entry_settings()` (line 1196)
3. **Entry Condition Check**: `check_auto_entry_conditions()` (line 1959)
4. **Spike Alert System**: `check_spike_alert_conditions()` (line 751)
5. **Trade Triggering**: `trigger_auto_entry_trade()` (line 1738)

---

## HOURLY HTC Entry Logic (Hard-Wired)

### Main Entry Function: `check_auto_entry_conditions()`

**Location**: Line 1959  
**Current Status**: Hard-wired for HOURLY HTC strategy

#### Execution Flow

1. **Spike Alert Check** (line 1967)
   - Calls `check_spike_alert_conditions()`
   - **HOURLY HTC Behavior**: Pauses all entries when momentum spikes detected
   - Blocks all trades if `spike_alert_active == True`

2. **Get Strike Table Data** (line 1969)
   - Fetches master strike table JSON file
   - Updates monitor state

3. **Check Auto Trade Enabled** (line 1974)
   - Calls `is_auto_trade_enabled()` (checks `monitor_list.auto_trade` boolean)

4. **Get Settings** (line 1997)
   - Calls `get_auto_entry_settings()`
   - **Required Settings for HOURLY HTC** (line 2000):
     - `min_time` (TTC window start)
     - `max_time` (TTC window end)
     - `min_probability` (minimum win probability)
     - `min_differential` (minimum price differential)
   - **Optional Settings**:
     - `max_differential` (maximum price differential)
     - `min_volume` (minimum volume threshold)
     - `max_ask` (maximum ask price - defaults to 98 cents)

5. **TTC Window Check** (lines 2012-2016)
   - Gets current TTC from unified endpoint
   - **HOURLY HTC Requirement**: `min_time <= current_ttc <= max_time`
   - If TTC not in window → **EXIT** (line 2041)

6. **Spike Alert Block** (lines 2044-2047)
   - If spike alert active → **EXIT** (blocks all trades)
   - **HOURLY HTC Behavior**: Spike alert pauses entries

7. **Strike Processing Loop** (lines 2055-2167)
   - Iterates through all strikes in strike table
   - **Processes strikes ONE AT A TIME** (sequential entry)
   - **HOURLY HTC Filters Applied**:
     - **Step 1**: Cooldown check (`can_trade_strike()`)
     - **Step 2**: Duplicate check (`is_strike_already_traded()`)
     - **Step 3**: Probability filter (`prob >= min_probability`)
     - **Step 4**: Min differential filter (`diff >= min_differential - 0.5`)
     - **Step 4.5**: Max differential filter (`diff <= max_differential`)
     - **Step 5**: Volume filter (`volume >= min_volume`)
     - **Step 6**: Max ask price filter (`max_ask_price <= max_ask`)
   - **Strike Selection**: ANY strike meeting all criteria
   - **Entry Direction**: Based on `active_side` (YES or NO)

8. **Trade Triggering** (line 2158)
   - Calls `trigger_auto_entry_trade()` for each eligible strike
   - **HOURLY HTC Behavior**: One trade at a time, sequential

---

## HOURLY HTC-Specific Hard-Coded Assumptions

### 1. TTC Window Requirement (CRITICAL)
- **Line 2016**: `ttc_within_window = min_time <= current_ttc <= max_time`
- **Line 2041**: Early exit if TTC not in window
- **Assumption**: HOURLY HTC **requires** TTC window - no trades outside window

### 2. Differential Requirements (CRITICAL)
- **Line 2089-2092**: Minimum differential check
- **Line 2094-2100**: Maximum differential check
- **Assumption**: HOURLY HTC **requires** differential filters - no trades without differential

### 3. Probability Requirement (CRITICAL)
- **Line 2083-2086**: Probability threshold check
- **Assumption**: HOURLY HTC **requires** probability filter

### 4. Spike Alert Behavior (CRITICAL)
- **Line 1967**: Spike alert checked FIRST
- **Line 2044-2047**: Spike alert blocks ALL trades
- **Assumption**: HOURLY HTC **pauses** on momentum spikes (opposite of MOMENTUM SCALP)

### 5. Sequential Entry (CRITICAL)
- **Line 2055**: `for i, strike in enumerate(strike_table_data["strikes"])`
- **Line 2158**: `trigger_auto_entry_trade()` called once per iteration
- **Assumption**: HOURLY HTC enters **ONE strike at a time**, sequentially

### 6. Any Strike Selection (CRITICAL)
- **Line 2055-2167**: Processes ALL strikes, enters ANY that meet criteria
- **Assumption**: HOURLY HTC can enter **any strike** meeting filters (not ITM-specific)

### 7. Active Side Selection (CRITICAL)
- **Line 2058-2062**: Uses `active_side` from strike data
- **Line 2123-2140**: Chooses YES or NO based on `active_side`
- **Assumption**: HOURLY HTC uses **active_side** to determine entry direction (not momentum-based)

### 8. Settings Required Check (CRITICAL)
- **Line 2000**: `required_settings = ["min_time", "max_time", "min_probability", "min_differential"]`
- **Assumption**: HOURLY HTC **requires** these settings - exits if missing

---

## Settings Retrieval: `get_auto_entry_settings()`

**Location**: Line 1196  
**Current Behavior**: Loads HOURLY HTC settings from `monitor_list_0001`

### Settings Retrieved (Line 1218-1222)
```python
SELECT min_probability, min_differential, max_differential, min_time, max_time, allow_re_entry,
       spike_alert_enabled, spike_alert_momentum_threshold, 
       spike_alert_cooldown_threshold, spike_alert_cooldown_minutes,
       min_volume
FROM users.monitor_list_0001 WHERE id = %s
```

### Settings Structure (Lines 1227-1240)
```python
{
    "min_probability": ...,
    "min_differential": ...,
    "max_differential": ...,
    "min_time": ...,
    "max_time": ...,
    "allow_re_entry": ...,
    "spike_alert_enabled": ...,
    "spike_alert_momentum_threshold": ...,
    "spike_alert_cooldown_threshold": ...,
    "spike_alert_cooldown_minutes": ...,
    "min_volume": ...,
    "max_ask": 98  # Hard-coded default
}
```

### Key Observations
- **Strategy Detection**: Reads `strategy` field (line 1209) but **DOES NOT USE IT**
- **Settings Are Strategy-Agnostic**: Returns same settings regardless of strategy
- **No Strategy-Specific Routing**: Does not route to different settings based on strategy

---

## Spike Alert System: `check_spike_alert_conditions()`

**Location**: Line 751  
**Purpose**: HOURLY HTC-specific feature that **pauses entries** on momentum spikes

### Behavior
1. **Detection** (lines 831-832): `momentum >= threshold OR momentum <= -threshold`
2. **Action** (line 842): Sets `spike_alert_active = True`
3. **Blocking** (line 2044-2047): Blocks **ALL** trades when active
4. **Recovery** (lines 854-877): Waits for cooldown period before resuming

### Settings Used
- `spike_alert_enabled` (line 802)
- `spike_alert_momentum_threshold` (line 803)
- `spike_alert_cooldown_threshold` (line 804)
- `spike_alert_cooldown_minutes` (line 805)

### HOURLY HTC Assumption
- **Spike Alert = PAUSE** entries (opposite of MOMENTUM SCALP which should ACTIVATE on spikes)

---

## Trade Triggering: `trigger_auto_entry_trade()`

**Location**: Line 1738  
**Status**: Strategy-agnostic (can be reused)

### Flow
1. Gets contract name from strike table
2. Gets position size from trade preferences
3. **Loss Prevention Check** (lines 1763-1768): Overrides position size if `loss_prevention == "one_contract"`
4. Gets bankroll allotment from monitor
5. Creates trade payload and calls trade_manager API

### HOURLY HTC-Specific Elements
- **Loss Prevention**: Checked and applied (line 1763)
- **Position Size**: Uses configured position size (unless loss prevention active)

---

## State Management

### Global State: `auto_entry_indicator_state` (Lines 507-521)
```python
{
    "enabled": False,
    "ttc_within_window": False,
    "scanning_active": False,
    "service_healthy": False,
    "spike_alert_active": False,
    "spike_alert_start_time": None,
    "spike_alert_momentum_value": None,
    "spike_alert_recovery_countdown": None,
    "current_momentum": None,
    "current_ttc": 0,
    "min_time": 0,
    "max_time": 3600,
    "last_updated": None
}
```

### Database State: `load_auto_entry_state_from_db()` / `save_auto_entry_state_to_db()`
- Stores spike alert state in `monitor_list_0001` table
- Includes cooldown timer and spike detection state

---

## Strategy Detection: `get_trade_strategy()`

**Location**: Line 1684  
**Status**: EXISTS but **NOT USED** in entry logic

### Behavior
- Reads `strategy` field from `monitor_list_0001`
- Returns strategy name or defaults to `"Hourly HTC"` (line 1703, 1706)
- **Currently not called anywhere in entry logic**

---

## Key Findings: What Makes This HOURLY HTC-Specific

### 1. Entry Conditions Are Hard-Wired
- TTC window check is **required** (line 2041)
- Differential check is **required** (lines 2089-2100)
- Probability check is **required** (lines 2083-2086)
- **No strategy routing** - all logic assumes HOURLY HTC

### 2. Spike Alert System Is HOURLY HTC-Specific
- Spike alert **pauses** entries (HOURLY HTC behavior)
- MOMENTUM SCALP needs **opposite** behavior (activate on spikes)

### 3. Sequential Entry Processing
- Processes strikes **one at a time** (line 2055)
- Enters **single strike** per check cycle
- MOMENTUM SCALP needs **multiple simultaneous** entries

### 4. Any Strike Selection
- Can enter **any strike** meeting criteria
- MOMENTUM SCALP needs **ITM strikes only** (specific side based on momentum)

### 5. Active Side Selection
- Uses `active_side` from strike data
- MOMENTUM SCALP needs **momentum-based** direction selection

### 6. Settings Structure Is HOURLY HTC-Specific
- Returns HOURLY HTC settings (differential, spike alert, etc.)
- Does not include MOMENTUM SCALP settings (entry threshold, trailing stop, profit target)

---

## What Needs to Stay Untouched (HOURLY HTC)

### Functions to Preserve As-Is
1. `check_auto_entry_conditions()` - **RENAME** to `check_auto_entry_conditions_hourly_htc()`
2. `check_spike_alert_conditions()` - **KEEP** for HOURLY HTC only
3. `get_auto_entry_settings()` - **KEEP** but add strategy routing
4. `trigger_auto_entry_trade()` - **REUSE** (strategy-agnostic)
5. `is_strike_already_traded()` - **REUSE** (strategy-agnostic)
6. `can_trade_strike()` - **REUSE** (strategy-agnostic)
7. `get_current_ttc()` - **REUSE** (strategy-agnostic)
8. `get_current_momentum()` - **REUSE** (strategy-agnostic)

### Hard-Coded Values to Preserve
- `TRADE_COOLDOWN = 10` (line 504)
- `max_ask = 98` default (line 1239)

---

## Implementation Strategy for MOMENTUM SCALP

### 1. Add Strategy Router
- Modify `check_auto_entry_conditions()` to detect strategy and route
- Call `check_auto_entry_conditions_hourly_htc()` for HOURLY HTC
- Call `check_auto_entry_conditions_momentum_scalp()` for MOMENTUM SCALP

### 2. Create MOMENTUM SCALP Entry Function
- New function: `check_auto_entry_conditions_momentum_scalp()`
- **Different Logic**:
  - TTC window: **REQUIRED** (same as HOURLY HTC per implementation doc)
  - Momentum spike: **ACTIVATES** entry (opposite of spike alert)
  - ITM strike filtering: **REQUIRED** (YES ITM for up spike, NO ITM for down spike)
  - No differential check
  - Multiple simultaneous entries
  - Probability-based sorting

### 3. Add Strategy-Specific Settings Getter
- New function: `get_momentum_scalp_entry_settings()`
- Returns MOMENTUM SCALP-specific settings:
  - `momentum_scalp_entry_threshold`
  - `min_time`, `max_time` (shared)
  - `min_probability` (shared)
  - `min_volume` (shared)

### 4. Modify Settings Router
- Update `get_auto_entry_settings()` to route based on strategy
- Or create separate getters for each strategy

---

## Summary: HOURLY HTC Entry Flow

```
1. Check spike alert (PAUSES if active)
2. Get settings (HOURLY HTC-specific)
3. Check TTC window (REQUIRED - exit if not in window)
4. Check spike alert again (BLOCKS if active)
5. Loop through strikes:
   - Check cooldown
   - Check duplicates
   - Check probability
   - Check min differential
   - Check max differential
   - Check volume
   - Check max ask price
   - Enter strike (ONE AT A TIME)
6. Repeat every 1 second
```

---

## Critical Notes for Implementation

1. **Strategy Detection Exists But Unused**: `get_trade_strategy()` exists but is not called in entry logic
2. **No Strategy Routing**: Entry logic assumes HOURLY HTC always
3. **Complete Separation Required**: MOMENTUM SCALP logic must be completely separate
4. **Preserve HOURLY HTC**: All existing logic must remain untouched
5. **Default Fallback**: Unknown strategies should default to HOURLY HTC

