# Production host (canonical)

**SSH and PostgreSQL run on the same machine.** Credentials match local `.env` patterns (`DB_*` / `REC_DB_*`); only the **host** differs from a typical developer laptop.

| | Value |
|--|--|
| **Public IPv4 (SSH + Postgres from your machine)** | `165.22.13.146` |
| **Project root on the server** | `/opt/rec_io_server` |
| **Env for SSH runbooks** | `REC_PROD_SSH_HOST` |
| **Env for local scripts connecting to prod Postgres** | `REC_PROD_DB_HOST` (optional if same as SSH target; often set to the same value as `REC_PROD_SSH_HOST`) |
| **DigitalOcean droplet (name)** | **562337636** — `rec-io-server-new-york-1` (active). `prepare-update` / `scripts/do/snapshot_prod.sh` default; override with `DO_PROD_DROPLET_ID`. Prior prod droplet **513735057** (`137.184.224.94`) is retired/off — do not snapshot it for current prod. |

## Quick setup (local shell)

```bash
export REC_PROD_SSH_HOST=165.22.13.146
export REC_PROD_DB_HOST=165.22.13.146   # when a script needs DB_HOST pointed at prod
```

## SSH from automation / agents

- **Wrapper (recommended):** `scripts/prod/rec_prod_ssh.sh 'remote command'` and `scripts/prod/simple_git_pull_on_prod.sh` resolve `REC_PROD_SSH_HOST` inside the script (defaulting to the table above if unset). Run them from the repo root.
- **Bash pitfall:** A single line like `REC_PROD_SSH_HOST=165.22.13.146 ssh root@$REC_PROD_SSH_HOST '…'` often breaks: the destination is expanded **before** the assignment applies to the current shell, so you get `root@` with an empty host. **Export first**, then `ssh root@$REC_PROD_SSH_HOST '…'`, or use the wrapper script.

## Cron: bookkeeper Kalshi reconcile

**What it does:** Once per day, compares Kalshi portfolio total (API) to QuickBooks **Kalshi Trading Account** balance and, if the gap exceeds the CLI `--min-diff`, posts a two-line journal entry to **Kalshi Trading Account** and **Trading Income**. Implemented as a **one-shot** process (starts, exits). It does **not** run under Supervisor; schedule it with **cron** only.

**When to install:** After the deploy that includes `scripts/cron/bookkeeper_kalshi_reconcile.sh` (and the bookkeeper reconcile code) is on production.

**Prerequisites on the server**

- Project at **`/opt/rec_io_server`** (or set paths below to match your checkout).
- **`venv`** present and dependencies installed (`venv/bin/python` used by the wrapper).
- Credentials for the bookkeeper user, same layout as local:
  - `backend/data/users/user_NNNN/credentials/quickbooks/.env` (Intuit / QBO tokens).
  - `backend/data/users/user_NNNN/credentials/kalshi-credentials/prod/` (Kalshi API).

**Verify before enabling cron**

```bash
cd /opt/rec_io_server
chmod +x scripts/cron/bookkeeper_kalshi_reconcile.sh   # if not already executable
REC_USER_NO=0001 ./scripts/cron/bookkeeper_kalshi_reconcile.sh
tail -30 logs/bookkeeper_kalshi_reconcile.log
```

Use **`REC_USER_NO`** to match the credentials directory (`user_0001` → `0001`).

**Install crontab (12:30 AM US Eastern wall clock)**

Edit the crontab for the **same Linux user** that can read the repo and credential files (often **`root`** on this host):

```bash
crontab -e
```

Add (two lines: timezone for the job + schedule):

```cron
CRON_TZ=America/New_York
30 0 * * * /opt/rec_io_server/scripts/cron/bookkeeper_kalshi_reconcile.sh
```

To pin a different bookkeeper user:

```cron
CRON_TZ=America/New_York
30 0 * * * REC_USER_NO=0002 /opt/rec_io_server/scripts/cron/bookkeeper_kalshi_reconcile.sh
```

**Logs:** append-only **`/opt/rec_io_server/logs/bookkeeper_kalshi_reconcile.log`**.

**Note:** Production droplets use **Linux** `cron`; **`CRON_TZ`** is honored (same pattern as [ARCHITECTURE.md](ARCHITECTURE.md)). This differs from macOS `cron`, which often ignores `CRON_TZ`.

---

## Notes

- Prefer these variables in docs and automation instead of scattering the raw IP. When copy-paste clarity matters, this file is the single place that records the **current** production IPv4.
- **`DO_PROD_DROPLET_ID`** overrides the snapshot script default; the default in repo tracks **562337636** with this IPv4.

See also: [ARCHITECTURE.md](ARCHITECTURE.md) (production targeting), [PRODUCTION_SYNC_CHECKLIST.md](PRODUCTION_SYNC_CHECKLIST.md), [REC_ALERTS_SMTP_SECRETS.md](REC_ALERTS_SMTP_SECRETS.md) (Gmail app password file for registration email).
