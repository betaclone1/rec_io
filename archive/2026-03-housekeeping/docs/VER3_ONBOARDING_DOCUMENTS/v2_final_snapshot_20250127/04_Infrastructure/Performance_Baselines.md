# Performance Baselines and Monitoring

## Overview
This document establishes performance baselines for the REC.IO trading system, including current v2 metrics, v3 performance targets, monitoring tools, and alert thresholds.

**Last Updated**: 2025-01-27  
**Current Version**: v2.0  
**Target Version**: v3.0

---

## Current v2 Performance Metrics

### 1. Response Time Metrics

#### API Response Times
```json
{
  "current_metrics": {
    "main_app": {
      "average_response_time": "45ms",
      "p95_response_time": "120ms",
      "p99_response_time": "250ms",
      "max_response_time": "500ms"
    },
    "trade_manager": {
      "average_response_time": "25ms",
      "p95_response_time": "80ms",
      "p99_response_time": "150ms",
      "max_response_time": "300ms"
    },
    "trade_executor": {
      "average_response_time": "150ms",
      "p95_response_time": "300ms",
      "p99_response_time": "500ms",
      "max_response_time": "1000ms"
    },
    "kalshi_api": {
      "average_response_time": "200ms",
      "p95_response_time": "400ms",
      "p99_response_time": "800ms",
      "max_response_time": "2000ms"
    },
    "coinbase_api": {
      "average_response_time": "100ms",
      "p95_response_time": "250ms",
      "p99_response_time": "500ms",
      "max_response_time": "1000ms"
    }
  }
}
```

#### WebSocket Performance
```json
{
  "websocket_metrics": {
    "connection_latency": "15ms",
    "message_delivery_time": "5ms",
    "reconnection_time": "200ms",
    "active_connections": 5,
    "messages_per_second": 50
  }
}
```

### 2. Database Performance

