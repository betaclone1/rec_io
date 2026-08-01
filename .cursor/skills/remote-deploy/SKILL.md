# Remote deploy (commit, push, pull, restart if needed)

**Prerequisite:** Export `REC_PROD_SSH_HOST` to the production server IP or DNS name (SSH).

**Current production:** IPv4 **`165.22.13.146`**. Example: `export REC_PROD_SSH_HOST=165.22.13.146`. Optional: `export REC_PROD_SSH_USER=recio_deploy` (default **`root`**). Canonical: `docs/PRODUCTION_HOST.md`.

Quick deploy workflow for changes that don't require migrations or the full changelog process.

## When to use

- Frontend-only changes (HTML, CSS, JS, images)
- Backend Python changes that need a restart
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
- Capture the list of files that changed in the pull output (or run `git diff --name-only HEAD~1 HEAD` on prod if needed).

### 4. Determine if restart is needed

Analyze the files that changed. A restart is **required** if any of these patterns match:

**Restart required:**
- Any `.py` file in `backend/` (Python code changes)
- `backend/supervisord.conf` or supervisor config changes
- `scripts/` changes (shell scripts, especially startup scripts)
- `requirements.txt` or dependency changes
- Any file that affects running processes

**Restart NOT required (static files only):**
- `frontend/**/*.html`
- `frontend/**/*.css`
- `frontend/**/*.js`
- `frontend/**/*.png`, `*.jpg`, `*.svg`, `*.ico`, etc.
- `docs/**/*`
- `.cursor/**/*`
- `README.md`, `LICENSE`, etc.

If **all** changed files are static/frontend-only, skip restart. Otherwise, restart is needed.

### 5. Restart prod if needed

If restart is required:
- Run MASTER_RESTART on prod via SSH:
  ```bash
  ssh "${REC_PROD_SSH_USER:-root}@$REC_PROD_SSH_HOST" 'cd /opt/rec_io_server && ./scripts/MASTER_RESTART.sh'
  ```
- Wait for the restart to complete (blocking command).
- Note: Supervisor may print internal tracebacks during restart; this is expected noise if services come back up.

If restart is NOT required:
- Skip this step and report that only static files changed.

### 6. Quick health check (if restart ran)

If a restart was performed, do a quick health check:
```bash
ssh "${REC_PROD_SSH_USER:-root}@$REC_PROD_SSH_HOST" 'cd /opt/rec_io_server && supervisorctl status'
```
- Verify key services are RUNNING (main_app, trade_executor, etc.).
- If any critical service is not running, report it clearly.

### 7. Report outcome

Report:
- What commit was deployed (short SHA and message)
- Whether restart was needed and why (list the file patterns that triggered it, or state "static files only")
- If restart ran: supervisor status summary
- Any errors encountered

## Example outputs

**Static files only (no restart):**
```
Deployed: abc1234 "Update mobile trade history styles"
Files changed: frontend/mobile/trade_history_mobile.html
Restart: Not needed (frontend-only changes)
Pull successful on prod.
```

**Backend changes (restart needed):**
```
Deployed: def5678 "Add new API endpoint for trade stats"
Files changed: backend/api/trades.py, backend/routers/stats.py
Restart: Required (backend Python changes)
MASTER_RESTART completed.
Supervisor status: main_app RUNNING, trade_executor RUNNING, ...
```

## Error handling

- If commit fails: report and stop
- If push fails: retry with backoff, then report and stop
- If pull fails: report and stop (do not attempt restart)
- If restart fails: report the error clearly; do not claim success
- If health check shows issues: report them (⚠️ or 🔴 as appropriate)
