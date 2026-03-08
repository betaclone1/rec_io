# Partner & Stakeholder Onboarding Guide – REC.IO v2

> **🚨 CRITICAL SAFETY NOTICE:**  
> **NO AI AGENTS OR TEAM MEMBERS ARE PERMITTED TO PLACE LIVE TRADES FOR TESTING OR ANY OTHER PURPOSES.**  
> **NO AI AGENTS OR TEAM MEMBERS ARE PERMITTED TO ENABLE AUTOMATED TRADING FUNCTIONS FOR TESTING OR ANY OTHER PURPOSES.**  
> All testing must be performed in **read-only** or **simulation** modes. This is a mandatory policy for all BMAD team members.

---

## 1. Purpose
Provide step-by-step onboarding instructions for BMAD operators, developers, and stakeholders to understand, observe, and safely interact with REC.IO v2.

---

## 2. Environment Access

### 2.1 Accounts & Permissions
- **Production Servers**: Access only via approved SSH keys (BMAD lead operator or system architect)
- **Local Dev**: Each developer has their own environment with local PostgreSQL and supervisor configs
- **Kalshi & Coinbase Credentials**: Stored securely per Secrets Management Policy; never shared in plaintext

### 2.2 Environment Types
- **Production** – Live trading, restricted access, no AI/agent writes allowed
- **Staging** – Mirror of production for testing (read-only trades, no execution)
- **Local** – Developer sandbox for UI and service testing

---

## 3. Initial Setup (Local)
1. Clone repository & checkout correct branch
2. Set environment:
   ```bash
   export APP_ENV=local
   source v2_final_snapshot_20250127/02_Config/env_files/local.env
   ```
3. Install dependencies:
   ```bash
   python -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   ```
4. Start services:
   ```bash
   supervisord -c supervisor.conf
   ```
5. Open `http://localhost:3000` in browser

---

## 4. Testing Procedures

### 4.1 UI Testing
- Verify dashboard loads with real-time BTC prices
- Confirm strike table updates in sync with market feed
- Inspect indicators: volatility flags, momentum arrows

### 4.2 Trade Flow Simulation (Read-Only)
- **Do not** place live trades
- Simulate signals in auto_entry_supervisor (simulation mode flag)
- Verify trades appear in UI and database without execution

### 4.3 Market Data
- Validate BTC price feed via btc_price_watchdog logs
- Validate Kalshi API feed via kalshi_api_watchdog logs and DB writes

---

## 5. Viewing Logs
- **Supervisor logs**:
  ```bash
  sudo supervisorctl tail <service_name>
  ```
- **Service logs**: `${LOG_ROOT}/{service}/{service}.log`
- **Market snapshots**: `${DATA_ROOT}/snapshots/*.json`

---

## 6. Debugging Procedures
- Always reproduce issues in staging/local first
- Use read-only API keys for testing
- Document issues in the shared bug tracker with logs & timestamps
- Never attempt direct DB modifications in production

---

## 7. Communication Protocol
- All incidents reported immediately to BMAD lead operator
- Code changes must be reviewed before merging to main
- Security or credential issues escalated to system architect

---

## 8. v3 Onboarding Considerations
- Multi-strategy per monitor will require strategy-specific onboarding
- Backtesting tools will allow safe trade simulation at scale
- Security upgrade will further lock down trade execution endpoints
