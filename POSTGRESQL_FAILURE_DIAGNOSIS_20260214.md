# PostgreSQL Failure Diagnosis — February 14, 2026

## Executive Summary

**Root cause:** A stale `postmaster.pid` lock file left behind when PostgreSQL was killed during the Mac restart. The LaunchAgent is loaded and repeatedly trying to start PostgreSQL, but each attempt fails because of the lock file. `brew services start` fails because the job is already loaded (duplicate bootstrap).

---

## Diagnosis Results

### 1. System Environment
| Component | Version |
|-----------|---------|
| macOS | **26.1** (Tahoe, build 25B78) |
| Homebrew | 4.6.7 |
| PostgreSQL | 15.13 |

### 2. LaunchAgent Status
- **Loaded:** YES — `homebrew.mxcl.postgresql@15` is present in launchd (gui/502)
- **Running:** NO — Process exits immediately on each start attempt
- **Schedulable:** NO

### 3. Root Cause: Stale Lock File

**File:** `/opt/homebrew/var/postgresql@15/postmaster.pid`

**Contents:**
```
1097          <- PID of PostgreSQL process from BEFORE restart
/opt/homebrew/var/postgresql@15
...
stopping      <- PostgreSQL was shutting down when Mac restarted
```

**What happened:** During the Mac restart, PostgreSQL (PID 1097) was killed before it could remove its lock file. The `postmaster.pid` file remained on disk. PID 1097 has since been reused by another process (Chrome); the postgres process no longer exists.

**Current behavior:** launchd (KeepAlive=true) tries to start PostgreSQL every ~10 seconds. Each attempt fails with:
```
FATAL: lock file "postmaster.pid" already exists
HINT: Is another postmaster (PID 1097) running in data directory?
```

PostgreSQL refuses to start because it thinks another instance is running.

### 4. Why `brew services start` Fails

`launchctl bootstrap` returns exit 5 (Input/output error) when the job is **already loaded**. The Homebrew PostgreSQL LaunchAgent is already in launchd (from a previous session or RunAtLoad). Homebrew attempts to bootstrap it again → duplicate job → failure.

### 5. PostgreSQL Data Directory — OK
- Binary exists: `/opt/homebrew/opt/postgresql@15/bin/postgres`
- Data directory exists and has correct structure
- No corruption detected
- Last successful run: November 13, 2025 (darwin24.4.0) — system has been upgraded to darwin26 since

### 6. Third-Party Updates
- **macOS 26.1 Tahoe** — Major OS upgrade. Release date Nov 3, 2025. Possible launchd/LaunchAgent behavior changes.
- **Plist:** Valid (plutil -lint OK)
- **Paths:** All plist paths exist and are accessible

---

## Fix (Execute in Order)

### Step 1: Remove the stale lock file
```bash
rm /opt/homebrew/var/postgresql@15/postmaster.pid
```

### Step 2: Verify PostgreSQL starts
The LaunchAgent has KeepAlive=true and will retry within ~10 seconds. Check:
```bash
sleep 15
pg_isready -h localhost -p 5432
```

### Step 3: If still not running — manual start
```bash
/opt/homebrew/opt/postgresql@15/bin/pg_ctl -D /opt/homebrew/var/postgresql@15 start
```

### Step 4: If `brew services start` still needed later
First bootout the existing job, then start:
```bash
launchctl bootout gui/502 ~/Library/LaunchAgents/homebrew.mxcl.postgresql@15.plist
brew services start postgresql@15
```

---

## Prevention (Optional)

Add a PostgreSQL health check to MASTER_RESTART that:
1. Removes stale `postmaster.pid` if the referenced PID is not postgres
2. Ensures `brew services start postgresql@15` runs before supervisor
