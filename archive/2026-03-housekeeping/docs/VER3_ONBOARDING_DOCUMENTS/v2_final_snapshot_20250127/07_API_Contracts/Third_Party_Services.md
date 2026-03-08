# Third-Party Services API Contract Reference

## Overview
This document provides API contracts for additional third-party services used in the REC.IO trading system beyond Kalshi and Coinbase.

**Last Verified**: 2025-01-27  
**Scope**: Additional services, monitoring, and integrations

---

## Email/SMS Notification Services

### SendGrid Email Service

#### Configuration
```python
# SendGrid API configuration
SENDGRID_API_KEY = "SG.your_api_key_here"
SENDGRID_FROM_EMAIL = "alerts@rec.io"
SENDGRID_FROM_NAME = "REC.IO Trading System"
```

#### Send Email
```http
POST https://api.sendgrid.com/v3/mail/send
```

**Headers**:
```python
headers = {
    'Authorization': f'Bearer {SENDGRID_API_KEY}',
    'Content-Type': 'application/json'
}
```

**Request Body**:
```json
{
  "personalizations": [
    {
      "to": [
        {
          "email": "user@example.com",
          "name": "User Name"
        }
      ],
      "subject": "Trading Alert"
    }
  ],
  "from": {
    "email": "alerts@rec.io",
    "name": "REC.IO Trading System"
  },
  "content": [
    {
      "type": "text/plain",
      "value": "Trade executed: BTC-2024-12-31 at $0.65"
    },
    {
      "type": "text/html",
      "value": "<h1>Trade Alert</h1><p>Trade executed: BTC-2024-12-31 at $0.65</p>"
    }
  ]
}
```

**Error Codes**:
- `200`: Success
- `400`: Bad Request
- `401`: Unauthorized
- `403`: Forbidden
- `429`: Rate limit exceeded

**Rate Limits**:
- **Free tier**: 100 emails/day
- **Paid tier**: 100,000 emails/month

---

## Database Services

### PostgreSQL (Primary Database)

#### Connection Configuration
```python
# PostgreSQL connection parameters
POSTGRES_HOST = "localhost"
POSTGRES_PORT = "5432"
POSTGRES_DB = "rec_io_db"
POSTGRES_USER = "rec_io_user"
POSTGRES_PASSWORD = "rec_io_password"
```

#### Connection String
```python
# Connection string format
DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
```

#### Health Check
```sql
-- Database health check query
SELECT 1 as health_check;
```

#### Performance Monitoring
```sql
-- Active connections
SELECT count(*) as active_connections 
FROM pg_stat_activity 
WHERE state = 'active';

-- Database size
SELECT pg_size_pretty(pg_database_size('rec_io_db')) as db_size;
```

---

## File System Services

### Local File Storage

#### Log File Management
```python
# Log file paths
LOG_DIR = "logs/"
ERROR_LOG_PATTERN = "*.err.log"
OUTPUT_LOG_PATTERN = "*.out.log"

# Log rotation configuration
LOG_ROTATION = {
    "max_size": "10MB",
    "backup_count": 5,
    "rotation_interval": "daily"
}
```

#### Data File Storage
```python
# Data directory structure
DATA_DIR = "backend/data/"
USER_DATA_DIR = "backend/data/users/"
CREDENTIALS_DIR = "backend/data/users/{user_id}/credentials/"
PRICE_HISTORY_DIR = "backend/data/price_history/"
```

#### File Permissions
```bash
# Secure file permissions
chmod 600 backend/data/users/*/credentials/*
chmod 644 logs/*.log
chmod 755 backend/data/
```

---

## Process Management Services

### Supervisor (Process Manager)

#### Configuration File
```ini
# supervisord.conf
[supervisord]
logfile = logs/supervisord.log
pidfile = /tmp/supervisord.pid

[program:main_app]
command = venv/bin/python backend/main.py
directory = .
autostart = true
autorestart = true
stderr_logfile = logs/main_app.err.log
stdout_logfile = logs/main_app.out.log
environment = PATH="venv/bin",PYTHONPATH="."
```

#### Supervisor Control Commands
```bash
# Start supervisor
supervisord -c supervisord.conf

# Control services
supervisorctl start main_app
supervisorctl stop main_app
supervisorctl restart main_app
supervisorctl status

# Reload configuration
supervisorctl reread
supervisorctl update
```

#### Health Monitoring
```python
# Supervisor health check
def check_supervisor_health():
    try:
        result = subprocess.run(
            ['supervisorctl', 'status'],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Supervisor health check failed: {e}")
        return False
```

---

## Network Services

