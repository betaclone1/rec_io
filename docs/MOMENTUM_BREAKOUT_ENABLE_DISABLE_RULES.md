# Momentum Breakout Strategy - Enable/Disable Rules

## Analysis Summary

**Data Analyzed:**
- 497 cycles (312 wins, 185 losses)
- 62.78% overall win rate (below 70% threshold)
- Date range: Dec 19, 2025 - Feb 4, 2026 (44 trading days)

**Goal:** Identify signals to ENABLE/DISABLE strategy to maximize PnL

---

## TOP 3 MOST PREDICTIVE SIGNALS

### 1. Daily Regime Pattern ⭐⭐⭐ (STRONGEST)

**Finding:**
- After day with < 50% win rate: Next day = 36.63% win rate
- After day with >= 70% win rate: Next day = 78.38% win rate

**Rule:**
```
IF previous_trading_day_win_rate < 50%:
    DISABLE strategy
ELSE IF previous_trading_day_win_rate >= 70%:
    ENABLE strategy
```

**Impact:** This single rule could eliminate many losing cycles.

### 2. Momentum Reversal Pattern ⭐⭐⭐

**Finding:**
- Accounts for **49.73% of all losing cycles**
- Losing cycles: Momentum was positive 30m before, reversed to negative at entry
- Winning cycles: Momentum was negative 30m before, continued negative at entry

**Rule:**
```
IF momentum_30m_before > 0 AND momentum_at_entry < 0:
    DISABLE strategy (momentum reversal - high risk)
ELSE IF momentum_30m_before < 0 AND momentum_at_entry < momentum_30m_before:
    ENABLE strategy (momentum continuation - high confidence)
```

**Impact:** Could prevent ~50% of losing cycles.

### 3. Price Movement Before Entry ⭐⭐

**Finding:**
- Winning cycles: Price falling in 30 minutes before entry (-0.15%)
- Losing cycles: Price rising in 30 minutes before entry (+0.03%)

**Rule:**
```
IF price_change_30m_before > 0:
    DISABLE strategy (price rising before entry - weak signal)
ELSE IF price_change_30m_before < -0.1%:
    ENABLE strategy (price falling before entry - strong signal)
```

---

## COMPLETE ENABLE/DISABLE RULE SET

### Priority 1: Daily Regime Check (Run First)

```python
def should_enable_daily_regime():
    prev_day_win_rate = get_previous_trading_day_win_rate()
    
    if prev_day_win_rate < 50:
        return False  # DISABLE - bad regime
    elif prev_day_win_rate >= 70:
        return True   # ENABLE - good regime
    else:
        return None   # Continue to other checks
```

### Priority 2: Momentum Pattern Check

```python
def should_enable_momentum_pattern():
    momentum_30m_before = get_momentum_30m_before_entry()
    momentum_at_entry = get_momentum_at_entry()
    
    # Momentum reversal = BAD
    if momentum_30m_before > 0 and momentum_at_entry < 0:
        return False  # DISABLE - momentum reversing
    
    # Momentum continuation = GOOD
    if momentum_30m_before < 0 and momentum_at_entry < momentum_30m_before:
        return True   # ENABLE - momentum accelerating
    
    return None  # Continue to other checks
```

### Priority 3: Price Movement Check

```python
def should_enable_price_movement():
    price_change_30m = get_price_change_30m_before_entry()
    
    if price_change_30m > 0:
        return False  # DISABLE - price rising
    elif price_change_30m < -0.1:
        return True   # ENABLE - price falling significantly
    else:
        return None   # Continue to other checks
```

### Priority 4: Time-Based Filters

