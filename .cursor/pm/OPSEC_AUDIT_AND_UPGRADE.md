# Operational security — audit and upgrade process

Lightweight audit of current OpSec behavior and a framed process for security upgrades. PM and agents can use this when reviewing security-related changes. An **@opsec** agent can be added later as head of security, consulted on auth, secrets, and deployment safety.

---

## Current state (2026-03-08)

**Secrets and credentials**
- **.gitignore:** `.env`, `.env.*` (except `.env.example`), `backend/api/kalshi-api/kalshi-credentials/`, `*.pem`, `.cursor/gcp-oauth.keys.json`, `.cursor/gdrive-server-credentials.json`, `.cursor/mcp.json` (may contain Discord token). Root `.env` is the primary env for local/dev.
- **Kalshi:** Credentials loaded from a credential dir (e.g. `kalshi-credentials/<mode>/`) via `get_kalshi_credentials_dir()`; each mode has `.env` (KALSHI_API_KEY_ID) and `kalshi.pem` (RSA private key). Used by trade_executor, kalshi_account_sync_ws, kalshi API watchdogs. No credentials in repo.
- **DB:** DB_* / REC_DB_* from .env or environment; no DB passwords in code. database.py centralizes connection; scripts use get_postgresql_connection().
- **G Drive / MCP:** OAuth and token in .cursor (gitignored). Script and MCP share same credentials.

**Network and deployment**
- Services bind to ports from MASTER_PORT_MANIFEST; main_app, trade_executor, etc. Config and paths can be server-specific (unified config, REC_PROJECT_ROOT). Production deployment (e.g. Digital Ocean) documented elsewhere; prod credentials and .env are off-repo.
- Real-money decisions require CEO approval (ORG_CHART).

**Hardcoded / legacy**
- Audit notes (e.g. 10_audit_per_file, 09) mention hardcoded localhost/DB in some analytics and legacy scripts; env conventions (REC_DB_* vs DB_*) normalization is an open task (13_proposed_tasks). No secrets in code; risk is portability and accidental env leakage in logs.

---

## Security upgrade process (framed)

1. **Periodic audit** — Quarterly or after major changes: (a) List all credential and secret touchpoints (Kalshi, DB, MCP, third-party APIs). (b) Confirm they are env or gitignored files only; no secrets in code or logs. (c) Check .cursorignore and .gitignore for any new secret paths.
2. **Secrets rotation** — Document rotation procedure for Kalshi API key, DB password, MCP tokens. Rotate after any suspected exposure or per policy.
3. **Least privilege** — DB user, Kalshi API scope, and file permissions for credential dirs should be minimum required. Document in install/deploy docs.
4. **Logs and errors** — Ensure stack traces and error messages do not echo secrets or full env. Review high-traffic or external-facing endpoints.
5. **Dependencies** — Keep dependencies (Python, Node, system packages) updated for security patches; track in changelog when we bump for security.
6. **OpSec agent (optional)** — Add **@opsec** as head of security: consulted on auth, secrets, deployment, and compliance. Rule in .cursor/rules/opsec.mdc; PM routes security-related questions to @opsec when the agent exists.

---

## When to consult security

- Adding a new third-party API or storing new secrets.
- Changing credential loading, env layout, or deployment targets.
- Exposing new endpoints or user data.
- After a suspected incident or before a formal audit.

---

*Last updated: 2026-03-08. Expand this doc as we add controls or an @opsec agent.*