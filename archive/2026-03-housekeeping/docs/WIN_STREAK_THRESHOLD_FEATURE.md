# Win Streak Threshold Feature

## Overview

The win streak threshold feature allows each monitor to have a configurable threshold value that determines when the `loss_prevention` setting is automatically toggled between `'one_contract'` and `'off'` based on the current win streak.

## Database Changes

### New Columns

Added to all `users.monitor_list_XXXX` tables:

#### `win_streak_threshold`
- **Type**: `INTEGER`
- **Default**: `22`
- **Purpose**: Defines the win streak threshold at which loss prevention is toggled off

#### `last_processed_cycle`
- **Type**: `VARCHAR(100)`
- **Default**: `NULL`
- **Purpose**: Tracks the last settlement cycle processed to prevent double-counting trades from the same cycle

### Logic

**CYCLE-BASED WIN STREAK**: Win streaks are calculated per trading cycle (settlement hour). If ANY trade in a cycle is a loss, that entire cycle does not contribute to the win_streak.

When a trade is closed, the `win_streak` and `loss_prevention` are updated based on the cycle result:

1. **Cycle with ALL Wins**:
   - Increment `win_streak` by the number of wins in the cycle
   - If `win_streak >= win_streak_threshold`: Set `loss_prevention = 'off'`
   - If `win_streak < win_streak_threshold`: Set `loss_prevention = 'one_contract'`

2. **Cycle with ANY Loss**:
   - Set `win_streak` to 0 (all trades in that cycle are ignored for win_streak)
   - Set `loss_prevention = 'one_contract'` (since 0 < threshold)

**Cycle Definition**: A cycle is defined by the contract settlement hour (e.g., all trades for "KXBTCD-25OCT1314" are in the same cycle). This prevents win_streak from counting wins that occurred in the same hour as a loss.

## Implementation

### Files Modified

1. **backend/trade_manager.py** (lines 1176-1210)
   - Updated `update_monitor_win_streak()` function
   - Now reads `win_streak_threshold` from database for each monitor
   - Uses the threshold value to determine loss_prevention setting

2. **backend/core/config/database.py** (line 122)
   - Added `win_streak_threshold INTEGER DEFAULT 22` to table creation

3. **scripts/manage_monitors_list.sh** (line 77)
   - Added `win_streak_threshold INTEGER DEFAULT 22` to table creation

4. **scripts/user_registration_system.sh** (line 221)
   - Added `win_streak_threshold INTEGER DEFAULT 22` to table creation

5. **docs/MONITORS_LIST_INFRASTRUCTURE.md**
   - Updated schema documentation to include new column

### Migration Script

Created `scripts/add_win_streak_threshold_column.py` to:
- Find all existing `monitor_list_XXXX` tables
- Add `win_streak_threshold` column with default value 22
- Update all existing monitor rows to have value 22

## Usage

### View Current Threshold

```sql
SELECT id, name, win_streak, win_streak_threshold, loss_prevention 
FROM users.monitor_list_0001 
WHERE id = 10001;
```

### Update Threshold for a Monitor

```sql
UPDATE users.monitor_list_0001 
SET win_streak_threshold = 30 
WHERE id = 10001;
```

### Check All Monitors with Custom Thresholds

```sql
SELECT id, name, win_streak, win_streak_threshold, loss_prevention 
FROM users.monitor_list_0001 
WHERE win_streak_threshold != 22;
```

## Benefits

1. **Per-Monitor Customization**: Each monitor can have its own threshold value
2. **Database-Driven**: No code changes needed to adjust thresholds
3. **Automatic Updates**: Loss prevention is automatically managed based on win streaks
4. **Audit Trail**: Can track when thresholds were changed

## Future Enhancements

The threshold value could be:
- Made user-configurable through the frontend UI
- Set per-strategy type
- Dynamically adjusted based on market conditions
- Linked to risk management profiles

## Testing

To verify the feature is working:

1. Check that the column exists:
```bash
PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db \
  -c "SELECT column_name, data_type, column_default FROM information_schema.columns WHERE table_schema = 'users' AND table_name = 'monitor_list_0001' AND column_name = 'win_streak_threshold';"
```

2. Verify existing monitors have the default value:
```bash
PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db \
  -c "SELECT id, name, win_streak, win_streak_threshold, loss_prevention FROM users.monitor_list_0001 LIMIT 5;"
```

3. Test threshold logic by closing trades and observing:
   - Win streak incrementing
   - Loss prevention toggling at threshold
   - Win streak resetting on losses

## Notes

- The default threshold value of 22 was chosen based on existing system requirements
- The threshold is currently used for all monitors but can be customized per monitor
- The feature is backward compatible - all existing monitors received the default value of 22

