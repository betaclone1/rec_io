# Active Trade Supervisor Failsafe Implementation Guide

**Purpose**: Implement a bulletproof failsafe that restarts the entire process when monitoring fails, ensuring trades are never left unprotected.

**Date**: December 2, 2025  
**Priority**: CRITICAL - System currently has no reliable protection

---

## Overview

The current failsafe detects monitoring failures but cannot reliably fix them. This implementation adds:
1. Thread restart attempt (quick recovery)
2. Verification that restart succeeded
3. Process restart escalation (fixes corrupted state)
4. Cooldown protection (prevents restart loops)
5. Comprehensive error handling and logging

---

## Required Imports

Ensure these imports are present at the top of the file (they should already be there):

```python
import subprocess
import sys
import time
import threading
```

---

## Step 1: Add Process Restart Function

**Location**: Add this new function AFTER `check_monitoring_failsafe()` and BEFORE `start_monitoring_loop()`

**Function to Add**:

```python
def restart_active_trade_supervisor_process():
    """
    Restart the entire active_trade_supervisor process via supervisorctl.
    This will cause this process to exit and supervisor will restart it.
    """
    try:
        from backend.util.paths import get_supervisorctl_path, get_supervisor_config_path
        
        service_name = f"active_trade_supervisor_{MONITOR_IDENTIFIER}"
        
        log(f"🔄 PROCESS RESTART: Restarting {service_name} via supervisorctl...")
        log(f"🚨 CRITICAL: Process restart initiated due to monitoring failure")
        
        supervisorctl_path = get_supervisorctl_path()
        supervisor_config_path = get_supervisor_config_path()
        
        # Restart the service
        result = subprocess.run(
            [supervisorctl_path, "-c", supervisor_config_path, "restart", service_name],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            log(f"✅ PROCESS RESTART: Successfully initiated restart of {service_name}")
            log(f"✅ PROCESS RESTART: Supervisor output: {result.stdout}")
            
            # Give supervisor time to restart the process
            time.sleep(2)
            
            # This process will be terminated by supervisor, so we can exit
            log("🔄 PROCESS RESTART: Process restart initiated, supervisor will handle termination")
        else:
            log(f"❌ PROCESS RESTART: Failed to restart {service_name}")
            log(f"❌ PROCESS RESTART: Return code: {result.returncode}")
            log(f"❌ PROCESS RESTART: stderr: {result.stderr}")
            log(f"❌ PROCESS RESTART: stdout: {result.stdout}")
            
            # If supervisorctl fails, try alternative: exit and let supervisor auto-restart
            log("🔄 PROCESS RESTART: Falling back to process exit (supervisor will auto-restart)")
            sys.exit(1)  # Exit with error code, supervisor will restart
            
    except subprocess.TimeoutExpired:
        log(f"❌ PROCESS RESTART: Timeout waiting for supervisorctl")
        # Fall back to exit
        log("🔄 PROCESS RESTART: Falling back to process exit (supervisor will auto-restart)")
        sys.exit(1)
    except Exception as e:
        log(f"❌ PROCESS RESTART: Exception during restart: {e}")
        import traceback
        log(f"❌ PROCESS RESTART: Stack trace: {traceback.format_exc()}")
        # Fall back to exit
        log("🔄 PROCESS RESTART: Falling back to process exit (supervisor will auto-restart)")
        sys.exit(1)
```

---

## Step 2: Replace `check_monitoring_failsafe()` Function

**Location**: Replace the existing `check_monitoring_failsafe()` function (currently at line 1486)

**Find This**:
```python
def check_monitoring_failsafe():
    """
    Simple failsafe: Check if monitoring should be running and restart if needed.
    This runs periodically to catch any monitoring loop failures.
    """
    global monitoring_thread
    
    try:
        # Check if there are active trades
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(f"SELECT COUNT(*) FROM users.{active_trades_table} WHERE status = 'active'")
        active_count = cursor.fetchone()[0]
        conn.close()
        
        # If there are active trades but no monitoring thread, restart it
        if active_count > 0:
            with monitoring_thread_lock:
                if monitoring_thread is None or not monitoring_thread.is_alive():
                    log(f"🔄 FAILSAFE: Found {active_count} active trades but monitoring not running, restarting...")
                    start_monitoring_loop()
        
    except Exception as e:
        log(f"❌ Error in monitoring failsafe check: {e}")
```

