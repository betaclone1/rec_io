# Strategy Switch Framework Analysis

## Proposed Framework

### Rule 1: Momentum Breakout (Full Position)
**Condition:** 3-hour average absolute volatility between 50-70 percentile
- Use full position size
- Standard Momentum Breakout strategy (YES above money line, NO below money line)

### Rule 2: Momentum Contain (Inverted Strategy)
**Condition:** 2-hour average absolute momentum below 40 percentile
- Invert Y and N sides
- Bet on regression into channel (opposite of breakout)

### Combined Logic:
- If Volatility 50-70 (3h) AND Momentum >= 40 (2h): Momentum Breakout
- If Momentum < 40 (2h): Momentum Contain (regardless of volatility)
- Otherwise: No Trade

---

## Framework Performance Analysis

### Trade Entry Rate
- **Total Cycles:** 211
- **Cycles Meeting Framework Conditions:** 76 cycles (36.02%)
- **Breakdown:**
  - Volatility 50-70 (3h): 69 cycles
  - Momentum < 40 (2h): 7 cycles
  - Overlap (both conditions): Need to check
  - Total unique: 76 cycles

### Actual Performance Breakdown (Current Strategy)

**Momentum Breakout (Vol 50-70, Mom >= 40):**
- **69 cycles**
- **71.01% win rate** (49 wins, 20 losses)
- **+$519.25 total PnL** (+$7.53 avg cycle PnL)
- ✅ **EXCEEDS 70% profitability threshold**

**Momentum Contain (Mom < 40, 2h):**
- **7 cycles**
- **28.57% win rate** (2 wins, 5 losses)
- **-$220.43 total PnL** (-$31.49 avg cycle PnL)
- ⚠️ **Currently losing, but would be INVERTED**

**No Trade (Other conditions):**
- **135 cycles**
- 57.04% win rate (77 wins, 58 losses)
- -$722.91 total PnL (-$5.35 avg cycle PnL)

### Key Finding: No Overlap
- **0 cycles** meet BOTH conditions simultaneously
- This means the conditions are mutually exclusive
- No need to define priority - each cycle goes to exactly one category

### Expected Performance with Inversion

**If Momentum Contain is inverted (betting on regression):**
- Current: 28.57% win rate → **Inverted: 71.43% win rate** (if inversion works perfectly)
- Current: -$31.49 avg PnL → **Inverted: +$31.49 avg PnL** (if inversion works perfectly)
- **7 cycles × +$31.49 = +$220.43 total PnL** (flip from -$220.43)

**Combined Framework Performance (if inversion works):**
- Momentum Breakout: +$519.25
- Momentum Contain (inverted): +$220.43
- **Total: +$739.68** from 76 cycles
- **Average: +$9.73 per cycle**

---

## Key Considerations

### 1. Momentum Contain Strategy Validation Needed

The framework assumes that inverting the strategy when momentum < 40 will work. This needs validation:
- Current performance with momentum < 40: 28.57% win rate
- If inverted, would this become 71.43% win rate?
- Need to test if the inverse logic actually works

### 2. Overlap Between Conditions

- Some cycles may meet BOTH conditions (Vol 50-70 AND Mom < 40)
- Need to define priority: Which strategy takes precedence?

### 3. Framework Coverage

- ~38% of cycles meet the conditions
- ~62% of cycles would be skipped
- This is a significant reduction in trade frequency

---

## Recommended Next Steps

1. **Validate Momentum Contain Logic:**
   - Test if inverting the strategy when momentum < 40 actually improves performance
   - May need to analyze what happens when momentum is low - does price regress?

2. **Define Priority Rules:**
   - If both conditions met, which strategy takes precedence?
   - Suggested: Momentum Contain takes priority (more specific condition)

3. **Backtest the Framework:**
   - Calculate expected PnL if:
     - Momentum Breakout: Use actual performance (71.01% win rate)
     - Momentum Contain: Use inverted performance (assume 71.43% win rate if inversion works)

4. **Consider Additional Filters:**
   - The framework currently covers ~38% of cycles
   - May want to add more conditions to increase coverage
   - Or refine conditions to improve win rate

---

## Framework Logic Flow

```
IF abs_momentum_2h < 40:
    → Use Momentum Contain Strategy (invert sides, bet on regression)
ELSE IF abs_volatility_3h >= 50 AND abs_volatility_3h < 70:
    → Use Momentum Breakout Strategy (full position)
ELSE:
    → No Trade
```

## Summary Statistics

| Metric | Value |
|--------|-------|
| Total Cycles | 211 |
| Cycles Traded | 76 (36.02%) |
| Cycles Skipped | 135 (63.98%) |
| Momentum Breakout Cycles | 69 (32.70%) |
| Momentum Contain Cycles | 7 (3.32%) |
| Overlap (Both Conditions) | 0 (0%) |

## Current vs Framework Performance

| Scenario | Cycles | Win Rate | Total PnL |
|----------|--------|----------|-----------|
| **Baseline (All Trades)** | 211 | 60.66% | -$424.09 |
| **Framework (Current Strategy)** | 76 | 67.11% | +$298.82 |
| **Framework (If Inversion Works)** | 76 | ~71% | +$739.68 |

**Improvement:**
- Current framework: +$298.82 vs baseline -$424.09 = **+$722.91 improvement**
- If inversion works: +$739.68 vs baseline -$424.09 = **+$1,163.77 improvement**
