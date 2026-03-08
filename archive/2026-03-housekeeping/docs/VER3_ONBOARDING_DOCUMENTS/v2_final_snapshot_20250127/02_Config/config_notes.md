# REC.IO v2 Configuration Notes

## Environment Setup

### Required Environment Variables
```bash
# Database Configuration
export DATABASE_TYPE="postgresql"
export POSTGRES_HOST="localhost"
export POSTGRES_PORT="5432"
export POSTGRES_DB="rec_io_db"
export POSTGRES_USER="rec_io_user"
export POSTGRES_PASSWORD="rec_io_password"

# System Configuration
export TRADING_SYSTEM_HOST="localhost"  # or auto-detected IP
export AUTH_ENABLED="false"  # true for production

# Python Environment
export PYTHONPATH="."
export PYTHONGC=1
export PYTHONDNSCACHE=1
```

### Optional Environment Variables
```bash
# Development Overrides
export TRADING_SYSTEM_HOST="192.168.86.42"  # Specific IP
export AUTH_ENABLED="true"  # Enable authentication
export DEBUG_MODE="true"  # Enable debug logging
```

## Configuration Files

### Core Configuration Files

#### 1. Master Port Manifest
**Location**: `backend/core/config/MASTER_PORT_MANIFEST.json`
**Purpose**: Single source of truth for all port assignments
**Format**: JSON with service definitions and port mappings

#### 2. System Configuration
**Location**: `backend/core/config/config.json`
**Purpose**: System-wide configuration settings
**Format**: JSON with nested configuration objects

#### 3. Feature Flags
**Location**: `backend/core/config/feature_flags.py`
**Purpose**: Feature enable/disable controls
**Format**: Python module with boolean flags

#### 4. Settings Module
**Location**: `backend/core/config/settings.py`
**Purpose**: Configuration management class
**Format**: Python class with validation and defaults

### Supervisor Configuration

#### Main Supervisor Config
**Location**: `backend/supervisord.conf`
**Purpose**: Process management for all services
**Features**:
- Auto-restart on failure
- Centralized logging
- Environment variable injection
- Process grouping

#### Root Supervisor Config
**Location**: `supervisord.conf`
**Purpose**: Alternative supervisor configuration
**Features**:
- PostgreSQL environment variables
- Different logging configuration
- Process-specific settings

### Authentication Configuration

#### User Configuration
**Location**: `backend/data/users/user_0001/user_info.json`
**Purpose**: User credentials and preferences
**Format**: JSON with user data

#### Token Storage
**Location**: `backend/data/users/user_0001/auth_tokens.json`
**Purpose**: Active session tokens
**Format**: JSON with token data

#### Device Tokens
**Location**: `backend/data/users/user_0001/device_tokens.json`
**Purpose**: Remembered device tokens
**Format**: JSON with device data

## Database Configuration

### PostgreSQL Setup
```sql
-- Create database
CREATE DATABASE rec_io_db;

-- Create user
CREATE USER rec_io_user WITH PASSWORD 'rec_io_password';

-- Grant permissions
GRANT ALL PRIVILEGES ON DATABASE rec_io_db TO rec_io_user;

-- Create schemas
CREATE SCHEMA IF NOT EXISTS users;
CREATE SCHEMA IF NOT EXISTS live_data;
CREATE SCHEMA IF NOT EXISTS historical_data;
```

### Database Connection Parameters
```python
# Standard connection parameters
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "rec_io_db",
    "user": "rec_io_user",
    "password": "rec_io_password"
}
```

## Service Configuration

### Core Services Configuration

#### Main Application
- **Port**: 3000
- **Framework**: FastAPI
- **Features**: WebSocket support, CORS, static file serving
- **Dependencies**: PostgreSQL, Redis (planned)

#### Trade Manager
- **Port**: 4000
- **Framework**: FastAPI
- **Features**: Trade lifecycle management, database operations
- **Dependencies**: PostgreSQL

#### Trade Executor
- **Port**: 8001
- **Framework**: FastAPI
- **Features**: Order execution, market interaction
- **Dependencies**: Kalshi API, PostgreSQL

#### Active Trade Supervisor
- **Port**: 8007
- **Framework**: Flask
- **Features**: Real-time trade monitoring
- **Dependencies**: PostgreSQL, WebSocket

### Watchdog Services Configuration

#### BTC Price Watchdog
- **Port**: 8002
- **Purpose**: Bitcoin price monitoring
- **Data Source**: Coinbase API
- **Output**: PostgreSQL, SQLite

#### Kalshi Account Sync
- **Port**: 8004
- **Purpose**: Account synchronization
- **Data Source**: Kalshi API
- **Output**: PostgreSQL

#### Kalshi API Watchdog
- **Port**: 8005
- **Purpose**: API health monitoring
- **Data Source**: Kalshi API
- **Output**: JSON files, PostgreSQL

## Credential Management

### Kalshi Credentials
**Location**: `backend/data/users/user_0001/credentials/kalshi-credentials/`
**Structure**:
```
kalshi-credentials/
├── prod/
│   ├── .env
│   └── private_key.pem
└── demo/
    ├── .env
    └── private_key.pem
```

### Credential File Format
```bash
# .env file format
KALSHI_API_KEY_ID=your_api_key_id
KALSHI_PRIVATE_KEY_PATH=private_key.pem
```

### Security Considerations
- Credentials stored in user-specific directories
- No credentials in version control
- Environment-specific credential sets
- Secure file permissions

