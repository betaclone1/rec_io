# Redis Message Contracts

## Overview
This document defines the message contracts for Redis pub/sub integration planned for REC.IO v3. These contracts establish the standardized message formats, topics, and schemas for inter-service communication.

## Message Topics

### Market Data Topics
```
market_data:btc_price
market_data:kalshi_events
market_data:strike_updates
market_data:position_changes
```

### Trade Execution Topics
```
trades:new_order
trades:order_filled
trades:order_cancelled
trades:position_update
trades:pnl_update
```

### System Health Topics
```
system:health_check
system:service_status
system:error_alert
system:performance_metrics
```

### User Session Topics
```
user:login
user:logout
user:session_update
user:preferences_change
```

## Message Schemas

### Market Data Messages

#### BTC Price Update
```json
{
  "topic": "market_data:btc_price",
  "timestamp": "2025-01-27T10:30:00Z",
  "data": {
    "symbol": "BTC-USD",
    "price": 43250.50,
    "volume": 1250.75,
    "change_24h": 2.5,
    "source": "coinbase_api"
  },
  "metadata": {
    "sequence_id": 12345,
    "version": "1.0"
  }
}
```

#### Kalshi Event
```json
{
  "topic": "market_data:kalshi_events",
  "timestamp": "2025-01-27T10:30:00Z",
  "data": {
    "event_type": "order_filled",
    "order_id": "ord_123456",
    "market_id": "BTC-2025-01-31",
    "side": "buy",
    "quantity": 10,
    "price": 0.65,
    "fill_time": "2025-01-27T10:29:58Z"
  },
  "metadata": {
    "user_id": "user_0001",
    "session_id": "sess_789"
  }
}
```

### Trade Execution Messages

#### New Order
```json
{
  "topic": "trades:new_order",
  "timestamp": "2025-01-27T10:30:00Z",
  "data": {
    "order_id": "ord_123456",
    "user_id": "user_0001",
    "market_id": "BTC-2025-01-31",
    "side": "buy",
    "quantity": 10,
    "price": 0.65,
    "order_type": "limit",
    "status": "pending"
  },
  "metadata": {
    "source": "frontend",
    "session_id": "sess_789"
  }
}
```

#### Order Filled
```json
{
  "topic": "trades:order_filled",
  "timestamp": "2025-01-27T10:30:05Z",
  "data": {
    "order_id": "ord_123456",
    "fill_id": "fill_789",
    "filled_quantity": 10,
    "filled_price": 0.65,
    "fill_time": "2025-01-27T10:30:03Z",
    "commission": 0.10
  },
  "metadata": {
    "user_id": "user_0001",
    "pnl_impact": 6.50
  }
}
```

### System Health Messages

#### Health Check
```json
{
  "topic": "system:health_check",
  "timestamp": "2025-01-27T10:30:00Z",
  "data": {
    "service": "trade_manager",
    "status": "healthy",
    "uptime": 86400,
    "memory_usage": 512,
    "cpu_usage": 15.5,
    "active_connections": 25
  },
  "metadata": {
    "check_id": "health_123",
    "version": "2.0"
  }
}
```

#### Error Alert
```json
{
  "topic": "system:error_alert",
  "timestamp": "2025-01-27T10:30:00Z",
  "data": {
    "service": "kalshi_api",
    "error_type": "connection_timeout",
    "error_message": "Failed to connect to Kalshi API",
    "severity": "high",
    "retry_count": 3
  },
  "metadata": {
    "alert_id": "alert_456",
    "escalation_level": 2
  }
}
```

## Message Routing

### Publisher Responsibilities
- Validate message schema before publishing
- Include required metadata fields
- Use appropriate topic naming conventions
- Handle publishing failures gracefully
- Implement retry logic for critical messages

### Subscriber Responsibilities
- Subscribe to relevant topics only
- Validate incoming message schemas
- Handle message processing failures
- Implement dead letter queues for failed messages
- Monitor message processing latency

## Error Handling

### Message Validation Errors
```json
{
  "error_type": "validation_error",
  "message": "Invalid message schema",
  "details": {
    "missing_fields": ["timestamp", "data"],
    "invalid_fields": ["price": "must be numeric"]
  }
}
```

### Processing Errors
```json
{
  "error_type": "processing_error",
  "service": "trade_executor",
  "message": "Failed to execute trade",
  "original_message": {...},
  "retry_count": 2
}
```

## Performance Considerations

### Message Size Limits
- Maximum message size: 1MB
- Recommended message size: < 10KB
- Large data should be stored in database, referenced by ID

### Rate Limiting
- Maximum messages per second per service: 1000
- Burst allowance: 2000 messages
- Throttling applied per service and topic

### Message TTL
- Market data messages: 5 minutes
- Trade messages: 1 hour
- System messages: 24 hours
- User session messages: 30 minutes

## Monitoring and Alerting

### Metrics to Track
- Message publish rate per topic
- Message processing latency
- Error rates by topic and service
- Queue depth and backlog
- Memory usage per service

### Alert Thresholds
- Error rate > 5% for any topic
- Processing latency > 100ms
- Queue depth > 1000 messages
- Service unresponsive for > 30 seconds

## Security Considerations

### Message Encryption
- All messages encrypted in transit
- Sensitive data encrypted at rest
- API keys and credentials never in messages

### Access Control
- Service-specific topic subscriptions
- Message signing for critical operations
- Rate limiting per service and user

### Audit Trail
- All messages logged with timestamps
- User actions traceable through session IDs
- Failed message processing logged

## Implementation Guidelines

### Service Integration
1. Add Redis client to each service
2. Implement message publisher interface
3. Add message subscriber handlers
4. Configure topic subscriptions
5. Add error handling and retry logic

### Testing Strategy
1. Unit tests for message schemas
2. Integration tests for pub/sub flow
3. Load tests for message throughput
4. Failure scenario testing
5. Performance benchmarking

### Migration Plan
1. Deploy Redis infrastructure
2. Implement message contracts
3. Add pub/sub to non-critical services first
4. Gradually migrate critical services
5. Monitor and optimize performance

This comprehensive Redis message contract document provides the foundation for implementing reliable, scalable inter-service communication in REC.IO v3.