**Replace With This**:
```python
def check_monitoring_failsafe():
    """
    Bulletproof failsafe: Check if monitoring should be running and restart if needed.
    First attempts thread restart, then escalates to process restart if that fails.
    """
    global monitoring_thread
    
    # Track restart attempts to prevent infinite loops
    if not hasattr(check_monitoring_failsafe, 'restart_attempts'):
        check_monitoring_failsafe.restart_attempts = {}
        check_monitoring_failsafe.last_process_restart = 0
        check_monitoring_failsafe.process_restart_cooldown = 300  # 5 minutes between process restarts
    
    try:
        # Check if there are active trades
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(f"SELECT COUNT(*) FROM users.{active_trades_table} WHERE status = 'active'")
        active_count = cursor.fetchone()[0]
        conn.close()
        
        # If there are active trades but no monitoring thread, restart it
        if active_count > 0:
            with monitoring_thread_lock:
                thread_alive = False
                try:
                    thread_alive = monitoring_thread is not None and monitoring_thread.is_alive()
                except Exception as e:
                    log(f"⚠️ FAILSAFE: Thread object corrupted ({e}), forcing cleanup")
                    monitoring_thread = None
                    thread_alive = False
                
                if not thread_alive:
                    log(f"🔄 FAILSAFE: Found {active_count} active trades but monitoring not running")
                    
                    # Step 1: Try thread restart first (quick recovery)
                    log("🔄 FAILSAFE: Attempting thread restart...")
                    thread_restart_succeeded = False
                    try:
                        start_monitoring_loop()
                        
                        # Verify thread restart succeeded
                        time.sleep(1)  # Give thread time to start
                        with monitoring_thread_lock:
                            if monitoring_thread is not None:
                                try:
                                    if monitoring_thread.is_alive():
                                        log("✅ FAILSAFE: Thread restart succeeded and verified")
                                        thread_restart_succeeded = True
                                        # Reset restart attempts on success
                                        check_monitoring_failsafe.restart_attempts = {}
                                except Exception as e:
                                    log(f"⚠️ FAILSAFE: Thread verification failed ({e}), escalating to process restart")
                    except Exception as e:
                        log(f"❌ FAILSAFE: Thread restart failed ({e}), escalating to process restart")
                        import traceback
                        log(f"❌ FAILSAFE: Thread restart stack trace: {traceback.format_exc()}")
                    
                    # Step 2: Thread restart failed or verification failed - restart entire process
                    if not thread_restart_succeeded:
                        current_time = time.time()
                        time_since_last_restart = current_time - check_monitoring_failsafe.last_process_restart
                        
                        if time_since_last_restart < check_monitoring_failsafe.process_restart_cooldown:
                            log(f"⏳ FAILSAFE: Process restart on cooldown ({int(check_monitoring_failsafe.process_restart_cooldown - time_since_last_restart)}s remaining)")
                            return
                        
                        log(f"🚨 CRITICAL FAILSAFE: Thread restart failed, restarting entire process!")
                        log(f"🚨 CRITICAL: {active_count} active trades are UNPROTECTED - process restart required!")
                        
                        # Restart this process via supervisorctl
                        restart_active_trade_supervisor_process()
                        
                        # Update cooldown
                        check_monitoring_failsafe.last_process_restart = current_time
        
    except Exception as e:
        log(f"❌ CRITICAL: Failsafe check itself failed: {e}")
        import traceback
        log(f"❌ CRITICAL: Failsafe stack trace: {traceback.format_exc()}")
        # Even the failsafe failed - try process restart as last resort
        try:
            restart_active_trade_supervisor_process()
        except Exception as restart_error:
            log(f"❌ CATASTROPHIC: Process restart also failed: {restart_error}")
```

---

## Step 3: Enhance `start_monitoring_loop()` with Exception Handling

**Location**: Replace the existing `start_monitoring_loop()` function (currently at line 1512)

**Find This**:
```python
def start_monitoring_loop():
    """
    Start monitoring loop when there are active trades.
    This should be called when trades are added to active_trades.
    """
    global monitoring_thread
    
    # Check if monitoring thread is already running
    with monitoring_thread_lock:
        if monitoring_thread is not None and monitoring_thread.is_alive():
            log("📊 MONITORING: Monitoring thread already running, skipping")
            return
    
    def monitoring_worker():
        # ... existing worker code ...
    
    # Start monitoring in a separate thread
    with monitoring_thread_lock:
        monitoring_thread = threading.Thread(target=monitoring_worker, daemon=True)
        monitoring_thread.start()
        log("📊 MONITORING: Monitoring thread started")
```

