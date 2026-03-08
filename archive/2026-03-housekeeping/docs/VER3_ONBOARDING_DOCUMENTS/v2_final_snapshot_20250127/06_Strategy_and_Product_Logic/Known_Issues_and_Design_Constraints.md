# Known Issues & Design Constraints – REC.IO v2

## Purpose
List current v2 technical debt, edge cases, and architectural constraints so BMAD can plan remediation in v3.

---

## 1. Technical Debt (v2)

### 1.1 Legacy Components
- **SQLite writes** still present in `btc_price_watchdog.py`, `kalshi_historical_ingest.py`
- **JSON snapshots** used for Kalshi market data (`kalshi_api_watchdog.py`)
- **Symbol Price Watchdog** (legacy BTC/ETH) still in supervisor config

### 1.2 Error Handling Gaps
- Inconsistent logging formats
- Minimal context in exceptions for some API failures
- No global error handler or escalation path

### 1.3 Configuration & Environment
- `.env` files in plaintext on production servers
- No automatic config validation on startup

### 1.4 Process Management
- Services rely on manual ordering in supervisor config
- No dependency-aware restart logic

### 1.5 Testing & QA
- No automated integration testing in CI/CD
- Manual verification required after deploy

---

## 2. Edge Cases / Brittle Logic

### 2.1 Market Data Gaps
- BTC price feed reconnection can stall without manual restart
- Kalshi market data snapshots not validated for completeness before processing

### 2.2 Probability Model
- Model assumes stable market conditions; extreme volatility reduces accuracy
- Volatility threshold (0.03% stddev over 30s) may not adapt well to sudden regime changes

### 2.3 Trade Execution
- No retry logic for failed Kalshi API calls
- Race conditions possible if trade_manager updates DB before executor confirms

### 2.4 Active Trade Supervisor
- UI updates can lag if db_poller misses change event
- Forced table redraw on mobile causes button rebind issues

---

## 3. Design Constraints

### 3.1 Architecture
- Monolithic Python services under supervisor; limited horizontal scaling
- Tight coupling between market data services and strategy logic

### 3.2 Deployment
- Local-first with single production instance; no load balancing
- Manual release/rollback

### 3.3 Database
- PostgreSQL optimized for single-user workloads
- No sharding or partitioning; v3 must address multi-user scaling

### 3.4 Security
- No MFA for critical actions
- No central secrets manager
- Limited audit logging

---

## 4. v3 Recommendations
- Remove all legacy SQLite/JSON writes
- Implement standardized logging & error handling
- Adopt dependency-aware process management
- Introduce CI/CD integration tests
- Add adaptive volatility thresholds to probability model
- Decouple data services from strategy execution
- Containerize services for scaling
- Add MFA + secrets manager