## Logging Configuration

### Log File Locations
```
logs/
├── main_app.out.log
├── main_app.err.log
├── trade_manager.out.log
├── trade_manager.err.log
├── trade_executor.out.log
├── trade_executor.err.log
├── active_trade_supervisor.out.log
├── active_trade_supervisor.err.log
└── ... (other service logs)
```

### Log Rotation
**Configuration**: `logrotate.conf`
**Features**:
- Daily rotation
- Compression after 7 days
- Keep 30 days of logs
- Size-based rotation

### Log Levels
- **DEBUG**: Detailed debugging information
- **INFO**: General information messages
- **WARNING**: Warning messages
- **ERROR**: Error messages
- **CRITICAL**: Critical error messages

## Frontend Configuration

### Static File Serving
**Location**: `frontend/`
**Structure**:
```
frontend/
├── tabs/
│   ├── trade_monitor.html
│   ├── trade_history.html
│   ├── account_manager.html
│   └── settings.html
├── js/
│   ├── strike-table.js
│   ├── active-trade-supervisor_panel.js
│   ├── trade-execution-controller.js
│   └── ...
├── styles/
│   ├── global.css
│   └── strike-table.css
└── mobile/
    └── ... (mobile-specific files)
```

### WebSocket Configuration
- **Endpoint**: `/ws`
- **Protocol**: WebSocket
- **Features**: Real-time updates, connection management
- **Authentication**: Token-based authentication

## Mobile Configuration

### iOS App Configuration
**Location**: `rec_webview_app/`
**Features**:
- Native iOS webview
- Local file serving
- Offline capability
- Push notifications (planned)

### Mobile-Specific Settings
- Responsive design
- Touch-optimized interface
- Reduced data usage
- Battery optimization

## Development Configuration

### Local Development Setup
```bash
# Activate virtual environment
source venv/bin/activate

# Set development environment
export AUTH_ENABLED=false
export DEBUG_MODE=true

# Start supervisor
supervisord -c backend/supervisord.conf
```

### Testing Configuration
```bash
# Test environment variables
export TEST_MODE=true
export DATABASE_TYPE="sqlite"  # Use SQLite for testing
export AUTH_ENABLED=false
```

### Debug Configuration
```bash
# Enable debug logging
export DEBUG_MODE=true
export LOG_LEVEL=DEBUG

# Enable verbose output
export VERBOSE=true
```

## Production Configuration

### Production Environment Variables
```bash
# Production settings
export AUTH_ENABLED=true
export DEBUG_MODE=false
export LOG_LEVEL=INFO

# Database settings
export POSTGRES_HOST="production-db-host"
export POSTGRES_PASSWORD="secure-production-password"

# Security settings
export TRADING_SYSTEM_HOST="production-host"
```

### Production Security
- Authentication enabled
- HTTPS required
- Secure database connections
- Credential rotation
- Log monitoring

## Configuration Validation

### Configuration Check Script
```python
def validate_configuration():
    """Validate all configuration settings."""
    checks = [
        check_database_connection(),
        check_port_availability(),
        check_file_permissions(),
        check_environment_variables(),
        check_service_health()
    ]
    return all(checks)
```

### Required Checks
1. **Database Connection**: Verify PostgreSQL connectivity
2. **Port Availability**: Ensure all ports are available
3. **File Permissions**: Check credential file permissions
4. **Environment Variables**: Validate required variables
5. **Service Health**: Verify all services can start

## Configuration Migration

### v2 to v3 Migration
1. **Port System**: Preserve current port assignments
2. **Path System**: Extend universal path system
3. **Database**: Maintain PostgreSQL schema
4. **Authentication**: Enhance current auth system
5. **Configuration**: Extend config management

### Backward Compatibility
- All current configuration files preserved
- Environment variables remain compatible
- Database schema unchanged
- API endpoints maintained

## Troubleshooting

### Common Configuration Issues

#### Port Conflicts
```bash
# Check port usage
lsof -i :3000
lsof -i :4000
# ... check all ports

# Kill conflicting processes
kill -9 <PID>
```

#### Database Connection Issues
```bash
# Test database connection
psql -h localhost -U rec_io_user -d rec_io_db

# Check PostgreSQL status
sudo systemctl status postgresql
```

#### File Permission Issues
```bash
# Fix credential file permissions
chmod 600 backend/data/users/user_0001/credentials/kalshi-credentials/*/.env
chmod 600 backend/data/users/user_0001/credentials/kalshi-credentials/*/*.pem
```

#### Environment Variable Issues
```bash
# Check environment variables
env | grep -E "(TRADING|POSTGRES|AUTH)"

# Set missing variables
export TRADING_SYSTEM_HOST="localhost"
export AUTH_ENABLED="false"
```

### Configuration Debugging
```python
# Debug configuration loading
from backend.core.config.settings import config
print(config.get("system.name"))
print(config.get("agents.main.port"))
```

## Configuration Best Practices

### Security
- Never commit credentials to version control
- Use environment variables for sensitive data
- Implement proper file permissions
- Rotate credentials regularly

### Portability
- Use relative paths where possible
- Externalize environment-specific values
- Implement configuration validation
- Provide default values for all settings

### Maintainability
- Centralize configuration management
- Use consistent naming conventions
- Document all configuration options
- Implement configuration validation

### Scalability
- Design for multiple environments
- Support configuration inheritance
- Implement feature flags
- Plan for configuration automation
