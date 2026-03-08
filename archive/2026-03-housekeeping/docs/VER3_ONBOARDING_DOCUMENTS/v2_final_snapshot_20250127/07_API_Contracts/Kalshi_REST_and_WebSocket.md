# Kalshi REST and WebSocket API Contract Reference

## Overview
This document provides the complete API contract for Kalshi integration, including REST endpoints, WebSocket connections, authentication patterns, error handling, and retry logic.

**Last Verified**: 2025-01-27  
**API Version**: v2  
**Base URL**: https://api.elections.kalshi.com/trade-api/v2

---

## Authentication

### API Key Authentication
```python
# Authentication header format
headers = {
    'Authorization': f'Bearer {api_key}',
    'Content-Type': 'application/json'
}
```

### Credential Storage
- **Location**: `backend/data/users/{user_id}/credentials/kalshi-credentials`
- **Format**: JSON file with API key and secret
- **Security**: File permissions restricted to user only

### Authentication Flow
1. Load credentials from user-specific directory
2. Validate API key format
3. Include in all REST API requests
4. WebSocket authentication handled separately

---

## REST API Endpoints

### 1. Account Information

#### Get Account Balance
```http
GET /accounts/{account_id}
```

**Response Example**:
```json
{
  "account": {
    "account_id": "user_0001",
    "balance": 10000,
    "currency": "USD",
    "status": "active"
  }
}
```

**Error Codes**:
- `401`: Invalid API key
- `403`: Insufficient permissions
- `404`: Account not found
- `500`: Internal server error

#### Get Positions
```http
GET /accounts/{account_id}/positions
```

**Response Example**:
```json
{
  "positions": [
    {
      "ticker": "BTC-2024-12-31",
      "position": 100,
      "avg_price": 0.65,
      "unrealized_pnl": 150
    }
  ]
}
```

### 2. Market Data

#### Get Markets
```http
GET /markets
```

**Query Parameters**:
- `status`: active, closed, settled
- `limit`: Number of markets to return
- `offset`: Pagination offset

**Response Example**:
```json
{
  "markets": [
    {
      "ticker": "BTC-2024-12-31",
      "title": "Will Bitcoin close above $50,000 on December 31, 2024?",
      "status": "active",
      "last_price": 0.65,
      "volume": 1000000
    }
  ]
}
```

#### Get Market Details
```http
GET /markets/{ticker}
```

**Response Example**:
```json
{
  "market": {
    "ticker": "BTC-2024-12-31",
    "title": "Will Bitcoin close above $50,000 on December 31, 2024?",
    "description": "This market will resolve to YES if Bitcoin closes above $50,000 on December 31, 2024.",
    "status": "active",
    "last_price": 0.65,
    "volume": 1000000,
    "open_interest": 500000,
    "expiration_date": "2024-12-31T23:59:59Z"
  }
}
```

### 3. Order Management

#### Place Order
```http
POST /orders
```

**Request Body**:
```json
{
  "ticker": "BTC-2024-12-31",
  "side": "buy",
  "type": "limit",
  "size": 100,
  "price": 0.65,
  "time_in_force": "gtc"
}
```

**Response Example**:
```json
{
  "order": {
    "order_id": "ord_123456789",
    "ticker": "BTC-2024-12-31",
    "side": "buy",
    "type": "limit",
    "size": 100,
    "price": 0.65,
    "filled_size": 0,
    "status": "open",
    "created_at": "2024-01-27T10:30:00Z"
  }
}
```

**Error Codes**:
- `400`: Invalid order parameters
- `401`: Authentication required
- `403`: Insufficient balance
- `404`: Market not found
- `429`: Rate limit exceeded

#### Cancel Order
```http
DELETE /orders/{order_id}
```

**Response Example**:
```json
{
  "order": {
    "order_id": "ord_123456789",
    "status": "cancelled",
    "cancelled_at": "2024-01-27T10:35:00Z"
  }
}
```

#### Get Order Status
```http
GET /orders/{order_id}
```

**Response Example**:
```json
{
  "order": {
    "order_id": "ord_123456789",
    "ticker": "BTC-2024-12-31",
    "side": "buy",
    "type": "limit",
    "size": 100,
    "price": 0.65,
    "filled_size": 50,
    "status": "partially_filled",
    "fills": [
      {
        "fill_id": "fill_123",
        "size": 50,
        "price": 0.65,
        "filled_at": "2024-01-27T10:32:00Z"
      }
    ]
  }
}
```

### 4. Trade History

#### Get Fills
```http
GET /fills
```

**Query Parameters**:
- `ticker`: Filter by market ticker
- `limit`: Number of fills to return
- `offset`: Pagination offset

**Response Example**:
```json
{
  "fills": [
    {
      "fill_id": "fill_123",
      "order_id": "ord_123456789",
      "ticker": "BTC-2024-12-31",
      "side": "buy",
      "size": 50,
      "price": 0.65,
      "filled_at": "2024-01-27T10:32:00Z"
    }
  ]
}
```

---

## WebSocket API

### Connection
```python
# WebSocket connection URL
ws_url = "wss://trading-api.kalshi.com/ws/v2"
```

### Authentication
```python
# WebSocket authentication message
auth_message = {
    "type": "auth",
    "api_key": "your_api_key"
}
```