**Replace With This**:
```python
def start_monitoring_loop():
    """
    Start monitoring loop when there are active trades.
    This should be called when trades are added to active_trades.
    """
    global monitoring_thread
    
    try:
        # Clean up any corrupted state first
        with monitoring_thread_lock:
            if monitoring_thread is not None:
                try:
                    if not monitoring_thread.is_alive():
                        log("🧹 CLEANUP: Clearing dead thread reference")
                        monitoring_thread = None
                except Exception as e:
                    log(f"🧹 CLEANUP: Thread object corrupted ({e}), forcing cleanup")
                    monitoring_thread = None
        
        # Check if monitoring thread is already running
        with monitoring_thread_lock:
            if monitoring_thread is not None:
                try:
                    if monitoring_thread.is_alive():
                        log("📊 MONITORING: Monitoring thread already running, skipping")
                        return
                except Exception as e:
                    log(f"⚠️ Thread object corrupted ({e}), clearing and continuing")
                    monitoring_thread = None
        
        def monitoring_worker():
            # ... existing worker code (DO NOT CHANGE) ...
        
        # Start monitoring in a separate thread WITH EXCEPTION HANDLING
        with monitoring_thread_lock:
            try:
                monitoring_thread = threading.Thread(target=monitoring_worker, daemon=True)
                monitoring_thread.start()
                
                # Verify thread actually started
                if not monitoring_thread.is_alive():
                    raise RuntimeError("Thread failed to start after start() call")
                
                log("📊 MONITORING: Monitoring thread started and verified alive")
                
            except Exception as e:
                log(f"❌ CRITICAL: Failed to start monitoring thread: {e}")
                log(f"❌ CRITICAL: Exception type: {type(e).__name__}")
                import traceback
                log(f"❌ CRITICAL: Stack trace: {traceback.format_exc()}")
                # Clear thread reference on failure
                monitoring_thread = None
                raise  # Re-raise to let caller know it failed
                
    except Exception as e:
        log(f"❌ CRITICAL: Error in start_monitoring_loop: {e}")
        import traceback
        log(f"❌ CRITICAL: Stack trace: {traceback.format_exc()}")
        # Ensure cleanup even on failure
        with monitoring_thread_lock:
            monitoring_thread = None
        raise
```

**IMPORTANT**: Do NOT change the `monitoring_worker()` function definition or its contents. Only add exception handling around the thread creation and starting code.

---

## Step 4: Update Brute Force Failsafe Loop

**Location**: In `start_event_driven_supervisor()` function, find the brute force failsafe loop (around line 1975)

**Find This**:
```python
            # If there are active trades but no monitoring thread, restart it
            if active_count > 0 and not monitoring_thread_alive:
                log(f"🚨 BRUTE FORCE FAILSAFE: Found {active_count} active trades but monitoring thread is dead!")
                log("🔄 BRUTE FORCE FAILSAFE: Restarting monitoring loop...")
                start_monitoring_loop()
```

**Replace With This**:
```python
            # If there are active trades but no monitoring thread, restart it
            if active_count > 0 and not monitoring_thread_alive:
                log(f"🚨 BRUTE FORCE FAILSAFE: Found {active_count} active trades but monitoring thread is dead!")
                
                # Try thread restart first
                thread_restart_succeeded = False
                try:
                    log("🔄 BRUTE FORCE FAILSAFE: Attempting thread restart...")
                    start_monitoring_loop()
                    time.sleep(1)  # Give thread time to start
                    
                    # Verify
                    with monitoring_thread_lock:
                        if monitoring_thread is not None:
                            try:
                                if monitoring_thread.is_alive():
                                    log("✅ BRUTE FORCE FAILSAFE: Thread restart succeeded and verified")
                                    thread_restart_succeeded = True
                            except Exception as e:
                                log(f"⚠️ BRUTE FORCE FAILSAFE: Thread verification failed ({e})")
                    
                except Exception as e:
                    log(f"❌ BRUTE FORCE FAILSAFE: Thread restart exception: {e}")
                    import traceback
                    log(f"❌ BRUTE FORCE FAILSAFE: Stack trace: {traceback.format_exc()}")
                
                # If thread restart failed, restart process
                if not thread_restart_succeeded:
                    log("🚨 BRUTE FORCE FAILSAFE: Thread restart failed, restarting process...")
                    try:
                        restart_active_trade_supervisor_process()
                    except Exception as e:
                        log(f"❌ BRUTE FORCE FAILSAFE: Process restart failed: {e}")
```

---

