#!/bin/bash

# =============================================================================
# MASTER RESTART FUNCTION - UNIVERSAL SYSTEM RESTART
# =============================================================================
# This script provides a complete system restart with port flushing and
# supervisor restart. Use this as the primary tool for starting/restarting
# the trading system.
#
# Every supervisord start done through this script runs generate_unified_supervisor_config.py
# first so active system.master_users get user-level program blocks. For OS boot without
# MASTER_RESTART, use scripts/supervisord_with_config_regen.sh as supervisord's command.
# =============================================================================

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Load unified configuration system
source "$(dirname -- "${BASH_SOURCE[0]}")/load_unified_config.sh"

# Configuration - Use unified configuration
SUPERVISOR_CONFIG="$REC_PROJECT_ROOT/backend/supervisord.conf"
SUPERVISOR_SOCKET="/tmp/supervisord.sock"
SUPERVISOR_PID="/tmp/supervisord.pid"

# Port assignments from MASTER_PORT_MANIFEST.json
PORTS=(3000 4000 6000 8001 8002 8003 8004 8005 8008)

# Function to print colored output
print_status() {
    echo -e "${BLUE}[MASTER_RESTART]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[MASTER_RESTART] ✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[MASTER_RESTART] ⚠️${NC} $1"
}

print_error() {
    echo -e "${RED}[MASTER_RESTART] ❌${NC} $1"
}

print_header() {
    echo -e "${PURPLE}=============================================================================${NC}"
    echo -e "${PURPLE}                    MASTER RESTART FUNCTION${NC}"
    echo -e "${PURPLE}=============================================================================${NC}"
}

# Sanitization gate before restart: not enforced (snapshot→new prod; first-boot
# wipe is opt-in in first_boot_sanitize.sh via REC_ENABLE_FIRST_BOOT_SANITIZE=1).
# check_sanitization_status() {
#     return 0
# }

# Function to check if a port is in use (only listening processes)
check_port() {
    local port=$1
    if lsof -i :$port | grep LISTEN >/dev/null 2>&1; then
        return 0  # Port is in use (listening)
    else
        return 1  # Port is free
    fi
}

# Function to kill processes on a specific port
kill_port() {
    local port=$1
    print_status "Checking port $port..."
    
    if check_port $port; then
        print_warning "Port $port is in use. Killing processes..."
        
        # Get the process IDs using the port
        local pids=$(lsof -ti :$port 2>/dev/null)
        if [ -n "$pids" ]; then
            print_warning "Found processes on port $port: $pids"
            
            # Kill the processes
            echo "$pids" | xargs kill -9 2>/dev/null || true
            /bin/sleep 2
            
            # Try again if still in use
            if check_port $port; then
                print_warning "Port $port still in use, trying again..."
                /bin/sleep 2
                lsof -ti :$port | xargs kill -9 2>/dev/null || true
                /bin/sleep 2
            fi
            
            # Final verification
            if check_port $port; then
                print_error "Failed to free port $port after multiple attempts"
                return 1
            else
                print_success "Port $port freed"
            fi
        else
            print_warning "No process IDs found for port $port"
            return 1
        fi
    else
        print_success "Port $port is already free"
    fi
}

# Function to flush all ports
flush_all_ports() {
    print_header
    print_status "Starting port flush operation..."
    
    for port in "${PORTS[@]}"; do
        kill_port $port
    done
    
    print_success "All ports flushed"
}

# Redis: stack expects a real redis-server on REDIS_HOST:REDIS_PORT (supervisor only runs redis_switchboard).
# Defaults match supervisord env (localhost:6379).
_redis_ping_ok() {
    local h="${1:-localhost}"
    local p="${2:-6379}"
    if command -v redis-cli >/dev/null 2>&1; then
        redis-cli -h "$h" -p "$p" ping 2>/dev/null | grep -q PONG
        return $?
    fi
    # No redis-cli: best-effort TCP check (local only)
    if [ "$h" = "localhost" ] || [ "$h" = "127.0.0.1" ]; then
        nc -z 127.0.0.1 "$p" >/dev/null 2>&1
        return $?
    fi
    return 1
}

_redis_host_is_local() {
    local h="${1:-localhost}"
    case "$h" in
        localhost|127.0.0.1|"") return 0 ;;
        *) return 1 ;;
    esac
}

