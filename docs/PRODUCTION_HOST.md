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

## Notes

- Prefer these variables in docs and automation instead of scattering the raw IP. When copy-paste clarity matters, this file is the single place that records the **current** production IPv4.
- **`DO_PROD_DROPLET_ID`** overrides the snapshot script default; the default in repo tracks **562337636** with this IPv4.

See also: [ARCHITECTURE.md](ARCHITECTURE.md) (production targeting), [PRODUCTION_SYNC_CHECKLIST.md](PRODUCTION_SYNC_CHECKLIST.md), [REC_ALERTS_SMTP_SECRETS.md](REC_ALERTS_SMTP_SECRETS.md) (Gmail app password file for registration email).
