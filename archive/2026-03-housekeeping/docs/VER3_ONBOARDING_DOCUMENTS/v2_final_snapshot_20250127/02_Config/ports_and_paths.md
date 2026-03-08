# REC.IO v2 Port and Path Configuration

## Universal Port Management System

### Centralized Port Configuration
All port assignments are managed through a single source of truth: `backend/core/config/MASTER_PORT_MANIFEST.json`

### Current Port Assignments

#### Core Services
| Service | Port | Description | Status |
|---------|------|-------------|--------|
| main_app | 3000 | Main web application | RUNNING |
| trade_manager | 4000 | Trade management service | RUNNING |
| trade_executor | 8001 | Trade execution service | RUNNING |
| active_trade_supervisor | 8007 | Active trade monitoring | RUNNING |
| auto_entry_supervisor | 8009 | Auto entry monitoring and indicators | RUNNING |

#### Watchdog Services
| Service | Port | Description | Status |
|---------|------|-------------|--------|
| btc_price_watchdog | 8002 | Bitcoin price monitoring | RUNNING |
| db_poller | 8003 | Database polling service | RUNNING |
| kalshi_account_sync | 8004 | Kalshi account synchronization | RUNNING |
| kalshi_api_watchdog | 8005 | Kalshi API monitoring | RUNNING |
| unified_production_coordinator | 8010 | Unified data production coordinator | RUNNING |

### Port Range Configuration
- **Safe Range**: 8000-8100 (avoids macOS system services)
- **Avoided Ports**: 5000, 7000, 9000, 10000 (macOS conflicts)
- **Core Range**: 3000-4000 (main application services)

## Universal Path Management System

### Project Root Path
```python
def get_project_root():
    """Get the absolute path to the project root directory."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

### Data Directory Structure
```
backend/data/
├── users/
│   └── user_0001/
│       ├── accounts/
│       ├── active_trades/
│       ├── trade_history/
│       ├── credentials/
│       │   └── kalshi-credentials/
│       │       ├── prod/
│       │       └── demo/
│       ├── auth_tokens.json
│       └── device_tokens.json
├── live_data/
│   ├── markets/
│   │   └── kalshi/
│   ├── price_history/
│   │   ├── btc/
│   │   └── eth/
│   └── live_probabilities/
├── historical_data/
├── archives/
└── locks/
```

### Key Path Functions

#### User Data Paths
```python
def get_accounts_data_dir():
    """Get the accounts data directory path."""
    return os.path.join(get_data_dir(), "users", "user_0001", "accounts")

def get_trade_history_dir():
    """Get the trade history directory path."""
    return os.path.join(get_data_dir(), "users", "user_0001", "trade_history")

def get_active_trades_dir():
    """Get the active trades directory path."""
    return os.path.join(get_data_dir(), "users", "user_0001", "active_trades")

def get_kalshi_credentials_dir():
    """Get the Kalshi credentials directory path."""
    return os.path.join(get_data_dir(), "users", "user_0001", "credentials", "kalshi-credentials")
```

#### Market Data Paths
```python
def get_kalshi_data_dir():
    """Get the Kalshi data directory path."""
    return os.path.join(get_data_dir(), "live_data", "markets", "kalshi")

def get_coinbase_data_dir():
    """Get the Coinbase data directory path."""
    return os.path.join(get_data_dir(), "coinbase")

def get_price_history_dir():
    """Get the price history directory path."""
    return os.path.join(get_data_dir(), "live_data", "price_history")

def get_btc_price_history_dir():
    """Get the BTC price history directory path."""
    return os.path.join(get_price_history_dir(), "btc")
```

#### System Paths
```python
def get_logs_dir():
    """Get the logs directory path."""
    return os.path.join(get_project_root(), "logs")

def get_frontend_dir():
    """Get the frontend directory path."""
    return os.path.join(get_project_root(), "frontend")

def get_venv_python_path():
    """Get the virtual environment Python executable path."""
    return os.path.join(get_project_root(), "venv", "bin", "python")

def get_supervisor_config_path():
    """Get the supervisor configuration file path."""
    return os.path.join(get_project_root(), "backend", "supervisord.conf")
```

### Host Configuration

#### Dynamic Host Detection
```python
def get_host():
    """Get the host configuration for the current environment."""
    # Check for environment variable first
    env_host = os.getenv("TRADING_SYSTEM_HOST")
    if env_host:
        return env_host
    
    # Try to detect the actual IP address for network access
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception as e:
        return "localhost"
```

#### Service URL Generation
```python
def get_service_url(service_name: str, endpoint: str = "") -> str:
    """Get the full URL for a service endpoint using universal host system."""
    port = get_port(service_name)
    host = get_host()
    return f"http://{host}:{port}{endpoint}"
