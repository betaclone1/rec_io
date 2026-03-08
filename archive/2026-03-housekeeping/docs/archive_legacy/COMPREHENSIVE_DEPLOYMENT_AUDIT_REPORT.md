# COMPREHENSIVE DEPLOYMENT AUDIT REPORT

**Note: These fixes must be completed in one day, not two days, and deployment should happen immediately afterward.**

## Complete System Analysis for Digital Ocean Mirror Deployment

**Date**: January 27, 2025  
**Purpose**: Identify ALL hardcoded local paths, URLs, and dependencies that prevent true mirror deployment  
**Goal**: Create a MIRROR IMAGE of the locally functional system on Digital Ocean

---

## 🚨 CRITICAL FINDINGS

### **1. HARDCODED LOCAL PATHS (MUST BE FIXED)**

#### **1.1 Absolute Path References**
- **File**: `backend/main.py` (Lines 1887, 2935, 2985, 3026, 3066)
  - `sys.path.append('/Users/ericwais1/rec_io_20')`
  - `project_dir = "/Users/ericwais1/rec_io_20"`
  - **Impact**: Will cause import failures on server

- **File**: `backend/system_monitor.py` (Line 152)
  - `if '/Users/ericwais1/rec_io_20' in proc['cmdline']:`
  - **Impact**: Process detection will fail on server

- **File**: `frontend/terminal-control.html` (Lines 165, 302)
  - `<strong>Current Directory:</strong> /Users/ericwais1/rec_io_20`
  - **Impact**: Frontend will show incorrect directory

#### **1.2 Supervisor Configuration Paths**
- **Files**: Multiple Python files reference `backend/supervisord.conf`
  - `backend/main.py` (Line 2944)
  - `backend/system_monitor.py` (Lines 78, 321, 569, 760, 777)
  - `backend/cascading_failure_detector.py` (Lines 84, 335)
  - `backend/core/port_flush.py` (Lines 75, 79, 83)
  - **Impact**: Supervisor commands will fail on server (different path structure)

#### **1.3 Homebrew Paths (macOS-specific)**
- **File**: `backend/main.py` (Lines 2939, 2990, 3031, 3075)
  - `supervisorctl_path = "/opt/homebrew/bin/supervisorctl"`
  - `env['PATH'] = '/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin'`
  - **Impact**: Will fail on Ubuntu server (different supervisor location)

---

### **2. INTERNAL SERVICE COMMUNICATION (MOSTLY OK)**

#### **2.1 Localhost Usage Analysis**
✅ **GOOD**: Most `localhost` references are correct for internal service communication
- Database connections: `host="localhost"` ✅
- Internal API calls: `http://localhost:{port}` ✅
- Service-to-service communication: ✅

⚠️ **POTENTIAL ISSUES**: Some services may need host detection
- **Files**: `backend/trade_manager.py`, `backend/active_trade_supervisor.py`
- **Issue**: Hardcoded `localhost` in some API calls
- **Impact**: May work but should use dynamic host detection

---

### **3. FRONTEND CONFIGURATION (GOOD)**

#### **3.1 Port Management System**
✅ **EXCELLENT**: Frontend uses centralized port configuration
- **File**: `frontend/js/globals.js`
- **System**: Dynamic port loading via `/api/ports`
- **Host**: Uses `window.location.hostname` (portable)
- **Status**: ✅ Ready for deployment

#### **3.2 Supervisor Status Integration**
✅ **GOOD**: Frontend supervisor status works via API
- **Endpoint**: `/api/admin/supervisor-status`
- **Files**: `frontend/tabs/system.html`, `frontend/mobile/system_mobile.html`
- **Status**: ✅ Ready for deployment

---

### **4. MASTER RESTART SYSTEM (NEEDS UPDATES)**

#### **4.1 Script Paths**
⚠️ **ISSUE**: MASTER_RESTART.sh uses relative paths
- **File**: `scripts/MASTER_RESTART.sh`
- **Issue**: Assumes local directory structure
- **Impact**: May fail on server with different layout

#### **4.2 Process Detection**
⚠️ **ISSUE**: Process killing uses macOS-specific patterns
- **File**: `scripts/MASTER_RESTART.sh`
- **Issue**: Uses `pkill -f "python.*backend"` patterns
- **Impact**: May not work correctly on Ubuntu

---

### **5. DATABASE CONFIGURATION (GOOD)**

