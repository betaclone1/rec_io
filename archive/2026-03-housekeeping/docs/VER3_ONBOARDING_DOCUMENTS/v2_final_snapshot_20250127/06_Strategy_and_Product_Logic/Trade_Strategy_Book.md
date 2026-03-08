# Trade Strategy Book – REC.IO v2

## Purpose
Document REC.IO v2's primary trading strategy and provide a foundation for v3's multi-strategy, multi-market architecture.

---

## 1. Strategy: HOURLY HTC (Hold Til Close)

### 1.1 Overview
HOURLY HTC is the core v2 trading strategy. It operates in Kalshi's hourly BTC binary markets, entering positions based on real-time price, momentum, and volatility conditions, and holding until market settlement.

**Market Code Format**: `KXBTCD-DDMMMHHMM`  
Example: `KXBTCD-25JUN2010` (settles at 20:10 UTC)

### 1.2 Instruments & Markets
- **Underlying**: BTC-USD
- **Market**: Kalshi hourly binary contracts
- **Time Frame**: Positions opened within hour, held to expiry

### 1.3 Entry Logic
1. **Monitor Target Market** (ATM and near-ATM strikes)
2. **Calculate Adjusted Buffer per Minute (ABPM)**:
   - Base buffer from historical price movement probabilities
   - Adjusted by momentum and volatility
3. **Signal from Auto Entry Supervisor**:
   - If calculated win probability > market ask price probability → enter position
4. **Order Flow**:
   - Trade Manager logs trade → Trade Executor sends order to Kalshi API

**Inputs**:
- BTC price feed (btc_price_watchdog)
- Kalshi market data (kalshi_api_watchdog)
- Probability model output
- Momentum/volatility scores

### 1.4 Stop Logic
- v2: No automated stop; manual close via Active Trade Supervisor UI
- v2 planned enhancement: Auto-stop triggers based on:
  - Price crossing pre-defined threshold
  - Momentum reversal
- v3: Fully integrated auto-stop per strategy/monitor

### 1.5 Parameters
- **Base Probability Threshold**: 96%+ for near-expiry trades (modifiable)
- **Volatility Flag**: 0.03% stddev over 30s default
- **Momentum Bias**: Weighted directional score, used to tilt probability
- **ABPM Adjustment Factors**: Derived from backtest fingerprints

**Note**: Values above are current v2 defaults and subject to tuning.

### 1.6 Calculation Breakdown (ABPM)
1. Historical movement probability at given TTC (time-to-close) and buffer
2. Adjust probability by current momentum factor
3. Adjust by volatility flag (reduce entry aggressiveness if flagged)
4. Compare final probability to market ask

---

## 2. Trade Lifecycle (v2)
1. **Signal Generation** → Auto Entry Supervisor
2. **Trade Creation** → Trade Manager (PostgreSQL write)
3. **Order Execution** → Trade Executor (Kalshi API)
4. **Monitoring** → Active Trade Supervisor (real-time PnL & TTC)
5. **Settlement** → Position closed at expiry, win/loss logged

---

## 3. v3 Strategy Framework

### 3.1 Multi-Monitor, Multi-Strategy Architecture
- Each user can run multiple **monitors**, each assigned a strategy
- Strategies can be applied to any supported instrument & market
- Example: BTC HOURLY HTC + ETH 15-min scalper + SPY daily swing

### 3.2 Strategy Customization
- Adjustable parameters per monitor:
  - Probability thresholds
  - Buffer/momentum weighting
  - Auto-stop behavior
  - Risk per trade
- Saved strategies tied to user profile

### 3.3 Backtesting Integration
- Historical data fingerprinting for each instrument/market
- Custom backtest runs with current or proposed strategy parameters
- Retention of successful strategies in user’s strategy library

### 3.4 Planned v3 Enhancements to HOURLY HTC
- Parameter sliders in UI for ABPM adjustments
- Automated stop-loss and take-profit
- Dynamic position sizing based on live win probability
- Cross-market hedging

---

## 4. Strategy Template (for adding more in v3)
**Strategy Name**:  
**Overview**:  
**Markets**:  
**Entry Logic**:  
**Stop Logic**:  
**Parameters**:  
**Calculation Breakdown**:  
**Lifecycle**:  
**Performance Notes**:  