## Step 5: Add Cleanup Function (Optional but Recommended)

**Location**: Add this function AFTER `check_monitoring_failsafe()` and BEFORE `start_monitoring_loop()`

**Function to Add**:
```python
def cleanup_monitoring_thread_state():
    """
    Clean up monitoring thread state to prevent corrupted state.
    Should be called at the end of each monitoring cycle or when monitoring stops.
    """
    global monitoring_thread
    
    try:
        with monitoring_thread_lock:
            # If thread exists, check if it's actually alive
            if monitoring_thread is not None:
                try:
                    # Try to check if thread is alive - if this raises exception, thread is corrupted
                    is_alive = monitoring_thread.is_alive()
                    if not is_alive:
                        # Thread is dead, clear the reference
                        log("🧹 CLEANUP: Clearing dead thread reference")
                        monitoring_thread = None
                except Exception as e:
                    # Thread object is in invalid state - force clear it
                    log(f"🧹 CLEANUP: Thread object in invalid state ({e}), forcing cleanup")
                    monitoring_thread = None
    except Exception as e:
        # Even the cleanup failed - force clear
        log(f"🧹 CLEANUP: Cleanup failed ({e}), forcing thread reference to None")
        with monitoring_thread_lock:
            monitoring_thread = None
```

**Then update the monitoring_worker exit point** (around line 1822):

**Find This**:
```python
        # Clear the global monitoring thread reference when done
        with monitoring_thread_lock:
            monitoring_thread = None
        log("📊 MONITORING: Monitoring thread finished")
```

**Replace With This**:
```python
        # Clear the global monitoring thread reference when done
        cleanup_monitoring_thread_state()
        log("📊 MONITORING: Monitoring thread finished")
```

---

## Implementation Checklist

- [ ] Add `restart_active_trade_supervisor_process()` function
- [ ] Replace `check_monitoring_failsafe()` function
- [ ] Enhance `start_monitoring_loop()` with exception handling (keep `monitoring_worker()` unchanged)
- [ ] Update brute force failsafe loop in `start_event_driven_supervisor()`
- [ ] (Optional) Add `cleanup_monitoring_thread_state()` function
- [ ] (Optional) Update monitoring_worker exit point to use cleanup function

---

## Testing After Implementation

1. **Normal Operation**: Verify monitoring starts normally for new trades
2. **Thread Restart**: Simulate thread failure, verify thread restart works
3. **Process Restart**: Simulate corrupted state, verify process restart triggers
4. **Cooldown**: Verify process restart doesn't trigger too frequently
5. **Supervisor Integration**: Verify supervisor restarts the process correctly

---

## Safety Notes

1. **Do NOT modify** the `monitoring_worker()` function - only add exception handling around thread creation
2. **Do NOT change** any other functionality - only the failsafe mechanisms
3. **Preserve** all existing logging and behavior for normal operation
4. **Test** thoroughly before deploying to production
5. **Monitor** logs after deployment to ensure process restarts work correctly

---

## Expected Behavior After Implementation

1. **Normal Case**: Monitoring starts normally, no changes to behavior
2. **Thread Failure**: Failsafe detects failure, attempts thread restart, verifies success
3. **Corrupted State**: Thread restart fails, process restart triggers, supervisor restarts process, monitoring resumes
4. **Cooldown**: If failures persist, process restart only happens every 5 minutes max

---

## Rollback Plan

If issues occur, the changes are isolated to:
- `check_monitoring_failsafe()` function
- `start_monitoring_loop()` function (exception handling only)
- Brute force failsafe loop
- New `restart_active_trade_supervisor_process()` function

All can be reverted individually if needed.

---

## Code Locations Reference

- **File**: `/opt/rec_io_server/backend/active_trade_supervisor.py`
- **check_monitoring_failsafe()**: ~line 1486
- **start_monitoring_loop()**: ~line 1512
- **Brute force failsafe loop**: ~line 1975 in `start_event_driven_supervisor()`
- **Monitoring thread cleanup**: ~line 1822 in `monitoring_worker()`

---

## Summary

This implementation adds a bulletproof failsafe that:
1. ✅ Detects monitoring failures
2. ✅ Attempts quick thread restart first
3. ✅ Verifies restart succeeded
4. ✅ Escalates to process restart if thread restart fails
5. ✅ Includes cooldown protection
6. ✅ Has comprehensive error handling and logging
7. ✅ Does not interfere with existing functionality

The process restart clears any corrupted state and ensures monitoring can resume, preventing unprotected trades.



