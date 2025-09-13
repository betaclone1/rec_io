# Analytics Package

A comprehensive analytics pipeline for trading symbols that generates momentum profiles, fingerprint tables, and probability lookup tables for algorithmic trading.

## 🚀 Features

- **Complete Data Pipeline**: 8-step process from data fetching to lookup table generation
- **Symbol Agnostic**: Works with any trading symbol (BTC, ETH, SPY, etc.)
- **Dynamic Buffer Sizing**: Automatically calculates optimal buffer ranges based on price profiles
- **Resume Capability**: Can resume interrupted operations without data loss
- **Real-time Progress Tracking**: Live UI with progress bars and detailed logging
- **Comprehensive Logging**: Detailed timing and status information for each step

## 📋 Requirements

- Python 3.8+
- PostgreSQL database
- 8GB+ RAM (for large datasets)
- 50GB+ disk space (for lookup tables)

## 🛠️ Installation

1. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up PostgreSQL database:**
   ```sql
   CREATE DATABASE rec_io_db;
   CREATE USER rec_io_user WITH PASSWORD 'rec_io_password';
   GRANT ALL PRIVILEGES ON DATABASE rec_io_db TO rec_io_user;
   ```

3. **Create required schemas:**
   ```sql
   CREATE SCHEMA analytics;
   CREATE SCHEMA work_progress;
   ```

## 🎯 Quick Start

### Option 1: Web UI (Recommended)

1. **Start the standalone analytics server:**
   ```bash
   python analytics_server.py
   ```

2. **Open the UI:**
   ```
   http://localhost:8080
   ```

3. **Select symbols and click "Start Update"**

### Option 2: Command Line

```bash
# Update BTC and ETH
python analytics_updater.py btc eth

# Update all available symbols
python analytics_updater.py btc eth sol spy qqq tsla aapl msft
```

## 📊 Pipeline Steps

The analytics pipeline consists of 8 sequential steps:

1. **Data Update** - Fetch latest price data from exchanges
2. **Momentum Generation** - Calculate momentum scores and percentiles
3. **Profile Generation** - Create momentum and price distribution profiles
4. **Percentile Assignment** - Assign momentum percentiles to all data points
5. **Data Verification** - Verify data completeness and quality
6. **Fingerprint Archiving** - Archive existing fingerprint tables
7. **Fingerprint Generation** - Generate 199 fingerprint tables per symbol
8. **Lookup Table Generation** - Create probability lookup tables

## 📁 File Structure

```
analytics/
├── __init__.py                          # Package initialization
├── analytics_updater.py                 # Main orchestration script
├── symbol_data_fetch_pg.py             # Data fetching from exchanges
├── momentum_generator_pg.py            # Momentum calculation
├── symbol_profiler.py                  # Profile generation
├── fingerprint_generator_postgresql.py # Fingerprint table generation
├── probability_lookup_generator.py     # Lookup table generation
├── fingerprint_archiver.py             # Archive management
├── copy_analytics_to_prod.py           # Production deployment
├── analytics_ui.html                   # Web interface
├── requirements.txt                    # Python dependencies
└── README.md                          # This file
```

## 🗄️ Database Schema

### Core Tables

- `historical_data.{symbol}_price_history` - Raw price data with momentum scores
- `analytics.{symbol}_momentum_profile` - Momentum distribution profiles
- `analytics.{symbol}_price_profile` - Price movement profiles
- `analytics.{symbol}_fingerprint_XX` - 199 fingerprint tables per symbol
- `analytics.probability_lookup_{symbol}` - Probability lookup tables

### Work Progress Tables

- `work_progress.ttc_progress_incremental` - TTC processing status
- `work_progress.{symbol}_progress` - Symbol-specific progress tracking

## ⚙️ Configuration

### Environment Variables

```bash
export POSTGRES_HOST=localhost
export POSTGRES_DB=rec_io_db
export POSTGRES_USER=rec_io_user
export POSTGRES_PASSWORD=rec_io_password
```

### Database Connection

The package uses PostgreSQL with the following default configuration:
- Host: localhost
- Database: rec_io_db
- User: rec_io_user
- Password: rec_io_password

## 📈 Performance

### Estimated Processing Times

| Step | Duration | Notes |
|------|----------|-------|
| Data Update | 5-15 minutes | Depends on new data volume |
| Momentum Generation | 10-30 minutes | CPU intensive |
| Profile Generation | 5-15 minutes | Statistical analysis |
| Percentile Assignment | 10-20 minutes | Database operations |
| Data Verification | 1-5 minutes | Quick validation |
| Fingerprint Archiving | 1-5 minutes | File operations |
| Fingerprint Generation | 2-4 hours | 199 tables per symbol |
| Lookup Table Generation | 1-3 days | Most time-intensive |

### Memory Requirements

- **Minimum**: 8GB RAM
- **Recommended**: 16GB+ RAM
- **Large datasets**: 32GB+ RAM

### Storage Requirements

- **Base data**: ~5GB per symbol (5 years of 1-minute data)
- **Fingerprint tables**: ~2GB per symbol
- **Lookup tables**: ~10-50GB per symbol (depending on buffer configuration)

## 🔧 Advanced Usage

### Test Mode

Run with reduced data for testing:

```bash
python probability_lookup_generator.py btc --test
```

### Custom Buffer Configuration

The system automatically calculates optimal buffer ranges, but you can override:

```bash
python probability_lookup_generator.py btc --buffer-limit 200 --momentum-range -10 10
```

### Resume Interrupted Operations

The system automatically resumes from where it left off. No manual intervention required.

## 🐛 Troubleshooting

### Common Issues

1. **Database Connection Errors**
   - Verify PostgreSQL is running
   - Check connection credentials
   - Ensure database and schemas exist

2. **Memory Errors**
   - Increase system RAM
   - Reduce batch sizes in configuration
   - Process fewer symbols simultaneously

3. **Disk Space Errors**
   - Monitor available disk space
   - Clean up old log files
   - Archive completed tables

### Log Files

Logs are stored in:
- `../logs/weekly_update_YYYYMMDD_HHMMSS.log`
- Console output with real-time progress

### Debug Mode

Enable debug logging by setting:
```python
logging.getLogger().setLevel(logging.DEBUG)
```

## 🔄 Deployment

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Start web server
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Production Deployment

1. **Set up production database**
2. **Configure environment variables**
3. **Use production web server (gunicorn)**
4. **Set up monitoring and logging**

### Copy to Production

Use the included copy script:

```bash
python copy_analytics_to_prod.py
```

## 📚 API Reference

### Web API Endpoints

- `POST /api/analytics/start` - Start analytics update
- `POST /api/analytics/stop` - Stop running process
- `GET /api/analytics/status` - Get current status
- `GET /api/analytics/stream` - Stream live logs

### Command Line Interface

```bash
# Main updater
python analytics_updater.py [symbols...]

# Individual components
python symbol_data_fetch_pg.py [symbol]
python momentum_generator_pg.py [symbol]
python symbol_profiler.py [symbol] [options]
python fingerprint_generator_postgresql.py [symbols...]
python probability_lookup_generator.py [symbols...] [options]
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project is proprietary software. All rights reserved.

## 🆘 Support

For issues and questions:
1. Check the troubleshooting section
2. Review log files for error details
3. Contact the development team

---

**Last Updated**: August 2025
**Version**: 2.0
**Status**: Production Ready
