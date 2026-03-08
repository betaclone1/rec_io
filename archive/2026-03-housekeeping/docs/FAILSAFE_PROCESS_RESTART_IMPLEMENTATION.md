# Failsafe Process Restart Implementation

## Overview

This document provides the implementation for a failsafe that restarts the entire `active_trade_supervisor` process when monitoring fails, rather than just attempting to restart the monitoring thread.

## Why Process Restart?

1. **Fixes Corrupted State**: If the process state is corrupted (thread limits, resource exhaustion, etc.), restarting just the thread won't help. Restarting the process clears all state.

2. **More Reliable**: Process restart is more reliable than thread restart when the underlying issue is process-level corruption.

3. **Proven Solution**: Your manual restart worked because it restarted the entire process, clearing the corrupted state.

## Implementation

### New Failsafe Function

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
                    try:
                        start_monitoring_loop()
                        
                        # Verify thread restart succeeded
                        time.sleep(1)  # Give thread time to start
                        with monitoring_thread_lock:
                            if monitoring_thread is not None:
                                try:
                                    if monitoring_thread.is_alive():
                                        log("✅ FAILSAFE: Thread restart succeeded and verified")
                                        # Reset restart attempts on success
                                        check_monitoring_failsafe.restart_attempts = {}
                                        return
                                except Exception as e:
                                    log(f"⚠️ FAILSAFE: Thread verification failed ({e}), escalating to process restart")
                    except Exception as e:
                        log(f"❌ FAILSAFE: Thread restart failed ({e}), escalating to process restart")
                        import traceback
                        log(f"❌ FAILSAFE: Thread restart stack trace: {traceback.format_exc()}")
                    
                    # Step 2: Thread restart failed or verification failed - restart entire process
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


def restart_active_trade_supervisor_process():
    """
    Restart the entire active_trade_supervisor process via supervisorctl.
    This will cause this process to exit and supervisor will restart it.
    """
    try:
        import subprocess
        from backend.util.paths import get_supervisorctl_path, get_supervisor_config_path
        
        service_name = f"active_trade_supervisor_{MONITOR_IDENTIFIER}"
        
        log(f"🔄 PROCESS RESTART: Restarting {service_name} via supervisorctl...")
        
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
            # But don't exit immediately - let supervisor handle it
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

### Enhanced Brute Force Failsafe

Also update the brute force failsafe in `start_event_driven_supervisor()`:

```python
# In start_event_driven_supervisor() brute force loop:
if active_count > 0 and not monitoring_thread_alive:
    log(f"🚨 BRUTE FORCE FAILSAFE: Found {active_count} active trades but monitoring thread is dead!")
    
    # Try thread restart first
    try:
        log("🔄 BRUTE FORCE FAILSAFE: Attempting thread restart...")
        start_monitoring_loop()
        time.sleep(1)
        
        # Verify
        with monitoring_thread_lock:
            if monitoring_thread is not None:
                try:
                    if monitoring_thread.is_alive():
                        log("✅ BRUTE FORCE FAILSAFE: Thread restart succeeded")
                        continue  # Success, continue loop
                except:
                    pass
        
        # Thread restart failed or verification failed
        log("❌ BRUTE FORCE FAILSAFE: Thread restart failed, restarting process...")
        restart_active_trade_supervisor_process()
        
    except Exception as e:
        log(f"❌ BRUTE FORCE FAILSAFE: Thread restart exception: {e}")
        log("🚨 BRUTE FORCE FAILSAFE: Restarting process...")
        restart_active_trade_supervisor_process()
```

## Key Features

1. **Two-Tier Approach**: 
   - First tries quick thread restart
   - Escalates to process restart if thread restart fails

2. **Verification**: 
   - Verifies thread restart actually worked
   - Only escalates if verification fails

3. **Cooldown Protection**: 
   - Prevents infinite restart loops
   - 5-minute cooldown between process restarts

4. **Fallback**: 
   - If supervisorctl fails, exits process (supervisor will auto-restart)
   - Multiple fallback mechanisms

5. **Detailed Logging**: 
   - Logs every step of the restart process
   - Includes stack traces for debugging

## Safety Considerations

1. **Cooldown**: Prevents rapid restart loops that could destabilize the system
2. **Verification**: Ensures we don't restart unnecessarily if thread restart worked
3. **Graceful Degradation**: Falls back to process exit if supervisorctl fails
4. **Supervisor Auto-Restart**: Supervisor is configured with `autorestart=true`, so it will restart the process

## Testing

After implementation, test:
1. Normal operation (should not trigger)
2. Thread restart scenario (should succeed)
3. Process restart scenario (should restart process)
4. Cooldown protection (should not restart too frequently)
5. Supervisorctl failure (should fall back to exit)

## Integration

Replace the existing `check_monitoring_failsafe()` function with the new implementation above. Also update the brute force failsafe loop in `start_event_driven_supervisor()`.

