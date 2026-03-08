# Secrets Management Policy – REC.IO v2

## Purpose
Define how REC.IO v2 handles credentials, API keys, and other sensitive information in production, staging, and local environments. BMAD agents should follow these procedures until v3’s system-wide security upgrade.

---

## 1. Current Secrets Storage (v2)
- **Environment Variables**: Primary method for service credentials (loaded from `.env`)
- **Credential Files**: Located in `${CREDENTIALS_ROOT}`, referenced in `.env`
- **.env Files**:
  - Stored in `02_Config/env_files/{production|staging|local}.env`
  - Not committed to Git
  - Separate copies per environment
- **File Permissions**:
  - `.env` and credential files: `chmod 600`
  - Owned by `svc_rec` user on production

**Examples of Stored Secrets**:
```
KALSHI_API_KEY=...
KALSHI_API_SECRET=...
COINBASE_API_KEY=...
POSTGRES_PASSWORD=...
```

---

## 2. Loading Secrets
- **Local Dev**: `source v2_final_snapshot_20250127/02_Config/env_files/local.env`
- **Production**: Supervisor loads env vars from `/etc/environment` or `.env` path set in supervisor config
- **Scripts**: Python services use `os.getenv()`; no hardcoded secrets

---

## 3. Rotation Procedure
**API Keys (Kalshi, Coinbase)**:
1. Generate new key in provider dashboard
2. Update `.env` for target environment
3. Restart affected services:
   ```bash
   supervisorctl restart trade_executor kalshi_api_watchdog btc_price_watchdog
   ```
4. Remove old key from provider account

**PostgreSQL Password**:
1. Create new password in Postgres:
   ```sql
   ALTER USER rec_trading_user WITH PASSWORD 'newpassword';
   ```
2. Update `.env` and `/etc/environment`
3. Restart all DB-dependent services

**Credential Files**:
- Replace file contents with new secret
- Ensure file permissions remain `600`

---

## 4. Access Control
- Only BMAD lead operators and system architect have SSH access to prod servers
- No shared credentials in chat or email; use secure transfer (e.g., encrypted message or vault)
- `.env` files and credential files must be excluded from any shared archives

---

## 5. Current Liabilities (to be addressed in v3 security upgrade)
- Secrets stored as plaintext in `.env` and credential files
- No automated rotation schedule
- No central audit/logging for secret access
- No secrets manager (e.g., HashiCorp Vault, AWS Secrets Manager)
- Production `.env` readable by svc account without MFA

---

## 6. v3 Upgrade Plan – High-Level
- Migrate all secrets to centralized secrets manager
- Enforce MFA for secret access
- Remove all plaintext `.env` files from servers
- Implement automated key rotation for APIs and DB
- Audit logging for all secret reads

---

## 7. Incident Response (Credential Compromise)
1. **Revoke compromised key/password immediately** in provider or DB
2. **Generate replacement** per Section 3
3. **Invalidate active sessions** for affected service
4. **Review logs** for suspicious activity during compromise window
5. **Document incident** and corrective actions in security log