#### PostgreSQL Query Performance
```sql
-- Current database performance metrics
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size,
    pg_stat_get_tuples_returned(c.oid) as rows_returned,
    pg_stat_get_tuples_fetched(c.oid) as rows_fetched
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE schemaname IN ('users', 'live_data', 'historical_data')
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

#### Query Performance Metrics
```json
{
  "database_metrics": {
    "average_query_time": "12ms",
    "slow_queries_per_minute": 2,
    "active_connections": 8,
    "max_connections": 100,
    "cache_hit_ratio": "85%",
    "database_size": "2.3GB",
    "index_usage": "92%"
  }
}
```

### 3. System Resource Usage

#### CPU and Memory Usage
```json
{
  "system_metrics": {
    "cpu_usage": {
      "average": "35%",
      "peak": "65%",
      "idle": "65%"
    },
    "memory_usage": {
      "total": "4GB",
      "used": "2.8GB",
      "available": "1.2GB",
      "usage_percentage": "70%"
    },
    "disk_usage": {
      "total": "80GB",
      "used": "45GB",
      "available": "35GB",
      "usage_percentage": "56%"
    },
    "network_io": {
      "bytes_sent": "15MB/s",
      "bytes_received": "8MB/s",
      "packets_sent": "1200/s",
      "packets_received": "800/s"
    }
  }
}
```

#### Process-Specific Resource Usage
```json
{
  "process_metrics": {
    "main_app": {
      "cpu_percent": "8%",
      "memory_mb": "150MB",
      "threads": 4
    },
    "trade_manager": {
      "cpu_percent": "12%",
      "memory_mb": "200MB",
      "threads": 3
    },
    "trade_executor": {
      "cpu_percent": "5%",
      "memory_mb": "100MB",
      "threads": 2
    },
    "active_trade_supervisor": {
      "cpu_percent": "6%",
      "memory_mb": "120MB",
      "threads": 2
    },
    "btc_price_watchdog": {
      "cpu_percent": "3%",
      "memory_mb": "80MB",
      "threads": 1
    }
  }
}
```

### 4. Trading Performance Metrics

#### Trade Execution Performance
```json
{
  "trading_metrics": {
    "order_execution_time": {
      "average": "180ms",
      "p95": "350ms",
      "p99": "600ms"
    },
    "order_success_rate": "98.5%",
    "order_failure_rate": "1.5%",
    "orders_per_minute": 2,
    "active_positions": 3,
    "daily_trade_volume": 15
  }
}
```

#### Market Data Performance
```json
{
  "market_data_metrics": {
    "price_update_frequency": "1 update/second",
    "price_update_latency": "50ms",
    "data_accuracy": "99.9%",
    "market_data_sources": 2,
    "historical_data_points": "50,000"
  }
}
```

---

## v3 Performance Targets

### 1. Response Time Targets

#### API Response Time Targets
```json
{
  "v3_targets": {
    "main_app": {
      "target_response_time": "<10ms",
      "p95_target": "<25ms",
      "p99_target": "<50ms"
    },
    "trade_manager": {
      "target_response_time": "<5ms",
      "p95_target": "<15ms",
      "p99_target": "<30ms"
    },
    "trade_executor": {
      "target_response_time": "<50ms",
      "p95_target": "<100ms",
      "p99_target": "<200ms"
    },
    "kalshi_api": {
      "target_response_time": "<100ms",
      "p95_target": "<200ms",
      "p99_target": "<400ms"
    },
    "coinbase_api": {
      "target_response_time": "<50ms",
      "p95_target": "<100ms",
      "p99_target": "<200ms"
    }
  }
}
```

#### WebSocket Performance Targets
```json
{
  "websocket_targets": {
    "connection_latency": "<5ms",
    "message_delivery_time": "<1ms",
    "reconnection_time": "<50ms",
    "active_connections": 100,
    "messages_per_second": 1000
  }
}
```

### 2. Database Performance Targets

#### PostgreSQL Optimization Targets
```json
{
  "database_targets": {
    "average_query_time": "<5ms",
    "slow_queries_per_minute": 0,
    "cache_hit_ratio": ">95%",
    "index_usage": ">98%",
    "connection_pool_efficiency": ">90%"
  }
}
```

#### Redis Integration Targets
```json
{
  "redis_targets": {
    "cache_hit_ratio": ">90%",
    "average_response_time": "<1ms",
    "memory_usage": "<2GB",
    "key_expiration_rate": ">80%"
  }
}
```

### 3. System Resource Targets

#### Resource Optimization Targets
```json
{
  "resource_targets": {
    "cpu_usage": {
      "average": "<25%",
      "peak": "<50%"
    },
    "memory_usage": {
      "usage_percentage": "<60%",
      "swap_usage": "<5%"
    },
    "disk_usage": {
      "usage_percentage": "<70%",
      "iops": ">1000"
    },
    "network_io": {
      "latency": "<10ms",
      "throughput": ">100MB/s"
    }
  }
}
```

### 4. Trading Performance Targets

#### Enhanced Trading Targets
```json
{
  "trading_targets": {
    "order_execution_time": {
      "target": "<50ms",
      "p95_target": "<100ms",
      "p99_target": "<200ms"
    },
    "order_success_rate": ">99.5%",
    "orders_per_minute": 10,
    "active_positions": 20,
    "daily_trade_volume": 100
  }
}
```

---

## Monitoring Tools and Setup

### 1. Application Performance Monitoring

#### Prometheus Configuration
```yaml
# prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - "rec_io_rules.yml"

scrape_configs:
  - job_name: 'rec-io-app'
    static_configs:
      - targets: ['localhost:3000']
    metrics_path: '/metrics'
    scrape_interval: 5s

  - job_name: 'postgresql'
    static_configs:
      - targets: ['localhost:9187']
    scrape_interval: 10s

  - job_name: 'redis'
    static_configs:
      - targets: ['localhost:9121']
    scrape_interval: 5s
```

#### Custom Metrics Collection
```python
# metrics_collector.py
from prometheus_client import Counter, Histogram, Gauge
import time
import psutil

# Define metrics
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint'])
REQUEST_DURATION = Histogram('http_request_duration_seconds', 'HTTP request duration')
ACTIVE_CONNECTIONS = Gauge('websocket_active_connections', 'Active WebSocket connections')
TRADE_EXECUTION_TIME = Histogram('trade_execution_duration_seconds', 'Trade execution time')
DATABASE_QUERY_TIME = Histogram('database_query_duration_seconds', 'Database query time')

