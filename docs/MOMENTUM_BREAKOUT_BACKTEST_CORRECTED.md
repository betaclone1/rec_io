# Momentum Breakout Strategy - Corrected Backtest Results

## Correction

After verifying the math, the backtest results are **NOT as positive as initially calculated**.

## Corrected Results

### Backtest Performance
- **Total Trades:** 498
- **Actual Total PnL:** -$278.08
- **Backtest Total PnL:** **-$445.72**
- **Difference:** **-$167.64** (WORSE, not better)

### Breakdown
- **Trades with Size 100:** 162 trades → -$449.00 PnL
- **Trades with Size 1:** 336 trades → +$3.28 PnL
- **Average PnL per Size 100 trade:** -$2.77
- **Average PnL per Size 1 trade:** +$0.01

## Why It Performed Worse

### The Problem
1. **False Positives:** Many days after a 70%+ win rate day still lost money:
   - Dec 28 (after 100% day): 50% win rate, -$59.04 actual PnL
   - Jan 4 (after 100% day): 28.57% win rate, -$87.01 actual PnL
   - Jan 7 (after 71.43% day): 0% win rate, -$323.18 actual PnL
   - Jan 9 (after 83.33% day): 40% win rate, -$337.82 actual PnL
   - Jan 12 (after 75% day): 33.33% win rate, -$209.44 actual PnL
   - Jan 19 (after 100% day): 0% win rate, -$90.72 actual PnL
   - Jan 23 (after 80% day): 42.86% win rate, -$224.68 actual PnL
   - Jan 27 (after 83.33% day): 57.14% win rate, -$5.60 actual PnL
   - Jan 31 (after 87.5% day): 63.64% win rate, -$90.48 actual PnL
   - Feb 2 (after 92.86% day): 63.64% win rate, -$15.08 actual PnL

2. **Scaling Losses:** When we used position size 100 on losing days, losses were amplified.

3. **Reducing Wins:** When we used position size 1 on winning days, wins were minimized.

### The Math
- **Actual average position size:** ~95 (ranges from 56 to 164)
- **Backtest position sizes:** 1 or 100
- When actual position was ~144 and we use 100, we're reducing position size
- When actual position was ~56 and we use 100, we're increasing position size
- **Net effect:** We increased position size on more losing trades than winning trades

## Key Insight

**The previous day's win rate is NOT a reliable predictor of the next day's performance.**

Many days after a strong win rate (70%+) still resulted in losses. This suggests:
1. The regime might not persist day-to-day
2. Other factors (momentum patterns, price movement, etc.) may be more important
3. The daily win rate signal alone is not sufficient

## What This Means

The position sizing rule based solely on previous day's win rate:
- ❌ Does NOT improve performance
- ❌ Actually makes performance worse (-$167.64 worse)
- ❌ Has too many false positives (days after 70%+ win rate that still lose)

## Alternative Approaches

Based on the earlier analysis, we found stronger signals:
1. **Momentum reversal pattern** (accounts for 49.73% of losses)
2. **Price movement before entry** (falling price = better)
3. **Time-based patterns** (certain hours/days perform better)

These might be more reliable than daily win rate for position sizing decisions.

## Conclusion

The backtest shows that using previous day's win rate for position sizing **does not work** and actually makes performance worse. The daily regime pattern, while interesting, is not strong enough to use for position sizing decisions.

We should explore other signals (momentum patterns, price movement, time-based) for enable/disable rules instead.