```python
def should_enable_time_based():
    hour = get_current_hour()
    day_of_week = get_current_day_of_week()
    
    # Hard DISABLE times
    if hour in [0, 3]:  # Midnight, 3 AM
        return False
    
    # Strong ENABLE times
    if hour == 8:  # 8 AM - 83.33% win rate
        return True
    if day_of_week == 'Sunday':  # 75.95% win rate
        return True
    if hour in [13, 15, 19, 20]:  # 70-75% win rate
        return True
    
    # Weak times - DISABLE unless other signals strong
    if hour in [14, 18, 21]:  # 41-47% win rate
        return False
    if day_of_week == 'Monday':  # 54.29% win rate
        return False
    
    return None  # Continue to other checks
```

### Priority 5: Combination Rules (Hard Blocks)

```python
def should_enable_combination_rules():
    hour = get_current_hour()
    day = get_current_day_of_week()
    momentum = get_momentum_percentile_at_entry()
    
    # Hard DISABLE combinations (0% win rate)
    bad_combinations = [
        (15, 'Wednesday', '< -50'),  # Hour 15 Wed + Bearish
        (10, 'Wednesday', '50-80'),  # Hour 10 Wed + Bullish
        (12, 'Monday', '< -50'),     # Hour 12 Mon + Bearish
        (17, 'Tuesday', '< -50'),    # Hour 17 Tue + Bearish
        (14, 'Friday', '-50 to 0'),  # Hour 14 Fri + Mild Bearish
        (11, 'Tuesday', '-50 to 0'), # Hour 11 Tue + Mild Bearish
    ]
    
    for bad_hour, bad_day, bad_momentum in bad_combinations:
        if hour == bad_hour and day == bad_day and matches_momentum(momentum, bad_momentum):
            return False  # DISABLE
    
    return None  # Continue to other checks
```

---

## COMPLETE DECISION TREE

```python
def should_enable_momentum_breakout():
    """
    Complete enable/disable logic for Momentum Breakout strategy.
    Returns: True (enable), False (disable), or None (use default)
    """
    
    # Priority 1: Daily Regime
    daily_check = should_enable_daily_regime()
    if daily_check is not None:
        return daily_check
    
    # Priority 2: Momentum Pattern
    momentum_check = should_enable_momentum_pattern()
    if momentum_check is not None:
        return momentum_check
    
    # Priority 3: Price Movement
    price_check = should_enable_price_movement()
    if price_check is not None:
        return price_check
    
    # Priority 4: Time-Based
    time_check = should_enable_time_based()
    if time_check is not None:
        return time_check
    
    # Priority 5: Combination Rules
    combo_check = should_enable_combination_rules()
    if combo_check is not None:
        return combo_check
    
    # Default: Enable if no strong signals (conservative approach)
    # OR: Disable if no strong signals (aggressive approach)
    return False  # Conservative: disable by default
```

---

## EXPECTED IMPACT

### If we DISABLE on:
1. **Previous day < 50% win rate:** Eliminates ~64 losing cycles (36.63% win rate days)
2. **Momentum reversal pattern:** Eliminates ~92 losing cycles (49.73% of all losses)
3. **Bad time combinations:** Eliminates ~20-30 losing cycles (hour 14, Mondays, etc.)

### Potential Improvement:
- Current: 62.78% win rate
- Target: 70%+ win rate
- Estimated improvement: Could increase win rate by 7-10 percentage points

---

## IMPLEMENTATION NOTES

1. **Daily Regime:** Calculate at start of each trading day
2. **Momentum Pattern:** Check in real-time before each trade entry
3. **Price Movement:** Check in real-time before each trade entry
4. **Time-Based:** Simple time/day checks
5. **Combination Rules:** Check all factors together

---

## VALIDATION REQUIRED

Before implementing:
1. Backtest these rules against historical data
2. Calculate expected win rate improvement
3. Calculate expected PnL improvement
4. Test edge cases and false positives/negatives

---

## NEXT STEPS

1. **Build Real-Time Monitoring:** Create system to track daily win rates
2. **Implement Momentum Checks:** Add 30-minute momentum lookback
3. **Add Price Movement Checks:** Track price changes before entry
4. **Test & Refine:** Validate rules and adjust thresholds
5. **Deploy:** Integrate into auto-entry supervisor
