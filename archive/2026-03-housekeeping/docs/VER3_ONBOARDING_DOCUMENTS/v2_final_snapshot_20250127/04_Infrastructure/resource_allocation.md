# REC.IO v2 Resource Allocation

## System Resource Overview

The REC.IO v2 system is designed to run efficiently on a single server with optimized resource allocation for real-time trading operations, data processing, and web interface delivery.

## Current Resource Allocation

### CPU Allocation

#### Core Services (High Priority)
| Service | CPU Usage | Priority | Description |
|---------|-----------|----------|-------------|
| main_app | 15% | High | Web interface and API gateway |
| trade_manager | 20% | High | Trade lifecycle management |
| trade_executor | 15% | High | Order execution |
| active_trade_supervisor | 10% | High | Real-time trade monitoring |
| auto_entry_supervisor | 10% | High | Automated entry signals |

#### Watchdog Services (Medium Priority)
| Service | CPU Usage | Priority | Description |
|---------|-----------|----------|-------------|
| btc_price_watchdog | 5% | Medium | Bitcoin price monitoring |
| kalshi_account_sync | 5% | Medium | Account synchronization |
| kalshi_api_watchdog | 5% | Medium | API health monitoring |
| unified_production_coordinator | 5% | Medium | Data coordination |

#### System Services (Low Priority)
| Service | CPU Usage | Priority | Description |
|---------|-----------|----------|-------------|
| system_monitor | 2% | Low | System health monitoring |
| cascading_failure_detector | 2% | Low | Failure detection |
| db_poller | 3% | Low | Database polling |

**Total CPU Usage**: ~100% (with headroom for spikes)

### Memory Allocation

#### Application Memory
| Component | Memory Usage | Description |
|-----------|--------------|-------------|
| PostgreSQL Database | 512MB | Database server |
| Python Processes | 256MB | All Python services |
| Web Interface | 64MB | Frontend assets |
| Supervisor | 16MB | Process management |
| System Cache | 128MB | File system cache |

#### Memory Breakdown by Service
| Service | Memory | Description |
|---------|--------|-------------|
| main_app | 64MB | FastAPI application |
| trade_manager | 128MB | Database operations |
| trade_executor | 32MB | Order execution |
| active_trade_supervisor | 32MB | Trade monitoring |
| auto_entry_supervisor | 32MB | Signal generation |
| Watchdog Services | 64MB | All watchdog services |
| System Services | 32MB | Monitoring services |

**Total Memory Usage**: ~1GB (with 2GB available)

### Disk Space Allocation

#### Data Storage
| Directory | Size | Purpose |
|-----------|------|---------|
| PostgreSQL Data | 2GB | Database storage |
| Historical Data | 5GB | Price history archives |
| Live Data | 1GB | Real-time data |
| Log Files | 500MB | System logs |
| User Data | 100MB | User-specific data |
| Credentials | 10MB | Secure credentials |

#### File Organization
```
backend/data/
├── users/user_0001/          # 50MB - User data
├── live_data/                # 1GB - Real-time data
├── historical_data/          # 5GB - Historical archives
└── archives/                 # 2GB - System archives

logs/                         # 500MB - System logs
backup/                       # 1GB - System backups
```

**Total Disk Usage**: ~10GB (with 50GB available)

### Network Allocation

#### Port Usage
| Port Range | Purpose | Services |
|------------|---------|----------|
| 3000-4000 | Core Services | main_app, trade_manager |
| 8000-8100 | Watchdog Services | All watchdog services |
| 5432 | Database | PostgreSQL |
| 80/443 | Web Interface | HTTP/HTTPS |

#### Bandwidth Requirements
| Service | Bandwidth | Description |
|---------|-----------|-------------|
| Kalshi API | 1MB/s | Market data streaming |
| Coinbase API | 100KB/s | Price data |
| WebSocket | 50KB/s | Real-time updates |
| Database | 10KB/s | Local database traffic |

**Total Bandwidth**: ~2MB/s peak

## Performance Optimization

### CPU Optimization

#### Process Prioritization
```bash
# High priority processes
nice -n -10 python backend/main.py
nice -n -10 python backend/trade_manager.py
nice -n -10 python backend/trade_executor.py

# Medium priority processes
nice -n 0 python backend/api/coinbase-api/coinbase-btc/btc_price_watchdog.py
nice -n 0 python backend/api/kalshi-api/kalshi_account_sync_ws.py

# Low priority processes
nice -n 10 python backend/system_monitor.py
nice -n 10 python backend/cascading_failure_detector.py
```

#### CPU Affinity
```bash
# Bind critical processes to specific CPU cores
taskset -c 0 python backend/main.py
taskset -c 1 python backend/trade_manager.py
taskset -c 2 python backend/trade_executor.py
```

### Memory Optimization

#### Python Memory Management
```python
# Garbage collection optimization
import gc
gc.set_threshold(700, 10, 10)

# Memory monitoring
import psutil
def monitor_memory():
    process = psutil.Process()
    memory_info = process.memory_info()
    return memory_info.rss / 1024 / 1024  # MB
```

#### Database Memory Tuning
```sql
-- PostgreSQL memory configuration
shared_buffers = 256MB
effective_cache_size = 1GB
work_mem = 4MB
maintenance_work_mem = 64MB
```

### Disk I/O Optimization

#### File System Optimization
```bash
# SSD optimization
echo 'noatime' >> /etc/fstab
echo 'discard' >> /etc/fstab

# Log rotation optimization
logrotate -f /etc/logrotate.conf
```