### WebSocket Server

#### WebSocket Configuration
```python
# WebSocket server settings
WS_HOST = "0.0.0.0"
WS_PORT = 8000
WS_MAX_CONNECTIONS = 100
WS_HEARTBEAT_INTERVAL = 30
```

#### WebSocket Message Format
```json
{
  "type": "price_update",
  "data": {
    "symbol": "BTC-USD",
    "price": 46250.12,
    "timestamp": "2024-01-27T10:30:00Z"
  }
}
```

#### Connection Management
```python
# WebSocket connection tracking
class WebSocketManager:
    def __init__(self):
        self.connections = set()
        self.heartbeat_interval = 30
    
    def add_connection(self, websocket):
        self.connections.add(websocket)
    
    def remove_connection(self, websocket):
        self.connections.discard(websocket)
    
    def broadcast_message(self, message):
        for websocket in self.connections.copy():
            try:
                websocket.send(json.dumps(message))
            except Exception as e:
                logger.error(f"Failed to send message: {e}")
                self.remove_connection(websocket)
```

---

## Monitoring Services

### System Health Monitoring

#### Health Check Endpoints
```python
# Health check API endpoints
@app.route('/health')
def health_check():
    return {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'services': {
            'database': check_database_health(),
            'kalshi_api': check_kalshi_health(),
            'coinbase_api': check_coinbase_health(),
            'supervisor': check_supervisor_health()
        }
    }

@app.route('/health/detailed')
def detailed_health_check():
    return {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'system_info': {
            'cpu_usage': get_cpu_usage(),
            'memory_usage': get_memory_usage(),
            'disk_usage': get_disk_usage(),
            'network_status': get_network_status()
        },
        'service_status': {
            'main_app': get_service_status('main_app'),
            'trade_manager': get_service_status('trade_manager'),
            'trade_executor': get_service_status('trade_executor'),
            'active_trade_supervisor': get_service_status('active_trade_supervisor')
        }
    }
```

#### Performance Metrics
```python
# Performance monitoring
def get_system_metrics():
    return {
        'cpu_percent': psutil.cpu_percent(interval=1),
        'memory_percent': psutil.virtual_memory().percent,
        'disk_percent': psutil.disk_usage('/').percent,
        'network_io': psutil.net_io_counters()._asdict()
    }

def get_service_metrics():
    return {
        'response_time': measure_response_time(),
        'error_rate': calculate_error_rate(),
        'throughput': calculate_throughput(),
        'active_connections': count_active_connections()
    }
```

---

## Security Services

### Authentication Service

#### User Authentication
```python
# Authentication endpoints
@app.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if validate_credentials(username, password):
        token = generate_auth_token(username)
        return {'token': token, 'status': 'success'}
    else:
        return {'error': 'Invalid credentials'}, 401

@app.route('/auth/verify', methods=['POST'])
def verify_token():
    token = request.headers.get('Authorization')
    if validate_token(token):
        return {'status': 'valid'}
    else:
        return {'error': 'Invalid token'}, 401
```

#### Token Management
```python
# JWT token configuration
JWT_SECRET_KEY = "your-secret-key"
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

def generate_auth_token(username):
    payload = {
        'username': username,
        'exp': datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
        'iat': datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

def validate_token(token):
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return True
    except jwt.ExpiredSignatureError:
        return False
    except jwt.InvalidTokenError:
        return False
```

---

## Backup Services

### Database Backup

#### PostgreSQL Backup
```bash
# Database backup script
#!/bin/bash
BACKUP_DIR="backup/"
DATE=$(date +%Y%m%d_%H%M%S)
DB_NAME="rec_io_db"
DB_USER="rec_io_user"

# Create backup directory
mkdir -p $BACKUP_DIR

# Perform backup
pg_dump -h localhost -U $DB_USER -d $DB_NAME > $BACKUP_DIR/backup_$DATE.sql

# Compress backup
gzip $BACKUP_DIR/backup_$DATE.sql

# Clean old backups (keep last 7 days)
find $BACKUP_DIR -name "backup_*.sql.gz" -mtime +7 -delete
```

#### File System Backup
```bash
# File system backup script
#!/bin/bash
BACKUP_DIR="backup/"
SOURCE_DIR="backend/data/"
DATE=$(date +%Y%m%d_%H%M%S)

# Create backup directory
mkdir -p $BACKUP_DIR

# Perform backup
tar -czf $BACKUP_DIR/data_backup_$DATE.tar.gz $SOURCE_DIR

# Clean old backups (keep last 7 days)
find $BACKUP_DIR -name "data_backup_*.tar.gz" -mtime +7 -delete
```

