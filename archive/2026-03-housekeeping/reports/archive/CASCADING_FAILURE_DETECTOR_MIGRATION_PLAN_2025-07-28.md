# Cascading Failure Detector Migration Plan

## Current Issues with V1

1. **False Positive Detection**: Reports services as failing when they're actually running
2. **Broken Restart Mechanism**: Can't find `bash` executable due to PATH issues
3. **Aggressive Thresholds**: Triggers restarts too frequently
4. **Flawed Health Check Logic**: Tries HTTP health checks on services without endpoints

## V2 Improvements

1. **Accurate Health Checks**: Proper supervisor status checking with fallback
2. **Fixed Restart Mechanism**: Uses full path `/bin/bash` for MASTER RESTART
3. **Conservative Thresholds**: Higher failure thresholds to prevent false positives
4. **Complete Service Monitoring**: Monitors ALL supervisor services as critical
5. **Improved Logging**: Separate log file for V2 detector

## Migration Steps

### Step 1: Backup Current Detector
```bash
cp backend/cascading_failure_detector.py backend/cascading_failure_detector_v1_backup.py
```

### Step 2: Stop Current Detector
```bash
supervisorctl -c backend/supervisord.conf stop cascading_failure_detector
```

### Step 3: Replace with V2
```bash
cp backend/cascading_failure_detector_v2.py backend/cascading_failure_detector.py
```

### Step 4: Update Supervisor Configuration
Edit `backend/supervisord.conf` to use the new detector.

### Step 5: Test New Detector
```bash
python3 test_cascading_detector_v2.py
```

### Step 6: Start New Detector
```bash
supervisorctl -c backend/supervisord.conf start cascading_failure_detector
```

### Step 7: Monitor for 24 Hours
Watch the new detector logs to ensure it's working correctly.

## Rollback Plan

If issues occur:
1. Stop the new detector
2. Restore the backup: `cp backend/cascading_failure_detector_v1_backup.py backend/cascading_failure_detector.py`
3. Restart the old detector

## Key Differences

| Feature | V1 | V2 |
|---------|----|----|
| Health Check Method | HTTP + Supervisor | Supervisor Primary, HTTP Fallback |
| Restart Command | `bash` | `/bin/bash` |
| Failure Thresholds | 3/5/7 | 5/10/15 |
| Check Interval | 30s | 60s |
| Critical Services | 9 | 11 |
| Rate Limiting | 3/hour | 2/hour |

## Expected Results

- No more false positive cascading failure detections
- Proper MASTER RESTART execution when needed
- Reduced false alarms
- More stable system monitoring 