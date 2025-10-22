# Monitors List Infrastructure

## Overview

The monitors_list infrastructure provides support for multiple trade monitors per user, allowing users to create, manage, and track multiple trading strategies simultaneously. Each user gets their own `monitors_list_XXXX` table where XXXX is their user number.

## Database Schema

### Table Structure

Each user has a `monitors_list_XXXX` table with the following structure:

```sql
CREATE TABLE users.monitors_list_XXXX (
    id INTEGER PRIMARY KEY DEFAULT nextval('users.monitors_list_XXXX_id_seq'),
    name VARCHAR(255) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    strategy VARCHAR(100),
    auto_trade BOOLEAN DEFAULT FALSE,
    auto_trade_status VARCHAR(20) DEFAULT 'inactive',
    trades INTEGER DEFAULT 0,
    win_loss DECIMAL(5,1) DEFAULT 0.0,
    ret_pct DECIMAL(5,1) DEFAULT 0.0,
    pnl DECIMAL(10,2) DEFAULT 0.00,
    bankroll_allotment DECIMAL(5,1) DEFAULT 0.0,
    status VARCHAR(20) DEFAULT 'active',
    win_streak INTEGER DEFAULT 0,
    win_streak_threshold INTEGER DEFAULT 22,
    loss_prevention VARCHAR(50) DEFAULT 'none',
    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### ID Sequence

Each user has their own sequence for 5-digit IDs starting with 10001:

```sql
CREATE SEQUENCE users.monitors_list_XXXX_id_seq
START WITH 10001
INCREMENT BY 1
MINVALUE 10001
MAXVALUE 99999
CYCLE;
```

This means:
- User 0001: IDs 10001, 10002, 10003, ...
- User 0002: IDs 10001, 10002, 10003, ...
- And so on...

## Column Descriptions

| Column | Type | Description | Default |
|--------|------|-------------|---------|
| `id` | INTEGER | Unique 5-digit identifier | Auto-generated (10001+) |
| `name` | VARCHAR(255) | Monitor display name | Required |
| `symbol` | VARCHAR(20) | Trading symbol (BTC, ETH, etc.) | Required |
| `strategy` | VARCHAR(100) | Trading strategy name | Optional |
| `auto_trade` | BOOLEAN | Whether auto-trading is enabled | FALSE |
| `auto_trade_status` | VARCHAR(20) | Auto-trade status | 'inactive' |
| `trades` | INTEGER | Number of trades executed | 0 |
| `win_loss` | DECIMAL(5,1) | Win/loss percentage | 0.0 |
| `ret_pct` | DECIMAL(5,1) | Return percentage | 0.0 |
| `pnl` | DECIMAL(10,2) | Profit/loss in dollars | 0.00 |
| `bankroll_allotment` | DECIMAL(5,1) | Percentage of bankroll allocated | 0.0 |
| `status` | VARCHAR(20) | Monitor status | 'active' |
| `win_streak` | INTEGER | Current consecutive win streak | 0 |
| `win_streak_threshold` | INTEGER | Win streak threshold for loss prevention toggle | 22 |
| `loss_prevention` | VARCHAR(50) | Loss prevention strategy | 'none' |
| `created` | TIMESTAMP | Creation timestamp | CURRENT_TIMESTAMP |

## Status Values

### Monitor Status
- `active` - Monitor is active and running
- `inactive` - Monitor is inactive/stopped
- `archived` - Monitor is archived (read-only)

### Auto Trade Status
- `active` - Auto-trading is active
- `inactive` - Auto-trading is inactive
- `paused` - Auto-trading is temporarily paused
- `off` - Auto-trading is completely disabled

## Management Script

The `scripts/manage_monitors_list.sh` script provides comprehensive management capabilities:

### Usage

```bash
./scripts/manage_monitors_list.sh <command> [options]
```

### Commands

#### Create Table
```bash
./scripts/manage_monitors_list.sh create-table <user_id>
```
Creates the monitors_list table for a new user.

#### List Monitors
```bash
./scripts/manage_monitors_list.sh list <user_id>
```
Lists all monitors for a user.

#### Add Monitor
```bash
./scripts/manage_monitors_list.sh add <user_id> <name> <symbol> <strategy> [auto_trade] [bankroll]
```
Adds a new monitor.

#### Update Status
```bash
./scripts/manage_monitors_list.sh update-status <user_id> <monitor_id> <status>
```
Updates monitor status.

#### Update Auto Trade Status
```bash
./scripts/manage_monitors_list.sh update-auto-trade <user_id> <monitor_id> <status>
```
Updates auto-trade status.

#### Delete Monitor
```bash
./scripts/manage_monitors_list.sh delete <user_id> <monitor_id>
```
Deletes a monitor.

#### Show Monitor Details
```bash
./scripts/manage_monitors_list.sh show <user_id> <monitor_id>
```
Shows detailed information for a specific monitor.

### Examples

```bash
# Create table for user_0001
./scripts/manage_monitors_list.sh create-table user_0001