### Subscription Messages

#### Subscribe to Account Updates
```json
{
  "type": "subscribe",
  "channel": "account",
  "account_id": "user_0001"
}
```

#### Subscribe to Market Data
```json
{
  "type": "subscribe",
  "channel": "market",
  "ticker": "BTC-2024-12-31"
}
```

#### Subscribe to Order Updates
```json
{
  "type": "subscribe",
  "channel": "orders",
  "account_id": "user_0001"
}
```

### Message Types

#### Account Update
```json
{
  "type": "account_update",
  "data": {
    "account_id": "user_0001",
    "balance": 10000,
    "currency": "USD"
  }
}
```

#### Market Update
```json
{
  "type": "market_update",
  "data": {
    "ticker": "BTC-2024-12-31",
    "last_price": 0.65,
    "volume": 1000000,
    "timestamp": "2024-01-27T10:30:00Z"
  }
}
```

#### Order Update
```json
{
  "type": "order_update",
  "data": {
    "order_id": "ord_123456789",
    "status": "filled",
    "filled_size": 100,
    "timestamp": "2024-01-27T10:32:00Z"
  }
}
```

---

## Error Handling

### HTTP Status Codes
- `200`: Success
- `400`: Bad Request - Invalid parameters
- `401`: Unauthorized - Invalid API key
- `403`: Forbidden - Insufficient permissions
- `404`: Not Found - Resource doesn't exist
- `429`: Too Many Requests - Rate limit exceeded
- `500`: Internal Server Error

### Error Response Format
```json
{
  "error": {
    "code": "INVALID_ORDER",
    "message": "Order size must be positive",
    "details": {
      "field": "size",
      "value": -100
    }
  }
}
```

### Common Error Codes
- `INVALID_API_KEY`: Authentication failed
- `INSUFFICIENT_BALANCE`: Not enough funds
- `MARKET_NOT_FOUND`: Invalid ticker
- `ORDER_NOT_FOUND`: Order doesn't exist
- `RATE_LIMIT_EXCEEDED`: Too many requests
- `MARKET_CLOSED`: Market is not active

---

## Retry Logic

### REST API Retry Strategy
```python
def api_request_with_retry(url, headers, data=None, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=data)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                # Rate limit - exponential backoff
                wait_time = 2 ** attempt
                time.sleep(wait_time)
                continue
            elif response.status_code in [400, 401, 403, 404]:
                # Client errors - don't retry
                return response.json()
            else:
                # Server errors - retry with backoff
                wait_time = 2 ** attempt
                time.sleep(wait_time)
                continue
                
        except requests.exceptions.RequestException:
            if attempt == max_retries - 1:
                raise
            wait_time = 2 ** attempt
            time.sleep(wait_time)
    
    raise Exception("Max retries exceeded")
```

### WebSocket Reconnection Strategy
```python
def websocket_reconnect(ws_url, api_key, max_reconnects=5):
    for attempt in range(max_reconnects):
        try:
            ws = websocket.WebSocketApp(
                ws_url,
                on_open=lambda ws: ws.send(json.dumps({
                    "type": "auth",
                    "api_key": api_key
                })),
                on_message=handle_message,
                on_error=handle_error,
                on_close=handle_close
            )
            ws.run_forever()
            
        except Exception as e:
            if attempt == max_reconnects - 1:
                raise
            wait_time = min(30, 2 ** attempt)  # Cap at 30 seconds
            time.sleep(wait_time)
```

---

## Rate Limits

### REST API Limits
- **Requests per minute**: 100
- **Orders per minute**: 10
- **Market data requests**: 1000/minute

### WebSocket Limits
- **Connections per account**: 5
- **Subscriptions per connection**: 100
- **Messages per second**: 100

### Rate Limit Response
```json
{
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "Rate limit exceeded",
    "retry_after": 60
  }
}
```

---

## Testing and Validation

### Test Environment
- **Base URL**: https://demo-api.elections.kalshi.com/trade-api/v2
- **WebSocket**: wss://demo-trading-api.kalshi.com/ws/v2
- **Test API Key**: Available in demo environment

### Validation Checklist
- [ ] API key authentication works
- [ ] Order placement and cancellation
- [ ] Market data retrieval
- [ ] WebSocket connection and subscription
- [ ] Error handling for all scenarios
- [ ] Rate limit handling
- [ ] Retry logic for network failures

---

## Security Considerations

### API Key Security
- Store API keys in user-specific directories only
- Never commit API keys to version control
- Rotate API keys regularly
- Use minimal required permissions

### Network Security
- Use HTTPS for all REST API calls
- Use WSS for WebSocket connections
- Validate SSL certificates
- Implement connection timeouts

### Data Validation
- Validate all input parameters
- Sanitize user inputs
- Check response data integrity
- Log all API interactions

---

## Monitoring and Alerting

### Key Metrics to Monitor
- API response times
- Error rates by endpoint
- Rate limit usage
- WebSocket connection stability
- Order success/failure rates

### Alert Thresholds
- API response time > 5 seconds
- Error rate > 5%
- Rate limit usage > 80%
- WebSocket disconnections > 10/hour

### Logging Requirements
- Log all API requests and responses
- Log WebSocket connection events
- Log authentication failures
- Log rate limit violations
- Log order lifecycle events
