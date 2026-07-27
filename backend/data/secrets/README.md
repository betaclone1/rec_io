# Alerts email secrets (local and production)

## Preferred (production / DigitalOcean): Gmail API OAuth

DigitalOcean blocks outbound SMTP (ports 25/465/587). Use Gmail API over HTTPS instead.

### File: `rec_alerts_gmail_oauth.json` (not in git)

Created by:

```bash
PYTHONPATH=. python3 scripts/setup_gmail_api_alerts_oauth.py \
  --client-secrets /path/to/client_secret.json
```

See **`docs/REC_ALERTS_SMTP_SECRETS.md`** for the Google Cloud OAuth client steps (sign in as `alerts@rec-io.com`).

Copy the resulting JSON to prod:

`/opt/rec_io_server/backend/data/secrets/rec_alerts_gmail_oauth.json` (mode **600**)

Then restart **`main_app`** and **`monitor_manager_*`**.

## Optional (laptop SMTP only): app password

### File: `rec_alerts_smtp_password.txt` (not in git)

One line = Google app password for `alerts@rec-io.com`. Works locally; usually **not** reachable from DigitalOcean droplets.

Optional overrides: `REC_ALERTS_SMTP_USER`, `REC_ALERTS_SMTP_FROM`, `REC_ALERTS_SMTP_HOST`, `REC_ALERTS_SMTP_PORT`, `REC_ALERTS_GMAIL_OAUTH_FILE`.

## Google Drive (cycle packages / scripts) — `eric@rec-io.com`

Same pattern as Gmail OAuth: **not in git**, mode **600**, under `backend/data/secrets/`.

### Files

| File | Source |
|------|--------|
| `gdrive_oauth_client.json` | Desktop OAuth client (`gcp-oauth.keys.json` / GCP “Desktop app”) |
| `gdrive_oauth_token.json` | User token after browser consent as **`eric@rec-io.com`** |

Authorize once on a laptop (see `scripts/gdrive/README.md` / `create-doc.js auth` with `login_hint=eric@rec-io.com`), then copy both files to prod:

```bash
# from laptop (paths relative to repo root)
scp .cursor/gcp-oauth.keys.json root@$REC_PROD_SSH_HOST:/opt/rec_io_server/backend/data/secrets/gdrive_oauth_client.json
scp .cursor/gdrive-server-credentials.json root@$REC_PROD_SSH_HOST:/opt/rec_io_server/backend/data/secrets/gdrive_oauth_token.json
ssh root@$REC_PROD_SSH_HOST 'chmod 600 /opt/rec_io_server/backend/data/secrets/gdrive_oauth_*.json'
```

### Env for scripts on prod

```bash
export GDRIVE_OAUTH_PATH=/opt/rec_io_server/backend/data/secrets/gdrive_oauth_client.json
export GDRIVE_CREDENTIALS_PATH=/opt/rec_io_server/backend/data/secrets/gdrive_oauth_token.json
export GDRIVE_BACKTESTING_DATA_FOLDER_ID=1Jlhz57hSXMYe8Yr_GtIJsaXY0GAW6L1v   # DATA/HISTORICAL_DATA/BACKTESTING_DATA
```

Requires **Node ≥ 18** on the host (`scripts/gdrive` uses `googleapis`). Upload: `node scripts/gdrive/upload-backtesting-data.js`.

## Intuit OAuth (bookkeeper)

## Test

```bash
PYTHONPATH=. python3 scripts/send_test_workspace_alerts_email.py --user-no 0001
```