# List all monitors for user_0001
./scripts/manage_monitors_list.sh list user_0001

# Add a new BTC momentum monitor
./scripts/manage_monitors_list.sh add user_0001 "BTC Momentum" BTC momentum_based true 25.0

# Update monitor status
./scripts/manage_monitors_list.sh update-status user_0001 10001 active

# Update auto-trade status
./scripts/manage_monitors_list.sh update-auto-trade user_0001 10001 paused

# Delete a monitor
./scripts/manage_monitors_list.sh delete user_0001 10001

# Show monitor details
./scripts/manage_monitors_list.sh show user_0001 10001
```

## Integration with User Registration

The monitors_list table creation is integrated into the user registration system. When a new user is registered, their monitors_list table is automatically created.

### User Registration Script Integration

The `scripts/user_registration_system.sh` script includes monitors_list table creation:

```bash
# Create monitors_list table for new user
CREATE TABLE IF NOT EXISTS users.monitors_list_$USER_NUMBER (
    LIKE users.monitors_list_0001 INCLUDING ALL
);
```

## Database Initialization

The monitors_list table is included in the main database initialization (`backend/core/config/database.py`):

```python
# Create sequence for 5-digit IDs starting with 10001
cursor.execute("""
    CREATE SEQUENCE IF NOT EXISTS users.monitors_list_0001_id_seq
    START WITH 10001
    INCREMENT BY 1
    MINVALUE 10001
    MAXVALUE 99999
    CYCLE;
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS users.monitors_list_0001 (
        id INTEGER PRIMARY KEY DEFAULT nextval('users.monitors_list_0001_id_seq'),
        name VARCHAR(255) NOT NULL,
        symbol VARCHAR(20) NOT NULL,
        strategy VARCHAR(100),
        auto_trade BOOLEAN DEFAULT FALSE,
        auto_trade_status VARCHAR(20) DEFAULT 'inactive',
        trades INTEGER DEFAULT 0,
        win_loss DECIMAL(5,1) DEFAULT 0.0,
        ret_pct DECIMAL(5,1) DEFAULT 0.0,
        pnl DECIMAL(10,2) DEFAULT 0.00,
        bankroll_allotment DECIMAL(5,1) DEFAULT 0.0,
        status VARCHAR(20) DEFAULT 'active',
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
""")
```

## Testing

A test script is available at `scripts/test_monitors_list_table.py` that:

1. Tests table creation
2. Tests sequence creation
3. Inserts sample data
4. Verifies data integrity
5. Displays results

Run the test:
```bash
python3 scripts/test_monitors_list_table.py
```

## Future Enhancements

### Planned Features

1. **API Endpoints** - REST API for monitor management
2. **Frontend Integration** - Web interface for monitor management
3. **Performance Tracking** - Real-time performance metrics
4. **Alert System** - Notifications for monitor events
5. **Backtesting** - Historical performance analysis
6. **Risk Management** - Advanced risk controls per monitor

### Database Extensions

Potential additional columns:
- `last_trade_time` - Timestamp of last trade
- `max_drawdown` - Maximum drawdown percentage
- `sharpe_ratio` - Risk-adjusted return metric
- `max_position_size` - Maximum position size
- `stop_loss_pct` - Stop loss percentage
- `take_profit_pct` - Take profit percentage
- `risk_per_trade` - Risk per trade percentage

## Security Considerations

1. **User Isolation** - Each user's data is completely isolated
2. **Access Control** - Database permissions are user-specific
3. **Input Validation** - All inputs are validated and sanitized
4. **Audit Trail** - Creation timestamps provide audit trail

## Performance Considerations

1. **Indexing** - Primary key on `id` provides fast lookups
2. **Partitioning** - Tables are naturally partitioned by user
3. **Sequences** - Efficient ID generation with sequences
4. **Constraints** - Appropriate data type constraints for performance

## Monitoring and Maintenance

### Regular Tasks

1. **Sequence Monitoring** - Check sequence values for overflow
2. **Performance Metrics** - Monitor query performance
3. **Storage Usage** - Track table growth
4. **Backup Verification** - Ensure backups include monitors_list tables

### Maintenance Commands

```bash
# Check sequence values
SELECT sequence_name, last_value FROM information_schema.sequences 
WHERE sequence_schema = 'users' AND sequence_name LIKE 'monitors_list_%_id_seq';

# Check table sizes
SELECT schemaname, tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
FROM pg_tables 
WHERE schemaname = 'users' AND tablename LIKE 'monitors_list_%';

# Check for orphaned sequences
SELECT s.sequence_name 
FROM information_schema.sequences s
WHERE s.sequence_schema = 'users' 
AND s.sequence_name LIKE 'monitors_list_%_id_seq'
AND NOT EXISTS (
    SELECT 1 FROM information_schema.tables t
    WHERE t.table_schema = 'users' 
    AND t.table_name = REPLACE(s.sequence_name, '_id_seq', '')
);
```
