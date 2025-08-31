# 🚀 PostgreSQL Table Monitoring - Quick Reference

## 📋 One-Liner Commands

### Web Viewer (Recommended)
```bash
# Monitor BTC price data
python backend/util/launch_table_monitor.py --schema live_data --table live_price_log_1s_btc --mode web

# Monitor trades table
python backend/util/launch_table_monitor.py --schema public --table trades --mode web --port 8081

# Fast updates for development
python backend/util/launch_table_monitor.py --schema live_data --table live_price_log_1s_btc --mode web --poll-interval 0.5
```

### Terminal Watcher
```bash
# Monitor with terminal output
python backend/util/launch_table_monitor.py --schema live_data --table live_price_log_1s_btc --mode terminal
```

## 🎯 Common Use Cases

### Migration Monitoring
```bash
# Watch trades table during migration
python backend/util/launch_table_monitor.py --schema public --table trades --mode web --port 8080
```

### Multiple Tables
```bash
# Terminal 1: Trades
python backend/util/launch_table_monitor.py --schema public --table trades --mode web --port 8080

# Terminal 2: Active trades  
python backend/util/launch_table_monitor.py --schema public --table active_trades --mode web --port 8081

# Terminal 3: BTC price data
python backend/util/launch_table_monitor.py --schema live_data --table live_price_log_1s_btc --mode web --port 8082
```

## 🌐 Web Interface
- **URL**: `http://localhost:8080` (or your chosen port)
- **Auto-refresh**: Every 1 second (configurable)
- **Features**: Dark theme, change detection, color-coded values

## 📁 Files Location
```
backend/util/
├── launch_table_monitor.py    # 🚀 Use this launcher!
├── live_table_viewer.py       # Web-based viewer
├── live_table_watcher.py      # Terminal watcher
├── env.example               # Environment template
├── README_TABLE_MONITORING.md # Full documentation
└── QUICK_REFERENCE.md        # This file
```

## ⚡ Pro Tips

1. **Use the launcher script** - it handles environment setup automatically
2. **Web mode is recommended** - better for development and monitoring
3. **Multiple ports** - run different tables on different ports
4. **Custom intervals** - use `--poll-interval` for performance tuning
5. **Environment variables** - copy `env.example` to `.env` for custom config

## 🎉 Ready for Migration!

Your monitoring tools are organized and ready to watch your PostgreSQL migration in real-time! 