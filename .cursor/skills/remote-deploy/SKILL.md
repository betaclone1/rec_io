# Remote deploy (commit, push, pull, restart specific scripts if needed)

**Prerequisite:** Export `REC_PROD_SSH_HOST` to the production server IP or DNS name (SSH).

**Current production:** IPv4 **`165.22.13.146`**. Example: `export REC_PROD_SSH_HOST=165.22.13.146`. Optional: `export REC_PROD_SSH_USER=recio_deploy` (default **`root`**). Canonical: `docs/PRODUCTION_HOST.md`.

Quick deploy workflow for changes that don't require migrations or the full changelog process.

## When to use

- Frontend-only changes (HTML, CSS, JS, images)
- Backend Python changes to specific modules
- Config or script tweaks
- Any change that doesn't need DB migrations or snapshots

## When NOT to use

- Changes requiring DB migrations → use `/apply-update-from-local`
- Changes requiring pre-deploy snapshots → use `/push-commits-and-update-production`
- First-time deploys or major version bumps → use full changelog flow

## Steps (execute in order)

### 1. Stage and commit changes

- Run `git status` to see what has changed.
- If there are unstaged changes, stage them: `git add -A` (or specific files if the user indicated a subset).
- If there are staged changes, commit with a descriptive message:
  ```bash
  git commit -m "<concise summary of changes>"
  ```
- If nothing to commit (already committed), proceed to step 2.

### 2. Push to origin

- Push the current branch:
  ```bash
  git push origin $(git branch --show-current)
  ```
- If push fails due to network errors, retry up to 4 times with exponential backoff (4s, 8s, 16s, 32s).
- If push fails for other reasons (e.g., not fast-forward), report the error and stop.

### 3. Pull on prod via SSH

- From the **repo root**, run:
  ```bash
  ./scripts/prod/simple_git_pull_on_prod.sh
  ```
- This pulls the latest commit on production. The script handles host resolution correctly.
- If the pull fails, report the error and stop.
- Note which files changed from the pull output.

### 4. Determine which scripts need restart (if any)

Analyze the files that changed. **Only restart the specific supervisor programs affected.**

#### No restart needed (static files):
- `frontend/**/*.html`, `frontend/**/*.css`, `frontend/**/*.js`
- `frontend/**/*.png`, `*.jpg`, `*.svg`, `*.ico`, etc.
- `docs/**/*`, `.cursor/**/*`, `README.md`, etc.

If ALL changed files are static, skip to step 6.

#### File-to-program mapping (restart only affected programs):

| Changed file pattern | Supervisor program(s) to restart |
|---------------------|----------------------------------|
| `backend/main.py` | `main_app` |
| `backend/web/**/*.py` | `main_app` |
| `backend/routers/**/*.py` | `main_app` |
| `backend/read_api.py` | `read_api` |
| `backend/redis_switchboard.py` | `redis_switchboard` |
| `backend/cfbenchmarks_price_watchdog.py` | `cfbenchmarks_price_watchdog` |
| `backend/market_watchdog_ws.py` | `market_watchdog_ws_kalshi` |
| `backend/system_monitor.py` | `system_monitor` |
| `backend/cascading_failure_detector.py` | `cascading_failure_detector` |
| `backend/strike_snapshot_publisher.py` | `strike_snapshot_publisher` |
| `backend/cycle_packager.py` | `cycle_packager` |
| `backend/trade_manager.py` | `trade_manager_0001` (and other user slots) |
| `backend/trade_executor.py` | `trade_executor_0001` (and other user slots) |
| `backend/kalshi_account_sync.py` | `kalshi_account_sync_0001` (and other user slots) |
| `backend/monitor_manager.py` | `monitor_manager_0001` (and other user slots) |
| `backend/kalshi_lifecycle_consumer.py` | `kalshi_lifecycle_consumer_0001` (and other user slots) |
| `backend/auto_entry_supervisor.py` | `auto_entry_supervisor_0001` (and other user slots) |
| `backend/active_trade_supervisor.py` | `active_trade_supervisor_0001` (and other user slots) |
| `backend/strike_table_generator_ws.py` | `strike_table_generator_ws_hourly`, `strike_table_generator_ws_15m` |

