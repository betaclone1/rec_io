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

## Test

```bash
PYTHONPATH=. python3 scripts/send_test_workspace_alerts_email.py --user-no 0001
```
