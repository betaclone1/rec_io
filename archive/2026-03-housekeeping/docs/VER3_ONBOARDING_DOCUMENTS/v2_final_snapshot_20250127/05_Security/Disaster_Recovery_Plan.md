# Disaster Recovery Plan – REC.IO v2

## Purpose
Provide step-by-step operational recovery procedures for critical system failures in REC.IO v2, ensuring minimal downtime and data loss. Designed for BMAD operators until v3 introduces advanced redundancy and automation.

---

## 1. Critical Failure Scenarios

### 1.1 PostgreSQL Database Failure
**Symptoms**:
- Services logging `connection refused` or `could not connect to server`
- API returning empty datasets or 500 errors
- Trade execution blocked

**Recovery Steps**:
1. **Check service**:
   ```bash
   sudo systemctl status postgresql
   sudo systemctl restart postgresql
   ```
2. **Validate DB integrity**:
   ```bash
   psql -U $POSTGRES_USER -d $POSTGRES_DB -c "\dt"
   ```
3. **Restore from backup** (if DB is corrupted):
   ```bash
   psql -U $POSTGRES_USER -d $POSTGRES_DB < /path/to/latest_backup.sql
   ```
4. **Restart dependent services**:
   ```bash
   supervisorctl restart trade_manager trade_executor active_trade_supervisor auto_entry_supervisor
   ```

**v3 Upgrade Note**: Will add automated failover to standby DB.

---

### 1.2 Service Crash (Core or Watchdog)
**Symptoms**:
- Supervisor shows `FATAL` or `BACKOFF`
- Missing market data or stopped trade updates

**Recovery Steps**:
1. Check logs:
   ```bash
   supervisorctl tail <service_name>
   ```
2. Restart service:
   ```bash
   supervisorctl restart <service_name>
   ```
3. If repeated failures, check dependencies (DB/API).

**v3 Upgrade Note**: Will implement automatic backoff + restart with dependency checks.

---

### 1.3 API Provider Outage (Kalshi or Coinbase)
**Symptoms**:
- API error 5xx or timeouts in logs
- Market/price updates frozen

**Recovery Steps**:
1. Confirm provider status via status page or API health endpoint.
2. If temporary outage, services will reconnect automatically (may need restart if >15min downtime).
3. For prolonged outage, disable auto_entry_supervisor to prevent stale trade entries.

**v3 Upgrade Note**: Will add provider failover and cache fallback.

---

### 1.4 Broken Deploy / Bad Release
**Symptoms**:
- Services fail immediately after deploy
- New code causing crashes

**Recovery Steps**:
1. Roll back to last known good release:
   ```bash
   cd /opt/rec_io_v2
   git checkout <last_good_tag>
   pip install -r requirements.txt --upgrade
   supervisorctl restart all
   ```
2. Verify with smoke tests.

**v3 Upgrade Note**: Will use blue/green deploy for zero-downtime rollback.

---

## 2. Backup Strategy

### 2.1 Database
- **Full PostgreSQL dump** nightly:
  ```bash
  pg_dump -U $POSTGRES_USER $POSTGRES_DB > /backups/postgres/db_$(date +%F).sql
  ```
- Retain last 7 days locally, last 30 days in offsite storage.

### 2.2 Config & Secrets
- Backup `.env` files, `MASTER_PORT_MANIFEST.json`, `config.json`
- Store in encrypted archive offsite

### 2.3 Logs & Historical Data
- Archive service logs weekly
- Compress & store BTC price history, market snapshots

---

## 3. Recovery Verification Checklist
- [ ] DB restored and accessible (`\dt` shows expected tables)
- [ ] Services running (`supervisorctl status` all `RUNNING`)
- [ ] Market data flowing in (`kalshi_api_watchdog` updates visible)
- [ ] BTC price feed updating (`btc_price_watchdog` writing new entries)
- [ ] Web UI responsive
- [ ] Trades can be placed and confirmed

---

## 4. Roles & Responsibilities
- **BMAD Lead Operator**: Executes recovery steps, validates system health
- **System Architect**: Investigates root cause, applies long-term fix
- **Security Officer**: Handles incidents involving compromised credentials

---

## 5. Continuous Improvement
- After each incident, log details in incident report doc
- Update recovery steps if process changes
- Test recovery quarterly

**v3 Upgrade Targets**:
- Automated DB failover
- Service restart orchestration
- API provider failover
- Zero-downtime deploy with auto-rollback
