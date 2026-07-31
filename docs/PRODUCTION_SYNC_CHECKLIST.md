# Production server sync checklist

Production runs whatever is on **`origin/main`**. To get your local commits onto production you must get them into `main` on GitHub, then pull on the server.

---

## 1. Local: get your work onto `origin/main`

**Option A – You work on a feature branch and want to update production with it**

```bash
# From your feature branch (e.g. features/strategy-health-score)
git fetch origin
git checkout main
git pull origin main

# Merge your branch into main (resolve any conflicts)
git merge features/strategy-health-score

# Push main to GitHub (this is what production will pull)
git push origin main

# Optional: switch back to your branch
git checkout features/strategy-health-score
```

**Option B – You already merged into main locally**

```bash
git checkout main
git push origin main
```

**Option C – Your branch was never pushed**

```bash
# Push the branch so it exists on GitHub
git push -u origin features/strategy-health-score

# Then merge into main (Option A) and push main.
```

---

## 2. Production: pull and restart

On the **production server** (SSH: see [PRODUCTION_HOST.md](PRODUCTION_HOST.md); canonical IPv4 **`165.22.13.146`**, project root **`/opt/rec_io_server`**):

```bash
cd /opt/rec_io_server

# See what branch you're on and if there are local changes
git status

# If you have local changes you don't need, stash or discard:
#   git stash
# or (only if you're sure):  git checkout -- .  git clean -fd

# Use main and get latest from GitHub
git checkout main
git fetch origin
git pull origin main

# Restart services so they run the new code
./scripts/MASTER_RESTART.sh
```

If you use the existing update script (it also pulls `origin/main` and restarts):

```bash
cd /opt/rec_io_server
./scripts/install_deploy/git_update_system.sh update
```

**Nightly bookkeeper cron (first deploy only):** After the release that adds `scripts/cron/bookkeeper_kalshi_reconcile.sh`, install the production crontab entry once so Kalshi vs QuickBooks reconcile runs daily at 12:30 AM Eastern. Full steps: [PRODUCTION_HOST.md — Cron: bookkeeper Kalshi reconcile](PRODUCTION_HOST.md#cron-bookkeeper-kalshi-reconcile).

**Nightly redundant backup cron (first deploy only):** After the release that adds `scripts/cron/do_auto_backup_snapshot.sh` (DO snapshot + DB → Drive), put `DIGITALOCEAN_API_TOKEN` in production `.env`, ensure Drive OAuth secrets + `scripts/gdrive` npm deps + `pg_dump` are present, then install the crontab entry for 1:00 AM Eastern. Full steps: [PRODUCTION_HOST.md — Cron: nightly redundant backups](PRODUCTION_HOST.md#cron-nightly-redundant-backups-do-snapshot--db--google-drive).

---

## 3. Common “nightmare” cases

| Situation | Fix |
|-----------|-----|
| Production is on a different branch | On server: `git checkout main` then `git pull origin main`. |
| Production has local changes | On server: `git stash` (or discard with `git checkout -- .` if you don’t need them), then pull. |
| Your branch isn’t on GitHub | Locally: `git push -u origin <branch>`. Then merge that branch into `main` and `git push origin main`. |
| `git pull` on production says “diverged” or “conflict” | On server: `git fetch origin` then `git reset --hard origin/main` (this makes production exactly match GitHub main; any local commits on the server are dropped). Then run `./scripts/MASTER_RESTART.sh`. |
| You want production to run a branch that isn’t main | On server: `git fetch origin` then `git checkout <branch>` then `git pull origin <branch>`. You’ll need to change or bypass `scripts/install_deploy/git_update_system.sh` (it’s hardcoded to `main`) for future updates. |

---

## 4. One-line summary

**Local:** Merge your work into `main`, then `git push origin main`.  
**Production:** `git checkout main && git pull origin main && ./scripts/MASTER_RESTART.sh`.
