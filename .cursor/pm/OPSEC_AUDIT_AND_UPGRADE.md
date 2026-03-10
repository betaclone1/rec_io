# Operational security — audit and upgrade process

Lightweight audit of current OpSec behavior and a framed process for security upgrades. PM and agents can use this when reviewing security-related changes. An **@opsec** agent can be added later as head of security, consulted on auth, secrets, and deployment safety.

---

## Proper OpSec audit (2026-03-08) — findings and suggestions

A full codebase scan was run for secrets, auth, logging, CORS, and exposure. Summary below; details in **.cursor/pm/brain/07_audit_log.md** (2026-03-08 OpSec entry).

### Glaring issues (fix soon)

| Severity | Issue | Where | Suggestion |
|----------|--------|--------|------------|
| **Critical** | Hardcoded DB password `rec_io_password` as default | database.py get_database_config; main.py get_user_credentials, change_password, many psycopg2.connect; kalshi_account_sync_ws, auto_entry_supervisor, active_trade_supervisor; MASTER_RESTART.sh, simple_deploy.sh, first_boot_sanitize.sh, generate_unified_supervisor_config.py | Remove default password; require DB_PASSWORD in production; use get_database_config() everywhere; fail fast if password empty when REC_ENVIRONMENT=production. |
| **Critical** | Auth bypass: any token starting with `local_dev_` accepted | main.py /api/auth/verify | Remove bypass or allow only when REC_ENVIRONMENT != production. |
| **Critical** | Fallback password hashing stores plaintext | main.py change_password_hash / verify_password (fallback_hash_&lt;plaintext&gt;); get_user_credentials JSON fallback "password": "admin" | Require bcrypt; remove plaintext fallback. Ensure production never uses JSON user_info. |
| **High** | Credentials printed to console | scripts/archive/setup_auth.py (Password), scripts/archive/install.py (db_password) | Remove prints of passwords; use "Password set" or redact. |
| **High** | CORS allow_origins includes "*" with allow_credentials=True | main.py origins list | Remove "*" in production or use explicit origins only. |
| **High** | change_password uses hardcoded DB connection | main.py change_password | Use get_database_config() / get_postgresql_connection(). |

### Other issues (medium / low)

- **Medium:** Token in query params (leak via Referer, logs, history). Prefer Authorization header or httpOnly cookie.
- **Medium:** Auth tokens in JSON file (no encryption at rest). File is gitignored; acceptable for single-user; consider short expiry.
- **Medium:** Many API endpoints have no token check (e.g. /api/notify_db_change); when AUTH_ENABLED=false entire app is open. Document internal-only endpoints; consider token or network restriction for sensitive routes.
- **Low:** Archive scripts and tests contain hardcoded password or prod IP (e.g. 137.184.224.94 in auto_entry_supervisor_test.py). Use env or placeholders.

### Positive findings

