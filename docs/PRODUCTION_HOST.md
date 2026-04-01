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

## Notes

- Prefer these variables in docs and automation instead of scattering the raw IP. When copy-paste clarity matters, this file is the single place that records the **current** production IPv4.
- **`DO_PROD_DROPLET_ID`** overrides the snapshot script default; the default in repo tracks **562337636** with this IPv4.

See also: [ARCHITECTURE.md](ARCHITECTURE.md) (production targeting), [PRODUCTION_SYNC_CHECKLIST.md](PRODUCTION_SYNC_CHECKLIST.md).
