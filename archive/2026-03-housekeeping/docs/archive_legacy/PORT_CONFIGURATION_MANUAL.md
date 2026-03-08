# PORT CONFIGURATION SYSTEM - MASTER INSTRUCTION MANUAL

## Overview
This manual defines the **mandatory procedure** for adding, modifying, or removing services in the REC.IO trading system. **ALL changes must follow this procedure exactly** to avoid system-wide failures.

## System Architecture

### Centralized Port Management
- **Primary Config**: `backend/core/config/MASTER_PORT_MANIFEST.json`
- **Fallback Config**: `backend/core/port_config.py` (DEFAULT_PORTS)
- **Service Integration**: All services MUST use `get_port(service_name)` function
- **Supervisor Config**: `backend/supervisord.conf`

### Port Ranges
- **Safe Range**: 8000-8100 (avoiding macOS system services)
- **Core Services**: 3000, 4000, 6000, 8001
- **Watchdog Services**: 8002-8100
- **Avoid**: 5000, 7000, 9000, 10000 (macOS conflicts)

## MANDATORY PROCEDURE FOR NEW SERVICES

### Step 1: Add to Fallback Configuration
**File**: `backend/core/port_config.py`
**Action**: Add service to DEFAULT_PORTS dictionary

```python
DEFAULT_PORTS = {
    "main_app": 3000,
    "trade_manager": 4000,
    "trade_executor": 8001,
    "active_trade_supervisor": 6000,
    "btc_price_watchdog": 8002,
    "db_poller": 8003,
    "kalshi_account_sync": 8004,
    "kalshi_api_watchdog": 8005,
    "NEW_SERVICE_NAME": 8007  # ← ADD HERE FIRST
}
```

### Step 2: Add to Master Port Manifest
**File**: `backend/core/config/MASTER_PORT_MANIFEST.json`
**Action**: Add service configuration

```json
{
  "core_services": {
    "NEW_SERVICE_NAME": {
      "port": 8007,
      "description": "Description of what this service does",
      "status": "RUNNING"
    }
  }
}
```

**OR** for watchdog services:

```json
{
  "watchdog_services": {
    "NEW_SERVICE_NAME": {
      "port": 8007,
      "description": "Description of what this service does", 
      "status": "RUNNING"
    }
  }
}
```

### Step 3: Update Service Code
**File**: `backend/api/[category]/[service_name].py`
**Action**: Replace hardcoded ports with centralized system

```python
# ❌ WRONG - Never hardcode ports
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8007)

# ✅ CORRECT - Use centralized port system
from backend.core.port_config import get_port

# Get port from centralized system
SERVICE_PORT = get_port("NEW_SERVICE_NAME")
print(f"[SERVICE_NAME] 🚀 Using centralized port: {SERVICE_PORT}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
```

### Step 4: Add to Supervisor Configuration
**File**: `backend/supervisord.conf`
**Action**: Add service program section

```ini
[program:NEW_SERVICE_NAME]
command=python backend/api/[category]/[service_name].py
directory=.
autostart=true
autorestart=true
stderr_logfile=logs/NEW_SERVICE_NAME.err.log
stdout_logfile=logs/NEW_SERVICE_NAME.out.log
environment=PATH="venv/bin",PYTHONPATH="."
```

### Step 5: Test Service Manually
**Command**: Test the service before adding to supervisor

```bash
# Test the service manually first
source venv/bin/activate
python backend/api/[category]/[service_name].py

# Verify it starts without errors
# Verify it uses the correct port
# Verify it can be stopped with Ctrl+C
```

### Step 6: Restart Supervisor
**Command**: Apply changes to running system

```bash
./scripts/MASTER_RESTART.sh
```

### Step 7: Verify Service Status
**Command**: Confirm service is running correctly

```bash
supervisorctl -c backend/supervisord.conf status
```

## MANDATORY PROCEDURE FOR MODIFYING EXISTING SERVICES

### Step 1: Update Port Assignment (if needed)
**File**: `backend/core/config/MASTER_PORT_MANIFEST.json`
**Action**: Change port number if required

```json
{
  "core_services": {
    "EXISTING_SERVICE": {
      "port": 8008,  # ← Changed from 8007
      "description": "Updated description",
      "status": "RUNNING"
    }
  }
}
```

### Step 2: Update Fallback Configuration
**File**: `backend/core/port_config.py`
**Action**: Update DEFAULT_PORTS if port changed

```python
DEFAULT_PORTS = {
    # ... other services ...
    "EXISTING_SERVICE": 8008,  # ← Updated port
}
```

### Step 3: Test Service Manually
**Command**: Verify changes work before restarting supervisor

```bash
source venv/bin/activate
python backend/api/[category]/[service_name].py
```

### Step 4: Restart Supervisor
**Command**: Apply changes

```bash
./scripts/MASTER_RESTART.sh
```

## MANDATORY PROCEDURE FOR REMOVING SERVICES

### Step 1: Remove from Supervisor Configuration
**File**: `backend/supervisord.conf`
**Action**: Delete the entire program section