```

## Environment Configuration

### Environment Variables
| Variable | Purpose | Default | Required |
|----------|---------|---------|----------|
| TRADING_SYSTEM_HOST | System host address | Auto-detected | No |
| AUTH_ENABLED | Enable authentication | false | No |
| DATABASE_TYPE | Database type | postgresql | Yes |
| POSTGRES_HOST | PostgreSQL host | localhost | Yes |
| POSTGRES_PORT | PostgreSQL port | 5432 | Yes |
| POSTGRES_DB | PostgreSQL database | rec_io_db | Yes |
| POSTGRES_USER | PostgreSQL user | rec_io_user | Yes |
| POSTGRES_PASSWORD | PostgreSQL password | rec_io_password | Yes |

### Configuration Files

#### Master Port Manifest
Location: `backend/core/config/MASTER_PORT_MANIFEST.json`
```json
{
  "system_name": "REC.IO Trading System",
  "created": "2025-07-19",
  "description": "MASTER PORT MANIFEST - Single source of truth for ALL port assignments",
  "core_services": {
    "main_app": {
      "port": 3000,
      "description": "Main web application",
      "status": "RUNNING"
    }
  },
  "watchdog_services": {
    "btc_price_watchdog": {
      "port": 8002,
      "description": "Bitcoin price monitoring",
      "status": "RUNNING"
    }
  }
}
```

#### System Configuration
Location: `backend/core/config/config.json`
```json
{
  "system": {
    "name": "Trading System",
    "version": "1.0.0",
    "environment": "development"
  },
  "agents": {
    "main": {
      "enabled": true,
      "host": "192.168.86.42",
      "port": 3000
    }
  }
}
```

## Port Management Functions

### Core Functions
```python
def get_port(service_name: str) -> int:
    """Get the port for a specific service from master manifest."""
    ensure_port_config_exists()
    
    try:
        with open(PORT_CONFIG_FILE, 'r') as f:
            manifest = json.load(f)
        
        # Check core_services first
        if service_name in manifest.get("core_services", {}):
            return manifest["core_services"][service_name]["port"]
        
        # Check watchdog_services
        if service_name in manifest.get("watchdog_services", {}):
            return manifest["watchdog_services"][service_name]["port"]
        
        raise ValueError(f"Service '{service_name}' not found in master manifest")
    except Exception as e:
        return DEFAULT_PORTS.get(service_name, 3000)

def list_all_ports() -> Dict[str, int]:
    """Get all port assignments from master manifest."""
    ensure_port_config_exists()
    
    try:
        with open(PORT_CONFIG_FILE, 'r') as f:
            manifest = json.load(f)
        
        ports = {}
        
        # Extract ports from core_services
        for service_name, service_config in manifest.get("core_services", {}).items():
            ports[service_name] = service_config["port"]
        
        # Extract ports from watchdog_services
        for service_name, service_config in manifest.get("watchdog_services", {}).items():
            ports[service_name] = service_config["port"]
        
        return ports
    except Exception as e:
        return DEFAULT_PORTS

def get_port_info() -> Dict:
    """Get comprehensive port information for API endpoints using universal host system."""
    ports = list_all_ports()
    host = "localhost"
    return {
        "ports": ports,
        "service_urls": {name: f"http://{host}:{port}" for name, port in ports.items()},
        "config_file": PORT_CONFIG_FILE,
        "host": host
    }
```

## Path Management Functions

### Directory Creation
```python
def ensure_data_dirs():
    """Ensure all data directories exist."""
    dirs = [
        get_data_dir(),
        get_kalshi_data_dir(),
        get_price_history_dir(),
        get_btc_price_history_dir(),
        get_logs_dir(),
        # User-specific directories
        get_accounts_data_dir(),
        get_trade_history_dir(),
        get_active_trades_dir(),
        # User credentials directories
        os.path.join(get_data_dir(), "users", "user_0001", "credentials", "kalshi-credentials", "prod"),
        os.path.join(get_data_dir(), "users", "user_0001", "credentials", "kalshi-credentials", "demo"),
    ]
    for dir_path in dirs:
        os.makedirs(dir_path, exist_ok=True)
```

## Configuration Notes

### Environment-Specific Values
- **Host Addresses**: Some hardcoded IP addresses in config files (192.168.86.42)
- **Database Credentials**: PostgreSQL credentials are environment-specific
- **File Paths**: All paths are relative to project root for portability

### Portability Considerations
- **Universal Paths**: All paths use relative references from project root
- **Host Detection**: Automatic host detection for network access
- **Environment Variables**: Configuration externalized for deployment
- **No Hardcoded Paths**: All paths generated dynamically

### Security Considerations
- **Credential Isolation**: User-specific credential storage
- **File Permissions**: Secure handling of credential files
- **Environment Variables**: Sensitive data via environment
- **No Secrets in Code**: All secrets externalized

## Migration to v3

### Planned Improvements
- **Redis Integration**: Centralized caching and pub/sub
- **Containerization**: Docker-based deployment
- **Service Discovery**: Dynamic service registration
- **Load Balancing**: Multiple service instances
- **API Gateway**: Centralized API management

### Backward Compatibility
- **Port System**: Current port system will be preserved
- **Path System**: Universal path system will be extended
- **Configuration**: Current config system will be enhanced
- **Data Migration**: All data structures will be preserved