def collect_system_metrics():
    """Collect system-level metrics"""
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    SYSTEM_CPU.set(cpu_percent)
    SYSTEM_MEMORY.set(memory.percent)
    SYSTEM_DISK.set(disk.percent)

def collect_application_metrics():
    """Collect application-specific metrics"""
    # Trade execution metrics
    TRADE_EXECUTION_TIME.observe(execution_time)
    
    # Database query metrics
    DATABASE_QUERY_TIME.observe(query_time)
    
    # WebSocket connection metrics
    ACTIVE_CONNECTIONS.set(connection_count)
```

### 2. Database Monitoring

#### PostgreSQL Monitoring
```sql
-- Performance monitoring queries
-- Active connections
SELECT count(*) as active_connections 
FROM pg_stat_activity 
WHERE state = 'active';

-- Slow queries
SELECT query, mean_time, calls 
FROM pg_stat_statements 
ORDER BY mean_time DESC 
LIMIT 10;

-- Table sizes
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
FROM pg_tables 
WHERE schemaname IN ('users', 'live_data', 'historical_data')
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- Cache hit ratio
SELECT 
    sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read)) as cache_hit_ratio
FROM pg_statio_user_tables;
```

#### Redis Monitoring (v3)
```python
# redis_monitor.py
import redis
import time
from prometheus_client import Gauge, Counter

# Redis metrics
REDIS_MEMORY_USAGE = Gauge('redis_memory_bytes', 'Redis memory usage in bytes')
REDIS_CONNECTED_CLIENTS = Gauge('redis_connected_clients', 'Number of connected clients')
REDIS_COMMANDS_PROCESSED = Counter('redis_commands_total', 'Total commands processed')
REDIS_KEYS_EXPIRED = Counter('redis_keys_expired_total', 'Total keys expired')

def monitor_redis():
    """Monitor Redis performance"""
    r = redis.Redis(host='localhost', port=6379, db=0)
    
    # Get Redis info
    info = r.info()
    
    # Update metrics
    REDIS_MEMORY_USAGE.set(info['used_memory'])
    REDIS_CONNECTED_CLIENTS.set(info['connected_clients'])
    REDIS_COMMANDS_PROCESSED.inc(info['total_commands_processed'])
    REDIS_KEYS_EXPIRED.inc(info['expired_keys'])
```

### 3. System Resource Monitoring

#### System Metrics Collection
```python
# system_monitor.py
import psutil
import time
from prometheus_client import Gauge

# System metrics
SYSTEM_CPU = Gauge('system_cpu_percent', 'CPU usage percentage')
SYSTEM_MEMORY = Gauge('system_memory_percent', 'Memory usage percentage')
SYSTEM_DISK = Gauge('system_disk_percent', 'Disk usage percentage')
SYSTEM_NETWORK_IO = Gauge('system_network_io_bytes', 'Network I/O in bytes')

def collect_system_metrics():
    """Collect system resource metrics"""
    # CPU usage
    cpu_percent = psutil.cpu_percent(interval=1)
    SYSTEM_CPU.set(cpu_percent)
    
    # Memory usage
    memory = psutil.virtual_memory()
    SYSTEM_MEMORY.set(memory.percent)
    
    # Disk usage
    disk = psutil.disk_usage('/')
    SYSTEM_DISK.set(disk.percent)
    
    # Network I/O
    network = psutil.net_io_counters()
    SYSTEM_NETWORK_IO.set(network.bytes_sent + network.bytes_recv)

# Run monitoring loop
while True:
    collect_system_metrics()
    time.sleep(15)
```

### 4. Trading Performance Monitoring

#### Trade Execution Monitoring
```python
# trade_monitor.py
from prometheus_client import Histogram, Counter, Gauge
import time

# Trading metrics
TRADE_EXECUTION_TIME = Histogram('trade_execution_duration_seconds', 'Trade execution time')
TRADE_SUCCESS_COUNTER = Counter('trades_successful_total', 'Successful trades')
TRADE_FAILURE_COUNTER = Counter('trades_failed_total', 'Failed trades')
ACTIVE_POSITIONS = Gauge('active_positions', 'Number of active positions')