```ini
# DELETE THIS ENTIRE SECTION
[program:OLD_SERVICE_NAME]
command=python backend/api/[category]/[service_name].py
directory=.
autostart=true
autorestart=true
stderr_logfile=logs/OLD_SERVICE_NAME.err.log
stdout_logfile=logs/OLD_SERVICE_NAME.out.log
environment=PATH="venv/bin",PYTHONPATH="."
```

### Step 2: Remove from Master Port Manifest
**File**: `backend/core/config/MASTER_PORT_MANIFEST.json`
**Action**: Delete service entry

```json
{
  "core_services": {
    // DELETE THIS ENTIRE ENTRY
    "OLD_SERVICE_NAME": {
      "port": 8007,
      "description": "Old service",
      "status": "RUNNING"
    }
  }
}
```

### Step 3: Remove from Fallback Configuration
**File**: `backend/core/port_config.py`
**Action**: Remove from DEFAULT_PORTS

```python
DEFAULT_PORTS = {
    "main_app": 3000,
    "trade_manager": 4000,
    # DELETE THIS LINE
    "OLD_SERVICE_NAME": 8007,
}
```

### Step 4: Restart Supervisor
**Command**: Apply removal

```bash
./scripts/MASTER_RESTART.sh
```

## CRITICAL RULES

### Rule 1: Never Hardcode Ports
```python
# ❌ NEVER DO THIS
uvicorn.run(app, host="0.0.0.0", port=8007)

# ✅ ALWAYS DO THIS
from backend.core.port_config import get_port
SERVICE_PORT = get_port("SERVICE_NAME")
uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
```

### Rule 2: Always Test Manually First
- Test service manually before adding to supervisor
- Verify port assignment works
- Verify service starts and stops cleanly

### Rule 3: Follow the Order
1. Add to DEFAULT_PORTS (fallback)
2. Add to MASTER_PORT_MANIFEST.json (primary)
3. Update service code (use centralized system)
4. Add to supervisord.conf
5. Test manually
6. Restart supervisor
7. Verify status

### Rule 4: Use Correct Log Paths
```ini
# ✅ CORRECT - Use logs/ directory
stderr_logfile=logs/SERVICE_NAME.err.log
stdout_logfile=logs/SERVICE_NAME.out.log

# ❌ WRONG - Don't use /tmp/
stderr_logfile=/tmp/SERVICE_NAME.err.log
stdout_logfile=/tmp/SERVICE_NAME.out.log
```

### Rule 5: Check Port Conflicts
```bash
# Before adding new service, check if port is free
lsof -i :8007

# If port is in use, kill the process or choose different port
kill -9 [PID]
```

## TROUBLESHOOTING CHECKLIST

### Service Won't Start
- [ ] Added to DEFAULT_PORTS in port_config.py
- [ ] Added to MASTER_PORT_MANIFEST.json
- [ ] Service code uses get_port() function
- [ ] Added to supervisord.conf
- [ ] Log paths point to logs/ directory
- [ ] Port is not in use by another process
- [ ] Python path issues resolved (sys.path setup)

### Port Already in Use
- [ ] Check what's using the port: `lsof -i :PORT`
- [ ] Kill conflicting process: `kill -9 PID`
- [ ] Or choose different port in manifest

### Import Errors
- [ ] Service has proper sys.path setup
- [ ] All imports use 'backend.' prefix
- [ ] Service runs from correct directory

### Supervisor Issues
- [ ] All log paths are correct
- [ ] All environment variables set
- [ ] Service executable and has proper permissions

## QUICK REFERENCE

### Add New Service
1. `port_config.py` → DEFAULT_PORTS
2. `MASTER_PORT_MANIFEST.json` → Add service
3. Service code → Use `get_port()`
4. `supervisord.conf` → Add program section
5. Test manually
6. `MASTER_RESTART.sh`
7. Verify status

### Modify Service
1. `MASTER_PORT_MANIFEST.json` → Update port/description
2. `port_config.py` → Update DEFAULT_PORTS (if port changed)
3. Test manually
4. `MASTER_RESTART.sh`
5. Verify status

### Remove Service
1. `supervisord.conf` → Delete program section
2. `MASTER_PORT_MANIFEST.json` → Delete service entry
3. `port_config.py` → Remove from DEFAULT_PORTS
4. `MASTER_RESTART.sh`
5. Verify removal

## COMMON MISTAKES TO AVOID

1. **Hardcoding ports** - Always use centralized system
2. **Skipping manual testing** - Test before supervisor restart
3. **Wrong log paths** - Use logs/ not /tmp/
4. **Missing fallback** - Always add to DEFAULT_PORTS
5. **Wrong import paths** - Use 'backend.' prefix
6. **Port conflicts** - Check before assigning
7. **Incomplete procedure** - Follow ALL steps in order

## EMERGENCY RECOVERY

If system breaks after service changes:

1. **Stop supervisor**: `supervisorctl -c backend/supervisord.conf shutdown`
2. **Kill all processes**: `pkill -f python`
3. **Check port conflicts**: `lsof -i :[PORT]`
4. **Fix configuration**: Follow procedure above
5. **Restart**: `./scripts/MASTER_RESTART.sh`

---

**This manual is MANDATORY for all service modifications. Follow every step exactly to avoid system failures.** 