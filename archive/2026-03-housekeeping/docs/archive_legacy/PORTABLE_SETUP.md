# Portable Supervisor Setup Guide

## Overview
This guide ensures the supervisor system can run on any machine without hardcoded paths or machine-specific configurations.

## Prerequisites
- Python 3.8+
- Virtual environment
- Git repository cloned

## Setup Steps

### 1. Environment Setup
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Database Setup
```bash
# Create required directories
mkdir -p backend/data/active_trades
mkdir -p backend/data/trade_history
mkdir -p logs
```

### 3. Start Supervisor System
```bash
# Use the portable startup script
./scripts/start_supervisor.sh
```

## Environment Variables
The system uses these environment variables for portability:
- `PROJECT_ROOT`: Absolute path to project directory
- `VENV_PATH`: Path to virtual environment
- `PYTHONPATH`: Python path for imports

## Troubleshooting

### Common Issues
1. **Port conflicts**: Check `backend/core/config/MASTER_PORT_MANIFEST.json`
2. **Database locks**: Restart with `./scripts/MASTER_RESTART.sh`
3. **Path issues**: Ensure `PROJECT_ROOT` is set correctly

### Log Locations
- Supervisor logs: `logs/supervisord.log`
- Application logs: `logs/*.out.log` and `logs/*.err.log`

## Verification
```bash
# Check all services are running
supervisorctl -c backend/supervisord.conf status

# Check ports are active
netstat -tulpn | grep -E ':(3000|4000|8001|8007)'
``` 