def monitor_trade_execution():
    """Monitor trade execution performance"""
    start_time = time.time()
    
    try:
        # Execute trade
        result = execute_trade(order)
        
        # Record metrics
        execution_time = time.time() - start_time
        TRADE_EXECUTION_TIME.observe(execution_time)
        
        if result.success:
            TRADE_SUCCESS_COUNTER.inc()
        else:
            TRADE_FAILURE_COUNTER.inc()
            
    except Exception as e:
        TRADE_FAILURE_COUNTER.inc()
        raise e
```

---

## Alert Thresholds and Configuration

### 1. Critical Alert Thresholds

#### Performance Alerts
```yaml
# alerting_rules.yml
groups:
  - name: rec_io_performance
    rules:
      - alert: HighResponseTime
        expr: http_request_duration_seconds{quantile="0.95"} > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High response time detected"
          description: "95th percentile response time is {{ $value }}s"

      - alert: HighCPUUsage
        expr: system_cpu_percent > 80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High CPU usage"
          description: "CPU usage is {{ $value }}%"

      - alert: HighMemoryUsage
        expr: system_memory_percent > 85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High memory usage"
          description: "Memory usage is {{ $value }}%"

      - alert: DatabaseSlowQueries
        expr: database_query_duration_seconds{quantile="0.95"} > 0.1
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Slow database queries detected"
          description: "95th percentile query time is {{ $value }}s"

      - alert: TradeExecutionFailure
        expr: rate(trades_failed_total[5m]) > 0.1
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "High trade failure rate"
          description: "Trade failure rate is {{ $value }} per second"
```

#### Service Health Alerts
```yaml
      - alert: ServiceDown
        expr: up == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Service is down"
          description: "Service {{ $labels.job }} is down"

      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High error rate"
          description: "Error rate is {{ $value }}%"
```

### 2. Warning Alert Thresholds

#### Resource Usage Warnings
```yaml
      - alert: DiskSpaceWarning
        expr: system_disk_percent > 70
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Disk space usage high"
          description: "Disk usage is {{ $value }}%"

      - alert: NetworkLatencyWarning
        expr: http_request_duration_seconds{quantile="0.95"} > 0.2
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Network latency high"
          description: "95th percentile latency is {{ $value }}s"
```

### 3. Alert Notification Configuration

#### Alert Manager Configuration
```yaml
# alertmanager.yml
global:
  smtp_smarthost: 'localhost:587'
  smtp_from: 'alerts@rec.io'

route:
  group_by: ['alertname']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 1h
  receiver: 'team-rec-io'

receivers:
  - name: 'team-rec-io'
    email_configs:
      - to: 'team@rec.io'
        send_resolved: true
    webhook_configs:
      - url: 'https://hooks.slack.com/services/YOUR_SLACK_WEBHOOK'
        send_resolved: true
```

---

## Performance Testing

### 1. Load Testing

#### API Load Testing
```python
# load_test.py
import requests
import time
import threading
from concurrent.futures import ThreadPoolExecutor

def api_load_test():
    """Load test the main API endpoints"""
    base_url = "https://your-domain.com"
    endpoints = [
        "/health",
        "/api/trades",
        "/api/positions",
        "/api/market-data"
    ]
    
    def make_request(endpoint):
        start_time = time.time()
        try:
            response = requests.get(f"{base_url}{endpoint}", timeout=10)
            duration = time.time() - start_time
            return {
                'endpoint': endpoint,
                'status_code': response.status_code,
                'duration': duration,
                'success': response.status_code == 200
            }
        except Exception as e:
            return {
                'endpoint': endpoint,
                'status_code': 0,
                'duration': time.time() - start_time,
                'success': False,
                'error': str(e)
            }
    
    # Run load test with 100 concurrent users
    with ThreadPoolExecutor(max_workers=100) as executor:
        results = list(executor.map(make_request, endpoints * 25))
    
    return results
```

#### Database Load Testing
```python
# db_load_test.py
import psycopg2
import time
import threading
from concurrent.futures import ThreadPoolExecutor