#### Shared modules (may affect multiple programs):
| Changed file pattern | Programs to consider |
|---------------------|---------------------|
| `backend/core/**/*.py` | Depends on what imports it - check imports or restart affected top-level scripts |
| `backend/kalshi/**/*.py` | Programs that use Kalshi: `main_app`, `trade_executor_*`, `kalshi_account_sync_*`, `market_watchdog_ws_kalshi`, `kalshi_lifecycle_consumer_*` |
| `backend/database/**/*.py` | Most programs use DB - but often hot-reloadable; restart if schema/connection logic changed |
| `backend/strategies/**/*.py` | `trade_manager_*`, `monitor_manager_*`, `auto_entry_supervisor_*` |

#### MASTER_RESTART only if:
- `backend/supervisord.conf` changed
- `scripts/MASTER_RESTART.sh` changed
- `requirements.txt` changed (new dependencies)
- Multiple core infrastructure files changed that affect most/all programs
- Unsure which programs are affected by a broad change

### 5. Restart specific programs on prod

For each program that needs restart, run:
```bash
ssh "${REC_PROD_SSH_USER:-root}@$REC_PROD_SSH_HOST" 'cd /opt/rec_io_server && supervisorctl restart <program_name>'
```

Examples:
```bash
# Single program
ssh "${REC_PROD_SSH_USER:-root}@$REC_PROD_SSH_HOST" 'cd /opt/rec_io_server && supervisorctl restart main_app'

# Multiple programs
ssh "${REC_PROD_SSH_USER:-root}@$REC_PROD_SSH_HOST" 'cd /opt/rec_io_server && supervisorctl restart main_app read_api'

# User-slot programs (if trade_executor.py changed)
ssh "${REC_PROD_SSH_USER:-root}@$REC_PROD_SSH_HOST" 'cd /opt/rec_io_server && supervisorctl restart trade_executor_0001'
```

**Only if MASTER_RESTART is truly needed** (supervisor config, requirements, or broad infrastructure changes):
```bash
ssh "${REC_PROD_SSH_USER:-root}@$REC_PROD_SSH_HOST" 'cd /opt/rec_io_server && ./scripts/MASTER_RESTART.sh'
```

### 6. Verify restarted programs

If any programs were restarted, check their status:
```bash
ssh "${REC_PROD_SSH_USER:-root}@$REC_PROD_SSH_HOST" 'cd /opt/rec_io_server && supervisorctl status'
```
- Verify the restarted programs show RUNNING.
- If any restarted program is not running, report it clearly.

### 7. Report outcome

Report:
- What commit was deployed (short SHA and message)
- Which files changed
- Which programs were restarted (if any) and why
- If no restart needed: state "static files only"
- Supervisor status of restarted programs

## Example outputs

**Static files only (no restart):**
```
Deployed: abc1234 "Update mobile trade history styles"
Files changed: frontend/mobile/trade_history_mobile.html
Restart: None needed (frontend-only changes)
```

**Single program restart:**
```
Deployed: def5678 "Fix read_api pagination bug"
Files changed: backend/read_api.py
Restart: read_api
Status: read_api RUNNING (pid 12345, uptime 0:00:03)
```

**Multiple program restart:**
```
Deployed: ghi9012 "Update Kalshi API handling"
Files changed: backend/kalshi/client.py, backend/kalshi/websocket.py
Restart: main_app, trade_executor_0001, kalshi_account_sync_0001, market_watchdog_ws_kalshi
Status: All restarted programs RUNNING
```

**Shared core module (targeted restart):**
```
Deployed: jkl3456 "Fix database connection pooling"
Files changed: backend/core/config/database.py
Restart: main_app, read_api (primary DB users; other programs use pooled connections that will refresh)
Status: main_app RUNNING, read_api RUNNING
```

## Error handling

- If commit fails: report and stop
- If push fails: retry with backoff, then report and stop
- If pull fails: report and stop (do not attempt restart)
- If specific program restart fails: report the error, try remaining programs
- If program not running after restart: report clearly