#### Database I/O Optimization
```sql
-- PostgreSQL I/O optimization
random_page_cost = 1.1
effective_io_concurrency = 200
max_worker_processes = 8
max_parallel_workers_per_gather = 4
```

## Resource Monitoring

### System Monitoring
```python
import psutil
import time

def monitor_system_resources():
    """Monitor system resource usage"""
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    return {
        'cpu_percent': cpu_percent,
        'memory_percent': memory.percent,
        'memory_available': memory.available / 1024 / 1024,  # MB
        'disk_percent': disk.percent,
        'disk_free': disk.free / 1024 / 1024 / 1024  # GB
    }
```

### Service Monitoring
```python
def monitor_service_resources():
    """Monitor individual service resource usage"""
    services = [
        'main_app', 'trade_manager', 'trade_executor',
        'active_trade_supervisor', 'auto_entry_supervisor'
    ]
    
    service_stats = {}
    for service in services:
        try:
            process = psutil.Process()
            service_stats[service] = {
                'cpu_percent': process.cpu_percent(),
                'memory_mb': process.memory_info().rss / 1024 / 1024,
                'status': 'running'
            }
        except psutil.NoSuchProcess:
            service_stats[service] = {'status': 'not_running'}
    
    return service_stats
```

## Scalability Considerations

### Current Limitations
- **Single Server**: All services run on one server
- **Single User**: Designed for single user operation
- **Local Database**: PostgreSQL runs locally
- **Limited Concurrency**: Optimized for single-user access

### Scaling Options

#### Vertical Scaling
- **CPU Upgrade**: Add more CPU cores
- **Memory Upgrade**: Increase RAM capacity
- **Storage Upgrade**: Add SSD storage
- **Network Upgrade**: Increase bandwidth

#### Horizontal Scaling (Future v3)
- **Load Balancer**: Distribute traffic across servers
- **Database Clustering**: PostgreSQL clustering
- **Redis Integration**: Centralized caching
- **Microservices**: Service decomposition

## Resource Constraints

### Hardware Requirements
| Component | Minimum | Recommended | Current |
|-----------|---------|-------------|---------|
| CPU | 2 cores | 4 cores | 4 cores |
| RAM | 4GB | 8GB | 8GB |
| Storage | 20GB SSD | 100GB SSD | 100GB SSD |
| Network | 10Mbps | 100Mbps | 100Mbps |

### Performance Bottlenecks
1. **Database I/O**: PostgreSQL disk operations
2. **Network Latency**: API calls to external services
3. **Memory Usage**: Python process memory
4. **CPU Spikes**: Real-time data processing

## Optimization Strategies

### Database Optimization
```sql
-- Query optimization
EXPLAIN ANALYZE SELECT * FROM users.trades_0001 WHERE status = 'open';

-- Index optimization
CREATE INDEX CONCURRENTLY idx_trades_status ON users.trades_0001(status);

-- Vacuum and analyze
VACUUM ANALYZE users.trades_0001;
```

### Application Optimization
```python
# Connection pooling
from psycopg2.pool import SimpleConnectionPool
pool = SimpleConnectionPool(5, 20, database="rec_io_db")

# Caching
import functools
@functools.lru_cache(maxsize=128)
def get_cached_data(key):
    return expensive_operation(key)
```

### System Optimization
```bash
# Process priority
renice -n -10 -p $(pgrep -f "trade_manager")

# Memory limits
ulimit -v 1048576  # 1GB virtual memory limit

# File descriptor limits
ulimit -n 4096  # 4096 open files
```

## Monitoring and Alerting

### Resource Thresholds
| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| CPU Usage | 80% | 95% | Scale up |
| Memory Usage | 85% | 95% | Add RAM |
| Disk Usage | 80% | 90% | Clean up |
| Network Latency | 100ms | 500ms | Check connection |

### Alerting Configuration
```python
def check_resource_thresholds():
    """Check resource usage against thresholds"""
    resources = monitor_system_resources()
    
    alerts = []
    if resources['cpu_percent'] > 80:
        alerts.append('High CPU usage')
    if resources['memory_percent'] > 85:
        alerts.append('High memory usage')
    if resources['disk_percent'] > 80:
        alerts.append('High disk usage')
    
    return alerts
```

## Backup and Recovery

### Backup Strategy
```bash
# Database backup
pg_dump rec_io_db > backup_$(date +%Y%m%d).sql

# File backup
tar -czf data_backup_$(date +%Y%m%d).tar.gz backend/data/

# Configuration backup
cp -r backend/core/config/ config_backup_$(date +%Y%m%d)/
```

### Recovery Procedures
```bash
# Database recovery
psql rec_io_db < backup_20250127.sql

# File recovery
tar -xzf data_backup_20250127.tar.gz

# Service restart
supervisorctl restart all
```

## Future Resource Planning

### v3 Resource Requirements
- **Redis Server**: 512MB RAM
- **Load Balancer**: 256MB RAM
- **Additional Services**: 1GB RAM
- **Monitoring Stack**: 512MB RAM

### Cloud Deployment Considerations
- **Digital Ocean**: 2GB RAM, 1 vCPU minimum
- **AWS EC2**: t3.medium or larger
- **Google Cloud**: e2-medium or larger
- **Azure**: Standard_B2s or larger

### Scaling Roadmap
1. **Phase 1**: Optimize current resources
2. **Phase 2**: Add Redis caching layer
3. **Phase 3**: Implement load balancing
4. **Phase 4**: Deploy to cloud infrastructure

## Conclusion

The current resource allocation is optimized for single-user operation with real-time trading capabilities. The system efficiently utilizes available resources while maintaining performance and reliability. Future scaling will require additional infrastructure and architectural changes as outlined in the v3 development plan.