def database_load_test():
    """Load test the database"""
    def execute_query():
        start_time = time.time()
        try:
            conn = psycopg2.connect(
                host="localhost",
                database="rec_io_db",
                user="rec_io_user",
                password="rec_io_password"
            )
            cursor = conn.cursor()
            
            # Execute various queries
            cursor.execute("SELECT COUNT(*) FROM users.trades_0001")
            cursor.execute("SELECT * FROM users.trades_0001 ORDER BY id DESC LIMIT 10")
            cursor.execute("SELECT * FROM live_data.btc_price_log ORDER BY timestamp DESC LIMIT 100")
            
            duration = time.time() - start_time
            conn.close()
            
            return {
                'duration': duration,
                'success': True
            }
        except Exception as e:
            return {
                'duration': time.time() - start_time,
                'success': False,
                'error': str(e)
            }
    
    # Run 50 concurrent database connections
    with ThreadPoolExecutor(max_workers=50) as executor:
        results = list(executor.map(lambda x: execute_query(), range(100)))
    
    return results
```

### 2. Stress Testing

#### System Stress Test
```python
# stress_test.py
import psutil
import time
import threading

def stress_test():
    """Stress test the system"""
    def cpu_stress():
        """Generate CPU load"""
        while True:
            _ = sum(i * i for i in range(1000))
    
    def memory_stress():
        """Generate memory load"""
        data = []
        while True:
            data.append([0] * 1000000)
            if len(data) > 100:
                data.pop(0)
    
    # Start stress threads
    cpu_threads = [threading.Thread(target=cpu_stress) for _ in range(4)]
    memory_threads = [threading.Thread(target=memory_stress) for _ in range(2)]
    
    for thread in cpu_threads + memory_threads:
        thread.daemon = True
        thread.start()
    
    # Monitor system during stress test
    start_time = time.time()
    while time.time() - start_time < 300:  # 5 minutes
        cpu_percent = psutil.cpu_percent(interval=1)
        memory_percent = psutil.virtual_memory().percent
        
        print(f"CPU: {cpu_percent}%, Memory: {memory_percent}%")
        time.sleep(5)
```

---

## Performance Optimization Strategies

### 1. Application-Level Optimization

#### Code Optimization
```python
# performance_optimizations.py

# 1. Connection pooling
from psycopg2.pool import SimpleConnectionPool
pool = SimpleConnectionPool(1, 20, 
    host="localhost",
    database="rec_io_db",
    user="rec_io_user",
    password="rec_io_password"
)

# 2. Caching
from functools import lru_cache
@lru_cache(maxsize=1000)
def get_cached_data(key):
    return expensive_operation(key)

# 3. Async operations
import asyncio
async def async_trade_execution(order):
    # Execute trade asynchronously
    result = await execute_trade_async(order)
    return result

# 4. Batch processing
def batch_process_trades(trades):
    # Process multiple trades in a single database transaction
    with pool.getconn() as conn:
        with conn.cursor() as cursor:
            for trade in trades:
                cursor.execute("INSERT INTO users.trades_0001 (...) VALUES (...)", trade)
        conn.commit()
```

### 2. Database Optimization

#### Query Optimization
```sql
-- Create indexes for frequently queried columns
CREATE INDEX idx_trades_user_id ON users.trades_0001(user_id);
CREATE INDEX idx_trades_status ON users.trades_0001(status);
CREATE INDEX idx_trades_timestamp ON users.trades_0001(timestamp);
CREATE INDEX idx_btc_price_timestamp ON live_data.btc_price_log(timestamp);

-- Partition large tables
CREATE TABLE users.trades_0001_partitioned (
    LIKE users.trades_0001 INCLUDING ALL
) PARTITION BY RANGE (timestamp);

-- Create partitions by month
CREATE TABLE users.trades_0001_2024_01 PARTITION OF users.trades_0001_partitioned
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
```

#### Redis Caching Strategy
```python
# redis_caching.py
import redis
import json

