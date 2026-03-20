# Kalshi credential rotation (Op Sec)

**Goal:** Rotate Kalshi API credentials on a schedule using Kalshi’s API (generate new key, persist it, delete old key) so the system does not rely on long-lived static keys.

**Scope:**
- **In:** Kalshi trade API v2 key lifecycle (generate, persist, verify, delete); single shared credential set per account mode (prod/demo); scripted rotation + optional scheduled runs; logging/audit of rotations; safe order (create → verify → persist → delete).
- **Out:** Changing how existing consumers load credentials (they keep reading from same paths); Kalshi UI or manual bootstrap for the very first key; rotation of non-Kalshi secrets.

**Status:** draft

## Context

- **Credential layout:** `get_kalshi_credentials_dir() / account_mode` (e.g. `backend/data/users/user_0001/credentials/kalshi-credentials/prod`). Files: `.env` (`KALSHI_API_KEY_ID`), `kalshi.pem` (RSA private key). All Kalshi callers load from these paths (trade_executor, kalshi_account_sync_ws, watchdogs, historical ingest, diagnostics).
- **Kalshi API (trade-api/v2):**
  - `POST /api_keys/generate` — Kalshi generates RSA pair; returns `api_key_id` + `private_key` (PEM, one-time). Request: `name`, optional `scopes` (e.g. `["read","write"]`). Auth: current key (KALSHI-ACCESS-KEY, -TIMESTAMP, -SIGNATURE).
  - `DELETE /api_keys/{api_key}` — Permanently delete key. Auth: current key.
  - Base URL prod: `https://api.elections.kalshi.com/trade-api/v2`; demo: `https://demo-api.kalshi.co/trade-api/v2`.
- **Bootstrap:** The first key cannot be created via API (no “current” key). It must be created once via Kalshi UI (or manual process); rotation then takes over for subsequent keys.

## Steps

1. **Implement Kalshi key-management client (generate + delete)**  
   - Add a small module (e.g. under `backend/api/kalshi-api/` or `scripts/`) that uses existing credential loading and signing to:
     - Call `POST /api_keys/generate` with a name (e.g. `rec_io_rotated_YYYY-MM-DD`) and scopes `["read","write"]`, return `api_key_id` and `private_key` (PEM).
     - Call `DELETE /api_keys/{api_key}` for a given key id.
   - Reuse existing `get_base_url()`, credential dir per `account_mode`, and the same signature generation used by trade_executor / kalshi_account_sync_ws (path for signature: `/trade-api/v2/api_keys/...`). Handle demo vs prod via existing account_mode.

2. **Implement credential writer**  
   - Given `api_key_id` and PEM `private_key`, write atomically to the credential dir for the current account_mode:
     - Write new `.env` with `KALSHI_API_KEY_ID=<new_id>` (and any existing vars we want to keep, e.g. `KALSHI_PRIVATE_KEY_PATH=kalshi.pem` if used).
     - Write new `kalshi.pem` with correct permissions (e.g. 0o600). Prefer write-to-temp then rename so existing processes don’t read half-written files.

3. **Implement rotation script (create → verify → persist → delete)**  
   - Single script (e.g. `scripts/kalshi_rotate_credentials.py` or under `scripts/credentials/`) that:
     1. Loads current credentials (existing pattern).
     2. Calls generate; receives new `api_key_id` and `private_key`.
     3. Verifies new key with a cheap authenticated request (e.g. GET portfolio or GET exchange status) using the new key in memory (no persist yet).
     4. If verify succeeds: atomically write new `.env` and `kalshi.pem`; then call delete for the *old* key id.
     5. Log rotation (e.g. old key id prefix, new key id prefix, timestamp, account_mode). No private key material in logs.
   - Script must support `--account-mode prod|demo` (or use existing env/config for account_mode). Exit non-zero on failure; no delete if verify or write fails.

4. **Document and add optional schedule**  
   - Document in `docs/` (e.g. Op Sec or credentials runbook): bootstrap (first key via Kalshi UI), how to run rotation manually, and that after rotation, services that already hold credentials in memory must be restarted (supervisor restart or equivalent).
   - Optional: add a cron or systemd timer (or internal scheduler) to run the rotation script on a configurable interval (e.g. every 30/60/90 days). Default: document manual run first; schedule can be added once stable.

5. **Optional: grace period before delete**  
   - If desired, make “delete old key” a separate step or delayed (e.g. script writes new creds and logs “old key X can be deleted after Y hours”; second run or separate script deletes). Reduces risk of lockout if something is still using the old key. Plan can leave this as optional and implement “delete immediately after verify” first.

## Completion criteria

- [ ] Module or script can call Kalshi `POST /api_keys/generate` and `DELETE /api_keys/{api_key}` using existing creds and signing.
- [ ] Rotation script creates new key, verifies it with one API call, atomically updates `.env` and `kalshi.pem`, then deletes old key; logs rotation without private key material.
- [ ] Docs describe bootstrap, manual rotation, and post-rotation restart (e.g. supervisor).
- [ ] Rotation is testable in demo account without affecting prod.

## Blockers / decisions

- **Demo vs prod:** Confirm demo base URL and that `POST /api_keys/generate` and `DELETE` exist on demo (docs suggest same API surface). If not, rotation may be prod-only until demo supports it.
- **Schedule:** Decide rotation interval (e.g. 90 days) and whether to automate (cron/timer) in this plan or a follow-up.
- **Restart policy:** After rotation, all processes that use Kalshi must pick up new creds. Current code loads at startup; therefore document “run rotation then restart supervisor” (or equivalent). Optional later: signal or file-based reload without full restart.