#### **5.1 Environment Variables**
✅ **EXCELLENT**: Database uses environment variables
- **File**: `backend/core/config/database.py`
- **System**: `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
- **Status**: ✅ Ready for deployment

#### **5.2 Connection Strings**
✅ **GOOD**: All database connections use environment variables
- **Files**: All backend services
- **Pattern**: `host=os.getenv('POSTGRES_HOST', 'localhost')`
- **Status**: ✅ Ready for deployment

---

## 🔧 REQUIRED FIXES FOR DEPLOYMENT

### **Priority 1: Critical Path Issues**

#### **Fix 1.1: Dynamic Project Root Detection**
```python
# Replace hardcoded paths with dynamic detection
import os

def get_project_root():
    """Get the project root directory dynamically"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # Navigate up to find project root
    while current_dir != '/':
        if os.path.exists(os.path.join(current_dir, 'backend', 'main.py')):
            return current_dir
        current_dir = os.path.dirname(current_dir)
    raise FileNotFoundError("Could not find project root")

PROJECT_ROOT = get_project_root()
```

#### **Fix 1.2: Dynamic Supervisor Path Detection**
```python
# Replace hardcoded supervisor paths
def get_supervisorctl_path():
    """Get supervisorctl path for current system"""
    if os.path.exists("/opt/homebrew/bin/supervisorctl"):  # macOS
        return "/opt/homebrew/bin/supervisorctl"
    elif os.path.exists("/usr/bin/supervisorctl"):  # Ubuntu
        return "/usr/bin/supervisorctl"
    else:
        return "supervisorctl"  # Fallback to PATH

def get_supervisor_config_path():
    """Get supervisor config path relative to project root"""
    project_root = get_project_root()
    return os.path.join(project_root, "backend", "supervisord.conf")
```

#### **Fix 1.3: Update Frontend Directory Display**
```javascript
// Replace hardcoded directory in terminal-control.html
// Use dynamic detection or environment variable
const currentDirectory = window.location.hostname === 'localhost' 
    ? '/Users/ericwais1/rec_io_20' 
    : '/opt/trading_system';
```

### **Priority 2: System-Specific Adaptations**

#### **Fix 2.1: Process Detection Updates**
```python
# Update system_monitor.py process detection
def is_project_process(proc):
    """Check if process belongs to this project"""
    project_root = get_project_root()
    return project_root in proc.get('cmdline', '')
```

#### **Fix 2.2: MASTER_RESTART.sh Updates**
```bash
# Update script to work on both macOS and Ubuntu
# Add system detection and appropriate paths
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS paths
    SUPERVISORCTL="/opt/homebrew/bin/supervisorctl"
else
    # Ubuntu paths
    SUPERVISORCTL="/usr/bin/supervisorctl"
fi
```

---

## ✅ AUTHORITATIVE DECISIONS (LOCKED FOR TODAY)

1) **Config Auto-Save**: Remove it **now**. Config files must **never** be rewritten at runtime or during restarts. Only create a local config when missing via an explicit init command.
2) **Environment Variables**: Use the `REC_` prefix consistently for all envs. Ship a complete `.env.example`.
3) **Implementation Approach**: Minimal, incremental patches with clean diffs. Sequence below. Each step is reversible and tested.
4) **Testing Scope**: Add fast, automated portability checks that run locally and on DO (lint + no-config-writes + smoke).
5) **Database Migration**: Include a simple, optional backup/restore script. Do **not** tie app boot to DB restore.

---

## 🛠️ IMPLEMENTATION PLAN (TODAY)

### Step A — Config layering & no-clobber (PR: `config_no_clobber`)
- Introduce `config.default.json` (checked in) and `config.local.json` (git-ignored).
- Load order: **ENV → local → default** (later overrides earlier). Do **not** persist environment-derived values.
- Remove any auto-save-on-load behavior in `settings.py` (or equivalent `ConfigManager`).

**Minimal pattern (drop-in example):**
```python
import json, os, hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # adjust if needed
DEFAULT = ROOT / 'config.default.json'
LOCAL = ROOT / 'config.local.json'

def deep_merge(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        for k, v in b.items():
            out[k] = deep_merge(out.get(k), v)
        return out
    return b if b is not None else a

class Config:
    def __init__(self):
        base = json.loads(DEFAULT.read_text()) if DEFAULT.exists() else {}
        local = json.loads(LOCAL.read_text()) if LOCAL.exists() else {}
        merged = deep_merge(base, local)
        # ENV precedence (example for common keys)
        merged.setdefault('runtime', {})
        merged['runtime']['bind_host'] = os.getenv('REC_BIND_HOST', merged['runtime'].get('bind_host', '0.0.0.0'))
        merged['runtime']['target_host'] = os.getenv('REC_TARGET_HOST', merged['runtime'].get('target_host', '127.0.0.1'))
        self.data = merged

    # Never write during normal boot/restart
    def save_local_if_missing(self):
        if not LOCAL.exists():
            LOCAL.write_text(json.dumps(self.data, indent=2))
```

### Step B — Supervisor absolutes + restart discipline (PR: `supervisor_absolute_paths`)
- Convert all `command=`, `directory=`, `stdout_logfile`, `stderr_logfile` to **absolute** paths.
- Standardize on one socket/pid: `/tmp/supervisord.sock`, `/tmp/supervisord.pid`.
- Ensure `logs/` exists before start.
- Always call `supervisord`/`supervisorctl` with `-c <ABS>/backend/supervisord.conf`.

**Supervisor template (replace `<ABS_ROOT>` with the real absolute project root, e.g., `/opt/rec_io`):**
```ini
[supervisord]
logfile=/tmp/supervisord.log
pidfile=/tmp/supervisord.pid
nodaemon=true

[unix_http_server]
file=/tmp/supervisord.sock
chmod=0700

[supervisorctl]
serverurl=unix:///tmp/supervisord.sock

; Example program: main app
[program:main_app]
command=<ABS_ROOT>/venv/bin/python <ABS_ROOT>/backend/main.py
directory=<ABS_ROOT>
autostart=true
autorestart=true
startretries=3
stopasgroup=true
killasgroup=true
stdout_logfile=<ABS_ROOT>/logs/main_app.out.log
stderr_logfile=<ABS_ROOT>/logs/main_app.err.log

; Repeat blocks for each service with absolute paths only.
```

**MASTER_RESTART.sh essentials (insert/ensure):**
```bash
#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SUPERVISOR_CONF="$PROJECT_ROOT/backend/supervisord.conf"
mkdir -p "$PROJECT_ROOT/logs"

# Always target our config; ignore errors on shutdown
supervisorctl -c "$SUPERVISOR_CONF" shutdown || true

# Start supervisord if socket missing
if [ ! -S /tmp/supervisord.sock ]; then
  supervisord -c "$SUPERVISOR_CONF"
  sleep 1
fi

# Status for verification
supervisorctl -c "$SUPERVISOR_CONF" status
```

### Step C — Hosts & ports (PR: `env_hosts_ports`)
- Servers bind to `REC_BIND_HOST` (default `0.0.0.0`).
- Internal clients use `REC_TARGET_HOST` (default `127.0.0.1`).
- Keep per-agent overrides optional in `config.local.json` only; never persist detected IPs.

**.env.example (add/extend):**
```env
REC_BIND_HOST=0.0.0.0
REC_TARGET_HOST=127.0.0.1
REC_MAIN_PORT=3000
REC_TRADE_MANAGER_PORT=4000
REC_TRADE_EXECUTOR_PORT=8001
REC_ACTIVE_TRADE_SUPERVISOR_PORT=8007
REC_DB_HOST=127.0.0.1
REC_DB_PORT=5432
REC_DB_NAME=rec_io
REC_DB_USER=rec_user
REC_DB_PASS=change_me
REC_DB_SSLMODE=disable
REC_KALSHI_BASE_URL=https://api.elections.kalshi.com/trade-api/
REC_ACCOUNT_MODE=prod
REC_CREDENTIALS_PATH=backend/data/users/user_0001/credentials/kalshi-credentials
REC_LOG_DIR=<ABS_ROOT>/logs
```

### Step D — Tests & guardrails (PR: `portability_guardrails`)

**scripts/portability_lint.sh**
```bash
#!/usr/bin/env bash
set -euo pipefail
rg -n --hidden -S "(192\\.168\\.|/Users/|\\\\\\\\| C:\\\\|/home/|^http://|venv/bin/python|stdout_logfile=|directory=\.)" \
  | grep -v "^docs/" && { echo "\nPortability lint FAILED"; exit 1; } || echo "Lint OK"
```

**scripts/verify_no_config_writes.sh**
```bash
#!/usr/bin/env bash
set -euo pipefail
cfg_default="config.default.json"
cfg_local="config.local.json"
cksum_before=$(sha256sum "$cfg_default" "$cfg_local" 2>/dev/null || true)
# start services (no-op if already running)
supervisorctl -c "$(pwd)/backend/supervisord.conf" start all || true
sleep 30
cksum_after=$(sha256sum "$cfg_default" "$cfg_local" 2>/dev/null || true)
if [ "$cksum_before" != "$cksum_after" ]; then
  echo "Config files modified at runtime — FAIL"; exit 1
fi
echo "No config writes detected — OK"
```

**scripts/bootstrap_venv.sh**
```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3 -m venv venv
./venv/bin/pip install --upgrade pip wheel
./venv/bin/pip install -r requirements.txt
```

**scripts/db_restore.sh** (optional, explicit only)
```bash
#!/usr/bin/env bash
set -euo pipefail
FILE="${1:-}"
[ -z "$FILE" ] && { echo "Usage: $0 <dump.sql|dump.dump>"; exit 1; }
: "${REC_DB_HOST:=127.0.0.1}" "${REC_DB_PORT:=5432}" "${REC_DB_NAME:=rec_io}" "${REC_DB_USER:=rec_user}" "${REC_DB_PASS:=}" "${REC_DB_SSLMODE:=disable}"
export PGPASSWORD="$REC_DB_PASS"
case "$FILE" in
  *.dump) pg_restore -h "$REC_DB_HOST" -p "$REC_DB_PORT" -U "$REC_DB_USER" -d "$REC_DB_NAME" --clean --if-exists "$FILE" ;;
  *.sql) psql -h "$REC_DB_HOST" -p "$REC_DB_PORT" -U "$REC_DB_USER" -d "$REC_DB_NAME" -v ON_ERROR_STOP=1 -f "$FILE" ;;
  *) echo "Unsupported file type"; exit 1;;

esac
```

---

## ✅ ACCEPTANCE GATES (TODAY)
- `scripts/verify_no_config_writes.sh` passes locally.
- `supervisorctl -c <ABS_ROOT>/backend/supervisord.conf status` shows all RUNNING.
- Local health endpoints return 200.
- Fresh DO droplet, run documented runbook verbatim → same results; no config files modified.

---

## 📋 DEPLOYMENT CHECKLIST

### **Step 1: Code Fixes (REQUIRED — COMPLETE TODAY)**
*All steps are to be completed in a single development session today.*

- [ ] **1.1** Implement dynamic project root detection
- [ ] **1.2** Replace hardcoded supervisor paths
- [ ] **1.3** Update frontend directory displays
- [ ] **1.4** Fix process detection logic
- [ ] **1.5** Update MASTER_RESTART.sh for cross-platform compatibility

### **Step 2: Configuration Updates**
- [ ] **2.1** Create server-specific environment variables
- [ ] **2.2** Update supervisor configuration for server paths
- [ ] **2.3** Test all API endpoints with server hostnames

### **Step 3: Testing**
- [ ] **3.1** Test MASTER_RESTART on local system after fixes
- [ ] **3.2** Verify all frontend tools work (supervisor status, terminal, logs)
- [ ] **3.3** Test database connectivity with server configuration

### **Step 4: Deployment**
- [ ] **4.1** Upload fixed codebase to server
- [ ] **4.2** Configure server environment variables
- [ ] **4.3** Test complete system functionality

---

## 🎯 RECOMMENDATIONS

### **Immediate Actions**
1. **STOP** any further deployment attempts until these fixes are implemented TODAY
2. **Implement** dynamic path detection system
3. **Test** all fixes locally before attempting server deployment
4. **Create** server-specific configuration templates

### **Architecture Improvements**
1. **Centralize** all path detection in a single module
2. **Create** environment-specific configuration files
3. **Implement** proper logging for path detection failures
4. **Add** health checks for configuration loading

### **Deployment Strategy**
1. **Use** environment variables for all system-specific paths
2. **Implement** graceful fallbacks for missing configurations
3. **Create** comprehensive testing before deployment
4. **Document** all server-specific requirements
5. **Perform a full DO droplet deployment immediately upon fix completion to confirm portability and stability**

---

## 🚨 CONCLUSION

**The system is NOT ready for deployment** in its current state. The hardcoded paths and macOS-specific configurations will cause immediate failures on the Ubuntu server.

**Estimated time to fix: 3–5 hours of focused development — all to be completed today**, and this is a same-day task, not multi-day.

**Risk level**: HIGH - attempting deployment without fixes will result in complete failure

**Next steps**: Implement the Priority 1 fixes, test locally, then proceed with deployment.