class RedisCache:
    def __init__(self):
        self.redis = redis.Redis(host='localhost', port=6379, db=0)
    
    def cache_market_data(self, symbol, data, ttl=60):
        """Cache market data with TTL"""
        key = f"market_data:{symbol}"
        self.redis.setex(key, ttl, json.dumps(data))
    
    def get_cached_market_data(self, symbol):
        """Get cached market data"""
        key = f"market_data:{symbol}"
        data = self.redis.get(key)
        return json.loads(data) if data else None
    
    def cache_user_positions(self, user_id, positions, ttl=300):
        """Cache user positions"""
        key = f"user_positions:{user_id}"
        self.redis.setex(key, ttl, json.dumps(positions))
```

### 3. Infrastructure Optimization

#### Nginx Optimization
```nginx
# nginx.conf optimizations
worker_processes auto;
worker_connections 1024;

# Enable gzip compression
gzip on;
gzip_vary on;
gzip_min_length 1024;
gzip_types text/plain text/css application/json application/javascript;

# Enable caching
location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {
    expires 1y;
    add_header Cache-Control "public, immutable";
}

# Proxy buffering
proxy_buffering on;
proxy_buffer_size 4k;
proxy_buffers 8 4k;
```

#### PostgreSQL Optimization
```sql
-- PostgreSQL performance tuning
-- Increase shared buffers for better caching
ALTER SYSTEM SET shared_buffers = '1GB';

-- Optimize work memory
ALTER SYSTEM SET work_mem = '16MB';

-- Enable query plan caching
ALTER SYSTEM SET plan_cache_mode = 'auto';

-- Optimize autovacuum
ALTER SYSTEM SET autovacuum_vacuum_scale_factor = 0.1;
ALTER SYSTEM SET autovacuum_analyze_scale_factor = 0.05;
```

---

## Performance Reporting

### 1. Daily Performance Report

#### Automated Performance Report
```python
# performance_report.py
import json
import datetime
from prometheus_api_client import PrometheusConnect

def generate_daily_report():
    """Generate daily performance report"""
    prom = PrometheusConnect(url="http://localhost:9090")
    
    # Get metrics for the last 24 hours
    end_time = datetime.datetime.now()
    start_time = end_time - datetime.timedelta(days=1)
    
    # Collect metrics
    response_time = prom.get_metric_range_data(
        metric_name='http_request_duration_seconds',
        start_time=start_time,
        end_time=end_time
    )
    
    cpu_usage = prom.get_metric_range_data(
        metric_name='system_cpu_percent',
        start_time=start_time,
        end_time=end_time
    )
    
    # Generate report
    report = {
        'date': end_time.strftime('%Y-%m-%d'),
        'response_time_avg': calculate_average(response_time),
        'response_time_p95': calculate_percentile(response_time, 95),
        'cpu_usage_avg': calculate_average(cpu_usage),
        'cpu_usage_peak': calculate_peak(cpu_usage),
        'alerts_triggered': get_alert_count(start_time, end_time),
        'recommendations': generate_recommendations()
    }
    
    return report
```

### 2. Weekly Performance Summary

#### Weekly Metrics Summary
```python
def generate_weekly_summary():
    """Generate weekly performance summary"""
    # Collect daily reports for the week
    daily_reports = []
    for i in range(7):
        date = datetime.datetime.now() - datetime.timedelta(days=i)
        report = generate_daily_report_for_date(date)
        daily_reports.append(report)
    
    # Calculate weekly averages
    weekly_summary = {
        'period': 'weekly',
        'start_date': (datetime.datetime.now() - datetime.timedelta(days=7)).strftime('%Y-%m-%d'),
        'end_date': datetime.datetime.now().strftime('%Y-%m-%d'),
        'avg_response_time': calculate_weekly_average(daily_reports, 'response_time_avg'),
        'avg_cpu_usage': calculate_weekly_average(daily_reports, 'cpu_usage_avg'),
        'peak_cpu_usage': max([r['cpu_usage_peak'] for r in daily_reports]),
        'total_alerts': sum([r['alerts_triggered'] for r in daily_reports]),
        'performance_trend': analyze_performance_trend(daily_reports)
    }
    
    return weekly_summary
```

---

This comprehensive performance baselines document provides detailed metrics, targets, monitoring setup, and optimization strategies for the REC.IO trading system, ensuring optimal performance from v2 to v3.
