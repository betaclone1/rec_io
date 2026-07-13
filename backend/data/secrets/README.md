# Alerts email secrets (local and production)

## File: `rec_alerts_smtp_password.txt` (not in git)

Put your **Google app password** for `alerts@rec-io.com` on **exactly one line** in that file. No comments, no extra lines. Google shows the password as four groups with spaces; **pasting with spaces is fine** — the app strips them before login.

You must use an **App password** (Google Account → Security → 2-Step Verification → App passwords), not your normal Google password. The Workspace account needs 2-Step Verification enabled first.

Create or fix permissions (run from repo root):

```bash
install -m 600 /dev/null backend/data/secrets/rec_alerts_smtp_password.txt
# then edit the file and paste the app password on line 1
```

Restart **`main_app`** and **`monitor_manager`** (tenant workers) after changing this file — drawdown halt alerts are sent from `monitor_manager`.

Optional overrides (environment / supervisord, not this folder): `REC_ALERTS_SMTP_USER`, `REC_ALERTS_SMTP_FROM`, `REC_ALERTS_SMTP_HOST`, `REC_ALERTS_SMTP_PORT`. Defaults match `alerts@rec-io.com` and Gmail SMTP.

## Production

This directory is **not** deployed from git. After you sync code to prod, **create the same path** on the server and the same file, e.g. under `/opt/rec_io_server/backend/data/secrets/rec_alerts_smtp_password.txt`, with **600** permissions and ownership matching the user that runs `main_app` / `monitor_manager`. See **`docs/REC_ALERTS_SMTP_SECRETS.md`**.

## Test

```bash
PYTHONPATH=. python3 scripts/send_test_workspace_alerts_email.py --user-no 0001
```
