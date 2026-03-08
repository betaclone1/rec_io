# Database Backup – System Audit (No Patches)

**Date:** 2026-02-14  
**Scope:** Why the Database Backup UI flow fails with `pg_dump: command not found` after previously working.

---

## 1. End-to-end flow

| Step | Component | What happens |
|------|-----------|--------------|
| 1 | **Frontend** `frontend/tabs/system.html` | User clicks "CREATE BACKUP". `startBackup()` sends POST to **`/api/admin/execute-command`** with body: `{ command: "bash ./scripts/package_user_data.sh --type full" }` (or `--type user`). |
| 2 | **Backend** `main.py` → `execute_command()` | Receives that command. Because `'package_user_data.sh' in command`, it runs the backup via a **login shell** and does **not** pass `env` to the subprocess. |
| 3 | **Backend** subprocess | Runs: `['/bin/bash', '-l', '-c', 'cd <project_dir> && bash ./scripts/package_user_data.sh --type full']` with `cwd=project_dir`, **no `env`** (so child inherits backend process environment). |
| 4 | **Script** `scripts/package_user_data.sh` | Runs inside that shell. Line 94 (full backup) or 84 (user backup): runs **`pg_dump`** with no path – relies entirely on **PATH** in the shell that is executing the script. Script sources `$PROJECT_ROOT/.env` for `POSTGRES_*` and `PGPASSWORD` only; it does **not** set or modify PATH. |
| 5 | **Frontend** on success | Uses a **hardcoded** path for download: `backupPath = '/opt/rec_io_server/backup/${backupFileName}'` (production Linux path). Download API expects a path on the server; for a Mac dev environment the backup actually lives under `project_dir/backup/`, so this path is wrong for local/dev. |

So the UI backup path is: **execute-command** → **login shell** → **package_user_data.sh** → **pg_dump**. No other endpoint is used for this flow.

---

## 2. Why `pg_dump` is not found

- The script is run by a shell whose **PATH** is whatever that shell has when it starts.
- That shell is started by `subprocess.run(..., run_cmd, cwd=project_dir)` **without** an `env` argument, so the subprocess **inherits the backend process environment** (including PATH).
- So the PATH seen by the script is, in practice, the **backend’s PATH** (possibly modified by the login shell’s profile – see below).

So:

- **Root cause:** The process that runs `package_user_data.sh` has a **PATH that does not contain the directory where `pg_dump` lives** (e.g. `/opt/homebrew/bin`, Postgres.app bin, or a versioned PostgreSQL bin).
- That process is either:
  - The backend itself (if the script were run with `command.split()` and the same env), or
  - The login shell we spawn; that shell **inherits** the backend’s env, then `bash -l` may source `~/.bash_profile` / `~/.profile` and **override** PATH. So the script’s PATH depends on:
    1. How the backend was started (what PATH it had), and  
    2. Whether the user’s profile (for a non-interactive `bash -l`) actually adds the directory that contains `pg_dump`.

So the failure is **environment-dependent**: it appears when the combination of “who started the backend” and “what the login shell does” produces a PATH without `pg_dump`.

---

## 3. Why it “worked for months” and then stopped

Plausible explanations (no code changes, just diagnosis):

1. **Backend used to be started with a “full” PATH**
   - Example: run from a terminal where you had already used PostgreSQL (e.g. `which pg_dump` works). That terminal’s PATH is inherited by the backend, so the backup subprocess (and thus the script) also saw `pg_dump`.
   - After a “master restart” or a different way of starting the app (e.g. Cursor/IDE run, or a system/launchd service), the backend may now start with a **minimal or default PATH** that does not include the directory where `pg_dump` is installed. So the same code path now sees “pg_dump: command not found”.

2. **Different environment (e.g. production vs local)**
   - On a server (e.g. Linux), PATH might be set system-wide or by the process manager so that `pg_dump` is on PATH when the backend runs; backup works there.
   - On your Mac, the same backend might be started by an IDE or launcher that does not load your full shell profile, so PATH never gets the PostgreSQL bin directory.

3. **Login shell profile not helping in this context**
   - Backup is run with `/bin/bash -l -c '...'`. For a **non-interactive** login shell, bash typically sources `~/.bash_profile` (or `~/.profile`). If your usual shell is **zsh**, your PATH for development might be set only in `~/.zshrc` or similar; bash would not source that, so the login shell might still have a PATH without `pg_dump`.
   - So even with “login shell”, the effective PATH can differ from the one you see in your day-to-day terminal.

4. **No second code path that “used to work”**
   - The UI has **never** called `/api/admin/create-backup`. It has always used **execute-command** with the string `bash ./scripts/package_user_data.sh --type ...`. So the only path that “worked for months” is this one, under an environment where PATH included `pg_dump`; the same path now fails under a different environment.

So the behavior change is explained by **who starts the backend and what PATH that launcher provides**, not by a recent change to the backup script or to the fact that we use execute-command.

---

## 4. Other findings (no fixes applied)

- **Unused endpoint:** `POST /api/admin/create-backup` runs `['bash', 'scripts/package_user_data.sh']` with a **restricted** PATH and no `--type` (script defaults to full). The frontend does not call this; it only uses execute-command. So create-backup is irrelevant to the current UI flow.
- **Download path on success:** The frontend uses a fixed path `/opt/rec_io_server/backup/${backupFileName}`. That is appropriate for a production server at that path; on a dev Mac the backup file is under `get_dynamic_project_root()/backup/`. So even if the backup step were to succeed locally, the download request could fail or point at the wrong place unless the server and UI are both in the same environment and the backend serves from that path.
- **Script itself:** Relies on `pg_dump` being on PATH; it does not assume a path for `pg_dump` and does not source any profile. So the only way to get `pg_dump` is for the **caller’s environment** (here, the shell started by the backend) to have the right PATH.

---

## 5. Summary

| Question | Answer |
|----------|--------|
| Why does backup fail now? | The process that runs `package_user_data.sh` has a PATH that does not include the directory containing `pg_dump`. That process is the subprocess started by the backend (a login shell running the script). |
| Why did it work before? | The backend was likely started in an environment (e.g. your terminal, or a process with a full PATH) where PATH included `pg_dump`. After a different way of starting (e.g. master restart, IDE, or service), the backend (and thus its subprocess) gets a different, minimal PATH. |
| What in the code is responsible? | The backup flow depends on **inherited environment** (no explicit `env` for the backup subprocess) and on the script using `pg_dump` without a path. So the effective PATH is entirely determined by how the backend is started and, for the login shell, by the user’s bash profile. No bug in the script logic; the contract is “run in an environment where pg_dump is on PATH”. |
| What was not changed in this audit? | No code was patched. This document only describes the flow and the cause of the current failure. |

To fix the failure you need to ensure the **environment** in which the backup runs has PATH containing the directory that holds `pg_dump` (e.g. by how the backend is started, or by explicitly setting PATH or the full path to `pg_dump` when running the backup – that would be a separate change, not done here).
