# REC.IO alerts email (Gmail SMTP) — storing credentials safely

Registration verification and `scripts/send_test_alerts_email.py` use **`backend/util/registration_email.py`**, which authenticates to Gmail with an **app password** (not your normal Google password).

## Rules

1. **Never commit** the app password. Repo already ignores `backend/data/secrets/` and `.env`.
2. **Do not put `REC_ALERTS_SMTP_PASSWORD` in `supervisord.conf`.** The supervisor config generator **does not** propagate that variable so the secret is not copied into a file that often sits in backups or wider ACLs than intended.
3. Prefer a **root-owned or deploy-owned file** with mode **600** (or **400**) on servers.

## Resolution order (same in dev and prod)

The app loads the password from the first match:

1. Environment variable **`REC_ALERTS_SMTP_PASSWORD`** (fine for one-off shell tests; avoid for long-lived `main_app` via supervisor — use file instead).
2. **`REC_ALERTS_SMTP_PASSWORD_FILE`** — absolute path to a file whose **first line** is the app password (no newline needed at end).
3. Default path under the repo: **`backend/data/secrets/rec_alerts_smtp_password.txt`** (same one-line format).

Optional non-secret overrides: `REC_ALERTS_SMTP_HOST`, `REC_ALERTS_SMTP_PORT`, `REC_ALERTS_SMTP_USER`, `REC_ALERTS_SMTP_FROM`, `REC_ALERTS_ADMIN_NOTIFY_EMAIL` (inbox for post-verification new-user application alerts; default `rec.io.alerts@gmail.com` — see `registration_email.py`), `REC_PUBLIC_BASE_URL` (overrides default `https://rec-io.com` for verification links in email, e.g. local testing).

## Local development

```bash
mkdir -p backend/data/secrets
install -m 600 /dev/null backend/data/secrets/rec_alerts_smtp_password.txt
# edit the file: one line = Gmail app password
```

Restart **`main_app`** after creating or changing the file.

To point supervisor at a non-default file (optional), export when regenerating supervisor config:

```bash
export REC_ALERTS_SMTP_PASSWORD_FILE="/your/absolute/path/to/smtp_secret.txt"
# then run your usual supervisor config regeneration / MASTER_RESTART flow
```

## Production (`docs/PRODUCTION_HOST.md`)

Typical layout: project root **`/opt/rec_io_server`**.

**Option A (simplest):** use the default repo-relative file on the server:

```text
/opt/rec_io_server/backend/data/secrets/rec_alerts_smtp_password.txt
```

Create on the server (as the user that runs `main_app`, or adjust ownership):

```bash
sudo install -d -m 700 -o REC_USER -g REC_GROUP /opt/rec_io_server/backend/data/secrets
sudo sh -c 'umask 077; printf %s "YOUR_APP_PASSWORD" > /opt/rec_io_server/backend/data/secrets/rec_alerts_smtp_password.txt'
sudo chown REC_USER:REC_GROUP /opt/rec_io_server/backend/data/secrets/rec_alerts_smtp_password.txt
sudo chmod 600 /opt/rec_io_server/backend/data/secrets/rec_alerts_smtp_password.txt
```

Replace `REC_USER` / `REC_GROUP` with the account supervisord uses (often `root` or a dedicated deploy user — match your install).

**Option B:** store outside the tree (e.g. only root can read):

```bash
sudo install -d -m 755 /etc/rec-io
sudo sh -c 'umask 077; printf %s "YOUR_APP_PASSWORD" > /etc/rec-io/rec_alerts_smtp_password'
sudo chmod 600 /etc/rec-io/rec_alerts_smtp_password
```

Then set **`REC_ALERTS_SMTP_PASSWORD_FILE=/etc/rec-io/rec_alerts_smtp_password`** in the environment used when **regenerating** `supervisord.conf` (so it is baked into the `environment=` line for `main_app`), or append that single key to the `main_app` program section by hand if your process forbids regen with secrets in shell.

After any change: **`supervisorctl restart main_app`**.

## Smoke test

From repo root (uses the same credential resolution as the app):

```bash
PYTHONPATH=. python3 scripts/send_test_alerts_email.py your-email@example.com
```

## Rotation

1. Create a new Google app password; update the secret file (or replace file contents atomically with a temp file + `mv`).
2. Restart `main_app`.
3. Revoke the old app password in Google Account settings.

## Related

- `backend/util/registration_email.py` — implementation and env names.
- `.env.example` — optional commented hints (note: **`main_app` does not load `.env`**; secrets file or supervisor `environment=` is what matters for the web app).
