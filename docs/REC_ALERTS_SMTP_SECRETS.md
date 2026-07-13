# REC.IO alerts email — credentials

`backend/util/registration_email.py` sends transactional mail from **`alerts@rec-io.com`**.

**Production (DigitalOcean):** outbound SMTP ports 25/465/587 are blocked. Use **Gmail API over HTTPS** (OAuth JSON). Do not rely on SMTP app passwords on the droplet.

**Laptop:** SMTP app password still works for local tests.

## Rules

1. **Never commit** OAuth JSON or app passwords. `backend/data/secrets/` is gitignored.
2. **Do not put secrets in `supervisord.conf`.**
3. Secret files on servers: mode **600**.

## Production path (Gmail API / HTTPS)

### File

`backend/data/secrets/rec_alerts_gmail_oauth.json`  
(or `REC_ALERTS_GMAIL_OAUTH_FILE` absolute path)

### One-time Google Cloud setup

1. Open https://console.cloud.google.com/ while signed in as a Workspace admin (or a user who can create projects).
2. Create or select a project (e.g. `rec-io-alerts`).
3. **APIs & Services → Library** → enable **Gmail API**.
4. **APIs & Services → OAuth consent screen**
   - User type: **Internal** (Workspace) if available; otherwise External with test users including `alerts@rec-io.com`.
   - App name: e.g. `rec.io alerts`
   - Save.
5. **APIs & Services → Credentials → Create credentials → OAuth client ID**
   - Application type: **Desktop app**
   - Name: `rec-io-alerts-desktop`
   - Download the JSON (`client_secret_….json`).
6. On your laptop, run (browser opens; **sign in as `alerts@rec-io.com`** and allow send mail):

```bash
PYTHONPATH=. python3 scripts/setup_gmail_api_alerts_oauth.py \
  --client-secrets ~/Downloads/client_secret_XXXX.json
```

7. Copy the written file to prod:

```text
/opt/rec_io_server/backend/data/secrets/rec_alerts_gmail_oauth.json
```

8. Restart **`main_app`** and **`monitor_manager_0001`** (and other tenant monitor_managers if any).

### Resolution order for send

1. If `rec_alerts_gmail_oauth.json` is present and valid → **Gmail API** (HTTPS).
2. Else if SMTP app password is present → **SMTP** (local/dev).
3. Else → error (missing credentials).

## Optional SMTP (local only)

App password in `backend/data/secrets/rec_alerts_smtp_password.txt`, or `REC_ALERTS_SMTP_PASSWORD` / `REC_ALERTS_SMTP_PASSWORD_FILE`.

Optional non-secret overrides: `REC_ALERTS_SMTP_HOST`, `REC_ALERTS_SMTP_PORT`, `REC_ALERTS_SMTP_USER`, `REC_ALERTS_SMTP_FROM`, `REC_ALERTS_ADMIN_NOTIFY_EMAIL`, `REC_PUBLIC_BASE_URL`, `REC_ALERTS_GMAIL_OAUTH_FILE`.

## Smoke test

```bash
PYTHONPATH=. python3 scripts/send_test_workspace_alerts_email.py --user-no 0001
```

On prod (after OAuth file is in place):

```bash
cd /opt/rec_io_server
PYTHONPATH=. ./venv/bin/python scripts/send_test_workspace_alerts_email.py --user-no 0001
```

## Related

- `backend/util/registration_email.py`
- `scripts/setup_gmail_api_alerts_oauth.py`
- `scripts/send_test_workspace_alerts_email.py`