---

## Error Handling and Logging

### Centralized Logging
```python
# Logging configuration
import logging
import logging.handlers

def setup_logging():
    # Create logger
    logger = logging.getLogger('rec_io_system')
    logger.setLevel(logging.INFO)
    
    # Create handlers
    file_handler = logging.handlers.RotatingFileHandler(
        'logs/system.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    
    console_handler = logging.StreamHandler()
    
    # Create formatters
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Add formatters to handlers
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger
```

### Error Tracking
```python
# Error tracking and alerting
def track_error(error, context=None):
    error_data = {
        'error': str(error),
        'timestamp': datetime.now().isoformat(),
        'context': context or {},
        'stack_trace': traceback.format_exc()
    }
    
    # Log error
    logger.error(f"System error: {error_data}")
    
    # Send alert if critical
    if is_critical_error(error):
        send_error_alert(error_data)
    
    # Store error for analysis
    store_error_for_analysis(error_data)
```

---

## Integration Testing

### Service Integration Tests
```python
# Integration test suite
def test_all_services():
    """Test all third-party service integrations"""
    
    # Test database connectivity
    assert test_database_connection()
    
    # Test API connectivity
    assert test_kalshi_api_connection()
    assert test_coinbase_api_connection()
    
    # Test email service
    assert test_sendgrid_connection()
    
    # Test supervisor
    assert test_supervisor_health()
    
    # Test WebSocket
    assert test_websocket_connection()
    
    print("All service integrations working correctly")

def test_database_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Database connection test failed: {e}")
        return False

def test_kalshi_api_connection():
    try:
        response = requests.get(
            "https://api.elections.kalshi.com/trade-api/v2/markets",
            headers={'Authorization': f'Bearer {KALSHI_API_KEY}'},
            timeout=10
        )
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Kalshi API connection test failed: {e}")
        return False
```

---

## Rate Limiting and Throttling

### API Rate Limiting
```python
# Rate limiting implementation
from functools import wraps
import time
from collections import defaultdict

class RateLimiter:
    def __init__(self, max_requests, time_window):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = defaultdict(list)
    
    def is_allowed(self, key):
        now = time.time()
        # Clean old requests
        self.requests[key] = [req_time for req_time in self.requests[key] 
                            if now - req_time < self.time_window]
        
        if len(self.requests[key]) < self.max_requests:
            self.requests[key].append(now)
            return True
        return False

# Usage
kalshi_limiter = RateLimiter(max_requests=100, time_window=60)  # 100 requests per minute
coinbase_limiter = RateLimiter(max_requests=1000, time_window=60)  # 1000 requests per minute

def rate_limited_api_call(limiter, key):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if limiter.is_allowed(key):
                return func(*args, **kwargs)
            else:
                raise Exception("Rate limit exceeded")
        return wrapper
    return decorator
```

---

## Monitoring and Alerting

### Service Monitoring Dashboard
```python
# Service monitoring endpoints
@app.route('/monitor/services')
def service_monitor():
    return {
        'database': {
            'status': check_database_status(),
            'response_time': measure_database_response_time(),
            'connections': get_database_connections()
        },
        'apis': {
            'kalshi': check_kalshi_status(),
            'coinbase': check_coinbase_status(),
            'sendgrid': check_sendgrid_status()
        },
        'processes': {
            'supervisor': check_supervisor_status(),
            'main_app': check_process_status('main_app'),
            'trade_manager': check_process_status('trade_manager')
        },
        'system': {
            'cpu': get_cpu_usage(),
            'memory': get_memory_usage(),
            'disk': get_disk_usage()
        }
    }

@app.route('/monitor/alerts')
def get_alerts():
    return {
        'critical_alerts': get_critical_alerts(),
        'warning_alerts': get_warning_alerts(),
        'info_alerts': get_info_alerts()
    }
```

### Alert Configuration
```python
# Alert thresholds and configuration
ALERT_THRESHOLDS = {
    'cpu_usage': 80,  # Alert if CPU > 80%
    'memory_usage': 85,  # Alert if memory > 85%
    'disk_usage': 90,  # Alert if disk > 90%
    'api_response_time': 5,  # Alert if API response > 5 seconds
    'error_rate': 5,  # Alert if error rate > 5%
    'database_connections': 80,  # Alert if DB connections > 80%
}

ALERT_CHANNELS = {
    'email': True,
    'sms': False,
    'webhook': False,
    'log': True
}
```

This document provides comprehensive coverage of all third-party services used in the REC.IO trading system, including their API contracts, configuration, monitoring, and integration patterns.
