# PostgreSQL Table Monitoring Tools

Real-time monitoring tools for PostgreSQL tables during database migration and development.

## 🚀 Quick Start

### Web-Based Viewer (Recommended)
```bash
# Monitor BTC price data
python backend/util/launch_table_monitor.py --schema live_data --table live_price_log_1s_btc --mode web

# Monitor trades table
python backend/util/launch_table_monitor.py --schema public --table trades --mode web --port 8081
```

### Terminal-Based Watcher
```bash
# Monitor with terminal output
python backend/util/launch_table_monitor.py --schema live_data --table live_price_log_1s_btc --mode terminal
```

## 📁 Files

- **`launch_table_monitor.py`** - Easy launcher script (use this!)
- **`live_table_viewer.py`** - Web-based real-time viewer
- **`live_table_watcher.py`** - Terminal-based watcher
- **`env.example`** - Environment variables template

## 🎯 Use Cases

### 1. Migration Monitoring
Watch data flow as you migrate from SQLite to PostgreSQL:
```bash
# Monitor the table you're migrating
python backend/util/launch_table_monitor.py --schema public --table trades --mode web --port 8080
```

### 2. Development Testing
Monitor test data during development:
```bash
# Watch test data with faster updates
python backend/util/launch_table_monitor.py --schema live_data --table live_price_log_1s_btc --mode web --poll-interval 0.5
```

### 3. Multiple Tables
Run multiple viewers on different ports:
```bash
# Terminal 1: Monitor trades
python backend/util/launch_table_monitor.py --schema public --table trades --mode web --port 8080

# Terminal 2: Monitor active trades
python backend/util/launch_table_monitor.py --schema public --table active_trades --mode web --port 8081

# Terminal 3: Monitor BTC price data
python backend/util/launch_table_monitor.py --schema live_data --table live_price_log_1s_btc --mode web --port 8082
```

## 🌐 Web Viewer Features

- **Dark theme** similar to Xcode's JSON viewer
- **Real-time updates** with visual indicators
- **Change detection** (inserts, updates, deletes)
- **Color-coded values** (numbers, strings, nulls)
- **Auto-refresh** every 1 second (configurable)
- **Responsive design** for different screen sizes

## 📊 Terminal Watcher Features

- **Color-coded output** with emojis
- **Change detection** with detailed reporting
- **Hash-based monitoring** for efficient updates
- **Graceful shutdown** with Ctrl+C
- **Error handling** and reconnection logic

## ⚙️ Configuration

### Environment Variables
Copy `env.example` to `.env` and customize:
```bash
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=rec_io_db
POSTGRES_USER=rec_io_user
POSTGRES_PASSWORD=
```

### Command Line Options
```bash
--schema          Database schema (e.g., live_data, public)
--table           Table name to monitor
--mode            web or terminal (default: web)
--port            Web server port (default: 8080)
--poll-interval   Update frequency in seconds (default: 1.0)
```

## 🔧 Advanced Usage

### Direct Script Execution
```bash
# Web viewer
python backend/util/live_table_viewer.py --schema live_data --table live_price_log_1s_btc --port 8080

# Terminal watcher
python backend/util/live_table_watcher.py --schema public --table trades --poll-interval 2.0
```

### Custom Environment
```bash
# Set custom database connection
POSTGRES_HOST=192.168.1.100 POSTGRES_PORT=5433 python backend/util/launch_table_monitor.py --schema live_data --table live_price_log_1s_btc --mode web
```

## 🎯 Perfect for Migration

These tools are specifically designed for monitoring your PostgreSQL migration:

1. **Watch data flow** as you migrate applications
2. **Verify data integrity** during migration
3. **Monitor performance** and data volume
4. **Debug issues** with real-time visibility
5. **Compare SQLite vs PostgreSQL** data

## 🚨 Troubleshooting

### Connection Issues
```bash
# Check PostgreSQL is running
ps aux | grep postgres

# Test connection
psql -U rec_io_user -d rec_io_db -c "SELECT 1;"
```

### Port Conflicts
```bash
# Use different port
python backend/util/launch_table_monitor.py --schema live_data --table live_price_log_1s_btc --mode web --port 8081
```

### Performance Issues
```bash
# Slower updates for large tables
python backend/util/launch_table_monitor.py --schema public --table trades --mode web --poll-interval 5.0
```

## 📈 Migration Workflow

1. **Start monitoring** the table you're migrating
2. **Run migration script** to copy data
3. **Watch real-time** as data flows
4. **Verify completeness** and accuracy
5. **Switch application** to use PostgreSQL
6. **Monitor for issues** during transition

## 🎉 Success!

Your PostgreSQL table monitoring tools are ready for the migration journey! 