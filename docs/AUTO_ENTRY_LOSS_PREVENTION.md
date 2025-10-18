# Auto Entry Loss Prevention Feature

## Overview

The auto entry supervisor now respects the monitor's `loss_prevention` state when creating trade tickets. This allows automatic risk management by reducing position sizes during losing streaks.

## How It Works

When `auto_entry_supervisor` creates a trade ticket, it checks the monitor's `loss_prevention` state:

1. **`loss_prevention = "off"`**: Uses the configured `total_position` size (normal behavior)
2. **`loss_prevention = "one_contract"`**: Overrides position size to 1 contract regardless of configuration

## Implementation

### New Function: `get_loss_prevention_state()`

Located in `backend/auto_entry_supervisor.py` (lines 1358-1383):

```python
def get_loss_prevention_state():
    """Get loss_prevention state from monitor-specific configuration"""
    - Queries: SELECT loss_prevention FROM users.monitor_list_0001 WHERE id = MONITOR_ID
    - Returns: The loss_prevention state string ("off", "one_contract", etc.)
    - Default: "off" if not found or error occurs
```

### Modified Function: `trigger_auto_entry_trade()`

Updated at lines 1463-1469:

```python
# Check loss prevention state and override position size if needed
loss_prevention = get_loss_prevention_state()
if loss_prevention == "one_contract":
    log(f"[AUTO ENTRY] 🛡️ Loss prevention active - overriding position size from {position_size} to 1 contract")
    position_size = 1
else:
    log(f"[AUTO ENTRY] Loss prevention is '{loss_prevention}' - using configured position size: {position_size}")
```

## Integration with Win Streak

This feature works seamlessly with the win streak threshold system:

1. **Trade Manager** updates `loss_prevention` based on `win_streak` after each trade closes
2. **Auto Entry Supervisor** reads the current `loss_prevention` state before each trade
3. Position size is automatically adjusted based on trading performance

### Example Flow

```
Initial State:
- total_position: 100
- win_streak: 15
- win_streak_threshold: 22
- loss_prevention: "one_contract"

Auto Entry Triggers:
- Reads total_position: 100
- Reads loss_prevention: "one_contract"
- Overrides position_size to: 1
- Sends trade ticket with position: 1

After 7 More Wins:
- win_streak: 22
- loss_prevention: "off" (automatically updated by trade_manager)

Next Auto Entry:
- Reads total_position: 100
- Reads loss_prevention: "off"
- Uses configured position_size: 100
- Sends trade ticket with position: 100
```

## Logging

The system provides clear logging for debugging:

### When Loss Prevention is Active:
```
[AUTO ENTRY] Loss prevention state loaded from monitor 10002: one_contract
[AUTO ENTRY] 🛡️ Loss prevention active - overriding position size from 100 to 1 contract
```

### When Loss Prevention is Off:
```
[AUTO ENTRY] Loss prevention state loaded from monitor 10002: off
[AUTO ENTRY] Loss prevention is 'off' - using configured position size: 100
```

## Testing

### Check Current State

```sql
SELECT id, name, total_position, win_streak, win_streak_threshold, loss_prevention 
FROM users.monitor_list_0001 
WHERE id = 10002;
```

### Manually Set Loss Prevention

```sql
-- Activate loss prevention
UPDATE users.monitor_list_0001 
SET loss_prevention = 'one_contract' 
WHERE id = 10002;

-- Deactivate loss prevention
UPDATE users.monitor_list_0001 
SET loss_prevention = 'off' 
WHERE id = 10002;
```

### Test Auto Entry Behavior

1. Set a monitor to `loss_prevention = 'one_contract'`
2. Trigger auto entry (wait for conditions to be met)
3. Check logs to verify position size was overridden to 1
4. Check trade in database to confirm `position = 1`

## Benefits

1. **Automatic Risk Management**: Position sizes reduce during losing streaks
2. **Capital Preservation**: Limits losses when strategy is underperforming
3. **No Manual Intervention**: System automatically adjusts based on performance
4. **Gradual Recovery**: Allows strategy to prove itself before returning to full size
5. **Per-Monitor Control**: Each monitor manages its own risk independently

## Configuration

No additional configuration needed. The feature uses:
- `total_position` from monitor_list table (user configurable)
- `loss_prevention` from monitor_list table (auto-managed by trade_manager)
- `win_streak_threshold` from monitor_list table (user configurable, defaults to 22)

## Future Enhancements

Potential additional loss prevention modes:
- `"half_size"`: Use 50% of configured position size
- `"quarter_size"`: Use 25% of configured position size
- `"paused"`: Block all auto entries until manually reset
- `"dynamic"`: Scale position size based on win_streak percentage

## Error Handling

If the loss prevention state cannot be read:
- System defaults to `"off"` (safe fallback)
- Logs error message for debugging
- Continues with normal operation using configured position size

This ensures the system remains functional even if database queries fail.