- Kalshi credentials not in repo; loaded from credential dir; .gitignore covers them.
- .gitignore covers .env, kalshi-credentials, *.pem, GCP/G Drive creds, backend/data/users/** (auth_tokens, device_tokens, user_info, credentials).
- Most DB access uses env; risk is the default when env is unset. SQL in main paths uses parameterized queries.

### Prioritized suggestions (implemented 2026-03-08)

1. **DB password:** Done. database.py requires DB_PASSWORD/REC_DB_PASS in production (no default); main.py, kalshi_account_sync_ws, auto_entry_supervisor, active_trade_supervisor, kalshi_market_ticker_websocket, generate_unified_supervisor_config use get_database_config()/get_postgresql_connection(). Scripts (MASTER_RESTART, simple_deploy, first_boot_sanitize) use env vars with fallback for dev.
2. **Auth:** Done. local_dev_ bypass only when REC_ENVIRONMENT != production; bcrypt required for new hashes (no plaintext fallback); change_password uses get_postgresql_connection(). bcrypt added to requirements.txt.
3. **Logging:** Done. setup_auth.py and install.py (archive) no longer print password.
4. **CORS:** Done. In production (REC_ENVIRONMENT=production) origins = explicit list only (no "*").
5. **Token:** Optional improvement; not changed.
6. **Endpoint auth:** Optional; not changed.

---

## Current state (2026-03-08)

**Secrets and credentials**
- **.gitignore:** `.env`, `.env.*` (except `.env.example`), `backend/api/kalshi-api/kalshi-credentials/`, `*.pem`, `.cursor/gcp-oauth.keys.json`, `.cursor/gdrive-server-credentials.json`, `.cursor/mcp.json` (may contain Discord token). Root `.env` is the primary env for local/dev.
- **Kalshi:** Credentials loaded from a credential dir (e.g. `kalshi-credentials/<mode>/`) via `get_kalshi_credentials_dir()`; each mode has `.env` (KALSHI_API_KEY_ID) and `kalshi.pem` (RSA private key). Used by trade_executor, kalshi_account_sync_ws, kalshi API watchdogs. No credentials in repo.
- **DB:** DB_* / REC_DB_* from .env; audit finding: database.py and many call sites use hardcoded default `rec_io_password` when env unset — see "Proper OpSec audit" above. Use get_database_config()/get_postgresql_connection() and require password in production.
- **G Drive / MCP:** OAuth and token in .cursor (gitignored). Script and MCP share same credentials.

**Network and deployment**
- Services bind to ports from MASTER_PORT_MANIFEST; main_app, trade_executor, etc. Config and paths can be server-specific (unified config, REC_PROJECT_ROOT). Production deployment (e.g. Digital Ocean) documented elsewhere; prod credentials and .env are off-repo.
- Real-money decisions require CEO approval (ORG_CHART).

**Hardcoded / legacy**
- Many backend and script paths use literal `rec_io_password` or `os.getenv(..., 'rec_io_password')`; see "Proper OpSec audit" table. Env normalization (REC_DB_* vs DB_*) is an open task (13_proposed_tasks). Risk: portability and production using default password if env misconfigured.

---

## Security upgrade process (framed)

1. **Periodic audit** — Quarterly or after major changes: (a) List all credential and secret touchpoints (Kalshi, DB, MCP, third-party APIs). (b) Confirm they are env or gitignored files only; no secrets in code or logs. (c) Check .cursorignore and .gitignore for any new secret paths.
2. **Secrets rotation** — Document rotation procedure for Kalshi API key, DB password, MCP tokens. Rotate after any suspected exposure or per policy.
3. **Least privilege** — DB user, Kalshi API scope, and file permissions for credential dirs should be minimum required. Document in install/deploy docs.
4. **Logs and errors** — Ensure stack traces and error messages do not echo secrets or full env. Review high-traffic or external-facing endpoints.
5. **Dependencies** — Keep dependencies (Python, Node, system packages) updated for security patches; track in changelog when we bump for security.
6. **OpSec agent (optional)** — Add **@opsec** as head of security: consulted on auth, secrets, deployment, and compliance. Rule in .cursor/rules/opsec.mdc; PM routes security-related questions to @opsec when the agent exists.

---

## Production server: OpSec update (2026-03-08)

When this update is pushed to the production server, the **production agent** (or operator running /apply-update) must follow these instructions so the OpSec changes do not cause failures.

**Prerequisites (must be true before or right after pull)**

1. **DB password in environment** — Production runs with `REC_ENVIRONMENT=production` (or equivalent). The code now **requires** `DB_PASSWORD` or `REC_DB_PASS` to be set in that environment. If neither is set, `get_database_config()` raises and the app (and supervisor config generation) will fail.
   - **Check:** On the prod server, ensure `.env` or whatever feeds the app/supervisor defines `DB_PASSWORD` or `REC_DB_PASS`. If prod has always used a real DB password in env, no change needed. If it was never set, set it before running MASTER_RESTART after the pull.
   - **Quick check:** From project root, after sourcing env: `[ -n "$DB_PASSWORD" ] || [ -n "$REC_DB_PASS" ] && echo "OK" || echo "MUST SET DB_PASSWORD or REC_DB_PASS"`.

2. **bcrypt installed** — `requirements.txt` now includes `bcrypt`. Run `venv/bin/pip install -r requirements.txt` (or your usual deploy install) so change-password works. Existing logins and existing password hashes are unaffected.

**Apply-update / checklist**

- The entry **2026-03-08 — OpSec remediation** in `docs/changelog/MASTER_CHANGELOG.md` has the full Production agent checklist. The agent should: confirm DB password is set, pull, install deps, run MASTER_RESTART, then run verify. If any step fails with a config/DB error, fix env (set DB password) and retry.

**CORS**

- In production, CORS allows only explicit origins (no `"*"`). If the frontend is served from `rec-io.com` or `www.rec-io.com` (or the same host as the API), it is already in the list. If you use another origin (e.g. a different domain or IP), add it to the `origins` list in `main.py` before or as part of the update.

---

## When to consult security

- Adding a new third-party API or storing new secrets.
- Changing credential loading, env layout, or deployment targets.
- Exposing new endpoints or user data.
- After a suspected incident or before a formal audit.

---

*Last updated: 2026-03-08. Expand this doc as we add controls or an @opsec agent.*