# Try to start redis-server on this machine (macOS Homebrew, systemd Linux, or redis-server in PATH).
_start_redis_local() {
    local started=0
    if [ "$(uname -s 2>/dev/null)" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
        if brew services start redis >/dev/null 2>&1; then
            started=1
        fi
    fi
    if [ "$started" != "1" ] && command -v systemctl >/dev/null 2>&1; then
        if systemctl start redis-server >/dev/null 2>&1 || systemctl start redis >/dev/null 2>&1; then
            started=1
        fi
    fi
    if [ "$started" != "1" ] && command -v redis-server >/dev/null 2>&1; then
        local conf=""
        for c in /opt/homebrew/etc/redis.conf /usr/local/etc/redis.conf /etc/redis/redis.conf; do
            if [ -f "$c" ]; then
                conf="$c"
                break
            fi
        done
        if [ -n "$conf" ]; then
            redis-server "$conf" --daemonize yes >/dev/null 2>&1 && started=1
        else
            redis-server --daemonize yes >/dev/null 2>&1 && started=1
        fi
    fi
    [ "$started" = "1" ]
}

# Ensure Redis responds before processes that use it (switchboard, main forwarders, ATS, etc.).
ensure_redis_available() {
    local rh="${REDIS_HOST:-localhost}"
    local rp="${REDIS_PORT:-6379}"
    print_status "Checking Redis (${rh}:${rp})..."
    if _redis_ping_ok "$rh" "$rp"; then
        print_success "Redis is responding"
        return 0
    fi
    if ! _redis_host_is_local "$rh"; then
        print_warning "Redis at ${rh}:${rp} is not responding (non-local host; not auto-starting). Install redis-cli to verify, or start Redis on that host."
        return 0
    fi
    print_warning "Redis is not responding; attempting to start a local redis-server..."
    if ! _start_redis_local; then
        print_warning "Could not start Redis automatically (install: brew install redis, or apt install redis-server). Continuing; services may log Connection refused until Redis runs."
        return 0
    fi
    local n=0
    while [ $n -lt 20 ]; do
        if _redis_ping_ok "$rh" "$rp"; then
            print_success "Redis is responding after start"
            return 0
        fi
        /bin/sleep 0.5
        n=$((n + 1))
    done
    print_warning "Redis start was attempted but PING still fails after 10s. Check logs: brew services info redis (macOS) or journalctl -u redis (Linux)."
    return 0
}

# Function to stop supervisor
stop_supervisor() {
    print_status "Stopping supervisor..."
    
    if [ -S "$SUPERVISOR_SOCKET" ]; then
        "$REC_SUPERVISORCTL" -c "$SUPERVISOR_CONFIG" shutdown 2>/dev/null || true
        /bin/sleep 2
    fi
    
    # Kill supervisor process if still running
    if [ -f "$SUPERVISOR_PID" ]; then
        local pid=$(cat "$SUPERVISOR_PID")
        if kill -0 $pid 2>/dev/null; then
            print_warning "Killing supervisor process $pid"
            kill -9 $pid 2>/dev/null || true
        fi
    fi
    
    # Clean up socket and pid files
    rm -f "$SUPERVISOR_SOCKET" "$SUPERVISOR_PID" 2>/dev/null || true
    
    print_success "Supervisor stopped"
}

# Regenerate backend/supervisord.conf from the database (active system.master_users → per-user stacks).
# Call this before every supervisord start so reboot / quick restart picks up newly active users.
regenerate_supervisor_config() {
    print_status "Regenerating supervisord.conf from DB (active system.master_users + per-tenant monitors)..."
    if [ ! -f "$REC_PROJECT_ROOT/scripts/config/generate_unified_supervisor_config.py" ]; then
        print_error "scripts/config/generate_unified_supervisor_config.py not found"
        return 1
    fi
    # Mirror unified loader export so get_database_config() sees the same password as unified_config.
    if [ -n "${REC_DB_PASSWORD:-}" ] && [ -z "${REC_DB_PASS:-}" ]; then
        export REC_DB_PASS="$REC_DB_PASSWORD"
    fi
    if ! "$REC_PYTHON_EXECUTABLE" "$REC_PROJECT_ROOT/scripts/config/generate_unified_supervisor_config.py"; then
        print_error "Supervisor configuration generation failed (see Python errors above); not starting with stale config."
        return 1
    fi
    print_success "Supervisor configuration written: $SUPERVISOR_CONFIG"
}

# Function to start supervisor
start_supervisor() {
    print_status "Starting supervisor..."

    # Force Python to load current source (avoids stale .pyc; ensures account sync and all backend use disk code)
    _REPO_ROOT="$(cd "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
    rm -rf "${_REPO_ROOT}/backend/__pycache__" 2>/dev/null || true

    regenerate_supervisor_config || return 1

    local config_to_use="$SUPERVISOR_CONFIG"
    print_status "Using supervisord: $REC_SUPERVISORD"

    if [ "$(uname -s)" = "Darwin" ]; then
        # nodaemon=true in repo config ties supervisord to the shell; daemonize on macOS.
        config_to_use="${REC_PROJECT_ROOT}/backend/.supervisord.daemon.conf"
        sed 's/^nodaemon=true$/nodaemon=false/' "$SUPERVISOR_CONFIG" > "$config_to_use"
        print_status "macOS: starting supervisord as daemon (nodaemon=false)"
        "$REC_SUPERVISORD" -c "$config_to_use"
    else
        nohup "$REC_SUPERVISORD" -c "$SUPERVISOR_CONFIG" </dev/null >>"${REC_PROJECT_ROOT}/logs/supervisord_nohup.log" 2>&1 &
        local supervisor_pid=$!
        disown "$supervisor_pid" 2>/dev/null || true
        print_status "Supervisor background PID: $supervisor_pid"
    fi

    # Wait for supervisor to start
    local attempts=0
    while [ $attempts -lt 30 ]; do
        if [ -S "$SUPERVISOR_SOCKET" ]; then
            break
        fi
        /bin/sleep 1
        attempts=$((attempts + 1))
    done

    if [ -S "$SUPERVISOR_SOCKET" ]; then
        local running_pid=""
        if [ -f "$SUPERVISOR_PID" ]; then
            running_pid=$(cat "$SUPERVISOR_PID" 2>/dev/null || true)
        fi
        print_success "Supervisor started${running_pid:+ (PID: $running_pid)}"
    else
        print_error "Failed to start supervisor"
        return 1
    fi
}

# Function to restart all services
# Restarts each program in sequence so we never have old + new instances (e.g. duplicate
# auto_entry_supervisor per monitor). Supervisor "uncaptured python exception" / FileNotFoundError
# in the log during restart is known noise on macOS (kqueue) and can be ignored if services end up RUNNING.
#
# supervisorctl restart sometimes returns non-zero (e.g. 7) while the child still reaches RUNNING
# (abnormal termination during handoff). With set -e, treat that as success when status is RUNNING/STARTING.
restart_all_services() {
    print_status "Restarting all services..."
    
    # Wait a moment for supervisor to fully initialize
    /bin/sleep 2
    
    local programs
    programs=$("$REC_SUPERVISORCTL" -c "$SUPERVISOR_CONFIG" status | awk '{print $1}' | grep -v "supervisorctl")
    
    for program in $programs; do
        print_status "Restarting $program..."
        if "$REC_SUPERVISORCTL" -c "$SUPERVISOR_CONFIG" restart "$program"; then
            :
        else
            local rc=$?
            print_warning "supervisorctl restart $program exited with code $rc (often transient); rechecking status..."
            /bin/sleep 2
            local state
            state=$("$REC_SUPERVISORCTL" -c "$SUPERVISOR_CONFIG" status "$program" 2>/dev/null | awk '{print $2}')
            if [ "$state" = "RUNNING" ] || [ "$state" = "STARTING" ]; then
                print_warning "$program is $state after non-zero restart exit; continuing"
            else
                print_error "$program restart failed (supervisorctl exit $rc, state=${state:-unknown})"
                return "$rc"
            fi
        fi
        /bin/sleep 1
    done
    
    print_success "All services restarted"
}

# Set when Step 0 puts DB in maintenance; cleared after Step 8. If the script exits early (set -e),
# restore trading mode so operators are not stuck in maintenance.
_MASTER_RESTART_MAINT_ACTIVE=0

_master_restart_exit_cleanup() {
    if [ "${_MASTER_RESTART_MAINT_ACTIVE:-0}" != "1" ]; then
        return 0
    fi
    print_warning "MASTER_RESTART did not finish all steps; setting core.system_state.mode to 'normal' (trading re-enabled)..."
    PGPASSWORD="${POSTGRES_PASSWORD:-${DB_PASSWORD:-rec_io_password}}" psql -h localhost -U rec_io_user -d rec_io_db <<'EOF' >/dev/null 2>&1
INSERT INTO core.system_state (id, mode)
VALUES (1, 'normal')
ON CONFLICT (id) DO UPDATE
SET mode = EXCLUDED.mode,
    updated_at = now();
EOF
    _MASTER_RESTART_MAINT_ACTIVE=0
}

# Confirm supervisord survived script exit (macOS orphan issue when socket dies).
verify_supervisord_alive() {
    /bin/sleep 3
    if [ -S "$SUPERVISOR_SOCKET" ] && "$REC_SUPERVISORCTL" -c "$SUPERVISOR_CONFIG" status >/dev/null 2>&1; then
        print_success "Supervisord responding on $SUPERVISOR_SOCKET"
        return 0
    fi
    print_error "Supervisord is not responding (socket dead). Check logs/supervisord.log and logs/supervisord_nohup.log"
    return 1
}

# Function to verify all services are running
verify_services() {
    print_status "Verifying all services are running..."
    
    local all_running=true
    
    # Check supervisor status
    local status_output=$("$REC_SUPERVISORCTL" -c "$SUPERVISOR_CONFIG" status)
    echo "$status_output" | while IFS= read -r line; do
        if [[ $line =~ ^[a-zA-Z_]+[[:space:]]+(RUNNING|STARTING) ]]; then
            local service=$(echo "$line" | awk '{print $1}')
            local state=$(echo "$line" | awk '{print $2}')
            if [ "$state" = "RUNNING" ]; then
                print_success "$service is running"
            else
                print_warning "$service is starting..."
            fi
        elif [[ $line =~ ^[a-zA-Z_]+[[:space:]]+(FATAL|EXITED|STOPPED) ]]; then
            local service=$(echo "$line" | awk '{print $1}')
            print_error "$service failed to start"
            all_running=false
        fi
    done
    
    # Check if all ports are now in use by our services
    print_status "Verifying port assignments..."
    for port in "${PORTS[@]}"; do
        if check_port $port; then
            print_success "Port $port is active"
        else
            print_warning "Port $port is not in use (may be normal for watchdog services)"
        fi
    done
    
    if [ "$all_running" = true ]; then
        print_success "All services verified"
    else
        print_error "Some services failed to start"
        return 1
    fi
}

# Function to show system status
show_status() {
    print_header
    print_status "Current system status:"
    echo ""
    
    # Show supervisor status
    "$REC_SUPERVISORCTL" -c "$SUPERVISOR_CONFIG" status
    
    echo ""
    print_status "Port usage:"
    for port in "${PORTS[@]}"; do
        if check_port $port; then
            local process=$(lsof -i :$port | grep LISTEN | awk '{print $1}' | head -1)
            print_success "Port $port: $process"
        else
            print_warning "Port $port: free"
        fi
    done
}

# Function to check for external connections
check_external_connections() {
    print_status "Checking for external connections that might interfere..."
    
    local external_connections=$(lsof -i | grep -E "(64\.23\.138\.71|digitalocean)" 2>/dev/null || true)
    if [ -n "$external_connections" ]; then
        print_warning "Found external connections to remote servers:"
        echo "$external_connections"
        print_warning "These connections will be terminated during restart"
        echo ""
    else
        print_success "No external connections detected"
        echo ""
    fi
}

# Function to ensure python dependencies are installed.
# Runs pip install only when requirements files change, to avoid re-installing everything on every restart.
ensure_dependencies() {
    print_status "Ensuring Python dependencies (requirements sync)..."

    # requirements*.txt live at the project root
    local req_core="$REC_PROJECT_ROOT/requirements-core.txt"
    local req_full="$REC_PROJECT_ROOT/requirements.txt"

    # Use the venv python executable discovered by unified config
    local py="$REC_PYTHON_EXECUTABLE"

    if [ ! -f "$py" ]; then
        print_error "Python executable not found: $py"
        return 1
    fi

    if [ ! -f "$req_core" ] && [ ! -f "$req_full" ]; then
        print_warning "No requirements-core.txt or requirements.txt found; skipping dependency install."
        return 0
    fi

    local marker="$REC_PROJECT_ROOT/.requirements_installed_marker"

    # Hash the requirements files so we can skip pip install if nothing changed.
    local core_hash=""
    local full_hash=""
    if [ -f "$req_core" ]; then
        core_hash="$(sha256sum "$req_core" | awk '{print $1}')"
    fi
    if [ -f "$req_full" ]; then
        full_hash="$(sha256sum "$req_full" | awk '{print $1}')"
    fi

    local prev_core=""
    local prev_full=""
    if [ -f "$marker" ]; then
        read -r prev_core prev_full < "$marker" || true
    fi

    if [ -n "$core_hash" ] && [ -n "$full_hash" ] && [ "$core_hash" = "$prev_core" ] && [ "$full_hash" = "$prev_full" ]; then
        print_success "Dependencies up to date (requirements unchanged)."
        return 0
    fi

    print_status "Installing dependencies into venv (best-effort)..."

    # SciPy is the main source of install failures across environments because it may require
    # wheels (which depend on Python version) or a native toolchain (gfortran/clang toolchain).
    # We still want restart to succeed and we still want "new deps" like redis to install.
    # So: install everything EXCEPT SciPy first, then attempt SciPy as best-effort.

    local tmpdir
    tmpdir="$(mktemp -d)"

    # Filter SciPy out: lines starting with "scipy" + a version/operator are removed.
    # Keep comments/blank lines and all other deps.
    local core_no_scipy="$tmpdir/requirements-core.no-scipy.txt"
    local full_no_scipy="$tmpdir/requirements.no-scipy.txt"
    local core_install_ok=1
    local full_install_ok=1

    set +e

    if [ -f "$req_core" ]; then
        awk '!/^scipy[=<>!~]/ {print}' "$req_core" > "$core_no_scipy"
        "$py" -m pip install -r "$core_no_scipy"
        core_install_ok=$?
    fi
    if [ -f "$req_full" ]; then
        awk '!/^scipy[=<>!~]/ {print}' "$req_full" > "$full_no_scipy"
        "$py" -m pip install -r "$full_no_scipy"
        full_install_ok=$?
    fi

    # SciPy is a frequent source of install failures (no wheel for platform/Python,
    # or missing native toolchain). If it's already importable, we skip installing
    # a potentially pinned version; restart must keep progressing.
    local scipy_version=""
    scipy_version="$("$py" -c "import scipy,sys; sys.stdout.write(getattr(scipy,'__version__',''))" 2>/dev/null || true)"

    if [ -z "$scipy_version" ]; then
        print_warning "SciPy not found in venv; attempting pinned SciPy install best-effort..."

        # Prefer installing the core SciPy version first, if present.
        local scipy_core_ver=""
        local scipy_full_ver=""
        scipy_core_ver="$(awk -F'==' '/^scipy==/ {print $2; exit}' "$req_core" 2>/dev/null || true)"
        scipy_full_ver="$(awk -F'==' '/^scipy==/ {print $2; exit}' "$req_full" 2>/dev/null || true)"

        if [ -n "$scipy_core_ver" ]; then
            "$py" -m pip install --only-binary=:all: "scipy==$scipy_core_ver" || true
        elif [ -n "$scipy_full_ver" ]; then
            "$py" -m pip install --only-binary=:all: "scipy==$scipy_full_ver" || true
        fi
    else
        print_warning "SciPy already installed (version=${scipy_version}); skipping SciPy install."
    fi

    set -e

    # Update marker if at least one requirements install succeeded (SciPy is best-effort).
    if [ "$core_install_ok" = "0" ] || [ "$full_install_ok" = "0" ]; then
        echo "${core_hash} ${full_hash}" > "$marker"
        print_success "Python dependencies ensured (SciPy best-effort)."
    else
        print_warning "Dependency install failed for both requirements sets (non-SciPy deps may be missing). Not updating marker."
    fi
}

# Function to perform complete restart
master_restart() {
    print_header
    print_status "Initiating MASTER RESTART sequence..."
    echo ""
    
    # Check sanitization status first (SECURITY CHECK) - DISABLED FOR PRODUCTION
    # check_sanitization_status
    # echo ""
    
    # Create logs directory if it doesn't exist
    print_status "Ensuring logs directory exists..."
    mkdir -p "$PROJECT_ROOT/logs"
    print_success "Logs directory ready"
    echo ""

    ensure_redis_available
    echo ""
    
    # Check for external connections first
    check_external_connections

    # Step 0: Put system into maintenance mode to block new trades
    print_status "Step 0: Setting system_state.mode to 'maintenance' (trading disabled)..."
    PGPASSWORD="${POSTGRES_PASSWORD:-${DB_PASSWORD:-rec_io_password}}" psql -h localhost -U rec_io_user -d rec_io_db <<'EOF' >/dev/null 2>&1
CREATE SCHEMA IF NOT EXISTS core;
CREATE TABLE IF NOT EXISTS core.system_state (
    id INTEGER PRIMARY KEY,
    mode TEXT NOT NULL CHECK (mode IN ('normal', 'maintenance')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO core.system_state (id, mode)
VALUES (1, 'maintenance')
ON CONFLICT (id) DO UPDATE
SET mode = EXCLUDED.mode,
    updated_at = now();
EOF
    print_success "System state set to maintenance; new trades will be rejected during restart."
    _MASTER_RESTART_MAINT_ACTIVE=1
    trap '_master_restart_exit_cleanup' EXIT
    echo ""

    # Step 1: Stop supervisor first to prevent auto-restart
    print_status "Step 1: Stopping supervisor..."
    stop_supervisor
    echo ""
    
    # Step 2: Force kill ALL related processes - BULLETPROOF
    print_status "Step 2: Force killing ALL related processes..."
    
    # Kill all screen sessions that might be running our processes
    print_warning "Killing all screen sessions..."
    screen -ls 2>/dev/null | grep -E "(combined_trade_tails|trade)" | cut -d. -f1 | xargs -r kill 2>/dev/null || true
    
    # Kill all tail processes that might be monitoring logs
    print_warning "Killing all tail processes..."
    ps aux 2>/dev/null | grep "tail.*log" | grep -v grep | awk '{print $2}' | xargs -r kill 2>/dev/null || true
    
    # Kill core Python backend processes (exclude analytics tooling)
    print_warning "Killing all Python backend processes..."
    ps aux 2>/dev/null | grep python | grep -E "(main\.py|trade_manager|trade_executor|active_trade_supervisor|auto_entry_supervisor|symbol_price_watchdog|cfbenchmarks_price_watchdog|strike_table_generator|kalshi_account_sync|kalshi_live|market_watchdog_ws|market_watchdog|cascading_failure_detector|system_monitor)" | grep -v grep | grep -v "MASTER_RESTART" | grep -Ev "(analytics_gui\.py|analytics_updater\.py|daily_update\.py|daily_update_lightweight\.py|symbol_data_fetch_pg\.py|momentum_generator_pg\.py|movement_generator_pg\.py|volatility_generator_pg\.py|fingerprint_generator_postgresql\.py|probability_lookup_generator\.py|symbol_profiler\.py)" | awk '{print $2}' | xargs -r kill 2>/dev/null || true
    
    # Kill any remaining project processes, but preserve analytics tooling
    print_warning "Killing processes with project path..."
    ps aux 2>/dev/null | grep -E "(rec_io|rec_io_20)" | grep -v grep | grep -v "MASTER_RESTART" | grep -Ev "(analytics_gui\.py|analytics_updater\.py|daily_update\.py|daily_update_lightweight\.py|symbol_data_fetch_pg\.py|momentum_generator_pg\.py|movement_generator_pg\.py|volatility_generator_pg\.py|fingerprint_generator_postgresql\.py|probability_lookup_generator\.py|symbol_profiler\.py)" | awk '{print $2}' | xargs -r kill 2>/dev/null || true
    
    # Kill any processes using our ports - BULLETPROOF
    print_warning "Killing processes using our ports..."
    for port in "${PORTS[@]}"; do
        lsof -ti :$port 2>/dev/null | xargs -r kill 2>/dev/null || true
    done
    
    # Kill supervisor process if still running - BULLETPROOF
    print_warning "Killing any remaining supervisor processes..."
    ps aux 2>/dev/null | grep supervisord | grep -v grep | awk '{print $2}' | xargs -r kill 2>/dev/null || true
    
    # Wait for processes to fully terminate (Postgres frees sessions from dead backends).
    /bin/sleep 5
    echo ""

    # Step 2.5: Install new dependencies if requirements changed
    ensure_dependencies
    echo ""
    
    # Step 3: Flush all ports
    print_status "Step 3: Flushing all ports..."
    flush_all_ports
    echo ""
    
    # Step 4: Start supervisor (regenerates supervisord.conf inside start_supervisor — all active users get stacks)
    print_status "Step 4: Starting supervisor (regenerates config from DB first)..."
    _REPO_ROOT="$(cd "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
    rm -rf "${_REPO_ROOT}/backend/__pycache__" 2>/dev/null || true
    start_supervisor
    echo ""

    # Step 5: Wait for core services to bind (avoids kalshi_account_sync hitting trade_manager before it is listening)
    print_status "Step 5: Waiting for core ports (3000, 4000, 8001)..."
    _wait_attempts=0
    while [ $_wait_attempts -lt 30 ]; do
        if check_port 3000 && check_port 4000 && check_port 8001; then
            print_success "Core ports active"
            break
        fi
        /bin/sleep 1
        _wait_attempts=$((_wait_attempts + 1))
    done
    if [ $_wait_attempts -ge 30 ]; then
        print_warning "Core ports not all active after 30s; continuing anyway"
    fi
    echo ""
    
    # Step 6: Fresh supervisord already spawned all programs from regenerated config.
    # Re-restarting every program here is redundant and on macOS can crash supervisord (kqueue).
    print_status "Step 6: Skipping per-program restart (fresh supervisord start already spawned all programs)"
    echo ""
    
    # Step 7: Verify everything is running
    print_status "Step 7: Verifying all services..."
    verify_services
    echo ""

    # Step 8: Return system to normal trading mode
    print_status "Step 8: Setting system_state.mode back to 'normal' (trading enabled)..."
    PGPASSWORD="${POSTGRES_PASSWORD:-${DB_PASSWORD:-rec_io_password}}" psql -h localhost -U rec_io_user -d rec_io_db <<'EOF' >/dev/null 2>&1
INSERT INTO core.system_state (id, mode)
VALUES (1, 'normal')
ON CONFLICT (id) DO UPDATE
SET mode = EXCLUDED.mode,
    updated_at = now();
EOF
    print_success "System state set to normal; trading operations re-enabled."
    _MASTER_RESTART_MAINT_ACTIVE=0
    trap - EXIT
    echo ""

    verify_supervisord_alive || true

    print_success "MASTER RESTART completed successfully!"
    echo ""
    print_status "System is now ready for trading operations."
}

# Function to perform quick restart (just supervisor restart)
quick_restart() {
    print_header
    print_status "Initiating QUICK RESTART (supervisor stop → regenerate config from DB → start)..."
    echo ""

    ensure_redis_available
    echo ""
    
    # Stop and start supervisor
    stop_supervisor
    start_supervisor
    restart_all_services
    verify_services
    verify_supervisord_alive || true
    
    print_success "QUICK RESTART completed!"
}

# Function to perform emergency restart (force kill everything)
emergency_restart() {
    print_header
    print_status "Initiating EMERGENCY RESTART (force kill all)..."
    echo ""
    
    # Stop supervisor first to prevent auto-restart
    print_warning "Stopping supervisor..."
    if [ -S "$SUPERVISOR_SOCKET" ]; then
        "$REC_SUPERVISORCTL" -c "$SUPERVISOR_CONFIG" shutdown 2>/dev/null || true
        /bin/sleep 3
    fi
    
    # Kill supervisor process if still running
    pkill -f "supervisord" || true
    /bin/sleep 2
    
    # Kill all screen sessions that might be running our processes
    print_warning "Killing all screen sessions..."
    screen -ls | grep -E "(combined_trade_tails|trade)" | cut -d. -f1 | xargs -r kill 2>/dev/null || true
    
    # Kill all tail processes that might be monitoring logs
    print_warning "Killing all tail processes..."
    pkill -f "tail.*log" || true
    
    # Kill core Python backend processes related to our project - MORE COMPREHENSIVE
    print_warning "Killing all Python backend processes..."
    pkill -f "python.*main.py" || true
    pkill -f "python.*trade_manager.py" || true
    pkill -f "python.*trade_executor.py" || true
    pkill -f "python.*active_trade_supervisor.py" || true
    pkill -f "python.*btc_price_watchdog.py" || true
    pkill -f "python.*kalshi_account_sync.py" || true
    pkill -f "python.*kalshi_market_watchdog.py" || true
    pkill -f "python.*market_watchdog.py" || true
    pkill -f "python.*market_watchdog_ws.py" || true
    pkill -f "python.*kalshi_live" || true
    
    # Kill any remaining project processes, excluding analytics tooling
    print_warning "Killing processes with project path..."
    ps aux | grep -E "(rec_io|rec_io_20)" | grep -v grep | grep -v "MASTER_RESTART" | grep -Ev "(analytics_gui\.py|analytics_updater\.py|daily_update\.py|daily_update_lightweight\.py|symbol_data_fetch_pg\.py|momentum_generator_pg\.py|movement_generator_pg\.py|volatility_generator_pg\.py|fingerprint_generator_postgresql\.py|probability_lookup_generator\.py|symbol_profiler\.py)" | awk '{print $2}' | xargs -r kill -9 2>/dev/null || true
    
    # Kill any processes using our ports
    print_warning "Killing processes using our ports..."
    for port in "${PORTS[@]}"; do
        lsof -ti :$port | xargs kill -9 2>/dev/null || true
    done
    
    # Kill any remaining Python processes that might be ours (exclude analytics tooling)
    print_warning "Killing any remaining suspicious Python processes..."
    ps aux | grep python | grep -E "(trade|kalshi|btc|eth|spx|ndx|xrp|sol)" | grep -v grep | grep -Ev "(analytics_gui\.py|analytics_updater\.py|daily_update\.py|daily_update_lightweight\.py|symbol_data_fetch_pg\.py|momentum_generator_pg\.py|movement_generator_pg\.py|volatility_generator_pg\.py|fingerprint_generator_postgresql\.py|probability_lookup_generator\.py|symbol_profiler\.py)" | awk '{print $2}' | xargs -r kill -9 2>/dev/null || true
    
    # Clean up socket files
    rm -f /tmp/supervisord.sock /tmp/supervisord.pid
    
    # Wait a moment for processes to fully terminate
    /bin/sleep 5
    
    # Flush all ports
    flush_all_ports
    
    # Wait a moment
    /bin/sleep 2

    ensure_redis_available
    echo ""
    
    # Start fresh (programs spawned on start; skip per-program restart storm)
    start_supervisor
    verify_services
    verify_supervisord_alive || true
    
    print_success "EMERGENCY RESTART completed!"
}

# Main script logic
main() {
    case "${1:-master}" in
        "master"|"full")
            master_restart
            ;;
        "quick")
            # Regenerates supervisord.conf then restarts supervisor (same as full path for multi-user stacks)
            quick_restart
            ;;
        "emergency"|"force")
            master_restart
            ;;
        "status")
            show_status
            ;;
        "flush")
            flush_all_ports
            ;;
        "help"|"-h"|"--help")
            echo "Usage: $0 [COMMAND]"
            echo ""
            echo "Commands:"
            echo "  master, full    - Complete MASTER RESTART with process cleanup (default); ensures local Redis if REDIS_HOST is localhost"
            echo "  quick           - Supervisor stop/start + regenerate config from DB (no full process kill)"
            echo "  emergency, force - Same as master restart (legacy alias)"
            echo "  status          - Show current system status"
            echo "  flush           - Flush all ports only"
            echo "  help            - Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0              # MASTER RESTART (default) - KILLS ALL PROCESSES"
            echo "  $0 quick        # Quick restart (supervisor only)"
            echo "  $0 emergency    # Same as default (legacy)"
            echo "  $0 status       # Show status"
            ;;
        *)
            print_error "Unknown command: $1"
            echo "Use '$0 help' for usage information"
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@" 